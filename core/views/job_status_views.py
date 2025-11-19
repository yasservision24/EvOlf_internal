import os
import json
import tempfile
import zipfile
from django.conf import settings
from django.http import FileResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

# Prefer configured JOB_DATA_DIR, otherwise fallback to your host path
JOB_DATA_DIR = getattr(settings, "JOB_DATA_DIR", "/16Tbdrive1/evolf/evolf_docker/pipeline_runs")

class JobStatusAPIView(APIView):
    """
    GET /predict/job/<job_id>/
      - returns job_status.json if exists
      - if ?download=output or ?dl=output -> returns a zip of <JOB_DATA_DIR>/<job_id>/output/ as attachment
    """

    def get(self, request, job_id):
        job_dir = os.path.join(JOB_DATA_DIR, job_id)
        if not os.path.isdir(job_dir):
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)

        # If client asked to download output as zip
        download_param = request.query_params.get("download") or request.query_params.get("dl")
        if download_param and download_param.lower() == "output":
            return self._serve_output_zip(job_dir, job_id)

        # Default: return job_status.json (if present)
        status_path = os.path.join(job_dir, "job_status.json")
        if not os.path.exists(status_path):
            return Response({"error": "Job status not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            with open(status_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            return Response(meta, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": f"Failed to read job status: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _serve_output_zip(self, job_dir: str, job_id: str):
        """
        Create a zip of job_dir/output and return it as a FileResponse.
        """
        output_dir = os.path.join(job_dir, "output")
        if not os.path.isdir(output_dir):
            return Response({"error": "Output folder not found for job"}, status=status.HTTP_404_NOT_FOUND)

        # Create a zip file inside the job_dir (overwrite if exists)
        zip_name = f"{job_id}_output.zip"
        zip_path = os.path.join(job_dir, zip_name)

        try:
            # Create/overwrite zip
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                # Walk the output_dir and add files preserving relative paths
                for root, _, files in os.walk(output_dir):
                    for fname in files:
                        full_path = os.path.join(root, fname)
                        # preserve relative path inside 'output/' folder
                        rel_path = os.path.relpath(full_path, job_dir)
                        zf.write(full_path, arcname=rel_path)
        except Exception as e:
            return Response({"error": f"Failed to create zip archive: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Stream the created zip file back
        try:
            f = open(zip_path, "rb")
            response = FileResponse(f, as_attachment=True, filename=zip_name, content_type="application/zip")
            return response
        except Exception as e:
            return Response({"error": f"Failed to serve zip file: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
