import os
import pandas as pd
from django.core.management.base import BaseCommand
from elasticsearch import Elasticsearch
from tqdm import tqdm
from dotenv import load_dotenv


class Command(BaseCommand):
    help = "Load enhanced_data_with_species_links.csv into Elasticsearch."

    def handle(self, *args, **options):

        load_dotenv()

        base_dir = os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(base_dir, "..", "evolf_data.csv")
        csv_path = os.path.normpath(csv_path)

        self.stdout.write(self.style.SUCCESS(f"📂 Loading CSV from: {csv_path}"))

        # --- Load CSV ---
        df = pd.read_csv(csv_path)
        df = df.fillna("")

        df.rename(columns=lambda x: x.strip().replace(" ", "_"), inplace=True)

        # --- Extract environment variables ---
        es_user = os.getenv("ELASTIC_USERNAME", "elastic")
        es_pass = os.getenv("ELASTIC_PASSWORD")
        es_host = os.getenv("ELASTIC_HOST", "https://localhost:9200")

        if not es_pass:
            self.stdout.write(self.style.ERROR("❌ Missing ELASTIC_PASSWORD in environment!"))
            return

        # --- Connect to ES ---
        es = Elasticsearch(
            es_host,
            basic_auth=(es_user, es_pass),
            verify_certs=False
        )

        index_name = "evolf"

        # --- Delete index ---
        try:
            if es.indices.exists(index=index_name):
                self.stdout.write(self.style.WARNING(f"🗑️ Deleting old index '{index_name}'"))
                es.indices.delete(index=index_name)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"⚠️ Could not delete index: {e}"))

        # --- Create mapping for all fields ---
        mapping = {
            "mappings": {
                "properties": {
                    "EvOlf_ID": {"type": "keyword"},
                    "Class": {"type": "keyword"},
                    "Species": {"type": "keyword"},
                    "Receptor_ID": {"type": "keyword"},
                    "Receptor": {"type": "text"},
                    "UniProt_ID": {"type": "keyword"},
                    "Mutation_Status": {"type": "keyword"},
                    "Mutation": {"type": "text"},
                    "Mutation_Impact": {"type": "text"},
                    "Sequence": {"type": "text"},
                    "Receptor_SubType": {"type": "text"},
                    "Ligand_ID": {"type": "keyword"},
                    "Ligand": {"type": "text"},
                    "SMILES": {"type": "text"},
                    "CID": {"type": "keyword"},
                    "ChEMBL_ID": {"type": "keyword"},
                    "InChiKey": {"type": "keyword"},
                    "InChi": {"type": "text"},
                    "IUPAC_Name": {"type": "text"},
                    "Method": {"type": "text"},
                    "Expression_System": {"type": "text"},
                    "Parameter": {"type": "text"},
                    "Value": {"type": "text"},
                    "Unit": {"type": "text"},
                    "Source": {"type": "text"},
                    "Model": {"type": "keyword"},
                    "Image": {"type": "text"},
                    "Structure_3D": {"type": "text"},
                    "PubChem_Link": {"type": "text"},
                    "Source_Links": {"type": "text"},
                    "UniProt_Link": {"type": "text"},

                    # Suggest field
                    "suggest": {"type": "completion"}
                }
            }
        }

        try:
            es.indices.create(index=index_name, body=mapping)
            self.stdout.write(self.style.SUCCESS(f"✅ Index '{index_name}' created."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Failed to create index: {e}"))
            return

        # --- Insert docs ---
        for _, row in tqdm(df.iterrows(), total=len(df)):
            doc = row.to_dict()

            # Build autocomplete suggestions
            doc["suggest"] = {
                "input": [
                    str(row.get("EvOlf_ID", "")),
                    str(row.get("Receptor", "")),
                    str(row.get("Ligand", "")),
                    str(row.get("Species", "")),
                    str(row.get("Class", "")),
                    str(row.get("Receptor_SubType", "")),
                ],
                "weight": 1,
            }

            try:
                es.index(index=index_name, document=doc)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"⚠️ Failed to index row: {e}"))

        self.stdout.write(self.style.SUCCESS("🎯 All documents indexed successfully!"))
