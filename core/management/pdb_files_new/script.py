import os
import shutil
import ast
import pandas as pd

# -----------------------------
# PATHS
# -----------------------------
mapping_csv = r"Final_seq_evolf.csv"

# Where original PDB files are located
pdb_folder = r"/16Tbdrive1/evolf/EvOlf_internal/core/management/pdb_files_new/pdb_out"

# Where to save all copied PDB files
output_folder = r"/16Tbdrive1/evolf/EvOlf_internal/core/management/pdb_files"
os.makedirs(output_folder, exist_ok=True)

# -----------------------------
# READ CSV
# -----------------------------
df = pd.read_csv(mapping_csv)

# Loop through every mapping entry
for idx, row in df.iterrows():

    base_id = str(row["EvOlf ID"]).strip()
    base_pdb = os.path.join(pdb_folder, f"{base_id}.pdb")

    # Check if base file exists
    if not os.path.exists(base_pdb):
        print(f"❌ Base PDB not found for {base_id}")
        continue

    # Parse list of IDs
    try:
        target_ids = ast.literal_eval(row["EvOlf_IDs"])
    except:
        print(f"❌ Could not parse EvOlf_IDs for {base_id}")
        continue

    # -----------------------------
    # 1️⃣ Copy original base PDB also
    # -----------------------------
    original_output = os.path.join(output_folder, f"{base_id}.pdb")
    shutil.copy(base_pdb, original_output)
    print(f"✔ Copied base: {original_output}")

    # -----------------------------
    # 2️⃣ Copy for all IDs in list
    # -----------------------------
    for tid in target_ids:
        tid = str(tid).strip()
        output_pdb = os.path.join(output_folder, f"{tid}.pdb")

        shutil.copy(base_pdb, output_pdb)
        print(f"✔ Created: {output_pdb}")

print("\n🎉 All files copied including originals!")
