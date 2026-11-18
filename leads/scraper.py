"""Fetch pages and merge what we find into one lead per input URL."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

from leads.extract import extract

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class Lead:
    url: str
    domain: str = ""
    title: str = ""
    description: str = ""
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    socials: dict[str, str] = field(default_factory=dict)
    pages_scanned: int = 0
    error: str = ""


def fetch(session: requests.Session, url: str, timeout: float) -> str:
    resp = session.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    if "html" not in resp.headers.get("Content-Type", "html"):
        raise ValueError(f"not an HTML page ({resp.headers.get('Content-Type')})")
    return resp.text


def scrape_url(
    session: requests.Session,
    url: str,
    *,
    follow_contact_pages: int = 3,
    delay: float = 1.0,
    timeout: float = 15.0,
) -> Lead:
    if not urlparse(url).scheme:
        url = "https://" + url
    lead = Lead(url=url, domain=urlparse(url).netloc.lower().removeprefix("www."))

    try:
        html = fetch(session, url, timeout)
    except Exception as exc:  # noqa: BLE001 - record any failure on the lead
        lead.error = str(exc)
        log.warning("failed %s: %s", url, exc)
        return lead

    page = extract(html, url)
    lead.title, lead.description = page.title, page.description
    lead.emails |= page.emails
    lead.phones |= page.phones
    lead.socials.update(page.socials)
    lead.pages_scanned = 1

    for link in page.contact_links[:follow_contact_pages]:
        if link.rstrip("/") == url.rstrip("/"):
            continue
        time.sleep(delay)
        try:
            sub = extract(fetch(session, link, timeout), link)
        except Exception as exc:  # noqa: BLE001
            log.info("skipped %s: %s", link, exc)
            continue
        lead.emails |= sub.emails
        lead.phones |= sub.phones
        for k, v in sub.socials.items():
            lead.socials.setdefault(k, v)
        lead.pages_scanned += 1

    return lead
