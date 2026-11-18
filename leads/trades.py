"""Contractor leads from a Louisville Metro violations export.

Finds properties where the city has ordered repairs in your trade that are
still open, and ranks them by how pressured the owner is to get them fixed
(fines, court, deadlines) and how recently the inspector was out.

    python -m leads.trades export.csv --trade roofing
    python -m leads.trades export.csv --trade roofing --trade gutters_exterior --zip 40215
    python -m leads.trades export.csv --list-trades
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from leads.louisville import OCCUPANCY_CSV, VIOLATIONS_CSV, Owners, fetch, norm_address
from leads.violations import Property, load

# Violation code -> the trades that would be hired to fix it.
TRADES: dict[str, list[str]] = {
    "roofing":          ["X50", "X04"],
    "exterior_siding_paint": ["X19", "080A", "X18"],
    "windows_doors":    ["X72", "X07", "I03", "X83", "X02", "01A"],
    "carpentry_porch_stairs": ["X40", "X57", "I24", "I33", "X78"],
    "interior_drywall_flooring": ["I13", "I11", "I01", "I36", "K09"],
    "electrical":       ["E01", "E02", "E03", "E05", "X15", "X16", "X65", "I14", "K19"],
    "smoke_detectors":  ["I22"],
    "plumbing":         ["P01", "P03", "K10", "K11", "K14", "T05", "T13", "T18", "T22", "T30",
                         "T01", "M67", "X68"],
    "hvac":             ["M23", "M32", "M46", "M51", "M99", "M100", "M02", "K06", "I34"],
    "cleanup_junk_lawn": ["02A", "X84", "X67", "X48", "I18", "ML1"],
    "tree":             ["X90"],
    "concrete_paving":  ["X13", "X38"],
    "drainage":         ["X47", "X68"],
    "pest_control":     ["I17", "07A"],
    "demolition":       ["X94", "C01"],
    "appliances":       ["K02", "K03", "K18", "K21"],
}

# Bundles of trades for a type of business. Each lists the codes it takes on.
# property_maintenance = handyman / make-ready work that doesn't need a licensed
# electrician, plumber, HVAC or roofing contractor.
PROFILES: dict[str, list[str]] = {
    "property_maintenance": [
        # cleanup, junk, lawn, nuisance
        "02A", "X84", "X67", "X48", "I18", "ML1",
        # exterior surfaces, paint, graffiti, house numbers, awnings
        "X19", "080A", "X69", "X04",
        # windows, doors, boarding up
        "X72", "X07", "I03", "X83", "X02", "01A",
        # porches, steps, rails, fences, gates
        "X40", "X57", "I24", "X78",
        # interior walls, ceilings, floors, cabinets
        "I13", "I11", "K09",
        # fixture-level plumbing: sinks, faucets, drains, toilets, tubs
        "K10", "K11", "K14", "T05", "T22", "T30", "T13", "T18",
        # smoke detectors, appliance swaps
        "I22", "K02", "K18",
    ],
}

# Item statuses that mean the work is still not done.
OPEN = {"No Compliance", "Not Due", "New Violation", "Partial Compliance", "No Entry",
        "Citation - Referral", "Citation", "Citation - Emergency Referral", "Citation 1",
        "Citation 2", "Citation 3 or More", "In Court", "In Hearing"}
# Statuses where the owner is already being fined or taken to court.
PRESSURE = {"Citation - Referral", "Citation", "Citation - Emergency Referral", "Citation 1",
            "Citation 2", "Citation 3 or More", "In Court", "In Hearing"}

CODE_TO_TRADES: dict[str, list[str]] = {}
for _trade, _codes in TRADES.items():
    for _c in _codes:
        CODE_TO_TRADES.setdefault(_c, []).append(_trade)
CODE_TO_PROFILES: dict[str, list[str]] = {}
for _profile, _codes in PROFILES.items():
    for _c in _codes:
        CODE_TO_PROFILES.setdefault(_c, []).append(_profile)

RENTAL_CODES = {"R01"}   # cited for not registering a rental -> owner is a landlord


GOVERNMENT = re.compile(r"LOUISVILLE METRO|LOUISVILLE/JEFFERSON|HOUSING AUTHORITY|LANDBANK|LAND BANK|"
                        r"COMMONWEALTH OF|UNITED STATES|BOARD OF EDUCATION|JEFFERSON COUNTY|"
                        r"CITY OF |URBAN RENEWAL", re.I)
COMPANY = re.compile(r"\b(LLC|L L C|INC|CORP|CORPORATION|LP|LLP|LTD|TRUST|TRUSTEE|PROPERTIES|PROPERTY|"
                     r"HOLDINGS|INVESTMENTS?|REALTY|RENTALS?|HOMES|COMPANY|CO|PARTNERS|PARTNERSHIP|"
                     r"GROUP|BANK|CHURCH|MINISTRIES|ASSOCIATION|ASSN|MANAGEMENT|MGMT|"
                     r"VENTURES|CAPITAL|ENTERPRISES|DEVELOPMENT|APARTMENTS|MULTIFAMILY|HOUSING|VILLAGE|"
                     r"ESTATES|TOWNHOMES|HOLDING|FUND|SFR|BORROWER|OWNER|ASSETS?|RESIDENTIAL|"
                     r"REAL ESTATE|LEGACY|LIMITED|COMMUNITY|FOUNDATION|SOLUTIONS|SERVICES|"
                     r"INVESTORS|REVITALIZATION|LAND|PLACE)\b|\d", re.I)
ESTATE = re.compile(r"\b(HEIRS|ESTATE|DEVISEES|DECEASED)\b", re.I)


def owner_type(owner: str) -> str:
    if not owner:
        return ""
    if GOVERNMENT.search(owner):
        return "government"
    if COMPANY.search(owner):        # before ESTATE so "Real Estate Investments" is a company
        return "company/LLC"
    if ESTATE.search(owner):
        return "estate/heirs"
    return "individual"


def is_absentee(p: Property) -> bool:
    """Owner's mailing address is somewhere other than the property -> landlord/investor."""
    if not p.owner_address:
        return False
    owner = norm_address(p.owner_address)
    here = norm_address(p.address)
    if owner.startswith(("PO BOX", "P O BOX")):
        return True
    return not (owner == here or owner.startswith(here + " ") or here.startswith(owner + " "))


