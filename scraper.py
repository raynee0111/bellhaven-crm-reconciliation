"""Discover every Bellhaven community, including homepage-only announcements."""
from __future__ import annotations
import json
import re
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

BASE = "https://analyst-assessment-production.up.railway.app"
AGENT = {"User-Agent": "BellhavenAssessment/1.0 (research and reconciliation)"}
OFFERINGS = ["Short-Term Rehabilitation & Nursing", "Assisted Living", "Memory Support"]
CITY_LINE = re.compile(r"^(?P<city>.+?),\s*(?P<state>[A-Z]{2})\s+(?P<zip>\d{5}(?:-\d{4})?)$")


def get_soup(session, url):
    r = session.get(url, headers=AGENT, timeout=25)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def discover_links(session, base=BASE):
    """Fetch page 1..N; also scan homepage for separately announced communities."""
    found = set()
    listing_pages = set()
    page = 1
    while page <= 30:
        listing_url = urljoin(base, "/communities" + (f"?page={page}" if page > 1 else ""))
        soup = get_soup(session, listing_url)
        listing_pages.add(listing_url)
        for a in soup.select("a[href]"):
            href = urljoin(base, a.get("href", ""))
            parts = urlparse(href)
            if parts.netloc == urlparse(base).netloc and re.fullmatch(r"/communities/[^/]+/?", parts.path):
                found.add(href.split("?")[0].rstrip("/"))
        # Stop on last page even if the site reports a larger total than the listing.
        body = soup.get_text(" ", strip=True)
        has_next = any(a.get_text(" ", strip=True).lower().startswith("next") for a in soup.select("a[href]"))
        if not has_next:
            break
        page += 1
    home = get_soup(session, base)
    for a in home.select("a[href]"):
        href = urljoin(base, a.get("href", ""))
        parts = urlparse(href)
        if parts.netloc == urlparse(base).netloc and re.fullmatch(r"/communities/[^/]+/?", parts.path):
            found.add(href.split("?")[0].rstrip("/"))
    advertised = re.search(r"\bserve\s+(\d+)\s+communities\b", home.get_text(" ", strip=True), re.I)
    return sorted(found), {"directory_pages": sorted(listing_pages), "advertised_count": int(advertised.group(1)) if advertised else None}


def scrape_detail(session, url):
    soup = get_soup(session, url)
    h1 = soup.find("h1")
    if not h1:
        raise ValueError(f"No page title: {url}")
    lines = [s.strip() for s in soup.get_text("\n", strip=True).splitlines() if s.strip()]

    def section(label, end_labels):
        try:
            start = lines.index(label) + 1
        except ValueError:
            raise ValueError(f"Missing {label!r} on {url}")
        stops = [i for i, item in enumerate(lines[start:], start) if item in end_labels]
        return lines[start:min(stops) if stops else len(lines)]

    addr = section("Address", {"Care Offerings", "Administrator", "Phone"})
    if len(addr) < 2:
        raise ValueError(f"Incomplete address on {url}: {addr}")
    street, city_line = addr[0], addr[1]
    match = CITY_LINE.match(city_line)
    if not match:
        raise ValueError(f"Unrecognized city/state/zip on {url}: {city_line}")
    offerings_raw = " ".join(section("Care Offerings", {"Administrator", "Phone"}))
    offerings = [item for item in OFFERINGS if item.casefold() in offerings_raw.casefold()]
    if not offerings:
        raise ValueError(f"No recognized care offerings on {url}: {offerings_raw}")
    return {
        "name": h1.get_text(" ", strip=True),
        "address": street,
        "city": match.group("city"),
        "state": match.group("state"),
        "zip": match.group("zip"),
        "care_offerings": offerings,
        "source_url": url,
        "slug": urlparse(url).path.rstrip("/").split("/")[-1],
    }


def scrape_all(base=BASE):
    with requests.Session() as session:
        links, audit = discover_links(session, base)
        locations = [scrape_detail(session, url) for url in links]
    audit["found_count"] = len(locations)
    audit["complete_against_homepage"] = (audit["advertised_count"] == len(locations) if audit["advertised_count"] else None)
    return locations, audit


if __name__ == "__main__":
    data, audit = scrape_all()
    print(json.dumps({"audit": audit, "locations": data}, indent=2, ensure_ascii=False))
