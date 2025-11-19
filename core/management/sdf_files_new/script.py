import os
import shutil
import pandas as pd

# Paths (adjust if needed)
csv_path = "/16Tbdrive1/evolf/EvOlf_internal/core/management/evolf_data.csv"
source_folder = "/16Tbdrive1/evolf/EvOlf_internal/core/management/sdf_files_new/Ligand_SDFs"
dest_folder = "/16Tbdrive1/evolf/EvOlf_internal/core/management/sdf_files"

# Reporting CSVs
missing_csv = "/16Tbdrive1/evolf/EvOlf_internal/core/management/missing_sdfs.csv"
empty_csv = "/16Tbdrive1/evolf/EvOlf_internal/core/management/empty_sdfs.csv"

os.makedirs(dest_folder, exist_ok=True)

# Read the CSV
df = pd.read_csv(csv_path)

# Normalize column names to avoid case/space issues
df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

# Ensure required columns exist (accept common variants)
if "evolf_id" not in df.columns and "evolf id" not in df.columns:
    raise ValueError("CSV must contain 'EvOlf ID' (e.g. 'evolf_id') column.")
if "ligand_id" not in df.columns and "ligand id" not in df.columns:
    raise ValueError("CSV must contain 'Ligand ID' (e.g. 'ligand_id') column.")

# If user had slightly different names, pick the best match
if "evolf_id" in df.columns:
    evolf_col = "evolf_id"
else:
    evolf_col = [c for c in df.columns if "evolf" in c][0]

if "ligand_id" in df.columns:
    ligand_col = "ligand_id"
else:
    ligand_col = [c for c in df.columns if "ligand" in c][0]

total = 0
copied = 0
missing = []   # (evolf_id, ligand_id)
empty = []     # (evolf_id, ligand_id, source_file_path)

def file_has_content(path: str) -> bool:
    """
    Return True if file size > 0 and it contains at least one non-whitespace line.
    This filters out files that are 0 bytes or only whitespace/newline.
    """
    try:
        if os.path.getsize(path) == 0:
            return False
        # quick read: stop early if non-empty line found
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line.strip():
                    return True
        return False
    except OSError:
        return False

for _, row in df.iterrows():
    evolf_id = str(row[evolf_col]).strip()
    ligand_id = str(row[ligand_col]).strip()

    if not evolf_id or not ligand_id or evolf_id.lower() in ("nan", "n/a") or ligand_id.lower() in ("nan", "n/a"):
        continue

    total += 1

    source_file = os.path.join(source_folder, f"{ligand_id}.sdf")
    dest_file = os.path.join(dest_folder, f"{evolf_id}.sdf")

    if not os.path.exists(source_file):
        missing.append((evolf_id, ligand_id))
        continue

    # If file exists, check content
    if not file_has_content(source_file):
        empty.append((evolf_id, ligand_id, source_file))
        continue

    # File exists and has content -> copy
    try:
        shutil.copy2(source_file, dest_file)
        copied += 1
    except Exception as e:
        # treat copy failure as missing for reporting, but include error
        missing.append((evolf_id, ligand_id))
        print(f"Failed to copy {source_file} -> {dest_file}: {e}")

# Summary print
print(f"\nTotal rows processed: {total}")
print(f"Copied successfully: {copied}")
print(f"Missing SDF files: {len(missing)}")
print(f"Empty SDF files (found but no content): {len(empty)}")

# Write missing CSV (if any)
if missing:
    df_missing = pd.DataFrame(missing, columns=["evolf_id", "ligand_id"])
    df_missing.to_csv(missing_csv, index=False)
    print(f"Missing report written to: {missing_csv}")

# Write empty CSV (if any) with source path
if empty:
    df_empty = pd.DataFrame(empty, columns=["evolf_id", "ligand_id", "source_file"])
    df_empty.to_csv(empty_csv, index=False)
    print(f"Empty-file report written to: {empty_csv}")

print("\nDone.")
