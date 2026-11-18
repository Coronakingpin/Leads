"""Mail personalized postcards to property owners through Lob (lob.com).

One postcard per owner mailing address, naming their property and the specific
items Metro cited, so it reads as relevant, not junk mail.

    # 1. Preview: writes output/postcards-preview.csv + an HTML proof, sends nothing
    python -m leads.postcards output/pm-leads.csv

    # 2. Test send with a Lob TEST key (test_...): Lob renders proofs, nothing is mailed, $0
    LOB_API_KEY=test_xxx python -m leads.postcards output/pm-leads.csv --send

    # 3. Real send with a LIVE key: prints, mails and bills your Lob account
    LOB_API_KEY=live_xxx python -m leads.postcards output/pm-leads.csv --send --live

Every sent card is logged to output/postcards-sent.csv; addresses mailed within
`skip_days` are skipped on later runs, so weekly runs don't double-mail people.
"""

from __future__ import annotations

import argparse
import csv
import html
import os
import re
import sys
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

import requests

LOB_URL = "https://api.lob.com/v1/postcards"
SENT_LOG = Path("output/postcards-sent.csv")

# Plain-English names for the city's violation codes (what the owner would hire for).
FRIENDLY = {
    "02A": "yard cleanup / trash removal", "X84": "trash cleanup", "X67": "trash storage",
    "X48": "nuisance cleanup", "I18": "interior cleanout", "ML1": "overgrown landscaping",
    "X19": "exterior surfaces / siding / paint", "080A": "graffiti removal",
    "X69": "house numbers", "X04": "awning / overhang",
    "X72": "windows", "X07": "exterior doors", "I03": "interior doors",
    "X83": "basement window guards", "X02": "basement hatch", "01A": "boarding up",
    "X40": "porch / balcony", "X57": "exterior stairs / railings", "I24": "interior stairs",
    "X78": "fence / gate / shed",
    "I13": "walls / ceilings", "I11": "flooring", "K09": "kitchen cabinets",
    "K10": "kitchen sink", "K11": "sink drain / faucet", "K14": "sink water supply",
    "T05": "tub / shower", "T22": "bathroom sink", "T30": "toilet",
    "T13": "washer drain", "T18": "laundry tub drain",
    "I22": "smoke detectors", "K02": "stove", "K18": "refrigerator",
}


def load_config(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"Missing {path}. Copy campaign.example.toml to campaign.toml and fill it in.")
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    b = cfg.get("business", {})
    if "Your Business Name" in b.get("name", "") or "123 Main St" in b.get("address_line1", ""):
        sys.exit(f"{path} still has placeholder business info. Fill it in first.")
    return cfg


def parse_mailing_address(addr: str) -> dict | None:
    """'1033 DEMONBREUN ST STE 600, NASHVILLE, TN 37203-4460' -> Lob address fields."""
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    if len(parts) < 3:
        return None
    m = re.fullmatch(r"([A-Z]{2})\s+(\d{5})(?:-?(\d{4}))?", parts[-1].upper())
    if not m:
        return None   # foreign or malformed
    street = ", ".join(parts[:-2])
    line2 = ""
    unit = re.search(r"\s+((?:STE|SUITE|UNIT|APT|#|FL|RM|BLDG)\b.*)$", street, re.I)
    if unit:
        street, line2 = street[:unit.start()], unit.group(1)
    return {
        "address_line1": nice(street),
        "address_line2": line2.upper(),
        "address_city": nice(parts[-2]),
        "address_state": m.group(1),
        "address_zip": m.group(2) + (f"-{m.group(3)}" if m.group(3) else ""),
    }


