from django.core.management.base import BaseCommand
from core.models import EvOlf
from core.views.dataset_views import DatasetListAPIView, ES_AVAILABLE, es
from django.conf import settings
import os
import csv
import json
from django.db.models import Q
from django.contrib.postgres.search import TrigramSimilarity


class Command(BaseCommand):
    help = "Fetch EvoLF data for a given query term (same logic as DatasetListAPIView)"

    def add_arguments(self, parser):
        parser.add_argument('--query', type=str, help='Search term (e.g., "human")')
        parser.add_argument('--output', type=str, default='fetched_results', help='Output folder')

    def handle(self, *args, **options):
        query = options.get('query')
        output_folder = options.get('output')
        os.makedirs(output_folder, exist_ok=True)

        if not query:
            self.stderr.write(self.style.ERROR("Please provide a --query argument."))
            return

        self.stdout.write(self.style.SUCCESS(f"🔍 Searching for: {query}"))

        results_ids_ordered = None
        try:
            if ES_AVAILABLE:
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
                res = es.search(index="evolf", body=body)
                results_ids_ordered = [hit["_source"].get("EvOlf_ID") for hit in res["hits"]["hits"]]
        except Exception:
            results_ids_ordered = None

        if results_ids_ordered:
            qs = EvOlf.objects.filter(EvOlf_ID__in=results_ids_ordered)
        else:
            qs = EvOlf.objects.annotate(similarity=TrigramSimilarity('Receptor', query)) \
                            .filter(similarity__gt=0.2).order_by('-similarity')

        if not qs.exists():
            self.stdout.write(self.style.WARNING("⚠️ No results found."))
            return

        csv_path = os.path.join(output_folder, f"{query}_results.csv")
        with open(csv_path, "w", newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'EvOlf_ID', 'Receptor', 'Species', 'Class', 'Ligand',
                'Mutation_Status', 'Mutation', 'ChEMBL_ID', 'UniProt_ID', 'Ensembl_ID'
            ])
            for obj in qs:
                writer.writerow([
                    obj.EvOlf_ID, obj.Receptor, obj.Species, obj.Class, obj.Ligand,
                    obj.Mutation_Status, obj.Mutation, obj.ChEMBL_ID, obj.UniProt_ID, obj.Ensembl_ID
                ])

        json_path = os.path.join(output_folder, f"{query}_results.json")
        data = list(qs.values())
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        self.stdout.write(self.style.SUCCESS(f"✅ Results saved at:\n- {csv_path}\n- {json_path}"))
