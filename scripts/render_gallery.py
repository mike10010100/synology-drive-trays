"""True Z-buffered 3D CAD studio renderer for side-by-side comparison cards (Official Photo vs. Generated CAD vs. Community GT)."""
from __future__ import annotations

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
import trimesh

from synology_drive_trays.specs import build_all_tray_specs
from synology_drive_trays.templates import COMMUNITY_TEMPLATE_MAP, has_community_template, load_canonical_template

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "output"
GALLERY_DIR = OUT_DIR / "gallery"
REF_IMG_DIR = ROOT / "data" / "reference_images"
GT_DIR = ROOT / "data" / "ground_truth"


def _orient_mesh_for_display(mesh: trimesh.Trimesh, is_gt: bool = False, gt_name: str = "") -> trimesh.Trimesh:
    """
    Canonicalize mesh into display coordinates:
      X in [-L/2, +L/2] where +X is the FRONT BEZEL (foreground bottom-left in isometric view)
      Y in [-W/2, +W/2] where -Y is left rail, +Y is right rail
      Z in [-H/2, +H/2] where -Z is the bottom floor plate, +Z is the top of bezel/rails
    """
    if is_gt and gt_name:
        m = load_canonical_template(gt_name).copy()
    else:
        m = mesh.copy()
    m.vertices -= (m.bounds[0] + m.bounds[1]) / 2.0
    return m


