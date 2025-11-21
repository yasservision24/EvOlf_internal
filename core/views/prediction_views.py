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

PREDICT_DOCKER_URL = getattr(settings, "PREDICT_DOCKER_URL", None)
JOB_DATA_DIR = getattr(settings, "JOB_DATA_DIR", None)
DEBUG_LOG = getattr(settings, "DEBUG_LOG", False)
ENABLE_SCHEDULER = getattr(settings, "ENABLE_SCHEDULER", False)

# Column-name defaults (used in form data sent to pipeline)
DEFAULT_LIG_COL = "SMILES"
DEFAULT_REC_COL = "Mutated_Sequence"
DEFAULT_LIG_ID_COL = "Temp_Ligand_ID"
DEFAULT_REC_ID_COL = "TempRecID"
DEFAULT_LR_ID_COL = "ID"


def _sanitize_identifier(s: str) -> str:
    """
    Make a safe identifier from a name: keep alphanumerics, dash, underscore.
    Collapse whitespace to underscore, lowercase.
    """
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-z0-9_-]", "", s)
    return s or ""


# Basic SMILES sanity regex (lightweight — not a full validator)
_SMILES_ALLOWED_RE = re.compile(r'^[A-Za-z0-9@\+\-\[\]\(\)=#\/\\%.:\*]+$')

# Receptor/amino-acid sequence regex (single-letter codes, allowing common ambiguous letters)
_RECEPTOR_AA_RE = re.compile(r'^[ACDEFGHIKLMNPQRSTVWYBXZJUO]+$', re.I)


