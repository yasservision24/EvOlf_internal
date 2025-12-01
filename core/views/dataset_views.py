import csv
import io
import json
import zipfile
import datetime
import os
import math
import re

from django.http import HttpResponse, JsonResponse, FileResponse, Http404
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework import status
import pandas as pd
from django.conf import settings

from core.models import EvOlf
from core.serializers import EvOlfSerializer
from core.views.structure_views import format_dataset_detail, FetchLocalStructureAPIView

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
        verify_certs=False
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
# Enhanced Search Functions
# -------------------------------

def build_elasticsearch_query(search_term, filters=None):
    """
    Build a robust Elasticsearch query with multiple search strategies
    """
    if not search_term:
        # Return all results if no search term - no size limit for retrieving IDs
        query_body = {
            "query": {"match_all": {}},
            "_source": ["EvOlf_ID"],  # Only retrieve EvOlf_ID for efficiency
            "size": 10000  # Max window size in ES, but we'll handle this via scrolling if needed
        }
        
        if filters:
            filter_clauses = []
            if filters.get('species'):
                filter_clauses.append({"term": {"Species": filters['species']}})
            if filters.get('class_filter'):
                filter_clauses.append({"term": {"Class": filters['class_filter']}})
            if filters.get('mutation_type'):
                filter_clauses.append({"term": {"Mutation_Status": filters['mutation_type']}})
            
            if filter_clauses:
                query_body["query"] = {"bool": {"filter": filter_clauses}}
                
        return query_body

    # Check if search looks like an ID (alphanumeric with possible underscores/dashes)
    is_id_like = re.match(r'^[a-zA-Z0-9_-]+$', search_term) if search_term else False
    
    # Check if search looks like a chemical identifier
    is_chemical_like = any(char in search_term for char in ['@', '+', '-', '(', ')', '=', '#']) if search_term else False
    
    # Build the base query
    base_query = {
        "query": {
            "bool": {
                "should": [
                    # Exact match on IDs (highest priority)
                    {
                        "multi_match": {
                            "query": search_term,
                            "fields": ["EvOlf_ID^10","Receptor^9" ,"Ligand^8" "UniProt_ID^8", "CID^8"],
                            "type": "phrase",
                            "boost": 5.0
                        }
                    } if is_id_like else {
                        "multi_match": {
                            "query": search_term,
                            "fields": ["EvOlf_ID^10","Receptor^9" ,"Ligand^8" "UniProt_ID^8", "CID^8"],
                            "boost": 3.0
                        }
                    },
                    
                    # Field-specific weighted search
                    {
                        "multi_match": {
                            "query": search_term,
                            "fields": [
                                "EvOlf_ID^6",
                                "Ligand^5", 
                                "Receptor^5",
                                "Species^4",
                                "ChEMBL_ID^4",
                                "UniProt_ID^4", 
                                "CID^4",
                                "Class^3",
                                "Mutation^2",
                                "Sequence^1"
                            ],
                            "type": "best_fields",
                            "fuzziness": "AUTO",
                            "boost": 2.0
                        }
                    },
                    
                    # Wildcard search for partial matches
                    {
                        "bool": {
                            "should": [
                                {"wildcard": {"EvOlf_ID": {"value": f"*{search_term}*", "case_insensitive": True}}},
                                {"wildcard": {"Ligand": {"value": f"*{search_term}*", "case_insensitive": True}}},
                                {"wildcard": {"Receptor": {"value": f"*{search_term}*", "case_insensitive": True}}},
                                {"wildcard": {"Species": {"value": f"*{search_term}*", "case_insensitive": True}}},
                                {"wildcard": {"CID": {"value": f"*{search_term}*", "case_insensitive": True}}},
                                {"wildcard": {"UniProt_ID": {"value": f"*{search_term}*", "case_insensitive": True}}}
                            ]
                        }
                    },
                    
                    # Chemical-specific search if it looks like a chemical
                    {
                        "multi_match": {
                            "query": search_term,
                            "fields": ["Ligand^6", "SMILES^4"],
                            "type": "phrase"
                        }
                    } if is_chemical_like else None,
                    
                    # Completion suggester for autocomplete
                    {
                        "match_phrase_prefix": {
                            "Ligand": {
                                "query": search_term,
                                "boost": 1.5
                            }
                        }
                    }
                ],
                "minimum_should_match": 1
            }
        },
        "suggest": {
            "autocomplete_suggest": {
                "prefix": search_term,
                "completion": {
                    "field": "suggest",
                    "fuzzy": {
                        "fuzziness": 1
                    }
                }
            },
            "ligand_suggest": {
                "text": search_term,
                "term": {
                    "field": "Ligand"
                }
            }
        },
        "highlight": {
            "fields": {
                "EvOlf_ID": {},
                "Ligand": {},
                "Receptor": {},
                "Species": {},
                "CID": {},
                "UniProt_ID": {}
            }
        },
        "size": 10000  # Max window size in ES
    }
    
    # Remove None values from should clauses
    base_query["query"]["bool"]["should"] = [clause for clause in base_query["query"]["bool"]["should"] if clause is not None]
    
    # Apply filters if provided
    if filters:
        filter_clauses = []
        
        if filters.get('species'):
            filter_clauses.append({"term": {"Species": filters['species']}})
        
        if filters.get('class_filter'):
            filter_clauses.append({"term": {"Class": filters['class_filter']}})
            
        if filters.get('mutation_type'):
            filter_clauses.append({"term": {"Mutation_Status": filters['mutation_type']}})
        
        if filter_clauses:
            base_query["query"]["bool"]["filter"] = filter_clauses
    
    return base_query

