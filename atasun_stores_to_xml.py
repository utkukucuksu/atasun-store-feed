#!/usr/bin/env python3
"""
Atasun Optik mağaza listesi -> XML

Kaynak : https://www.atasunoptik.com.tr/kurumsal/nerelerdeyiz_1476
Çıktı  : stores.xml (+ önceki çalışmaya göre değişiklik özeti: changes.json)

Kullanım:
    pip install requests beautifulsoup4
    python atasun_stores_to_xml.py                 # ./stores.xml yazar
    python atasun_stores_to_xml.py -o out/stores.xml

Güvenlik kontrolü: Sayfadan MIN_STORES'tan az mağaza gelirse (site hatası,
WAF engeli, şablon değişikliği vb.) mevcut XML'in üzerine YAZMAZ ve
hata koduyla çıkar — böylece bozuk bir feed yayına girmez.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.atasunoptik.com.tr/kurumsal/nerelerdeyiz_1476"
BASE_URL = "https://www.atasunoptik.com.tr"
MIN_STORES = 150          # bugün ~290 mağaza var; bunun çok altı = bir şeyler ters
TZ_TR = timezone(timedelta(hours=3))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AtasunStoreFeed/1.0)",
    "Accept-Language": "tr-TR,tr;q=0.9",
}


def clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def normalize_phone(raw: str) -> str:
    """'+90 212 727 07 37' / '0212 ...' / '90 322 ...' -> '+902127270737'. Boşsa ''."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if digits.startswith("900") and len(digits) == 13:   # "90 0256 ..." gibi hatalı giriş
        digits = "90" + digits[3:]
    if digits.startswith("90") and len(digits) == 12:
        return "+" + digits
    if digits.startswith("0") and len(digits) == 11:
        return "+9" + digits
    if len(digits) == 10:
        return "+90" + digits
    return "+" + digits if len(digits) > 10 else digits


def to_float(v: str | None) -> str:
    try:
        return f"{float(v):.7f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return ""


def parse_store(el) -> dict:
    a = el.attrs
    title_span = el.select_one(".title")
    status_el = title_span.select_one("strong") if title_span else None
    hours_text = clean(status_el.get_text()) if status_el else ""

    phone_el = el.select_one('a[data-contact-type="landline"]')
    mobile_el = el.select_one('a[data-contact-type="mobile"]')
    phone_raw = clean(phone_el.get_text()).replace("Telefon:", "").strip() if phone_el else ""
    mobile_raw = clean(mobile_el.get_text()).replace("Cep Telefonu:", "").strip() if mobile_el else ""

    addr_el = el.select_one(".address")
    address = ""
    if addr_el:
        # İlk satır sokak adresi, <br> sonrası "İlçe, İl"
        parts = [clean(p) for p in addr_el.get_text("\n").split("\n") if clean(p)]
        if parts:
            address = re.sub(r"^Adres\s*:\s*", "", parts[0]).strip()

    link_el = el.select_one('a[data-js="yol-tarifi"]')
    href = link_el.get("href", "") if link_el else ""

    name = clean(a.get("data-store-name"))
    lname = name.lower()
    if "cadde" in lname or "caddesi" in lname:
        store_type = "Cadde"
    elif "avm" in lname or "mall" in lname or "outlet" in lname:
        store_type = "AVM"
    else:
        store_type = "Diğer"

    is_closed = "kapalı" in hours_text.lower() and "pazar" not in hours_text.lower()

    return {
        "code": clean(a.get("data-store-code")),
        "name": name,
        "slug": clean(a.get("data-store-slug")),
        "url": (BASE_URL + href) if href.startswith("/") else href,
        "type": store_type,
        "status": "temporarily_closed" if is_closed else "open",
        "hours": hours_text,
        "phone": normalize_phone(phone_raw),
        "mobile": normalize_phone(mobile_raw),
        "address": address,
        "district": clean(a.get("data-town-name")),
        "district_id": clean(a.get("data-town-id")),
        "city": clean(a.get("data-city-name")),
        "city_id": clean(a.get("data-city-id")),
        "country": "TR",
        "latitude": to_float(a.get("data-xx")),
        "longitude": to_float(a.get("data-yy")),
    }


def fetch_stores() -> list[dict]:
    r = requests.get(SOURCE_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    stores = [parse_store(el) for el in soup.select('[data-js="store"][data-store-code]')]
    # Mağaza koduna göre tekilleştir (sayfa ileride tekrar eden blok içerirse)
    seen, unique = set(), []
    for s in stores:
        if s["code"] and s["code"] not in seen:
            seen.add(s["code"])
            unique.append(s)
    return unique


def build_xml(stores: list[dict], generated_at: datetime) -> bytes:
    root = ET.Element("stores", {
        "source": SOURCE_URL,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "count": str(len(stores)),
    })
    for s in stores:
        st = ET.SubElement(root, "store", {"code": s["code"]})
        for key in ("name", "slug", "url", "type", "status", "hours", "phone", "mobile", "address"):
            ET.SubElement(st, key).text = s[key]
        loc = ET.SubElement(st, "location")
        ET.SubElement(loc, "city", {"id": s["city_id"]}).text = s["city"]
        ET.SubElement(loc, "district", {"id": s["district_id"]}).text = s["district"]
        ET.SubElement(loc, "country").text = s["country"]
        ET.SubElement(loc, "latitude").text = s["latitude"]
        ET.SubElement(loc, "longitude").text = s["longitude"]
    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")


def read_previous(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return {}
    prev = {}
    for st in tree.getroot().findall("store"):
        code = st.get("code")
        prev[code] = {
            "name": st.findtext("name", ""),
            "status": st.findtext("status", ""),
            "hours": st.findtext("hours", ""),
            "phone": st.findtext("phone", ""),
            "mobile": st.findtext("mobile", ""),
            "address": st.findtext("address", ""),
            "latitude": st.findtext("location/latitude", ""),
            "longitude": st.findtext("location/longitude", ""),
        }
    return prev


def diff(prev: dict[str, dict], stores: list[dict]) -> dict:
    cur = {s["code"]: s for s in stores}
    added = [f'{c} {cur[c]["name"]}' for c in cur if c not in prev]
    removed = [f'{c} {prev[c]["name"]}' for c in prev if c not in cur]
    changed = []
    for c in cur.keys() & prev.keys():
        fields = [k for k in prev[c] if prev[c][k] != cur[c].get(k, "")]
        if fields:
            changed.append({"code": c, "name": cur[c]["name"], "fields": fields})
    return {"added": added, "removed": removed, "changed": changed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="stores.xml")
    args = ap.parse_args()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    stores = fetch_stores()
    if len(stores) < MIN_STORES:
        print(f"HATA: yalnızca {len(stores)} mağaza bulundu (< {MIN_STORES}). "
              f"Mevcut XML korunuyor.", file=sys.stderr)
        return 2

    now = datetime.now(TZ_TR)
    changes = diff(read_previous(out), stores)
    out.write_bytes(build_xml(stores, now))
    (out.parent / "changes.json").write_text(
        json.dumps({"generated_at": now.isoformat(timespec="seconds"),
                    "count": len(stores), **changes}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print(f"{len(stores)} mağaza -> {out}  "
          f"(+{len(changes['added'])} / -{len(changes['removed'])} / ~{len(changes['changed'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
