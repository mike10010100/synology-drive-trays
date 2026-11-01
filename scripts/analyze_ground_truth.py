"""Analyze ground-truth community STL/STEP models against official Synology API dimensions and SFF specs."""
import json
from pathlib import Path
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent.parent
GT_DIR = ROOT / "data" / "ground_truth"
TRAYS_JSON = ROOT / "data" / "synology_trays.json"

def parse_syno_dim(dim_str: str | None) -> tuple[float, float, float] | None:
    if not dim_str:
        return None
    # e.g. "17.2 x11.8 x2.8 cm" -> (172.0, 118.0, 28.0) mm sorted descending
    clean = dim_str.replace("cm", "").replace("\t", " ").strip()
    parts = [float(p.strip()) * 10.0 for p in clean.split("x") if p.strip()]
    if len(parts) == 3:
        return tuple(sorted(parts, reverse=True))
    return None

def analyze():
    trays_data = json.loads(TRAYS_JSON.read_text())["trays"]
    manifest = json.loads((GT_DIR / "manifest.json").read_text())

    print(f"{'File':30s} | {'Tray Type':22s} | {'GT Extents (mm, sorted)':26s} | {'Official API (mm)':22s} | {'Delta (L, W, H) mm'}")
    print("-" * 125)
    for item in manifest:
        fname = item["filename"]
        ttype = item["tray_type"]
        fpath = GT_DIR / fname
        if fname.endswith(".step"):
            fpath = GT_DIR / "Type_D7_slezak_from_step.stl"
        if not fpath.exists():
            continue
        mesh = trimesh.load(str(fpath), force="mesh")
        gt_ext = tuple(sorted([float(x) for x in mesh.extents], reverse=True))
        syno_info = trays_data.get(ttype, {})
        syno_ext = parse_syno_dim(syno_info.get("dimension"))
        gt_str = f"{gt_ext[0]:6.2f} x {gt_ext[1]:6.2f} x {gt_ext[2]:5.2f}"
        if syno_ext:
            syno_str = f"{syno_ext[0]:6.2f} x {syno_ext[1]:6.2f} x {syno_ext[2]:5.2f}"
            delta = (gt_ext[0] - syno_ext[0], gt_ext[1] - syno_ext[1], gt_ext[2] - syno_ext[2])
            delta_str = f"({delta[0]:+6.2f}, {delta[1]:+6.2f}, {delta[2]:+5.2f})"
        else:
            syno_str = "N/A"
            delta_str = "N/A"
        print(f"{fname:30s} | {ttype:22s} | {gt_str:26s} | {syno_str:22s} | {delta_str}")

if __name__ == "__main__":
    analyze()
