"""
Structure utilities and views for EvoLF dataset details.
Includes:
1. format_dataset_detail() – formats dataset detail response
2. FetchLocalStructureAPIView – fetches local ligand & receptor structures
"""

import os
import math
from typing import Dict, Optional
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status


def _sanitize_scalar(v):
    """Return JSON-safe scalar (convert NaN/Inf to None)."""
    try:
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v
    except Exception:
        return None


def read_file_safe(path: str) -> str:
    """Return file contents if exists, else empty string."""
    try:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
    except Exception:
        pass
    return ""


def _choose_existing(base_root: str, *relpaths) -> Optional[str]:
    """Return first existing absolute path among relpaths, else None."""
    for rel in relpaths:
        abs_path = os.path.join(base_root, rel)
        if os.path.exists(abs_path):
            return abs_path
    return None


# ============================================================
# 1️⃣ FORMATTER FUNCTION
# ============================================================

def format_dataset_detail(entry: Dict, request=None) -> Dict:
    """
    Prepare structured dataset detail response for a single EvoLF entry.
    """
    evolf_id = entry.get("EvOlf_ID") or entry.get("EvOlf ID") or entry.get("evolfId") or entry.get("EvOlf")
    if not evolf_id:
        return {"error": "Missing EvOlf_ID"}

    media_root = settings.MEDIA_ROOT

    pdb_candidates = [f"pdb_files/{evolf_id}.pdb", f"pdf_files/{evolf_id}.pdb"]
    sdf_file = f"sdf_files/{evolf_id}.sdf"
    img_file = f"smiles_2d/{evolf_id}.png"

    pdb_path = _choose_existing(media_root, *pdb_candidates)
    sdf_path = os.path.join(media_root, sdf_file)
    img_path = os.path.join(media_root, img_file)

    pdb_text = read_file_safe(pdb_path) if pdb_path else ""
    sdf_text = read_file_safe(sdf_path) if os.path.exists(sdf_path) else ""

    # Helper to build absolute URLs
    

    def build_url(rel_path: str) -> str:
        """
        Build URL for a media file.
        Uses BASE_URL from environment if present, otherwise falls back to request or relative path.
        """
        base_url = os.getenv("BASE_URL")  # e.g., "http://192.168.24.13:3000"
        if base_url:
            base_url = base_url.rstrip("/")
            media_url = settings.MEDIA_URL if settings.MEDIA_URL.endswith("/") else settings.MEDIA_URL + "/"
            return f"{base_url}{media_url}{rel_path}"

        # fallback: relative path if no BASE_URL
        return f"/media/{rel_path}"


    # Safe getter for entry fields
    def gf(*keys):
        for k in keys:
            v = entry.get(k)
            if v is None:
                continue
            try:
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    continue
            except Exception:
                pass
            return v
        return ""

    # Extract IDs and mutation info
    uniprot_id = gf("UniProt ID", "uniprotId", "UniProt_ID") or ""
    ensembl_id = gf("Ensembl ID", "ensemblId", "Ensembl_ID") or ""
    chembl_id = gf("Ligand ID", "chemblId", "ChEMBL_ID") or ""
    cid_raw = gf("CID", "pubchemId", "PubChem_ID", "cid") or ""
    cid = str(cid_raw).split(".")[0] if cid_raw else ""

    mutation_val = gf("Mutation") or ""
    mutation_status = "Wild-type" if mutation_val == "" else "Mutant"

    # Structure URLs
    structure2d_url = build_url(img_file) if os.path.exists(img_path) else ""
    chosen_pdb_rel = next((p for p in pdb_candidates if os.path.exists(os.path.join(media_root, p))), None)
    structure3d_url = build_url(chosen_pdb_rel) if chosen_pdb_rel else ""
    sdf_file_url = build_url(sdf_file) if os.path.exists(sdf_path) else ""

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
        "pdbData": pdb_text,
        "sdfData": sdf_text,
        "structure2d": structure2d_url,
        "image": structure2d_url,
        "structure3d": structure3d_url,
        "sdfFile": sdf_file_url,
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


# ============================================================
# 2️⃣ FETCH LOCAL STRUCTURES
# ============================================================

class FetchLocalStructureAPIView(APIView):
    """
    GET /api/structures/<evolf_id>/
    Returns pdbData and sdfData for given id if present under MEDIA_ROOT.
    """
    def get(self, request, evolf_id):
        try:
            media_root = settings.MEDIA_ROOT
            pdb_candidates = [f"pdb_files/{evolf_id}.pdb", f"pdf_files/{evolf_id}.pdb"]
            sdf_file = f"sdf_files/{evolf_id}.sdf"

            pdb_abs = _choose_existing(media_root, *pdb_candidates)
            sdf_abs = os.path.join(media_root, sdf_file)

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
