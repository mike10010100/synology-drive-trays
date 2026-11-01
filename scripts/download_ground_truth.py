"""Download community ground-truth STL/STEP files and official Synology reference data."""
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GT_DIR = ROOT / "data" / "ground_truth"
IMG_DIR = ROOT / "data" / "reference_images"
GT_DIR.mkdir(parents=True, exist_ok=True)
IMG_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

PRINTABLES_FILES = [
    # (modelId, fileId, fileType, local_filename, tray_type, description)
    ("200878", "834610", "stl", "Type_D7_kai.stl", "Disk Tray (Type D7)", "Synology DISK TRAY (Type D7) by kai (STL)"),
    ("1328363", "5586168", "stl", "Type_D7_slezak.step", "Disk Tray (Type D7)", "Synology HDD Tray D7 by Frederic Slezak (Native STEP)"),
    ("422496", "1835450", "stl", "Type_D5_lioncat.stl", "Disk Tray (Type D5)", "Synology D5 Tray by Lioncat55 (STL)"),
    ("467163", "2021414", "stl", "Type_D6_25in_urill.stl", "Disk Tray (Type D6)", "Synology D6 tray for 2.5-inch drives by urill (STL)"),
    ("1631635", "6865152", "stl", "Type_D8_25in_kairi_1.stl", "Disk Tray (Type D8)", "Synology D8 2.5in Tray 1 by Kairi (STL)"),
    ("1367836", "5766001", "stl", "Push_Lock_Latch_btcb.stl", "Latch (D5/D6/D8/D9)", "Synology Push Lock Latch part by BTCB (STL)"),
    ("446654", "1943296", "stl", "Holder_Type_C_prspr.stl", "Disk Holder (Type C)", "Synology SSD Adapter (Type C equivalent) by PRSPR (STL)"),
]

THINGIVERSE_FILES = [
    # (thingId, target_file_index, local_filename, tray_type, description)
    ("6072020", 0, "Type_R7_vikingu.stl", "Disk Tray (Type R7)", "Synology Disk Tray (Type R7) by vikingu (STL)"),
    ("4813963", 0, "Type_R8_th0r88.stl", "Disk Tray (Type R8)", "RS818+/RS818RP+ HDD Caddy (Type R8) by th0r88 (STL)"),
    ("6205109", 0, "Type_D1_jimka_nosupports.stl", "Disk Tray (Type D1)", "Synology Disk Tray (Type D1) without supports by Jimka (STL)"),
    ("6205109", 1, "Type_D1_jimka.stl", "Disk Tray (Type D1)", "Synology Disk Tray (Type D1) by Jimka (STL)"),
    ("2490968", 0, "Type_D1_ds409.stl", "Disk Tray (Type D1)", "Synology Disk tray D1 (DS409) (STL)"),
    ("4887288", 0, "Type_D6_sunbrowner.stl", "Disk Tray (Type D6)", "Synology D6 3.5/2.5 Hard Drive Tray by sunbrowner (STL)"),
    ("7018439", 0, "Holder_Type_C_johnny.stl", "Disk Holder (Type C)", "Disk holder Synology 2.5in, Type C by JohnnyAdams2024 (STL)"),
    ("1456350", 0, "Holder_Type_C_bender.stl", "Disk Holder (Type C)", "2.5in Adapter for Synology DS Disk Stations (Type C) by Bender2k (STL)"),
    ("4677567", 0, "Push_Lock_Latch_yujung.stl", "Latch (D5/D6/D8/D9)", "Synology push lock door latch by yujungchang (STL)"),
]

GQL_URL = "https://api.printables.com/graphql/"

def gql_request(query: str, variables: dict) -> dict:
    req = urllib.request.Request(
        GQL_URL,
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))

def download_all():
    m_dl = """
    mutation GetDownloadLink($id: ID!, $modelId: ID!, $fileType: DownloadFileTypeEnum!) {
      getDownloadLink(id: $id, printId: $modelId, fileType: $fileType, source: model_detail) {
        ok
        output { link }
      }
    }
    """
    manifest = []
    for model_id, file_id, ftype, local_name, tray_type, desc in PRINTABLES_FILES:
        dest = GT_DIR / local_name
        if not dest.exists():
            res = gql_request(m_dl, {"id": file_id, "modelId": model_id, "fileType": ftype})
            link = res.get("data", {}).get("getDownloadLink", {}).get("output", {}).get("link")
            if link:
                print(f"Downloading {local_name} from Printables...")
                req = urllib.request.Request(link, headers={"User-Agent": UA})
                data = urllib.request.urlopen(req, timeout=30).read()
                dest.write_bytes(data)
        if dest.exists():
            manifest.append({
                "filename": local_name,
                "tray_type": tray_type,
                "source": f"https://www.printables.com/model/{model_id}",
                "description": desc,
                "size_bytes": dest.stat().st_size,
            })

    # Thingiverse downloads via /v2/auth/view + /v2/things/{id}/complete
    req_tok = urllib.request.Request(
        "https://api.thingiverse.com/v2/auth/view",
        headers={"User-Agent": UA, "Origin": "https://www.thingiverse.com", "Referer": "https://www.thingiverse.com/"},
    )
    tv_token = json.loads(urllib.request.urlopen(req_tok, timeout=10).read().decode("utf-8"))["access"]

    for tid, fidx, local_name, tray_type, desc in THINGIVERSE_FILES:
        dest = GT_DIR / local_name
        if not dest.exists():
            url = f"https://api.thingiverse.com/v2/things/{tid}/complete"
            req_meta = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Authorization": f"Bearer {tv_token}",
                    "Origin": "https://www.thingiverse.com",
                    "Referer": "https://www.thingiverse.com/",
                },
            )
            meta = json.loads(urllib.request.urlopen(req_meta, timeout=15).read().decode("utf-8"))
            files = meta.get("zip_data", {}).get("files", [])
            if fidx < len(files):
                furl = files[fidx]["url"]
                print(f"Downloading {local_name} from {furl}...")
                data = urllib.request.urlopen(urllib.request.Request(furl, headers={"User-Agent": UA}), timeout=30).read()
                dest.write_bytes(data)
                print(f"  Saved {dest} ({len(data)} bytes)")
        if dest.exists():
            manifest.append({
                "filename": local_name,
                "tray_type": tray_type,
                "source": f"https://www.thingiverse.com/thing:{tid}",
                "description": desc,
                "size_bytes": dest.stat().st_size,
            })

    (GT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Total ground-truth files ready: {len(manifest)}")

    # Also download all 29 official Synology 2D reference renders
    trays_path = ROOT / "data" / "synology_trays.json"
    if trays_path.exists():
        trays_data = json.loads(trays_path.read_text())["trays"]
        for tname, tinfo in trays_data.items():
            hcl_id = tinfo.get("hcl_id")
            if hcl_id:
                safe_name = tname.replace('"', 'in').replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_")
                img_dest = IMG_DIR / f"{safe_name}_{hcl_id}.png"
                if not img_dest.exists():
                    img_url = f"https://www.synology.com/api/products/getSparePartImg/{hcl_id}"
                    try:
                        img_bytes = urllib.request.urlopen(urllib.request.Request(img_url, headers={"User-Agent": UA}), timeout=15).read()
                        img_dest.write_bytes(img_bytes)
                    except Exception as e:
                        print(f"Warning: failed to download image for {tname}: {e}")
        print(f"Reference images in {IMG_DIR}: {len(list(IMG_DIR.glob('*.png')))}")

if __name__ == "__main__":
    download_all()
