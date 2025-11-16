# # core/views/job_status_views.py
# import os
# import json
# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework import status

# BASE_DATA_DIR = "/data"

# class JobStatusAPIView(APIView):
#     """
#     GET /api/job/<job_id>/status/
#     Returns the job_status.json content for the job.
#     """
#     def get(self, request, job_id):
#         path = os.path.join(BASE_DATA_DIR, job_id, "job_status.json")
#         if not os.path.exists(path):
#             return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)

#         try:
#             with open(path, "r") as f:
#                 meta = json.load(f)
#             return Response(meta, status=200)
#         except Exception as e:
#             return Response({"error": f"Failed to read job status: {str(e)}"}, status=500)
