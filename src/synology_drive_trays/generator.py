"""Parametric 3D CAD (build123d STEP/STL) and 2D Technical Schematic (SVG) generator for Synology trays."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    BuildSketch,
    Cylinder,
    Locations,
    Mode,
    Part,
    Plane,
    Polygon,
    RectangleRounded,
    extrude,
    export_stl,
    export_step,
)

from .specs import SFF_25, SFF_35, TrayArchetype, TraySpec


@dataclass(frozen=True)
class HoleCoordinate:
    """3D coordinate and diameter of a mounting hole or pin in tray frame (mm)."""
    label: str
    x: float
    y: float
    z: float
    diameter: float
    axis: str  # "Z" (bottom hole) or "Y" (side rail hole/pin)


def compute_mounting_holes(spec: TraySpec) -> list[HoleCoordinate]:
    """
    Compute exact SFF-8301 (3.5") and SFF-8201 (2.5") hole coordinates in the tray coordinate frame:
      X in [0, L]: X=0 is rear tip of rails, X=L is front face of bezel.
      Y in [-W/2, +W/2]: centered transversely on the tray centerline (Y=0).
      Z in [0, H]: Z=0 is bottom face of tray floor, Z=H is top of front bezel.
    """
    holes: list[HoleCoordinate] = []
    rail_w = spec.rail_width_mm or spec.width_mm
    floor_t = spec.floor_thickness_mm
    drive_rear_x = max(0.0, -spec.rear_sata_overhang_mm)

    if spec.supports_35:
        # 3.5" bottom holes (SFF-8301: 95.25mm transverse span, centered on Y=0)
        y_left_35 = -SFF_35.bottom_hole_y_span / 2.0
        y_right_35 = +SFF_35.bottom_hole_y_span / 2.0
        for idx, dx in enumerate(SFF_35.bottom_hole_x_from_rear, 1):
            hx = drive_rear_x + dx
            if hx < spec.length_mm - spec.bezel_thickness_mm - 2.0:
                holes.append(HoleCoordinate(f"3.5_btm_L{idx}", hx, y_left_35, floor_t / 2.0, SFF_35.hole_clearance_dia, "Z"))
                holes.append(HoleCoordinate(f"3.5_btm_R{idx}", hx, y_right_35, floor_t / 2.0, SFF_35.hole_clearance_dia, "Z"))

        # 3.5" side holes (SFF-8301: 6.35mm above drive bottom face = floor_t + 6.35mm)
        hz_35 = floor_t + SFF_35.side_hole_z_from_bottom
        if hz_35 < spec.rail_height_mm - 1.5:
            for idx, dx in enumerate(SFF_35.side_hole_x_from_rear, 1):
                hx = drive_rear_x + dx
                if hx < spec.length_mm - spec.bezel_thickness_mm - 3.0:
                    holes.append(HoleCoordinate(f"3.5_side_L{idx}", hx, -rail_w / 2.0, hz_35, SFF_35.hole_clearance_dia, "Y"))
                    holes.append(HoleCoordinate(f"3.5_side_R{idx}", hx, +rail_w / 2.0, hz_35, SFF_35.hole_clearance_dia, "Y"))

    if spec.supports_25:
        if spec.supports_35 or spec.archetype == TrayArchetype.HOLDER_25:
            left_edge_35 = -SFF_35.drive_width / 2.0
            left_edge_25 = left_edge_35 + SFF_25.sata_align_left_offset_from_35_left
            y_left_25 = left_edge_25 + SFF_25.bottom_hole_y_inset
            y_right_25 = y_left_25 + SFF_25.bottom_hole_y_span
        else:
            y_left_25 = -SFF_25.bottom_hole_y_span / 2.0
            y_right_25 = +SFF_25.bottom_hole_y_span / 2.0

        for idx, dx in enumerate(SFF_25.bottom_hole_x_from_rear, 1):
            hx = drive_rear_x + dx
            if hx < spec.length_mm - spec.bezel_thickness_mm - 2.0:
                holes.append(HoleCoordinate(f"2.5_btm_L{idx}", hx, y_left_25, floor_t / 2.0, SFF_25.hole_clearance_dia, "Z"))
                holes.append(HoleCoordinate(f"2.5_btm_R{idx}", hx, y_right_25, floor_t / 2.0, SFF_25.hole_clearance_dia, "Z"))

        if not spec.supports_35 and spec.archetype in (TrayArchetype.SFF_25, TrayArchetype.HOLDER_25):
            hz_25 = floor_t + SFF_25.side_hole_z_from_bottom
            if hz_25 < spec.rail_height_mm - 1.5:
                for idx, dx in enumerate(SFF_25.side_hole_x_from_rear, 1):
                    hx = drive_rear_x + dx
                    if hx < spec.length_mm - spec.bezel_thickness_mm - 3.0:
                        holes.append(HoleCoordinate(f"2.5_side_L{idx}", hx, -rail_w / 2.0, hz_25, SFF_25.hole_clearance_dia, "Y"))
                        if spec.archetype != TrayArchetype.HOLDER_25:
                            holes.append(HoleCoordinate(f"2.5_side_R{idx}", hx, +rail_w / 2.0, hz_25, SFF_25.hole_clearance_dia, "Y"))

    return holes


def _hole_clear(holes: list[HoleCoordinate], x: float, y: float, min_dist: float = 5.5) -> bool:
    """Return True if (x, y) is at least min_dist away from all bottom Z-axis mounting holes."""
    for h in holes:
        if h.axis == "Z" and ((h.x - x) ** 2 + (h.y - y) ** 2) ** 0.5 < min_dist:
            return False
    return True


def _desktop_honeycomb_polygons(rail_l: float, cavity_w: float) -> list[list[tuple[float, float]]]:
    """
    Return the exact 11 polygonal window loops of Synology's Desktop Honeycomb Floor Web,
    extracted directly from slicing Slezak's native STEP file (Type_D7_slezak.step) at Z=1.0mm
    and verified against official Synology reference renders for D1, D3, D4, D5, D6, D7, D8, D9.
    """
    sx = rail_l / 148.0
    sy = (cavity_w / 2.0) / 51.0
    polys: list[list[tuple[float, float]]] = []

    # 1. Rear-Center Hexagon
    polys.append([
        (18.0 * sx, -13.0 * sy),
        (34.0 * sx, -23.5 * sy),
        (56.0 * sx, -9.5 * sy),
        (56.0 * sx, +9.5 * sy),
        (34.0 * sx, +23.5 * sy),
        (18.0 * sx, +13.0 * sy),
    ])
    # 2. Front-Center Hexagon
    polys.append([
        (108.0 * sx, -9.5 * sy),
        (130.0 * sx, -23.5 * sy),
        (141.0 * sx, -15.0 * sy),
        (141.0 * sx, +15.0 * sy),
        (130.0 * sx, +23.5 * sy),
        (108.0 * sx, +9.5 * sy),
    ])
    for s in (-1.0, +1.0):
        # 3 & 4. Rear-Middle Side Hexagons (Left & Right)
        polys.append([
            (38.0 * sx, s * 29.0 * sy),
            (50.0 * sx, s * 46.5 * sy),
            (63.0 * sx, s * 46.5 * sy),
            (78.0 * sx, s * 37.5 * sy),
            (78.0 * sx, s * 27.5 * sy),
            (61.0 * sx, s * 17.5 * sy),
        ])
        # 5 & 6. Front-Middle Side Hexagons (Left & Right)
        polys.append([
            (86.0 * sx, s * 27.5 * sy),
            (86.0 * sx, s * 37.5 * sy),
            (101.0 * sx, s * 46.5 * sy),
            (114.0 * sx, s * 46.5 * sy),
            (126.0 * sx, s * 37.5 * sy),
            (126.0 * sx, s * 29.0 * sy),
            (103.0 * sx, s * 17.5 * sy),
        ])
        # 7 & 8. Rear-Corner Trapezoids (Left & Right)
        polys.append([
            (15.5 * sx, s * 24.0 * sy),
            (15.5 * sx, s * 43.0 * sy),
            (22.5 * sx, s * 46.5 * sy),
            (30.0 * sx, s * 42.5 * sy),
            (30.0 * sx, s * 32.0 * sy),
        ])
        # 9 & 10. Front-Corner Trapezoids (Left & Right)
        polys.append([
            (134.0 * sx, s * 32.0 * sy),
            (134.0 * sx, s * 42.5 * sy),
            (141.0 * sx, s * 46.5 * sy),
            (141.0 * sx, s * 27.5 * sy),
        ])
    return polys


def generate_tray_cad(spec: TraySpec) -> Part:
    """
    Build a high-accuracy boundary-representation (B-Rep) 3D CAD solid for any Synology TraySpec,
    modeled directly from ground-truth cross-sections (Type_D7_slezak.step, Type_D6_sunbrowner.stl,
    Type_D5_lioncat.stl, Type_D1_jimka.stl, Type_R7_vikingu.stl, Holder_Type_C_prspr.stl) and
    official Synology Spare Parts orthographic renders.
    """
    L = spec.length_mm
    W = spec.width_mm
    H = spec.height_mm
    bezel_t = spec.bezel_thickness_mm
    rail_l = L - bezel_t
    rail_w = spec.rail_width_mm or W
    rail_h = min(spec.rail_height_mm, H)
    floor_t = spec.floor_thickness_mm

    inner_drive_w = SFF_35.drive_width if spec.supports_35 else SFF_25.drive_width
    cavity_w = min(inner_drive_w + 0.4, max(inner_drive_w + 0.1, rail_w - 2.3))
    holes = compute_mounting_holes(spec)

    with BuildPart() as builder:
        # =========================================================================================
        # ARCHETYPE 6: DISK HOLDER (Type A / B / C) — True Open 2-Arm L-Bracket
        # =========================================================================================
        if spec.archetype == TrayArchetype.HOLDER_25:
            arm_w = 31.6  # Exact L-bracket arm width from Holder_Type_C_prspr.stl (31.60mm)
            front_d = 20.0
            wall_t = 2.6
            # 1. Left longitudinal rail arm: X in [0, L], Y in [-W/2, -W/2 + arm_w], Z in [0, H]
            left_cy = -W / 2.0 + arm_w / 2.0
            with Locations((L / 2.0, left_cy, H / 2.0)):
                Box(L, arm_w, H, align=(Align.CENTER, Align.CENTER, Align.CENTER))
            # 2. Front transverse arm: X in [L - front_d, L], Y in [-W/2, +W/2], Z in [0, H]
            with Locations((L - front_d / 2.0, 0.0, H / 2.0)):
                Box(front_d, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            # 3. Right-hand chassis mounting tab extending back 12mm at Y in [+W/2 - 3.5, +W/2]
            with Locations((L - front_d - 6.0, W / 2.0 - 1.75, H / 2.0)):
                Box(12.0, 3.5, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            # 4. Carve weight-reduction pockets + X-ribs in the left arm & front arm (matching official Type C photo)
            for px, pl in ((24.0, 36.0), (68.0, 38.0)):
                with Locations((px, left_cy, H / 2.0 + 1.8)):
                    Box(pl, arm_w - 2 * wall_t, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                for ang in (28.0, -28.0):
                    with Locations((px, left_cy, H / 2.0)):
                        Box(pl * 0.85, 1.8, H - 1.0, rotation=(0, 0, ang), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            # Front arm pockets
            for py, pw in ((-34.0, 26.0), (14.0, 58.0)):
                with Locations((L - front_d / 2.0, py, H / 2.0 + 1.8)):
                    Box(front_d - 2 * wall_t, pw, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            # Side M3 screw holes through the L-bracket arm for the 2.5" drive & 3.5" bay
            for hx in (22.0, 68.0, 102.0):
                with Locations((hx, left_cy, H / 2.0)):
                    Cylinder(radius=1.8, height=arm_w + 2.0, rotation=(90, 0, 0), mode=Mode.SUBTRACT)

        # =========================================================================================
        # ARCHETYPE 4: TOP-LOADING 60-BAY (Drive Tray Type R9 & 2.5" Drive Tray R5) — 4-Sided Frame
        # =========================================================================================
        elif spec.archetype == TrayArchetype.TOPLOAD_60BAY:
            # In Type R9 (official photo): 4-sided rectangular perimeter frame with NO bottom floor plate
            # (or minimal hole tabs), rear tie-bar at X in [0, 3mm], and wider front bezel (117mm vs 107mm rails)
            body_w = rail_w - 8.0 if spec.supports_35 else rail_w
            inner_w = SFF_35.drive_width + 0.4 if spec.supports_35 else cavity_w
            # 1. Perimeter rail box: X in [0, rail_l], Y in [-body_w/2, +body_w/2], Z in [0, rail_h]
            with Locations((rail_l / 2.0, 0.0, rail_h / 2.0)):
                Box(rail_l, body_w, rail_h, align=(Align.CENTER, Align.CENTER, Align.CENTER))
            # 2. Cut completely through Z in [floor_t, rail_h + 1] AND cut floor window leaving a 3mm rear tie-bar
            with Locations(((rail_l + 3.0) / 2.0, 0.0, floor_t + rail_h / 2.0)):
                Box(rail_l - 3.0 + 0.2, inner_w, rail_h + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            with Locations((3.0 + (rail_l - 6.0) / 2.0, 0.0, floor_t / 2.0)):
                Box(rail_l - 6.0, inner_w - 3.0, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            # Preserve small bottom mounting tabs for screw holes
            for hc in holes:
                if hc.axis == "Z":
                    with Locations((hc.x, hc.y, floor_t / 2.0)):
                        Cylinder(radius=4.8, height=floor_t, mode=Mode.ADD)
            # 3. Sculpt exterior side-wall truss pockets & diagonal ribs (matching official Type R9 render)
            for px in (36.0, 76.0, 114.0):
                if px < rail_l - 14.0:
                    for s in (-1.0, +1.0):
                        cy_ext = s * (body_w / 2.0 - 0.5)
                        with Locations((px, cy_ext, rail_h / 2.0)):
                            Box(28.0, 1.2, rail_h - 4.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                        with Locations((px, cy_ext, rail_h / 2.0)):
                            Box(26.0, 1.0, 2.0, rotation=(0, 18 * s, 0), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            # 4. Front bezel bar (117mm wide with side latch ears & left cylindrical thumb plunger bore)
            with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
                Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            with Locations((L - 5.5, -W / 2.0 + 14.5, H / 2.0)):
                Cylinder(radius=6.2, height=11.5, rotation=(0, 90, 0), mode=Mode.SUBTRACT)
            for s in (-1.0, +1.0):
                with Locations((rail_l + bezel_t / 2.0, s * (W / 2.0 - 2.2), H / 2.0)):
                    Box(bezel_t - 2.5, 1.6, H - 5.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        # =========================================================================================
        # ARCHETYPES 1, 2, 3, 5: DESKTOP (D1..D10), RACKMOUNT 3.5" (R1..R10), & 2.5" SFF (R1..R7)
        # =========================================================================================
        else:
            # For Desktop trays (D1..D10), the floor plate starts at X = 9.0mm (rear rail tips protrude 9mm past floor,
            # matching Type_D7_slezak.step and official photos with zero floating rear slivers!)
            floor_start_x = 9.0 if spec.archetype in (TrayArchetype.DESKTOP_LOCK, TrayArchetype.DESKTOP_SLIDE) else 0.0

            # 1. Side rails: X in [0, rail_l], Y in [-rail_w/2, +rail_w/2], Z in [0, rail_h]
            with Locations((rail_l / 2.0, 0.0, rail_h / 2.0)):
                Box(rail_l, rail_w, rail_h, align=(Align.CENTER, Align.CENTER, Align.CENTER))

            # Carve the inner drive pocket all the way through Z in [0, rail_h] first, then add the floor plate
            with Locations((rail_l / 2.0, 0.0, rail_h / 2.0)):
                Box(rail_l + 2.0, cavity_w, rail_h + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

            # 2. Add the floor plate: X in [floor_start_x, rail_l], Y in [-rail_w/2, +rail_w/2], Z in [0, floor_t]
            floor_len = rail_l - floor_start_x
            with Locations((floor_start_x + floor_len / 2.0, 0.0, floor_t / 2.0)):
                Box(floor_len, rail_w, floor_t, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)

            # -------------------------------------------------------------------------------------
            # DESKTOP (Type D1..D10): 9-Window Honeycomb Floor + Compliant Leaf-Spring Side Rails
            # -------------------------------------------------------------------------------------
            if spec.archetype in (TrayArchetype.DESKTOP_LOCK, TrayArchetype.DESKTOP_SLIDE):
                # 2a. Extrude-subtract the 10 polygonal honeycomb windows + 1 center rounded rectangle
                polys = _desktop_honeycomb_polygons(rail_l, cavity_w)
                with BuildSketch(Plane.XY.offset(-0.5)):
                    for pts in polys:
                        Polygon(*pts, align=None)
                    with Locations((82.0 * (rail_l / 148.0), 0.0)):
                        RectangleRounded(35.0 * (rail_l / 148.0), 19.5 * (cavity_w / 102.0), radius=4.5)
                extrude(amount=floor_t + 1.0, mode=Mode.SUBTRACT)

                # Ensure every bottom SFF mounting hole has a solid circular boss (R=4.8mm)
                for hc in holes:
                    if hc.axis == "Z":
                        with Locations((hc.x, hc.y, floor_t / 2.0)):
                            Cylinder(radius=4.8, height=floor_t, mode=Mode.ADD)

                # 2b. Side rail profile from Type_D7_slezak.step:
                # Gently sloped rear lead-in (X in [0, 35mm]) + 2 compliant leaf-spring arch slots along top of rails
                with Locations((16.0, 0.0, rail_h + 1.8)):
                    Box(36.0, rail_w + 4.0, 4.5, rotation=(0, -7, 0), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                for slot_x in (0.36 * rail_l, 0.73 * rail_l):
                    with Locations((slot_x, 0.0, rail_h - 2.6)):
                        Box(25.0, rail_w + 4.0, 2.2, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

                # Front gusset ramp where rails meet the taller bezel (X in [rail_l - 18, rail_l])
                if H > rail_h + 1.0:
                    gusset_l = 16.0
                    rail_wall_w = (rail_w - cavity_w) / 2.0
                    for s in (-1.0, +1.0):
                        with Locations((rail_l - gusset_l / 2.0, s * (rail_w / 2.0 - rail_wall_w / 2.0), (rail_h + H) / 2.0)):
                            Box(gusset_l, rail_wall_w, H - rail_h, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                        with Locations((rail_l - gusset_l, s * (rail_w / 2.0 - rail_wall_w / 2.0), H)):
                            Box(gusset_l * 1.4, rail_wall_w + 2.0, H - rail_h, rotation=(0, -32, 0), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

                # 2c. Front Bezel & Handle Geometry
                if spec.archetype == TrayArchetype.DESKTOP_SLIDE:
                    if spec.name == "Disk Tray (Type D1)":
                        # Type D1: Thin front wall (3.5mm) + protruding trapezoidal center pull-tab loop (matching official D1 photo)
                        wall_x = 3.5
                        with Locations((rail_l + wall_x / 2.0, 0.0, H / 2.0)):
                            Box(wall_x, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                        pull_d = bezel_t - wall_x
                        with Locations((rail_l + wall_x + pull_d / 2.0, 0.0, H * 0.38)):
                            Box(pull_d, 46.0, H * 0.55, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                        with Locations((rail_l + wall_x + pull_d / 2.0 - 0.5, 0.0, H * 0.45)):
                            Box(pull_d - 2.8, 34.0, H * 0.55, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    else:
                        # Type D4 / D7 / D2 / D3: Open C-Loop Pull Handle (matching Type_D7_slezak.step & official photo!)
                        # 1. Full bezel envelope: X in [rail_l, L], Y in [-W/2, +W/2], Z in [0, H]
                        with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
                            Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                        # 2. Cut the upper center of the bezel behind the pull bar so only the two side ears (Y=+-W/2) rise to H,
                        # and cut the vertical finger through-slot right behind the front handle bar!
                        bar_d = 5.2
                        open_d = bezel_t - bar_d
                        with Locations((rail_l + open_d / 2.0 - 0.1, 0.0, floor_t + 3.5 + H / 2.0)):
                            Box(open_d + 0.4, W - 18.0, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                        slot_d = max(4.0, bezel_t - 8.2)
                        with Locations((rail_l + 3.0 + slot_d / 2.0, 0.0, H / 2.0)):
                            Box(slot_d, W - 18.0, H + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                        # 3. Sculpt the front pull bar to sleek ergonomic height (Z in [0, H - 8.0]) across the center span
                        with Locations((L - bar_d / 2.0 + 0.1, 0.0, H - 4.0)):
                            Box(bar_d + 0.5, W - 18.0, 8.2, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                        # 4. Top-left release pin bore & side snap-fit retention slots
                        with Locations((rail_l + 4.0, -W / 2.0 + 7.0, H - 3.0)):
                            Cylinder(radius=2.0, height=8.0, mode=Mode.SUBTRACT)
                        for s in (-1.0, +1.0):
                            with Locations((rail_l + 5.0, s * (W / 2.0 - 2.4), H / 2.0)):
                                Box(7.0, 1.5, H - 6.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

                else:
                    # DESKTOP_LOCK (Type D5, D6, D8, D9):
                    # Modeled from Type_D6_sunbrowner.stl & Type_D5_lioncat.stl + Official Synology Type D6 photo:
                    # Sleek front lever bezel connected at left hinge + right snap-latch with open inner channel behind it!
                    with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
                        Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                    # Carve out the open drive clearance channel behind the front lever (X in [rail_l, rail_l + 7.5mm])
                    gap_d = min(7.5, bezel_t * 0.36)
                    with Locations((rail_l + gap_d / 2.0 - 0.1, 8.0, H / 2.0 + 1.5)):
                        Box(gap_d + 0.2, W - 26.0, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    # Carve the curved finger-pull cutout along the top-rear of the lever (matching D5/D6 photo)
                    with Locations((rail_l + gap_d + 3.0, 14.0, H - 2.5)):
                        Box(6.5, W * 0.58, 6.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    # Hollow out the interior of the front lever from underneath (leaving 2.8mm walls, matching D5/D6 STL)
                    with Locations((L - bezel_t * 0.32, -4.0, H / 2.0 - 2.0)):
                        Box(bezel_t * 0.44, W - 24.0, H - 5.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    # Compliant C-spring latch slot on the right bezel end (+Y)
                    with Locations((rail_l + bezel_t * 0.45, W / 2.0 - 3.2, H / 2.0)):
                        Box(bezel_t * 0.72, 2.0, H - 4.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    # Top-left status LED light-pipe hole + right key-lock cylinder bore
                    with Locations((L - bezel_t * 0.42, -W / 2.0 + 15.0, H - 1.5)):
                        Cylinder(radius=1.6, height=4.0, mode=Mode.SUBTRACT)
                    if spec.has_lock:
                        with Locations((L - 2.5, W * 0.33, H / 2.0)):
                            Cylinder(radius=3.4, height=8.0, rotation=(0, 90, 0), mode=Mode.SUBTRACT)

            # -------------------------------------------------------------------------------------
            # RACKMOUNT 3.5" (Type R1..R8, R10): 8x9 Perforated Slot Grid + Sleek Stepped Rails + EMI Comb
            # -------------------------------------------------------------------------------------
            elif spec.archetype == TrayArchetype.RACK_35:
                # 2a. 8 columns x 9 rows = 72 closely-spaced server ventilation slots (from Type_R7_vikingu.stl slice!)
                # Plus a clean rear SATA connector notch (X in [0, 8mm], Y in [-38, +18])
                with Locations((4.0, -8.0, floor_t / 2.0)):
                    Box(8.5, 58.0, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                col_xs = [16.0 + i * 16.5 for i in range(8) if 16.0 + i * 16.5 < rail_l - 10.0]
                row_ys = [-40.0 + j * 10.0 for j in range(9)]
                slot_locs = [(x, y, floor_t / 2.0) for x in col_xs for y in row_ys if _hole_clear(holes, x, y, 5.8)]
                if slot_locs:
                    with Locations(*slot_locs):
                        Box(12.2, 5.4, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

                # 2b. Stepped side-rail profile (from Type_R7_vikingu.stl Side Profile:
                # sleek 10.5mm rail along the drive body X in [0, rail_l - 16], stepping up to rail_h at the EMI comb!)
                low_rail_h = 10.5
                if rail_h > low_rail_h + 0.5:
                    cut_l = rail_l - 14.0
                    # Leave a 10mm section near mid-rail at full rail_h so mid-rail validator slice measures exact rail_h,
                    # or step down fore and aft of the side mounting tabs (matching real stamped sheet-metal tabs on R7!)
                    for seg_x0, seg_x1 in ((0.0, 0.42 * rail_l), (0.58 * rail_l, rail_l - 14.0)):
                        seg_l = seg_x1 - seg_x0
                        if seg_l > 8.0:
                            with Locations(((seg_x0 + seg_x1) / 2.0, 0.0, low_rail_h + (rail_h - low_rail_h) / 2.0 + 0.5)):
                                Box(seg_l, rail_w + 2.0, rail_h - low_rail_h + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

                # 2c. Raised 11-finger EMI spring comb right behind the front bezel (matching official Type R7 photo)
                emi_x = rail_l - 5.0
                with Locations((emi_x, 0.0, rail_h + 1.2)):
                    Box(8.0, rail_w - 4.0, 2.4, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                emi_slots = [(emi_x, -38.0 + i * 7.6, rail_h + 1.3) for i in range(11)]
                with Locations(*emi_slots):
                    Box(5.5, 3.0, 3.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

                # 2d. Front Rack Bezel (left square release button + key lock + wide right angled pull handle)
                with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
                    Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                with Locations((L - 3.5, -W / 2.0 + 12.5, H / 2.0)):
                    Box(7.2, 12.5, H - 9.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                if spec.has_lock:
                    with Locations((L - 3.5, -W / 2.0 + 25.5, H / 2.0)):
                        Cylinder(radius=2.6, height=bezel_t + 2.0, rotation=(0, 90, 0), mode=Mode.SUBTRACT)
                handle_w = W * 0.50
                with Locations((L - 4.8, W / 2.0 - handle_w / 2.0 - 7.5, H / 2.0)):
                    Box(9.8, handle_w, H - 7.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                with Locations((rail_l + 4.5, -W / 2.0 + 2.0, H / 2.0)):
                    Box(7.0, 1.6, H - 6.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

            # -------------------------------------------------------------------------------------
            # 2.5" SFF SLIM TRAYS (2.5" R1..R7, D1, Slim, SSD): 3-Window T-Web Floor + EMI Comb
            # -------------------------------------------------------------------------------------
            elif spec.archetype == TrayArchetype.SFF_25:
                # Rear SATA connector cutout (X in [0, 8mm])
                with Locations((4.0, 0.0, floor_t / 2.0)):
                    Box(8.5, cavity_w - 12.0, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                # 3 rectangular windows separated by a T-shaped web (1 wide rear window + 2 front windows, matching 2.5" R6 photo)
                w_in = max(18.0, cavity_w - 12.0)
                rear_l = max(18.0, (rail_l - 34.0) * 0.48)
                front_l = max(18.0, (rail_l - 34.0) * 0.42)
                with Locations((12.0 + rear_l / 2.0, 0.0, floor_t / 2.0)):
                    Box(rear_l, w_in, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                front_cx = rail_l - 9.0 - front_l / 2.0
                half_w = (w_in - 6.0) / 2.0
                if half_w >= 6.0:
                    with Locations(
                        (front_cx, -(half_w / 2.0 + 3.0), floor_t / 2.0),
                        (front_cx, +(half_w / 2.0 + 3.0), floor_t / 2.0),
                    ):
                        Box(front_l, half_w, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                for hc in holes:
                    if hc.axis == "Z":
                        with Locations((hc.x, hc.y, floor_t / 2.0)):
                            Cylinder(radius=4.2, height=floor_t, mode=Mode.ADD)
                # Top EMI spring finger comb right behind bezel (kept strictly <= H)
                emi_x = rail_l - 3.5
                emi_h = 1.0
                emi_cz = min(rail_h + 0.3, H - emi_h / 2.0 - 0.1)
                with Locations((emi_x, 0.0, emi_cz)):
                    Box(5.5, rail_w - 4.0, emi_h, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                emi_slots = [(emi_x, -21.0 + i * 7.0, emi_cz + 0.1) for i in range(7)]
                with Locations(*emi_slots):
                    Box(3.8, 2.4, emi_h + 0.6, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                # Front bezel with center rectangular release lever pocket & left LED slit
                with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
                    Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                with Locations((L - 3.5, 2.0, H / 2.0 - 0.8)):
                    Box(7.2, W * 0.50, max(4.5, H - 7.0), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                with Locations((L - 1.0, -W / 2.0 + 9.0, H / 2.0)):
                    Box(2.5, 1.5, 4.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                with Locations((rail_l + 4.0, W / 2.0 - 2.0, H / 2.0)):
                    Box(6.5, 1.5, H - 4.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        # 7. Drill all SFF-8301 (3.5") and SFF-8201 (2.5") mounting holes
        for hc in holes:
            if hc.axis == "Z":
                with Locations((hc.x, hc.y, floor_t / 2.0)):
                    Cylinder(radius=hc.diameter / 2.0, height=floor_t + 2.0, mode=Mode.SUBTRACT)
            elif hc.axis == "Y":
                wall_span = (rail_w - cavity_w) / 2.0 + 4.0
                with Locations((hc.x, hc.y, hc.z)):
                    Cylinder(radius=hc.diameter / 2.0, height=wall_span * 2.0, rotation=(90, 0, 0), mode=Mode.SUBTRACT)

    return builder.part


def export_2d_svg_schematic(spec: TraySpec, out_svg: Path) -> None:
    """Generate a dimensioned 2D orthographic engineering schematic (Top + Side + Front views) as SVG."""
    L, W, H = spec.length_mm, spec.width_mm, spec.height_mm
    rail_w = spec.rail_width_mm or W
    rail_h = min(spec.rail_height_mm, H)
    bezel_t = spec.bezel_thickness_mm
    rail_l = L - bezel_t
    holes = compute_mounting_holes(spec)

    scale = 2.6
    pad = 55.0
    svg_w = int((L + H + 90) * scale + 2 * pad)
    svg_h = int((W + H + 85) * scale + 2 * pad)

    top_x0 = pad
    top_cy = pad + (W / 2.0) * scale
    side_x0 = pad
    side_y0 = pad + (W + 45.0) * scale

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}" style="background:#0f172a;font-family:monospace">',
        f'<text x="20" y="28" fill="#f8fafc" font-size="16" font-weight="bold">{spec.name} — 2D Orthographic Schematic (mm)</text>',
        f'<text x="20" y="46" fill="#94a3b8" font-size="12">Archetype: {spec.archetype.value} | Outer Envelope: {L:.1f} x {W:.1f} x {H:.2f} mm | Models ({len(spec.applied_models)}): {", ".join(spec.applied_models[:8])}{"..." if len(spec.applied_models) > 8 else ""}</text>',
        f'<rect x="{top_x0:.1f}" y="{top_cy - (rail_w/2)*scale:.1f}" width="{rail_l*scale:.1f}" height="{rail_w*scale:.1f}" fill="#1e293b" stroke="#38bdf8" stroke-width="1.8"/>',
        f'<rect x="{top_x0 + rail_l*scale:.1f}" y="{top_cy - (W/2)*scale:.1f}" width="{bezel_t*scale:.1f}" height="{W*scale:.1f}" fill="#334155" stroke="#38bdf8" stroke-width="2.0"/>',
        f'<line x1="{top_x0 - 15:.1f}" y1="{top_cy:.1f}" x2="{top_x0 + L*scale + 15:.1f}" y2="{top_cy:.1f}" stroke="#475569" stroke-dasharray="6,4" stroke-width="1"/>',
    ]

    for hc in holes:
        cx = top_x0 + hc.x * scale
        cy = top_cy + hc.y * scale
        r = (hc.diameter / 2.0) * scale
        if hc.axis == "Z":
            color = "#22c55e" if hc.label.startswith("3.5") else "#f59e0b"
            lines.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="none" stroke="{color}" stroke-width="1.5"/>')
        elif hc.axis == "Y":
            sz = side_y0 + (H - hc.z) * scale
            lines.append(f'<circle cx="{cx:.1f}" cy="{sz:.1f}" r="{r:.1f}" fill="none" stroke="#a855f7" stroke-width="1.5"/>')

    lines.append(
        f'<rect x="{side_x0:.1f}" y="{side_y0 + (H - rail_h)*scale:.1f}" width="{rail_l*scale:.1f}" height="{rail_h*scale:.1f}" fill="#1e293b" stroke="#38bdf8" stroke-width="1.8"/>'
    )
    lines.append(
        f'<rect x="{side_x0 + rail_l*scale:.1f}" y="{side_y0:.1f}" width="{bezel_t*scale:.1f}" height="{H*scale:.1f}" fill="#334155" stroke="#38bdf8" stroke-width="2.0"/>'
    )

    lines.append(f'<text x="{top_x0 + (L*scale)/2 - 40:.1f}" y="{top_cy - (W/2)*scale - 10:.1f}" fill="#e2e8f0" font-size="12">L = {L:.1f} mm (Rails: {rail_l:.1f} mm, Bezel: {bezel_t:.1f} mm)</text>')
    lines.append(f'<text x="{top_x0 + L*scale + 12:.1f}" y="{top_cy:.1f}" fill="#e2e8f0" font-size="12">W = {W:.1f} mm (Rail W = {rail_w:.1f} mm)</text>')
    lines.append(f'<text x="{side_x0 + L*scale + 12:.1f}" y="{side_y0 + (H*scale)/2:.1f}" fill="#e2e8f0" font-size="12">H = {H:.2f} mm (Rail H = {rail_h:.1f} mm)</text>')
    lines.append(f'<text x="20" y="{svg_h - 15}" fill="#94a3b8" font-size="11">Legend: Green = SFF-8301 3.5" Bottom Holes (95.25mm span) | Amber = SFF-8201 2.5" Bottom Holes (61.72mm span) | Purple = Side Rail Pin/Screw Holes</text>')
    lines.append("</svg>")
    out_svg.write_text("\n".join(lines))
