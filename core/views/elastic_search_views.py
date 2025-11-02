from elasticsearch import Elasticsearch
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from django.http import JsonResponse, HttpResponseBadRequest

# ✅ Elasticsearch config (using HTTPS)
es = Elasticsearch(
    "http://localhost:9200",
    basic_auth=("elastic", "HSoMIJHnTnrIiueNgCP2"),
    verify_certs=False  # ignore SSL self-signed cert
)

INDEX_NAME = "evolf"

@method_decorator(csrf_exempt, name="dispatch")
class ElasticSearchView(View):
    def get(self, request):
        query = request.GET.get("q", "")
        if not query:
            return HttpResponseBadRequest("Missing 'q' parameter.")

        # wildcard query for flexible matching
        body = {
            "query": {
                "bool": {
                    "should": [
                        {"wildcard": {"Receptor": {"value": f"*{query}*", "case_insensitive": True}}},
                        {"wildcard": {"Ligand": {"value": f"*{query}*", "case_insensitive": True}}},
                        {"wildcard": {"Species": {"value": f"*{query}*", "case_insensitive": True}}}
                    ]
                }
            }
        }

        try:
            response = es.search(index=INDEX_NAME, body=body)
            results = [
                {
                    "EvOlf_ID": hit["_source"].get("EvOlf_ID"),
                    "Receptor": hit["_source"].get("Receptor"),
                    "Ligand": hit["_source"].get("Ligand"),
                    "Species": hit["_source"].get("Species"),
                }
                for hit in response["hits"]["hits"]
            ]
            return JsonResponse({"results": results})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
