"""
Structure utilities and views for EvoLF dataset details.
Includes:
1. format_dataset_detail() – formats dataset detail response
2. FetchStructureFilesAPIView – fetches 2D/3D ligand & receptor structures
"""

import os
import requests
from typing import Dict
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status


# ============================================================
# 1️⃣ FORMATTER FUNCTION
# ============================================================

def format_dataset_detail(entry: Dict) -> Dict:
    """
    Prepare structured dataset detail response for a single EvoLF entry.
    Ensures all fields are present and formatted consistently.
    """
    evolf_id = entry.get("EvOlf_ID") or entry.get("evolfId")

    # External links
    uniprot_id = entry.get("uniprotId") or ""
    ensembl_id = entry.get("ensembleId") or ""
    chembl_id = entry.get("chemblId") or ""
    cid = entry.get("pubchemId") or entry.get("cid")

    return {
        "evolfId": evolf_id or "",
        "receptor": entry.get("Receptor", ""),
        "receptorName": entry.get("Receptor", ""),
        "ligand": entry.get("Ligand", ""),
        "ligandName": entry.get("Ligand", ""),
        "species": entry.get("Species", ""),
        "class": entry.get("Class", "") or entry.get("class_field", ""),
        "mutation": entry.get("Mutation", ""),
        "mutationStatus": "Wild-type" if not entry.get("Mutation") else "Mutant",
        "mutationType": entry.get("mutationType", ""),
        "mutationImpact": entry.get("mutationImpact", ""),
        "receptorSubtype": entry.get("receptorSubtype", "Olfactory"),
        "uniprotId": uniprot_id,
        "uniprotLink": f"https://www.uniprot.org/uniprot/{uniprot_id}" if uniprot_id else "",
        "ensemblId": ensembl_id,
        "ensemblLink": f"https://www.ensembl.org/Homo_sapiens/Gene/Summary?g={ensembl_id}" if ensembl_id else "",
        "chemblId": chembl_id,
        "chemblLink": f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}" if chembl_id else "",
        "cid": cid,
        "pubchemId": cid,
        "pubchemLink": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}" if cid else "",
        "smiles": entry.get("smiles", ""),
        "inchi": entry.get("inchi", ""),
        "inchiKey": entry.get("inchiKey", ""),
        "iupacName": entry.get("iupacName", ""),
        "sequence": entry.get("sequence", ""),
        "pdbData": entry.get("pdbData", ""),
        "sdfData": entry.get("sdfData", ""),
        "structure2d": f"https://pubchem.ncbi.nlm.nih.gov/image/imagefly.cgi?cid={cid}&width=300&height=300" if cid else "",
        "image": f"https://pubchem.ncbi.nlm.nih.gov/image/imagefly.cgi?cid={cid}&width=300&height=300" if cid else "",
        "structure3d": f"https://api.evolf.com/structures/{evolf_id}.pdb" if evolf_id else "",
        "expressionSystem": entry.get("expressionSystem", ""),
        "parameter": entry.get("parameter", ""),
        "value": entry.get("value", ""),
        "unit": entry.get("unit", ""),
        "comments": entry.get("comments", ""),
        "geneSymbol": entry.get("geneSymbol", ""),
        "interactionType": entry.get("interactionType", ""),
        "interactionValue": entry.get("interactionValue", ""),
        "interactionUnit": entry.get("interactionUnit", ""),
        "quality": entry.get("quality", ""),
        "qualityScore": entry.get("qualityScore", ""),
    }


# ============================================================
# 2️⃣ STRUCTURE FETCH API
# ============================================================

class FetchStructureFilesAPIView(APIView):
    """
    Fetch 2D and 3D structures for ligand (PubChem) and protein (AlphaFold)
    and save them locally under /media/structures/<EvOlf_ID>/
    """

    def get(self, request, evolf_id):
        ligand_name = request.query_params.get("ligand")
        protein_id = request.query_params.get("uniprot")

        if not ligand_name:
            return Response(
                {"error": "Missing 'ligand' query parameter"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        base_dir = os.path.join(settings.MEDIA_ROOT, evolf_id)
        os.makedirs(base_dir, exist_ok=True)

        try:
            # 1️⃣ Get CID from PubChem
            cid_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{ligand_name}/cids/JSON"
            cid_response = requests.get(cid_url, timeout=15)
            cid_response.raise_for_status()
            cid_data = cid_response.json()
            cid = cid_data["IdentifierList"]["CID"][0]

            # 2️⃣ Download 2D image
            img_url = f"https://pubchem.ncbi.nlm.nih.gov/image/imagefly.cgi?cid={cid}&width=500&height=500"
            img_path = os.path.join(base_dir, f"{ligand_name}_2d.png")
            img_data = requests.get(img_url, timeout=15)
            with open(img_path, "wb") as f:
                f.write(img_data.content)

            # 3️⃣ Download 3D SDF (ligand)
            sdf_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/CID/{cid}/record/SDF/?record_type=3d"
            sdf_path = os.path.join(base_dir, f"{ligand_name}_3d.sdf")
            sdf_data = requests.get(sdf_url, timeout=15)
            with open(sdf_path, "wb") as f:
                f.write(sdf_data.content)

            # 4️⃣ Download PDB (receptor)
            pdb_path = None
            if protein_id:
                pdb_url = f"https://alphafold.ebi.ac.uk/files/AF-{protein_id}-F1-model_v4.pdb"
                pdb_path = os.path.join(base_dir, f"{protein_id}.pdb")
                pdb_data = requests.get(pdb_url, timeout=15)
                if pdb_data.status_code == 200:
                    with open(pdb_path, "wb") as f:
                        f.write(pdb_data.content)

            return Response(
                {
                    "message": "Downloaded successfully",
                    "pubchem_cid": cid,
                    "paths": {
                        "2d_image": img_path,
                        "3d_sdf": sdf_path,
                        "protein_pdb": pdb_path,
                    },
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
