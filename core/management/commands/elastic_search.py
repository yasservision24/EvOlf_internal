import os
import pandas as pd
from django.core.management.base import BaseCommand
from elasticsearch import Elasticsearch
from tqdm import tqdm
from dotenv import load_dotenv


class Command(BaseCommand):
    help = "Load evolf_data.csv into Elasticsearch."

    def handle(self, *args, **options):

        load_dotenv()

        # --------------------------------------
        # Load CSV
        # --------------------------------------
        base_dir = os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(base_dir, "..", "evolf_data.csv")
        csv_path = os.path.normpath(csv_path)

        self.stdout.write(self.style.SUCCESS(f"📂 Loading CSV from: {csv_path}"))

        df = pd.read_csv(csv_path)
        df = df.fillna("")
        df.rename(columns=lambda x: x.strip().replace(" ", "_"), inplace=True)

        # --------------------------------------
        # Connect to Elasticsearch
        # --------------------------------------
        es_user = os.getenv("ELASTIC_USERNAME", "elastic")
        es_pass = os.getenv("ELASTIC_PASSWORD")
        es_host = os.getenv("ELASTIC_HOST", "https://localhost:9200")

        if not es_pass:
            self.stdout.write(self.style.ERROR("❌ Missing ELASTIC_PASSWORD!"))
            return

        es = Elasticsearch(
            es_host,
            basic_auth=(es_user, es_pass),
            verify_certs=False
        )

        index_name = "evolf"

        # --------------------------------------
        # Delete old index
        # --------------------------------------
        try:
            if es.indices.exists(index=index_name):
                es.indices.delete(index=index_name)
                self.stdout.write(self.style.WARNING(f"🗑 Deleted old index '{index_name}'"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"⚠ Could not delete index: {e}"))

        # --------------------------------------
        # Create Mapping
        # --------------------------------------
        mapping = {
            "mappings": {
                "properties": {
                    "EvOlf_ID": {"type": "keyword"},
                    "Class": {"type": "keyword"},
                    "Species": {"type": "text"},
                    "Receptor": {"type": "text"},
                    "UniProt_ID": {"type": "keyword"},
                    "Mutation_Status": {"type": "keyword"},
                    "Mutation": {"type": "text"},
                    "Mutation_Impact": {"type": "text"},
                    "Sequence": {"type": "text"},
                    "Ligand": {"type": "text"},
                    "InChiKey": {"type": "keyword"},
                    "InChi": {"type": "text"},
                    "IUPAC_Name": {"type": "text"},
                    "SMILES": {"type": "text"},
                    "CID": {"type": "keyword"},
                    "ChEMBL_ID": {"type": "keyword"},

                    # ignore these (no autocomplete)
                    "Source": {"type": "text"},
                    "Model": {"type": "text"},
                    "PubChem_Link": {"type": "text"},
                    "Source_Links": {"type": "text"},
                    "UniProt_Link": {"type": "text"},
                    "Value": {"type": "text"},
                    "Method": {"type": "text"},
                    "Image": {"type": "text"},
                    "Structure_3D": {"type": "text"},

                    # 🔥 AUTOCOMPLETE FIELD
                    "suggest": {"type": "completion"}
                }
            }
        }

        try:
            es.indices.create(index=index_name, body=mapping)
            self.stdout.write(self.style.SUCCESS("✅ Index created."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Failed to create index: {e}"))
            return

        # --------------------------------------
        # Insert documents
        # --------------------------------------

        autocomplete_columns = [
            "EvOlf_ID", "Class", "Species", "Receptor", "UniProt_ID",
            "Mutation_Status", "Mutation", "Mutation_Impact", "Sequence",
            "Ligand", "InChiKey", "InChi", "IUPAC_Name", "SMILES",
            "CID", "ChEMBL_ID"
        ]

        for _, row in tqdm(df.iterrows(), total=len(df)):
            doc = row.to_dict()

            # Build autocomplete input
            inputs = []
            for col in autocomplete_columns:
                val = str(row.get(col, "")).strip()
                if val:
                    inputs.append(val)

            doc["suggest"] = {
                "input": inputs,
                "weight": 1
            }

            try:
                es.index(index=index_name, document=doc)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"⚠ Index error: {e}"))

        self.stdout.write(self.style.SUCCESS("🎯 All docs indexed successfully!"))


#python manage.py elastic_search