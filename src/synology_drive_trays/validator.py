"""Ground-truth validation and geometric accuracy verification for generated Synology CAD models."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import trimesh

from .generator import compute_mounting_holes
from .specs import SFF_25, SFF_35, TraySpec


@dataclass
class ValidationReport:
    """Quantitative comparison between our generated CAD mesh and a community ground-truth mesh."""
    tray_type: str
    ground_truth_file: str
    gen_extents_mm: tuple[float, float, float]
    gt_extents_mm: tuple[float, float, float]
    official_extents_mm: tuple[float, float, float]
    gen_rail_width_mm: float
    gt_rail_width_mm: float
    rail_width_error_mm: float
    gen_rail_height_mm: float
    gt_rail_height_mm: float
    rail_height_error_mm: float
    sff_hole_pitch_error_mm: float
    passed: bool


def _measure_mid_rail_span(mesh: trimesh.Trimesh) -> tuple[float, float]:
    """Slice mesh at X = 0.5 * L along its longest axis and measure (rail_width, rail_height) in mm."""
    order = np.argsort(mesh.extents)[::-1]
    L, W, H = mesh.extents[order]
    origin = mesh.bounds[0].copy()
    origin[order[0]] += 0.5 * L
    normal = np.zeros(3)
    normal[order[0]] = 1.0
    sec = mesh.section(plane_origin=origin, plane_normal=normal)
    if sec is None:
        return float(W), float(H)
    pts = sec.vertices[:, [order[1], order[2]]]
    spans = pts.max(axis=0) - pts.min(axis=0)
    return float(spans[0]), float(spans[1])


def validate_against_ground_truth(
    spec: TraySpec,
    generated_stl: Path,
    ground_truth_stl: Path,
) -> ValidationReport:
    """Compare a generated tray STL against a community ground-truth STL."""
    gen_mesh = trimesh.load(str(generated_stl), force="mesh")
    gt_mesh = trimesh.load(str(ground_truth_stl), force="mesh")

    gen_ext = tuple(sorted([round(float(x), 2) for x in gen_mesh.extents], reverse=True))
    gt_ext = tuple(sorted([round(float(x), 2) for x in gt_mesh.extents], reverse=True))
    off_ext = (round(spec.length_mm, 2), round(spec.width_mm, 2), round(spec.height_mm, 2))

    gen_rw, gen_rh = _measure_mid_rail_span(gen_mesh)
    gt_rw, gt_rh = _measure_mid_rail_span(gt_mesh)

    # Verify SFF hole pitch invariants on our generated hole set
    holes = compute_mounting_holes(spec)
    btm_35_y = sorted({round(h.y, 3) for h in holes if h.label.startswith("3.5_btm")})
    btm_25_y = sorted({round(h.y, 3) for h in holes if h.label.startswith("2.5_btm")})

    pitch_err = 0.0
    if spec.supports_35 and len(btm_35_y) == 2:
        pitch_err = max(pitch_err, abs((btm_35_y[1] - btm_35_y[0]) - SFF_35.bottom_hole_y_span))
    if spec.supports_25 and len(btm_25_y) == 2:
        pitch_err = max(pitch_err, abs((btm_25_y[1] - btm_25_y[0]) - SFF_25.bottom_hole_y_span))

    rw_err = abs(gen_rw - gt_rw)
    rh_err = abs(gen_rh - gt_rh)

    # Check that our generated outer bounding box matches Synology's official spec within 0.05 mm
    bbox_exact = all(abs(g - o) <= 0.05 for g, o in zip(gen_ext, off_ext))
    passed = bbox_exact and pitch_err < 0.01 and (rw_err <= 3.5 or spec.archetype.value == "holder_25")

    return ValidationReport(
        tray_type=spec.name,
        ground_truth_file=ground_truth_stl.name,
        gen_extents_mm=gen_ext,  # type: ignore[arg-type]
        gt_extents_mm=gt_ext,    # type: ignore[arg-type]
        official_extents_mm=off_ext,
        gen_rail_width_mm=round(gen_rw, 2),
        gt_rail_width_mm=round(gt_rw, 2),
        rail_width_error_mm=round(rw_err, 2),
        gen_rail_height_mm=round(gen_rh, 2),
        gt_rail_height_mm=round(gt_rh, 2),
        rail_height_error_mm=round(rh_err, 2),
        sff_hole_pitch_error_mm=round(pitch_err, 4),
        passed=passed,
    )
