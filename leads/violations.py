"""Turn a Louisville Metro property-maintenance violations export into property leads.

The ArcGIS export (PM_SiteVisit_Violations_*.csv) has one row per violation per
site visit. This rolls it up to one row per property and scores how distressed
the property looks, so the most motivated-seller / most-work-needed properties
come first.

    python -m leads.violations PM_SiteVisit_Violations.csv
    python -m leads.violations export.csv --vacant-only --min-score 8 -o output/hot.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

VACANT_STATES = {"Vacant Structure", "Vacant Lot", "Abandoned Structure", "Abandoned Lot",
                 "Abandoned", "Condemned"}

# Points per signal. Kept simple and visible so you can tune it.
SCORE = {
    "condemned": 6,
    "order_to_vacate": 6,
    "abandoned": 4,
    "vacant": 3,
    "emergency_referral": 4,
    "citation_referral": 3,
    "referred_to_court": 3,
    "cited": 2,
    "per_unresolved_violation": 1,   # No Compliance / Partial Compliance / No Entry
    "per_500_cited": 1,               # $ of citations, capped below
    "cited_cap": 5,
    "per_extra_case": 2,              # more than one open case on the parcel
    "extra_case_cap": 6,
    "unresolved_cap": 10,
}

UNRESOLVED = {"No Compliance", "Partial Compliance", "No Entry"}


@dataclass
class Property:
    parcel_id: str
    address: str = ""
    full_address: str = ""
    zip: str = ""
    council_district: str = ""
    latitude: str = ""
    longitude: str = ""
    occupancy: set[str] = field(default_factory=set)
    cases: set[str] = field(default_factory=set)
    visits: dict[str, tuple[datetime | None, str, float]] = field(default_factory=dict)
    violations: dict[str, str] = field(default_factory=dict)       # code -> short name
    unresolved: set[str] = field(default_factory=set)
    addresses: set[str] = field(default_factory=set)   # >1 means apartments/units on one parcel
    # code -> (date, item status) from the most recent visit that listed it
    code_status: dict[str, tuple[datetime | None, str]] = field(default_factory=dict)


def _date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y %I:%M:%S %p")
    except ValueError:
        return None


def _short_name(text: str) -> str:
    # "X50 - ROOF/ROOFING MATERIAL(S)/ DOWN SPOUTS/ GUTTERS  [156.0..." -> "ROOF/ROOFING MATERIAL(S)/ DOWN SPOUTS/ GUTTERS"
    name = text.split(" - ", 1)[-1]
    name = re.split(r"\s{2,}|\[|\{", name, maxsplit=1)[0]
    return name.strip(" .")[:60]


def load(path: Path) -> dict[str, Property]:
    props: dict[str, Property] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = row["PARCEL_ID"].strip() or row["PartialAddress"].strip()
            if not key:
                continue
            p = props.get(key)
            if p is None:
                full = row["FullAddress"].strip()
                m = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", full)
                p = props[key] = Property(
                    parcel_id=row["PARCEL_ID"].strip(),
                    address=row["PartialAddress"].strip(),
                    full_address=full,
                    zip=m.group(1) if m else "",
                    council_district=row["CouncilDist"].strip(),
                    latitude=row["Latitude"].strip(),
                    longitude=row["Longitude"].strip(),
                )

            p.addresses.add(row["PartialAddress"].strip())
            visit_id = row["B1_ALT_ID"].strip()
            p.cases.add(visit_id.rsplit("-", 1)[0])
            if row["OccupancyStatus"].strip():
                p.occupancy.add(row["OccupancyStatus"].strip())

            # Citation amount repeats on every violation row of a visit; count it once per visit.
            amount = float(row["CitationAmount"] or 0)
            prev = p.visits.get(visit_id)
            if prev is None or amount > prev[2]:
                p.visits[visit_id] = (_date(row["G6A_G6_COMPL_DD"]),
                                      row["G6A_G6_STATUS"].strip(), amount)

            code = row["VIOLATION_CODE"].strip()
            if code:
                p.violations.setdefault(code, _short_name(row["GUIDE_ITEM_TEXT"]))
                if row["GUIDE_ITEM_STATUS"].strip() in UNRESOLVED:
                    p.unresolved.add(code)
                when = _date(row["G6A_G6_COMPL_DD"])
                prev_status = p.code_status.get(code)
                if prev_status is None or (when and (prev_status[0] is None or when >= prev_status[0])):
                    p.code_status[code] = (when, row["GUIDE_ITEM_STATUS"].strip())
    return props


def score(p: Property) -> tuple[int, list[str]]:
    statuses = {s for _, s, _ in p.visits.values()}
    cited = sum(a for _, _, a in p.visits.values())
    pts, why = 0, []

    def add(points: int, reason: str) -> None:
        nonlocal pts
        if points:
            pts += points
            why.append(reason)

    if "Condemned" in p.occupancy:
        add(SCORE["condemned"], "condemned")
    if "Order to Vacate" in statuses:
        add(SCORE["order_to_vacate"], "order to vacate")
    if p.occupancy & {"Abandoned Structure", "Abandoned Lot", "Abandoned"}:
        add(SCORE["abandoned"], "abandoned")
    elif p.occupancy & {"Vacant Structure", "Vacant Lot"}:
        add(SCORE["vacant"], "vacant")
    if "Emergency Referral" in statuses:
        add(SCORE["emergency_referral"], "emergency referral")
    if "Citation Referral" in statuses:
        add(SCORE["citation_referral"], "citation referral")
    if "Referred to Court" in statuses:
        add(SCORE["referred_to_court"], "referred to court")
    if cited:
        add(SCORE["cited"], f"cited ${cited:,.0f}")
        add(min(int(cited // 500) * SCORE["per_500_cited"], SCORE["cited_cap"]), "citation size")
    add(min(len(p.unresolved) * SCORE["per_unresolved_violation"], SCORE["unresolved_cap"]),
        f"{len(p.unresolved)} unresolved violations")
    add(min((len(p.cases) - 1) * SCORE["per_extra_case"], SCORE["extra_case_cap"]),
        f"{len(p.cases)} cases")
    return pts, why


COLUMNS = ["score", "score_reasons", "address", "zip", "full_address", "parcel_id",
           "addresses_on_parcel", "council_district", "occupancy", "latest_status", "latest_visit", "visits",
           "cases", "violation_count", "unresolved_count", "citation_total",
           "violations", "latitude", "longitude"]


def to_row(p: Property) -> dict[str, str]:
    pts, why = score(p)
    dated = [v for v in p.visits.values() if v[0]]
    latest = max(dated, key=lambda v: v[0]) if dated else (None, "", 0.0)
    return {
        "score": str(pts),
        "score_reasons": "; ".join(why),
        "address": p.address,
        "zip": p.zip,
        "full_address": p.full_address,
        "parcel_id": p.parcel_id,
        "addresses_on_parcel": str(len(p.addresses)),
        "council_district": p.council_district,
        "occupancy": "; ".join(sorted(p.occupancy)),
        "latest_status": latest[1],
        "latest_visit": latest[0].strftime("%Y-%m-%d") if latest[0] else "",
        "visits": str(len(p.visits)),
        "cases": "; ".join(sorted(p.cases)),
        "violation_count": str(len(p.violations)),
        "unresolved_count": str(len(p.unresolved)),
        "citation_total": f"{sum(a for _, _, a in p.visits.values()):.0f}",
        "violations": "; ".join(f"{c} {n}" for c, n in sorted(p.violations.items())),
        "latitude": p.latitude,
        "longitude": p.longitude,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Roll up a violations export into scored property leads.")
    ap.add_argument("input", type=Path, help="PM_SiteVisit_Violations_*.csv export")
    ap.add_argument("-o", "--output", type=Path,
                    help="CSV path (default: output/property-leads-<timestamp>.csv)")
    ap.add_argument("--min-score", type=int, default=0, help="drop properties scoring below this")
    ap.add_argument("--vacant-only", action="store_true",
                    help="only vacant, abandoned or condemned properties")
    ap.add_argument("--include-closed", action="store_true",
                    help="keep properties whose latest visit status is Closed")
    ap.add_argument("--zip", action="append", help="limit to a ZIP code (repeatable)")
    ap.add_argument("--single-address", action="store_true",
                    help="skip parcels with several unit addresses (apartment complexes)")
    args = ap.parse_args(argv)

    if not args.input.exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 1

    props = load(args.input)
    rows = []
    for p in props.values():
        if args.vacant_only and not p.occupancy & VACANT_STATES:
            continue
        row = to_row(p)
        if not args.include_closed and row["latest_status"] == "Closed":
            continue
        if args.single_address and len(p.addresses) > 1:
            continue
        if args.zip and row["zip"] not in args.zip:
            continue
        if int(row["score"]) < args.min_score:
            continue
        rows.append(row)
    rows.sort(key=lambda r: (-int(r["score"]), -float(r["citation_total"]), r["address"]))

    out = args.output or Path("output") / f"property-leads-{datetime.now():%Y%m%d-%H%M%S}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    print(f"{len(props)} properties in export -> {len(rows)} leads written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
