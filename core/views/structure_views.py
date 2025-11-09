"""
Structure utilities and views for EvoLF dataset details.
Includes:
1. format_dataset_detail() – formats dataset detail response
2. FetchStructureFilesAPIView – fetches 2D/3D ligand & receptor structures
"""

import os
import requests
from typing import Dict, Optional
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

import math


def _sanitize_scalar(v):
    """Return JSON-safe scalar (convert NaN/Inf to None or empty string)."""
    try:
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                return None
        # Keep ints as-is, convert numpy types if needed by str()
        return v
    except Exception:
        return None


def read_file_safe(path: str) -> str:
    """Return file contents if exists, else empty string."""
    try:
        if path and os.path.exists(path):
            # text files (pdb/sdf) -> read as text
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
    except Exception:
        pass
    return ""


def _choose_existing(base_root: str, *relpaths) -> Optional[str]:
    """Return first existing absolute path among relpaths, else None."""
    for rel in relpaths:
        p = os.path.join(base_root, rel)
        if os.path.exists(p):
            return p
    return None

# ============================================================
# 1️⃣ FORMATTER FUNCTION
# ============================================================

def format_dataset_detail(entry: Dict, request=None) -> Dict:
    """
    Prepare structured dataset detail response for a single EvoLF entry.
    - entry: a dict row (from CSV or DB)
    - request: optional, used for building absolute URLs
    Returns keys exactly as README expects (with defaults).
    """
    # normalize potential id keys
    evolf_id = entry.get("EvOlf_ID") or entry.get("EvOlf ID") or entry.get("evolfId") or entry.get("EvOlf")
    if not evolf_id:
        return {"error": "Missing EvOlf_ID"}

    # base paths (your MEDIA_ROOT is core/management in your setup)
    media_root = settings.MEDIA_ROOT
    # allow both "pdb_files" and possible "pdf_files" typo
    pdb_rel_candidates = [os.path.join("pdb_files", f"{evolf_id}.pdb"),
                          os.path.join("pdf_files", f"{evolf_id}.pdb")]
    sdf_rel = os.path.join("sdf_files", f"{evolf_id}.sdf")
    img_rel = os.path.join("smiles_2d", f"{evolf_id}.png")

    pdb_path = _choose_existing(media_root, *pdb_rel_candidates)
    sdf_path = os.path.join(media_root, sdf_rel)
    img_path = os.path.join(media_root, img_rel)

    pdb_text = read_file_safe(pdb_path) if pdb_path else ""
    sdf_text = read_file_safe(sdf_path) if os.path.exists(sdf_path) else ""

    # build absolute URL helper (if request provided)
    def build_url(folder: str, filename: str) -> str:
        if not request:
            return ""  # no request -> leave empty (frontend can use relative paths if needed)
        media_url = settings.MEDIA_URL if settings.MEDIA_URL.endswith("/") else settings.MEDIA_URL + "/"
        # ensure we don't duplicate slashes badly
        return request.build_absolute_uri(f"{media_url}{folder}/{filename}")

    # safe getter that returns string ("" default)
    def gf(*keys):
        for k in keys:
            if k in entry:
                v = entry.get(k)
                if v is None:
                    continue
                # handle pandas NaN
                try:
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        continue
                except Exception:
                    pass
                return v
        return ""

    # fields mapping and defaults to exactly match README
    uniprot_id = gf("UniProt ID", "uniprotId", "UniProt_ID") or ""
    ensembl_id = gf("Ensembl ID", "ensemblId", "Ensembl_ID") or ""
    chembl_id = gf("Ligand ID", "chemblId", "ChEMBL_ID") or ""
    cid_raw = gf("CID", "pubchemId", "PubChem_ID", "cid") or ""
    cid = str(cid_raw).split(".")[0] if cid_raw != "" else ""

    mutation_val = gf("Mutation") or ""
    mutation_status = "Wild-type" if mutation_val == "" else "Mutant"

    # structure URLs (only if files exist)
    structure2d_url = build_url("smiles_2d", f"{evolf_id}.png") if os.path.exists(img_path) else ""
    # prefer pdb_files or pdf_files whichever exists
    chosen_pdb_rel = None
    for rel in pdb_rel_candidates:
        if os.path.exists(os.path.join(media_root, rel)):
            chosen_pdb_rel = rel
            break
    structure3d_url = build_url(os.path.dirname(chosen_pdb_rel).replace("\\", "/"), os.path.basename(chosen_pdb_rel)) if chosen_pdb_rel and request else (f"/{chosen_pdb_rel}" if chosen_pdb_rel else "")

    sdf_file_url = build_url("sdf_files", f"{evolf_id}.sdf") if os.path.exists(sdf_path) else ""

    formatted = {
        "evolfId": str(evolf_id),
        "receptor": gf("Receptor") or "",
        "receptorName": gf("Receptor") or "",
        "ligand": gf("Ligand") or "",
        "ligandName": gf("Ligand") or "",
        "species": gf("Species") or "",
        "class": str(gf("Class", "class_field") or ""),
        "mutation": mutation_val,
        "mutationStatus": mutation_status,
        "mutationType": gf("Mutation Type", "mutationType") or "",
        "mutationImpact": gf("Mutation Impact", "mutationImpact") or "",
        "receptorSubtype": gf("Receptor SubType", "receptorSubtype") or "Olfactory",
        "uniprotId": uniprot_id,
        "uniprotLink": f"https://www.uniprot.org/uniprot/{uniprot_id}" if uniprot_id else "",
        "ensemblId": ensembl_id,
        "ensemblLink": f"https://www.ensembl.org/Homo_sapiens/Gene/Summary?g={ensembl_id}" if ensembl_id else "",
        "chemblId": chembl_id,
        "chemblLink": f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}" if chembl_id else "",
        "cid": cid,
        "pubchemId": cid,
        "pubchemLink": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}" if cid else "",
        "smiles": gf("SMILES", "smiles") or "",
        "inchi": gf("InChI", "inchi") or "",
        "inchiKey": gf("InChI Key", "inchiKey") or "",
        "iupacName": gf("IUPAC Name", "iupacName") or "",
        "sequence": gf("Sequence", "sequence") or "",
        "pdbData": pdb_text or "",
        "sdfData": sdf_text or "",
        "structure2d": structure2d_url or "",
        "image": structure2d_url or "",
        "structure3d": structure3d_url or "",
        "expressionSystem": gf("Expression System", "expressionSystem") or "",
        "parameter": gf("Parameter", "parameter") or "",
        "value": str(gf("Value", "value") or ""),
        "unit": gf("Unit", "unit") or "",
        "comments": gf("Comments", "comments") or "",
        "geneSymbol": gf("Gene Symbol", "geneSymbol") or "",
        "interactionType": gf("Interaction Type", "interactionType") or "",
        "interactionValue": _sanitize_scalar(gf("Interaction Value", "interactionValue")) or "",
        "interactionUnit": gf("Interaction Unit", "interactionUnit") or "",
        "quality": gf("Quality", "quality") or "",
        "qualityScore": _sanitize_scalar(gf("Quality Score", "qualityScore")) or "",
    }

    return formatted


