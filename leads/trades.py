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
import sys
from datetime import datetime, timedelta
from pathlib import Path

from leads.violations import Property, load

# Violation code -> the trades that would be hired to fix it.
TRADES: dict[str, list[str]] = {
    "roofing":          ["X50", "X04"],
    "exterior_siding_paint": ["X19", "080A", "X18"],
    "windows_doors":    ["X72", "X07", "I03", "X83", "X02", "01A"],
    "carpentry_porch_stairs": ["X40", "X57", "I24", "I33", "X78"],
    "interior_drywall_flooring": ["I13", "I11", "I01", "I36", "K09"],
    "electrical":       ["E01", "E02", "E03", "E05", "X15", "X16", "X65", "I14", "I22", "K19"],
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


def open_jobs(p: Property, trades: set[str]) -> dict[str, str]:
    """Open violations on this property that fall in the given trades: code -> item status."""
    return {code: status for code, (_, status) in p.code_status.items()
            if status in OPEN and trades & set(CODE_TO_TRADES.get(code, []))}


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

    if p.occupancy & {"Condemned"} or any(s == "Order to Vacate" for _, s, _ in p.visits.values()):
        pts -= 3  # often headed to demolition, not repair
        why.append("condemned/vacate order (may be demo, not repair)")
    return pts, why


COLUMNS = ["score", "why", "address", "zip", "trades", "open_jobs", "job_statuses",
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
        hit_trades = sorted({t for c in jobs for t in CODE_TO_TRADES[c] if t in trades})
        rows.append({
            "score": str(pts),
            "why": "; ".join(why),
            "address": p.address,
            "zip": p.zip,
            "trades": ", ".join(hit_trades),
            "open_jobs": "; ".join(f"{c} {p.violations.get(c, '')}" for c in sorted(jobs)),
            "job_statuses": "; ".join(f"{c}: {s}" for c, s in sorted(jobs.items())),
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Contractor leads from a violations export.")
    ap.add_argument("input", type=Path, nargs="?", help="PM_SiteVisit_Violations_*.csv export")
    ap.add_argument("--trade", action="append", choices=sorted(TRADES),
                    help="trade to target (repeatable). Default: every trade, one file each")
    ap.add_argument("--zip", action="append", help="limit to a ZIP code (repeatable)")
    ap.add_argument("--single-address", action="store_true",
                    help="skip parcels with several unit addresses (apartment complexes)")
    ap.add_argument("-o", "--output", type=Path, help="CSV path (only with --trade)")
    ap.add_argument("--list-trades", action="store_true", help="show trades and their codes")
    args = ap.parse_args(argv)

    if args.list_trades:
        for t, codes in TRADES.items():
            print(f"{t:28} {' '.join(codes)}")
        return 0
    if not args.input or not args.input.exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 1

    props = load(args.input)
    if args.single_address:
        props = {k: p for k, p in props.items() if len(p.addresses) <= 1}
    if args.zip:
        props = {k: p for k, p in props.items() if p.zip in args.zip}
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
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        print(f"{name:28} {len(rows):5} leads -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
