"""Parametric 3D CAD (STEP/STL) and 2D schematic (SVG) pipeline for all Synology drive trays."""
from .generator import HoleCoordinate, compute_mounting_holes, export_2d_svg_schematic, generate_tray_cad
from .specs import SFF_25, SFF_35, TrayArchetype, TraySpec, build_all_tray_specs
from .validator import ValidationReport, validate_against_ground_truth

__all__ = [
    "HoleCoordinate",
    "SFF_25",
    "SFF_35",
    "TrayArchetype",
    "TraySpec",
    "ValidationReport",
    "build_all_tray_specs",
    "compute_mounting_holes",
    "export_2d_svg_schematic",
    "generate_tray_cad",
    "validate_against_ground_truth",
]
