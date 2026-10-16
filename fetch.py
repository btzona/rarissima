#!/usr/bin/env python3
"""Fetch and filter rare-insect / entomology research feeds into data/articles.json.

A single feed that fails (PubMed often answers with an HTML block page) is
recorded and skipped. If the run collects no articles at all, the existing
data/articles.json is left untouched and the process exits 0 so a scheduled
build keeps the last good ledger.

Successful runs merge into that ledger instead of replacing it. Europe PMC
supplies older new-species and cryptic-insect papers so the archive still
reaches back to April 2026 after the cap is applied.
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
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "articles.json"
USER_AGENT = "RarissimaBot/1.0 (+https://github.com/btzona/rarissima)"
TIMEOUT = 20
# Daily refresh merges into the file. The cap keeps the page bounded while
# reserving room for papers dated on or before April 2026.
HISTORY_CAP = 180
HISTORY_FLOOR = datetime(2026, 4, 30, tzinfo=timezone.utc)
ARCHIVE_ORDERS = (
    "Coleoptera OR Lepidoptera OR Hymenoptera OR Diptera OR Hemiptera "
    "OR Orthoptera OR Odonata OR Trichoptera OR Neuroptera OR Blattodea "
    "OR Mantodea OR Phasmida OR Insecta"
)
DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)", re.I)
ORDER_IN_TITLE_RE = re.compile(
    r"\((?:[^)]*\b)?(?:Coleoptera|Lepidoptera|Hymenoptera|Diptera|Hemiptera|"
    r"Orthoptera|Odonata|Trichoptera|Neuroptera|Blattodea|Mantodea|Phasmida|"
    r"Insecta|Strepsiptera|Mecoptera|Psocodea|Thysanoptera|Plecoptera|"
    r"Ephemeroptera|Dermaptera|Zygentoma|Phasmatodea)\b",
    re.I,
)
# Archive queries match these words in abstracts too. A fungus or mite paper
# that only mentions an insect host is not part of the ledger.
NON_INSECT_SUBJECT_RE = re.compile(
    r"\b(fungi|fungus|fungal|acari|mite|mites|arachnid|spider|spiders|"
    r"nematode|nematodes|microsporid\w*|yeast|yeasts|bacterium|bacteria|bacterial|"
    r"oomycete)\b",
    re.I,
)

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


def extract_doi(text: str) -> str | None:
    if not text:
        return None
    match = DOI_RE.search(text)
    if not match:
        return None
    return match.group(1).rstrip(".,);]").lower()


def title_key(title: str) -> str:
    text = strip_html(title).lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def canonical_keys(article: dict) -> list[str]:
    keys: list[str] = []
    doi = extract_doi(article.get("link") or "")
    if doi:
        keys.append("doi:" + doi)
    title = title_key(article.get("title") or "")
    if len(title) >= 12:
        keys.append("title:" + title)
    if not keys:
        keys.append("id:" + (article.get("id") or article.get("link") or ""))
    return keys


def article_timestamp(article: dict) -> float:
    raw = article.get("date") or ""
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return 0.0


def history_sort_key(article: dict) -> tuple:
    return (
        -article_timestamp(article),
        0 if article.get("rare") else 1,
        -(article.get("score") or 0),
    )


def publication_date(raw: str) -> str | None:
    raw = (raw or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return f"{raw}T00:00:00+00:00"
    if re.fullmatch(r"\d{4}-\d{2}", raw):
        return f"{raw}-01T00:00:00+00:00"
    if re.fullmatch(r"\d{4}", raw):
        return f"{raw}-01-01T00:00:00+00:00"
    return parse_date(raw)


def prefer_article(old: dict, new: dict) -> dict:
    """Keep the fuller record when the same paper arrives from two sources."""
    chosen = dict(old)
    if len(new.get("summary") or "") > len(old.get("summary") or ""):
        chosen["summary"] = new.get("summary") or ""
    if new.get("date") and not old.get("date"):
        chosen["date"] = new["date"]
    if new.get("rare") or old.get("rare"):
        chosen["rare"] = True
    chosen["score"] = max(int(old.get("score") or 0), int(new.get("score") or 0))
    new_doi = extract_doi(new.get("link") or "")
    old_doi = extract_doi(old.get("link") or "")
    if new_doi and not old_doi:
        chosen["link"] = f"https://doi.org/{new_doi}"
        chosen["id"] = article_id(chosen["link"], chosen.get("title") or "")
    if not chosen.get("species") and new.get("species"):
        chosen["species"] = new["species"]
    if (new.get("source") or "") and (old.get("source") in {None, "", "Europe PMC"}):
        chosen["source"] = new["source"]
        chosen["source_id"] = new.get("source_id") or chosen.get("source_id")
    return chosen


def load_previous_articles() -> list[dict]:
    if not OUT.exists():
        return []
    try:
        previous = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    articles = previous.get("articles") if isinstance(previous, dict) else None
    if not isinstance(articles, list):
        return []
    return [item for item in articles if isinstance(item, dict)]


def merge_articles(previous: list[dict], fresh: list[dict]) -> list[dict]:
    records: list[dict] = []
    index: dict[str, int] = {}

    def add(article: dict) -> None:
        keys = canonical_keys(article)
        found = next((index[key] for key in keys if key in index), None)
        if found is None:
            records.append(dict(article))
            found = len(records) - 1
        else:
            records[found] = prefer_article(records[found], article)
        for key in keys:
            index[key] = found

    for article in list(previous) + list(fresh):
        if (article.get("title") or "").strip() and str(article.get("link") or "").startswith("http"):
            add(article)
    return records


def journal_name(rec: dict) -> str:
    info = rec.get("journalInfo") or {}
    journal = info.get("journal") if isinstance(info, dict) else None
    name = ""
    if isinstance(journal, dict):
        name = journal.get("title") or journal.get("medlineAbbreviation") or ""
    name = strip_html(str(name)).strip()
    return name or "Europe PMC"


MICROBE_JOURNAL_RE = re.compile(r"microbiol|mycolog|mycobiol|parasitolog|fungal biology", re.I)


def archive_is_insect(article: dict) -> bool:
    """Europe PMC hits must describe an insect, not a microbe or mite that uses one as a host."""
    if article.get("source_id") != "europepmc":
        return True
    title = article.get("title") or ""
    if re.search(r"fungus beetles?", title, re.I):
        return True
    if NON_INSECT_SUBJECT_RE.search(title):
        return False
    # A microbiology or mycology journal is in range only when the title's
    # taxon is itself an insect order, not a yeast or bacterium cultured from one.
    if MICROBE_JOURNAL_RE.search(article.get("source") or "") and not ORDER_IN_TITLE_RE.search(title):
        return False
    if ORDER_IN_TITLE_RE.search(title) or any(pattern.search(title) for pattern in INSECT_RE):
        return True
    blob = f"{title} {article.get('summary') or ''}"
    return any(pattern.search(blob) for pattern in INSECT_RE)


def cap_history(items: list[dict]) -> list[dict]:
    """Bound the ledger without letting the shelf stop short of April 2026."""
    items = [
        item
        for item in items
        if str(item.get("link") or "").startswith("http") and archive_is_insect(item)
    ]
    items.sort(key=history_sort_key)
    if len(items) <= HISTORY_CAP:
        return items
    floor_ts = HISTORY_FLOOR.timestamp()
    early = [item for item in items if 0 < article_timestamp(item) <= floor_ts]
    early_keep = early[:36]
    kept = {id(item) for item in early_keep}
    rest = [item for item in items if id(item) not in kept]
    selected = early_keep + rest[: max(0, HISTORY_CAP - len(early_keep))]
    selected.sort(key=history_sort_key)
    return selected


def archive_month_spans() -> list[tuple[str, str]]:
    spans: list[tuple[str, str]] = []
    for month in range(1, 10):
        start = f"2026-{month:02d}-01"
        if month == 2:
            end = "2026-02-28"
        elif month in {4, 6, 9}:
            end = f"2026-{month:02d}-30"
        else:
            end = f"2026-{month:02d}-31"
        spans.append((start, end))
    spans.append(("2026-10-01", "2026-10-16"))
    return spans


def europepmc_record(rec: dict) -> dict | None:
    title = strip_html(rec.get("title") or "").strip().rstrip(".")
    if len(title) < 12:
        return None
    doi = extract_doi(rec.get("doi") or "")
    pmid = str(rec.get("pmid") or "").strip()
    if doi:
        link = f"https://doi.org/{doi}"
    elif pmid:
        link = f"https://europepmc.org/article/MED/{pmid}"
    else:
        return None
    summary = truncate(strip_html(rec.get("abstractText") or ""), 320)
    journal = journal_name(rec)
    if not summary:
        summary = journal
    date_iso = publication_date(rec.get("firstPublicationDate") or rec.get("pubYear") or "")
    score, is_rare, is_ento = score_item(title, summary, "europepmc", "high")
    blob = f"{title} {summary}".lower()
    if "new species" in blob or "sp. nov" in blob or "new genus" in blob:
        is_rare = True
        is_ento = True
    if not is_ento and not is_rare:
        return None
    return {
        "id": article_id(link, title),
        "title": title,
        "link": link,
        "summary": summary,
        "source": journal[:72],
        "source_id": "europepmc",
        "date": date_iso,
        "score": max(score, 50 if is_rare else score),
        "rare": is_rare,
        "species": detect_species(f"{title} {summary}"),
    }


def europepmc_search(query: str, page_size: int = 15) -> tuple[list[dict], str | None]:
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(
        {
            "query": query,
            "format": "json",
            "pageSize": str(page_size),
            "resultType": "core",
            "sort": "P_PDATE_D desc",
        }
    )
    raw, err = fetch_url(url)
    if err or not raw:
        return [], err or "empty Europe PMC response"
    head = raw[:160].lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        return [], "Europe PMC returned HTML"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], f"Europe PMC parse: {exc}"
    results = (payload.get("resultList") or {}).get("result") or []
    if isinstance(results, dict):
        results = [results]
    articles: list[dict] = []
    for rec in results:
        if not isinstance(rec, dict):
            continue
        article = europepmc_record(rec)
        if article:
            articles.append(article)
    return articles, None


def fetch_europepmc_archive() -> tuple[list[dict], str | None]:
    """Older new-species and cryptic insect papers, one slice per month."""
    found: list[dict] = []
    seen: set[str] = set()
    errors: list[str] = []
    orders = ARCHIVE_ORDERS
    for start, end in archive_month_spans():
        query = (
            f'TITLE:"new species" AND ({orders}) '
            f"AND FIRST_PDATE:[{start} TO {end}]"
        )
        batch, err = europepmc_search(query, page_size=12)
        label = start[:7]
        if err:
            errors.append(f"{label}: {err}")
            print(f"  FAIL {label}: {err}")
            continue
        added = 0
        for article in batch:
            if article["link"] in seen:
                continue
            seen.add(article["link"])
            found.append(article)
            added += 1
        print(f"  {label}: {added} kept")
        time.sleep(0.2)

    broad = (
        f'(TITLE:cryptic OR TITLE:undescribed OR TITLE:rediscovered OR TITLE:"new genus" '
        f'OR TITLE:"sp. nov") AND ({orders}) '
        f"AND FIRST_PDATE:[2026-01-01 TO 2026-10-16]"
    )
    batch, err = europepmc_search(broad, page_size=25)
    if err:
        errors.append(f"broader: {err}")
        print(f"  FAIL broader query: {err}")
    else:
        added = 0
        for article in batch:
            if article["link"] in seen:
                continue
            seen.add(article["link"])
            found.append(article)
            added += 1
        print(f"  broader taxonomic query: {added} kept")
    warning = "; ".join(errors[:4]) if errors else None
    return found, warning


def write_ledger(payload: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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

    print("Fetching Europe PMC archive …", flush=True)
    archive_items, archive_err = fetch_europepmc_archive()
    if archive_err and not archive_items:
        feed_status.append({"id": "europepmc", "name": "Europe PMC", "ok": False, "error": archive_err})
        print(f"  FAIL: {archive_err}")
    else:
        added = 0
        for article in archive_items:
            link = article["link"]
            if link in seen_links:
                continue
            collected.append(article)
            seen_links.add(link)
            added += 1
        status: dict = {"id": "europepmc", "name": "Europe PMC", "ok": True, "items": added}
        if archive_err:
            status["warning"] = archive_err
        feed_status.append(status)
        print(f"  OK: {added} archive items")

    previous = load_previous_articles()
    ok = sum(1 for feed in feed_status if feed.get("ok"))
    fail = sum(1 for feed in feed_status if not feed.get("ok"))
    print(f"Feeds OK: {ok}  Failed: {fail}")

    # Every source failed. Leave the last good ledger on disk.
    if not collected:
        if previous:
            print(f"No articles collected. Keeping last good {OUT} ({len(previous)} articles).")
            return 0
        now = datetime.now(timezone.utc).isoformat()
        write_ledger(
            {
                "site": "Rarissima",
                "subtitle": "A ledger of obscure, rare, and newly illuminated insect research",
                "updated": now,
                "article_count": 0,
                "rare_count": 0,
                "feeds": feed_status,
                "articles": [],
            }
        )
        print(f"No articles collected and no previous ledger. Wrote empty {OUT}.")
        return 0

    selected = cap_history(merge_articles(previous, collected))
    now = datetime.now(timezone.utc).isoformat()
    dated = [article["date"] for article in selected if article.get("date")]
    payload = {
        "site": "Rarissima",
        "subtitle": "A ledger of obscure, rare, and newly illuminated insect research",
        "updated": now,
        "article_count": len(selected),
        "rare_count": sum(1 for article in selected if article.get("rare")),
        "feeds": feed_status,
        "articles": selected,
    }
    write_ledger(payload)
    span = f"{min(dated)[:10]} → {max(dated)[:10]}" if dated else "undated"
    print(
        f"\nWrote {len(selected)} articles ({payload['rare_count']} rare-tagged, {span}) → {OUT}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
