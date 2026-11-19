"""Email outreach plumbing: skip-trace upload file in, cold-email campaign CSV out.

The city data has owner names and mailing addresses but no emails. The workflow:

    # 1. Make an upload file for a skip-trace service (BatchSkipTracing, REISkip, etc.)
    python -m leads.outreach skiptrace output/pm-leads.csv

    # 2. Upload output/skiptrace-upload.csv to the service, download its results CSV.

    # 3. Merge results back -> one row per email, personalized, ready for Instantly/Smartlead
    python -m leads.outreach campaign output/pm-leads.csv path/to/skiptrace-results.csv

For LLC owners, skip tracing the company name rarely works. Look the LLC up on the
Kentucky Secretary of State business search (sosbes.sos.ky.gov) and put the
manager/registered agent's name in the `contact_name` column of the landlords
CSV (or the upload file) before uploading.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from leads.postcards import display_name, items_for, nice, parse_mailing_address
from leads.trades import owner_type

UPLOAD_COLUMNS = ["First Name", "Last Name", "Company", "Mailing Address", "Mailing City",
                  "Mailing State", "Mailing Zip", "Property Address", "Property City",
                  "Property State", "Property Zip", "Owner (as recorded)", "Lead Key"]

CAMPAIGN_COLUMNS = ["email", "first_name", "last_name", "company_name", "phone", "property_address",
                    "repair_items", "repair_items_short", "other_properties", "owner_type", "lead_key"]


TRUST_WORDS = re.compile(r"\b(TRUST|TRUS|TRU|TR|REVOC\w*|LIVING|LIVIN|LIV|FAMILY|FAMIL|FAM|SUBTRUST|"
                         r"AMENDED|RESTATED|IRREVOCABLE|R)$|\b(TRUST|REVOC\w*|LIVING|FAMILY|FAM|SUBTRUST|AMENDED)\b",
                         re.I)
SUFFIXES = {"SR", "JR", "II", "III", "IV", "ETAL", "ET", "AL"}


def split_person(owner: str) -> tuple[str, str]:
    """Return (first, last). PVA usually stores people as 'Last First Middle', but family
    trusts ('Laura E Escobar Family Revoc') and couples ('Alan & Shelby Archer Living')
    are written first-name-first."""
    raw = owner.strip()
    first_name_first = bool(TRUST_WORDS.search(raw)) or bool(re.match(r"^\S+\s+&\s", raw))
    head = re.split(r"\s&\s", raw)[0] if not re.match(r"^\S+\s+&\s", raw) else raw
    parts = [p for p in re.split(r"\s+", head) if p and p != "&"]
    parts = [p for p in parts if p.upper().rstrip(".") not in SUFFIXES]
    if first_name_first:
        words = [p for p in parts if not TRUST_WORDS.fullmatch(p)]
        names = [w for w in words if len(w.rstrip(".")) > 1]
        if len(names) >= 2:
            return names[0].title(), names[-1].title()
    if len(parts) < 2:
        return "", raw.title()
    return parts[1].title(), parts[0].title()


def lead_key(mailing_address: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", mailing_address.upper())[:40]


def _group(leads: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for r in leads:
        mail = r.get("owner_mailing_address", "")
        if mail and "ADDRESS UNKNOWN" not in mail.upper() and r.get("owner_type") != "government":
            groups.setdefault(lead_key(mail), []).append(r)
    for rows in groups.values():
        rows.sort(key=lambda r: -int(r.get("score") or 0))
    return groups


def skiptrace(leads: list[dict], out: Path) -> int:
    groups = _group(leads)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=UPLOAD_COLUMNS)
        w.writeheader()
        for key, rows in groups.items():
            top = rows[0]
            mail = parse_mailing_address(top["owner_mailing_address"])
            if not mail:
                continue
            otype = top.get("owner_type") or owner_type(top["owner"])
            first, last = split_person(top["owner"]) if otype in {"individual", "estate/heirs"} else ("", "")
            m = re.search(r"\b(\d{5})\b", top.get("full_address", ""))
            w.writerow({
                "First Name": first, "Last Name": last,
                "Company": display_name(top["owner"]) if otype == "company/LLC" else "",
                "Mailing Address": " ".join(filter(None, [mail["address_line1"], mail["address_line2"]])),
                "Mailing City": mail["address_city"], "Mailing State": mail["address_state"],
                "Mailing Zip": mail["address_zip"][:5],
                "Property Address": nice(top["address"]), "Property City": "Louisville",
                "Property State": "KY", "Property Zip": m.group(1) if m else top.get("zip", ""),
                "Owner (as recorded)": top["owner"], "Lead Key": key,
            })
            n += 1
    return n


def _find_cols(header: list[str], *words: str) -> list[str]:
    return [h for h in header if all(w in h.lower() for w in words)]


def campaign(leads: list[dict], results_path: Path, out: Path) -> tuple[int, int]:
    """Join skip-trace results back to leads (by Lead Key, else mailing address) and write
    one row per email address with personalization fields."""
    groups = _group(leads)
    by_mail = {lead_key(rows[0]["owner_mailing_address"]): k for k, rows in groups.items()}
    with results_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        results = list(reader)
    email_cols = _find_cols(header, "email")
    phone_cols = [c for c in _find_cols(header, "phone") if "type" not in c.lower()]
    addr_col = next(iter(_find_cols(header, "mailing", "address")), None)
    city_col = next(iter(_find_cols(header, "mailing", "city")), None)
    state_col = next(iter(_find_cols(header, "mailing", "state")), None)
    zip_col = next(iter(_find_cols(header, "mailing", "zip")), None)
    if not email_cols:
        sys.exit(f"No email columns found in {results_path}. Columns: {header}")

    seen: set[str] = set()
    matched = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPAIGN_COLUMNS)
        w.writeheader()
        for r in results:
            key = r.get("Lead Key", "")
            if key not in groups and addr_col:
                mail = f"{r.get(addr_col, '')}, {r.get(city_col, '')}, {r.get(state_col, '')} {r.get(zip_col, '')}"
                key = by_mail.get(lead_key(mail), "")
            if key not in groups:
                continue
            matched += 1
            rows = groups[key]
            top = rows[0]
            items = items_for(top["job_statuses"])
            phone = next((r[c] for c in phone_cols if r.get(c)), "")
            for c in email_cols:
                email = (r.get(c) or "").strip().lower()
                if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email) or email in seen:
                    continue
                seen.add(email)
                w.writerow({
                    "email": email,
                    "first_name": r.get("First Name") or "",
                    "last_name": r.get("Last Name") or "",
                    "company_name": display_name(top["owner"]) if top.get("owner_type") == "company/LLC" else "",
                    "phone": phone,
                    "property_address": nice(top["address"]),
                    "repair_items": ", ".join(items[:4]),
                    "repair_items_short": items[0] if items else "repairs",
                    "other_properties": str(len(rows) - 1),
                    "owner_type": top.get("owner_type", ""),
                    "lead_key": key,
                })
    return matched, len(seen)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Skip-trace upload + email campaign export")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("skiptrace", help="write a skip-trace upload CSV")
    s1.add_argument("leads", type=Path)
    s1.add_argument("-o", "--output", type=Path, default=Path("output/skiptrace-upload.csv"))
    s2 = sub.add_parser("campaign", help="merge skip-trace results into a cold-email CSV")
    s2.add_argument("leads", type=Path)
    s2.add_argument("results", type=Path, help="CSV downloaded from the skip-trace service")
    s2.add_argument("-o", "--output", type=Path, default=Path("output/email-campaign.csv"))
    args = ap.parse_args(argv)

    with args.leads.open(encoding="utf-8") as f:
        leads = list(csv.DictReader(f))
    if args.cmd == "skiptrace":
        n = skiptrace(leads, args.output)
        print(f"{n} owners -> {args.output}. Upload it to your skip-trace service.")
    else:
        matched, emails = campaign(leads, args.results, args.output)
        print(f"{matched} skip-trace rows matched leads -> {emails} unique emails in {args.output}. "
              "Import into Instantly/Smartlead with the sequence in campaign/email-sequence.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