class FetchLocalStructureAPIView(APIView):
    """
    GET /api/structures/<evolf_id>/
    Returns pdbData and sdfData (text) for given id if present under MEDIA_ROOT.
    """
    def get(self, request, evolf_id):
        try:
            media_root = settings.MEDIA_ROOT
            pdb_rel_candidates = [os.path.join("pdb_files", f"{evolf_id}.pdb"),
                                  os.path.join("pdf_files", f"{evolf_id}.pdb")]
            sdf_rel = os.path.join("sdf_files", f"{evolf_id}.sdf")

            pdb_abs = _choose_existing(media_root, *pdb_rel_candidates)
            sdf_abs = os.path.join(media_root, sdf_rel)

            pdb_text = read_file_safe(pdb_abs) if pdb_abs else ""
            sdf_text = read_file_safe(sdf_abs) if os.path.exists(sdf_abs) else ""

            if not pdb_text and not sdf_text:
                return Response({"error": "No structure files found for this ID."}, status=status.HTTP_404_NOT_FOUND)

            return Response({
                "evolfId": evolf_id,
                "pdbData": pdb_text,
                "sdfData": sdf_text
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# class FetchStructureFilesAPIView(APIView):
#     """
#     Fetch 2D and 3D structures for ligand (PubChem) and protein (AlphaFold)
#     and save them locally under /media/structures/<EvOlf_ID>/
#     """

#     def get(self, request, evolf_id):
#         ligand_name = request.query_params.get("ligand")
#         protein_id = request.query_params.get("uniprot")

#         if not ligand_name:
#             return Response(
#                 {"error": "Missing 'ligand' query parameter"},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         base_dir = os.path.join(settings.MEDIA_ROOT, evolf_id)
#         os.makedirs(base_dir, exist_ok=True)

#         try:
#             # 1️⃣ Get CID from PubChem
#             cid_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{ligand_name}/cids/JSON"
#             cid_response = requests.get(cid_url, timeout=15)
#             cid_response.raise_for_status()
#             cid_data = cid_response.json()
#             cid = cid_data["IdentifierList"]["CID"][0]

#             # 2️⃣ Download 2D image
#             img_url = f"https://pubchem.ncbi.nlm.nih.gov/image/imagefly.cgi?cid={cid}&width=500&height=500"
#             img_path = os.path.join(base_dir, f"{ligand_name}_2d.png")
#             img_data = requests.get(img_url, timeout=15)
#             with open(img_path, "wb") as f:
#                 f.write(img_data.content)

#             # 3️⃣ Download 3D SDF (ligand)
#             sdf_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/CID/{cid}/record/SDF/?record_type=3d"
#             sdf_path = os.path.join(base_dir, f"{ligand_name}_3d.sdf")
#             sdf_data = requests.get(sdf_url, timeout=15)
#             with open(sdf_path, "wb") as f:
#                 f.write(sdf_data.content)

#             # 4️⃣ Download PDB (receptor)
#             pdb_path = None
#             if protein_id:
#                 pdb_url = f"https://alphafold.ebi.ac.uk/files/AF-{protein_id}-F1-model_v4.pdb"
#                 pdb_path = os.path.join(base_dir, f"{protein_id}.pdb")
#                 pdb_data = requests.get(pdb_url, timeout=15)
#                 if pdb_data.status_code == 200:
#                     with open(pdb_path, "wb") as f:
#                         f.write(pdb_data.content)

#             return Response(
#                 {
#                     "message": "Downloaded successfully",
#                     "pubchem_cid": cid,
#                     "paths": {
#                         "2d_image": img_path,
#                         "3d_sdf": sdf_path,
#                         "protein_pdb": pdb_path,
#                     },
#                 },
#                 status=status.HTTP_200_OK,
#             )

#         except Exception as e:
#             return Response(
#                 {"error": str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             )
