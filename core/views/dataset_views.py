# core/views/api_views.py
import csv
import io
import json
import zipfile
import datetime
import os
from django.http import HttpResponse, StreamingHttpResponse
from django.db.models import Q
from django.contrib.postgres.search import TrigramSimilarity
from rest_framework.views import APIView
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.conf import settings

from core.models import EvOlf
from core.serializers import EvOlfSerializer

# Pagination class reading limit param
class StandardResultsSetPagination(PageNumberPagination):
    page_size = int(os.getenv('DEFAULT_PAGE_SIZE', 20))
    page_size_query_param = 'limit'
    max_page_size = 1000

class DatasetListAPIView(APIView):
    """
    GET /api/dataset
    Supports pagination, filtering, sorting and search.
    """
    def get(self, request):
        # params
        page = int(request.GET.get('page', 1))
        limit = int(request.GET.get('limit', 20))
        search = request.GET.get('search', '').strip()
        sort_by = request.GET.get('sortBy', 'EvOlf_ID')
        sort_order = request.GET.get('sortOrder', 'desc')
        species = request.GET.get('species')
        class_filter = request.GET.get('class') or request.GET.get('classFilter')
        mutation_type = request.GET.get('mutationType')

        qs = EvOlf.objects.all()

        # filters
        if species:
            qs = qs.filter(Species__iexact=species)
        if class_filter:
            qs = qs.filter(Class__iexact=class_filter)
        if mutation_type:
            qs = qs.filter(Mutation_Status__iexact=mutation_type)

        # search: try to use ES first, fallback to trigram
        results_ids_ordered = None
        if search:
            try:
                # use absolute import to ensure the documents module is resolved correctly
                from core.documents import EvOlfDocument
                s = EvOlfDocument.search().query(
                    "multi_match",
                    query=search,
                    fields=['Receptor^3', 'UniProt_ID^4', 'Ligand^2', 'EvOlf_ID', 'SMILES', 'ChEMBL_ID'],
                    fuzziness='AUTO'
                )[:100]
                es_resp = s.execute()
                hits = list(es_resp.hits)
                if hits:
                    # normalize to top score and pick hits >= 0.8 threshold
                    scores = [h.meta.score or 0.0 for h in hits]
                    max_score = max(scores) if scores else 1.0
                    filtered_ids = []
                    for h in hits:
                        score = h.meta.score or 0.0
                        normalized = (score / max_score) if max_score > 0 else 0
                        if normalized >= 0.8:
                            # get EvOlf_ID from hit if present; fallback to id
                            evo_id = getattr(h, 'EvOlf_ID', None) or getattr(h, 'evolf_id', None)
                            if not evo_id:
                                # attempt to read from source
                                src = getattr(h, '_source', None)
                                evo_id = src.get('EvOlf_ID') if src else None
                            if evo_id:
                                filtered_ids.append(evo_id)
                    if filtered_ids:
                        results_ids_ordered = filtered_ids
            except Exception:
                # ES not available or error -> fallback to pg trigram
                results_ids_ordered = None

            if results_ids_ordered is None:
                # Postgres trigram fallback
                # requires pg_trgm extension installed
                qs = qs.annotate(similarity=TrigramSimilarity('Receptor', search)).filter(similarity__gt=0.2).order_by('-similarity')

        # if ES produced an ordered id list, apply filtering and keep DB objects in that order
        if results_ids_ordered:
            preserved = {k:i for i,k in enumerate(results_ids_ordered)}
            qs = EvOlf.objects.filter(EvOlf_ID__in=results_ids_ordered)
            # preserve ordering using Python sort after query (simple approach)
            qs = sorted(qs, key=lambda o: preserved.get(o.EvOlf_ID, 999999))

        # sorting
        ordering = f"{'' if sort_order=='asc' else '-'}{sort_by}"
        try:
            qs = qs.order_by(ordering)
        except Exception:
            # fallback if sort_by invalid
            qs = qs.order_by('-EvOlf_ID')

        # pagination
        paginator = StandardResultsSetPagination()
        paginator.page_size = limit
        page_obj = paginator.paginate_queryset(qs, request)
        serializer = EvOlfSerializer(page_obj, many=True)
        # stats
        stats = {
            "totalReceptors": EvOlf.objects.values('Receptor').distinct().count(),
            "totalLigands": EvOlf.objects.values('Ligand').distinct().count(),
            "totalMutations": EvOlf.objects.exclude(Mutation__isnull=True).count(),
            "totalSpecies": EvOlf.objects.values('Species').distinct().count()
        }
        return paginator.get_paginated_response({
            "data": serializer.data,
            "statistics": stats
        })

