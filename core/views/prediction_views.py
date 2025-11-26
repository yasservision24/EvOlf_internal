import os
import uuid
import csv
import io
import re
import requests
import threading
import time

from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.services.job_scheduler import schedule_job

# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------

PREDICT_DOCKER_URL = getattr(settings, "PREDICT_DOCKER_URL", None)
JOB_DATA_DIR = getattr(settings, "JOB_DATA_DIR", None)
DEBUG_LOG = getattr(settings, "DEBUG_LOG", False)
ENABLE_SCHEDULER = getattr(settings, "ENABLE_SCHEDULER", False)

# Column-name defaults
DEFAULT_LIG_COL = "SMILES"
DEFAULT_REC_COL = "Mutated_Sequence"
DEFAULT_LIG_ID_COL = "Temp_Ligand_ID"
DEFAULT_REC_ID_COL = "TempRecID"
DEFAULT_LR_ID_COL = "ID"


# ----------------------------------------------------------------------
# Utility functions
# ----------------------------------------------------------------------

def _sanitize_identifier(s: str) -> str:
    """Make a safe identifier: keep alpha-numeric, dash, underscore."""
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-z0-9_-]", "", s)
    return s or ""


_SMILES_ALLOWED_RE = re.compile(r'^[A-Za-z0-9@\+\-\[\]\(\)=#\/\\%.:\*]+$')
_RECEPTOR_AA_RE = re.compile(r'^[ACDEFGHIKLMNPQRSTVWYBXZJUO]+$', re.I)


# ----------------------------------------------------------------------
# Main API View
# ----------------------------------------------------------------------

