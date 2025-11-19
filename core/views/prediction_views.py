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

PREDICT_DOCKER_URL = settings.PREDICT_DOCKER_URL
JOB_DATA_DIR = getattr(settings, "JOB_DATA_DIR", None)
MAX_LIMIT = getattr(settings, "MAX_SMILES_LIMIT", 1)
DEBUG_LOG = getattr(settings, "DEBUG_LOG", False)
ENABLE_SCHEDULER = getattr(settings, "ENABLE_SCHEDULER", False)

# Default column names that match your curl example; change if needed
DEFAULT_LIG_COL = "SMILES"
DEFAULT_REC_COL = "Mutated_Sequence"
DEFAULT_LIG_ID_COL = "Temp_Ligand_ID"
DEFAULT_REC_ID_COL = "TempRecID"
DEFAULT_LR_ID_COL = "ID"


class SmilesPredictionAPIView(APIView):
    """
    Builds an in-memory CSV named {job_id}.csv and POSTs it to the pipeline
    with the form-field names matching your curl example.

    Additionally, saves a persistent copy of the CSV at:
      {JOB_DATA_DIR}/{job_id}/input/{job_id}.csv
    if JOB_DATA_DIR is configured.

    Returns only job_id + message (202 Accepted).
    """

    def post(self, request):
        payload = request.data or {}

        # 0) Optionally accept column-name overrides from payload
        lig_col_name = payload.get("lig_smiles_col", DEFAULT_LIG_COL)
        rec_col_name = payload.get("rec_seq_col", DEFAULT_REC_COL)
        lig_id_col_name = payload.get("lig_id_col", DEFAULT_LIG_ID_COL)
        rec_id_col_name = payload.get("rec_id_col", DEFAULT_REC_ID_COL)
        lr_id_col_name = payload.get("lr_id_col", DEFAULT_LR_ID_COL)

        # 1) Generate job_id
        job_id = str(uuid.uuid4())

        # 2) Normalize ligand inputs
        smiles_list = []
        lig_meta_list = []

        if "smiles" in payload:
            incoming = payload.get("smiles", [])
            if not isinstance(incoming, list):
                return Response({"error": "'smiles' must be a list"}, status=status.HTTP_400_BAD_REQUEST)
            if MAX_LIMIT and len(incoming) > MAX_LIMIT:
                return Response({"error": f"Max {MAX_LIMIT} SMILES allowed"}, status=status.HTTP_400_BAD_REQUEST)
            for s in incoming:
                s = str(s).strip()
                if not s:
                    return Response({"error": "Empty SMILES provided"}, status=status.HTTP_400_BAD_REQUEST)
                smiles_list.append(s)
                lig_meta_list.append({})
        elif "ligands" in payload:
            ligs = payload.get("ligands")
            if not isinstance(ligs, list) or not ligs:
                return Response({"error": "'ligands' must be a non-empty list"}, status=status.HTTP_400_BAD_REQUEST)
            if MAX_LIMIT and len(ligs) > MAX_LIMIT:
                return Response({"error": f"Max {MAX_LIMIT} ligands allowed"}, status=status.HTTP_400_BAD_REQUEST)
            for lig in ligs:
                if isinstance(lig, dict):
                    s = str(lig.get("smiles", "")).strip()
                    if not s:
                        return Response({"error": "Ligand SMILES empty"}, status=status.HTTP_400_BAD_REQUEST)
                    smiles_list.append(s)
                    lig_meta_list.append({"name": lig.get("name"), "id": lig.get("id")})
                elif isinstance(lig, str) and lig.strip():
                    smiles_list.append(lig.strip())
                    lig_meta_list.append({})
                else:
                    return Response({"error": "Invalid ligand format"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({"error": "Provide 'smiles' list or 'ligands' list"}, status=status.HTTP_400_BAD_REQUEST)

        if not smiles_list:
            return Response({"error": "No valid SMILES found"}, status=status.HTTP_400_BAD_REQUEST)

        if MAX_LIMIT == 1 and len(smiles_list) != 1:
            return Response({"error": "Exactly 1 SMILES required"}, status=status.HTTP_400_BAD_REQUEST)

        # 3) Receptor (optional)
        receptor = payload.get("receptor")
        receptor_seq = None
        if isinstance(receptor, dict):
            seq = receptor.get("sequence")
            if seq and isinstance(seq, str) and seq.strip():
                receptor_seq = seq.strip()

        # 4) Build CSV in-memory with header names matching the column names
        header = [lig_col_name]
        if receptor_seq:
            header.append(rec_col_name)

        include_name = any(m.get("name") for m in lig_meta_list)
        include_id = any(m.get("id") for m in lig_meta_list)
        if include_name:
            header.append("ligand_name")
        if include_id:
            header.append("ligand_id")

        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer, lineterminator="\n")
        writer.writerow(header)

        for idx, smi in enumerate(smiles_list):
            row = [smi]
            if receptor_seq:
                row.append(receptor_seq)
            meta = lig_meta_list[idx] if idx < len(lig_meta_list) else {}
            if include_name:
                row.append(meta.get("name") or "")
            if include_id:
                row.append(meta.get("id") or "")
            writer.writerow(row)

        csv_bytes = csv_buffer.getvalue().encode("utf-8")
        csv_buffer.close()

        csv_filename = f"{job_id}.csv"

        # Save CSV to disk if JOB_DATA_DIR configured (safe persistent copy)
        if JOB_DATA_DIR:
            try:
                job_input_dir = os.path.join(JOB_DATA_DIR, job_id, "input")
                os.makedirs(job_input_dir, exist_ok=True)
                csv_path = os.path.join(job_input_dir, csv_filename)
                with open(csv_path, "wb") as fh:
                    fh.write(csv_bytes)
                if DEBUG_LOG:
                    print(f"[SMILES] Saved CSV to disk: {csv_path}")
            except Exception as e:
                if DEBUG_LOG:
                    print(f"[SMILES] Warning: failed to save CSV to disk for job {job_id}: {e}")

        # debug: preview
        if DEBUG_LOG:
            try:
                print(f"[SMILES] CSV preview:\n{csv_bytes.decode('utf-8')}")
            except Exception:
                print("[SMILES] CSV preview: <binary or decode error>")

        # 5) Send to pipeline using the exact form fields as your curl
        if not PREDICT_DOCKER_URL:
            return Response({"error": "Pipeline URL not configured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        pipeline_url = PREDICT_DOCKER_URL.rstrip("/") + "/pipeline/run"

        data = {
            "job_id": job_id,
            "lig_smiles_col": lig_col_name,
            "rec_seq_col": rec_col_name if receptor_seq else "",
            "lig_id_col": lig_id_col_name,
            "rec_id_col": rec_id_col_name,
            "lr_id_col": lr_id_col_name,
        }

        # build BytesIO and ensure rewind
        bio = io.BytesIO(csv_bytes)
        bio.seek(0)
        files = {"input_file": (csv_filename, bio, "text/csv")}

        if DEBUG_LOG:
            print(f"[SMILES] Posting to pipeline {pipeline_url} job_id={job_id} rows={len(smiles_list)} csv_name={csv_filename}")
            print(f"[SMILES] form data: {data}")

        try:
            resp = requests.post(pipeline_url, data=data, files=files, timeout=30)
        except requests.RequestException as e:
            if DEBUG_LOG:
                print(f"[SMILES] Pipeline POST failed for job {job_id}: {e}")
            try:
                bio.close()
            except Exception:
                pass
            return Response({"error": "Failed to contact prediction pipeline."}, status=status.HTTP_502_BAD_GATEWAY)

        try:
            bio.close()
        except Exception:
            pass

        if not (200 <= resp.status_code < 300):
            err_body = None
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text
            if DEBUG_LOG:
                print(f"[SMILES] Pipeline returned non-2xx for job {job_id}: {resp.status_code} - {err_body}")
            return Response({"error": "Pipeline rejected job submission", "details": err_body}, status=status.HTTP_502_BAD_GATEWAY)

        # 6) Optionally schedule local bookkeeping via scheduler (lightweight)
        if ENABLE_SCHEDULER:
            def execute_local(jid):
                if DEBUG_LOG:
                    print(f"[SCHEDULER] Job {jid} enqueued for local bookkeeping.")
                # small, safe tasks only: DB updates, notifications, logging, etc.
                return
            schedule_job(job_id, execute_local)

        # 7) Return ONLY job_id and message
        return Response({"job_id": job_id, "message": "Job submitted to pipeline."}, status=status.HTTP_202_ACCEPTED)

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
