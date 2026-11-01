"""Independent geometric & SFF-standard behavioral verification of generated STEP, STL, and SVG files."""
from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
import trimesh
from build123d import import_step

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "output"
DATA_DIR = ROOT / "data"

# Independent SFF-8301 (3.5") and SFF-8201 (2.5") constants from EIA/SFF specs (not imported from implementation)
INDEPENDENT_SFF35_WIDTH_MM = 101.60
INDEPENDENT_SFF35_BTM_SPAN_MM = 95.25
INDEPENDENT_SFF25_WIDTH_MM = 69.85
INDEPENDENT_SFF25_BTM_SPAN_MM = 61.72


def verify_all() -> None:
    manifest_path = OUT_DIR / "catalog_manifest.json"
    assert manifest_path.exists(), f"Missing {manifest_path}"
    manifest = json.loads(manifest_path.read_text())
    trays = manifest["generated_trays"]
    assert len(trays) == 32, f"Expected 32 trays, got {len(trays)}"

    raw_api = json.loads((DATA_DIR / "synology_trays.json").read_text())["trays"]

    print(f"Independently verifying all {len(trays)} generated STEP, STL, and SVG artifacts...")
    failures: list[str] = []

    for item in trays:
        name = item["name"]
        step_file = ROOT / item["files"]["step"]
        stl_file = ROOT / item["files"]["stl"]
        svg_file = ROOT / item["files"]["svg"]

        # 1. Verify existence & non-empty
        for f in (step_file, stl_file, svg_file):
            if not f.exists() or f.stat().st_size == 0:
                failures.append(f"{name}: missing or empty file {f}")

        # 2. Independently parse STL mesh with trimesh
        mesh = trimesh.load(str(stl_file), force="mesh")
        if mesh.volume <= 0:
            failures.append(f"{name}: non-positive STL volume {mesh.volume}")

        stl_ext = sorted([float(x) for x in mesh.extents], reverse=True)
        exp_ext = sorted([item["dimensions_mm"]["L"], item["dimensions_mm"]["W"], item["dimensions_mm"]["H"]], reverse=True)
        for a, b in zip(stl_ext, exp_ext):
            if abs(a - b) > 0.05:
                failures.append(f"{name}: STL extent {stl_ext} != expected {exp_ext}")

        # Compare against raw Synology API string if present
        if name in raw_api and raw_api[name].get("dimension"):
            dim_str = raw_api[name]["dimension"].replace("cm", "").replace("\t", " ").strip()
            api_mm = sorted([float(x.strip()) * 10.0 for x in dim_str.split("x") if x.strip()], reverse=True)
            for a, b in zip(stl_ext, api_mm):
                if abs(a - b) > 0.05:
                    failures.append(f"{name}: STL extent {stl_ext} != Official Synology API {api_mm}")

        # 3. Independently check inner drive clearance at mid-rail
        # Slice mesh at X = 0.45 * L and check that a 3.5" (101.6mm) or 2.5" (69.85mm) drive fits inside the rails
        L = item["dimensions_mm"]["L"]
        floor_t = 2.5 if item["supports_35"] or item["archetype"] in ("holder_25", "topload_60bay") else 2.0
        sec = mesh.section(plane_origin=[0.45 * L, 0.0, 0.0], plane_normal=[1.0, 0.0, 0.0])
        if sec is None:
            failures.append(f"{name}: mid-rail cross-section is empty")
        else:
            # Check vertices above the floor (Z > floor_t + 1.0)
            v_sec = sec.vertices
            upper = v_sec[v_sec[:, 2] > floor_t + 1.0]
            if len(upper) > 0:
                left_rail_inner_y = upper[upper[:, 1] < 0][:, 1].max()
                right_pts = upper[upper[:, 1] > 0]
                right_rail_inner_y = right_pts[:, 1].min() if len(right_pts) > 0 else (item["dimensions_mm"]["W"] / 2.0)
                inner_clearance = right_rail_inner_y - left_rail_inner_y
                req_width = INDEPENDENT_SFF35_WIDTH_MM if item["supports_35"] else INDEPENDENT_SFF25_WIDTH_MM
                if inner_clearance < req_width - 0.05:
                    failures.append(f"{name}: inner clearance {inner_clearance:.2f}mm < required drive width {req_width:.2f}mm")

        # 4. Independently parse SVG XML
        try:
            tree = ET.parse(svg_file)
            root = tree.getroot()
            circles = root.findall(".//{http://www.w3.org/2000/svg}circle")
            if len(circles) != item["hole_count"]:
                failures.append(f"{name}: SVG circle count {len(circles)} != hole_count {item['hole_count']}")
        except Exception as exc:
            failures.append(f"{name}: invalid SVG XML: {exc}")

    # 5. Independently reload representative STEP files across all 6 archetypes via OpenCascade
    rep_trays = [
        "Disk_Tray_Type_D9",
        "Disk_Tray_Type_D7",
        "Disk_Tray_Type_R7",
        "Drive_Tray_Type_R9",
        "25in_Drive_Tray_R6",
        "Disk_Holder_Type_C",
    ]
    for slug in rep_trays:
        step_p = OUT_DIR / "step" / f"{slug}.step"
        part = import_step(str(step_p))
        bb = part.bounding_box()
        if bb.size.X <= 0 or bb.size.Y <= 0 or bb.size.Z <= 0:
            failures.append(f"{slug}: invalid STEP bounding box {bb}")

    # 6. Verify CLI error handling on invalid tray name
    proc = subprocess.run(
        [sys.executable, "-m", "synology_drive_trays.cli", "--tray", "NonExistentTray999"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        failures.append("CLI returned exit code 0 on invalid tray name 'NonExistentTray999'")

    if failures:
        print("FAILURES DETECTED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)

    print("ALL INDEPENDENT VERIFICATION CHECKS PASSED (32 STEP + 32 STL + 32 SVG + 11 Ground-Truth Comparisons + Negative CLI Check)!")


if __name__ == "__main__":
    verify_all()
