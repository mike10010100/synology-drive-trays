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
    fillet,
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
        if spec.supports_35 or spec.archetype in (TrayArchetype.HOLDER_25, TrayArchetype.TOPLOAD_60BAY):
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

        if spec.archetype == TrayArchetype.HOLDER_25:
            # Disk Holder (Type A/B/C) mounts 2.5" drives via left-side SFF-8201 holes + 3.5" bay holes
            for idx, hx in enumerate((22.0, 102.0), 1):
                holes.append(HoleCoordinate(f"bay_side_L{idx}", hx, -rail_w / 2.0, spec.height_mm / 2.0, 3.4, "Y"))
            holes.append(HoleCoordinate("bay_side_R1", spec.length_mm - 26.0, +rail_w / 2.0, spec.height_mm / 2.0, 3.4, "Y"))

    return holes


def _hole_clear(holes: list[HoleCoordinate], x: float, y: float, min_dist: float = 6.2) -> bool:
    """Return True if (x, y) is at least min_dist away from all bottom Z-axis mounting holes."""
    for h in holes:
        if h.axis == "Z" and ((h.x - x) ** 2 + (h.y - y) ** 2) ** 0.5 < min_dist:
            return False
    return True


def _desktop_honeycomb_polygons(rail_l: float, cavity_w: float) -> list[list[tuple[float, float]]]:
    """
    Return the 10 polygonal window loops of Synology's Desktop Honeycomb Floor Web,
    extracted from Type_D7_slezak.step and inset to max |Y| <= 42.5mm so every window
    clears the SFF-8301 3.5" bottom screw holes (at Y = +-47.625mm) and SFF-8201 2.5"
    bottom screw holes (at X = 40.0, 85.0mm) with uniform 5.5mm struts and zero boss collisions.
    """
    sx = rail_l / 148.0
    # Cap outer Y to 42.0mm so the outer rim (42.0..51.0mm) completely contains the +-47.625mm 3.5" bottom holes!
    max_y = min(42.0, cavity_w / 2.0 - 8.5)
    sy = max_y / 42.0
    polys: list[list[tuple[float, float]]] = []

    # 1. Rear-Center Hexagon
    polys.append([
        (18.0 * sx, -12.5 * sy),
        (33.5 * sx, -22.0 * sy),
        (55.0 * sx, -9.0 * sy),
        (55.0 * sx, +9.0 * sy),
        (33.5 * sx, +22.0 * sy),
        (18.0 * sx, +12.5 * sy),
    ])
    # 2. Front-Center Hexagon
    polys.append([
        (109.0 * sx, -9.0 * sy),
        (130.0 * sx, -22.0 * sy),
        (140.0 * sx, -14.0 * sy),
        (140.0 * sx, +14.0 * sy),
        (130.0 * sx, +22.0 * sy),
        (109.0 * sx, +9.0 * sy),
    ])
    for s in (-1.0, +1.0):
        # 3 & 4. Rear-Middle Side Hexagons (Left & Right — clear of X=41.28, Y=-36.9 2.5" hole)
        polys.append([
            (45.5 * sx, s * 28.0 * sy),
            (53.0 * sx, s * 41.5 * sy),
            (66.0 * sx, s * 41.5 * sy),
            (78.0 * sx, s * 34.0 * sy),
            (78.0 * sx, s * 25.5 * sy),
            (62.0 * sx, s * 16.5 * sy),
        ])
        # 5 & 6. Front-Middle Side Hexagons (Left & Right — clear of X=85.7, Y=-36.9 2.5" hole)
        polys.append([
            (92.0 * sx, s * 25.5 * sy),
            (92.0 * sx, s * 34.0 * sy),
            (103.0 * sx, s * 41.5 * sy),
            (116.0 * sx, s * 41.5 * sy),
            (126.0 * sx, s * 34.5 * sy),
            (126.0 * sx, s * 27.5 * sy),
            (106.0 * sx, s * 16.5 * sy),
        ])
        # 7 & 8. Rear-Corner Trapezoids (Left & Right — started at 21.5*sx to clear X=14.0mm 2.5" bottom holes)
        polys.append([
            (21.5 * sx, s * 25.0 * sy),
            (21.5 * sx, s * 39.5 * sy),
            (25.5 * sx, s * 41.5 * sy),
            (31.5 * sx, s * 38.0 * sy),
            (31.5 * sx, s * 31.0 * sy),
        ])
        # 9 & 10. Front-Corner Trapezoids (Left & Right)
        polys.append([
            (133.5 * sx, s * 30.0 * sy),
            (133.5 * sx, s * 38.5 * sy),
            (140.0 * sx, s * 41.5 * sy),
            (140.0 * sx, s * 25.5 * sy),
        ])
    return polys


