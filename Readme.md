# 🧬 EvoLF Internal — Fetch EvoLF Data Command

## 📖 Overview

The `fetch_evolf_data` management command allows you to **fetch EvoLF dataset entries** based on a query term (e.g., *human*, *mouse*, *olfactory receptor*).  
It replicates the same search logic used by the `DatasetListAPIView` — integrating both **Elasticsearch** (if available) and **PostgreSQL fuzzy matching** — and saves the results in **CSV** and **JSON** formats.



## ⚙️ Features

- 🔍 Search by receptor, ligand, or species name  
- 🔁 Automatically uses **Elasticsearch** if available, otherwise falls back to **PostgreSQL fuzzy search**
- 💾 Exports results to **CSV** and **JSON** files  
- 📂 Organized output folder per query  
- ⚠️ Handles connection or empty result gracefully  


## 🧠 How It Works

1. Accepts a search term via `--query` (e.g., `"human"`).  
2. Tries to connect to **Elasticsearch**:
   - If available, runs a wildcard search on the fields: `Receptor`, `Ligand`, and `Species`.
   - If not available, uses PostgreSQL’s **TrigramSimilarity** for approximate matching.
3. Filters matching records from the `EvOlf` model.
4. Writes the results to:
   - `fetched_results/<query>_results.csv`
   - `fetched_results/<query>_results.json`



## 💻 Usage

Run the command from your project root:

```bash
python manage.py fetch_evolf_data --query "human"


Optional arguments:

Argument	Description	Example
--query	Search term (required)	--query "mouse"
--output	Output folder name (optional)	--output my_results


📂 Output Files

Generated files will be stored in the output folder (default: fetched_results/):

fetched_results/
├── human_results.csv
└── human_results.json


Each record includes the following fields:

Field	Description
EvOlf_ID	Unique EvoLF identifier
Receptor	Receptor name
Species	Species name
Class	Protein class
Ligand	Ligand name
Mutation_Status	Mutation status
Mutation	Mutation type
ChEMBL_ID	ChEMBL database ID
UniProt_ID	UniProt ID
Ensembl_ID	Ensembl gene ID


⚠️ Error Messages
Message	Meaning
⚠️ “Could not connect to Elasticsearch.”	Elasticsearch is unavailable; fallback to PostgreSQL used
⚠️ “No results found.”	No matches found for the provided query
❌ “Please provide a --query argument.”	The query term is missing


🧩 Example Output
Command
python manage.py fetch_evolf_data --query "human"

Console Output
🔍 Searching for: human
✅ Results saved at:
- fetched_results/human_results.csv
- fetched_results/human_results.json

🧑‍💻 Developer Notes

File Location:
core/management/commands/fetch_evolf_data.py
Related View Logic:
core/views/dataset_views.py

Uses:

EvOlf model for data retrieval
Elasticsearch for high-speed search (if available)
TrigramSimilarity for fuzzy match fallback