class SmilesPredictionAPIView(APIView):
    """
    POST:
      - smiles (required)
      - sequence (optional)
    Produces a CSV with:
       ID,Temp_Ligand_ID,SMILES,Mutated_Sequence,TempRecID
    Saves CSV to JOB_DATA_DIR/<job_id>/<job_id>.csv
    Submits multipart/form-data to pipeline asynchronously.
    """

    def post(self, request):
        payload = request.data or {}

        # ------------------------------------------------------------------
        #  Reject file uploads
        # ------------------------------------------------------------------
        if request.FILES:
            return Response(
                {"error": "File uploads are not allowed. Send JSON or form fields (no files)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Reject arrays
        if any(isinstance(payload.get(k), (list, tuple)) for k in ("smiles", "sequence", "mutated_sequence")):
            return Response({"error": "Array values are not allowed."}, status=status.HTTP_400_BAD_REQUEST)

        # ------------------------------------------------------------------
        #  Collect Column Names
        # ------------------------------------------------------------------
        lig_col_name = payload.get("lig_smiles_col", DEFAULT_LIG_COL)
        rec_col_name = payload.get("rec_seq_col", DEFAULT_REC_COL)
        lig_id_col_name = payload.get("lig_id_col", DEFAULT_LIG_ID_COL)
        rec_id_col_name = payload.get("rec_id_col", DEFAULT_REC_ID_COL)
        lr_id_col_name = payload.get("lr_id_col", DEFAULT_LR_ID_COL)

        # ------------------------------------------------------------------
        #  Validate SMILES
        # ------------------------------------------------------------------
        smiles = payload.get("smiles")
        if not smiles or not isinstance(smiles, str) or not smiles.strip():
            return Response({"error": "'smiles' is required."}, status=status.HTTP_400_BAD_REQUEST)

        smiles = smiles.strip()
        if re.search(r"\s", smiles):
            return Response({"error": "SMILES contains whitespace."}, status=status.HTTP_400_BAD_REQUEST)
        if not _SMILES_ALLOWED_RE.match(smiles):
            return Response({"error": "Invalid SMILES characters."}, status=status.HTTP_400_BAD_REQUEST)

        # ------------------------------------------------------------------
        #  Validate Receptor Sequence
        # ------------------------------------------------------------------
        receptor_seq = payload.get("sequence") or payload.get("mutated_sequence") or ""
        if isinstance(receptor_seq, str):
            receptor_seq = receptor_seq.strip()
            if receptor_seq.startswith(">"):
                return Response(
                    {"error": "FASTA format is not allowed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if receptor_seq:
                if re.search(r"\s", receptor_seq):
                    return Response({"error": "Receptor sequence contains whitespace."},
                                    status=status.HTTP_400_BAD_REQUEST)
                if not _RECEPTOR_AA_RE.match(receptor_seq):
                    return Response({"error": "Invalid amino-acid letters in sequence."},
                                    status=status.HTTP_400_BAD_REQUEST)
        else:
            receptor_seq = ""

        # ------------------------------------------------------------------
        #  IDs
        # ------------------------------------------------------------------
        lr_id_value = payload.get("id") or payload.get("lr_id") or payload.get("lr_id_value") or "1"
        lr_id_value = lr_id_value.strip()

        ligand_id = payload.get("temp_ligand_id") or payload.get(lig_id_col_name) or ""
        ligand_id = ligand_id.strip() if isinstance(ligand_id, str) else ""
        if not ligand_id:
            ligand_name = payload.get("ligand_name") or ""
            sanitized = _sanitize_identifier(ligand_name)
            ligand_id = sanitized if sanitized else "lig_1"

        rec_id = payload.get("temp_rec_id") or payload.get(rec_id_col_name) or ""
        rec_id = rec_id.strip() if isinstance(rec_id, str) else ""
        if not rec_id:
            receptor_name = payload.get("receptor_name") or ""
            sanitized = _sanitize_identifier(receptor_name)
            rec_id = sanitized if sanitized else "TRec1"

        # ------------------------------------------------------------------
        #  Build CSV
        # ------------------------------------------------------------------
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf, lineterminator="\n")
        header = [lr_id_col_name, lig_id_col_name, lig_col_name, rec_col_name, rec_id_col_name]
        writer.writerow(header)
        writer.writerow([lr_id_value, ligand_id, smiles, receptor_seq or "", rec_id])
        csv_bytes = csv_buf.getvalue().encode("utf-8")
        csv_buf.close()

        # ------------------------------------------------------------------
        #  Save CSV to disk (with sync + stability wait)
        # ------------------------------------------------------------------
        job_id = str(uuid.uuid4())
        csv_filename = f"{job_id}.csv"

        try:
            job_dir = os.path.join(JOB_DATA_DIR or "/tmp/smiles_jobs", job_id)

            # ensure dir exists, then wait until fs shows it
            os.makedirs(job_dir, exist_ok=True)
            for _ in range(50):  # ~500 ms
                if os.path.isdir(job_dir):
                    break
                time.sleep(0.01)

            csv_path = os.path.join(job_dir, csv_filename)

            # Write with flush & fsync
            with open(csv_path, "wb") as fh:
                fh.write(csv_bytes)
                fh.flush()
                os.fsync(fh.fileno())

            # wait for file size > 0
            for _ in range(50):  # ~500 ms
                if os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
                    break
                time.sleep(0.01)

            if DEBUG_LOG:
                print(f"[SMILES] Final CSV saved & flushed: {csv_path} (size={os.path.getsize(csv_path)})")

        except Exception as e:
            if DEBUG_LOG:
                print(f"[SMILES] Error saving CSV: {e}")
            return Response({"error": "Failed to save CSV to disk."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # ------------------------------------------------------------------
        #  Async pipeline submission
        # ------------------------------------------------------------------
        if not PREDICT_DOCKER_URL:
            return Response({"error": "Pipeline URL not configured"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        pipeline_url = PREDICT_DOCKER_URL

        form_data = {
            "job_id": job_id,
            "lig_smiles_col": lig_col_name,
            "rec_seq_col": rec_col_name if receptor_seq else "",
            "lig_id_col": lig_id_col_name,
            "rec_id_col": rec_id_col_name,
            "lr_id_col": lr_id_col_name,
        }

        def async_submit():
            try:
                if DEBUG_LOG:
                    print(f"[ASYNC] Submitting job {job_id} -> {pipeline_url}")

                with open(csv_path, "rb") as fh:
                    files = {"input_file": (csv_filename, fh, "text/csv")}
                    resp = requests.post(pipeline_url, data=form_data, files=files, timeout=30)

                if DEBUG_LOG:
                    print(f"[ASYNC] Pipeline responded {resp.status_code} for job {job_id}")

            except Exception as e:
                if DEBUG_LOG:
                    print(f"[ASYNC] Error submitting job {job_id}: {e}")

        threading.Thread(target=async_submit, daemon=True).start()

        # ------------------------------------------------------------------
        #  Optional scheduler
        # ------------------------------------------------------------------
        if ENABLE_SCHEDULER:
            try:
                schedule_job(job_id, lambda j: None)
            except Exception as e:
                if DEBUG_LOG:
                    print(f"[SCHEDULER] Failed: {e}")

        # ------------------------------------------------------------------
        #  Return response
        # ------------------------------------------------------------------
        return Response(
            {"job_id": job_id, "message": "Job submitted to pipeline asynchronously."},
            status=status.HTTP_200_OK,
        )