def render_mesh_zbuffer(
    mesh: trimesh.Trimesh,
    width_px: int = 680,
    height_px: int = 480,
    elev_deg: float = 30.0,
    azim_deg: float = -138.0,
    base_color: tuple[float, float, float] = (0.22, 0.74, 0.97),
    bg_color: tuple[float, float, float] = (15 / 255, 23 / 255, 42 / 255),
) -> np.ndarray:
    """
    Software Z-buffered orthographic rasterizer with Phong lighting + screen-space crease/silhouette edge ink.
    Eliminates all Matplotlib Poly3DCollection painter's-algorithm sorting artifacts.
    """
    v = mesh.vertices.copy()
    f = mesh.faces
    normals = mesh.face_normals.copy()

    # Build camera rotation matrix (azim around Z, then elev around screen X)
    az = np.deg2rad(azim_deg)
    el = np.deg2rad(elev_deg)
    Rz = np.array([
        [np.cos(az), -np.sin(az), 0.0],
        [np.sin(az),  np.cos(az), 0.0],
        [0.0,         0.0,        1.0],
    ])
    Rx = np.array([
        [1.0, 0.0,          0.0],
        [0.0, np.cos(el), -np.sin(el)],
        [0.0, np.sin(el),  np.cos(el)],
    ])
    # Map world (X,Y,Z) -> camera (u_right, v_up, depth_towards_camera)
    # Standard isometric: camera looks along +Y_cam, so screen X = X_rot, screen Y = Z_rot, depth = -Y_rot
    R = Rx @ Rz
    v_cam = v @ R.T
    n_cam = normals @ R.T

    sx = v_cam[:, 0]
    sy = v_cam[:, 2]
    sz = -v_cam[:, 1]  # larger sz = closer to camera

    # Fit bounding box to screen with 12% margin
    span_x = max(1e-3, sx.max() - sx.min())
    span_y = max(1e-3, sy.max() - sy.min())
    scale = min((width_px * 0.82) / span_x, (height_px * 0.80) / span_y)

    cx = (sx.max() + sx.min()) / 2.0
    cy = (sy.max() + sy.min()) / 2.0

    px = (sx - cx) * scale + width_px / 2.0
    py = height_px / 2.0 - (sy - cy) * scale  # Y-down in image

    zbuf = np.full((height_px, width_px), -np.inf, dtype=np.float32)
    nbuf = np.zeros((height_px, width_px, 3), dtype=np.float32)
    hit_mask = np.zeros((height_px, width_px), dtype=bool)

    tris_x = px[f]
    tris_y = py[f]
    tris_z = sz[f]

    # Bounding boxes per triangle in pixel coords
    xmins = np.clip(np.floor(tris_x.min(axis=1)).astype(int), 0, width_px - 1)
    xmaxs = np.clip(np.ceil(tris_x.max(axis=1)).astype(int), 0, width_px - 1)
    ymins = np.clip(np.floor(tris_y.min(axis=1)).astype(int), 0, height_px - 1)
    ymaxs = np.clip(np.ceil(tris_y.max(axis=1)).astype(int), 0, height_px - 1)

    # Precompute 2x signed area in screen space
    x0, x1, x2 = tris_x[:, 0], tris_x[:, 1], tris_x[:, 2]
    y0, y1, y2 = tris_y[:, 0], tris_y[:, 1], tris_y[:, 2]
    z0, z1, z2 = tris_z[:, 0], tris_z[:, 1], tris_z[:, 2]
    denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)

    valid_tris = np.where(np.abs(denom) > 1e-4)[0]
    for i in valid_tris:
        x_lo, x_hi = xmins[i], xmaxs[i]
        y_lo, y_hi = ymins[i], ymaxs[i]
        if x_lo > x_hi or y_lo > y_hi:
            continue
        inv_d = 1.0 / denom[i]
        gx, gy = np.meshgrid(np.arange(x_lo, x_hi + 1) + 0.5, np.arange(y_lo, y_hi + 1) + 0.5)
        w0 = ((y1[i] - y2[i]) * (gx - x2[i]) + (x2[i] - x1[i]) * (gy - y2[i])) * inv_d
        w1 = ((y2[i] - y0[i]) * (gx - x2[i]) + (x0[i] - x2[i]) * (gy - y2[i])) * inv_d
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        if not np.any(inside):
            continue
        z_interp = w0 * z0[i] + w1 * z1[i] + w2 * z2[i]
        sub_z = zbuf[y_lo : y_hi + 1, x_lo : x_hi + 1]
        closer = inside & (z_interp > sub_z)
        if np.any(closer):
            sub_z[closer] = z_interp[closer]
            hit_mask[y_lo : y_hi + 1, x_lo : x_hi + 1][closer] = True
            n_vec = n_cam[i]
            if n_vec[1] > 0:
                n_vec = -n_vec
            nbuf[y_lo : y_hi + 1, x_lo : x_hi + 1][closer] = n_vec

    # Studio 3-point lighting (key light + fill light + rim light)
    img = np.zeros((height_px, width_px, 3), dtype=np.float32)
    img[:, :] = bg_color

    if np.any(hit_mask):
        n = nbuf[hit_mask]
        key_dir = np.array([-0.42, -0.65, 0.63], dtype=np.float32)
        key_dir /= np.linalg.norm(key_dir)
        fill_dir = np.array([0.55, -0.45, 0.25], dtype=np.float32)
        fill_dir /= np.linalg.norm(fill_dir)

        diff_key = np.clip(np.abs(n @ key_dir), 0.0, 1.0)
        diff_fill = np.clip(np.abs(n @ fill_dir), 0.0, 1.0)
        spec = np.power(diff_key, 18.0) * 0.28

        shade = 0.24 + 0.58 * diff_key + 0.22 * diff_fill
        base = np.array(base_color, dtype=np.float32)
        rgb = np.clip(base[None, :] * shade[:, None] + spec[:, None], 0.0, 1.0)
        img[hit_mask] = rgb

        # Screen-space CAD feature edge & silhouette detection
        z_clean = np.where(hit_mask, zbuf, zbuf[hit_mask].min() - 20.0)
        dz_x = np.abs(np.diff(z_clean, axis=1, prepend=z_clean[:, :1]))
        dz_y = np.abs(np.diff(z_clean, axis=0, prepend=z_clean[:1, :]))
        dn_x = np.linalg.norm(np.diff(nbuf, axis=1, prepend=nbuf[:, :1, :]), axis=2)
        dn_y = np.linalg.norm(np.diff(nbuf, axis=0, prepend=nbuf[:1, :, :]), axis=2)

        edge_strength = np.clip((dz_x + dz_y) * 0.22 + (dn_x + dn_y) * 0.45, 0.0, 1.0)
        edge_mask = hit_mask & (edge_strength > 0.35)
        img[edge_mask] *= 0.32

    return (np.clip(img, 0.0, 1.0) * 255).astype(np.uint8)


