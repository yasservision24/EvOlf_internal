import csv
import io
import json
import zipfile
import datetime
import os

from django.http import HttpResponse
from django.http import JsonResponse, FileResponse, Http404
from django.db.models import Q
from django.contrib.postgres.search import TrigramSimilarity
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework import status
import math
import json
from core.models import EvOlf
from core.serializers import EvOlfSerializer
from core.views.structure_views import format_dataset_detail, FetchLocalStructureAPIView
import pandas as pd
from django.conf import settings

# ES import
try:
    from elasticsearch import Elasticsearch

    # Load environment variables
    ES_HOST = os.getenv("ELASTIC_HOST", "http://localhost:9200")
    ES_USERNAME = os.getenv("ELASTIC_USERNAME", "")
    ES_PASSWORD = os.getenv("ELASTIC_PASSWORD", "")

    es = Elasticsearch(
        ES_HOST,
        basic_auth=(ES_USERNAME, ES_PASSWORD),
        verify_certs=False  # Set to True if using HTTPS with valid certs
    )

    # Check if connection works
    if es.ping():
        print(f"✅ Connected to Elasticsearch at {ES_HOST}")
        ES_AVAILABLE = True
    else:
        print("⚠️ Could not connect to Elasticsearch.")
        ES_AVAILABLE = False

except Exception as e:
    print(f"❌ Elasticsearch connection error: {e}")
    ES_AVAILABLE = False

# -------------------------------
# Pagination
# -------------------------------
class StandardResultsSetPagination(PageNumberPagination):
    page_size = int(os.getenv('DEFAULT_PAGE_SIZE', 20))
    page_size_query_param = 'limit'
    max_page_size = 1000


