# predict/views.py
import os
import zipfile
from django.conf import settings
from django.http import FileResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

# prefer configured JOB_DATA_DIR, otherwise fallback to the host path you mentioned
JOB_DATA_DIR = getattr(
    settings,
    "JOB_DATA_DIR",
    "/16Tbdrive1/evolf/evolf_docker/pipeline_runs",
)


class JobStatusAPIView(APIView):
    """
    GET /predict/job/<job_id>/
      - If output/ contains files -> return {"status":"finished","job_id":..., "output_files":[...]}
      - If ?download=output (or ?dl=output) and output/ has files -> return zip attachment of output/
      - Otherwise -> 404 {"error":"Job status not found"}
    """

    def get(self, request, job_id):
        job_dir = os.path.join(JOB_DATA_DIR, job_id)
        if not os.path.isdir(job_dir):
            return Response({"error": "Job not not found"}, status=status.HTTP_404_NOT_FOUND)

        output_dir = os.path.join(job_dir, "output")

        # gather output files (if any)
        output_files = []
        if os.path.isdir(output_dir):
            for root, _, filenames in os.walk(output_dir):
                for fn in filenames:
                    full = os.path.join(root, fn)
                    # include only real files (optionally skip zero-byte)
                    if os.path.isfile(full):
                        rel = os.path.relpath(full, job_dir)
                        output_files.append(rel)

            # If no output files yet -> job is still running / waiting
        if not output_files:
            return Response(
                {"status": "processing", "message": "Job started but no output files yet"},
                status=status.HTTP_200_OK
            )

        # if client requested download via query param
        download_param = request.query_params.get("download") or request.query_params.get("dl")
        if download_param and download_param.lower() == "output":
            return self._zip_and_serve(job_dir, job_id, output_dir)

        # Otherwise return finished + list of output files
        return Response(
            {"job_id": job_id, "status": "finished", "output_files": output_files},
            status=status.HTTP_200_OK,
        )

    def _zip_and_serve(self, job_dir: str, job_id: str, output_dir: str):
        """Create zip of output/ and return it as FileResponse (attachment)."""
        zip_name = f"{job_id}_output.zip"
        zip_path = os.path.join(job_dir, zip_name)

        try:
            # create/overwrite zip
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(output_dir):
                    for fname in files:
                        full_path = os.path.join(root, fname)
                        if os.path.isfile(full_path):
                            # keep relative paths inside zip (e.g. output/...)
                            rel_path = os.path.relpath(full_path, job_dir)
                            zf.write(full_path, arcname=rel_path)
        except Exception as e:
            return Response({"error": f"Failed to create zip archive: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            f = open(zip_path, "rb")
            return FileResponse(
                f,
                as_attachment=True,
                filename=zip_name,
                content_type="application/zip",
            )
        except Exception as e:
            return Response({"error": f"Failed to serve zip file: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DownloadOutputAPIView(APIView):
    """
    Convenience endpoint:
    GET /predict/download/<job_id>/ -> returns the same ZIP as ?download=output on job-status.
    """

    def get(self, request, job_id):
        # delegate to JobStatusAPIView._zip_and_serve-like behaviour
        job_dir = os.path.join(JOB_DATA_DIR, job_id)
        if not os.path.isdir(job_dir):
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)

        output_dir = os.path.join(job_dir, "output")
        # ensure there is at least one file
        has_files = False
        if os.path.isdir(output_dir):
            for _, _, filenames in os.walk(output_dir):
                if filenames:
                    has_files = True
                    break

        if not has_files:
            return Response({"error": "Output not found for job"}, status=status.HTTP_404_NOT_FOUND)

        # create zip path and stream it
        zip_name = f"{job_id}_output.zip"
        zip_path = os.path.join(job_dir, zip_name)

        try:
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(output_dir):
                    for fname in files:
                        full_path = os.path.join(root, fname)
                        if os.path.isfile(full_path):
                            rel_path = os.path.relpath(full_path, job_dir)
                            zf.write(full_path, arcname=rel_path)
        except Exception as e:
            return Response({"error": f"Failed to create zip archive: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            f = open(zip_path, "rb")
            return FileResponse(f, as_attachment=True, filename=zip_name, content_type="application/zip")
        except Exception as e:
            return Response({"error": f"Failed to serve zip file: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
