import csv
import io
import json
import zipfile
import datetime
import os

from django.http import HttpResponse
from django.db.models import Q
from django.contrib.postgres.search import TrigramSimilarity
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from core.models import EvOlf
from core.serializers import EvOlfSerializer

# ES import
try:
    from elasticsearch import Elasticsearch
    es = Elasticsearch(
        "http://localhost:9200",
        basic_auth=("elastic", "HSoMIJHnTnrIiueNgCP2"),
        verify_certs=False
    )
    ES_AVAILABLE = True
except Exception:
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

        qs = EvOlf.objects.all()

        # --- Apply filters
        if species:
            qs = qs.filter(Species__iexact=species)
        if class_filter:
            qs = qs.filter(Class__iexact=class_filter)
        if mutation_type:
            qs = qs.filter(Mutation_Status__iexact=mutation_type)

        results_ids_ordered = None

        # --- Run ES search (if available)
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
                    results_ids_ordered = [
                        hit["_source"].get("EvOlf_ID") for hit in res["hits"]["hits"]
                    ]
            except Exception:
                results_ids_ordered = None

            # --- Fallback to Postgres trigram if ES fails
            if not results_ids_ordered:
                qs = qs.annotate(similarity=TrigramSimilarity('Receptor', search)) \
                       .filter(similarity__gt=0.2) \
                       .order_by('-similarity')

        # --- Maintain ES ordering
        if results_ids_ordered:
            preserved = {eid: i for i, eid in enumerate(results_ids_ordered)}
            qs = EvOlf.objects.filter(EvOlf_ID__in=results_ids_ordered)
            qs = sorted(qs, key=lambda o: preserved.get(o.EvOlf_ID, 999999))

        # --- Sorting
        if isinstance(qs, list):
            reverse = sort_order == "desc"
            qs = sorted(qs, key=lambda x: getattr(x, sort_by, ""), reverse=reverse)

        else:
            ordering = sort_by if sort_order == "asc" else f"-{sort_by}"
            qs = qs.order_by(ordering)

        # --- Stats before pagination
        all_qs = EvOlf.objects.all()

        global_stats = {
            "totalReceptors": EvOlf.objects.values('Receptor').distinct().count(),
            "totalLigands": EvOlf.objects.values('Ligand').distinct().count(),
            "totalMutations": EvOlf.objects.exclude(Mutation__isnull=True).count(),
            "totalSpecies": EvOlf.objects.values('Species').distinct().count(),
            "uniqueClasses": list(all_qs.values_list('Class', flat=True).distinct()),
            "uniqueSpecies": list(all_qs.values_list('Species', flat=True).distinct()),
            "uniqueMutationTypes": list(all_qs.values_list('Mutation_Status', flat=True).distinct()),
        }

        # --- Pagination
        paginator = StandardResultsSetPagination()
        paginator.page_size = limit
        page_obj = paginator.paginate_queryset(qs, request)
        serializer = EvOlfSerializer(page_obj, many=True)



        # --- Return data
        if isinstance(qs, list):
            total_rows = len(qs)
            unique_classes = list({obj.Class for obj in qs if obj.Class})
            unique_species = list({obj.Species for obj in qs if obj.Species})
            unique_mutation_types = list({obj.Mutation_Status for obj in qs if obj.Mutation_Status})
        else:
            total_rows = qs.count()
            unique_classes = list(qs.values_list('Class', flat=True).distinct())
            unique_species = list(qs.values_list('Species', flat=True).distinct())
            unique_mutation_types = list(qs.values_list('Mutation_Status', flat=True).distinct())

        filtered_stats = {
            "totalRows": total_rows,
            "uniqueClasses": unique_classes,
            "uniqueSpecies": unique_species,
            "uniqueMutationTypes": unique_mutation_types,
        }


        filter_options = {
            "classes": list(EvOlf.objects.values_list("Class", flat=True).distinct()),
            "species": list(EvOlf.objects.values_list("Species", flat=True).distinct()),
            "mutationTypes": list(EvOlf.objects.values_list("Mutation_Status", flat=True).distinct()),
        }

        pagination_info = {
            "currentPage": page,
            "totalPages": (total_rows + limit - 1) // limit,
            "totalItems": total_rows ,
            "itemsPerPage": limit,
            }

                        
        return Response({
            "data": serializer.data,
            "pagination": pagination_info,
            "global statistics": global_stats,
            "filtered statiscs": filtered_stats,
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
            'Mutation_Status', 'Mutation', 'ChEMBL_ID', 'UniProt_ID', 'Ensembl_ID'
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
    CACHE_PATH = os.path.join("core", "management", "evolf_complete_dataset.zip")

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
            'Mutation_Status', 'Mutation', 'ChEMBL_ID', 'UniProt_ID', 'Ensembl_ID'
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