class SmilesPredictionAPIView(APIView):
    """
    Accepts JSON/form with only:
      - 'smiles' (required string)
      - 'sequence' (optional plain receptor sequence string; MUST NOT be FASTA starting with '>')

    Auto-generates:
      - ID -> "1" (unless top-level 'id' provided)
      - Temp_Ligand_ID -> "lig_1" (or sanitized 'ligand_name' if provided)
      - TempRecID -> "TRec1"

    Saves CSV as: ID,Temp_Ligand_ID,SMILES,Mutated_Sequence,TempRecID
    Posts multipart/form-data to pipeline URL (only after format checks pass).
    """

    def post(self, request):
        payload = request.data or {}

        # Reject file uploads
        if request.FILES:
            return Response(
                {"error": "File uploads are not allowed. Send JSON body or form fields (no files)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Prevent arrays
        if any(isinstance(payload.get(k), (list, tuple)) for k in ("smiles", "sequence", "mutated_sequence")):
            return Response({"error": "Array values are not allowed. Send single string values."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Column-name overrides (kept for compatibility with pipeline request)
        lig_col_name = payload.get("lig_smiles_col", DEFAULT_LIG_COL)
        rec_col_name = payload.get("rec_seq_col", DEFAULT_REC_COL)
        lig_id_col_name = payload.get("lig_id_col", DEFAULT_LIG_ID_COL)
        rec_id_col_name = payload.get("rec_id_col", DEFAULT_REC_ID_COL)
        lr_id_col_name = payload.get("lr_id_col", DEFAULT_LR_ID_COL)

        # Read fields (accept either 'sequence' or 'mutated_sequence' for receptor)
        smiles = payload.get("smiles")
        receptor_seq = payload.get("sequence") or payload.get("mutated_sequence") or ""

        # Validate smiles (basic checks)
        if not smiles or not isinstance(smiles, str) or not smiles.strip():
            return Response({"error": "'smiles' is required and must be a non-empty string."},
                            status=status.HTTP_400_BAD_REQUEST)
        smiles = smiles.strip()
        # No whitespace inside canonical SMILES for our use-case
        if re.search(r'\s', smiles):
            return Response({"error": "Invalid SMILES: contains whitespace."}, status=status.HTTP_400_BAD_REQUEST)
        if not _SMILES_ALLOWED_RE.match(smiles):
            return Response({"error": "Invalid SMILES: contains unsupported characters."}, status=status.HTTP_400_BAD_REQUEST)

        # Validate receptor_seq if present (basic amino-acid alphabet check)
        if receptor_seq is not None and isinstance(receptor_seq, str):
            receptor_seq = receptor_seq.strip()
            if receptor_seq.startswith(">"):
                return Response({"error": "FASTA format is not accepted. Provide a plain sequence string (no '>' header)."},
                                status=status.HTTP_400_BAD_REQUEST)
            if receptor_seq:
                # No whitespace allowed inside sequence
                if re.search(r'\s', receptor_seq):
                    return Response({"error": "Invalid receptor sequence: contains whitespace."},
                                    status=status.HTTP_400_BAD_REQUEST)
                if not _RECEPTOR_AA_RE.match(receptor_seq):
                    return Response({"error": "Invalid receptor sequence: contains non-amino-acid letters."},
                                    status=status.HTTP_400_BAD_REQUEST)
        else:
            receptor_seq = ""

        # Determine lr_id (ID) - allow optional override, else default "1"
        lr_id_value = payload.get("id") or payload.get("lr_id") or payload.get("lr_id_value") or ""
        lr_id_value = lr_id_value.strip() if isinstance(lr_id_value, str) else ""
        if not lr_id_value:
            lr_id_value = "1"

        # Temp_Ligand_ID: we only have SMILES, so default to lig_1 unless frontend supplies a ligand_name
        ligand_id = payload.get("temp_ligand_id") or payload.get(lig_id_col_name) or ""
        ligand_id = ligand_id.strip() if isinstance(ligand_id, str) else ""
        if not ligand_id:
            ligand_name = payload.get("ligand_name") or ""
            ligand_name = ligand_name.strip() if isinstance(ligand_name, str) else ""
            sanitized = _sanitize_identifier(ligand_name)
            ligand_id = sanitized if sanitized else "lig_1"

        # TempRecID
        rec_id = payload.get("temp_rec_id") or payload.get(rec_id_col_name) or ""
        rec_id = rec_id.strip() if isinstance(rec_id, str) else ""
        if not rec_id:
            receptor_name = payload.get("receptor_name") or ""
            receptor_name = receptor_name.strip() if isinstance(receptor_name, str) else ""
            sanitized_rec = _sanitize_identifier(receptor_name)
            rec_id = sanitized_rec if sanitized_rec else "TRec1"

        # Build CSV
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer, lineterminator="\n")
        header = [lr_id_col_name, lig_id_col_name, lig_col_name, rec_col_name, rec_id_col_name]
        writer.writerow(header)
        writer.writerow([lr_id_value, ligand_id, smiles, receptor_seq or "", rec_id])
        csv_bytes = csv_buffer.getvalue().encode("utf-8")
        csv_buffer.close()

        # Save CSV
        job_id = str(uuid.uuid4())
        csv_filename = f"{job_id}.csv"
        try:
            if JOB_DATA_DIR:
                job_dir = os.path.join(JOB_DATA_DIR, job_id)
            else:
                job_dir = os.path.join("/tmp", "smiles_jobs", job_id)

            os.makedirs(job_dir, exist_ok=True)
            csv_path = os.path.join(job_dir, csv_filename)

            with open(csv_path, "wb") as fh:
                fh.write(csv_bytes)

            # ------------------------------------------------------------------
            #   WAIT UNTIL FILE IS ACTUALLY WRITTEN (your request)
            # ------------------------------------------------------------------
            for _ in range(25):   # ~250 ms max
                if os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
                    break
                time.sleep(0.01)

            if DEBUG_LOG:
                print(f"[SMILES] Saved CSV to disk: {csv_path}  (size={os.path.getsize(csv_path)})")

        except Exception as e:
            if DEBUG_LOG:
                print(f"[SMILES] Error saving CSV to disk for job {job_id}: {e}")
            return Response({"error": "Failed to save CSV to disk"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if DEBUG_LOG:
            try:
                print(f"[SMILES] CSV preview:\n{csv_bytes.decode('utf-8')}")
            except Exception:
                print("[SMILES] CSV preview: <decode error>")

        # ------------------------------------------------------------------
        #  ASYNCHRONOUS PIPELINE SUBMISSION
        # ------------------------------------------------------------------

        if not PREDICT_DOCKER_URL:
            return Response({"error": "Pipeline URL not configured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        pipeline_url = PREDICT_DOCKER_URL.rstrip("/") + "/pipeline/run"

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
                    print(f"[ASYNC] Starting async submission for {job_id}")

                with open(csv_path, "rb") as fh:
                    files = {"input_file": (csv_filename, fh, "text/csv")}
                    resp = requests.post(pipeline_url, data=form_data, files=files, timeout=30)

                if DEBUG_LOG:
                    print(f"[ASYNC] Pipeline responded for {job_id} with {resp.status_code}")

                if resp.status_code >= 400 and DEBUG_LOG:
                    print(f"[ASYNC] Pipeline rejected job {job_id}: {resp.text}")

            except Exception as e:
                if DEBUG_LOG:
                    print(f"[ASYNC] Error for job {job_id}: {e}")

        threading.Thread(target=async_submit, daemon=True).start()

        # Optional scheduler
        if ENABLE_SCHEDULER:
            try:
                schedule_job(job_id, lambda j: None)
            except Exception:
                if DEBUG_LOG:
                    print(f"[SCHEDULER] Failed to schedule job {job_id}")

        # Return fast
        return Response({"job_id": job_id, "message": "Job submitted to pipeline asynchronously."},
                        status=status.HTTP_200_OK)
