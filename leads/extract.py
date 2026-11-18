"""Pull contact details out of a page's HTML."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Phones in page text: US-style (555) 123-4567 / 555.123.4567 / +1 555 123 4567,
# or international numbers that start with + (+44 20 7946 0958).
# Kept strict on purpose: loose patterns match prices, IDs and number sequences.
PHONE_RE = re.compile(
    r"(?<![\w+])(?:"
    r"(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]\d{4}"
    r"|\+\d{1,3}(?:[\s.-]?\(?\d{1,4}\)?){2,4}"
    r")(?!\w)"
)

# Image/asset names that look like emails (e.g. logo@2x.png) are not emails.
EMAIL_JUNK_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
EMAIL_JUNK_DOMAINS = ("example.com", "sentry.io", "wixpress.com", "domain.com")

SOCIAL_DOMAINS = {
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "linkedin.com": "linkedin",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "tiktok.com": "tiktok",
    "youtube.com": "youtube",
}

CONTACT_HINTS = ("contact", "about", "team", "reach", "connect", "location")


@dataclass
class PageData:
    title: str = ""
    description: str = ""
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    socials: dict[str, str] = field(default_factory=dict)
    contact_links: list[str] = field(default_factory=list)


def _clean_email(raw: str) -> str | None:
    email = raw.strip().strip(".").lower()
    if email.endswith(EMAIL_JUNK_SUFFIXES):
        return None
    if any(email.endswith("@" + d) or email.endswith("." + d) for d in EMAIL_JUNK_DOMAINS):
        return None
    return email if EMAIL_RE.fullmatch(email) else None


def _clean_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if not 10 <= len(digits) <= 15:
        return None
    # Reject runs like 0000000000 or 1234567890 that are usually IDs, not phones.
    if len(set(digits)) <= 2 or digits in "01234567890123456789":
        return None
    return raw.strip()


def _same_site(a: str, b: str) -> bool:
    strip = lambda host: host.lower().removeprefix("www.")
    return strip(urlparse(a).netloc) == strip(urlparse(b).netloc)


def extract(html: str, base_url: str) -> PageData:
    soup = BeautifulSoup(html, "html.parser")
    data = PageData()

    if soup.title and soup.title.string:
        data.title = soup.title.string.strip()
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    if meta and meta.get("content"):
        data.description = meta["content"].strip()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        lower = href.lower()
        if lower.startswith("mailto:"):
            email = _clean_email(href[7:].split("?")[0])
            if email:
                data.emails.add(email)
            continue
        if lower.startswith("tel:"):
            phone = _clean_phone(href[4:])
            if phone:
                data.phones.add(phone)
            continue

        absolute = urljoin(base_url, href)
        host = urlparse(absolute).netloc.lower().removeprefix("www.")
        for domain, name in SOCIAL_DOMAINS.items():
            if (host == domain or host.endswith("." + domain)) and name not in data.socials:
                data.socials[name] = absolute.split("?")[0]

        text = (a.get_text(" ", strip=True) + " " + lower).lower()
        if (
            _same_site(absolute, base_url)
            and any(h in text for h in CONTACT_HINTS)
            and absolute.split("#")[0] not in data.contact_links
        ):
            data.contact_links.append(absolute.split("#")[0])

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)

    for match in EMAIL_RE.findall(text):
        email = _clean_email(match)
        if email:
            data.emails.add(email)
    for match in PHONE_RE.findall(text):
        phone = _clean_phone(match)
        if phone:
            data.phones.add(phone)

    return data