def render_comparison_card(
    tray_name: str,
    ref_img_name: str | None,
    gt_stl_name: str | None,
    out_png: Path,
) -> None:
    """Render a 3-panel comparison card using true Z-buffered CAD rendering."""
    specs = build_all_tray_specs()
    spec = specs[tray_name]
    gen_stl = OUT_DIR / "stl" / f"{spec.slug}.stl"
    gen_mesh = _orient_mesh_for_display(trimesh.load(str(gen_stl), force="mesh"), is_gt=False)

    fig, axes = plt.subplots(1, 3, figsize=(16.0, 5.2), dpi=160, facecolor="#0f172a")
    fig.suptitle(
        f"{spec.name} — Archetype: {spec.archetype.value} | Official Envelope: {spec.length_mm:.1f} × {spec.width_mm:.1f} × {spec.height_mm:.1f} mm (Rail W: {spec.rail_width_mm:.1f} mm)",
        color="#f8fafc",
        fontsize=13,
        fontweight="bold",
        y=0.96,
    )

    # Panel 1: Official Synology Reference Photo
    axes[0].set_facecolor("#ffffff")
    if ref_img_name and (REF_IMG_DIR / ref_img_name).exists():
        img = Image.open(REF_IMG_DIR / ref_img_name)
        axes[0].imshow(img)
        axes[0].set_title(f"Official Synology Spare Parts Photo\n({ref_img_name})", color="#38bdf8", fontsize=10.5, fontweight="bold")
    else:
        axes[0].text(0.5, 0.5, "Legacy 2009 Part\n(No Official API Render)", ha="center", va="center", fontsize=12)
        axes[0].set_title("Official Synology Reference", color="#38bdf8", fontsize=10.5, fontweight="bold")
    axes[0].axis("off")

    # Panel 2: Our Output 3D CAD (Community Template + SFF-Preserving Warp OR Procedural CAD)
    gen_iso = render_mesh_zbuffer(gen_mesh, elev_deg=32.0, azim_deg=-138.0, base_color=(0.22, 0.74, 0.97))
    axes[1].imshow(gen_iso)
    if has_community_template(tray_name):
        t_file, t_mode = COMMUNITY_TEMPLATE_MAP[tray_name]
        mode_label = "Template-Derived CAD (Exact SFF + Calibrated Envelope)"
    else:
        mode_label = "Procedural 3D CAD (No Community Model Exists)"
    axes[1].set_title(
        f"Our Pipeline Output ({spec.slug}.stl)\n{mode_label} ({len(gen_mesh.faces)} tris)",
        color="#f8fafc",
        fontsize=10.5,
        fontweight="bold",
    )
    axes[1].axis("off")

    # Panel 3: Raw Unwarped Community Ground-Truth CAD OR Top Orthographic View
    if gt_stl_name and (GT_DIR / gt_stl_name).exists():
        gt_mesh = _orient_mesh_for_display(trimesh.load(str(GT_DIR / gt_stl_name), force="mesh"), is_gt=True, gt_name=gt_stl_name)
        gt_iso = render_mesh_zbuffer(gt_mesh, elev_deg=32.0, azim_deg=-138.0, base_color=(0.98, 0.75, 0.14))
        axes[2].imshow(gt_iso)
        axes[2].set_title(
            f"Raw Unwarped Community Source CAD\n({gt_stl_name} — {len(gt_mesh.faces)} tris)",
            color="#fbbf24",
            fontsize=10.5,
            fontweight="bold",
        )
    else:
        gen_top = render_mesh_zbuffer(gen_mesh, elev_deg=88.0, azim_deg=-90.0, base_color=(0.20, 0.83, 0.60))
        axes[2].imshow(gen_top)
        axes[2].set_title(
            "Generated CAD — Top Orthographic View\n(Floor Web & SFF-8301 / SFF-8201 Holes)",
            color="#34d399",
            fontsize=10.5,
            fontweight="bold",
        )
    axes[2].axis("off")

    plt.tight_layout(rect=[0.0, 0.0, 1.0, 0.91])
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=160, facecolor="#0f172a")
    plt.close(fig)
    print(f"  [GALLERY] Saved {out_png.name}")


