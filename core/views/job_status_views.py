# predict/views.py
import os
import csv
import zipfile
from django.conf import settings
from django.http import FileResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

JOB_DATA_DIR = getattr(settings, "JOB_DATA_DIR", None)


class JobStatusAPIView(APIView):
    """
    GET /predict/job/<job_id>/
      - If output/ contains files -> return {"status":"finished","job_id":..., "output_files":[...], "predictions":[...]}
      - If ?download=output (or ?dl=output) and output/ has files -> return zip attachment of output/
      - Otherwise -> 404 {"error":"Job status not found"}
    """

    def get(self, request, job_id):
        job_dir = os.path.join(JOB_DATA_DIR, job_id)
        if not os.path.isdir(job_dir):
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)

        output_dir = os.path.join(job_dir, "output")
        input_dir = os.path.join(job_dir, "input")

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

        # Parse prediction results from CSV files
        predictions = self._parse_prediction_results(output_dir, input_dir)

        # Otherwise return finished + list of output files + predictions
        return Response(
            {
                "job_id": job_id,
                "status": "finished",
                "output_files": output_files,
                "predictions": predictions
            },
            status=status.HTTP_200_OK,
        )

    def _parse_prediction_results(self, output_dir: str, input_dir: str) -> list:
        """
        Parse Prediction_Output.csv and input CSV to combine results.
        Returns list of dicts with: ID, Temp_Ligand_ID, SMILES, Mutated_Sequence, TempRecID, Predicted_Label, P1
        Converts 1 to "Agonist (1)" and 0 to "Non-Agonist (0)"
        """
        predictions = []
        
        # Read output predictions
        output_csv_path = os.path.join(output_dir, "Prediction_Output.csv")
        output_data = {}
        
        if os.path.isfile(output_csv_path):
            try:
                with open(output_csv_path, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # The output CSV should have 'ID' column that matches input CSV
                        row_id = row.get('ID', '').strip()
                        if row_id:
                            # Get predicted label and convert to human-readable format
                            pred_label_raw = row.get('Predicted Label', '').strip()
                            # Convert 1 to "Agonist (1)" and 0 to "Non-Agonist (0)"
                            if pred_label_raw == '1':
                                pred_label = "Agonist (1)"
                            elif pred_label_raw == '0':
                                pred_label = "Non-Agonist (0)"
                            else:
                                pred_label = pred_label_raw  # Keep as is if not 0 or 1
                            
                            output_data[row_id] = {
                                'predicted_label': pred_label,
                                'p1': row.get('P1', '').strip()
                            }
            except Exception as e:
                print(f"Error reading output CSV: {e}")

        # Read input CSV to get original data (ID, Temp_Ligand_ID, SMILES, Mutated_Sequence, TempRecID)
        input_data = {}
        if os.path.isdir(input_dir):
            for fn in os.listdir(input_dir):
                if fn.endswith('.csv'):
                    input_csv_path = os.path.join(input_dir, fn)
                    try:
                        with open(input_csv_path, 'r', newline='', encoding='utf-8') as f:
                            reader = csv.DictReader(f)
                            for row in reader:
                                # Use the actual ID column from input CSV (should be numeric string like "1", "2", etc.)
                                row_id = row.get('ID', '').strip()
                                if row_id:
                                    input_data[row_id] = {
                                        'temp_ligand_id': row.get('Temp_Ligand_ID', '').strip(),
                                        'smiles': row.get('SMILES', '').strip(),
                                        'mutated_sequence': row.get('Mutated_Sequence', '').strip(),
                                        'temp_rec_id': row.get('TempRecID', '').strip()
                                    }
                    except Exception as e:
                        print(f"Error reading input CSV: {e}")
                    break  # Only read first CSV found

        # Combine output and input data using the ID as key
        # First, try to match by ID
        matched_ids = set()
        for row_id, out_row in output_data.items():
            in_row = input_data.get(row_id)
            if in_row:
                predictions.append({
                    'id': row_id,
                    'temp_ligand_id': in_row.get('temp_ligand_id', ''),
                    'smiles': in_row.get('smiles', ''),
                    'mutated_sequence': in_row.get('mutated_sequence', ''),
                    'temp_rec_id': in_row.get('temp_rec_id', ''),
                    'predicted_label': out_row.get('predicted_label', ''),
                    'p1': out_row.get('p1', '')
                })
                matched_ids.add(row_id)
            else:
                # If no match found by ID, include output data only
                predictions.append({
                    'id': row_id,
                    'temp_ligand_id': '',
                    'smiles': '',
                    'mutated_sequence': '',
                    'temp_rec_id': '',
                    'predicted_label': out_row.get('predicted_label', ''),
                    'p1': out_row.get('p1', '')
                })

        # Also include any input rows that didn't have output predictions
        for row_id, in_row in input_data.items():
            if row_id not in matched_ids:
                predictions.append({
                    'id': row_id,
                    'temp_ligand_id': in_row.get('temp_ligand_id', ''),
                    'smiles': in_row.get('smiles', ''),
                    'mutated_sequence': in_row.get('mutated_sequence', ''),
                    'temp_rec_id': in_row.get('temp_rec_id', ''),
                    'predicted_label': '',
                    'p1': ''
                })

        # Sort by ID for consistent ordering
        predictions.sort(key=lambda x: int(x['id']) if x['id'].isdigit() else 0)
        
        return predictions

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