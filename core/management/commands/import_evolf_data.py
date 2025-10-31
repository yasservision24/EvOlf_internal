import pandas as pd
from django.core.management.base import BaseCommand
from core.models import Evolf  

class Command(BaseCommand):
    help = "Import Receptor data from a CSV file into PostgreSQL via Django ORM"

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=str, help='Path to the CSV file')

    def handle(self, *args, **options):
        csv_path = options['csv_path']
        self.stdout.write(self.style.NOTICE(f"📂 Loading data from {csv_path}..."))
        
        df = pd.read_csv(csv_path)
        df.fillna("", inplace=True)  # replace NaNs with empty strings for safety

        # Optional: Show how many rows
        self.stdout.write(self.style.NOTICE(f"🔢 Total rows: {len(df)}"))

        objects = []
        for _, row in df.iterrows():
            obj = Evolf(
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
                UniProt_Link=row.get("UniProt Link", ""),
                ChEMBL_Link=row.get("ChEMBL Link", ""),
                PubChem_Link=row.get("PubChem Link", ""),
                Ensembl_ID=row.get("Ensembl ID", ""),
                Ensembl_Link=row.get("Ensembl Link", ""),
                Comment=row.get("Comment", "")
            )
            objects.append(obj)

        # Bulk insert in batches (faster)
        Evolf.objects.bulk_create(objects, batch_size=500)

        self.stdout.write(self.style.SUCCESS(f"✅ Successfully imported {len(objects)} records into PostgreSQL!"))


#python manage.py import_evolf_data data/enhanced_data_with_species_links.csv
