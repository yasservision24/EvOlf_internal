from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from django.http import JsonResponse, HttpResponseBadRequest
from elasticsearch import Elasticsearch

es = Elasticsearch(
    "https://localhost:9200",
    basic_auth=("elastic", "HSoMIJHnTnrIiueNgCP2"),
    verify_certs=False
)

INDEX_NAME = "evolf"

@method_decorator(csrf_exempt, name="dispatch")
class ElasticSearchView(View):
    def get(self, request):
        query = request.GET.get("q", "")
        if not query:
            return HttpResponseBadRequest("Missing 'q' parameter.")

        # Use wildcard to handle case-insensitive and partial matches
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

#python manage.py elastic_search

#curl "http://127.0.0.1:8000/api/search/?q=human"
