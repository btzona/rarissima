#!/usr/bin/env python3
"""Fetch and filter rare-insect / entomology research feeds into data/articles.json.

A single feed that fails (PubMed often answers with an HTML block page) is
recorded and skipped. If the run collects no articles at all, the existing
data/articles.json is left untouched and the process exits 0 so a scheduled
build keeps the last good ledger.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "articles.json"
USER_AGENT = "RarissimaBot/1.0 (+local research aggregator; respectful fetch)"
TIMEOUT = 20

FEEDS = [
    {
        "id": "nature-entomology",
        "name": "Nature (Entomology)",
        "url": "https://www.nature.com/subjects/entomology.rss",
        "trust": "high",
    },
    {
        "id": "entomology-today",
        "name": "Entomology Today (ESA)",
        "url": "https://entomologytoday.org/feed/",
        "trust": "high",
    },
    {
        "id": "wiley-sysent",
        "name": "Systematic Entomology",
        "url": "https://resjournals.onlinelibrary.wiley.com/feed/13653113/most-recent",
        "trust": "high",
    },
    {
        "id": "sciencedaily-zoology",
        "name": "ScienceDaily Zoology",
        "url": "https://www.sciencedaily.com/rss/plants_animals/zoology.xml",
        "trust": "medium",
    },
    {
        "id": "sciencedaily-animals",
        "name": "ScienceDaily Animals",
        "url": "https://www.sciencedaily.com/rss/plants_animals/animals.xml",
        "trust": "medium",
    },
    {
        "id": "sciencedaily-ecology",
        "name": "ScienceDaily Ecology",
        "url": "https://www.sciencedaily.com/rss/plants_animals/ecology.xml",
        "trust": "medium",
    },
    {
        "id": "phys-plants-animals",
        "name": "Phys.org Plants & Animals",
        "url": "https://phys.org/rss-feed/biology-news/plants-and-animals/",
        "trust": "medium",
    },
    {
        "id": "phys-ecology",
        "name": "Phys.org Ecology",
        "url": "https://phys.org/rss-feed/biology-news/ecology/",
        "trust": "medium",
    },
    {
        "id": "frontiers-eco",
        "name": "Frontiers in Ecology and Evolution",
        "url": "https://www.frontiersin.org/journals/ecology-and-evolution/rss",
        "trust": "medium",
    },
]

# Rare / obscure / taxonomic relevance (primary filter)
RARE_PATTERNS = [
    r"\brare\b",
    r"\brarer\b",
    r"\brarissima\b",
    r"\bobscure\b",
    r"\bcryptic\b",
    r"\bundescribed\b",
    r"\bnew species\b",
    r"\bnovel species\b",
    r"\bnewly (?:discovered|described|identified|found)\b",
    r"\brediscover(?:ed|y|ies)?\b",
    r"\bendangered\b",
    r"\bthreatened\b",
    r"\bextinct(?:ion)?\b",
    r"\bfirst record\b",
    r"\btype specimen\b",
    r"\btaxonom(?:y|ic|ist)\b",
    r"\bsystematic(?:s)?\b",
    r"\bphylogen(?:y|etic)\b",
    r"\bholotype\b",
    r"\bparatype\b",
    r"\bmicroendemic\b",
    r"\bendemic\b",
    r"\brelict\b",
    r"\bunseen for\b",
    r"\bafter \d+ years\b",
    r"\blost species\b",
    r"\bghost species\b",
    r"\bundescribed genus\b",
    r"\bnew genus\b",
    r"\bnew tribe\b",
    r"\brevision of\b",
    r"\brevised\b",
    r"\bspecies complex\b",
    r"\bcryptic diversity\b",
    r"\bdark taxa\b",
    r"\bhyper.?diverse\b",
]

# Must look insect / arthropod / entomology related for broader feeds
INSECT_PATTERNS = [
    r"\binsect\b",
    r"\binsects\b",
    r"\bentomolog",
    r"\bbeetle\b",
    r"\bbeetles\b",
    r"\bbutterfl",
    r"\bmoth\b",
    r"\bmoths\b",
    r"\bant\b",
    r"\bants\b",
    r"\bwasp\b",
    r"\bwasps\b",
    r"\bbee\b",
    r"\bbees\b",
    r"\bfly\b",
    r"\bflies\b",
    r"\bdragonfl",
    r"\bdamselfl",
    r"\bcicada\b",
    r"\baphid\b",
    r"\bweevil\b",
    r"\blarva\b",
    r"\blarvae\b",
    r"\barthropod",
    r"\bcoleoptera\b",
    r"\blepidoptera\b",
    r"\bhymenoptera\b",
    r"\bdiptera\b",
    r"\bhemiptera\b",
    r"\borthoptera\b",
    r"\bodonata\b",
    r"\btrichoptera\b",
    r"\bneuroptera\b",
    r"\bblattodea\b",
    r"\bmantodea\b",
    r"\bphasmida\b",
    r"\bsiphonaptera\b",
    r"\bthysanoptera\b",
    r"\bplecoptera\b",
    r"\bephemeroptera\b",
    r"\bpollinator",
    r"\bhexapod",
    r"\btermite\b",
    r"\bcockroach\b",
    r"\bgrasshopper\b",
    r"\bcricket\b",
    r"\bpraying mantis\b",
    r"\bstick insect\b",
    r"\bmayfly\b",
    r"\bstonefly\b",
    r"\bcaddisfly\b",
    r"\blacewing\b",
    r"\bflea\b",
    r"\blouse\b",
    r"\blices\b",
    r"\btrue bug\b",
    r"\bspringtail\b",
    r"\bcollembola\b",
]

# Soft demote / exclude obvious non-targets from broad feeds
EXCLUDE_PATTERNS = [
    r"\bdinosaur\b",
    r"\bbird\b",
    r"\bmammal\b",
    r"\bwhale\b",
    r"\bshark\b",
    r"\bfish\b",
    r"\breptile\b",
    r"\bamphibian\b",
    r"\bfrog\b",
    r"\bturtle\b",
    r"\bcrocodile\b",
    r"\bsnake\b",
    r"\blizard\b",
    r"\bmonkey\b",
    r"\bape\b",
    r"\bchimpanzee\b",
    r"\bgorilla\b",
    r"\belephant\b",
    r"\btiger\b",
    r"\blion\b",
    r"\bbear\b",
    r"\bwolf\b",
    r"\bdog\b",
    r"\bcat\b",
    r"\bcattle\b",
    r"\bpig\b",
    r"\bchicken\b",
    r"\bhuman genome\b",
    r"\bcovid\b",
    r"\bsars-cov\b",
    r"\binfluenza\b",
]

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rss": "http://purl.org/rss/1.0/",
}


def compile_list(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in patterns]


RARE_RE = compile_list(RARE_PATTERNS)
INSECT_RE = compile_list(INSECT_PATTERNS)
EXCLUDE_RE = compile_list(EXCLUDE_PATTERNS)

# Binomial-ish Latin names: Genus species (optional subspecies)
BINOMIAL_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+\([A-Z][a-z]+\))?\s+[a-z]{3,}(?:\s+[a-z]{3,})?)\b"
)
COMMON_FALSE_BINOMIAL = {
    "Science Daily",
    "New York",
    "United States",
    "North America",
    "South America",
    "East Asia",
    "West Africa",
    "New Guinea",
    "Costa Rica",
    "Puerto Rico",
    "Hong Kong",
    "New Zealand",
    "South Africa",
    "Open Access",
    "Early View",
    "Table Contents",
}


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def truncate(text: str, n: int = 280) -> str:
    text = text.strip()
    if len(text) <= n:
        return text
    cut = text[: n - 1].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "…"


def fetch_url(url: str) -> tuple[bytes | None, str | None]:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            return resp.read(), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def local_text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    # Prefer text+tail concatenated from element tree for nested HTML summaries
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(ET.tostring(child, encoding="unicode", method="xml"))
    if el.tail:
        parts.append(el.tail)
    return strip_html("".join(parts))


def find_text(parent: ET.Element, paths: list[str]) -> str:
    for path in paths:
        el = parent.find(path, NS)
        if el is not None:
            t = local_text(el) if list(el) else strip_html((el.text or "") + (el.tail or ""))
            if not t and el.text:
                t = strip_html(el.text)
            if t:
                return t
        # also try without namespace for common tags
        tag = path.split("}")[-1].split("/")[-1]
        for child in parent:
            if child.tag == tag or child.tag.endswith("}" + tag):
                t = strip_html("".join(child.itertext()))
                if t:
                    return t
    return ""


def parse_date(raw: str) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            s = raw.replace("Z", "+0000") if fmt.endswith("%z") and raw.endswith("Z") else raw
            if fmt.endswith("%z") and re.search(r"[+-]\d{2}:\d{2}$", s):
                s = s[:-3] + s[-2:]
            dt = datetime.strptime(s[: len(raw)], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            continue
    # ISO loose
    m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    if m:
        return f"{m.group(1)}T00:00:00+00:00"
    return None


def article_id(url: str, title: str) -> str:
    base = (url or title).strip().lower()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def score_item(title: str, summary: str, source_id: str, trust: str) -> tuple[int, bool, bool]:
    blob = f"{title} {summary}"
    rare = any(r.search(blob) for r in RARE_RE)
    insect = any(r.search(blob) for r in INSECT_RE)
    excluded = any(r.search(blob) for r in EXCLUDE_RE)

    # High-trust entomology journals: accept even without rare keywords
    specialty = source_id in {"nature-entomology", "entomology-today", "wiley-sysent"}

    score = 0
    if rare:
        score += 40
    if insect:
        score += 25
    if specialty:
        score += 20
        insect = True  # treat specialty feeds as insect-relevant
    if trust == "high":
        score += 5
    if excluded and not insect and not specialty:
        score -= 50

    # Primary rare filter pass
    is_rare = rare and (insect or specialty)
    # Fallback entomology research
    is_ento = (insect or specialty) and not (excluded and not specialty)

    return score, is_rare, is_ento


def detect_species(text: str) -> list[str]:
    found: list[str] = []
    for m in BINOMIAL_RE.finditer(text):
        name = m.group(1).strip()
        # Filter obvious non-species
        if name in COMMON_FALSE_BINOMIAL:
            continue
        words = name.split()
        if len(words) < 2:
            continue
        # Avoid "The Something", months, etc.
        if words[0] in {
            "The",
            "This",
            "These",
            "Those",
            "From",
            "With",
            "After",
            "Before",
            "During",
            "Using",
            "Based",
            "Open",
            "Early",
            "Royal",
            "Journal",
            "Nature",
            "Science",
            "Frontiers",
            "Systematic",
            "Entomology",
            "September",
            "October",
            "November",
            "December",
            "January",
            "February",
            "March",
            "April",
            "August",
            "June",
            "July",
        }:
            continue
        if name not in found:
            found.append(name)
        if len(found) >= 3:
            break
    return found


def parse_rss_items(root: ET.Element) -> list[dict]:
    items: list[dict] = []
    # RSS 2.0
    for item in root.findall("./channel/item"):
        title = find_text(item, ["title"])
        link = find_text(item, ["link"])
        if not link:
            # sometimes link is attribute-less empty and guid is url
            guid = item.find("guid")
            if guid is not None and (guid.get("isPermaLink") == "true" or (guid.text or "").startswith("http")):
                link = (guid.text or "").strip()
        summary = find_text(
            item,
            [
                "description",
                "content:encoded",
                "{http://purl.org/rss/1.0/modules/content/}encoded",
                "summary",
            ],
        )
        # dc:date or pubDate
        date_raw = find_text(item, ["pubDate", "dc:date", "{http://purl.org/dc/elements/1.1/}date", "date"])
        items.append({"title": title, "link": link, "summary": summary, "date_raw": date_raw})

    # Atom
    for entry in root.findall("./{http://www.w3.org/2005/Atom}entry") + root.findall("./entry"):
        title = find_text(entry, ["{http://www.w3.org/2005/Atom}title", "title"])
        link = ""
        for link_el in list(entry):
            if link_el.tag.endswith("link"):
                href = link_el.get("href") or ""
                rel = link_el.get("rel", "alternate")
                if href and rel in ("alternate", None, ""):
                    link = href
                    break
        if not link:
            link = find_text(entry, ["{http://www.w3.org/2005/Atom}id", "id"])
        summary = find_text(
            entry,
            [
                "{http://www.w3.org/2005/Atom}summary",
                "{http://www.w3.org/2005/Atom}content",
                "summary",
                "content",
            ],
        )
        date_raw = find_text(
            entry,
            [
                "{http://www.w3.org/2005/Atom}updated",
                "{http://www.w3.org/2005/Atom}published",
                "updated",
                "published",
            ],
        )
        items.append({"title": title, "link": link, "summary": summary, "date_raw": date_raw})

    # RDF RSS 1.0
    for item in root.findall(".//{http://purl.org/rss/1.0/}item"):
        title = find_text(item, ["{http://purl.org/rss/1.0/}title", "title"])
        link = find_text(item, ["{http://purl.org/rss/1.0/}link", "link"])
        summary = find_text(item, ["{http://purl.org/rss/1.0/}description", "description"])
        date_raw = find_text(item, ["{http://purl.org/dc/elements/1.1/}date", "date"])
        items.append({"title": title, "link": link, "summary": summary, "date_raw": date_raw})

    return items


def fetch_pubmed_items(limit: int = 20) -> tuple[list[dict], str | None]:
    """Pull recent PubMed hits for rare/cryptic/new insect species via eutils."""
    term = (
        "(new species[Title] OR rediscovered[Title] OR cryptic[Title] OR "
        "undescribed[Title] OR endangered[Title] OR \"first record\"[Title]) AND "
        "(insect OR Insecta OR Coleoptera OR Lepidoptera OR Hymenoptera OR Diptera "
        "OR Hemiptera OR Orthoptera OR Odonata OR entomology)"
    )
    search_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&term={urllib.request.quote(term)}"
        f"&retmax={limit}&retmode=xml&sort=date"
    )
    raw, err = fetch_url(search_url)
    if err or not raw:
        return [], err or "empty PubMed search"
    head = raw[:120].lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        return [], "PubMed eutils blocked or returned HTML (IP rate limit)"
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return [], f"PubMed parse: {exc}"
    ids = [el.text for el in root.findall(".//Id") if el.text]
    if not ids:
        return [], "no PubMed ids"
    # polite pause
    time.sleep(0.35)
    fetch_url_s = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        f"?db=pubmed&id={','.join(ids)}&retmode=xml"
    )
    raw2, err2 = fetch_url(fetch_url_s)
    if err2 or not raw2:
        return [], err2 or "empty PubMed summary"
    try:
        sroot = ET.fromstring(raw2)
    except ET.ParseError as exc:
        return [], f"PubMed summary parse: {exc}"

    items: list[dict] = []
    for doc in sroot.findall("./DocSum"):
        pmid = None
        title = ""
        source = ""
        pubdate = ""
        for item in doc.findall("./Item"):
            name = item.get("Name")
            if name == "PubDate":
                pubdate = (item.text or "").strip()
            elif name == "Source":
                source = (item.text or "").strip()
            elif name == "Title":
                title = strip_html(item.text or "")
            elif name == "ArticleIds":
                for sub in item.findall("./Item"):
                    if sub.get("Name") == "pubmed":
                        pmid = (sub.text or "").strip()
        if not pmid:
            id_el = doc.find("./Id")
            pmid = id_el.text if id_el is not None else None
        if not title or not pmid:
            continue
        link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        # Normalize date like "2026 Sep" or "2026 Sep 12"
        date_iso = None
        m = re.match(r"(\d{4})\s+([A-Za-z]{3})\s*(\d{1,2})?", pubdate)
        if m:
            months = {
                "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
            }
            y, mon, d = int(m.group(1)), months.get(m.group(2), 1), int(m.group(3) or 1)
            try:
                date_iso = datetime(y, mon, d, tzinfo=timezone.utc).isoformat()
            except ValueError:
                date_iso = f"{y:04d}-{mon:02d}-01T00:00:00+00:00"
        elif re.match(r"^\d{4}$", pubdate):
            date_iso = f"{pubdate}-01-01T00:00:00+00:00"
        items.append(
            {
                "title": title.rstrip("."),
                "link": link,
                "summary": f"PubMed record via {source}." if source else "PubMed record.",
                "date_raw": pubdate,
                "date": date_iso,
                "source": "PubMed",
                "source_id": "pubmed",
            }
        )
    return items, None


def write_ledger(payload: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def previous_article_count() -> int:
    """How many articles are already in data/articles.json, or 0 if unusable."""
    if not OUT.exists():
        return 0
    try:
        previous = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    articles = previous.get("articles") if isinstance(previous, dict) else None
    if isinstance(articles, list) and articles:
        return len(articles)
    return 0


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    feed_status: list[dict] = []
    collected: list[dict] = []
    seen_links: set[str] = set()

    for feed in FEEDS:
        print(f"Fetching {feed['name']} …", flush=True)
        raw, err = fetch_url(feed["url"])
        if err or not raw:
            feed_status.append({"id": feed["id"], "name": feed["name"], "ok": False, "error": err or "empty"})
            print(f"  FAIL: {err}")
            continue
        # Reject HTML landings
        head = raw[:200].lstrip().lower()
        if head.startswith(b"<!doctype") or head.startswith(b"<html"):
            feed_status.append(
                {"id": feed["id"], "name": feed["name"], "ok": False, "error": "HTML response, not RSS"}
            )
            print("  FAIL: HTML not RSS")
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            feed_status.append({"id": feed["id"], "name": feed["name"], "ok": False, "error": str(exc)})
            print(f"  FAIL parse: {exc}")
            continue

        parsed = parse_rss_items(root)
        count = 0
        for it in parsed:
            title = it["title"].strip()
            link = it["link"].strip()
            if not title or not link:
                continue
            if link in seen_links:
                continue
            summary = truncate(it["summary"], 320)
            date_iso = parse_date(it.get("date_raw") or "")
            score, is_rare, is_ento = score_item(title, summary, feed["id"], feed["trust"])
            if not is_ento and not is_rare:
                continue
            species = detect_species(f"{title} {summary}")
            article = {
                "id": article_id(link, title),
                "title": title,
                "link": link,
                "summary": summary,
                "source": feed["name"],
                "source_id": feed["id"],
                "date": date_iso,
                "score": score,
                "rare": is_rare,
                "species": species,
            }
            collected.append(article)
            seen_links.add(link)
            count += 1
        feed_status.append({"id": feed["id"], "name": feed["name"], "ok": True, "items": count})
        print(f"  OK: {count} kept from feed")
        time.sleep(0.25)

    # PubMed enrichment
    print("Fetching PubMed eutils …", flush=True)
    pm_items, pm_err = fetch_pubmed_items(25)
    if pm_err:
        feed_status.append({"id": "pubmed", "name": "PubMed", "ok": False, "error": pm_err})
        print(f"  FAIL: {pm_err}")
    else:
        kept = 0
        for it in pm_items:
            link = it["link"]
            if link in seen_links:
                continue
            title = it["title"]
            summary = it["summary"]
            score, is_rare, is_ento = score_item(title, summary, "pubmed", "high")
            # PubMed query already rare-filtered
            is_rare = True
            is_ento = True
            score = max(score, 50)
            species = detect_species(title)
            collected.append(
                {
                    "id": article_id(link, title),
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "source": it["source"],
                    "source_id": "pubmed",
                    "date": it.get("date"),
                    "score": score,
                    "rare": is_rare,
                    "species": species,
                }
            )
            seen_links.add(link)
            kept += 1
        feed_status.append({"id": "pubmed", "name": "PubMed", "ok": True, "items": kept})
        print(f"  OK: {kept} PubMed items")

    # Prefer rare matches; always top up with specialty/recent entomology so page is never sparse
    rare_items = [a for a in collected if a["rare"]]
    fallback = [a for a in collected if not a["rare"]]

    def sort_key(a):
        ts = 0.0
        if a.get("date"):
            try:
                ts = datetime.fromisoformat(a["date"]).timestamp()
            except ValueError:
                ts = 0.0
        return (-ts, -a["score"])

    rare_items.sort(key=sort_key)
    fallback.sort(key=sort_key)

    selected = rare_items[:28]
    # Always add solid entomology research context from specialty feeds
    need = max(16, 36 - len(selected))
    for a in fallback:
        if len(selected) >= 36:
            break
        selected.append(a)
        need -= 1
        if need <= 0 and len(selected) >= 24:
            break
    selected = selected[:40]
    selected.sort(key=lambda a: (0 if a["rare"] else 1, sort_key(a)[0], sort_key(a)[1]))

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "site": "Rarissima",
        "subtitle": "A ledger of obscure, rare, and newly illuminated insect research",
        "updated": now,
        "article_count": len(selected),
        "rare_count": sum(1 for a in selected if a["rare"]),
        "feeds": feed_status,
        "articles": selected,
    }
    ok = sum(1 for f in feed_status if f.get("ok"))
    fail = sum(1 for f in feed_status if not f.get("ok"))
    print(f"Feeds OK: {ok}  Failed: {fail}")

    # Every feed failed, or nothing matched. Do not replace a good ledger
    # with an empty one, and do not fail the caller — Pages should keep
    # publishing the last successful snapshot.
    if not selected:
        kept = previous_article_count()
        if kept:
            print(f"No articles collected. Keeping last good {OUT} ({kept} articles).")
            return 0
        write_ledger(payload)
        print(f"No articles collected and no previous ledger. Wrote empty {OUT}.")
        return 0

    write_ledger(payload)
    print(f"\nWrote {len(selected)} articles ({payload['rare_count']} rare-tagged) → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
