import os
import shutil
import pandas as pd

# Paths
csv_path = "/16Tbdrive1/evolf/EvOlf_internal/core/management/evolf_data.csv"
source_folder = "/16Tbdrive1/evolf/EvOlf_internal/core/management/sdf_files_new/Ligand_SDFs"
dest_folder = "/16Tbdrive1/evolf/EvOlf_internal/core/management/sdf_files"

os.makedirs(dest_folder, exist_ok=True)

# Read the CSV
df = pd.read_csv(csv_path)

# Normalize column names to avoid case/space issues
df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

if "evolf_id" not in df.columns or "ligand_id" not in df.columns:
    raise ValueError("CSV must contain 'EvOlf ID' and 'Ligand ID' columns.")

total = 0
success = 0
missing = []

for _, row in df.iterrows():
    evolf_id = str(row["evolf_id"]).strip()
    ligand_id = str(row["ligand_id"]).strip()

    if not evolf_id or not ligand_id:
        continue

    total += 1

    source_file = os.path.join(source_folder, f"{ligand_id}.sdf")
    dest_file = os.path.join(dest_folder, f"{evolf_id}.sdf")

    if os.path.exists(source_file):
        shutil.copy2(source_file, dest_file)
        success += 1
    else:
        missing.append((evolf_id, ligand_id))

print(f"\nTotal rows processed: {total}")
print(f"Copied successfully: {success}")
print(f"Missing SDF files: {len(missing)}")

if missing:
    print("\nMissing list:")
    for e, l in missing:
        print(f"EvOlf ID: {e}, Ligand ID: {l}")
