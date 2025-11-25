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
    def gf(*keys):
        """Robust getter that handles whitespace, commas, capitalization, and weird key variants."""
        norm_entry = {k.strip().lower().replace(",", "").replace(" ", ""): v for k, v in entry.items()}
        for k in keys:
            if not k:
                continue
            nk = k.strip().lower().replace(",", "").replace(" ", "")
            v = norm_entry.get(nk)
            if v in [None, "", "nan"]:
                continue
            return str(v).strip()
        return ""


    evolf_id = gf("EvOlf ID", "EvOlf_ID", "evolfId")
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


   

    # Extract IDs and mutation info
    uniprot_id = gf("UniProt ID") 
    chembl_id = gf("ChEMBL ID") 
    cid_raw = gf("CID")
    cid = str(cid_raw).split(".")[0] if cid_raw else ""

    
    
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
        "class": gf(" Class") or "",
        "mutation": gf("Mutation") or "",
        "mutationStatus": gf("Mutation Status"),
        "mutationImpact": gf("Mutation Impact") or "",
        "receptorSubtype": gf("Receptor SubType"),
        "uniprotId": uniprot_id,
        "uniprotLink": gf("UniProt_Link"),
        "chemblId": chembl_id,
        "chemblLink": gf("ChEMBL Link"),
        "pubchemId": cid,
        "pubchemLink": gf("PubChem Link"),
        "smiles": gf("SMILES") or "",
        "inchi": gf("InChi") or "",
        "inchiKey": gf("InChiKey") or "",
        "iupacName": gf("IUPAC Name") or "", 
        "sequence": gf("Sequence") or "",
        "pdbData": pdb_text,
        "sdfData": sdf_text,
        "structure2d": structure2d_url,
        "image": structure2d_url,
        "structure3d": structure3d_url,
        "sdfFile": sdf_file_url,
        "expressionSystem": gf("Expression System") or "",
        
        "value": str(gf("Value") or ""),
        "method": gf("Method") or "",
        "comments": gf("Comment") or "",
       "sourceLinks":gf("Source_Links") or "",
       "source":gf("Source") or "",

        

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
