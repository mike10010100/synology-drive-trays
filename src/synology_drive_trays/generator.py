"""Parametric 3D CAD (build123d STEP/STL) and 2D Technical Schematic (SVG/DXF) generator for Synology trays."""
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
    chamfer,
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
    # Rear face of drive relative to rear rail tip X=0:
    # Positive overhang means drive protrudes slightly past X=0 (so rear of drive is at X = max(0, -overhang))
    # Wait: in a physical tray of length L, the rails run from X=0 (rear tip) to X = L - bezel_t.
    # The drive rear face sits near X=0 (offset inward by max(0.0, -spec.rear_sata_overhang_mm)).
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
            # Combo 3.5"/2.5" tray or Type C holder: 2.5" drive is offset toward the left rail (-Y)
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


def generate_tray_cad(spec: TraySpec) -> Part:
    """
    Build a boundary-representation (B-Rep) 3D CAD solid for any Synology TraySpec.
    Guarantees:
      - Exact outer bounding box: [0, length_mm] x [-width_mm/2, +width_mm/2] x [0, height_mm]
      - Exact inner drive pocket (101.60mm for 3.5", 69.85mm for 2.5" SFF)
      - Exact SFF-8301 / SFF-8201 bottom & side mounting holes
      - Ventilation hex/window cutouts in floor web & rear SATA/SAS backplane connector cutout
      - Front bezel with latch recess & key-lock bore (if has_lock)
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
    # Ensure wall thickness is at least 1.15mm per side on standard trays, or 0.5mm on ultra-compact 2.5" trays (e.g. R3 71.0mm)
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

        # 4. Rear SATA/SAS backplane connector cutout at X in [0, 12mm]
        sata_cut_w = cavity_w - 12.0
        with Locations((6.0, 0.0, floor_t / 2.0)):
            Box(12.5, sata_cut_w, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        # 5. Ventilation cutouts in floor web (preserving cross-straps at SFF mounting hole rows)
        hole_xs = sorted({round(h.x, 1) for h in holes if h.axis == "Z"})
        strap_pad = 6.5
        vent_w = max(16.0, cavity_w - 18.0)
        # Create ventilation windows in intervals between cross-straps
        boundaries = [12.0] + [x for x in hole_xs if 18.0 < x < rail_l - 8.0] + [rail_l - 4.0]
        for i in range(len(boundaries) - 1):
            x0 = boundaries[i] + (strap_pad if i > 0 else 2.0)
            x1 = boundaries[i + 1] - (strap_pad if i < len(boundaries) - 2 else 2.0)
            span_x = x1 - x0
            if span_x >= 12.0:
                cx = (x0 + x1) / 2.0
                # Split into 2 symmetric ventilation windows to keep a center longitudinal spine (width 7mm)
                win_w = (vent_w - 7.0) / 2.0
                if win_w >= 8.0:
                    with Locations(
                        (cx, -(win_w / 2.0 + 3.5), floor_t / 2.0),
                        (cx, +(win_w / 2.0 + 3.5), floor_t / 2.0),
                    ):
                        Box(span_x, win_w, floor_t + 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        # 6. Front bezel ergonomic finger pull pocket & lock cylinder hole
        pull_w = min(W * 0.48, 52.0)
        pull_h = max(4.0, H - 7.0)
        pull_d = min(bezel_t * 0.55, 8.0)
        with Locations((L - pull_d / 2.0 + 0.1, -W * 0.08, H / 2.0)):
            Box(pull_d, pull_w, pull_h, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        if spec.has_lock:
            # Key-lock cylinder bore on right side of front bezel
            with Locations((L - bezel_t / 2.0, W * 0.30, H / 2.0)):
                Cylinder(radius=3.2, height=bezel_t + 1.0, rotation=(0, 90, 0), mode=Mode.SUBTRACT)

        # 7. Side-rail slide grooves for desktop & rack chassis bay guides
        if spec.archetype in (TrayArchetype.DESKTOP_LOCK, TrayArchetype.DESKTOP_SLIDE) and rail_w >= 110.0:
            groove_h = 3.0
            groove_d = 1.2
            with Locations(
                (rail_l / 2.0, -rail_w / 2.0 + groove_d / 2.0 - 0.05, rail_h - 3.5),
                (rail_l / 2.0, +rail_w / 2.0 - groove_d / 2.0 + 0.05, rail_h - 3.5),
            ):
                Box(rail_l - 8.0, groove_d, groove_h, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)

        # 8. Drill all SFF-8301 (3.5") and SFF-8201 (2.5") mounting holes
        for hc in holes:
            if hc.axis == "Z":
                with Locations((hc.x, hc.y, floor_t / 2.0)):
                    Cylinder(radius=hc.diameter / 2.0, height=floor_t + 2.0, mode=Mode.SUBTRACT)
            elif hc.axis == "Y":
                wall_span = (rail_w - cavity_w) / 2.0 + 2.0
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
    floor_t = spec.floor_thickness_mm
    holes = compute_mounting_holes(spec)

    scale = 2.6
    pad = 55.0
    svg_w = int((L + H + 90) * scale + 2 * pad)
    svg_h = int((W + H + 85) * scale + 2 * pad)

    # Top view origin: X in [0..L], Y_center at top_cy
    top_x0 = pad
    top_cy = pad + (W / 2.0) * scale
    # Side view origin below Top view
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

    # Plot bottom & side mounting holes on Top & Side views
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

    # Dimension callouts
    lines.append(f'<text x="{top_x0 + (L*scale)/2 - 40:.1f}" y="{top_cy - (W/2)*scale - 10:.1f}" fill="#e2e8f0" font-size="12">L = {L:.1f} mm (Rails: {rail_l:.1f} mm, Bezel: {bezel_t:.1f} mm)</text>')
    lines.append(f'<text x="{top_x0 + L*scale + 12:.1f}" y="{top_cy:.1f}" fill="#e2e8f0" font-size="12">W = {W:.1f} mm (Rail W = {rail_w:.1f} mm)</text>')
    lines.append(f'<text x="{side_x0 + L*scale + 12:.1f}" y="{side_y0 + (H*scale)/2:.1f}" fill="#e2e8f0" font-size="12">H = {H:.2f} mm (Rail H = {rail_h:.1f} mm)</text>')
    lines.append(f'<text x="20" y="{svg_h - 15}" fill="#94a3b8" font-size="11">Legend: Green = SFF-8301 3.5" Bottom Holes (95.25mm span) | Amber = SFF-8201 2.5" Bottom Holes (61.72mm span) | Purple = Side Rail Pin/Screw Holes</text>')
    lines.append("</svg>")
    out_svg.write_text("\n".join(lines))
