
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

# Config from settings
PREDICT_DOCKER_URL = getattr(settings, "PREDICT_DOCKER_URL", None)
JOB_DATA_DIR = getattr(settings, "JOB_DATA_DIR", None)
MAX_LIMIT = getattr(settings, "MAX_SMILES_LIMIT", 1)
DEBUG_LOG = getattr(settings, "DEBUG_LOG", False)
ENABLE_SCHEDULER = getattr(settings, "ENABLE_SCHEDULER", False)

# Defaults matching earlier examples
DEFAULT_LIG_COL = "SMILES"
DEFAULT_REC_COL = "Mutated_Sequence"
DEFAULT_LIG_ID_COL = "Temp_Ligand_ID"
DEFAULT_REC_ID_COL = "TempRecID"
DEFAULT_LR_ID_COL = "ID"


class SmilesPredictionAPIView(APIView):
    """
    Save CSV under JOB_DATA_DIR/<job_id>/<job_id>.csv with column order:
      ID, Temp_Ligand_ID, SMILES, Mutated_Sequence, TempRecID

    Accepts:
      - uploaded CSV: request.FILES['input_file']
      - OR JSON/form: 'smiles' list or 'ligands' list
    Optional column name overrides via form fields:
      lig_smiles_col, rec_seq_col, lig_id_col, rec_id_col, lr_id_col
    """

    def post(self, request):
        payload = request.data or {}

        # Allow overrides but default to known names
        lig_col_name = payload.get("lig_smiles_col", DEFAULT_LIG_COL)
        rec_col_name = payload.get("rec_seq_col", DEFAULT_REC_COL)
        lig_id_col_name = payload.get("lig_id_col", DEFAULT_LIG_ID_COL)
        rec_id_col_name = payload.get("rec_id_col", DEFAULT_REC_ID_COL)
        lr_id_col_name = payload.get("lr_id_col", DEFAULT_LR_ID_COL)

        # Generate job id
        job_id = str(uuid.uuid4())

        # Prepare containers
        smiles_list = []
        lig_meta_list = []  # each: {"name":..., "id":..., "lr_id":...}

        # 1) If uploaded CSV present, parse it (CSV may include columns in any order)
        uploaded_csv = None
        try:
            uploaded_csv = request.FILES.get("input_file")
        except Exception:
            uploaded_csv = None

        if uploaded_csv:
            # Read CSV text
            try:
                csv_text = uploaded_csv.read().decode("utf-8", errors="replace")
                rdr = csv.DictReader(io.StringIO(csv_text))
                for row in rdr:
                    # Extract values using provided column names (fall back to common names)
                    smi = (row.get(lig_col_name) or row.get(DEFAULT_LIG_COL) or "").strip()
                    if not smi:
                        # skip rows without SMILES
                        continue

                    # ligand id field from provided lig_id_col_name or fallback keys
                    lig_id_val = (row.get(lig_id_col_name) or row.get(DEFAULT_LIG_ID_COL) or "").strip() or None

                    # receptor id field
                    rec_id_val = (row.get(rec_id_col_name) or row.get(DEFAULT_REC_ID_COL) or "").strip() or None

                    # lr id (ID) may be present per-row or can be top-level (see below)
                    lr_id_val = (row.get(lr_id_col_name) or row.get(DEFAULT_LR_ID_COL) or "").strip() or None

                    # Add to lists
                    smiles_list.append(smi)
                    lig_meta_list.append({
                        "name": (row.get("ligand_name") or row.get("name") or None),
                        "id": lig_id_val,
                        "rec_id": rec_id_val,
                        "lr_id": lr_id_val,
                    })
            except Exception as e:
                if DEBUG_LOG:
                    print(f"[SMILES] Failed to parse uploaded CSV: {e}")
                return Response({"error": "Failed to parse uploaded CSV."}, status=status.HTTP_400_BAD_REQUEST)

        else:
            # 2) JSON/form input behavior
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
                    lig_meta_list.append({"name": None, "id": None, "rec_id": None, "lr_id": None})

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
                        lig_meta_list.append({
                            "name": lig.get("name"),
                            "id": lig.get("id"),
                            "rec_id": lig.get("rec_id"),
                            "lr_id": lig.get("lr_id"),
                        })
                    elif isinstance(lig, str) and lig.strip():
                        smiles_list.append(lig.strip())
                        lig_meta_list.append({"name": None, "id": None, "rec_id": None, "lr_id": None})
                    else:
                        return Response({"error": "Invalid ligand format"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({"error": "Provide 'smiles' list or 'ligands' list or upload 'input_file' CSV"}, status=status.HTTP_400_BAD_REQUEST)

        if not smiles_list:
            return Response({"error": "No valid SMILES found"}, status=status.HTTP_400_BAD_REQUEST)

        if MAX_LIMIT == 1 and len(smiles_list) != 1:
            return Response({"error": "Exactly 1 SMILES required"}, status=status.HTTP_400_BAD_REQUEST)

        # 3) Receptor (optional top-level)
        receptor = payload.get("receptor")
        receptor_seq = None
        receptor_id_top = None
        if isinstance(receptor, dict):
            seq = receptor.get("sequence")
            if seq and isinstance(seq, str) and seq.strip():
                receptor_seq = seq.strip()
            receptor_id_top = receptor.get("id") or None

        # 4) lr_id value may also be provided top-level (applies to all rows unless per-row value present)
        lr_id_top = payload.get("lr_id") or payload.get("lr_id_value") or None

        # 5) Build CSV with EXACT ORDER requested:
        #    ID, Temp_Ligand_ID, SMILES, Mutated_Sequence, TempRecID
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer, lineterminator="\n")
        header = [
            lr_id_col_name,     # ID
            lig_id_col_name,    # Temp_Ligand_ID
            lig_col_name,       # SMILES
            rec_col_name,       # Mutated_Sequence
            rec_id_col_name     # TempRecID
        ]
        writer.writerow(header)

        for idx, smi in enumerate(smiles_list):
            meta = lig_meta_list[idx] if idx < len(lig_meta_list) else {}

            # Determine per-row values; precedence: per-row CSV lr_id/rec_id if present -> top-level values -> empty
            row_lr_id = meta.get("lr_id") or lr_id_top or ""
            row_lig_id = meta.get("id") or ""
            row_smiles = smi
            row_rec_seq = receptor_seq or ""  # if receptor provided top-level, use it; earlier CSV rows may contain rec id only
            # receptor id (TempRecID) — prefer per-row rec_id value (if parsed from uploaded CSV), else top-level receptor id
            row_rec_id = meta.get("rec_id") or receptor_id_top or ""

            row = [
                row_lr_id,
                row_lig_id,
                row_smiles,
                row_rec_seq,
                row_rec_id
            ]
            writer.writerow(row)

        csv_bytes = csv_buffer.getvalue().encode("utf-8")
        csv_buffer.close()

        csv_filename = f"{job_id}.csv"

        # Save CSV directly under JOB_DATA_DIR/<job_id>/<job_id>.csv
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
            # fallback to tmp
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

        # debug preview
        if DEBUG_LOG:
            try:
                print(f"[SMILES] CSV preview:\n{csv_bytes.decode('utf-8')}")
            except Exception:
                print("[SMILES] CSV preview: <binary or decode error>")

        # 6) Post to pipeline using saved file (multipart/form-data)
        if not PREDICT_DOCKER_URL:
            return Response({"error": "Pipeline URL not configured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        pipeline_url = PREDICT_DOCKER_URL.rstrip("/") + "/pipeline/run"

        form_data = {
            "job_id": job_id,
            "lig_smiles_col": lig_col_name,
            # If no receptor sequence present, send empty string for rec_seq_col (pipeline expects the field)
            "rec_seq_col": rec_col_name if receptor_seq else "",
            "lig_id_col": lig_id_col_name,
            "rec_id_col": rec_id_col_name,
            "lr_id_col": lr_id_col_name,
        }

        if DEBUG_LOG:
            print(f"[SMILES] Posting to pipeline {pipeline_url} job_id={job_id} rows={len(smiles_list)} csv_path={csv_path}")
            print(f"[SMILES] form data: {form_data}")

        try:
            with open(csv_path, "rb") as fh:
                files = {"input_file": (csv_filename, fh, "text/csv")}
                try:
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
            err_body = None
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text
            if DEBUG_LOG:
                print(f"[SMILES] Pipeline returned non-2xx for job {job_id}: {resp.status_code} - {err_body}")
            return Response({"error": "Pipeline rejected job submission", "details": err_body}, status=status.HTTP_502_BAD_GATEWAY)

        # Optional scheduler bookkeeping
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