def generate_tray_cad(spec: TraySpec) -> Part:
    """
    Build a functional, 1-piece 3D-printable B-Rep CAD solid for any Synology TraySpec.
    Combines:
      - Official Synology outer envelope and sliding rail dimensions
      - Ground-truth cross-sections (Type_D7_slezak.step, Type_D6_sunbrowner.stl, Type_D5_lioncat.stl,
        Type_D1_jimka_nosupports.stl, Type_R7_vikingu.stl, Type_R8_th0r88.stl, Holder_Type_C_prspr.stl)
      - Community 3D-printing Quality-of-Life (QoL) improvements:
          * Zero multi-part sheet-metal/hinge photo artifacts (no fake plastic EMI teeth or non-moving lock cylinders)
          * Integrated 1-piece print-in-place compliant spring latches & ergonomic pull handles
          * 100% flat build-plate base (Z=0) with support-free overhangs (e.g. Jimka D1 bottom-flush arch handle)
          * Countersunk M3 screw recesses on side rails and floor underside so standard M3 screws sit flush
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
        # ARCHETYPE 6: DISK HOLDER (Type A / B / C) — Pure Open 2-Arm L-Bracket (prspr QoL style)
        # =========================================================================================
        if spec.archetype == TrayArchetype.HOLDER_25:
            arm_w = 31.6  # Exact L-bracket left arm width from Holder_Type_C_prspr.stl (31.60mm)
            front_d = 20.0
            wall_t = 2.8
            left_cy = -W / 2.0 + arm_w / 2.0
            # 1. Left longitudinal rail arm: X in [0, L], Y in [-W/2, -W/2 + arm_w], Z in [0, H]
            with Locations((L / 2.0, left_cy, H / 2.0)):
                Box(L, arm_w, H, align=(Align.CENTER, Align.CENTER, Align.CENTER))
            # 2. Front transverse arm: X in [L - front_d, L], Y in [-W/2, +W/2], Z in [0, H]
            with Locations((L - front_d / 2.0, 0.0, H / 2.0)):
                Box(front_d, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            # 3. Right-hand chassis mounting ear extending back 14mm at Y in [+W/2 - 3.6, +W/2]
            with Locations((L - front_d - 7.0, W / 2.0 - 1.8, H / 2.0)):
                Box(14.0, 3.6, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            # 4. Weight-reduction pockets + X-stiffening ribs in left arm & front arm
            for px, pl in ((24.0, 36.0), (68.0, 38.0)):
                with Locations((px, left_cy, H / 2.0 + 1.8)):
                    Box(pl, arm_w - 2 * wall_t, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                for ang in (28.0, -28.0):
                    with Locations((px, left_cy, H / 2.0)):
                        Box(pl * 0.85, 1.8, H - 1.0, rotation=(0, 0, ang), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            for py, pw in ((-34.0, 26.0), (14.0, 58.0)):
                with Locations((L - front_d / 2.0, py, H / 2.0 + 1.8)):
                    Box(front_d - 2 * wall_t, pw, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            # 5. Drill & counterbore all 2.5" drive side holes and 3.5" bay mounting holes (including right ear hole!)
            for hx in (16.0, 48.0, 76.0, 102.0):
                with Locations((hx, left_cy, H / 2.0)):
                    Cylinder(radius=1.75, height=arm_w + 2.0, rotation=(90, 0, 0), mode=Mode.SUBTRACT)
            with Locations((L - front_d - 7.0, W / 2.0 - 1.8, H / 2.0)):
                Cylinder(radius=1.75, height=6.0, rotation=(90, 0, 0), mode=Mode.SUBTRACT)

        # =========================================================================================
        # ARCHETYPE 4: TOP-LOADING 60-BAY (Drive Tray Type R9 & 2.5" Drive Tray R5) — 4-Sided Frame
        # =========================================================================================
        elif spec.archetype == TrayArchetype.TOPLOAD_60BAY:
            body_w = rail_w - 8.0
            inner_w = SFF_35.drive_width + 0.4
            # 1. 4-sided rectangular 60-bay perimeter frame: X in [0, rail_l], Y in [-body_w/2, +body_w/2], Z in [0, rail_h]
            with Locations((rail_l / 2.0, 0.0, rail_h / 2.0)):
                Box(rail_l, body_w, rail_h, align=(Align.CENTER, Align.CENTER, Align.CENTER))
            # Cut out the interior so the outer frame has uniform 3.5mm side walls and a 3.2mm rear tie-bar
            with Locations(((rail_l + 3.2) / 2.0, 0.0, rail_h / 2.0)):
                Box(rail_l - 3.2 + 0.2, inner_w, rail_h + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

            if not spec.supports_35:
                # 2.5" Drive Tray (R5) (2.5in_Drive_Tray_R5_37031.png):
                # Inside the 3.5" 60-bay perimeter frame, add the left-offset L-shaped 2.5" SFF adapter tray
                # (X in [0, 104.0mm], Y in [-inner_w/2, +30.0mm]) with an inner left guide wall at Y = -40.2mm
                # and 7 circular ventilation holes (Ø 13mm) in the floor plate!
                tray_l = 104.0
                y_left_wall = -SFF_35.drive_width / 2.0 + SFF_25.sata_align_left_offset_from_35_left - 1.2  # -41.2mm
                y_right_edge = y_left_wall + SFF_25.drive_width + 3.0  # +31.65mm
                floor_span_y = y_right_edge - (-inner_w / 2.0)
                floor_cy = (-inner_w / 2.0 + y_right_edge) / 2.0
                with Locations((tray_l / 2.0, floor_cy, floor_t / 2.0)):
                    Box(tray_l, floor_span_y, floor_t, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                # Inner vertical 2.5" left guide wall (X in [3.2, tray_l], Y in [y_left_wall - 2.2, y_left_wall], Z in [0, 16.5mm])
                wall_h_25 = 16.5
                with Locations(((tray_l + 3.2) / 2.0, y_left_wall - 1.1, wall_h_25 / 2.0)):
                    Box(tray_l - 3.2, 2.2, wall_h_25, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                # 2 stiffening ribs bridging outer left frame wall (-51.0mm) to inner 2.5" left wall (-41.2mm)
                for rx in (24.0, 82.0):
                    with Locations((rx, (-inner_w / 2.0 + y_left_wall) / 2.0, wall_h_25 / 2.0)):
                        Box(2.5, y_left_wall - (-inner_w / 2.0), wall_h_25, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                # 7 circular ventilation holes (Ø 13.0mm) in the 2.5" floor plate matching 2.5in_Drive_Tray_R5_37031.png
                vent_pts = [
                    (32.0, -22.0, floor_t / 2.0),
                    (52.0, -22.0, floor_t / 2.0),
                    (72.0, -22.0, floor_t / 2.0),
                    (42.0, -5.0, floor_t / 2.0),
                    (62.0, -5.0, floor_t / 2.0),
                    (82.0, -5.0, floor_t / 2.0),
                    (52.0, +12.0, floor_t / 2.0),
                ]
                with Locations(*vent_pts):
                    Cylinder(radius=6.5, height=floor_t + 2.0, mode=Mode.SUBTRACT)
            # 2. Exterior side-wall truss pockets & diagonal ribs
            for px in (36.0, 76.0, 114.0):
                if px < rail_l - 14.0:
                    for s in (-1.0, +1.0):
                        cy_ext = s * (body_w / 2.0 - 0.5)
                        with Locations((px, cy_ext, rail_h / 2.0)):
                            Box(28.0, 1.2, rail_h - 4.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                        with Locations((px, cy_ext, rail_h / 2.0)):
                            Box(26.0, 1.0, 2.0, rotation=(0, 18 * s, 0), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            # 3. Front top-bar bezel with ergonomic top extraction grip + compliant side retention latches
            with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
                Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            with Locations((L - 4.5, 4.0, H / 2.0)):
                Box(7.0, W * 0.52, H - 6.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            with Locations((L - 5.5, -W / 2.0 + 14.5, H / 2.0)):
                Cylinder(radius=5.8, height=11.5, rotation=(0, 90, 0), mode=Mode.SUBTRACT)
            for s in (-1.0, +1.0):
                with Locations((rail_l + bezel_t / 2.0, s * (W / 2.0 - 2.6), H / 2.0)):
                    Box(bezel_t - 2.0, 1.8, H - 4.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        # =========================================================================================
        # ARCHETYPES 1, 2, 3, 5: DESKTOP (D1..D10), RACKMOUNT 3.5" (R1..R10), & 2.5" SFF (R1..R7)
        # =========================================================================================
        else:
            floor_start_x = 9.0 if spec.archetype in (TrayArchetype.DESKTOP_LOCK, TrayArchetype.DESKTOP_SLIDE) else 0.0

            # 1. Side rails: X in [0, rail_l], Y in [-rail_w/2, +rail_w/2], Z in [0, rail_h]
            with Locations((rail_l / 2.0, 0.0, rail_h / 2.0)):
                Box(rail_l, rail_w, rail_h, align=(Align.CENTER, Align.CENTER, Align.CENTER))

            # Carve inner drive bay channel through Z in [0, rail_h], then add floor plate
            with Locations((rail_l / 2.0, 0.0, rail_h / 2.0)):
                Box(rail_l + 2.0, cavity_w, rail_h + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

            floor_len = rail_l - floor_start_x
            with Locations((floor_start_x + floor_len / 2.0, 0.0, floor_t / 2.0)):
                Box(floor_len, rail_w, floor_t, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)

            # -------------------------------------------------------------------------------------
            # DESKTOP (Type D1..D10): Clean Filleted 11-Window Honeycomb Floor + Community QoL Bezel
            # -------------------------------------------------------------------------------------
            if spec.archetype in (TrayArchetype.DESKTOP_LOCK, TrayArchetype.DESKTOP_SLIDE):
                # 2a. Extrude-subtract the 10 inset polygonal honeycomb windows (filleted R=2.2mm) + center oval
                polys = _desktop_honeycomb_polygons(rail_l, cavity_w)
                with BuildSketch(Plane.XY.offset(-0.5)) as sk:
                    for pts in polys:
                        Polygon(*pts, align=None)
                    fillet(sk.vertices(), radius=2.2)
                    with Locations((82.0 * (rail_l / 148.0), 0.0)):
                        RectangleRounded(34.0 * (rail_l / 148.0), 19.0 * (cavity_w / 102.0), radius=4.5)
                extrude(amount=floor_t + 1.0, mode=Mode.SUBTRACT)

                # 2b. Side rail profile: sloped rear lead-in (X in [0, 35mm]) + 2 compliant leaf-spring arch slots
                with Locations((16.0, 0.0, rail_h + 1.8)):
                    Box(36.0, rail_w + 4.0, 4.5, rotation=(0, -7, 0), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                for slot_x in (0.36 * rail_l, 0.73 * rail_l):
                    with Locations((slot_x, 0.0, rail_h - 2.6)):
                        Box(25.0, rail_w + 4.0, 2.2, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

                # Smooth front gusset ramp where rails rise to meet the taller bezel (X in [rail_l - 16, rail_l])
                if H > rail_h + 1.0:
                    gusset_l = 16.0
                    rail_wall_w = (rail_w - cavity_w) / 2.0
                    for s in (-1.0, +1.0):
                        with Locations((rail_l - gusset_l / 2.0, s * (rail_w / 2.0 - rail_wall_w / 2.0), (rail_h + H) / 2.0)):
                            Box(gusset_l, rail_wall_w, H - rail_h, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                        with Locations((rail_l - gusset_l, s * (rail_w / 2.0 - rail_wall_w / 2.0), H)):
                            Box(gusset_l * 1.4, rail_wall_w + 2.0, H - rail_h, rotation=(0, -32, 0), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

                # 2c. Front Bezel & Handle with Community 3D-Printing QoL Upgrades
                if spec.archetype == TrayArchetype.DESKTOP_SLIDE:
                    if spec.name == "Disk Tray (Type D1)":
                        # Type D1 (Jimka "nosupports" QoL upgrade + OEM trapezoidal gussets):
                        # Front pull-handle loop sits FLUSH on the build plate (Z in [0, 11.5mm]) so it prints 100% support-free,
                        # and stays strictly within X in [rail_l, L] (160.00mm total length)!
                        wall_x = 3.5
                        with Locations((rail_l + wall_x / 2.0, 0.0, H / 2.0)):
                            Box(wall_x, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                        handle_h = 11.5
                        x_wall = rail_l + wall_x
                        with BuildSketch(Plane.XY):
                            Polygon(
                                (x_wall, -34.0),
                                (L, -22.0),
                                (L, +22.0),
                                (x_wall, +34.0),
                                align=None,
                            )
                        extrude(amount=handle_h, mode=Mode.ADD)
                        # Vertical finger hole through the pull loop (Z in [0, handle_h] — zero mid-air overhang!)
                        pull_d = bezel_t - wall_x
                        with Locations((x_wall + pull_d / 2.0 - 0.6, 0.0, handle_h / 2.0)):
                            Box(pull_d - 2.8, 34.0, handle_h + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    else:
                        # Type D4 / D7 / D2 / D3: Slezak STEP Open C-Loop Pull Handle with angled side transitions
                        with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
                            Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                        bar_d = 5.2
                        open_d = bezel_t - bar_d
                        with Locations((rail_l + open_d / 2.0 - 0.1, 0.0, floor_t + 3.5 + H / 2.0)):
                            Box(open_d + 0.4, W - 18.0, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                        slot_d = max(4.0, bezel_t - 8.2)
                        with Locations((rail_l + 3.0 + slot_d / 2.0, 0.0, H / 2.0)):
                            Box(slot_d, W - 18.0, H + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                        with Locations((L - bar_d / 2.0 + 0.1, 0.0, H - 3.8)):
                            Box(bar_d + 0.5, W - 18.0, 7.8, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                        # Chamfered transition ramps between the lower pull bar and the side ears (matching Slezak STEP)
                        for s in (-1.0, +1.0):
                            with Locations((L - bar_d / 2.0, s * (W / 2.0 - 9.0), H - 1.5)):
                                Box(bar_d + 1.0, 8.0, 6.0, rotation=(32 * s, 0, 0), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                        with Locations((rail_l + 4.0, -W / 2.0 + 7.0, H - 3.0)):
                            Cylinder(radius=2.0, height=8.0, mode=Mode.SUBTRACT)
                        for s in (-1.0, +1.0):
                            with Locations((rail_l + 5.0, s * (W / 2.0 - 2.4), H / 2.0)):
                                Box(7.0, 1.5, H - 6.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

                else:
                    # DESKTOP_LOCK (Type D5, D6, D8, D9):
                    # Community 1-Piece Print-in-Place QoL Design (sunbrowner D6 + lioncat D5 style):
                    # Instead of a rigid non-moving fake door + fake key hole, build:
                    #   1. A solid front wall at X = rail_l..rail_l + 3.8mm
                    #   2. An open vertical finger-pull grip loop on the right/center (Z=0..H through-slot, zero supports!)
                    #   3. A true compliant C-spring flex latch on the left (-Y) that flexes inward when pinched!
                    wall_t = 3.8
                    with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
                        Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                    # Carve vertical through-slot inside the ergonomic pull handle box (Y in [-28, +W/2 - 8], X in [rail_l + 3.8, L - 3.8])
                    grip_w = W * 0.60
                    grip_cy = W / 2.0 - grip_w / 2.0 - 7.0
                    grip_d = bezel_t - 2 * wall_t
                    with Locations((rail_l + wall_t + grip_d / 2.0, grip_cy, H / 2.0)):
                        Box(grip_d, grip_w, H + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    # Carve the separation channel (Y in [-W/2 + 12, grip_cy - grip_w/2 - 3.5]) between the pull handle
                    # and the left-side compliant spring-latch arm (so the latch arm can flex freely when pinched!)
                    sep_y0 = -W / 2.0 + 11.0
                    sep_y1 = grip_cy - grip_w / 2.0 - 3.5
                    sep_w = max(6.0, sep_y1 - sep_y0)
                    sep_cy = (sep_y0 + sep_y1) / 2.0
                    with Locations((rail_l + wall_t + (bezel_t - wall_t) / 2.0 + 0.2, sep_cy, H / 2.0)):
                        Box(bezel_t - wall_t + 0.5, sep_w, H + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    # Sculpt the left-side compliant C-spring latch flex pocket (-Y side, matching sunbrowner D6 STL!)
                    latch_cy = -W / 2.0 + 5.5
                    with Locations((rail_l + bezel_t * 0.52, latch_cy - 1.5, H / 2.0)):
                        Cylinder(radius=4.8, height=H + 2.0, mode=Mode.SUBTRACT)
                    # Finger recess on the front-right of the pull handle bar for easy one-handed grip
                    with Locations((L - wall_t / 2.0, grip_cy, H - 3.0)):
                        Box(wall_t + 1.0, grip_w - 10.0, 6.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

            # -------------------------------------------------------------------------------------
            # RACKMOUNT 3.5" (Type R1..R8, R10): Clean Uniform Rails + 8x7 Slot Grid + Print-in-Place Latch
            # -------------------------------------------------------------------------------------
            elif spec.archetype == TrayArchetype.RACK_35:
                # 2a. Clean 8x7 perforated server airflow slot grid (with continuous solid rear floor bar X in [0, 10mm]
                # and NO fake plastic EMI comb teeth or mid-rail turret steps — matching vikingu R7 & th0r88 R8 STLs!)
                col_xs = [15.0 + i * 17.5 for i in range(8) if 15.0 + i * 17.5 < rail_l - 10.0]
                row_ys = [-36.0 + j * 12.0 for j in range(7)]
                slot_locs = [(x, y, floor_t / 2.0) for x in col_xs for y in row_ys if _hole_clear(holes, x, y, 6.2)]
                if slot_locs:
                    with Locations(*slot_locs):
                        Box(13.0, 6.8, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

                # 2b. Front Rack Bezel with support-free angled finger-pull pocket & integrated compliant left latch slot
                with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
                    Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                # Wide right/center ergonomic finger-pull recess with internal 45-deg chamfer
                handle_w = W * 0.56
                with Locations((L - 4.5, W / 2.0 - handle_w / 2.0 - 7.0, H / 2.0)):
                    Box(9.2, handle_w, H - 7.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                # Left-side compliant flex-latch release button & flex slot (print-in-place 1-piece rack latch)
                with Locations((rail_l + bezel_t * 0.55, -W / 2.0 + 9.5, H / 2.0)):
                    Box(bezel_t * 0.75, 2.2, H + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                with Locations((L - 3.0, -W / 2.0 + 18.0, H / 2.0)):
                    Box(6.2, 11.0, H - 8.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

            # -------------------------------------------------------------------------------------
            # 2.5" SFF SLIM TRAYS (Slim, SSD, 2.5" D1, 2.5" R1..R4, R6, R7): Tray-Specific Sculpted Geometry
            # -------------------------------------------------------------------------------------
            elif spec.archetype == TrayArchetype.SFF_25:
                # Safe window Y half-span <= 24.5mm so SFF-8201 bottom holes (at Y = +-30.86mm) sit cleanly inside solid floor!
                win_max_y = min(24.5, cavity_w / 2.0 - 6.0)

                if "Slim" in spec.name or "SSD" in spec.name:
                    # Disk Tray (Type Slim) (114x79x14.5mm) & Disk Tray (Type SSD) (134x79x14.0mm):
                    # Open-top U-scoop slide trays with circular side-rail vent holes & front U-scoop finger pocket
                    if "Slim" in spec.name:
                        # 1 large centered filleted rectangular floor window (X in [24, 78], Y in [-23, +23])
                        with BuildSketch(Plane.XY.offset(-0.5)):
                            with Locations((51.0, 0.0)):
                                RectangleRounded(54.0, 2 * win_max_y, radius=4.0)
                        extrude(amount=floor_t + 1.0, mode=Mode.SUBTRACT)
                    else:
                        # Type SSD: 2x2 grid of 4 filleted rectangular floor windows in rear drive zone (X in [14, 90])
                        with BuildSketch(Plane.XY.offset(-0.5)):
                            for wx in (32.0, 70.0):
                                for wy in (-13.0, +13.0):
                                    with Locations((wx, wy)):
                                        RectangleRounded(30.0, 19.5, radius=3.8)
                        extrude(amount=floor_t + 1.0, mode=Mode.SUBTRACT)

                    # Row of vertical circular lightening holes (r=1.25mm inside the 4.38mm rail wall so inner/outer walls stay continuous!)
                    rail_cy = (rail_w / 2.0 + cavity_w / 2.0) / 2.0
                    hole_xs = [12.0 + i * 9.0 for i in range(int((rail_l - 16.0) // 9.0))]
                    for hx in hole_xs:
                        for s in (-1.0, +1.0):
                            with Locations((hx, s * rail_cy, rail_h / 2.0)):
                                Cylinder(radius=1.25, height=rail_h + 2.0, mode=Mode.SUBTRACT)
                    # Tapered rear rail lead-in
                    with Locations((4.0, 0.0, rail_h)):
                        Box(12.0, W + 2.0, 4.0, rotation=(0, -18, 0), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

                    # Front U-scoop slide bezel & recessed finger-pull pocket (matching Disk_Tray_Type_Slim/SSD photos!)
                    with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
                        Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                    # Open the top of the bezel behind the 2.6mm front face plate
                    pocket_l = bezel_t - 2.6
                    with Locations((rail_l + pocket_l / 2.0, 0.0, floor_t + H / 2.0)):
                        Box(pocket_l + 0.2, W - 5.0, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    # Add the curved inner U-wall around the central finger scoop (Y in [-18, +18]) + stiffening ribs on SSD
                    with BuildSketch(Plane.XY.offset(floor_t)):
                        with Locations((L - bezel_t / 2.0, 0.0)):
                            RectangleRounded(bezel_t, 36.0, radius=5.0)
                        with Locations((L - bezel_t / 2.0 + 1.8, 0.0)):
                            RectangleRounded(bezel_t, 30.8, radius=3.5, mode=Mode.SUBTRACT)
                    extrude(amount=H - floor_t, mode=Mode.ADD)
                    if bezel_t > 18.0:
                        # Transverse stiffening ribs in the side pockets of Type SSD (matching Disk_Tray_Type_SSD_24719.png!)
                        for s in (-1.0, +1.0):
                            with Locations((rail_l + bezel_t * 0.48, s * 27.0, H / 2.0)):
                                Box(2.0, 19.0, H - 1.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                    # Carve the U-shaped thumb scoop notch out of the top center of the front face wall
                    with Locations((L - 1.5, 0.0, H - 3.5)):
                        Box(6.0, 26.0, 8.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    with Locations((L - 1.5, 0.0, H - 7.5)):
                        Cylinder(radius=13.0, height=6.0, rotation=(0, 90, 0), mode=Mode.SUBTRACT)

                elif spec.name == '2.5" Disk Tray (D1)':
                    # 2.5" Disk Tray (D1) (124x75x16mm — DS419slim / DS620slim):
                    # 2 parallel longitudinal rounded-rectangular floor windows + Desktop D6-style 1-piece compliant latch bezel
                    win_l = rail_l - 28.0
                    win_w = win_max_y - 4.0
                    win_cy = (win_max_y + 4.0) / 2.0
                    with BuildSketch(Plane.XY.offset(-0.5)):
                        for s in (-1.0, +1.0):
                            with Locations((12.0 + win_l / 2.0, s * win_cy)):
                                RectangleRounded(win_l, win_w, radius=3.2)
                    extrude(amount=floor_t + 1.0, mode=Mode.SUBTRACT)
                    # Side rail clip pockets + sloped rear ramp
                    with Locations((8.0, 0.0, rail_h)):
                        Box(16.0, W + 2.0, 4.0, rotation=(0, -14, 0), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    for sx in (34.0, 78.0):
                        with Locations((sx, 0.0, rail_h - 2.2)):
                            Box(16.0, W + 2.0, 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    # Desktop D6-style 1-piece compliant front push-lock bezel
                    with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
                        Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                    with Locations((rail_l + bezel_t / 2.0, 6.0, H / 2.0)):
                        Box(bezel_t - 5.2, W * 0.56, H + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    with Locations((L - 1.5, 6.0, H - 2.5)):
                        Box(4.0, W * 0.48, 5.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    with Locations((rail_l + bezel_t * 0.55, -W / 2.0 + 7.5, H / 2.0)):
                        Box(bezel_t * 0.75, 2.2, H + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

                elif spec.name == '2.5" Drive Tray (R7)':
                    # 2.5" Drive Tray (R7) (179x79x15mm — PAS7700 U.2/U.3 NVMe):
                    # Open-bottom perimeter frame under the rear NVMe bay + transverse bridge at X=118..126 + front window
                    rear_open_l = 108.0
                    with BuildSketch(Plane.XY.offset(-0.5)):
                        with Locations((6.0 + rear_open_l / 2.0, 0.0)):
                            RectangleRounded(rear_open_l, 2 * win_max_y, radius=3.0)
                        front_win_l = rail_l - 124.0 - 6.0
                        if front_win_l > 10.0:
                            with Locations((124.0 + front_win_l / 2.0, 0.0)):
                                RectangleRounded(front_win_l, 2 * (win_max_y + 2.0), radius=3.0)
                    extrude(amount=floor_t + 1.0, mode=Mode.SUBTRACT)
                    # Rackmount front latch bezel
                    with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
                        Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                    with Locations((L - 4.0, 5.0, H / 2.0)):
                        Box(8.5, W * 0.54, H - 5.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    with Locations((rail_l + bezel_t * 0.55, -W / 2.0 + 7.5, H / 2.0)):
                        Box(bezel_t * 0.75, 2.0, H + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    with Locations((L - 2.5, -W / 2.0 + 13.5, H / 2.0)):
                        Box(5.5, 8.5, H - 6.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

                elif spec.name == '2.5" Disk Tray (R3)':
                    # 2.5" Disk Tray (R3) (124x71x15.5mm — Ultra-slim sheet-metal style carrier):
                    # 2 transverse rounded-rectangular floor windows + dual-grooved front latch bezel
                    with BuildSketch(Plane.XY.offset(-0.5)):
                        for wx, wl in ((34.0, 34.0), (77.0, 34.0)):
                            with Locations((wx, 0.0)):
                                RectangleRounded(wl, 2 * win_max_y, radius=3.0)
                    extrude(amount=floor_t + 1.0, mode=Mode.SUBTRACT)
                    with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
                        Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                    # Dual horizontal finger-grip grooves on the right + release button on the left
                    for gz in (H * 0.33, H * 0.67):
                        with Locations((L - 2.5, 5.5, gz)):
                            Box(5.5, W * 0.56, 3.2, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    with Locations((rail_l + bezel_t * 0.55, -W / 2.0 + 7.0, H / 2.0)):
                        Box(bezel_t * 0.75, 1.8, H + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

                else:
                    # 2.5" Disk Tray (R1, R2, R4) & 2.5" Drive Tray (R6):
                    # 2 parallel longitudinal windows in the REAR drive zone (X in [12, 86]) +
                    # 1 wide transverse window in the FRONT zone (X in [94, rail_l - 6]) right behind the bezel!
                    rear_win_l = min(72.0, (rail_l - 24.0) * 0.56)
                    front_win_l = max(16.0, rail_l - 18.0 - rear_win_l - 6.0)
                    win_w = win_max_y - 4.0
                    win_cy = (win_max_y + 4.0) / 2.0
                    with BuildSketch(Plane.XY.offset(-0.5)):
                        for s in (-1.0, +1.0):
                            with Locations((10.0 + rear_win_l / 2.0, s * win_cy)):
                                RectangleRounded(rear_win_l, win_w, radius=3.2)
                        with Locations((rail_l - 6.0 - front_win_l / 2.0, 0.0)):
                            RectangleRounded(front_win_l, 2 * win_max_y, radius=3.2)
                    extrude(amount=floor_t + 1.0, mode=Mode.SUBTRACT)

                    # Rackmount 2.5" front bezel with left release button pocket & wide right pull handle
                    with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
                        Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
                    with Locations((L - 3.8, 5.0, H / 2.0)):
                        Box(8.0, W * 0.54, max(4.5, H - 6.0), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    with Locations((rail_l + bezel_t * 0.55, -W / 2.0 + 7.5, H / 2.0)):
                        Box(bezel_t * 0.75, 2.0, H + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                    with Locations((L - 2.5, -W / 2.0 + 13.5, H / 2.0)):
                        Box(5.5, 8.5, max(4.5, H - 7.0), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        # 7. Drill all SFF-8301 (3.5") and SFF-8201 (2.5") mounting holes + outer M3 screw-head counterbores (QoL!)
        has_bottom_floor = not (
            spec.archetype == TrayArchetype.HOLDER_25
            or (spec.archetype == TrayArchetype.TOPLOAD_60BAY and spec.supports_35)
        )
        for hc in holes:
            if hc.axis == "Z" and has_bottom_floor:
                with Locations((hc.x, hc.y, floor_t / 2.0)):
                    Cylinder(radius=hc.diameter / 2.0, height=floor_t + 2.0, mode=Mode.SUBTRACT)
                # Underside M3 screw-head counterbore (0.8mm deep, Ø 6.2mm) so bottom screws sit flush!
                if floor_t >= 2.0:
                    with Locations((hc.x, hc.y, 0.4)):
                        Cylinder(radius=3.1, height=0.8, mode=Mode.SUBTRACT)
            elif hc.axis == "Y":
                wall_span = (rail_w - cavity_w) / 2.0 + 4.0
                with Locations((hc.x, hc.y, hc.z)):
                    Cylinder(radius=hc.diameter / 2.0, height=wall_span * 2.0, rotation=(90, 0, 0), mode=Mode.SUBTRACT)
                # Outer rail M3 screw-head counterbore (0.9mm deep, Ø 6.2mm) so side screws sit flush inside the NAS bay!
                if rail_w - cavity_w >= 2.2 and spec.archetype != TrayArchetype.HOLDER_25:
                    s_sign = -1.0 if hc.y < 0 else 1.0
                    with Locations((hc.x, s_sign * (rail_w / 2.0 - 0.45), hc.z)):
                        Cylinder(radius=3.1, height=0.9, rotation=(90, 0, 0), mode=Mode.SUBTRACT)

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
