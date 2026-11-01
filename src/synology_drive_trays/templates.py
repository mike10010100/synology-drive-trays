"""Template-first mesh synthesis using human-sculpted community CAD models with SFF-preserving piecewise-linear warping."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import numpy as np
import trimesh

from .specs import TraySpec

ROOT = Path(__file__).resolve().parent.parent.parent
GT_DIR = ROOT / "data" / "ground_truth"

# Mapping of 21 Synology 3.5" Desktop, 3.5" Rackmount, and 2.5" Disk Holder trays to their master community CAD templates.
# The remaining 11 trays (60-bay top-loaders R9 / 2.5" R5 and 2.5" SFF slim trays) have no community CAD online and use procedural CAD.
COMMUNITY_TEMPLATE_MAP: dict[str, tuple[str, str]] = {
    # 1. Desktop Slide-Latch Family (D1, D4, D7)
    "Disk Tray (Type D1)": ("Type_D1_jimka_nosupports.stl", "community_template_exact"),
    "Disk Tray (Type D7)": ("Type_D7_slezak_from_step.stl", "community_template_exact"),
    "Disk Tray (Type D4)": ("Type_D7_slezak_from_step.stl", "community_template_warped"),
    # 2. Desktop Push/Pull-Lock Modern Family (D6, D8, D9)
    "Disk Tray (Type D6)": ("Type_D6_sunbrowner.stl", "community_template_exact"),
    "Disk Tray (Type D8)": ("Type_D6_sunbrowner.stl", "community_template_exact"),
    "Disk Tray (Type D9)": ("Type_D6_sunbrowner.stl", "community_template_exact"),
    # 3. Desktop Narrow 112-113mm Family (D2, D3, D5)
    "Disk Tray (Type D5)": ("Type_D5_lioncat.stl", "community_template_exact"),
    "Disk Tray (Type D2)": ("Type_D5_lioncat.stl", "community_template_warped"),
    "Disk Tray (Type D3)": ("Type_D5_lioncat.stl", "community_template_warped"),
    # 4. Rackmount 3.5" Keyed Family (R7, R10)
    "Disk Tray (Type R7)": ("Type_R7_vikingu.stl", "community_template_exact"),
    "Drive Tray (Type R10)": ("Type_R7_vikingu.stl", "community_template_exact"),
    # 5. Rackmount 3.5" Flush Lever Family (R1, R2, R3, R4, R5, R6, R8)
    "Disk Tray (Type R8)": ("Type_R8_th0r88.stl", "community_template_exact"),
    "Disk Tray (Type R6)": ("Type_R8_th0r88.stl", "community_template_exact"),
    "Disk Tray (Type R1)": ("Type_R8_th0r88.stl", "community_template_warped"),
    "Disk Tray (Type R2)": ("Type_R8_th0r88.stl", "community_template_warped"),
    "Disk Tray (Type R3)": ("Type_R8_th0r88.stl", "community_template_warped"),
    "Disk Tray (Type R4)": ("Type_R8_th0r88.stl", "community_template_warped"),
    "Disk Tray (Type R5)": ("Type_R8_th0r88.stl", "community_template_warped"),
    # 6. Internal 2.5" Disk Holder L-Bracket Family (Holder Type A, B, C)
    "Disk Holder (Type C)": ("Holder_Type_C_prspr.stl", "community_template_exact"),
    "Disk Holder (Type A)": ("Holder_Type_C_prspr.stl", "community_template_warped"),
    "Disk Holder (Type B)": ("Holder_Type_C_prspr.stl", "community_template_warped"),
}


# Front-most X coordinate (mm from rear rail tip X=0) where the functional tray,
# SFF mounting holes, and front bezel chassis-stop face / latch hook end.
# All geometry in X in [0.0, x_front_pull] is locked at exact 1:1 (x' == x, 0.000 mm shift)
# so SATA/SAS backplane mating depth is 100% invariant. Any overall length delta (L1 - L0)
# is absorbed solely in the external front handle / door-cover protrusion [x_front_pull, L0].
TEMPLATE_FRONT_PULL_X: dict[str, float] = {
    "Type_D1_jimka_nosupports.stl": 150.0,    # Bezel stop at X=146.5..150.0; [150.0, 163.15] is external curved finger pull
    "Type_D7_slezak_from_step.stl": 161.0,    # Bezel stop & latch hooks at X=132..152; [161.0, 166.12] is outer front bar
    "Type_D6_sunbrowner.stl": 162.5,          # Bezel stop at X=141.5, latch hook to 152; [162.5, 166.5] is front door-cover face
    "Type_D5_lioncat.stl": 165.0,             # Bezel stop at X=158..165; [165.0, 177.84] is external finger-pull loop
    "Type_R7_vikingu.stl": 168.6,             # Rack bezel stop step at X=145.0; [168.6, 169.0] is outermost front bezel face
    "Type_R8_th0r88.stl": 165.0,              # Rack bezel stop step at X=145.0; [165.0, 169.0] is outer front bezel face
    "Holder_Type_C_prspr.stl": 110.0,         # Side M3 holes at X=29.9..106.51; [110.0, 120.5] is front pocket wall tip
}


def has_community_template(tray_name: str) -> bool:
    """Return True if the tray is backed by a human-sculpted community CAD template."""
    return tray_name in COMMUNITY_TEMPLATE_MAP


@lru_cache(maxsize=16)
def load_canonical_template(fname: str) -> trimesh.Trimesh:
    """
    Load a community ground-truth STL and canonicalize it into our standard coordinate frame:
      - X in [0, L0] (rear connector tip at X=0, front bezel/handle at X=L0)
      - Y centered on the sliding rails [-rail_W/2, +rail_W/2] (or [-W0/2, +W0/2] for L-bracket holders)
      - Z in [0, H0] (bottom floor plate at Z=0, top of rails/bezel at Z=H0)
    """
    m = trimesh.load(str(GT_DIR / fname), force="mesh").copy()
    order = np.argsort(m.extents)[::-1]
    v = np.asarray(m.vertices[:, order], dtype=float).copy()
    f = np.asarray(m.faces, dtype=int).copy()
    if np.linalg.det(np.eye(3)[:, order]) < 0:
        f = f[:, ::-1]

    v -= v.min(axis=0)
    L0, W0, H0 = v.max(axis=0)

    if "slezak" in fname:
        v[:, 2] = H0 - v[:, 2]
        v[:, 1] = W0 - v[:, 1]
    if any(k in fname for k in ("sunbrowner", "lioncat", "vikingu", "th0r88")):
        v[:, 0] = L0 - v[:, 0]
        v[:, 1] = W0 - v[:, 1]

    m_tmp = trimesh.Trimesh(vertices=v, faces=f)
    if m_tmp.volume < 0:
        f = f[:, ::-1]
        m_tmp = trimesh.Trimesh(vertices=v, faces=f)

    sec = m_tmp.section(plane_origin=[0.45 * L0, 0.0, 0.0], plane_normal=[1.0, 0.0, 0.0])
    sv = np.asarray(sec.vertices)
    upper = sv[sv[:, 2] > 3.0]
    y_mid = (upper[:, 1].min() + upper[:, 1].max()) / 2.0
    if "prspr" in fname:
        y_mid = W0 / 2.0
    v[:, 1] -= y_mid

    out = trimesh.Trimesh(vertices=v, faces=f)
    out.fix_normals()

    # Repair multi-body CAD exports (th0r88 and sunbrowner exported touching CAD solids without Boolean Union)
    if "th0r88" in fname:
        r8_ranges = [(0, 1932), (1932, 3886), (3886, 4510), (4510, 7672)]
        bodies = []
        for a, b in r8_ranges:
            sub = trimesh.Trimesh(vertices=out.vertices.copy(), faces=out.faces[a:b].copy(), process=True)
            sub.fix_normals()
            bodies.append(sub)
        # Add 0.05 mm internal overlap at abutting interfaces so 3D boolean union produces a single 2-manifold solid
        v0 = bodies[0].vertices.copy()
        v0[v0[:, 0] > 143.9, 0] = 144.05
        v0[v0[:, 1] < -50.9, 1] = -51.05
        v0[v0[:, 1] > 50.9, 1] = 51.05
        bodies[0].vertices = v0
        v1 = bodies[1].vertices.copy()
        v1[(v1[:, 0] < 147.1) & (v1[:, 1] < -48.9), 0] = 146.95
        bodies[1].vertices = v1
        v2 = bodies[2].vertices.copy()
        v2[v2[:, 0] < 147.1, 0] = 146.95
        bodies[2].vertices = v2
        out = trimesh.boolean.union(bodies, engine="manifold")
        out.fix_normals()
    elif "sunbrowner" in fname:
        d6_ranges = [(0, 2804), (2804, 2840), (2840, 3078)]
        bodies = []
        for a, b in d6_ranges:
            sub = trimesh.Trimesh(vertices=out.vertices.copy(), faces=out.faces[a:b].copy(), process=True)
            sub.fix_normals()
            bodies.append(sub)
        for bi in (1, 2):
            vb = bodies[bi].vertices.copy()
            vb[vb[:, 0] < 148.6, 0] -= 0.05
            bodies[bi].vertices = vb
        out = trimesh.boolean.union(bodies, engine="manifold")
        out.fix_normals()
    elif "vikingu" in fname:
        # Unfold 0.3-micron STL float32 rounding T-junction on top bezel surface (Z = 23.498 mm)
        ov = np.asarray(out.vertices, dtype=float).copy()
        mask_sliver = (np.abs(ov[:, 0] - 168.498) < 0.01) & (np.abs(ov[:, 1] - 48.070) < 0.01) & (ov[:, 2] > 23.0)
        ov[mask_sliver, 1] += 0.005
        out = trimesh.Trimesh(vertices=ov, faces=np.asarray(out.faces, dtype=int).copy(), process=False)
        out.fix_normals()

    return out


def generate_from_template(spec: TraySpec) -> tuple[trimesh.Trimesh, dict[str, str]]:
    """
    Synthesize a tray mesh from its master community CAD template using a 3-zone
    piecewise-linear coordinate warp that:
      1. Locks the interior drive-mounting region at 1:1 scale so SFF-8301 / SFF-8201
         hole pitches and circular screw hole geometry remain 100% undistorted.
      2. Preserves exact mid-rail sliding widths and inner drive clearances (>= 101.60 mm / >= 69.85 mm).
      3. Adjusts only outer bezel/tail margins to match Synology's official (L, W, H) envelope to 0.00 mm.
    """
    fname, mode = COMMUNITY_TEMPLATE_MAP[spec.name]
    base = load_canonical_template(fname)
    v = np.asarray(base.vertices, dtype=float).copy()
    f = np.asarray(base.faces, dtype=int).copy()

    L0 = float(v[:, 0].max() - v[:, 0].min())
    H0 = float(v[:, 2].max() - v[:, 2].min())
    L1, W1, H1 = spec.length_mm, spec.width_mm, spec.height_mm

    # 1. X-axis backplane-datum-locked warp:
    # Lock the entire functional tray from rear rail tip (X = 0) through all SFF screw holes AND
    # the front bezel chassis-stop face / latch hook (X = x_front_pull) at exact x' == x (0.000 mm shift).
    # Absorb overall length delta (L1 - L0) strictly in the external front handle overhang [x_front_pull, L0].
    x_front_pull = TEMPLATE_FRONT_PULL_X[fname]
    v[:, 0] = np.interp(v[:, 0], [0.0, x_front_pull, L0], [0.0, x_front_pull, L1])

    # 2. Y-axis piecewise-linear warp: lock SFF bottom holes [-49.5, +49.5] at 1:1, preserve rail_width_mm, hit W1
    ymin, ymax = float(v[:, 1].min()), float(v[:, 1].max())
    if "prspr" in fname:
        # 2-arm asymmetric L-bracket (Holder Type A/B/C): preserve 31.60 mm left rail arm width
        v[:, 1] = np.interp(
            v[:, 1],
            [ymin, ymin + 31.60, ymax - 15.0, ymax],
            [-W1 / 2.0, -W1 / 2.0 + 31.60, W1 / 2.0 - 15.0, W1 / 2.0],
        )
    else:
        sec = base.section(plane_origin=[0.45 * L0, 0.0, 0.0], plane_normal=[1.0, 0.0, 0.0])
        sv = np.asarray(sec.vertices)
        up = sv[sv[:, 2] > 3.0]
        li = float(up[up[:, 1] < 0][:, 1].max())
        ri = float(up[up[:, 1] > 0][:, 1].min())
        lo = float(up[up[:, 1] < 0][:, 1].min())
        ro = float(up[up[:, 1] > 0][:, 1].max())
        target_li = min(li, -50.85)
        target_ri = max(ri, 50.85)

        if "sunbrowner" in fname:
            r_half = spec.rail_width_mm / 2.0
            v[:, 1] = np.interp(
                v[:, 1],
                [ymin, lo, li, -49.5, 49.5, ri, ro],
                [-(W1 - r_half), -r_half, target_li, -49.5, 49.5, target_ri, r_half],
            )
        elif "slezak" in fname:
            # Sliding rail [-57.75, +57.75] is already 115.50mm exact; lock 100% of rail & inner wall at y' == y
            # and adjust only the external right front bezel ear [ro, ymax] to reach W1 = 120.00 mm.
            v[:, 1] = np.interp(
                v[:, 1],
                [lo, ro, ymax],
                [lo, ro, W1 - (-lo)],
            )
        elif "lioncat" in fname:
            r_half = (W1 - 2.0) / 2.0
            v[:, 1] = np.interp(
                v[:, 1],
                [ymin, lo, li, -49.5, 49.5, ri, ro],
                [-(W1 - r_half), -r_half, target_li, -49.5, 49.5, target_ri, r_half],
            )
        else:
            r_half = W1 / 2.0
            v[:, 1] = np.interp(
                v[:, 1],
                [lo, li, -49.5, 49.5, ri, ro],
                [-r_half, target_li, -49.5, 49.5, target_ri, r_half],
            )

    # 3. Z-axis backplane-and-rail-locked warp:
    # Lock 100% of the sliding rail height [0, rail_z_max] (bottom track Z=0, floor plate Z=2mm,
    # SFF side screw holes Z=4.5..9.5mm, AND the upper sliding rail edge) at exact z' == z (0.000 mm shift).
    # Any overall height delta (H1 - H0) is absorbed strictly in the upper front bezel above the sliding rail.
    if "lioncat" in fname:
        bezel_x_w = np.clip((v[:, 0] - 153.0) / 3.5, 0.0, 1.0)
        z_bezel = np.interp(v[:, 2], [0.0, 12.5, H0], [0.0, 12.5, H1])
        v[:, 2] = (1.0 - bezel_x_w) * v[:, 2] + bezel_x_w * z_bezel
    elif "jimka" in fname:
        # Keep sliding rail (X < 144mm) at exact 18.50mm and raise only the front bezel plate (X >= 146.5mm) to 20.00mm
        bezel_x_w = np.clip((v[:, 0] - 144.0) / 2.5, 0.0, 1.0)
        z_bezel = np.interp(v[:, 2], [0.0, 10.5, H0], [0.0, 10.5, H1])
        v[:, 2] = (1.0 - bezel_x_w) * v[:, 2] + bezel_x_w * z_bezel
    elif "prspr" in fname:
        # Lock side screw holes [0, 6.5mm] at 1:1 so M3 holes remain 100% circular
        v[:, 2] = np.interp(v[:, 2], [0.0, 6.5, H0], [0.0, 6.5, H1])
    elif "th0r88" in fname:
        # Sliding rail top is Z = 13.00mm; lock [0, 13.50mm] at 1:1 so only front bezel top [13.50, 26.50] adjusts
        v[:, 2] = np.interp(v[:, 2], [0.0, 13.50, H0], [0.0, 13.50, H1])
    elif "vikingu" in fname:
        # Sliding rail top is Z = 16.50mm; lock [0, 16.60mm] at 1:1 so only front bezel top [16.60, 26.50] adjusts
        v[:, 2] = np.interp(v[:, 2], [0.0, 16.60, H0], [0.0, 16.60, H1])
    elif "slezak" in fname:
        # Sliding rail top is Z = 19.63mm; lock [0, 20.00mm] at 1:1 so only front bezel arch [20.00, 27.67] adjusts
        v[:, 2] = np.interp(v[:, 2], [0.0, 20.00, H0], [0.0, 20.00, H1])
    else:
        # sunbrowner (rail top Z = 17.00mm, H0 = H1 = 28.00mm)
        v[:, 2] = np.interp(v[:, 2], [0.0, 17.50, H0], [0.0, 17.50, H1])

    out = trimesh.Trimesh(vertices=v, faces=f)
    out.fix_normals()
    return out, {"source_mode": mode, "template_file": fname}