def render_archetype_overview_grid(out_png: Path) -> None:
    """Render a 2x3 master overview grid of all 6 Synology Drive Tray structural archetypes."""
    specs = build_all_tray_specs()
    featured = [
        ("Disk Tray (Type D6)", (0.22, 0.74, 0.97), "1. Desktop Lock (D2, D3, D5, D6, D8, D9, D10)"),
        ("Disk Tray (Type D7)", (0.38, 0.65, 0.98), "2. Desktop Slide (D1, D4, D7, DX510)"),
        ("Disk Tray (Type R7)", (0.20, 0.83, 0.60), "3. Rackmount 3.5\" (R1..R8, R10)"),
        ("Drive Tray (Type R9)", (0.65, 0.55, 0.98), "4. Top-Loading 60-Bay (R9, 2.5\" R5)"),
        ("2.5\" Drive Tray (R6)", (0.98, 0.75, 0.14), "5. 2.5\" SFF Slim Tray (2.5\" R1..R7, D1, Slim, SSD)"),
        ("Disk Holder (Type C)", (0.96, 0.45, 0.71), "6. Internal 2.5\" Disk Holder (Type A, B, C)"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(16.5, 10.0), dpi=160, facecolor="#0f172a")
    fig.suptitle(
        "Synology Drive Tray Parametric 3D CAD Pipeline — All 6 Structural Archetypes (32/32 Tray Types)",
        color="#f8fafc",
        fontsize=15,
        fontweight="bold",
        y=0.97,
    )
    for idx, (tname, col, label) in enumerate(featured):
        spec = specs[tname]
        gen_stl = OUT_DIR / "stl" / f"{spec.slug}.stl"
        mesh = _orient_mesh_for_display(trimesh.load(str(gen_stl), force="mesh"), is_gt=False)
        img = render_mesh_zbuffer(mesh, elev_deg=32.0, azim_deg=-138.0, base_color=col)
        ax = axes[idx // 3, idx % 3]
        ax.imshow(img)
        ax.set_title(
            f"{label}\n{tname}: {spec.length_mm:.0f}×{spec.width_mm:.0f}×{spec.height_mm:.1f} mm",
            color="#f8fafc",
            fontsize=11,
            fontweight="bold",
        )
        ax.axis("off")

    plt.tight_layout(rect=[0.0, 0.0, 1.0, 0.93])
    fig.savefig(out_png, dpi=160, facecolor="#0f172a")
    plt.close(fig)
    print(f"  [GALLERY] Saved master overview {out_png.name}")


def main() -> None:
    GALLERY_DIR.mkdir(parents=True, exist_ok=True)
    render_archetype_overview_grid(GALLERY_DIR / "00_master_archetypes_grid.png")

    cards = [
        ("Disk Tray (Type D6)", "Disk_Tray_Type_D6_24851.png", "Type_D6_sunbrowner.stl", "01_compare_Type_D6.png"),
        ("Disk Tray (Type D7)", "Disk_Tray_Type_D7_24890.png", "Type_D7_slezak_from_step.stl", "02_compare_Type_D7.png"),
        ("Disk Tray (Type R7)", "Disk_Tray_Type_R7_24846.png", "Type_R7_vikingu.stl", "03_compare_Type_R7.png"),
        ("Disk Tray (Type R8)", "Disk_Tray_Type_R8_31665.png", "Type_R8_th0r88.stl", "04_compare_Type_R8.png"),
        ("Disk Tray (Type D1)", "Disk_Tray_Type_D1_24747.png", "Type_D1_jimka_nosupports.stl", "05_compare_Type_D1.png"),
        ("Disk Tray (Type D5)", "Disk_Tray_Type_D5_24713.png", "Type_D5_lioncat.stl", "06_compare_Type_D5.png"),
        ("Drive Tray (Type R9)", "Drive_Tray_Type_R9_36225.png", None, "07_compare_Type_R9_60bay.png"),
        ("2.5\" Drive Tray (R6)", "2.5in_Drive_Tray_R6_46989.png", None, "08_compare_25in_R6.png"),
        ("Disk Holder (Type C)", "Disk_Holder_Type_C_24492.png", "Holder_Type_C_prspr.stl", "09_compare_Holder_Type_C.png"),
        ("Disk Tray (Type D4)", "Disk_Tray_Type_D4_29497.png", "Type_D7_slezak_from_step.stl", "10_compare_Type_D4_warped.png"),
        ("Disk Tray (Type R1)", "Disk_Tray_Type_R1_29506.png", "Type_R8_th0r88.stl", "11_compare_Type_R1_warped.png"),
        ("2.5\" Drive Tray (R5)", "2.5in_Drive_Tray_R5_37031.png", None, "12_compare_25in_R5_60bay.png"),
        ("Disk Tray (Type Slim)", "Disk_Tray_Type_Slim_24710.png", None, "13_compare_Type_Slim.png"),
        ("Disk Tray (Type SSD)", "Disk_Tray_Type_SSD_24719.png", None, "14_compare_Type_SSD.png"),
        ("2.5\" Disk Tray (D1)", "2.5in_Disk_Tray_D1_34052.png", None, "15_compare_25in_D1.png"),
        ("2.5\" Drive Tray (R7)", "2.5in_Drive_Tray_R7_49194.png", None, "16_compare_25in_R7_NVMe.png"),
        ("2.5\" Disk Tray (R1)", "2.5in_Disk_Tray_R1_30434.png", None, "17_compare_25in_R1.png"),
        ("2.5\" Disk Tray (R3)", "2.5in_Disk_Tray_R3_36224.png", None, "18_compare_25in_R3.png"),
    ]
    for tname, ref_img, gt_stl, out_name in cards:
        render_comparison_card(tname, ref_img, gt_stl, GALLERY_DIR / out_name)


if __name__ == "__main__":
    main()
