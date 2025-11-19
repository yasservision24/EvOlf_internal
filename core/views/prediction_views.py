
import os
import uuid
import csv
import io
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


class SmilesPredictionAPIView(APIView):
    """
    Accepts JSON-formatted request bodies (or form fields) — NOT uploaded files.
    Builds CSV with column order:
      ID, Temp_Ligand_ID, SMILES, Mutated_Sequence, TempRecID
    Auto-fill:
      - missing ID -> "1"
      - missing Temp_Ligand_ID -> "lig_1"
    """

    def post(self, request):
        payload = request.data or {}

        # Reject any file uploads
        if request.FILES:
            return Response({"error": "File uploads are not allowed. Send JSON body or form fields (no files)."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Allow overrides for column names that will be sent to pipeline
        lig_col_name = payload.get("lig_smiles_col", DEFAULT_LIG_COL)
        rec_col_name = payload.get("rec_seq_col", DEFAULT_REC_COL)
        lig_id_col_name = payload.get("lig_id_col", DEFAULT_LIG_ID_COL)
        rec_id_col_name = payload.get("rec_id_col", DEFAULT_REC_ID_COL)
        lr_id_col_name = payload.get("lr_id_col", DEFAULT_LR_ID_COL)

        # Read the single-row fields from JSON/form. These must be strings (not lists).
        smiles = payload.get("smiles")
        mutated_seq = payload.get("mutated_sequence") or payload.get(rec_col_name) or ""
        temp_lig_id = payload.get("temp_ligand_id") or payload.get(lig_id_col_name) or ""
        temp_rec_id = payload.get("temp_rec_id") or payload.get(rec_id_col_name) or ""
        lr_id_value = payload.get("id") or payload.get(lr_id_col_name) or ""

        # Reject array/list inputs — require single string values
        if isinstance(smiles, (list, tuple)) or isinstance(mutated_seq, (list, tuple)):
            return Response({"error": "List/array values are not allowed. Send single string values."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Validate smiles presence and type
        if not smiles or not isinstance(smiles, str):
            return Response({"error": "Field 'smiles' is required and must be a non-empty string."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Normalize strings (strip)
        smiles = smiles.strip()
        mutated_seq = mutated_seq.strip() if isinstance(mutated_seq, str) else ""
        temp_lig_id = temp_lig_id.strip() if isinstance(temp_lig_id, str) else ""
        temp_rec_id = temp_rec_id.strip() if isinstance(temp_rec_id, str) else ""
        lr_id_value = lr_id_value.strip() if isinstance(lr_id_value, str) else ""

        # Auto-fill defaults
        if not lr_id_value:
            lr_id_value = "1"
        if not temp_lig_id:
            temp_lig_id = "lig_1"

        # Build CSV exactly in the order: ID,Temp_Ligand_ID,SMILES,Mutated_Sequence,TempRecID
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer, lineterminator="\n")
        header = [lr_id_col_name, lig_id_col_name, lig_col_name, rec_col_name, rec_id_col_name]
        writer.writerow(header)

        row = [lr_id_value, temp_lig_id, smiles, mutated_seq, temp_rec_id]
        writer.writerow(row)

        csv_bytes = csv_buffer.getvalue().encode("utf-8")
        csv_buffer.close()

        job_id = str(uuid.uuid4())
        csv_filename = f"{job_id}.csv"

        # Save CSV directly under JOB_DATA_DIR/<job_id>/<job_id>.csv (or /tmp fallback)
        if JOB_DATA_DIR:
            try:
                job_dir = os.path.join(JOB_DATA_DIR, job_id)
                os.makedirs(job_dir, exist_ok=True)
                csv_path = os.path.join(job_dir, csv_filename)
                with open(csv_path, "wb") as fh:
                    fh.write(csv_bytes)
                if DEBUG_LOG:
                    print(f"[SMILES] Saved CSV to disk: {csv_path}")
            except Exception as e:
                if DEBUG_LOG:
                    print(f"[SMILES] Error saving CSV to JOB_DATA_DIR for job {job_id}: {e}")
                return Response({"error": "Failed to save CSV to JOB_DATA_DIR"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            tmp_dir = os.path.join("/tmp", "smiles_jobs", job_id)
            try:
                os.makedirs(tmp_dir, exist_ok=True)
                csv_path = os.path.join(tmp_dir, csv_filename)
                with open(csv_path, "wb") as fh:
                    fh.write(csv_bytes)
                if DEBUG_LOG:
                    print(f"[SMILES] JOB_DATA_DIR not configured - saved CSV to tmp: {csv_path}")
            except Exception as e:
                if DEBUG_LOG:
                    print(f"[SMILES] Failed to save CSV to tmp for job {job_id}: {e}")
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
            "rec_seq_col": rec_col_name if mutated_seq else "",
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
