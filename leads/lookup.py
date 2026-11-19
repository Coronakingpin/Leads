"""Build an email-lookup workbook: one row per owner, most valuable first, with the
exact name/address to search and one-tap search links.

    python -m leads.lookup output/pm-leads.csv            # -> output/email-lookup.xlsx

Fill in the Email / Phone columns as you find them, then export the "All owners"
sheet as CSV and run:

    python -m leads.outreach campaign output/pm-leads.csv email-lookup.csv

(the Lead Key column lets it match each row back to its properties).
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from urllib.parse import quote, quote_plus

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from leads.outreach import _group, split_person
from leads.postcards import display_name, items_for, nice, parse_mailing_address

CONTACTS = Path("campaign/landlord-contacts.csv")

COLUMNS = [
    ("Priority", 8), ("Tier", 6), ("Search as", 30), ("Owner type", 13),
    ("Email", 28), ("Phone", 15), ("Found via", 14), ("Notes", 24),
    ("Known contact", 34), ("Properties", 10), ("Top property", 24), ("Open items", 40),
    ("Landlord?", 10), ("Mailing Address", 30), ("Mailing City", 16), ("Mailing State", 8),
    ("Mailing Zip", 10), ("Owner (as recorded)", 34), ("Google", 10), ("People search 1", 14),
    ("People search 2", 14), ("KY business record", 16), ("OpenCorporates", 15),
    ("Score", 8), ("Lead Key", 12),
]

FILL_TIER = {"A": "FCE4C4", "B": "FFF4E0", "C": "FFFFFF"}


def _known_contacts() -> list[tuple[list[str], str]]:
    if not CONTACTS.exists():
        return []
    out = []
    with CONTACTS.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            names = [n.strip().upper() for n in r["owner_group"].split(";") if n.strip() and n.strip() != "..."]
            bits = [r["contact_name"], r["role"] and f"({r['role']})", r["phone"], r["email"], r["notes"]]
            out.append((names, " ".join(b for b in bits if b)))
    return out


def tier(rows: list[dict]) -> str:
    top = rows[0]
    landlord = any(r.get("absentee_owner") == "yes" or r.get("rental") == "yes" for r in rows)
    total = sum(int(r["score"]) for r in rows)
    if landlord and (len(rows) >= 2 or total >= 25):
        return "A"
    if landlord or top.get("owner_type") == "company/LLC":
        return "B"
    return "C"


def build_rows(leads: list[dict]) -> list[dict]:
    contacts = _known_contacts()
    rows_out = []
    for key, rows in _group(leads).items():
        top = rows[0]
        mail = parse_mailing_address(top["owner_mailing_address"])
        if not mail:
            continue
        otype = top.get("owner_type", "")
        owner = top["owner"]
        city_st = f"{mail['address_city']}, {mail['address_state']}"
        if otype in {"individual", "estate/heirs"}:
            first, last = split_person(owner)
            search_as = f"{first} {last}".strip()
            people1 = ("https://www.truepeoplesearch.com/results?name=" + quote(search_as)
                       + "&citystatezip=" + quote(city_st))
            people2 = ("https://www.fastpeoplesearch.com/name/"
                       + quote(f"{first}-{last}".lower().replace(" ", "-")) + "_"
                       + quote(f"{mail['address_city']}-{mail['address_state']}".lower().replace(" ", "-")))
            ky = oc = ""
            google = "https://www.google.com/search?q=" + quote_plus(f'"{search_as}" {city_st} email')
        else:
            search_as = display_name(owner)
            people1 = people2 = ""
            ky = "https://www.google.com/search?q=" + quote_plus(f'"{search_as}" site:sos.ky.gov')
            oc = "https://opencorporates.com/companies?q=" + quote_plus(search_as)
            google = "https://www.google.com/search?q=" + quote_plus(f'"{search_as}" Louisville')
        names = {r["owner"].upper() for r in rows}
        known = next((c for ns, c in contacts if names & set(ns)), "")
        items = []
        for r in rows:
            for i in items_for(r["job_statuses"]):
                if i not in items:
                    items.append(i)
        rows_out.append({
            "Tier": tier(rows),
            "Search as": search_as,
            "Owner type": {"company/LLC": "Company", "individual": "Person",
                           "estate/heirs": "Estate/heirs"}.get(otype, otype),
            "Email": "", "Phone": "", "Found via": "", "Notes": "",
            "Known contact": known,
            "Properties": len(rows),
            "Top property": nice(top["address"]),
            "Open items": ", ".join(items[:6]),
            "Landlord?": "yes" if any(r.get("absentee_owner") == "yes" or r.get("rental") == "yes"
                                      for r in rows) else "",
            "Mailing Address": " ".join(filter(None, [mail["address_line1"], mail["address_line2"]])),
            "Mailing City": mail["address_city"], "Mailing State": mail["address_state"],
            "Mailing Zip": mail["address_zip"][:5],
            "Owner (as recorded)": owner,
            "Google": google, "People search 1": people1, "People search 2": people2,
            "KY business record": ky, "OpenCorporates": oc,
            "Score": sum(int(r["score"]) for r in rows),
            "Lead Key": key,
        })
    rows_out.sort(key=lambda r: ("ABC".index(r["Tier"]), -r["Score"]))
    for i, r in enumerate(rows_out, 1):
        r["Priority"] = i
    return rows_out


LINK_COLS = {"Google", "People search 1", "People search 2", "KY business record", "OpenCorporates"}
LINK_LABEL = {"Google": "Google", "People search 1": "TruePeople", "People search 2": "FastPeople",
              "KY business record": "KY SOS", "OpenCorporates": "OpenCorp"}


def _sheet(wb: Workbook, title: str, rows: list[dict]) -> None:
    ws = wb.create_sheet(title)
    head_fill = PatternFill("solid", fgColor="121212")
    for c, (name, width) in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        ws.column_dimensions[get_column_letter(c)].width = width
    entry_fill = PatternFill("solid", fgColor="E8F1FB")
    for r_i, row in enumerate(rows, 2):
        fill = PatternFill("solid", fgColor=FILL_TIER[row["Tier"]])
        for c, (name, _) in enumerate(COLUMNS, 1):
            val = row.get(name, "")
            cell = ws.cell(row=r_i, column=c)
            if name in LINK_COLS and val:
                cell.value = LINK_LABEL[name]
                cell.hyperlink = val
                cell.font = Font(color="1155CC", underline="single")
            else:
                cell.value = val
            cell.fill = entry_fill if name in {"Email", "Phone", "Found via", "Notes"} else fill
            if name in {"Open items", "Known contact"}:
                cell.alignment = Alignment(wrap_text=False)
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{len(rows) + 1}"


def _instructions(wb: Workbook, rows: list[dict]) -> None:
    ws = wb.active
    ws.title = "Start here"
    tiers = {t: sum(1 for r in rows if r["Tier"] == t) for t in "ABC"}
    lines = [
        ("Email lookup list - Outta The Madness LLC", True),
        ("", False),
        (f"{len(rows)} owners with open handyman/make-ready violations, most valuable first.", False),
        (f"Tier A ({tiers['A']}): landlords with 2+ properties or big open lists. Start here.", False),
        (f"Tier B ({tiers['B']}): other landlords and companies.", False),
        (f"Tier C ({tiers['C']}): owners who live at the property. Postcards work better than email.", False),
        ("", False),
        ("PEOPLE (Owner type = Person)", True),
        ("1. Tap 'TruePeople' or 'FastPeople'. Match the result to the mailing address in the row.", False),
        ("2. Those sites show phones and sometimes emails. Copy into the blue Email / Phone columns.", False),
        ("3. County records store names 'Last First', so a few may be flipped - try both orders.", False),
        ("", False),
        ("COMPANIES (Owner type = Company)", True),
        ("1. Tap 'KY SOS' to find the Kentucky business record: it names the manager / registered agent.", False),
        ("2. Put that person's name in Notes, then search them on TruePeopleSearch or Google.", False),
        ("3. Tap 'Google' for a company website or property-management site with a contact email.", False),
        ("4. Out-of-state LLCs: 'OpenCorporates' shows their home-state filing and officers.", False),
        ("5. Registered agent services (CT Corp, Northwest, etc.) are NOT the owner - skip those names.", False),
        ("", False),
        ("WHEN YOU'RE DONE", True),
        ("Fill Email/Phone/Found via, export the 'All owners' sheet as CSV, and send it to Claude:", False),
        ("it merges into output/email-campaign.csv for Instantly/Smartlead (the Lead Key column matches rows).", False),
        ("Too slow by hand? Upload output/skiptrace-upload.csv to a skip-trace service (~$0.10-0.20/record).", False),
        ("", False),
        ("Use contact info only for business outreach, include an opt-out, and stop if someone says no.", False),
    ]
    for i, (text, bold) in enumerate(lines, 1):
        ws.cell(row=i, column=1, value=text).font = Font(bold=bold, size=13 if i == 1 else 11)
    ws.column_dimensions["A"].width = 110


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Email lookup workbook from a leads CSV")
    ap.add_argument("leads", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=Path("output/email-lookup.xlsx"))
    ap.add_argument("--top", type=int, default=150, help="rows on the 'Top' sheet")
    args = ap.parse_args(argv)
    with args.leads.open(encoding="utf-8") as f:
        leads = list(csv.DictReader(f))
    rows = build_rows(leads)
    wb = Workbook()
    _instructions(wb, rows)
    _sheet(wb, f"Top {args.top}", rows[:args.top])
    _sheet(wb, "All owners", rows)
    _sheet(wb, "Companies", [r for r in rows if r["Owner type"] == "Company"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.output)
    tiers = {t: sum(1 for r in rows if r["Tier"] == t) for t in "ABC"}
    print(f"{len(rows)} owners (A {tiers['A']}, B {tiers['B']}, C {tiers['C']}) -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
