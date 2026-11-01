"""CLI entry point to generate STEP, STL, and 2D SVG schematics for all 32 Synology trays and validate against ground truth."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from build123d import export_step, export_stl

from .generator import compute_mounting_holes, export_2d_svg_schematic, generate_tray_cad
from .specs import build_all_tray_specs
from .validator import validate_against_ground_truth

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "output"
GT_DIR = ROOT / "data" / "ground_truth"

GROUND_TRUTH_PAIRS = [
    ("Disk Tray (Type D1)", "Type_D1_jimka.stl"),
    ("Disk Tray (Type D1)", "Type_D1_ds409.stl"),
    ("Disk Tray (Type D5)", "Type_D5_lioncat.stl"),
    ("Disk Tray (Type D6)", "Type_D6_sunbrowner.stl"),
    ("Disk Tray (Type D6)", "Type_D6_25in_urill.stl"),
    ("Disk Tray (Type D7)", "Type_D7_slezak_from_step.stl"),
    ("Disk Tray (Type D7)", "Type_D7_kai.stl"),
    ("Disk Tray (Type D8)", "Type_D8_25in_kairi_1.stl"),
    ("Disk Tray (Type R7)", "Type_R7_vikingu.stl"),
    ("Disk Tray (Type R8)", "Type_R8_th0r88.stl"),
    ("Disk Holder (Type C)", "Holder_Type_C_prspr.stl"),
]


def run_pipeline(only_tray: str | None = None) -> int:
    step_dir = OUT_DIR / "step"
    stl_dir = OUT_DIR / "stl"
    svg_dir = OUT_DIR / "svg_schematics"
    for d in (step_dir, stl_dir, svg_dir):
        d.mkdir(parents=True, exist_ok=True)

    specs = build_all_tray_specs()
    if only_tray:
        if only_tray not in specs:
            print(f"Error: unknown tray '{only_tray}'. Available: {list(specs.keys())}")
            return 1
        specs = {only_tray: specs[only_tray]}

    catalog_summary = []
    print(f"Generating 3D CAD (STEP + STL) and 2D Schematics (SVG) for {len(specs)} Synology tray types...")
    print("-" * 110)

    for name, spec in specs.items():
        part = generate_tray_cad(spec)
        bb = part.bounding_box()
        step_path = step_dir / f"{spec.slug}.step"
        stl_path = stl_dir / f"{spec.slug}.stl"
        svg_path = svg_dir / f"{spec.slug}.svg"

        export_step(part, str(step_path))
        export_stl(part, str(stl_path))
        export_2d_svg_schematic(spec, svg_path)

        holes = compute_mounting_holes(spec)
        dims_actual = (round(bb.size.X, 2), round(bb.size.Y, 2), round(bb.size.Z, 2))
        print(
            f"  [OK] {name:26s} | {spec.archetype.value:14s} | "
            f"BBox: {dims_actual[0]:6.2f} x {dims_actual[1]:6.2f} x {dims_actual[2]:5.2f} mm | "
            f"Holes: {len(holes):2d} | Models: {len(spec.applied_models):2d}"
        )
        catalog_summary.append({
            "name": name,
            "slug": spec.slug,
            "hcl_id": spec.hcl_id,
            "eol": spec.eol,
            "archetype": spec.archetype.value,
            "dimensions_mm": {"L": dims_actual[0], "W": dims_actual[1], "H": dims_actual[2]},
            "rail_width_mm": spec.rail_width_mm,
            "rail_height_mm": spec.rail_height_mm,
            "has_lock": spec.has_lock,
            "supports_35": spec.supports_35,
            "supports_25": spec.supports_25,
            "hole_count": len(holes),
            "applied_models": spec.applied_models,
            "files": {
                "step": str(step_path.relative_to(ROOT)),
                "stl": str(stl_path.relative_to(ROOT)),
                "svg": str(svg_path.relative_to(ROOT)),
            },
        })

    # Run ground-truth validation if all trays or validated trays were generated
    all_specs = build_all_tray_specs()
    reports = []
    print("\nRunning Ground-Truth Validation against Community CAD Models:")
    print("-" * 110)
    print(f"{'Tray Type':24s} | {'Ground-Truth File':28s} | {'Gen Rail (W,H)':16s} | {'GT Rail (W,H)':16s} | {'Rail W Δ':9s} | {'Status'}")
    print("-" * 110)
    for tname, gt_fname in GROUND_TRUTH_PAIRS:
        if only_tray and tname != only_tray:
            continue
        spec = all_specs[tname]
        gen_stl = stl_dir / f"{spec.slug}.stl"
        gt_stl = GT_DIR / gt_fname
        if gen_stl.exists() and gt_stl.exists():
            rep = validate_against_ground_truth(spec, gen_stl, gt_stl)
            reports.append(asdict(rep))
            status = "PASS" if rep.passed else "DIFF"
            print(
                f"{rep.tray_type:24s} | {rep.ground_truth_file:28s} | "
                f"({rep.gen_rail_width_mm:6.2f}, {rep.gen_rail_height_mm:5.2f}) | "
                f"({rep.gt_rail_width_mm:6.2f}, {rep.gt_rail_height_mm:5.2f}) | "
                f"{rep.rail_width_error_mm:6.2f} mm | {status}"
            )

    (OUT_DIR / "catalog_manifest.json").write_text(json.dumps({
        "generated_trays": catalog_summary,
        "validation_reports": reports,
    }, indent=2))
    print(f"\nSaved full manifest to {OUT_DIR / 'catalog_manifest.json'}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate STEP/STL/SVG CAD models for Synology drive trays.")
    parser.add_argument("--tray", type=str, default=None, help="Generate only a specific tray type by name.")
    args = parser.parse_args()
    raise SystemExit(run_pipeline(only_tray=args.tray))


if __name__ == "__main__":
    main()