def nice(text: str) -> str:
    """Title-case an all-caps address without '2Nd St' / 'Sw 6Th' artifacts."""
    out = text.title()
    out = re.sub(r"\b(\d+)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), out)
    out = re.sub(r"\b(Ne|Nw|Se|Sw|Po)\b", lambda m: m.group(1).upper(), out)
    return out


def display_name(owner: str) -> str:
    name = owner.title()
    for word, fixed in (("Llc", "LLC"), ("Lp", "LP"), ("Llp", "LLP"), ("Ii", "II"), ("Iii", "III")):
        name = re.sub(rf"\b{word}\b", fixed, name)
    return name[:40]


def greeting(owner: str) -> str:
    """Companies by name; people get 'Hello,' since PVA stores them as 'Last First M'."""
    from leads.trades import owner_type
    return f"Hi {display_name(owner)}," if owner_type(owner) == "company/LLC" else "Hello,"


def items_for(job_statuses: str) -> list[str]:
    codes = [part.split(":")[0].strip() for part in job_statuses.split(";") if part.strip()]
    seen, out = set(), []
    for c in codes:
        name = FRIENDLY.get(c)
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def build_mailings(leads: list[dict], min_score: int = 0) -> list[dict]:
    """Group leads by owner mailing address -> one postcard each."""
    groups: dict[str, list[dict]] = {}
    for r in leads:
        if int(r.get("score") or 0) < min_score or not r.get("owner_mailing_address"):
            continue
        groups.setdefault(r["owner_mailing_address"].upper(), []).append(r)
    mailings = []
    for mail_addr, rows in groups.items():
        to = parse_mailing_address(mail_addr)
        if not to:
            continue
        rows.sort(key=lambda r: -int(r["score"]))
        top = rows[0]
        items = items_for(top["job_statuses"])
        if not items:
            continue
        mailings.append({
            "mailing_address": mail_addr,
            "to": {"name": display_name(top["owner"]), **to},
            "greeting": greeting(top["owner"]),
            "property": nice(top["address"]),
            "other_properties": len(rows) - 1,
            "items": items[:5],
            "score": sum(int(r["score"]) for r in rows),
        })
    mailings.sort(key=lambda m: -m["score"])
    return mailings


def front_html(cfg: dict) -> str:
    b = cfg["business"]
    e = html.escape
    return f"""<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:6.25in;height:4.25in;font-family:Arial,Helvetica,sans-serif;background:#12355b;color:#fff}}
.wrap{{position:absolute;top:.35in;left:.4in;right:.4in;bottom:.35in}}
h1{{font-size:30pt;line-height:1.1;margin-top:.15in}}
h2{{font-size:15pt;font-weight:normal;color:#ffd166;margin-top:.15in}}
.cta{{position:absolute;bottom:0;left:0;right:0;background:#ffd166;color:#12355b;padding:.12in .2in;
     font-size:20pt;font-weight:bold;border-radius:6px}}
.cta small{{display:block;font-size:10pt;font-weight:normal}}
</style></head><body><div class="wrap">
<h1>Got a code violation<br>on your property?</h1>
<h2>We fix it before your deadline.</h2>
<div class="cta">Call or text {e(b['phone'])}<small>{e(b['name'])} &middot; {e(b.get('tagline', ''))}</small></div>
</div></body></html>"""


def back_html(cfg: dict, m: dict) -> str:
    """Back of one card, fully rendered. Text stays in the left half: the right side is Lob's address block."""
    b = cfg["business"]
    e = html.escape
    others = m["other_properties"]
    others_txt = (f"<p>Metro also has open items on {others} of your other Louisville "
                  f"propert{'y' if others == 1 else 'ies'}.</p>") if others else ""
    items = "".join(f"<li>{e(i)}</li>" for i in m["items"])
    return f"""<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:6.25in;height:4.25in;font-family:Arial,Helvetica,sans-serif;color:#1d1d1d}}
.msg{{position:absolute;top:.3in;left:.3in;width:2.75in;font-size:9.5pt;line-height:1.35}}
.msg b{{color:#12355b}}
.msg p+p,.msg ul+p{{margin-top:.06in}}
ul{{margin:.06in 0 .06in .18in}}
.sig{{margin-top:.08in;font-size:9pt}}
.fine{{position:absolute;bottom:.2in;left:.3in;width:2.75in;font-size:6.5pt;color:#666}}
</style></head><body>
<div class="msg">
<p>{e(m["greeting"])}</p>
<p style="margin-top:.06in">Louisville Metro's recent inspection of <b>{e(m["property"])}</b> listed repairs including:</p>
<ul>{items}</ul>
{others_txt}
<p>We handle exactly this work for owners and landlords across Louisville Metro: repairs, cleanouts and make-ready turns, usually within the week.</p>
<p class="sig"><b>{e(b['name'])}</b><br>{" &middot; ".join(e(x) for x in (b['phone'], b.get('website') or b.get('email')) if x)}</p>
</div>
<div class="fine">Private business advertisement. Not affiliated with Louisville Metro Government.
Violation info is from Metro's public open data.</div>
</body></html>"""


def recently_sent(days: int) -> set[str]:
    if not SENT_LOG.exists():
        return set()
    cutoff = datetime.now() - timedelta(days=days)
    with SENT_LOG.open(encoding="utf-8") as f:
        return {r["mailing_address"] for r in csv.DictReader(f)
                if datetime.fromisoformat(r["sent_at"]) >= cutoff and r["mode"] == "live"}


def log_sent(m: dict, lob_id: str, mode: str) -> None:
    new = not SENT_LOG.exists()
    SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SENT_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["sent_at", "mode", "lob_id", "mailing_address", "name", "property"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), mode, lob_id,
                    m["mailing_address"], m["to"]["name"], m["property"]])


