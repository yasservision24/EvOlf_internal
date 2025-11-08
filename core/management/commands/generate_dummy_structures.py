import os
import pandas as pd
from django.core.management.base import BaseCommand
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

class Command(BaseCommand):
    help = "Generate dummy (non-empty) structure files (PDB, SDF, PNG) for all EvOlf IDs in CSV"

    def handle(self, *args, **options):
        csv_path = os.path.join(settings.BASE_DIR, "core", "management", "enhanced_data_with_species_links.csv")

        if not os.path.exists(csv_path):
            self.stderr.write(f"❌ CSV file not found: {csv_path}")
            return

        df = pd.read_csv(csv_path)

        # detect the correct column automatically
        id_col = None
        for col in ["EvOlf_ID", "EvOlf ID", "Evolf_ID", "Evolf ID"]:
            if col in df.columns:
                id_col = col
                break

        if not id_col:
            self.stderr.write("❌ Could not find EvoLF ID column in CSV.")
            return

        # 📁 output folders
        pdb_dir = os.path.join(settings.BASE_DIR, "core", "pdb_files")
        sdf_dir = os.path.join(settings.BASE_DIR, "core", "sdf_files")
        img_dir = os.path.join(settings.BASE_DIR, "core", "smiles_2d")

        os.makedirs(pdb_dir, exist_ok=True)
        os.makedirs(sdf_dir, exist_ok=True)
        os.makedirs(img_dir, exist_ok=True)

        # Dummy text for PDB/SDF files
        dummy_pdb = """HEADER    DUMMY PDB FILE
ATOM      1  N   MET A   1      11.104  13.207  14.225  1.00 20.00           N
ATOM      2  CA  MET A   1      12.560  13.507  14.125  1.00 20.00           C
ATOM      3  C   MET A   1      13.045  14.939  14.525  1.00 20.00           C
TER
END
"""

        dummy_sdf = """Dummy Molecule
  EvoLF Internal 2025

  6  5  0  0  0  0            999 V2000
    1.2990   -0.7500    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    0.0000   -1.5000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0
    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    1.2990    0.7500    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0
    2.5980    0.0000    0.0000 N   0  0  0  0  0  0  0  0  0  0  0  0
M  END
$$$$
"""

        count = 0
        ids = df[id_col].dropna().unique()

        for evolf_id in ids:
            evolf_id = str(evolf_id).strip()
            if not evolf_id:
                continue

            # PDB
            pdb_path = os.path.join(pdb_dir, f"{evolf_id}.pdb")
            with open(pdb_path, "w") as f:
                f.write(dummy_pdb)

            # SDF
            sdf_path = os.path.join(sdf_dir, f"{evolf_id}.sdf")
            with open(sdf_path, "w") as f:
                f.write(dummy_sdf)

            # PNG
            img_path = os.path.join(img_dir, f"{evolf_id}.png")
            img = Image.new("RGB", (400, 400), color=(230, 230, 250))
            draw = ImageDraw.Draw(img)
            draw.rectangle([50, 50, 350, 350], outline=(100, 100, 255), width=5)
            draw.text((70, 180), evolf_id, fill=(50, 50, 120))
            img.save(img_path)

            count += 1

        self.stdout.write(self.style.SUCCESS(f"✅ Created {count} dummy structure sets"))
        self.stdout.write(f"📁 PDB → {pdb_dir}")
        self.stdout.write(f"📁 SDF → {sdf_dir}")
        self.stdout.write(f"📁 PNG → {img_dir}")