def search_with_elasticsearch(search_term, filters=None):
    """
    Perform Elasticsearch search with enhanced functionality
    """
    if not ES_AVAILABLE:
        return None, None, None
    
    try:
        query_body = build_elasticsearch_query(search_term, filters)
        response = es.search(index="evolf", body=query_body)
        
        # Extract results with highlighting
        results = []
        for hit in response.get("hits", {}).get("hits", []):
            source = hit["_source"]
            highlight = hit.get("highlight", {})
            
            result = {
                "EvOlf_ID": source.get("EvOlf_ID"),
                "Ligand": source.get("Ligand"),
                "Receptor": source.get("Receptor"),
                "Species": source.get("Species"),
                "Class": source.get("Class"),
                "Mutation_Status": source.get("Mutation_Status"),
                "ChEMBL_ID": source.get("ChEMBL_ID"),
                "UniProt_ID": source.get("UniProt_ID"),
                "CID": source.get("CID"),
                "highlight": highlight,
                "score": hit.get("_score", 0)
            }
            results.append(result)
        
        # Extract autocomplete suggestions
        suggestions = []
        for sug in response.get("suggest", {}).get("autocomplete_suggest", []):
            for opt in sug.get("options", []):
                text = opt.get("text")
                if text and text not in suggestions:
                    suggestions.append(text)
        
        # Extract search metadata
        total_hits = response.get("hits", {}).get("total", {}).get("value", 0)
        
        return [r["EvOlf_ID"] for r in results], suggestions, total_hits
        
    except Exception as e:
        print(f"Elasticsearch search error: {e}")
        return None, None, None

# -------------------------------
# Pagination
# -------------------------------
class StandardResultsSetPagination(PageNumberPagination):
    page_size = int(os.getenv('DEFAULT_PAGE_SIZE', 20))
    page_size_query_param = 'limit'
    max_page_size = 1000

