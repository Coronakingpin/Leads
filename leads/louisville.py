"""Pull Louisville Metro property-maintenance data straight from the city's public
ArcGIS feature services (no expiring export links), and look up owners.

    python -m leads.louisville fetch          # downloads to data/
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://services1.arcgis.com/79kfd2K6fskCAkyg/arcgis/rest/services"
VIOLATIONS = f"{BASE}/PM_SiteVisit_Violations/FeatureServer/0"
OCCUPANCY = f"{BASE}/pm_occupancy/FeatureServer/0"   # has Owner + Owner_Address

DATA_DIR = Path("data")
VIOLATIONS_CSV = DATA_DIR / "pm_violations.csv"
OCCUPANCY_CSV = DATA_DIR / "pm_occupancy.csv"

# Date fields come back as epoch milliseconds; the city's CSV export prints them in UTC like this.
DATE_FIELDS = {"G6A_G6_COMPL_DD", "G6A_G6_STATUS_DD", "Inspection_Date"}


def _fmt_date(ms: int | None) -> str:
    if ms is None:
        return ""
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return f"{dt.month}/{dt.day}/{dt.year} {dt.strftime('%I:%M:%S %p').lstrip('0')}"


def fetch_layer(url: str, session: requests.Session | None = None, page: int = 1000) -> list[dict]:
    session = session or requests.Session()
    rows, offset = [], 0
    while True:
        resp = session.get(f"{url}/query", params={
            "where": "1=1", "outFields": "*", "returnGeometry": "false", "f": "json",
            "orderByFields": "ObjectId", "resultOffset": offset, "resultRecordCount": page,
        }, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"{url}: {data['error']}")
        batch = [f["attributes"] for f in data.get("features", [])]
        for r in batch:
            for k in DATE_FIELDS & r.keys():
                r[k] = _fmt_date(r[k])
        rows.extend(batch)
        if not batch or not data.get("exceededTransferLimit"):
            return rows
        offset += len(batch)
        time.sleep(0.2)


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: "" if v is None else v for k, v in r.items()})


def norm_address(addr: str) -> str:
    """'601 W ST CATHERINE ST 1, LOUISVILLE, KY 40203-0000' -> '601 W ST CATHERINE ST 1'"""
    street = addr.split(",")[0].upper()
    street = re.sub(r"[^A-Z0-9 ]", " ", street)
    return re.sub(r"\s+", " ", street).strip()


def _case_id(visit_or_case: str) -> str:
    """'ENF-PMNT-24-011397-3' / 'ENF-PMNT-24-011397-PM-3' -> 'ENF-PMNT-24-011397'"""
    m = re.match(r"(ENF-PMNT-\d{2}-\d+)", visit_or_case.strip())
    return m.group(1) if m else ""


class Owners:
    """Owner lookup by case number, then by street address. Latest inspection wins."""

    def __init__(self, path: Path = OCCUPANCY_CSV):
        self.by_case: dict[str, tuple[datetime, str, str]] = {}
        self.by_addr: dict[str, tuple[datetime, str, str]] = {}
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                owner = (r.get("Owner") or "").strip()
                if not owner:
                    continue
                try:
                    when = datetime.strptime(r["Inspection_Date"], "%m/%d/%Y %I:%M:%S %p")
                except (KeyError, ValueError):
                    when = datetime.min
                rec = (when, owner, (r.get("Owner_Address") or "").strip())
                for index, key in ((self.by_case, _case_id(r.get("Case_Inspection_ID", ""))),
                                   (self.by_addr, norm_address(r.get("Address", "")))):
                    if key and (key not in index or when >= index[key][0]):
                        index[key] = rec

    def lookup(self, cases: set[str], address: str) -> tuple[str, str]:
        hits = [self.by_case[c] for c in map(_case_id, cases) if c in self.by_case]
        if not hits and norm_address(address) in self.by_addr:
            hits = [self.by_addr[norm_address(address)]]
        if not hits:
            return "", ""
        _, owner, owner_addr = max(hits)
        return owner, owner_addr


def fetch(_args=None) -> int:
    with requests.Session() as s:
        for name, url, path in (("violations", VIOLATIONS, VIOLATIONS_CSV),
                                ("occupancy/owners", OCCUPANCY, OCCUPANCY_CSV)):
            rows = fetch_layer(url, s)
            write_csv(rows, path)
            print(f"{name:18} {len(rows):6} rows -> {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Louisville Metro open data helpers")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="download violations + owner data to data/")
    args = ap.parse_args(argv)
    if args.cmd == "fetch":
        return fetch(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
