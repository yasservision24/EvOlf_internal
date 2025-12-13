from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.http import JsonResponse, HttpResponseBadRequest
from django.views import View
from elasticsearch import Elasticsearch
import os

ES_HOST = os.getenv("ELASTIC_HOST","")
ES_USERNAME = os.getenv("ELASTIC_USERNAME", "")
ES_PASSWORD = os.getenv("ELASTIC_PASSWORD", "")

es = Elasticsearch(
    ES_HOST,
    basic_auth=(ES_USERNAME, ES_PASSWORD),
    verify_certs=False
)

INDEX_NAME = "evolf"


@method_decorator(csrf_exempt, name="dispatch")
class ElasticSearchView(View):
    def get(self, request):
        query = request.GET.get("q", "").strip()

        if not query:
            return HttpResponseBadRequest("Missing 'q' parameter.")

        body = {
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": [
                        # High relevance fields
                        "EvOlf_ID^5",
                        "Ligand^4",
                        "Receptor^4",
                        "Species^3",
                        # Identity fields
                        "CID^3",
                        "ChEMBL_ID^3",
                        "UniProt_ID^3",
                        # Sequence (lower weight)
                        "Sequence^1"
                    ],
                    "type": "best_fields",
                    "fuzziness": "AUTO"
                }
            },
            "suggest": {
                "autocomplete_suggest": {
                    "prefix": query,
                    "completion": {"field": "suggest"}
                }
            },
            "size": 1000
        }

        try:
            response = es.search(index=INDEX_NAME, body=body)

            results = [
                {
                    "EvOlf_ID": hit["_source"].get("EvOlf_ID"),
                    "Ligand": hit["_source"].get("Ligand"),
                    "Receptor": hit["_source"].get("Receptor"),
                    "Species": hit["_source"].get("Species"),
                    "Sequence": hit["_source"].get("Sequence"),
                    "UniProt_ID": hit["_source"].get("UniProt_ID"),
                    "CID": hit["_source"].get("CID"),
                    "ChEMBL_ID": hit["_source"].get("ChEMBL_ID"),
                }
                for hit in response.get("hits", {}).get("hits", [])
            ]

            suggestions = []
            for sug in response.get("suggest", {}).get("autocomplete_suggest", []):
                for opt in sug.get("options", []):
                    suggestions.append(opt["_source"].get("Ligand"))

            return JsonResponse({
                "query": query,
                "results": results,
                "suggestions": list(set(suggestions))
            })

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
