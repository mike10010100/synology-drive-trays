"""Parametric CAD specification and SFF standards for all 32 Synology drive trays and holders."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path


class TrayArchetype(str, Enum):
    """Five structural archetypes covering all 32 Synology drive trays and holders."""
    DESKTOP_LOCK = "desktop_lock"          # Type D5, D6, D8, D9 (3.5"/2.5" tool-less with front lock bezel)
    DESKTOP_SLIDE = "desktop_slide"        # Type D1, D2, D3, D4, D7 (3.5"/2.5" slide-in tray)
    RACK_35 = "rack_35"                    # Type R1..R8, R10 (104-105mm wide rackmount 3.5"/2.5" caddy)
    TOPLOAD_60BAY = "topload_60bay"        # Type R9 (3.5") & 2.5" Drive Tray (R5) (159x117x21mm top-loader)
    SFF_25 = "sff_25"                      # 2.5" D1, Slim, SSD, 2.5" R1..R4, R6, R7 (dedicated 2.5" SFF caddies)
    HOLDER_25 = "holder_25"                # Disk Holder Type A, B, C (internal 2.5"-to-3.5" bay adapter bracket)


@dataclass(frozen=True)
class SFF8301Spec:
    """SFF-8301 / EIA-740 3.5-inch drive form-factor specification (all units in mm)."""
    drive_width: float = 101.60
    drive_length: float = 147.00
    drive_height_std: float = 26.10
    # Bottom mounting holes (#6-32 UNC, 3.8mm clearance)
    # Transverse distance from left side of drive (looking from front to rear, connector at rear)
    bottom_hole_y_inset: float = 3.18       # 95.25mm spacing centered on 101.60mm width
    bottom_hole_y_span: float = 95.25
    # Longitudinal distances measured forward from the REAR face of the 3.5" drive:
    bottom_hole_x_from_rear: tuple[float, ...] = (44.45, 88.90, 120.65)
    # Side mounting holes (#6-32 UNC / tool-less pin holes)
    side_hole_z_from_bottom: float = 6.35
    side_hole_x_from_rear: tuple[float, ...] = (28.50, 70.15, 101.60, 130.10)
    hole_clearance_dia: float = 3.80


@dataclass(frozen=True)
class SFF8201Spec:
    """SFF-8201 2.5-inch drive form-factor specification (all units in mm)."""
    drive_width: float = 69.85
    drive_length: float = 100.45
    drive_height_max: float = 12.50
    # Bottom mounting holes (M3, 3.2mm clearance)
    bottom_hole_y_inset: float = 4.065      # 61.72mm spacing centered on 69.85mm width
    bottom_hole_y_span: float = 61.72
    # Longitudinal distances measured forward from the REAR face of the 2.5" drive:
    bottom_hole_x_from_rear: tuple[float, ...] = (14.00, 90.60)
    # Side mounting holes (M3)
    side_hole_z_from_bottom: float = 3.00
    side_hole_x_from_rear: tuple[float, ...] = (14.00, 90.60)
    hole_clearance_dia: float = 3.20
    # Lateral offset of 2.5" drive left edge relative to 3.5" drive left edge
    # so that the SFF-8223 SATA connector aligns with the 3.5" SFF backplane receptacle:
    sata_align_left_offset_from_35_left: float = 10.80


SFF_35 = SFF8301Spec()
SFF_25 = SFF8201Spec()


@dataclass
class TraySpec:
    """Complete dimensional & structural specification for a single Synology tray/holder."""
    name: str
    slug: str
    hcl_id: int | None
    eol: bool
    archetype: TrayArchetype
    length_mm: float
    width_mm: float
    height_mm: float
    weight_kg: float | None
    has_lock: bool
    supports_35: bool
    supports_25: bool
    applied_models: list[str] = field(default_factory=list)
    # Derived / calibrated structural parameters (mm)
    bezel_thickness_mm: float = 14.0
    rail_width_mm: float | None = None      # Outer span across side guide rails (<= width_mm)
    rail_height_mm: float = 17.0            # Height of side walls along rail section
    floor_thickness_mm: float = 2.5         # Thickness of bottom web/ribs
    rear_sata_overhang_mm: float = 2.5      # How far drive rear face sits relative to rear rail tip


def _slugify(name: str) -> str:
    return (
        name.replace('2.5"', "25in")
        .replace('"', "")
        .replace("(", "")
        .replace(")", "")
        .replace("/", "_")
        .replace(" ", "_")
    )


def parse_dim_mm(dim_str: str | None) -> tuple[float, float, float] | None:
    if not dim_str:
        return None
    clean = dim_str.replace("cm", "").replace("\t", " ").strip()
    parts = [float(p.strip()) * 10.0 for p in clean.split("x") if p.strip()]
    if len(parts) == 3:
        parts.sort(reverse=True)
        return (parts[0], parts[1], parts[2])
    return None


def build_all_tray_specs(json_path: Path | None = None) -> dict[str, TraySpec]:
    """Load all 29 API trays + 3 legacy KB trays into calibrated TraySpec objects."""
    if json_path is None:
        json_path = Path(__file__).resolve().parent.parent.parent / "data" / "synology_trays.json"
    raw = json.loads(json_path.read_text())["trays"]

    specs: dict[str, TraySpec] = {}

    for name, info in sorted(raw.items()):
        dims = parse_dim_mm(info.get("dimension"))
        if dims is None:
            # Disk Tray (Type R1) has null dimensions in API; use R2 1U rack tray envelope
            dims = (171.0, 105.0, 27.0)
        L, W, H = dims
        wt_str = info.get("weight")
        wt = float(wt_str.replace("kg", "").strip()) if wt_str else None
        desc = info.get("description") or ""
        has_lock = "lock" in desc.lower()
        models = [m.strip() for m in (info.get("appliedModels") or "").split(",") if m.strip()]
        if name == "Disk Holder (Type C)":
            for extra in ["DS112+", "DS213air", "DX213"]:
                if extra not in models:
                    models.append(extra)

        # Classify archetype and calibrate parameters from ground-truth analysis
        if name == "Disk Holder (Type C)":
            arch = TrayArchetype.HOLDER_25
            supports_35, supports_25 = False, True
            bezel_t, rail_w, rail_h, floor_t, overhang = 4.0, W, H, 2.5, 0.0
        elif name.startswith('2.5"') or "Slim" in name or "SSD" in name:
            if name == '2.5" Drive Tray (R5)':
                arch = TrayArchetype.TOPLOAD_60BAY
                supports_35, supports_25 = False, True
                bezel_t, rail_w, rail_h, floor_t, overhang = 14.0, W, H, 2.5, 2.0
            else:
                arch = TrayArchetype.SFF_25
                supports_35, supports_25 = False, True
                bezel_t = 12.0 if L < 140 else 16.0
                rail_w = W
                rail_h = min(H, 14.0)
                floor_t = 2.0
                overhang = 2.5
        elif "Type D" in name:
            supports_35, supports_25 = True, True
            if name in ("Disk Tray (Type D5)", "Disk Tray (Type D6)", "Disk Tray (Type D8)", "Disk Tray (Type D9)"):
                arch = TrayArchetype.DESKTOP_LOCK
                bezel_t = 15.0
                rail_w = min(W, 113.5)   # Bezel flares to 118mm, rail body is 113.0-113.5mm
                rail_h = 17.0
                floor_t = 2.5
                overhang = 3.0
            else:
                # D1, D3, D4, D7
                arch = TrayArchetype.DESKTOP_SLIDE
                bezel_t = 13.0 if "D1" in name else 15.0
                rail_w = W if "D1" in name else min(W, 115.5)
                rail_h = min(H, 19.5)
                floor_t = 2.5
                overhang = 2.5
        elif name == "Drive Tray (Type R9)":
            arch = TrayArchetype.TOPLOAD_60BAY
            supports_35, supports_25 = True, False
            bezel_t, rail_w, rail_h, floor_t, overhang = 14.0, W, H, 2.5, 2.0
        else:
            # Type R1..R8, R10
            arch = TrayArchetype.RACK_35
            supports_35, supports_25 = True, True
            bezel_t = 16.0
            rail_w = W  # 104.0 - 105.0 mm (1.2 - 1.7 mm side walls around 101.6 mm drive)
            rail_h = 16.5 if "R7" in name or "R10" in name else 14.5
            floor_t = 2.2
            overhang = 3.0 if "R7" not in name else -5.23  # R7 sets drive 8.23mm deeper than R8

        specs[name] = TraySpec(
            name=name,
            slug=_slugify(name),
            hcl_id=info.get("hcl_id"),
            eol=bool(info.get("eol")),
            archetype=arch,
            length_mm=L,
            width_mm=W,
            height_mm=H,
            weight_kg=wt,
            has_lock=has_lock,
            supports_35=supports_35,
            supports_25=supports_25,
            applied_models=models,
            bezel_thickness_mm=bezel_t,
            rail_width_mm=rail_w,
            rail_height_mm=rail_h,
            floor_thickness_mm=floor_t,
            rear_sata_overhang_mm=overhang,
        )

    # Add the 3 legacy 2009 parts documented in Synology Knowledge Base
    legacy_specs = [
        TraySpec(
            name="Disk Tray (Type D2)",
            slug="Disk_Tray_Type_D2",
            hcl_id=None,
            eol=True,
            archetype=TrayArchetype.DESKTOP_SLIDE,
            length_mm=171.0,
            width_mm=112.0,
            height_mm=28.0,
            weight_kg=0.05,
            has_lock=False,
            supports_35=True,
            supports_25=True,
            applied_models=["DS509+", "DX5"],
            bezel_thickness_mm=15.0,
            rail_width_mm=112.0,
            rail_height_mm=18.5,
            floor_thickness_mm=2.5,
            rear_sata_overhang_mm=2.5,
        ),
        TraySpec(
            name="Disk Holder (Type A)",
            slug="Disk_Holder_Type_A",
            hcl_id=None,
            eol=True,
            archetype=TrayArchetype.HOLDER_25,
            length_mm=115.0,
            width_mm=103.0,
            height_mm=15.0,
            weight_kg=0.04,
            has_lock=False,
            supports_35=False,
            supports_25=True,
            applied_models=["DS109+", "DS109", "DS109j"],
            bezel_thickness_mm=4.0,
            rail_width_mm=103.0,
            rail_height_mm=15.0,
            floor_thickness_mm=2.5,
            rear_sata_overhang_mm=0.0,
        ),
        TraySpec(
            name="Disk Holder (Type B)",
            slug="Disk_Holder_Type_B",
            hcl_id=None,
            eol=True,
            archetype=TrayArchetype.HOLDER_25,
            length_mm=115.0,
            width_mm=103.0,
            height_mm=15.0,
            weight_kg=0.04,
            has_lock=False,
            supports_35=False,
            supports_25=True,
            applied_models=["DS409+", "DS209+II", "DS209+", "DS209", "DS209j"],
            bezel_thickness_mm=4.0,
            rail_width_mm=103.0,
            rail_height_mm=15.0,
            floor_thickness_mm=2.5,
            rear_sata_overhang_mm=0.0,
        ),
    ]
    for ls in legacy_specs:
        specs[ls.name] = ls

    return specs
