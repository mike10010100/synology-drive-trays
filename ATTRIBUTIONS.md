# Attributions, Upstream Licenses & Legal Notices

This document provides complete **Creative Commons 4.0 "TASL" attribution** (**T**itle, **A**uthor, **S**ource URL, **L**icense, and **Modification Notice**) for all upstream community 3D CAD models in [`data/ground_truth/`](data/ground_truth/) and their derived outputs in [`output/stl/`](output/stl/) and [`output/step/`](output/step/).

---

## 1. Master Community CAD Templates (Used for 21 of 32 Synology Trays)

Our template-first synthesis pipeline ([`src/synology_drive_trays/templates.py`](src/synology_drive_trays/templates.py)) uses 7 human-sculpted, hardware-proven community CAD models to generate 21 Synology 3.5" desktop, 3.5" rackmount, and internal 2.5" holder trays while locking 100% of the functional bay geometry (rear rail tip, SFF-8301/SFF-8201 screw holes, sliding rail cross-section, and front bezel chassis-stop step) at `1:1` (`0.000 mm` shift):

| Local File in `data/ground_truth/` | Original Title | Original Creator | Source URL | Upstream License | Derived Output Trays (`output/stl/` & `output/step/`) | Modifications Made (per CC 4.0 §3(a)(1)(B)) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `Type_D1_jimka_nosupports.stl` | *Synology Disk Tray (Type D1) without supports* | **Jimka** | [Thingiverse #6205109](https://www.thingiverse.com/thing:6205109) | [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) | `Disk Tray (Type D1)` | Canonicalized axes; adjusted external front finger-pull bow (`X > 150 mm`) and front bezel top edge (`X >= 146.5 mm`) to match `160 × 113 × 20 mm` envelope; `0.000 mm` shift in bay/SFF holes. |
| `Type_D7_slezak.step` & `Type_D7_slezak_from_step.stl` | *Synology HDD Tray D7* | **Frederic Slezak** | [Printables #1328363](https://www.printables.com/model/1328363) | [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) | `Disk Tray (Type D7)`, `Disk Tray (Type D4)` | Tessellated from native STEP; canonicalized axes; adjusted outer front pull-handle bar (`X > 161 mm`), right bezel ear (`Y > 57.75 mm`), and bezel top arch (`Z > 20 mm`) to match `D7` (`164 × 120 × 27.5 mm`) and `D4` (`166 × 120 × 27.5 mm`); `0.000 mm` shift in bay/SFF holes. |
| `Type_D6_sunbrowner.stl` | *Synology D6 3.5/2.5 Hard Drive Tray* | **sunbrowner** | [Thingiverse #4887288](https://www.thingiverse.com/thing:4887288) | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) | `Disk Tray (Type D6)`, `Disk Tray (Type D8)`, `Disk Tray (Type D9)` | Canonicalized axes; adjusted external front door face (`X > 162.5 mm`), left front bezel overhang, and `0.14 mm` inner pin-boss chord to match `172 × 118 × 28 mm` envelope; `0.000 mm` shift in bay/SFF holes. |
| `Type_D5_lioncat.stl` | *Synology D5 Tray* | **Lioncat55** | [Printables #422496](https://www.printables.com/model/422496) | [CC0 1.0 Public Domain](https://creativecommons.org/publicdomain/zero/1.0/) | `Disk Tray (Type D5)`, `Disk Tray (Type D2)`, `Disk Tray (Type D3)` | Canonicalized axes; adjusted external front finger-pull loop (`X > 165 mm`), outer rail cheek (`112/113 mm`), and front bezel height (`X > 153 mm` to `28 mm`) while keeping `16.0 mm` sliding rail and SFF holes at `0.000 mm` shift. |
| `Type_R7_vikingu.stl` | *Synology Disk Tray (Type R7)* | **vikingu** | [Thingiverse #6072020](https://www.thingiverse.com/thing:6072020) | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) | `Disk Tray (Type R7)`, `Drive Tray (Type R10)` | Canonicalized axes; adjusted external front bezel face (`X > 165 mm`) and top edge of front bezel (`Z > 16.6 mm`) to match `174 × 104 × 28 mm` envelope; `0.000 mm` shift on `104 × 16.5 mm` sliding rail and SFF holes. |
| `Type_R8_th0r88.stl` | *RS818+/RS818RP+ HDD Caddy (Type R8)* | **th0r88** | [Thingiverse #4813963](https://www.thingiverse.com/thing:4813963) | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) | `Disk Tray (Type R8)`, `Disk Tray (Type R6)`, `Disk Tray (Type R5)`, `Disk Tray (Type R1–R4)` | Canonicalized axes; adjusted external front bezel face (`X > 165 mm`), top edge of front bezel (`Z > 13.5 mm`), and outer rail cheek (`±0.50 mm` symmetric for `105 mm` `R1–R4`); `0.000 mm` shift on `13.0 mm` sliding rail height, bezel stop (`X = 145 mm`), and SFF holes. |
| `Holder_Type_C_prspr.stl` | *Synology SSD Adapter (Type C equivalent)* | **PRSPR** | [Printables #446654](https://www.printables.com/model/446654) | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) | `Disk Holder (Type C)`, `Disk Holder (Type A)`, `Disk Holder (Type B)` | Canonicalized axes; adjusted front pocket wall tip (`X > 110 mm`) and upper side wall (`Z > 6.5 mm`) to match `115 × 103 × 15 mm` envelope while locking `31.60 mm` left rail arm and all M3 screw holes at `0.000 mm` shift. |

---

## 2. Additional Community Validation Reference Models in `data/ground_truth/`

The following 9 community models are stored unmodified in [`data/ground_truth/`](data/ground_truth/) and used by [`src/synology_drive_trays/validator.py`](src/synology_drive_trays/validator.py) for independent cross-sectional validation:

| Local File in `data/ground_truth/` | Original Title | Original Creator | Source URL | Upstream License | Modification Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `Type_D1_jimka.stl` | *Synology Disk Tray (Type D1)* | **Jimka** | [Thingiverse #6205109](https://www.thingiverse.com/thing:6205109) | [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) | Unmodified validation reference |
| `Type_D1_ds409.stl` | *Synology Disk tray D1 (DS409)* | **SnakeNET** | [Thingiverse #2490968](https://www.thingiverse.com/thing:2490968) | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) | Unmodified validation reference |
| `Type_D7_kai.stl` | *Synology DISK TRAY (Type D7)* | **kai** | [Printables #200878](https://www.printables.com/model/200878) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Unmodified validation reference |
| `Type_D6_25in_urill.stl` | *Synology D6 tray for 2.5-inch drives* | **urill** | [Printables #467163](https://www.printables.com/model/467163) | [CC0 1.0 Public Domain](https://creativecommons.org/publicdomain/zero/1.0/) | Unmodified validation reference |
| `Type_D8_25in_kairi_1.stl` | *Synology D8 2.5in Tray 1* | **Vladimir_SM (Kairi)** | [Printables #1631635](https://www.printables.com/model/1631635) | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) | Unmodified validation reference |
| `Holder_Type_C_johnny.stl` | *Disk holder Synology 2.5in, Type C* | **JohnnyAdams2024** | [Thingiverse #7018439](https://www.thingiverse.com/thing:7018439) | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) | Unmodified validation reference |
| `Holder_Type_C_bender.stl` | *2.5in Adapter for Synology DS Disk Stations (Type C)* | **Bender2k** | [Thingiverse #1456350](https://www.thingiverse.com/thing:1456350) | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) | Unmodified validation reference |
| `Push_Lock_Latch_btcb.stl` | *Synology Push Lock Latch part* | **BTCB** | [Printables #1367836](https://www.printables.com/model/1367836) | [CC0 1.0 Public Domain](https://creativecommons.org/publicdomain/zero/1.0/) | Unmodified validation reference |
| `Push_Lock_Latch_yujung.stl` | *Synology push lock door latch* | **yujungchang** | [Thingiverse #4677567](https://www.thingiverse.com/thing:4677567) | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) | Unmodified validation reference |

---

## 3. Original Procedural 3D CAD Models (11 of 32 Synology Trays)

The following 11 trays have no existing community 3D CAD models online and are generated procedurally from scratch in [`src/synology_drive_trays/generator.py`](src/synology_drive_trays/generator.py) using SFF-8201 / SFF-8301 standards and official Synology envelope dimensions. They are released under the **MIT License**:

* `Drive Tray (Type R9)` (`HD6500`, `SA3400D`, `RX6022sas` — 60-bay 3.5"/2.5" top-loading vertical carrier)
* `2.5" Drive Tray (R5)` (`SA3200D`, `RS1619xs+` — 60-bay 2.5" left-offset L-floor carrier)
* `Disk Tray (Type Slim)` (`DS414slim`, `DS416slim`, `EDS14` — `114 mm` U-scoop slide bezel 2.5" carrier)
* `Disk Tray (Type SSD)` (`FS1018`, `DS411slim` — `134 mm` U-scoop slide bezel 2.5" carrier)
* `2.5" Disk Tray (D1)` (`DS620slim`, `DS419slim` — `124 mm` push-lock 2.5" desktop carrier)
* `2.5" Drive Tray (R7)` (`PAS7700` — `179 mm` open-bottom U.2/U.3 NVMe rack carrier)
* `2.5" Disk Tray (R1)` (`FS6400`, `FS3600`, `FS3410`, `FS3400`, `FS3017`, `FS2017`, `RS18016xs+`, `RX2417sas`)
* `2.5" Disk Tray (R2)` (`RS2416+`, `RS2416RP+`)
* `2.5" Disk Tray (R3)` (`UC3200` — `71 mm` ultra-slim 2.5" dual-controller carrier)
* `2.5" Disk Tray (R4)` (`FS2500`)
* `2.5" Drive Tray (R6)` (`SA6400`, `SA3610`, `SA3410`, `FS3410`)

---

## 4. Trademark & Fair-Use Reference Image Notice

* **Trademarks:** "Synology", "DiskStation", "RackStation", "FlashStation", and all Synology model numbers (`DS923+`, `RS1221+`, `HD6500`, etc.) are trademarks or registered trademarks of **Synology Inc.** Use of these marks in this repository is strictly for **nominative fair-use identification** of compatible replacement hardware dimensions and part compatibility. This project is independent and is neither affiliated with nor endorsed by Synology Inc.
* **Reference Thumbnails (`data/reference_images/` & `output/gallery/`):** Low-resolution spare-part catalog thumbnails retrieved from `synology.com/api/products/getSparePartImg/` are included for non-commercial educational, interoperability, and visual-verification comparison (`17 U.S.C. § 107` fair use). All copyrights in the original product photographs remain the property of Synology Inc.