def send(m: dict, cfg: dict, key: str, session: requests.Session) -> str:
    b, size = cfg["business"], cfg.get("postcards", {}).get("size", "4x6")
    payload = {
        "description": f"Leads: {m['property']}"[:255],
        "to": m["to"],
        "from": {"name": b["name"], "address_line1": b["address_line1"],
                 "address_line2": b.get("address_line2", ""), "address_city": b["city"],
                 "address_state": b["state"], "address_zip": b["zip"]},
        "front": front_html(cfg),
        "back": back_html(cfg, m),
        "size": size,
        "use_type": "marketing",
    }
    resp = session.post(LOB_URL, json=payload, auth=(key, ""), timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"Lob {resp.status_code}: {resp.text[:300]}")
    return resp.json()["id"]


def write_preview(mailings: list[dict], cfg: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "postcards-preview.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "address_line1", "address_line2", "city", "state", "zip",
                    "property", "other_properties", "items"])
        for m in mailings:
            t = m["to"]
            w.writerow([t["name"], t["address_line1"], t["address_line2"], t["address_city"],
                        t["address_state"], t["address_zip"], m["property"],
                        m["other_properties"], "; ".join(m["items"])])
    if mailings:
        back = back_html(cfg, mailings[0])
        (out_dir / "postcard-proof.html").write_text(
            "<h3>Front</h3><div style='position:relative;border:1px solid #999;width:6.25in;height:4.25in'>"
            f"<iframe srcdoc=\"{html.escape(front_html(cfg))}\" style='border:0;width:100%;height:100%'></iframe></div>"
            "<h3>Back (right side is Lob's address area)</h3><div style='position:relative;border:1px solid #999;width:6.25in;height:4.25in'>"
            f"<iframe srcdoc=\"{html.escape(back)}\" style='border:0;width:100%;height:100%'></iframe></div>",
            encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Mail postcards to property owners via Lob.")
    ap.add_argument("leads", type=Path, help="leads CSV from `python -m leads.trades`")
    ap.add_argument("--config", type=Path, default=Path("campaign.toml"))
    ap.add_argument("--send", action="store_true", help="actually call Lob (default: preview only)")
    ap.add_argument("--live", action="store_true", help="allow a live_ key (real mail, real charges)")
    ap.add_argument("--limit", type=int, help="override max_per_run")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    pc = cfg.get("postcards", {})
    with args.leads.open(encoding="utf-8") as f:
        leads = list(csv.DictReader(f))
    mailings = build_mailings(leads, pc.get("min_score", 0))
    skip = recently_sent(pc.get("skip_days", 30))
    mailings = [m for m in mailings if m["mailing_address"] not in skip]
    limit = args.limit or pc.get("max_per_run", 100)
    batch = mailings[:limit]

    write_preview(batch, cfg, Path("output"))
    print(f"{len(mailings)} mailing addresses eligible ({len(skip)} skipped as recently mailed); "
          f"this run: {len(batch)}. Preview: output/postcards-preview.csv, output/postcard-proof.html")
    if not args.send:
        print("Preview only. Re-run with --send to call Lob.")
        return 0

    key = os.environ.get("LOB_API_KEY", "")
    if not key:
        sys.exit("Set LOB_API_KEY (test_... to try it free, live_... to mail for real).")
    mode = "live" if key.startswith("live_") else "test"
    if mode == "live" and not args.live:
        sys.exit("That's a LIVE key: real postcards, real charges. Add --live to confirm.")

    sent = 0
    with requests.Session() as s:
        for m in batch:
            try:
                lob_id = send(m, cfg, key, s)
            except Exception as exc:  # noqa: BLE001
                print(f"  FAILED {m['to']['name']} ({m['mailing_address']}): {exc}")
                continue
            log_sent(m, lob_id, mode)
            sent += 1
    print(f"{mode.upper()}: {sent}/{len(batch)} postcards created. Log: {SENT_LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
