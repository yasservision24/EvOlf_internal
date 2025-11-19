import os
import uuid
import csv
import io
import re
import requests

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
    # keep only a-z0-9_- characters
    s = re.sub(r"[^a-z0-9_-]", "", s)
    return s or ""


class SmilesPredictionAPIView(APIView):
    """
    Accepts JSON-formatted request bodies (no file uploads).
    Expect payload:
      {
        "receptor": { "sequence": "<string>", "name": "<optional>", "id": "<optional>" },
        "ligand":  { "smiles": "<string>", "name": "<optional>", "id": "<optional>" },
        optional overrides for column names: lig_smiles_col, rec_seq_col, lig_id_col, rec_id_col, lr_id_col
      }

    Builds CSV with order:
      ID, Temp_Ligand_ID, SMILES, Mutated_Sequence, TempRecID

    Auto-generate identifiers when missing:
      - ID -> "1" (unless provided via top-level 'id' or lr_id_col)
      - Temp_Ligand_ID -> ligand.id OR sanitized ligand.name OR "lig_1"
      - TempRecID -> receptor.id OR sanitized receptor.name OR "TRec1"
    """

    def post(self, request):
        payload = request.data or {}

        # Reject any file uploads
        if request.FILES:
            return Response(
                {"error": "File uploads are not allowed. Send JSON body or form fields (no files)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Allow overrides for column names that will be sent to pipeline
        lig_col_name = payload.get("lig_smiles_col", DEFAULT_LIG_COL)
        rec_col_name = payload.get("rec_seq_col", DEFAULT_REC_COL)
        lig_id_col_name = payload.get("lig_id_col", DEFAULT_LIG_ID_COL)
        rec_id_col_name = payload.get("rec_id_col", DEFAULT_REC_ID_COL)
        lr_id_col_name = payload.get("lr_id_col", DEFAULT_LR_ID_COL)

        # Expect receptor (object) and ligand (object) in payload
        receptor = payload.get("receptor")
        ligand = payload.get("ligand") or payload.get("ligands")  # accept singular 'ligand' or mistakenly 'ligands' if frontend sends it

        # Reject lists/arrays for ligand or receptor
        if isinstance(ligand, (list, tuple)) or isinstance(receptor, (list, tuple)):
            return Response(
                {"error": "Array values are not allowed for 'ligand' or 'receptor'. Send single objects."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(receptor, dict):
            return Response({"error": "Field 'receptor' must be provided as an object with 'sequence'."},
                            status=status.HTTP_400_BAD_REQUEST)

        if not isinstance(ligand, dict):
            return Response({"error": "Field 'ligand' must be provided as an object with 'smiles'."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Extract receptor sequence
        receptor_seq = receptor.get("sequence") or receptor.get("seq") or ""
        if not receptor_seq or not isinstance(receptor_seq, str) or not receptor_seq.strip():
            # receptor sequence may be optional in some pipelines; here we allow empty but warn
            receptor_seq = receptor_seq.strip() if isinstance(receptor_seq, str) else ""
            # we won't fail — pipeline may accept empty receptor — but log if debug
            if DEBUG_LOG:
                print("[SMILES] Warning: receptor.sequence is empty")

        # Extract ligand SMILES and validate
        ligand_smiles = ligand.get("smiles") or ligand.get("smile") or ""
        if not ligand_smiles or not isinstance(ligand_smiles, str) or not ligand_smiles.strip():
            return Response({"error": "Field 'ligand.smiles' is required and must be a non-empty string."},
                            status=status.HTTP_400_BAD_REQUEST)
        ligand_smiles = ligand_smiles.strip()

        # Determine lr_id (ID column) - precedence: top-level id -> payload lr_id_value -> none -> default "1"
        lr_id_value = payload.get("id") or payload.get("lr_id") or payload.get("lr_id_value") or ""
        lr_id_value = lr_id_value.strip() if isinstance(lr_id_value, str) else ""
        if not lr_id_value:
            lr_id_value = "1"

        # Determine Temp_Ligand_ID
        ligand_id = payload.get("temp_ligand_id") or payload.get(lig_id_col_name) or ligand.get("id") or ""
        ligand_id = ligand_id.strip() if isinstance(ligand_id, str) else ""
        if not ligand_id:
            # try sanitize ligand name
            ligand_name = ligand.get("name") or payload.get("ligand_name") or ""
            ligand_name = ligand_name.strip() if isinstance(ligand_name, str) else ""
            sanitized = _sanitize_identifier(ligand_name)
            ligand_id = sanitized if sanitized else "lig_1"

        # Determine TempRecID
        rec_id = payload.get("temp_rec_id") or payload.get(rec_id_col_name) or receptor.get("id") or ""
        rec_id = rec_id.strip() if isinstance(rec_id, str) else ""
        if not rec_id:
            # try sanitize receptor name
            receptor_name = receptor.get("name") or payload.get("receptor_name") or ""
            receptor_name = receptor_name.strip() if isinstance(receptor_name, str) else ""
            sanitized_rec = _sanitize_identifier(receptor_name)
            rec_id = sanitized_rec if sanitized_rec else "TRec1"

        # Normalize receptor sequence (if it's FASTA, strip header lines)
        if isinstance(receptor_seq, str) and receptor_seq.strip().startswith(">"):
            lines = receptor_seq.splitlines()
            seq_lines = [ln for ln in lines if ln and not ln.startswith(">")]
            receptor_seq = "".join(seq_lines).strip()

        # Build CSV exactly in the order: ID, Temp_Ligand_ID, SMILES, Mutated_Sequence, TempRecID
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer, lineterminator="\n")
        header = [lr_id_col_name, lig_id_col_name, lig_col_name, rec_col_name, rec_id_col_name]
        writer.writerow(header)

        row = [lr_id_value, ligand_id, ligand_smiles, receptor_seq or "", rec_id]
        writer.writerow(row)

        csv_bytes = csv_buffer.getvalue().encode("utf-8")
        csv_buffer.close()

        job_id = str(uuid.uuid4())
        csv_filename = f"{job_id}.csv"

        # Save CSV directly under JOB_DATA_DIR/<job_id>/<job_id>.csv (or /tmp fallback)
        try:
            if JOB_DATA_DIR:
                job_dir = os.path.join(JOB_DATA_DIR, job_id)
            else:
                job_dir = os.path.join("/tmp", "smiles_jobs", job_id)
            os.makedirs(job_dir, exist_ok=True)
            csv_path = os.path.join(job_dir, csv_filename)
            with open(csv_path, "wb") as fh:
                fh.write(csv_bytes)
            if DEBUG_LOG:
                print(f"[SMILES] Saved CSV to disk: {csv_path}")
        except Exception as e:
            if DEBUG_LOG:
                print(f"[SMILES] Error saving CSV to disk for job {job_id}: {e}")
            return Response({"error": "Failed to save CSV to disk"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Debug preview
        if DEBUG_LOG:
            try:
                print(f"[SMILES] CSV preview:\n{csv_bytes.decode('utf-8')}")
            except Exception:
                print("[SMILES] CSV preview: <decode error>")

        # Post to pipeline (multipart/form-data) using the saved file
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

        if DEBUG_LOG:
            print(f"[SMILES] Posting to pipeline {pipeline_url} job_id={job_id} csv_path={csv_path} form_data={form_data}")

        try:
            with open(csv_path, "rb") as fh:
                files = {"input_file": (csv_filename, fh, "text/csv")}
                resp = requests.post(pipeline_url, data=form_data, files=files, timeout=30)
        except requests.RequestException as e:
            if DEBUG_LOG:
                print(f"[SMILES] Pipeline POST failed for job {job_id}: {e}")
            return Response({"error": "Failed to contact prediction pipeline."}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception as e:
            if DEBUG_LOG:
                print(f"[SMILES] Failed to open CSV file {csv_path} for POST: {e}")
            return Response({"error": "Failed to read saved CSV file."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not (200 <= resp.status_code < 300):
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text
            if DEBUG_LOG:
                print(f"[SMILES] Pipeline returned non-2xx for job {job_id}: {resp.status_code} - {err_body}")
            return Response({"error": "Pipeline rejected job submission", "details": err_body}, status=status.HTTP_502_BAD_GATEWAY)

        # Optional local scheduler bookkeeping
        if ENABLE_SCHEDULER:
            def execute_local(jid):
                if DEBUG_LOG:
                    print(f"[SCHEDULER] Job {jid} enqueued for local bookkeeping.")
                return
            schedule_job(job_id, execute_local)

        return Response({"job_id": job_id, "message": "Job submitted to pipeline."}, status=status.HTTP_200_OK)



# class CSVPredictionAPIView(APIView):

#     def post(self, request):
#         file = request.FILES.get("file")

#         if not file:
#             return Response(
#                 {"error": "CSV file required."},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         try:
#             decoded = file.read().decode("utf-8").splitlines()
#             reader = csv.DictReader(decoded)

#             if "SMILES" not in reader.fieldnames:
#                 return Response(
#                     {"error": "CSV must contain 'SMILES' column."},
#                     status=status.HTTP_400_BAD_REQUEST,
#                 )

#             smiles_list = [row["SMILES"] for row in reader]

#         except Exception as e:
#             return Response({"error": f"CSV parsing error: {str(e)}"}, status=400)

#         if len(smiles_list) > MAX_LIMIT:
#             return Response(
#                 {"error": f"CSV has > {MAX_LIMIT} SMILES. Use Docker pipeline."},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         job_id = str(uuid.uuid4())
#         input_path = f"{BASE_DATA_DIR}/{job_id}/input"
#         os.makedirs(input_path, exist_ok=True)

#         with open(f"{input_path}/smiles.json", "w") as f:
#             json.dump({"smiles": smiles_list}, f)

#         def execute(job_id):
#             if DEBUG_LOG:
#                 print(f"[EXECUTE] Running CSV job: {job_id}")
#             # requests.post(PREDICT_DOCKER_URL, json={"job_id": job_id})

#         if ENABLE_SCHEDULER:
#             schedule_job(job_id, execute)
#         else:
#             execute(job_id)

#         return Response(
#             {
#                 "job_id": job_id,
#                 "message": "CSV job submitted successfully."
#             },
#             status=status.HTTP_200_OK
#         )
