"""Automated test suite and preserved regression checks for Synology Drive Tray CAD pipeline."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import trimesh

from synology_drive_trays.cli import GROUND_TRUTH_PAIRS
from synology_drive_trays.generator import compute_mounting_holes, generate_tray_cad
from synology_drive_trays.specs import SFF_25, SFF_35, TrayArchetype, build_all_tray_specs
from synology_drive_trays.templates import COMMUNITY_TEMPLATE_MAP, generate_from_template, has_community_template
from synology_drive_trays.validator import validate_against_ground_truth

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "output"
GT_DIR = ROOT / "data" / "ground_truth"


@pytest.fixture(scope="module")
def all_specs():
    specs = build_all_tray_specs()
    assert len(specs) == 32
    return specs


def test_total_tray_and_model_coverage(all_specs):
    """Verify all 32 Synology tray types and 288 removable-tray models (322 total with trayless/legacy) are covered."""
    models = {m for s in all_specs.values() for m in s.applied_models}
    raw_api = json.loads((ROOT / "data" / "synology_trays.json").read_text())
    assert len(all_specs) == 32
    assert len(models) == 288
    assert len(raw_api["trays"]) == 29


def test_sff_hole_coordinate_invariants(all_specs):
    """Verify SFF-8301 (3.5" 95.25mm span) and SFF-8201 (2.5" 61.72mm span) hole pitches on all trays."""
    for name, spec in all_specs.items():
        holes = compute_mounting_holes(spec)
        assert len(holes) >= 4, f"{name} has fewer than 4 mounting holes"

        btm_35 = [h for h in holes if h.label.startswith("3.5_btm_")]
        if spec.supports_35:
            assert len(btm_35) >= 4
            ys = sorted({round(h.y, 3) for h in btm_35})
            assert len(ys) == 2
            assert abs((ys[1] - ys[0]) - 95.25) < 1e-3, f"{name}: 3.5\" bottom transverse span != 95.25mm"

        btm_25 = [h for h in holes if h.label.startswith("2.5_btm_")]
        if spec.supports_25:
            assert len(btm_25) >= 4
            ys = sorted({round(h.y, 3) for h in btm_25})
            assert len(ys) == 2
            assert abs((ys[1] - ys[0]) - 61.72) < 1e-3, f"{name}: 2.5\" bottom transverse span != 61.72mm"


def test_regression_r3_and_holder_inner_drive_clearance(all_specs):
    """
    Regression test for discovered bug:
      - 2.5" Disk Tray (R3) (outer width 71.0mm) previously subtracted 2.3mm wall thickness -> 68.70mm < 69.85mm 2.5" SFF width.
      - Disk Holder (Type A/B/C) previously required 101.60mm 3.5" inner clearance instead of 69.85mm 2.5" drive pocket.
    """
    for target_name in ("2.5\" Disk Tray (R3)", "Disk Holder (Type C)", "Disk Holder (Type A)", "Disk Holder (Type B)"):
        spec = all_specs[target_name]
        part = generate_tray_cad(spec)
        bb = part.bounding_box()
        assert abs(bb.size.X - spec.length_mm) < 0.05
        assert abs(bb.size.Y - spec.width_mm) < 0.05
        assert abs(bb.size.Z - spec.height_mm) < 0.05

        stl_path = OUT_DIR / "stl" / f"{spec.slug}.stl"
        mesh = trimesh.load(str(stl_path), force="mesh")
        sec = mesh.section(plane_origin=[0.45 * spec.length_mm, 0.0, 0.0], plane_normal=[1.0, 0.0, 0.0])
        assert sec is not None
        upper = sec.vertices[sec.vertices[:, 2] > spec.floor_thickness_mm + 1.0]
        left_inner = upper[upper[:, 1] < 0][:, 1].max()
        right_pts = upper[upper[:, 1] > 0]
        right_inner = right_pts[:, 1].min() if len(right_pts) > 0 else (spec.width_mm / 2.0)
        clearance = right_inner - left_inner
        assert clearance >= SFF_25.drive_width - 0.05, (
            f"{target_name}: inner clearance {clearance:.2f}mm < 2.5\" drive width {SFF_25.drive_width}mm"
        )


def test_all_generated_outputs_and_ground_truth_validation(all_specs):
    """Verify all 32 STEP, STL, and SVG files exist, match official dimensions, and pass ground-truth checks."""
    for name, spec in all_specs.items():
        step_p = OUT_DIR / "step" / f"{spec.slug}.step"
        stl_p = OUT_DIR / "stl" / f"{spec.slug}.stl"
        svg_p = OUT_DIR / "svg_schematics" / f"{spec.slug}.svg"
        assert step_p.exists() and step_p.stat().st_size > 1000
        assert stl_p.exists() and stl_p.stat().st_size > 1000
        assert svg_p.exists() and svg_p.stat().st_size > 500

        # Check SVG XML validity
        ET.parse(svg_p)

    # Check community ground-truth validation
    for tray_name, gt_fname in GROUND_TRUTH_PAIRS:
        spec = all_specs[tray_name]
        stl_p = OUT_DIR / "stl" / f"{spec.slug}.stl"
        gt_p = GT_DIR / gt_fname
        rep = validate_against_ground_truth(spec, stl_p, gt_p)
        assert rep.passed, f"Ground-truth validation failed for {tray_name} vs {gt_fname}: {rep}"


def test_template_first_coverage_and_warping(all_specs):
    """Verify that 21/32 trays use human-sculpted community CAD templates (11 exact + 10 warped) and 11 use procedural CAD."""
    template_count = 0
    procedural_count = 0
    for name, spec in all_specs.items():
        if has_community_template(name):
            template_count += 1
            mesh, meta = generate_from_template(spec)
            assert meta["source_mode"] in ("community_template_exact", "community_template_warped")
            assert abs(mesh.extents[0] - spec.length_mm) < 0.05
            assert abs(mesh.extents[1] - spec.width_mm) < 0.05
            assert abs(mesh.extents[2] - spec.height_mm) < 0.05
        else:
            procedural_count += 1
    assert template_count == 21
    assert procedural_count == 11
    assert len(COMMUNITY_TEMPLATE_MAP) == 21