# -------------------------------
# Dataset List (with ES fallback)
# -------------------------------
class DatasetListAPIView(APIView):
    """
    GET /api/dataset
    Supports pagination, filtering, sorting, and search.
    """
    def get(self, request):
        page = int(request.GET.get('page', 1))
        limit = int(request.GET.get('limit', 20))
        search = request.GET.get('search', '').strip()
        sort_by = request.GET.get('sortBy', 'EvOlf_ID')
        sort_order = request.GET.get('sortOrder', 'desc')
        species = request.GET.get('species')
        class_filter = request.GET.get('class') or request.GET.get('classFilter')
        mutation_type = request.GET.get('mutationType')

        # Base queryset
        base_qs = EvOlf.objects.all()
        qs = EvOlf.objects.all()


        # --- Step 1: Search Phase ---
        results_ids_ordered = None
        if search:
            try:
                if ES_AVAILABLE:
                    body = {
                        "query": {
                            "bool": {
                                "should": [
                                    {"wildcard": {"Receptor": {"value": f"*{search}*", "case_insensitive": True}}},
                                    {"wildcard": {"Ligand": {"value": f"*{search}*", "case_insensitive": True}}},
                                    {"wildcard": {"Species": {"value": f"*{search}*", "case_insensitive": True}}}
                                ]
                            }
                        }
                    }
                    res = es.search(index="evolf", body=body)
                    results_ids_ordered = [hit["_source"].get("EvOlf_ID") for hit in res["hits"]["hits"]]
            except Exception:
                results_ids_ordered = None

        # Fallback to Postgres trigram
        if search and not results_ids_ordered:
            search_qs = base_qs.annotate(similarity=TrigramSimilarity('Receptor', search)) \
                            .filter(similarity__gt=0.2) \
                            .order_by('-similarity')
        elif results_ids_ordered:
            preserved = {eid: i for i, eid in enumerate(results_ids_ordered)}
            search_qs = EvOlf.objects.filter(EvOlf_ID__in=results_ids_ordered)
            search_qs = sorted(search_qs, key=lambda o: preserved.get(o.EvOlf_ID, 999999))
        else:
            search_qs = base_qs  # no search term

        # --- Step 2: Build Search Statistics (before filters)
        if isinstance(search_qs, list):
            unique_classes = list({obj.Class for obj in search_qs if obj.Class})
            unique_species = list({obj.Species for obj in search_qs if obj.Species})
            unique_mutation_types = list({obj.Mutation_Status for obj in search_qs if obj.Mutation_Status})
            total_rows = len(search_qs)
        else:
            unique_classes = list(search_qs.values_list('Class', flat=True).distinct())
            unique_species = list(search_qs.values_list('Species', flat=True).distinct())
            unique_mutation_types = list(search_qs.values_list('Mutation_Status', flat=True).distinct())
            total_rows = search_qs.count()

        statistics = {
            "totalRows": total_rows,
            "uniqueClasses": unique_classes,
            "uniqueSpecies": unique_species,
            "uniqueMutationTypes": unique_mutation_types,
        }

        # --- Step 3: Apply Filters ---
        # --- Apply filters
        def apply_filters_to_queryset(queryset):
            if species:
                queryset = queryset.filter(Species__iexact=species)
            if class_filter:
                queryset = queryset.filter(Class__iexact=class_filter)
            if mutation_type:
                queryset = queryset.filter(Mutation_Status__iexact=mutation_type)
            return queryset

        def apply_filters_to_list(data_list):
            filtered = data_list
            if species:
                filtered = [obj for obj in filtered if getattr(obj, "Species", None) == species]
            if class_filter:
                filtered = [obj for obj in filtered if getattr(obj, "Class", None) == class_filter]
            if mutation_type:
                filtered = [obj for obj in filtered if getattr(obj, "Mutation_Status", None) == mutation_type]
            return filtered
        
        # --- Maintain ES ordering
        if results_ids_ordered:
            preserved = {eid: i for i, eid in enumerate(results_ids_ordered)}
            qs = list(EvOlf.objects.filter(EvOlf_ID__in=results_ids_ordered))
            qs.sort(key=lambda o: preserved.get(o.EvOlf_ID, 999999))
            qs = apply_filters_to_list(qs)
        else:
            qs = apply_filters_to_queryset(qs)



        # --- Step 4: Sorting ---
        if isinstance(qs, list):
            reverse = sort_order == "desc"
            qs = sorted(qs, key=lambda x: getattr(x, sort_by, ""), reverse=reverse)
        else:
            ordering = sort_by if sort_order == "asc" else f"-{sort_by}"
            qs = qs.order_by(ordering)

        # --- Step 5: Pagination ---
        paginator = StandardResultsSetPagination()
        paginator.page_size = limit
        page_obj = paginator.paginate_queryset(qs, request)
        serializer = EvOlfSerializer(page_obj, many=True)

        pagination_info = {
            "currentPage": page,
            "totalPages": (len(qs) if isinstance(qs, list) else qs.count() + limit - 1) // limit,
            "totalItems": len(qs) if isinstance(qs, list) else qs.count(),
            "itemsPerPage": limit,
        }

        # --- Step 6: Filter Options ---
        filter_options = {
            "uniqueClasses": statistics["uniqueClasses"],
            "uniqueSpecies": statistics["uniqueSpecies"],
            "uniqueMutationTypes": statistics["uniqueMutationTypes"],
        }

        pagination_info = {
            "currentPage": page,
            "totalPages": (total_rows + limit - 1) // limit,
            "totalItems": total_rows ,
            "itemsPerPage": limit,
            }
        statistics.update({"totalRows": total_rows})

                        
        return Response({
            "data": serializer.data,
            "pagination": pagination_info,
            "statistics": statistics,
            "filterOptions": filter_options,
            "all_evolf_ids": [obj.EvOlf_ID for obj in qs],
        })

        


