"""Render side-by-side 3D CAD visual comparison cards (Official Synology Photo vs. Community GT vs. Generated CAD)."""
from __future__ import annotations

import shutil
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np
from PIL import Image
import trimesh

from synology_drive_trays.specs import build_all_tray_specs

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "output"
GALLERY_DIR = OUT_DIR / "gallery"
REF_IMG_DIR = ROOT / "data" / "reference_images"
GT_DIR = ROOT / "data" / "ground_truth"


def _orient_mesh_for_display(mesh: trimesh.Trimesh, is_gt: bool = False) -> trimesh.Trimesh:
    """Center mesh at origin and orient longest axis along X, medium along Y, shortest along Z."""
    m = mesh.copy()
    m.vertices -= m.bounds.mean(axis=0)
    if is_gt:
        order = np.argsort(m.extents)[::-1]
        m.vertices = m.vertices[:, order]
        # Ensure floor is at bottom (-Z) by checking where more vertices sit in Z
        z_med = np.median(m.vertices[:, 2])
        if z_med > 0:
            m.vertices[:, 2] *= -1.0
    return m


def _plot_3d_mesh(ax, mesh: trimesh.Trimesh, title: str, color: str = "#38bdf8", edge_color: str = "#0284c7") -> None:
    """Render a shaded 3D triangle mesh with directional lighting onto a Matplotlib 3D axis."""
    v = mesh.vertices
    f = mesh.faces
    tris = v[f]

    # Simple diffuse lighting calculation from light vector [0.4, -0.5, 0.8]
    normals = mesh.face_normals
    light_dir = np.array([0.35, -0.45, 0.82])
    light_dir /= np.linalg.norm(light_dir)
    intensity = np.clip(np.abs(normals @ light_dir) * 0.72 + 0.28, 0.25, 1.0)

    base_rgb = np.array(matplotlib.colors.to_rgb(color))
    face_colors = np.zeros((len(f), 4))
    face_colors[:, :3] = base_rgb[None, :] * intensity[:, None]
    face_colors[:, 3] = 0.96

    poly = Poly3DCollection(tris, facecolors=face_colors, linewidths=0.08, edgecolors=(0.08, 0.12, 0.18, 0.18))
    ax.add_collection3d(poly)

    spans = v.max(axis=0) - v.min(axis=0)
    max_span = spans.max() * 0.54
    mid = (v.max(axis=0) + v.min(axis=0)) / 2.0
    ax.set_xlim(mid[0] - max_span, mid[0] + max_span)
    ax.set_ylim(mid[1] - max_span, mid[1] + max_span)
    ax.set_zlim(mid[2] - max_span * 0.55, mid[2] + max_span * 0.55)
    ax.set_box_aspect((1.0, 1.0, 0.55))
    ax.view_init(elev=30, azim=42)
    ax.set_axis_off()
    ax.set_facecolor("#0f172a")
    ax.set_title(title, color="#f8fafc", fontsize=11, fontweight="bold", pad=6)


