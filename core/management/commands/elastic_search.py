import os
import pandas as pd
from django.core.management.base import BaseCommand
from elasticsearch import Elasticsearch
from tqdm import tqdm
from dotenv import load_dotenv  # ✅ to load environment variables from .env


class Command(BaseCommand):
    help = "Load enhanced_data_with_species_links.csv into Elasticsearch."

    def handle(self, *args, **options):
        # --- Load .env variables ---
        load_dotenv()

        # --- Get full path to CSV ---
        base_dir = os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(base_dir, "..", "enhanced_data_with_species_links.csv")
        csv_path = os.path.normpath(csv_path)
        self.stdout.write(self.style.SUCCESS(f"📂 Loading CSV from: {csv_path}"))

        # --- Load CSV ---
        df = pd.read_csv(csv_path)
        df = df.fillna("")
        df.rename(columns=lambda x: x.strip().replace(" ", "_"), inplace=True)

        # --- Get Elasticsearch credentials from environment ---
        es_user = os.getenv("ELASTIC_USERNAME", "elastic")
        es_pass = os.getenv("ELASTIC_PASSWORD")
        es_host = os.getenv("ELASTIC_HOST", "http://localhost:9200")

        if not es_pass:
            self.stdout.write(self.style.ERROR("❌ Missing ELASTIC_PASSWORD in environment!"))
            return

        # --- Connect to Elasticsearch ---
        es = Elasticsearch(
            es_host,
            basic_auth=(es_user, es_pass),
            verify_certs=False,
        )

        index_name = "evolf"

        # --- Delete old index if it exists ---
        try:
            if es.indices.exists(index=index_name):
                self.stdout.write(self.style.WARNING(f"🗑️ Deleting old index: {index_name}"))
                es.indices.delete(index=index_name)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"⚠️ Skipping delete (index may not exist): {e}"))

        # --- Create index with mapping ---
        mapping = {
            "mappings": {
                "properties": {
                    "EvOlf_ID": {"type": "keyword"},
                    "Receptor": {"type": "text"},
                    "Ligand": {"type": "text"},
                    "Species": {"type": "keyword"},
                    "suggest": {"type": "completion"},
                }
            }
        }

        try:
            es.indices.create(index=index_name, body=mapping)
            self.stdout.write(self.style.SUCCESS(f"✅ Index '{index_name}' created successfully."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Failed to create index: {e}"))
            return

        # --- Insert documents ---
        for _, row in tqdm(df.iterrows(), total=len(df)):
            doc = {
                "EvOlf_ID": row.get("EvOlf_ID", ""),
                "Receptor": row.get("Receptor", ""),
                "Ligand": row.get("Ligand", ""),
                "Species": row.get("Species", ""),
                "suggest": {
                    "input": [
                        str(row.get("EvOlf_ID", "")),
                        str(row.get("Receptor", "")),
                        str(row.get("Ligand", "")),
                        str(row.get("Species", "")),
                    ],
                    "weight": 1,
                },
            }
            try:
                es.index(index=index_name, document=doc)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"⚠️ Failed to index row: {e}"))


        self.stdout.write(self.style.SUCCESS("🎯 All documents indexed successfully into Elasticsearch!"))
