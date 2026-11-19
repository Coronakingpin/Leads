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
import json
import re
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
    write_html(rows, args.output.with_suffix(".html"))
    tiers = {t: sum(1 for r in rows if r["Tier"] == t) for t in "ABC"}
    print(f"{len(rows)} owners (A {tiers['A']}, B {tiers['B']}, C {tiers['C']}) -> {args.output} (+ {args.output.with_suffix('.html')} for phones)")
    return 0



def address_links(r: dict) -> tuple[str, str]:
    street = r["Mailing Address"]
    csz = f"{r['Mailing City']}, {r['Mailing State']} {r['Mailing Zip']}".strip()
    tps = ("https://www.truepeoplesearch.com/resultaddress?streetaddress=" + quote(street)
           + "&citystatezip=" + quote(csz))
    slug = lambda s: quote(re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-"))
    fps = (f"https://www.fastpeoplesearch.com/address/{slug(street)}_"
           f"{slug(r['Mailing City'] + ' ' + r['Mailing State'] + ' ' + r['Mailing Zip'])}")
    return tps, fps


def write_html(rows: list[dict], path: Path) -> None:
    data = []
    for r in rows:
        tps_addr, fps_addr = address_links(r)
        links = []
        if r["People search 1"]:
            links += [["TruePeople (name)", r["People search 1"]], ["FastPeople (name)", r["People search 2"]]]
        links += [["TruePeople (address)", tps_addr], ["FastPeople (address)", fps_addr]]
        if r["KY business record"]:
            links += [["KY business record", r["KY business record"]], ["OpenCorporates", r["OpenCorporates"]]]
        links += [["Google", r["Google"]]]
        data.append({
            "p": r["Priority"], "t": r["Tier"], "n": r["Search as"], "o": r["Owner (as recorded)"],
            "ty": r["Owner type"], "a": r["Mailing Address"],
            "c": f"{r['Mailing City']}, {r['Mailing State']} {r['Mailing Zip']}",
            "k": r["Lead Key"], "pr": r["Properties"], "tp": r["Top property"], "i": r["Open items"],
            "kn": r["Known contact"], "l": r["Landlord?"] == "yes", "links": links,
        })
    html_doc = HTML_TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
    path.write_text(html_doc, encoding="utf-8")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Owner Email Lookup</title>
<style>
:root{--bg:#121212;--panel:#1c1c1c;--line:#2e2e2e;--fg:#f1f1f1;--muted:#a3a3a3;--accent:#f29a2e;--chip:#262626;--done:#1f3324;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
 padding:env(safe-area-inset-top,0) max(14px,env(safe-area-inset-right,0px)) 40px max(14px,env(safe-area-inset-left,0px))}
header{position:sticky;top:0;z-index:5;background:var(--bg);padding:12px 0 10px;border-bottom:1px solid var(--line)}
h1{font-size:19px;margin:0 0 2px}
.sub{color:var(--muted);font-size:13px;margin:0 0 10px}
.controls{display:flex;flex-wrap:wrap;gap:8px}
input[type=search]{flex:1 1 220px;min-width:0;background:var(--panel);border:1px solid var(--line);color:var(--fg);border-radius:10px;padding:11px 12px;font-size:16px}
.seg{display:flex;flex-wrap:wrap;gap:6px}
.seg button{background:var(--chip);color:var(--fg);border:1px solid var(--line);border-radius:999px;padding:8px 12px;font-size:14px}
.seg button[aria-pressed=true]{background:var(--accent);color:#121212;border-color:var(--accent);font-weight:600}
.count{color:var(--muted);font-size:13px;margin-top:8px}
.list{display:grid;gap:12px;margin-top:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px;display:grid;gap:8px;min-width:0}
.card.done{background:var(--done)}
.top{display:flex;gap:10px;align-items:flex-start;justify-content:space-between}
.name{font-size:17px;font-weight:700;overflow-wrap:anywhere}
.badges{display:flex;gap:6px;flex-wrap:wrap;margin-top:4px}
.b{font-size:12px;padding:2px 8px;border-radius:999px;background:var(--chip);color:var(--muted)}
.b.A{background:var(--accent);color:#121212;font-weight:700}
.b.B{background:#4a3519;color:#ffd7a3}
.rank{color:var(--muted);font-size:13px;white-space:nowrap}
.addr{font-size:15px}
.meta{color:var(--muted);font-size:13px;overflow-wrap:anywhere}
.known{font-size:13px;background:#2a2213;border:1px solid #4a3a1c;border-radius:8px;padding:6px 8px;overflow-wrap:anywhere}
.links{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.links a{display:block;text-align:center;text-decoration:none;background:#2b2b2b;color:var(--fg);border:1px solid #3a3a3a;border-radius:10px;padding:11px 8px;font-size:14px;font-weight:600}
.links a:active{background:var(--accent);color:#121212}
.row{display:flex;gap:8px;flex-wrap:wrap}
.row button{background:transparent;color:var(--accent);border:1px solid #4a3a1c;border-radius:10px;padding:9px 12px;font-size:14px}
.more{margin:16px auto;display:block;background:var(--accent);color:#121212;border:0;border-radius:10px;padding:12px 20px;font-weight:700;font-size:15px}
.tip{color:var(--muted);font-size:12.5px;margin-top:10px}
</style></head><body>
<header>
  <h1>Owner Email Lookup</h1>
  <p class="sub">Outta The Madness LLC &middot; owners with open Louisville Metro violations, best first</p>
  <div class="controls">
    <input type="search" id="q" placeholder="Search name, address, ZIP..." aria-label="Search owners">
    <div class="seg" id="tiers" role="group" aria-label="Tier">
      <button data-v="A" aria-pressed="true">Tier A</button><button data-v="B" aria-pressed="false">B</button>
      <button data-v="C" aria-pressed="false">C</button><button data-v="all" aria-pressed="false">All</button>
    </div>
    <div class="seg" id="types" role="group" aria-label="Owner type">
      <button data-v="all" aria-pressed="true">Everyone</button><button data-v="Person" aria-pressed="false">People</button>
      <button data-v="Company" aria-pressed="false">Companies</button><button data-v="todo" aria-pressed="false">Not done</button>
    </div>
  </div>
  <div class="count" id="count"></div>
</header>
<div class="list" id="list"></div>
<button class="more" id="more" hidden>Show more</button>
<p class="tip">Tier A = landlords with 2+ properties or big open lists. Match results to the mailing address shown. County records list names "Last First", so try both orders. For companies, the KY business record names the manager or registered agent: search that person next. "Done" marks are saved in this browser only.</p>
<script>
const DATA=__DATA__;
const LS='otm-lookup-done';
let done={};try{done=JSON.parse(localStorage.getItem(LS)||'{}')}catch(e){}
const save=()=>{try{localStorage.setItem(LS,JSON.stringify(done))}catch(e){}};
let tier='A',type='all',q='',shown=60;
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function filtered(){const t=q.toLowerCase();return DATA.filter(r=>(tier==='all'||r.t===tier)&&(type==='all'||(type==='todo'?!done[r.k]:r.ty===type))&&
 (!t||(r.n+' '+r.o+' '+r.a+' '+r.c+' '+r.tp+' '+r.kn).toLowerCase().includes(t)))}
function copy(text,btn){const ok=()=>{const o=btn.textContent;btn.textContent='Copied';setTimeout(()=>btn.textContent=o,1200)};
 if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(ok).catch(()=>prompt('Copy:',text))}else{prompt('Copy:',text)}}
function render(){const rows=filtered();$('#count').textContent=rows.length+' owners'+(rows.length>shown?' (showing '+shown+')':'');
 $('#list').innerHTML=rows.slice(0,shown).map((r,i)=>`<article class="card${done[r.k]?' done':''}" data-k="${esc(r.k)}">
  <div class="top"><div><div class="name">${esc(r.n)}</div><div class="badges"><span class="b ${r.t}">Tier ${r.t}</span><span class="b">${esc(r.ty)}</span>${r.l?'<span class="b">Landlord</span>':''}<span class="b">${r.pr} propert${r.pr==1?'y':'ies'}</span></div></div><span class="rank">#${r.p}</span></div>
  <div class="addr">${esc(r.a)}<br>${esc(r.c)}</div>
  <div class="meta">Recorded as: ${esc(r.o)}<br>Top property: ${esc(r.tp)}${r.i?' &middot; '+esc(r.i):''}</div>
  ${r.kn?`<div class="known">Already found: ${esc(r.kn)}</div>`:''}
  <div class="links">${r.links.map(l=>`<a href="${esc(l[1])}" target="_blank" rel="noopener">${esc(l[0])}</a>`).join('')}</div>
  <div class="row"><button data-copy="name">Copy name</button><button data-copy="addr">Copy address</button><button data-done>${done[r.k]?'Undo done':'Mark done'}</button></div>
 </article>`).join('');$('#more').hidden=rows.length<=shown}
$('#list').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;const card=b.closest('.card');const r=DATA.find(x=>x.k===card.dataset.k);
 if(b.dataset.copy==='name')copy(r.n,b);else if(b.dataset.copy==='addr')copy(r.a+', '+r.c,b);
 else if(b.hasAttribute('data-done')){if(done[r.k])delete done[r.k];else done[r.k]=1;save();render()}});
function seg(id,set){document.querySelectorAll(id+' button').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll(id+' button').forEach(x=>x.setAttribute('aria-pressed',x===b));set(b.dataset.v);shown=60;render()}))}
seg('#tiers',v=>tier=v);seg('#types',v=>type=v);
$('#q').addEventListener('input',e=>{q=e.target.value;shown=60;render()});
$('#more').addEventListener('click',()=>{shown+=60;render()});
render();
</script></body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