class DatasetExportAPIView(APIView):
    """
    POST /api/dataset/export
    Body: {"evolfIds": ["EVOLF001234","EVOLF..."]}
    Returns: ZIP file (data.csv, metadata.json, README.txt)
    """
    def post(self, request):
        data = request.data
        evolf_ids = data.get('evolfIds') or []
        if not isinstance(evolf_ids, list) or len(evolf_ids) == 0:
            return Response({"error": "evolfIds array is required and must not be empty"}, status=400)

        qs = EvOlf.objects.filter(EvOlf_ID__in=evolf_ids)
        if not qs.exists():
            return Response({"error": "No records found for given evolfIds"}, status=404)

        # Build CSV in memory
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        # header fields - choose fields to export
        fields = ['EvOlf_ID','Receptor','Species','Class','Ligand','Mutation_Status','Mutation','Value','Unit','Source']
        writer.writerow(fields)
        for obj in qs:
            row = [getattr(obj, f, '') for f in fields]
            writer.writerow(row)
        csv_data = csv_buffer.getvalue()

        # metadata
        metadata = {
            "exportDate": datetime.datetime.utcnow().isoformat() + 'Z',
            "totalRecords": qs.count(),
            "evolfIds": evolf_ids,
            "format": "csv",
            "version": "1.0"
        }
        metadata_json = json.dumps(metadata, indent=2)

        # README text
        readme_text = "EvoLF selected export. Columns: " + ", ".join(fields)

        # create zip file in memory
        mem_zip = io.BytesIO()
        with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('data.csv', csv_data)
            zf.writestr('metadata.json', metadata_json)
            zf.writestr('README.txt', readme_text)
        mem_zip.seek(0)
        response = HttpResponse(mem_zip.read(), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="evolf_selected_data.zip"'
        return response

class DatasetDownloadAPIView(APIView):
    """
    GET /api/dataset/download
    Returns a full dataset zip. This will generate on-demand (could be heavy).
    For production, pre-generate and serve statically.
    """
    def get(self, request):
        qs = EvOlf.objects.all()
        # build CSV stream (in memory)
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        fields = ['EvOlf_ID','Receptor','Species','Class','Ligand','Mutation_Status','Mutation','Value','Unit','Source']
        writer.writerow(fields)
        for obj in qs.iterator():
            row = [getattr(obj, f, '') for f in fields]
            writer.writerow(row)
        csv_data = csv_buffer.getvalue()

        metadata = {
            "exportDate": datetime.datetime.utcnow().isoformat() + 'Z',
            "totalRecords": qs.count(),
            "version": "1.0",
            "statistics": {
                "totalReceptors": EvOlf.objects.values('Receptor').distinct().count(),
                "totalLigands": EvOlf.objects.values('Ligand').distinct().count(),
            }
        }
        metadata_json = json.dumps(metadata, indent=2)
        readme_text = "EvoLF complete dataset export."

        mem_zip = io.BytesIO()
        with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('evolf_complete_data.csv', csv_data)
            zf.writestr('metadata.json', metadata_json)
            zf.writestr('README.txt', readme_text)
        mem_zip.seek(0)
        response = HttpResponse(mem_zip.read(), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="evolf_complete_dataset.zip"'
        return response
