import os
import csv
import uuid
import json
import requests
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.services.job_scheduler import schedule_job


PREDICT_DOCKER_URL = settings.PREDICT_DOCKER_URL
BASE_DATA_DIR = settings.JOB_DATA_DIR
MAX_LIMIT = settings.MAX_SMILES_LIMIT
ENABLE_SCHEDULER = settings.ENABLE_SCHEDULER
DEBUG_LOG = settings.DEBUG_LOG


class SmilesPredictionAPIView(APIView):

    def post(self, request):
        smiles_list = request.data.get("smiles")

        # Validate input
        if not smiles_list or not isinstance(smiles_list, list):
            return Response(
                {"error": "SMILES list must be a JSON array containing exactly 1 SMILES."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Only 1 ligand allowed
        if len(smiles_list) != 1:
            return Response(
                {"error": "Only one SMILES is allowed per prediction request."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job_id = str(uuid.uuid4())
        input_path = f"{BASE_DATA_DIR}/{job_id}/input"
        os.makedirs(input_path, exist_ok=True)

        with open(f"{input_path}/smiles.json", "w") as f:
            json.dump({"smiles": smiles_list}, f)

        # Job execution logic
        def execute(job_id):
            if DEBUG_LOG:
                print(f"[EXECUTE] Running job: {job_id}")
            return

        if ENABLE_SCHEDULER:
            schedule_job(job_id, execute)
        else:
            execute(job_id)

        return Response(
            {
                "job_id": job_id,
                "message": "Job submitted successfully."
            },
            status=status.HTTP_200_OK
        )




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
