import os
import uuid
import json
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.services.job_scheduler import schedule_job

PREDICT_DOCKER_URL = settings.PREDICT_DOCKER_URL
BASE_DATA_DIR = settings.JOB_DATA_DIR
MAX_LIMIT = getattr(settings, "MAX_SMILES_LIMIT", 1)
ENABLE_SCHEDULER = getattr(settings, "ENABLE_SCHEDULER", False)
DEBUG_LOG = getattr(settings, "DEBUG_LOG", False)


class SmilesPredictionAPIView(APIView):
    """
    Accepts either:
      - { "smiles": ["SMILES"] }   # preferred
    or
      - { "receptor": {"sequence": "...", "name": "..."}, "ligands": [{"smiles": "...", "name": "..."}] }

    Backend ALWAYS creates the job_id (uuid4) — clients MUST NOT provide job_id.
    """

    def post(self, request):
        payload = request.data or {}

        # -------------------------
        # 1) Create server-side job id and folders
        # -------------------------
        job_id = str(uuid.uuid4())
        job_base_dir = os.path.join(BASE_DATA_DIR, job_id)
        input_dir = os.path.join(job_base_dir, "input")

        try:
            os.makedirs(input_dir, exist_ok=True)
        except Exception as e:
            if DEBUG_LOG:
                print(f"[SMILES] Error creating directories for job {job_id}: {e}")
            return Response({"error": "Failed to create job directories."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # -------------------------
        # 2) Persist raw payload for audit (best-effort; don't fail request on logging error)
        # -------------------------
        try:
            with open(os.path.join(input_dir, "raw_request.json"), "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            if DEBUG_LOG:
                print(f"[SMILES] Warning: failed to write raw_request.json for job {job_id}: {e}")

        # -------------------------
        # 3) Normalize input to a single smiles_list (list[str]) — require exactly 1 SMILES
        # -------------------------
        smiles_list = None

        # Case A: explicit "smiles" key (preferred)
        if "smiles" in payload:
            s = payload.get("smiles")
            if not isinstance(s, list):
                return Response({"error": "'smiles' must be an array of SMILES strings."}, status=status.HTTP_400_BAD_REQUEST)

            if MAX_LIMIT is not None and len(s) > MAX_LIMIT:
                return Response({"error": f"Exceeded maximum allowed SMILES ({MAX_LIMIT})."}, status=status.HTTP_400_BAD_REQUEST)

            smiles_list = [str(x).strip() for x in s if str(x).strip()]

        # Case B: legacy ligands structure
        elif "ligands" in payload:
            ligs = payload.get("ligands")
            if not isinstance(ligs, list) or len(ligs) == 0:
                return Response({"error": "'ligands' must be a non-empty array."}, status=status.HTTP_400_BAD_REQUEST)

            first = ligs[0]
            if isinstance(first, dict) and "smiles" in first:
                s = first.get("smiles")
                if not s or not str(s).strip():
                    return Response({"error": "Ligand 'smiles' is empty."}, status=status.HTTP_400_BAD_REQUEST)
                smiles_list = [str(s).strip()]
            else:
                if isinstance(first, str) and first.strip():
                    smiles_list = [first.strip()]
                else:
                    return Response({"error": "Failed to parse ligand smiles."}, status=status.HTTP_400_BAD_REQUEST)

        else:
            return Response({"error": "Invalid payload. Provide 'smiles' array or 'ligands' list."}, status=status.HTTP_400_BAD_REQUEST)

        # Validate final list (exactly one SMILES required by server)
        if not smiles_list or len(smiles_list) != 1:
            return Response({"error": "SMILES list must be a JSON array containing exactly 1 SMILES."}, status=status.HTTP_400_BAD_REQUEST)

        # -------------------------
        # 4) Save receptor (optional) and smiles file
        # -------------------------
        receptor = payload.get("receptor")
        if receptor and isinstance(receptor, dict):
            seq = receptor.get("sequence")
            if seq and isinstance(seq, str) and seq.strip():
                try:
                    with open(os.path.join(input_dir, "receptor.fasta"), "w", encoding="utf-8") as fh:
                        fh.write(seq)
                except Exception as e:
                    if DEBUG_LOG:
                        print(f"[SMILES] Warning: failed to write receptor.fasta for job {job_id}: {e}")

            # receptor metadata (best-effort)
            try:
                with open(os.path.join(input_dir, "receptor_meta.json"), "w", encoding="utf-8") as fh:
                    json.dump({"name": receptor.get("name")}, fh, ensure_ascii=False, indent=2)
            except Exception as e:
                if DEBUG_LOG:
                    print(f"[SMILES] Warning: failed to write receptor_meta.json for job {job_id}: {e}")

        # Save smiles.json (required)
        try:
            with open(os.path.join(input_dir, "smiles.json"), "w", encoding="utf-8") as f:
                json.dump({"smiles": smiles_list}, f, ensure_ascii=False)
        except Exception as e:
            if DEBUG_LOG:
                print(f"[SMILES] Error writing smiles.json for job {job_id}: {e}")
            return Response({"error": "Failed to write smiles input file."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # -------------------------
        # 5) Submit / schedule job
        # -------------------------
        def execute(job_id_local):
            # Replace with real execution dispatch (e.g., send to prediction service or container)
            if DEBUG_LOG:
                print(f"[EXECUTE] Running job: {job_id_local}")
            return

        if ENABLE_SCHEDULER:
            # schedule_job should accept job_id and callable
            schedule_job(job_id, execute)
        else:
            execute(job_id)

        # -------------------------
        # 6) Success response (server-generated job_id only)
        # -------------------------
        return Response({"job_id": job_id, "message": "Job submitted successfully."}, status=status.HTTP_200_OK)

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