# -------------------------------
# Dataset Export (2 modes)
# -------------------------------
class DatasetExportAPIView(APIView):
    """
    POST /api/dataset/export
    Case A: body = {"evolfIds": [...]} → export those
    Case B: body = filters (species, class, search, etc.) → re-run query and export results
    """
    def post(self, request):
        data = request.data
        evolf_ids = data.get('evolfIds')

        # --- CASE A: frontend sends IDs directly
        if isinstance(evolf_ids, list) and len(evolf_ids) > 0:
            qs = EvOlf.objects.filter(EvOlf_ID__in=evolf_ids)
        else:
            # --- CASE B: no IDs -> re-run query logic
            search = data.get('search', '').strip()
            species = data.get('species')
            class_filter = data.get('class') or data.get('classFilter')
            mutation_type = data.get('mutationType')
            sort_by = data.get('sortBy', 'EvOlf_ID')
            sort_order = data.get('sortOrder', 'desc')

            qs = EvOlf.objects.all()
            if species:
                qs = qs.filter(Species__iexact=species)
            if class_filter:
                qs = qs.filter(Class__iexact=class_filter)
            if mutation_type:
                qs = qs.filter(Mutation_Status__iexact=mutation_type)

            # Try ElasticSearch first
            results_ids_ordered = None
            if search and ES_AVAILABLE:
                try:
                    body = {
                        "query": {
                            "bool": {
                                "should": [
                                    {"wildcard": {"Receptor": {"value": f"*{search}*", "case_insensitive": True}}},
                                    {"wildcard": {"Ligand": {"value": f"*{search}*", "case_insensitive": True}}},
                                    {"wildcard": {"Species": {"value": f"*{search}*", "case_insensitive": True}}}
                                ]
                            }
                        }
                    }
                    res = es.search(index="evolf", body=body)
                    results_ids_ordered = [hit["_source"].get("EvOlf_ID") for hit in res["hits"]["hits"]]
                except Exception:
                    results_ids_ordered = None

            # Fallback to trigram
            if search and not results_ids_ordered:
                qs = qs.annotate(similarity=TrigramSimilarity('Receptor', search)) \
                       .filter(similarity__gt=0.2) \
                       .order_by('-similarity')

            # Maintain ES order
            if results_ids_ordered:
                preserved = {eid: i for i, eid in enumerate(results_ids_ordered)}
                qs = EvOlf.objects.filter(EvOlf_ID__in=results_ids_ordered)
                qs = sorted(qs, key=lambda o: preserved.get(o.EvOlf_ID, 999999))

            # Sorting
                        
            if isinstance(qs, list):
                reverse = sort_order == "desc"
                qs = sorted(qs, key=lambda x: getattr(x, sort_by, ""), reverse=reverse)

            else:
                ordering = sort_by if sort_order == "asc" else f"-{sort_by}"
                qs = qs.order_by(ordering)


        # --- No records found
        if not qs:
            return Response({"error": "No records found for given filters or IDs"}, status=404)

        # --- Build ZIP
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        fields = [
            'EvOlf_ID', 'Receptor', 'Species', 'Class', 'Ligand',
            'Mutation_Status', 'Mutation', 'ChEMBL_ID', 'UniProt_ID', 'CID'
        ]

        
        writer.writerow(fields)
        for obj in qs:
            writer.writerow([getattr(obj, f, '') for f in fields])

        metadata = {
            "exportDate": datetime.datetime.utcnow().isoformat() + 'Z',
            "totalRecords": len(qs),
            "format": "csv",
            "version": "1.0"
        }
        mem_zip = io.BytesIO()
        with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("data.csv", csv_buffer.getvalue())
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))
            zf.writestr("README.txt", "EvoLF dataset export containing filtered data.")
        mem_zip.seek(0)
        response = HttpResponse(mem_zip.read(), content_type="application/zip")
        response["Content-Disposition"] = "attachment; filename=evolf_filtered_export.zip"
        return response


# -------------------------------
# Complete dataset ZIP
# -------------------------------
class DatasetDownloadAPIView(APIView):
    """
    GET /api/dataset/download
    Pre-generates and caches a full ZIP once, reused afterward.
    """
    CACHE_PATH = os.path.join(settings.BASE_DIR,settings.PATH_AFTER_BASE_DIR, "evolf_complete_dataset.zip")

    def get(self, request):
        if os.path.exists(self.CACHE_PATH):
            with open(self.CACHE_PATH, "rb") as f:
                zip_data = f.read()
        else:
            qs = EvOlf.objects.all()
            csv_buffer = io.StringIO()
            writer = csv.writer(csv_buffer)
            fields = [
            'EvOlf_ID', 'Receptor', 'Species', 'Class', 'Ligand',
            'Mutation_Status', 'Mutation', 'ChEMBL_ID', 'UniProt_ID', 'CID'
            ]
            writer.writerow(fields)
            for obj in qs.iterator():
                writer.writerow([getattr(obj, f, '') for f in fields])

            metadata = {
                "exportDate": datetime.datetime.utcnow().isoformat() + 'Z',
                "totalRecords": qs.count(),
                "version": "1.0"
            }
            mem_zip = io.BytesIO()
            with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("evolf_complete_data.csv", csv_buffer.getvalue())
                zf.writestr("metadata.json", json.dumps(metadata, indent=2))
                zf.writestr("README.txt", "EvoLF complete dataset export.")
            mem_zip.seek(0)
            zip_data = mem_zip.read()
            with open(self.CACHE_PATH, "wb") as f:
                f.write(zip_data)

        response = HttpResponse(zip_data, content_type="application/zip")
        response["Content-Disposition"] = "attachment; filename=evolf_complete_dataset.zip"
        return response