def is_rental(p: Property) -> bool:
    return bool(RENTAL_CODES & set(p.code_status)) or is_absentee(p)


def open_jobs(p: Property, trades: set[str]) -> dict[str, str]:
    """Open violations on this property that fall in the given trades: code -> item status."""
    return {code: status for code, (_, status) in p.code_status.items()
            if status in OPEN
            and trades & set(CODE_TO_TRADES.get(code, []) + CODE_TO_PROFILES.get(code, []))}


def job_score(p: Property, jobs: dict[str, str], today: datetime) -> tuple[int, list[str]]:
    pts, why = 0, []
    pts += 3 * len(jobs)
    why.append(f"{len(jobs)} open job item(s)")

    pressured = [c for c, s in jobs.items() if s in PRESSURE]
    if pressured:
        pts += 3 * len(pressured)
        why.append(f"{len(pressured)} already cited/in court")
    if any(s in {"New Violation", "Not Due"} for s in jobs.values()):
        pts += 2
        why.append("fresh notice, deadline running")

    fines = sum(a for _, _, a in p.visits.values())
    if fines:
        pts += min(int(fines // 500) + 1, 5)
        why.append(f"${fines:,.0f} in fines")

    dates = [d for d, _, _ in p.visits.values() if d]
    if dates and today - max(dates) <= timedelta(days=14):
        pts += 2
        why.append("inspected in last 14 days")

    if is_rental(p):
        pts += 3
        why.append("landlord/absentee owner (repeat work)")
    if owner_type(p.owner) == "company/LLC":
        pts += 1
        why.append("owned by a company")
    if len(p.addresses) > 1:
        pts += 2
        why.append(f"{len(p.addresses)} units on parcel")

    if p.occupancy & {"Condemned"} or any(s == "Order to Vacate" for _, s, _ in p.visits.values()):
        pts -= 3  # often headed to demolition, not repair
        why.append("condemned/vacate order (may be demo, not repair)")
    return pts, why


COLUMNS = ["score", "why", "address", "zip", "owner", "owner_type", "owner_mailing_address",
           "absentee_owner", "trades", "open_jobs", "job_statuses", "rental",
           "occupancy", "latest_case_status", "latest_visit", "fines_total",
           "addresses_on_parcel", "parcel_id", "full_address", "council_district",
           "latitude", "longitude"]


def build(props: dict[str, Property], trades: set[str], today: datetime) -> list[dict[str, str]]:
    rows = []
    for p in props.values():
        jobs = open_jobs(p, trades)
        if not jobs:
            continue
        dated = [v for v in p.visits.values() if v[0]]
        latest = max(dated, key=lambda v: v[0]) if dated else (None, "", 0.0)
        if latest[1] == "Closed":
            continue
        pts, why = job_score(p, jobs, today)
        hit_trades = sorted({t for c in jobs for t in CODE_TO_TRADES.get(c, [])})
        rows.append({
            "score": str(pts),
            "why": "; ".join(why),
            "address": p.address,
            "zip": p.zip,
            "owner": p.owner,
            "owner_type": owner_type(p.owner),
            "owner_mailing_address": p.owner_address,
            "absentee_owner": "yes" if is_absentee(p) else "",
            "trades": ", ".join(hit_trades),
            "open_jobs": "; ".join(f"{c} {p.violations.get(c, '')}" for c in sorted(jobs)),
            "job_statuses": "; ".join(f"{c}: {s}" for c, s in sorted(jobs.items())),
            "rental": "yes" if is_rental(p) else "",
            "occupancy": "; ".join(sorted(p.occupancy)),
            "latest_case_status": latest[1],
            "latest_visit": latest[0].strftime("%Y-%m-%d") if latest[0] else "",
            "fines_total": f"{sum(a for _, _, a in p.visits.values()):.0f}",
            "addresses_on_parcel": str(len(p.addresses)),
            "parcel_id": p.parcel_id,
            "full_address": p.full_address,
            "council_district": p.council_district,
            "latitude": p.latitude,
            "longitude": p.longitude,
        })
    # Highest score first; ties go to the most recent inspection.
    rows.sort(key=lambda r: r["address"])
    rows.sort(key=lambda r: r["latest_visit"], reverse=True)
    rows.sort(key=lambda r: int(r["score"]), reverse=True)
    return rows


OWNER_COLUMNS = ["owner_names", "owner_type", "owner_mailing_address", "properties",
                 "open_job_items", "total_score", "fines_total", "zips", "addresses"]


def landlords(rows: list[dict[str, str]], min_properties: int = 2) -> list[dict[str, str]]:
    """Group leads by who you'd actually pitch: same mailing address = same operator,
    even across differently named LLCs. Falls back to owner name when there's no address."""
    groups: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        if not r["owner"] or r["owner_type"] == "government":
            continue
        mail = r["owner_mailing_address"]
        known = mail and "ADDRESS UNKNOWN" not in mail.upper()
        key = norm_address(mail) + "|" + mail[-10:] if known else r["owner"].upper()
        groups.setdefault(key, []).append(r)
    out = []
    for props in groups.values():
        if len(props) < min_properties:
            continue
        names = sorted({r["owner"] for r in props}, key=lambda n: (n.upper(), n.isupper(), n))
        first: dict[str, str] = {}
        for n in names:
            first.setdefault(n.upper(), n)
        names = list(first.values())
        out.append({
            "owner_names": "; ".join(names),
            "owner_type": ", ".join(sorted({r["owner_type"] for r in props})),
            "owner_mailing_address": props[0]["owner_mailing_address"],
            "properties": str(len(props)),
            "open_job_items": str(sum(len(r["job_statuses"].split("; ")) for r in props)),
            "total_score": str(sum(int(r["score"]) for r in props)),
            "fines_total": str(sum(int(r["fines_total"]) for r in props)),
            "zips": ", ".join(sorted({r["zip"] for r in props})),
            "addresses": "; ".join(r["address"] for r in props),
        })
    out.sort(key=lambda r: (-int(r["properties"]), -int(r["total_score"])))
    return out


def _write(rows: list[dict[str, str]], columns: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Contractor leads from a violations export.")
    ap.add_argument("input", type=Path, nargs="?", default=VIOLATIONS_CSV,
                    help=f"violations CSV (default: {VIOLATIONS_CSV}, from `python -m leads.louisville fetch`)")
    ap.add_argument("--fetch", action="store_true", help="download fresh data from the city first")
    ap.add_argument("--owners", type=Path, default=OCCUPANCY_CSV, help="owner data CSV")
    ap.add_argument("--include-government", action="store_true",
                    help="keep properties owned by Metro, Housing Authority, Landbank, etc.")
    ap.add_argument("--trade", action="append", choices=sorted(TRADES) + sorted(PROFILES),
                    help="trade or profile to target (repeatable). Default: every trade, one file each")
    ap.add_argument("--rentals-only", action="store_true", help="only properties flagged as rentals")
    ap.add_argument("--zip", action="append", help="limit to a ZIP code (repeatable)")
    ap.add_argument("--single-address", action="store_true",
                    help="skip parcels with several unit addresses (apartment complexes)")
    ap.add_argument("-o", "--output", type=Path, help="CSV path (only with --trade)")
    ap.add_argument("--list-trades", action="store_true", help="show trades and their codes")
    args = ap.parse_args(argv)

    if args.list_trades:
        for t, codes in {**TRADES, **PROFILES}.items():
            print(f"{t:28} {' '.join(codes)}")
        return 0
    if args.fetch:
        fetch()
    if not args.input.exists():
        print(f"Input file not found: {args.input}. Run with --fetch.", file=sys.stderr)
        return 1

    props = load(args.input)
    if args.owners.exists():
        owners = Owners(args.owners)
        for p in props.values():
            p.owner, p.owner_address = owners.lookup(p.cases, p.address)
    else:
        print(f"No owner data at {args.owners}; run with --fetch to add owners.", file=sys.stderr)
    if not args.include_government:
        props = {k: p for k, p in props.items() if owner_type(p.owner) != "government"}
    if args.single_address:
        props = {k: p for k, p in props.items() if len(p.addresses) <= 1}
    if args.zip:
        props = {k: p for k, p in props.items() if p.zip in args.zip}
    if args.rentals_only:
        props = {k: p for k, p in props.items() if is_rental(p)}
    dates = [d for p in props.values() for d, _, _ in p.visits.values() if d]
    today = max(dates) if dates else datetime.now()   # score recency against the export, not the clock

    stamp = f"{datetime.now():%Y%m%d}"
    if args.trade:
        groups = {"-".join(args.trade): set(args.trade)}
    else:
        groups = {t: {t} for t in TRADES}

    for name, trades in groups.items():
        rows = build(props, trades, today)
        out = (args.output if args.output and args.trade
               else Path("output") / "trades" / f"{name}-leads-{stamp}.csv")
        _write(rows, COLUMNS, out)
        print(f"{name:28} {len(rows):5} leads -> {out}")
        if args.trade:
            owners_out = out.with_name(out.stem + "-landlords.csv")
            lords = landlords(rows)
            _write(lords, OWNER_COLUMNS, owners_out)
            print(f"{'  owners with 2+ properties':28} {len(lords):5}       -> {owners_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