# -------------------------------
# Enhanced Dataset List (with robust ES fallback)
# -------------------------------
class DatasetListAPIView(APIView):
    """
    GET /api/dataset
    Supports pagination, filtering, sorting, and robust search.
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

        # Build filters dict
        filters = {}
        if species:
            filters['species'] = species
        if class_filter:
            filters['class_filter'] = class_filter
        if mutation_type:
            filters['mutation_type'] = mutation_type

        # Base queryset
        base_qs = EvOlf.objects.all()

        # --- Step 1: Enhanced Search Phase ---
        results_ids_ordered = None
        suggestions = []
        search_metadata = {}
        
        # Only use Elasticsearch if there's a search term OR if filters are applied
        if search:
            # Try enhanced ElasticSearch first for search queries
            results_ids_ordered, es_suggestions, total_hits = search_with_elasticsearch(search, filters)
            # Ensure suggestions is always a list (ES may return None on error)
            suggestions = es_suggestions if es_suggestions is not None else []
            search_metadata = {
                "totalHits": total_hits or 0,
                "searchEngine": "elasticsearch" if results_ids_ordered else "postgres",
                "query": search
            }
        
        # Fallback to Postgres search if ES didn't work or not available
        if search and not results_ids_ordered:
            # Use simple icontains search (no pg_trgm extension required)
            search_qs = base_qs.filter(
                Q(EvOlf_ID__icontains=search) |
                Q(Ligand__icontains=search) |
                Q(Receptor__icontains=search) |
                Q(Species__icontains=search) |
                Q(ChEMBL_ID__icontains=search) |
                Q(UniProt_ID__icontains=search) |
                Q(CID__icontains=search)
            )
            
            search_metadata["searchEngine"] = "postgres"
        elif results_ids_ordered:
            # Use ES results - keep as queryset, don't convert to list yet
            preserved = {eid: i for i, eid in enumerate(results_ids_ordered)}
            search_qs = EvOlf.objects.filter(EvOlf_ID__in=results_ids_ordered)
        else:
            # No search term - use base queryset (all data)
            search_qs = base_qs

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
            **search_metadata
        }

        # --- Step 3: Apply Filters ---
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
        
        # --- Apply filters
        if isinstance(search_qs, list):
            # Already a list from ES results
            qs = apply_filters_to_list(search_qs)
        else:
            # Queryset - apply filters
            qs = apply_filters_to_queryset(search_qs)
            
            # If we have ES ordering, apply it now
            if results_ids_ordered:
                preserved = {eid: i for i, eid in enumerate(results_ids_ordered)}
                qs = list(qs)
                qs.sort(key=lambda o: preserved.get(o.EvOlf_ID, 999999))

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

        # Calculate filtered count (after filters are applied)
        filtered_count = len(qs) if isinstance(qs, list) else qs.count()

        pagination_info = {
            "currentPage": page,
            "totalPages": math.ceil(filtered_count / limit) if limit > 0 else 1,
            "totalItems": filtered_count,
            "itemsPerPage": limit,
        }

        # --- Step 6: Filter Options ---
        filter_options = {
            "uniqueClasses": statistics["uniqueClasses"],
            "uniqueSpecies": statistics["uniqueSpecies"],
            "uniqueMutationTypes": statistics["uniqueMutationTypes"],
        }

        # Update statistics with search results count
        statistics.update({"totalRows": total_rows})

        return Response({
            "data": serializer.data,
            "pagination": pagination_info,
            "statistics": statistics,
            "filterOptions": filter_options,
            "suggestions": suggestions[:10],  # Return top 10 suggestions
            "all_evolf_ids": [obj.EvOlf_ID for obj in qs],
        })

# -------------------------------
# Enhanced Dataset Export
# -------------------------------
class DatasetExportAPIView(APIView):
    """
    POST /api/dataset/export
    Uses enhanced search functionality
    """
    def post(self, request):
        data = request.data
        evolf_ids = data.get('evolfIds')

        # --- CASE A: frontend sends IDs directly
        if isinstance(evolf_ids, list) and len(evolf_ids) > 0:
            qs = EvOlf.objects.filter(EvOlf_ID__in=evolf_ids)
        else:
            # --- CASE B: no IDs -> re-run enhanced query logic
            search = data.get('search', '').strip()
            species = data.get('species')
            class_filter = data.get('class') or data.get('classFilter')
            mutation_type = data.get('mutationType')
            sort_by = data.get('sortBy', 'EvOlf_ID')
            sort_order = data.get('sortOrder', 'desc')

            # Build filters
            filters = {}
            if species:
                filters['species'] = species
            if class_filter:
                filters['class_filter'] = class_filter
            if mutation_type:
                filters['mutation_type'] = mutation_type

            qs = EvOlf.objects.all()
            
            # Apply basic filters first
            if species:
                qs = qs.filter(Species__iexact=species)
            if class_filter:
                qs = qs.filter(Class__iexact=class_filter)
            if mutation_type:
                qs = qs.filter(Mutation_Status__iexact=mutation_type)

            # Enhanced ElasticSearch search
            results_ids_ordered = None
            if search and ES_AVAILABLE:
                results_ids_ordered, _, _ = search_with_elasticsearch(search, filters)

            # Fallback to trigram
            if search and not results_ids_ordered:
                qs = qs.annotate(
                    similarity=TrigramSimilarity('Receptor', search) +
                               TrigramSimilarity('Ligand', search)
                ).filter(
                    Q(similarity__gt=0.1) |
                    Q(EvOlf_ID__icontains=search) |
                    Q(Ligand__icontains=search) |
                    Q(Receptor__icontains=search)
                ).order_by('-similarity')

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
            return Response({"message": "No records found for given filters or IDs"}, status=404)

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
            "version": "1.0",
            "searchUsed": "enhanced" if ES_AVAILABLE else "basic"
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
    CACHE_PATH = os.path.join(settings.BASE_DIR, settings.PATH_AFTER_BASE_DIR, "evolf_complete_dataset.zip")

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
            csv_path = os.path.join(settings.BASE_DIR, settings.PATH_AFTER_BASE_DIR, "evolf_data.csv")
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