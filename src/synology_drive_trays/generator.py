"""Parametric 3D CAD (build123d STEP/STL) and 2D Technical Schematic (SVG) generator for Synology trays."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    Cylinder,
    Locations,
    Mode,
    Part,
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
            # Combo 3.5"/2.5" tray or Type A/B/C holder: 2.5" drive is offset toward the left rail (-Y)
            # so its SFF-8223 SATA connector mates with the 3.5" backplane connector.
            left_edge_35 = -SFF_35.drive_width / 2.0
            left_edge_25 = left_edge_35 + SFF_25.sata_align_left_offset_from_35_left
            y_left_25 = left_edge_25 + SFF_25.bottom_hole_y_inset
            y_right_25 = y_left_25 + SFF_25.bottom_hole_y_span
        else:
            # Dedicated 2.5" SFF tray: centered on Y=0
            y_left_25 = -SFF_25.bottom_hole_y_span / 2.0
            y_right_25 = +SFF_25.bottom_hole_y_span / 2.0

        for idx, dx in enumerate(SFF_25.bottom_hole_x_from_rear, 1):
            hx = drive_rear_x + dx
            if hx < spec.length_mm - spec.bezel_thickness_mm - 2.0:
                holes.append(HoleCoordinate(f"2.5_btm_L{idx}", hx, y_left_25, floor_t / 2.0, SFF_25.hole_clearance_dia, "Z"))
                holes.append(HoleCoordinate(f"2.5_btm_R{idx}", hx, y_right_25, floor_t / 2.0, SFF_25.hole_clearance_dia, "Z"))

        if not spec.supports_35 and spec.archetype == TrayArchetype.SFF_25:
            hz_25 = floor_t + SFF_25.side_hole_z_from_bottom
            if hz_25 < spec.rail_height_mm - 1.5:
                for idx, dx in enumerate(SFF_25.side_hole_x_from_rear, 1):
                    hx = drive_rear_x + dx
                    if hx < spec.length_mm - spec.bezel_thickness_mm - 3.0:
                        holes.append(HoleCoordinate(f"2.5_side_L{idx}", hx, -rail_w / 2.0, hz_25, SFF_25.hole_clearance_dia, "Y"))
                        holes.append(HoleCoordinate(f"2.5_side_R{idx}", hx, +rail_w / 2.0, hz_25, SFF_25.hole_clearance_dia, "Y"))

    return holes


def _hole_clear(holes: list[HoleCoordinate], x: float, y: float, min_dist: float = 5.5) -> bool:
    """Return True if (x, y) is at least min_dist away from all bottom Z-axis mounting holes."""
    for h in holes:
        if h.axis == "Z" and ((h.x - x) ** 2 + (h.y - y) ** 2) ** 0.5 < min_dist:
            return False
    return True


def generate_tray_cad(spec: TraySpec) -> Part:
    """
    Build a high-detail boundary-representation (B-Rep) 3D CAD solid for any Synology TraySpec.
    Includes:
      - Exact outer bounding box: [0, length_mm] x [-width_mm/2, +width_mm/2] x [0, height_mm]
      - Exact inner drive pocket (101.60mm for 3.5", 69.85mm for 2.5" SFF)
      - Archetype-specific floor geometry:
          * Desktop (D1..D10): Synology 7-window diagonal honeycomb X-truss web + tapered rear rail tips
          * Rackmount 3.5" (R1..R8, R10): Stamped 6x5 server airflow slot grid + top EMI spring finger comb
          * Top-loader 60-bay (R9, 2.5" R5): Diagonal exterior side-wall truss ribs + top plunger bore
          * 2.5" SFF (R1..R7, D1): 3-window T-spine floor + EMI finger comb + front latch pocket
          * Disk Holder (Type A/B/C): Ribbed left rail + 2.5" support shelf + front transverse L-arm
      - Generation-specific front bezel louvers, status LED light-pipe cutouts, key-lock bores, and
        integrated compliant snap-fit latch hooks for 1-piece 3D printing.
      - Exact SFF-8301 / SFF-8201 bottom & side mounting holes.
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
    if spec.archetype == TrayArchetype.HOLDER_25:
        left_edge_25 = -SFF_35.drive_width / 2.0 + SFF_25.sata_align_left_offset_from_35_left
        cavity_cy = left_edge_25 + SFF_25.drive_width / 2.0
    else:
        cavity_cy = 0.0

    holes = compute_mounting_holes(spec)

    with BuildPart() as builder:
        # 1. Main rail & floor body: X in [0, rail_l], Y in [-rail_w/2, +rail_w/2], Z in [0, rail_h]
        with Locations((rail_l / 2.0, 0.0, rail_h / 2.0)):
            Box(rail_l, rail_w, rail_h, align=(Align.CENTER, Align.CENTER, Align.CENTER))

        # 2. Carve out inner drive bay channel above floor_t: Z in [floor_t, rail_h + 1]
        cavity_h = rail_h - floor_t + 1.0
        with Locations((rail_l / 2.0, cavity_cy, floor_t + cavity_h / 2.0)):
            Box(rail_l + 1.0, cavity_w, cavity_h, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        # 3. Front bezel / handle assembly: X in [rail_l, L], Y in [-W/2, +W/2], Z in [0, H]
        with Locations((rail_l + bezel_t / 2.0, 0.0, H / 2.0)):
            Box(bezel_t, W, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)

        # 4. Rear SATA/SAS backplane connector cutout at X in [0, 13mm]
        sata_cut_w = cavity_w - 14.0
        with Locations((6.5, cavity_cy, floor_t / 2.0)):
            Box(13.5, sata_cut_w, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        # 5. Archetype-specific floor webbing, side rails, and rear lead-in ramps
        if spec.archetype in (TrayArchetype.DESKTOP_LOCK, TrayArchetype.DESKTOP_SLIDE):
            # 5a. Tapered rear rail lead-in ramp (top of rails slopes down at X in [0, 10mm])
            with Locations((4.0, 0.0, rail_h + 1.0)):
                Box(11.0, rail_w + 2.0, 6.0, rotation=(0, -22, 0), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

            # 5b. Iconic Synology 7-window Diagonal Honeycomb X-Truss Floor Web
            # Start by carving a large open floor basin (preserving 8mm perimeter rim and hole bosses),
            # then ADD back the central oval ring and 4 diagonal X-truss struts!
            basin_l = rail_l - 26.0
            basin_w = cavity_w - 14.0
            basin_cx = 13.0 + basin_l / 2.0
            with Locations((basin_cx, 0.0, floor_t / 2.0)):
                Box(basin_l, basin_w, floor_t + 0.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

            # Add back the central rounded ring (outer 48x30mm, inner window 34x18mm)
            with Locations((basin_cx, 0.0, floor_t / 2.0)):
                Box(48.0, 30.0, floor_t, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            # Add back the 4 diagonal X-truss struts (+/- 36 deg) + transverse cross-ties at mounting holes
            for angle in (36.0, -36.0):
                with Locations((basin_cx, 0.0, floor_t / 2.0)):
                    Box(basin_l * 1.15, 7.5, floor_t, rotation=(0, 0, angle), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            # Add longitudinal side-web bridges for 2.5" and 3.5" bottom holes
            for hc in holes:
                if hc.axis == "Z":
                    with Locations((hc.x, hc.y, floor_t / 2.0)):
                        Cylinder(radius=5.2, height=floor_t, mode=Mode.ADD)
                    # Connect hole boss to nearest rail or center ring with a 6.5mm strut
                    with Locations((hc.x, hc.y / 2.0, floor_t / 2.0)):
                        Box(6.5, abs(hc.y) + 4.0, floor_t, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            # Carve the center stadium window inside the central ring (clear of center holes)
            with Locations((basin_cx, 0.0, floor_t / 2.0)):
                Box(32.0, 16.0, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

            # 5c. Outer side-rail recesses for tool-less drive fastening strips (as seen in D6/D7/D8/D9)
            pocket_d = 1.1
            pocket_h = rail_h - 5.5
            for px, pl in ((36.0, 40.0), (96.0, 42.0)):
                if px + pl / 2.0 < rail_l - 8.0:
                    with Locations(
                        (px, -rail_w / 2.0 + pocket_d / 2.0 - 0.05, rail_h / 2.0 + 0.5),
                        (px, +rail_w / 2.0 - pocket_d / 2.0 + 0.05, rail_h / 2.0 + 0.5),
                    ):
                        Box(pl, pocket_d, pocket_h, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        elif spec.archetype == TrayArchetype.RACK_35:
            # 5a. Stamped 6x5 Server Airflow Slot Grid across the floor (matching official Type R7 render)
            xs = [24.0 + i * 21.5 for i in range(6) if 24.0 + i * 21.5 < rail_l - 14.0]
            ys = [-34.0, -17.0, 0.0, 17.0, 34.0]
            slot_locs = [(x, y, floor_t / 2.0) for x in xs for y in ys if _hole_clear(holes, x, y, 6.2)]
            if slot_locs:
                with Locations(*slot_locs):
                    Box(13.5, 4.8, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

            # 5b. Raised EMI spring finger comb right behind the front bezel (matching Type R7/R8)
            emi_x = rail_l - 3.5
            with Locations((emi_x, 0.0, rail_h + 1.2)):
                Box(6.5, rail_w - 6.0, 2.4, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            # Cut 10 narrow slots across the EMI comb to form 11 spring fingers
            emi_slots = [(emi_x, -36.0 + i * 8.0, rail_h + 1.3) for i in range(10)]
            with Locations(*emi_slots):
                Box(4.5, 3.2, 3.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

            # 5c. Side-rail slide grooves for rack bay guides
            with Locations(
                (rail_l / 2.0, -rail_w / 2.0 + 0.55, rail_h / 2.0),
                (rail_l / 2.0, +rail_w / 2.0 - 0.55, rail_h / 2.0),
            ):
                Box(rail_l - 10.0, 1.2, 3.2, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        elif spec.archetype == TrayArchetype.TOPLOAD_60BAY:
            # 60-bay top-loading carrier (Drive Tray Type R9 / 2.5" R5):
            # Large open center floor window with mounting tabs + exterior diagonal truss pockets on side walls
            win_l = rail_l - 22.0
            win_w = cavity_w - 16.0
            with Locations((11.0 + win_l / 2.0, 0.0, floor_t / 2.0)):
                Box(win_l, win_w, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            for hc in holes:
                if hc.axis == "Z":
                    with Locations((hc.x, hc.y, floor_t / 2.0)):
                        Cylinder(radius=5.0, height=floor_t, mode=Mode.ADD)
            # Exterior side-wall truss pockets (matching official Drive Tray Type R9 render)
            for px in (38.0, 78.0, 115.0):
                if px < rail_l - 15.0:
                    with Locations(
                        (px, -rail_w / 2.0 + 0.6, rail_h / 2.0),
                        (px, +rail_w / 2.0 - 0.6, rail_h / 2.0),
                    ):
                        Box(26.0, 1.3, rail_h - 4.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        elif spec.archetype == TrayArchetype.SFF_25:
            # 2.5" SFF Slim Tray (matching official 2.5" Drive Tray R6 render):
            # 3 rectangular windows separated by a T-shaped web (1 wide rear window + 2 front windows)
            w_in = max(18.0, cavity_w - 14.0)
            rear_l = max(18.0, (rail_l - 38.0) * 0.46)
            front_l = max(18.0, (rail_l - 38.0) * 0.42)
            with Locations((16.0 + rear_l / 2.0, 0.0, floor_t / 2.0)):
                Box(rear_l, w_in, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            front_cx = rail_l - 10.0 - front_l / 2.0
            half_w = (w_in - 6.0) / 2.0
            if half_w >= 6.0:
                with Locations(
                    (front_cx, -(half_w / 2.0 + 3.0), floor_t / 2.0),
                    (front_cx, +(half_w / 2.0 + 3.0), floor_t / 2.0),
                ):
                    Box(front_l, half_w, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            # Preserve hole bosses
            for hc in holes:
                if hc.axis == "Z":
                    with Locations((hc.x, hc.y, floor_t / 2.0)):
                        Cylinder(radius=4.5, height=floor_t, mode=Mode.ADD)
            # Top EMI spring finger comb right behind bezel (kept strictly <= H)
            emi_x = rail_l - 3.0
            emi_h = 1.0
            emi_cz = min(rail_h + 0.3, H - emi_h / 2.0 - 0.1)
            with Locations((emi_x, 0.0, emi_cz)):
                Box(5.0, rail_w - 4.0, emi_h, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            emi_slots = [(emi_x, -22.0 + i * 7.3, emi_cz + 0.1) for i in range(7)]
            with Locations(*emi_slots):
                Box(3.5, 2.5, emi_h + 0.6, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        elif spec.archetype == TrayArchetype.HOLDER_25:
            # Disk Holder (Type A/B/C): Asymmetric L-bracket aesthetic with left structural ribbed adapter block
            # bridging the 11.4mm offset between the 3.5" bay wall (-51.5mm) and the 2.5" drive (-40.1mm)
            left_block_w = 11.4
            left_block_cy = -rail_w / 2.0 + left_block_w / 2.0
            with Locations((rail_l / 2.0, left_block_cy, rail_h / 2.0)):
                Box(rail_l, left_block_w, rail_h, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            # Carve weight-reduction pockets into the top of the left block (leaving X-ribs strictly inside block)
            for px in (22.0, 52.0, 82.0):
                with Locations((px, left_block_cy, rail_h / 2.0 + 2.0)):
                    Box(20.0, left_block_w - 2.8, rail_h, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                for ang in (22.0, -22.0):
                    with Locations((px, left_block_cy, rail_h / 2.0)):
                        Box(18.0, 1.5, rail_h - 1.0, rotation=(0, 0, ang), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)
            # Carve open floor window under the 2.5" drive while keeping front/rear cross-straps for the 4 bottom holes
            with Locations((rail_l / 2.0 + 4.0, cavity_cy + 4.0, floor_t / 2.0)):
                Box(48.0, 46.0, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        # 6. Generation-Specific Front Bezel Louvers, Handles, LED Ports & Compliant Snap-Fit Latch Hooks
        if spec.archetype == TrayArchetype.DESKTOP_LOCK:
            # Push-to-lock pivotal lever bezel (Type D2, D3, D5, D6, D8, D9):
            # Step-down finger recess along the top-right rear of the bezel so fingers can pull the lever open
            step_w = W * 0.62
            step_d = min(bezel_t * 0.36, 7.5)
            with Locations((rail_l + step_d / 2.0, W / 2.0 - step_w / 2.0 - 4.0, H - 3.2)):
                Box(step_d + 0.2, step_w, 7.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            # Top-left status LED light-pipe hole (visible in Type D5 & D6 renders)
            with Locations((L - bezel_t * 0.55, -W / 2.0 + 16.0, H - 1.5)):
                Cylinder(radius=1.6, height=4.0, mode=Mode.SUBTRACT)
            # Left-front triangular status indicator mark recess
            with Locations((L, -W / 2.0 + 5.0, H / 2.0)):
                Box(1.6, 3.0, 4.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            # Key lock cylinder bore (D5/D6/D8/D9) or rectangular push-latch window (D2/D3)
            if spec.has_lock:
                with Locations((L - 2.0, W * 0.32, H / 2.0)):
                    Cylinder(radius=3.5, height=bezel_t, rotation=(0, 90, 0), mode=Mode.SUBTRACT)
                with Locations((L - 2.0, W * 0.32, H / 2.0)):
                    Box(bezel_t + 2.0, 2.2, 4.8, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            else:
                with Locations((L - 2.0, W * 0.28, H / 2.0)):
                    Box(bezel_t + 2.0, 8.0, 5.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            # Bottom-bezel hidden ventilation louver slots
            louver_locs = [(L - bezel_t / 2.0, -W * 0.25 + i * 12.0, 1.5) for i in range(6)]
            with Locations(*louver_locs):
                Box(bezel_t - 4.0, 7.5, 3.2, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            # Integrated compliant snap-fit latch slot & hook on the right bezel end (+Y)
            with Locations((rail_l + bezel_t * 0.45, W / 2.0 - 3.2, H / 2.0)):
                Box(bezel_t * 0.75, 2.2, H - 5.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            with Locations((rail_l + 2.5, W / 2.0 - 0.8, H / 2.0)):
                Box(3.0, 1.6, H - 8.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.ADD)

        elif spec.archetype == TrayArchetype.DESKTOP_SLIDE:
            if spec.name == "Disk Tray (Type D1)":
                # Type D1: Open top U-bezel with center trapezoidal pull-tab pocket
                with Locations((L - bezel_t * 0.45, 0.0, H / 2.0 + 2.0)):
                    Box(bezel_t * 0.65, 38.0, H - 5.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            else:
                # Type D4 / D7: Deep C-channel ergonomic pull bar across the full front face (matching Type D7 render)
                c_width = W - 15.0
                c_height = H - 7.5
                c_depth = bezel_t - 3.5
                with Locations((L - c_depth / 2.0 + 0.1, 0.0, H / 2.0)):
                    Box(c_depth, c_width, c_height, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
                # Top-left vertical release pin bore & compliant flex slot (matching Type D7 top-left hole)
                with Locations((rail_l + 4.5, -W / 2.0 + 7.5, H - 3.0)):
                    Cylinder(radius=2.1, height=8.0, mode=Mode.SUBTRACT)
                # Compliant side snap-fit slots on both bezel ears
                for side_sign in (-1.0, +1.0):
                    with Locations((rail_l + 5.0, side_sign * (W / 2.0 - 2.6), H / 2.0)):
                        Box(7.5, 1.6, H - 6.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        elif spec.archetype == TrayArchetype.RACK_35:
            # Rackmount 3.5" bezel (Type R1..R8, R10 — matching Type R7 render):
            # 1. Left-side square push release button pocket
            with Locations((L - 3.5, -W / 2.0 + 13.0, H / 2.0)):
                Box(7.2, 13.0, H - 9.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            # 2. Key-lock hole next to release button
            if spec.has_lock:
                with Locations((L - 3.5, -W / 2.0 + 26.5, H / 2.0)):
                    Cylinder(radius=2.8, height=bezel_t + 2.0, rotation=(0, 90, 0), mode=Mode.SUBTRACT)
            # 3. Wide right-side angled finger-pull handle recess
            handle_w = W * 0.48
            with Locations((L - 4.5, W / 2.0 - handle_w / 2.0 - 8.0, H / 2.0)):
                Box(9.2, handle_w, H - 8.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            # 4. Bottom-left LED status light-pipe notch & compliant side latch slot
            with Locations((L - 1.5, -W / 2.0 + 10.0, 2.0)):
                Box(3.5, 3.5, 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            with Locations((rail_l + 4.5, -W / 2.0 + 2.2, H / 2.0)):
                Box(7.0, 1.8, H - 6.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        elif spec.archetype == TrayArchetype.TOPLOAD_60BAY:
            # Top-loading 60-bay carrier (Drive Tray Type R9 / 2.5" R5):
            # Left cylindrical thumb plunger pocket + compliant side retention slots
            with Locations((L - 5.0, -W / 2.0 + 14.0, H / 2.0)):
                Cylinder(radius=5.8, height=10.5, rotation=(0, 90, 0), mode=Mode.SUBTRACT)
            for side_sign in (-1.0, +1.0):
                with Locations((rail_l + bezel_t / 2.0, side_sign * (W / 2.0 - 2.5), H / 2.0)):
                    Box(bezel_t - 2.0, 1.8, H - 5.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        elif spec.archetype == TrayArchetype.SFF_25:
            # 2.5" SFF Slim Tray bezel (matching official 2.5" Drive Tray R6 render):
            # Rectangular recessed release lever window in center + left status LED vertical slit + compliant side latch
            with Locations((L - 3.5, 2.0, H / 2.0 - 1.0)):
                Box(7.2, W * 0.48, max(4.5, H - 7.5), align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            with Locations((L - 1.0, -W / 2.0 + 9.5, H / 2.0)):
                Box(2.5, 1.6, 4.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)
            with Locations((rail_l + 4.0, W / 2.0 - 2.0, H / 2.0)):
                Box(6.5, 1.5, H - 4.5, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        elif spec.archetype == TrayArchetype.HOLDER_25:
            # Disk Holder (Type A/B/C): Ribbed front L-arm pockets matching official Type C render
            for py in (-22.0, 0.0, +22.0):
                with Locations((L - bezel_t / 2.0 - 0.5, py, H / 2.0 + 1.5)):
                    Box(bezel_t - 2.5, 16.0, H, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        # 7. Drill all SFF-8301 (3.5") and SFF-8201 (2.5") mounting holes
        for hc in holes:
            if hc.axis == "Z":
                with Locations((hc.x, hc.y, floor_t / 2.0)):
                    Cylinder(radius=hc.diameter / 2.0, height=floor_t + 2.0, mode=Mode.SUBTRACT)
            elif hc.axis == "Y":
                wall_span = (rail_w - cavity_w) / 2.0 + 3.0
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
        # Top View — Rail Body
        f'<rect x="{top_x0:.1f}" y="{top_cy - (rail_w/2)*scale:.1f}" width="{rail_l*scale:.1f}" height="{rail_w*scale:.1f}" fill="#1e293b" stroke="#38bdf8" stroke-width="1.8"/>',
        # Top View — Front Bezel
        f'<rect x="{top_x0 + rail_l*scale:.1f}" y="{top_cy - (W/2)*scale:.1f}" width="{bezel_t*scale:.1f}" height="{W*scale:.1f}" fill="#334155" stroke="#38bdf8" stroke-width="2.0"/>',
        # Centerline
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

    # Side View — Rail + Bezel
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
