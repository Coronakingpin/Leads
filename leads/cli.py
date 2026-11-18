"""Command line entry point: python -m leads urls.txt"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

from leads.scraper import Lead, scrape_url

SOCIAL_COLUMNS = ["facebook", "instagram", "linkedin", "twitter", "tiktok", "youtube"]
COLUMNS = ["url", "domain", "title", "description", "emails", "phones", *SOCIAL_COLUMNS,
           "pages_scanned", "error"]


def read_urls(path: Path) -> list[str]:
    urls, seen = [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line not in seen:
            seen.add(line)
            urls.append(line)
    return urls


def lead_row(lead: Lead) -> dict[str, str]:
    row = {
        "url": lead.url,
        "domain": lead.domain,
        "title": lead.title,
        "description": lead.description,
        "emails": "; ".join(sorted(lead.emails)),
        "phones": "; ".join(sorted(lead.phones)),
        "pages_scanned": str(lead.pages_scanned),
        "error": lead.error,
    }
    for name in SOCIAL_COLUMNS:
        row[name] = lead.socials.get(name, "")
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape contact leads from a list of URLs.")
    parser.add_argument("input", nargs="?", default="urls.txt", type=Path,
                        help="text file with one URL per line (default: urls.txt)")
    parser.add_argument("-o", "--output", type=Path,
                        help="CSV path (default: output/leads-<timestamp>.csv)")
    parser.add_argument("--follow", type=int, default=3,
                        help="max contact/about pages to follow per site (default: 3, 0 disables)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="seconds to wait between requests (default: 1.0)")
    parser.add_argument("--timeout", type=float, default=15.0, help="request timeout in seconds")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")

    if not args.input.exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 1
    urls = read_urls(args.input)
    if not urls:
        print(f"No URLs in {args.input}. Add one per line.", file=sys.stderr)
        return 1

    output = args.output or Path("output") / f"leads-{datetime.now():%Y%m%d-%H%M%S}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)

    found = 0
    with requests.Session() as session, output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for i, url in enumerate(urls, 1):
            if i > 1:
                time.sleep(args.delay)
            lead = scrape_url(session, url, follow_contact_pages=args.follow,
                              delay=args.delay, timeout=args.timeout)
            writer.writerow(lead_row(lead))
            f.flush()
            status = "ERROR " + lead.error if lead.error else (
                f"{len(lead.emails)} emails, {len(lead.phones)} phones")
            print(f"[{i}/{len(urls)}] {url} -> {status}")
            found += bool(lead.emails or lead.phones)

    print(f"\nDone. {found}/{len(urls)} sites had contact info. Saved to {output}")
    return 0
