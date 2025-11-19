import pandas as pd
from django.core.management.base import BaseCommand
from core.models import EvOlf  

class Command(BaseCommand):
    help = "Import Receptor data from a CSV file into PostgreSQL via Django ORM"

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=str, help='Path to the CSV file')

    def handle(self, *args, **options):
        csv_path = options['csv_path']
        self.stdout.write(self.style.NOTICE(f"📂 Loading data from {csv_path}..."))

        df = pd.read_csv(csv_path)
        df.fillna("", inplace=True)

        self.stdout.write(self.style.NOTICE(f"🔢 Total rows: {len(df)}"))

        # -------------------------------------------------
        # 1️⃣ REMOVE OLD DATA
        # -------------------------------------------------
        self.stdout.write(self.style.WARNING("🗑️ Deleting old EvOlf data..."))
        EvOlf.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("✔️ Old data deleted."))

        # -------------------------------------------------
        # 2️⃣ IMPORT NEW DATA
        # -------------------------------------------------
        objects = []

        for _, row in df.iterrows():
            obj = EvOlf(
                EvOlf_ID=row.get("EvOlf ID", ""),
                Class=row.get("Class", ""),
                Species=row.get("Species", ""),
                Receptor_ID=row.get("Receptor ID", ""),
                Receptor=row.get("Receptor", ""),
                UniProt_ID=row.get("UniProt ID", ""),
                Mutation_Status=row.get("Mutation Status", ""),
                Mutation=row.get("Mutation", ""),
                Mutation_Impact=row.get("Mutation Impact", ""),
                Sequence=row.get("Sequence", ""),
                Receptor_SubType=row.get("Receptor SubType", ""),
                Ligand_ID=row.get("Ligand ID", ""),
                Ligand=row.get("Ligand", ""),
                SMILES=row.get("SMILES", ""),
                CID=row.get("CID", ""),
                ChEMBL_ID=row.get("ChEMBL ID", ""),
                InChiKey=row.get("InChiKey", ""),
                InChi=row.get("InChi", ""),
                IUPAC_Name=row.get("IUPAC Name", ""),
                Method=row.get("Method", ""),
                Expression_System=row.get("Expression System", ""),
                Parameter=row.get("Parameter", ""),
                Value=row.get("Value", ""),
                Unit=row.get("Unit", ""),
                Source=row.get("Source", ""),
                Model=row.get("Model", ""),
                Image=row.get("Image", ""),
                Structure_3D=row.get("3d Structure", ""),
                PubChem_Link=row.get("PubChem_Link", ""),
                Source_Links=row.get("Source_Links", ""),
                UniProt_Link=row.get("UniProt_Link", ""),
                Comments=""
            )
            objects.append(obj)

        EvOlf.objects.bulk_create(objects, batch_size=500)

        self.stdout.write(
            self.style.SUCCESS(f"✅ Successfully imported {len(objects)} new records into PostgreSQL!")
        )

#python manage.py import_evolf_data core/management/evolf_data.csv