def render_comparison_card(
    tray_name: str,
    ref_img_name: str | None,
    gt_stl_name: str | None,
    out_png: Path,
) -> None:
    """Render a 3-panel comparison card: Official Synology Render | Community GT Mesh (or Top View) | Generated 3D CAD."""
    specs = build_all_tray_specs()
    spec = specs[tray_name]
    gen_stl = OUT_DIR / "stl" / f"{spec.slug}.stl"
    gen_mesh = _orient_mesh_for_display(trimesh.load(str(gen_stl), force="mesh"), is_gt=False)

    fig = plt.figure(figsize=(15.5, 5.2), dpi=160, facecolor="#0f172a")
    fig.suptitle(
        f"{spec.name} — Archetype: {spec.archetype.value} | Official Envelope: {spec.length_mm:.1f} × {spec.width_mm:.1f} × {spec.height_mm:.1f} mm (Rail W: {spec.rail_width_mm:.1f} mm)",
        color="#f8fafc",
        fontsize=13,
        fontweight="bold",
        y=0.97,
    )

    # Panel 1: Official Synology Reference Photo
    ax1 = fig.add_subplot(1, 3, 1)
    ax1.set_facecolor("#ffffff")
    if ref_img_name and (REF_IMG_DIR / ref_img_name).exists():
        img = Image.open(REF_IMG_DIR / ref_img_name)
        ax1.imshow(img)
        ax1.set_title(f"Official Synology Spare Parts Photo\n({ref_img_name})", color="#38bdf8", fontsize=10.5, fontweight="bold")
    else:
        ax1.text(0.5, 0.5, "Legacy 2009 Part\n(No Official API Render)", ha="center", va="center", fontsize=12)
        ax1.set_title("Official Synology Reference", color="#38bdf8", fontsize=10.5, fontweight="bold")
    ax1.axis("off")

    # Panel 2: Generated Parametric 3D CAD (Isometric View)
    ax2 = fig.add_subplot(1, 3, 2, projection="3d")
    _plot_3d_mesh(
        ax2,
        gen_mesh,
        f"Our Generated Parametric 3D CAD (.step/.stl)\nHoneycomb/Slot Web + Snap-Fit Latch ({len(gen_mesh.faces)} tris)",
        color="#38bdf8",
    )

    # Panel 3: Community Ground-Truth 3D Mesh OR Top Orthographic Blueprint View
    ax3 = fig.add_subplot(1, 3, 3, projection="3d")
    if gt_stl_name and (GT_DIR / gt_stl_name).exists():
        gt_mesh = _orient_mesh_for_display(trimesh.load(str(GT_DIR / gt_stl_name), force="mesh"), is_gt=True)
        _plot_3d_mesh(
            ax3,
            gt_mesh,
            f"Community Ground-Truth CAD\n({gt_stl_name} — {len(gt_mesh.faces)} tris)",
            color="#fbbf24",
        )
    else:
        # Show Top-Down Orthographic 3D view of our generated model to highlight floor web & SFF holes
        _plot_3d_mesh(
            ax3,
            gen_mesh,
            f"Generated CAD — Top Orthographic View\n(SFF-8301 / SFF-8201 Hole Pattern & Floor Web)",
            color="#34d399",
        )
        ax3.view_init(elev=84, azim=-90)

    plt.tight_layout(rect=[0.0, 0.0, 1.0, 0.92])
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=160, facecolor="#0f172a")
    plt.close(fig)
    print(f"  [GALLERY] Saved {out_png.name}")


def render_archetype_overview_grid(out_png: Path) -> None:
    """Render a 2x3 master overview grid of all 6 Synology Drive Tray structural archetypes."""
    specs = build_all_tray_specs()
    featured = [
        ("Disk Tray (Type D6)", "#38bdf8", "1. Desktop Lock (D2, D3, D5, D6, D8, D9, D10)"),
        ("Disk Tray (Type D7)", "#60a5fa", "2. Desktop Slide (D1, D4, D7, DX510)"),
        ("Disk Tray (Type R7)", "#34d399", "3. Rackmount 3.5\" (R1..R8, R10)"),
        ("Drive Tray (Type R9)", "#a78bfa", "4. Top-Loading 60-Bay (R9, 2.5\" R5)"),
        ("2.5\" Drive Tray (R6)", "#fbbf24", "5. 2.5\" SFF Slim Tray (2.5\" R1..R7, D1, Slim, SSD)"),
        ("Disk Holder (Type C)", "#f472b6", "6. Internal 2.5\" Disk Holder (Type A, B, C)"),
    ]
    fig = plt.figure(figsize=(16, 10), dpi=160, facecolor="#0f172a")
    fig.suptitle(
        "Synology Drive Tray Parametric 3D CAD Pipeline — All 6 Structural Archetypes (32/32 Tray Types)",
        color="#f8fafc",
        fontsize=15,
        fontweight="bold",
        y=0.97,
    )
    for idx, (tname, col, label) in enumerate(featured, 1):
        spec = specs[tname]
        gen_stl = OUT_DIR / "stl" / f"{spec.slug}.stl"
        mesh = _orient_mesh_for_display(trimesh.load(str(gen_stl), force="mesh"), is_gt=False)
        ax = fig.add_subplot(2, 3, idx, projection="3d")
        _plot_3d_mesh(
            ax,
            mesh,
            f"{label}\n{tname}: {spec.length_mm:.0f}×{spec.width_mm:.0f}×{spec.height_mm:.1f} mm",
            color=col,
        )
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
    ]
    for tname, ref_img, gt_stl, out_name in cards:
        render_comparison_card(tname, ref_img, gt_stl, GALLERY_DIR / out_name)


if __name__ == "__main__":
    main()