def json_safe(obj):
    """Recursively convert non-serializable / NaN / inf values to None or strings."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [json_safe(v) for v in obj]
    return obj


from core.views.structure_views import format_dataset_detail, FetchLocalStructureAPIView

import os
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from core.models import EvOlf
from core.views.structure_views import format_dataset_detail



# ============================================================
# 1️⃣ FETCH DATASET DETAILS
# ============================================================

class FetchDatasetDetails(APIView):
    """
    GET /api/dataset/details/<evolfId>/
    Returns JSON exactly in README format (keys and default types/values).
    """
    def get(self, request, evolfId):
        try:
            csv_path = os.path.join(settings.BASE_DIR,settings.PATH_AFTER_BASE_DIR,"evolf_data.csv")
            if not os.path.exists(csv_path):
                return Response({"error": "Dataset CSV not found", "path": csv_path}, status=status.HTTP_404_NOT_FOUND)

            df = pd.read_csv(csv_path)

            # Accept either column name "EvOlf ID" or "EvOlf_ID"
            id_col = "EvOlf ID" if "EvOlf ID" in df.columns else ("EvOlf_ID" if "EvOlf_ID" in df.columns else None)
            if not id_col:
                return Response({"error": "Missing EvOlf_ID column in dataset"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            rows = df[df[id_col] == evolfId].to_dict(orient="records")
            if not rows:
                return Response({"error": "Entry not found", "message": f"No record with EvOlf ID: {evolfId}"}, status=status.HTTP_404_NOT_FOUND)

            entry = rows[0]

            # Build formatted data using centralized formatter (passes request for URL building)
            formatted = format_dataset_detail(entry, request=request)

            # Ensure exact README ordering/keys: produce dict with those keys
            # format_dataset_detail already returns keys matching README, so just sanitize
            cleaned = json_safe(formatted)

            return Response(cleaned, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": "Server Error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ============================================================
#  DOWNLOAD FILES AS ZIP
# ============================================================

class DownloadByEvolfId(APIView):
    def get(self, request, evolfId):
        base_dir = settings.MEDIA_ROOT
        files_to_zip = []

        # Paths for PDB, SDF, and image files
        paths = {
            "pdb": os.path.join(base_dir, 'pdb_files', f'{evolfId}.pdb'),
            "sdf": os.path.join(base_dir, 'sdf_files', f'{evolfId}.sdf'),
            "img": os.path.join(base_dir, 'smiles_2d', f'{evolfId}.png')
        }

        for p in paths.values():
            if os.path.exists(p):
                files_to_zip.append(p)

        # If no files exist, we still proceed because we'll add CSV row
        if not files_to_zip:
            files_to_zip = []

        # 🧠 Step 1: Fetch row data for this EvOlf ID
        try:
            csv_path = os.path.join(
                settings.BASE_DIR,
                settings.PATH_AFTER_BASE_DIR,
                "evolf_data.csv"
            )
            df = pd.read_csv(csv_path)
            id_col = "EvOlf ID" if "EvOlf ID" in df.columns else "EvOlf_ID"
            row_df = df[df[id_col] == evolfId]
        except Exception as e:
            row_df = pd.DataFrame()
            print("Error fetching row data:", e)

        # 🧠 Step 2: Prepare ZIP
        zip_filename = f"{evolfId}_data.zip"
        zip_path = os.path.join(base_dir, zip_filename)

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add files if available
            for f in files_to_zip:
                zipf.write(f, os.path.basename(f))

            # 🧠 Step 3: Add CSV row if available
            if not row_df.empty:
                csv_buffer = io.StringIO()
                row_df.to_csv(csv_buffer, index=False)
                zipf.writestr(f"{evolfId}_data.csv", csv_buffer.getvalue())
            else:
                zipf.writestr("note.txt", f"No matching row found for {evolfId}")

            # 🧠 Step 4: Add README / Metadata
            metadata = {
                "EvOlf_ID": evolfId,
                "exportDate": datetime.datetime.utcnow().isoformat() + "Z",
                "containsFiles": [os.path.basename(f) for f in files_to_zip],
                "containsCSV": not row_df.empty,
                "version": "1.1"
            }
            zipf.writestr("metadata.json", json.dumps(metadata, indent=2))
            zipf.writestr("README.txt", f"All available files and data for {evolfId}.")

        # 🧠 Step 5: Return the ZIP as a downloadable file
        response = FileResponse(open(zip_path, 'rb'), as_attachment=True, filename=zip_filename)
        return response
