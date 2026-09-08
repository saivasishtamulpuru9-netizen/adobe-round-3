"""
fetch_page.py — Page fetcher for the crawl-render-audit skill.

Responsibilities
----------------
1.  Check robots.txt for the URL                    → DV-16 detection
2.  GET the page; detect bot-block / WAF response   → DV-13 detection
3.  Parse key <head> fields (meta, og, twitter,
    canonical, noindex, keywords)
4.  Probe /llms.txt at domain root                  → DV-18 input
5.  Return a structured per-page dict consumed by
    checks_dv.py and the other sub-skills

Guardrails
----------
- GET / HEAD requests ONLY; no authenticated actions.
- robots.txt is checked FIRST; disallowed paths are flagged, not crawled.
- Polite crawl delay between requests (default 1 s).
- User-agent identifies this as a read-only audit bot.
"""

import re
import time
import urllib.parse
import urllib.robotparser
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ── Constants ────────────────────────────────────────────────────────────────

USER_AGENT = (
    "BrandAIAuditBot/1.0 "
    "(+https://github.com/brand-ai-audit; "
    "read-only audit; not for commercial use)"
)
TIMEOUT = 15          # seconds per request
REQUEST_DELAY = 1.2   # polite delay between page fetches

TRACKING_PARAMS: set = {
    "srsltid", "gclid", "fbclid",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "crid", "dib", "qid", "sprefix", "sr", "ref", "tag", "affiliate",
    "mc_eid", "mc_cid", "yclid", "twclid", "igshid",
}

# Headers that, when present, indicate a WAF/challenge front-end
BOT_BLOCK_RESPONSE_HEADERS: tuple = (
    "cf-mitigated",        # Cloudflare
    "x-sucuri-cache",      # Sucuri WAF
    "x-ddos-protection",
    "server-timing",       # sometimes injected by WAFs as a side-effect
)

# HTTP status codes that frequently indicate a bot-block (vs. legitimate 404)
BOT_BLOCK_STATUS_CODES: frozenset = frozenset({403, 429, 503})

# Body-text patterns that suggest a challenge/block page
BOT_BLOCK_BODY_RE = re.compile(
    r"(enable\s+javascript"
    r"|captcha"
    r"|checking\s+your\s+browser"
    r"|ddos\s+protection"
    r"|ray\s+id\s*:"
    r"|access\s+denied"
    r"|403\s+forbidden"
    r"|please\s+wait.*cloudflare"
    r"|bot\s+detection"
    r"|security\s+check"
    r"|unusual\s+traffic"
    r"|automated\s+query)",
    re.IGNORECASE,
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def strip_tracking_params(url: str) -> str:
    """Return the URL with known tracking query-parameters removed."""
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    clean_qs = {k: v for k, v in qs.items()
                if k.lower() not in TRACKING_PARAMS}
    clean_query = urllib.parse.urlencode(clean_qs, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=clean_query))


def _parse_head(soup: BeautifulSoup) -> dict:
    """Extract key <head> metadata fields into a flat dict."""

    def _meta_name(name: str) -> str:
        tag = soup.find("meta", attrs={"name": name})
        return (tag.get("content") or "").strip() if tag else ""

    def _meta_prop(prop: str) -> str:
        tag = soup.find("meta", attrs={"property": prop})
        return (tag.get("content") or "").strip() if tag else ""

    canonical_tag = soup.find("link", rel="canonical")
    canonical = (canonical_tag.get("href") or "").strip() if canonical_tag else ""

    robots_meta = _meta_name("robots")
    noindex = bool(robots_meta and "noindex" in robots_meta.lower())

    return {
        "title": (soup.title.string or "").strip() if soup.title else "",
        "meta_description": _meta_name("description"),
        "meta_keywords": _meta_name("keywords"),
        "robots_meta": robots_meta,
        "noindex": noindex,
        "canonical": canonical,
        "og_title": _meta_prop("og:title"),
        "og_description": _meta_prop("og:description"),
        "og_image": _meta_prop("og:image"),
        "twitter_title": _meta_name("twitter:title"),
        "twitter_description": _meta_name("twitter:description"),
        "twitter_image": _meta_name("twitter:image"),
        "article_published_time": _meta_prop("article:published_time"),
        "article_modified_time": _meta_prop("article:modified_time"),
    }


def _extract_body_text(soup: BeautifulSoup) -> str:
    """
    Strip boilerplate tags (nav, footer, header, script, style, noscript)
    and return collapsed plain text from the remaining body.
    """
    s = BeautifulSoup(str(soup), "html.parser")
    for tag in s(["script", "style", "nav", "footer", "header", "noscript",
                  "aside", "form"]):
        tag.decompose()
    text = s.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _is_bot_blocked(response: requests.Response) -> bool:
    """Heuristically decide whether a response is a WAF/bot-block page."""
    if response.status_code in BOT_BLOCK_STATUS_CODES:
        # 503 might be a legitimate maintenance page — also check body
        if response.status_code == 503:
            body_snippet = response.text[:3000].lower()
            return bool(BOT_BLOCK_BODY_RE.search(body_snippet))
        return True

    # Suspicious response headers
    lower_headers = {k.lower() for k in response.headers.keys()}
    for sig in BOT_BLOCK_RESPONSE_HEADERS:
        if sig in lower_headers and response.status_code in {200, 403}:
            # Header alone is not enough; check body too
            break

    # Body patterns (check first 4000 chars for speed)
    body_snippet = response.text[:4000].lower()
    return bool(BOT_BLOCK_BODY_RE.search(body_snippet)
                and response.status_code != 200)


def _extract_internal_links(soup: BeautifulSoup, base_url: str) -> list:
    """Return de-duplicated list of absolute internal hrefs."""
    parsed_base = urllib.parse.urlparse(base_url)
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        abs_href = urllib.parse.urljoin(base_url, href)
        abs_parsed = urllib.parse.urlparse(abs_href)
        # Same host only; strip fragment
        if abs_parsed.netloc == parsed_base.netloc:
            links.add(urllib.parse.urlunparse(abs_parsed._replace(fragment="")))
    return list(links)


def _extract_ldjson(soup: BeautifulSoup) -> list:
    """Return raw text of every <script type='application/ld+json'> block."""
    return [
        (tag.string or "").strip()
        for tag in soup.find_all("script", type="application/ld+json")
        if (tag.string or "").strip()
    ]


# ── robots.txt ───────────────────────────────────────────────────────────────

def check_robots(url: str) -> dict:
    """
    Fetch and parse robots.txt for the domain of *url*.

    Returns
    -------
    dict with keys:
      allowed       bool   – whether our user-agent may crawl this URL
      robots_url    str    – URL of the robots.txt that was checked
      disallow_rule str|None
      error         str|None  – only present on fetch failure
    """
    parsed = urllib.parse.urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = f"{base}/robots.txt"

    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    try:
        r = requests.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=6)
        if r.status_code == 200:
            rp.parse(r.text.splitlines())
        elif r.status_code in {401, 403}:
            # Deliberate disallow
            return {
                "robots_url": robots_url,
                "allowed": False,
                "disallow_rule": url,
            }
        else:
            # 404 or other status → allow
            return {
                "robots_url": robots_url,
                "allowed": True,
                "disallow_rule": None,
            }

        # Check both our specific agent and the wildcard agent
        allowed_specific = rp.can_fetch(USER_AGENT, url)
        allowed_wildcard = rp.can_fetch("*", url)
        allowed = allowed_specific and allowed_wildcard
        return {
            "robots_url": robots_url,
            "allowed": allowed,
            "disallow_rule": None if allowed else url,
        }
    except Exception as exc:
        # If robots.txt is unreachable (e.g. timeout), assume allowed (fail open)
        return {
            "robots_url": robots_url,
            "allowed": True,
            "disallow_rule": None,
            "error": str(exc),
        }


# ── /llms.txt probe ──────────────────────────────────────────────────────────

def probe_llms_txt(base_url: str, session: requests.Session) -> bool:
    """Return True if a non-empty /llms.txt exists at the domain root."""
    parsed = urllib.parse.urlparse(base_url)
    llms_url = f"{parsed.scheme}://{parsed.netloc}/llms.txt"
    try:
        r = session.get(llms_url, timeout=TIMEOUT, allow_redirects=True)
        return r.status_code == 200 and len(r.text.strip()) > 20
    except Exception:
        return False


# ── Session factory ───────────────────────────────────────────────────────────

def create_session() -> requests.Session:
    """Create a shared requests session with the audit user-agent."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


# ── Main fetch function ───────────────────────────────────────────────────────

def fetch_page(
    url: str,
    session: Optional[requests.Session] = None,
    delay: float = REQUEST_DELAY,
    probe_llms: bool = False,
    timeout: int = TIMEOUT,
) -> dict:
    """
    Fetch a single page and return a structured per-page dict.

    Result keys
    -----------
    url                 str         original URL requested
    clean_url           str         URL with tracking params stripped
    final_url           str         URL after redirects (if any)
    http_status         int|None
    blocked             bool        True if DV-13 (bot-block) fired
    blocked_reason      str|None    'BOT_BLOCK' | 'FETCH_ERROR' | 'ROBOTS_DISALLOWED'
    robots_disallowed   bool        True if DV-16 (robots.txt) fired
    noindex             bool
    head                dict        parsed <head> fields
    raw_html            str|None    full raw HTML (None if blocked)
    body_text           str         boilerplate-stripped plain text
    content_word_count  int
    has_raw_html        bool
    rendered_text_only  bool        True if only rendered text was available (no raw HTML)
    ldjson_blocks       list[str]   raw text of JSON-LD script blocks
    internal_links      list[str]   absolute internal hrefs
    llms_txt_present    bool        only meaningful when probe_llms=True
    error               str|None
    """
    if session is None:
        session = create_session()

    clean_url = strip_tracking_params(url)

    result: dict = {
        "url": url,
        "clean_url": clean_url,
        "final_url": clean_url,
        "http_status": None,
        "blocked": False,
        "blocked_reason": None,
        "robots_disallowed": False,
        "noindex": False,
        "head": {},
        "raw_html": None,
        "body_text": "",
        "content_word_count": 0,
        "has_raw_html": False,
        "rendered_text_only": False,
        "ldjson_blocks": [],
        "internal_links": [],
        "llms_txt_present": False,
        "error": None,
    }

    # ── Step 1: robots.txt ───────────────────────────────────────────────────
    robots_info = check_robots(clean_url)
    if not robots_info["allowed"]:
        result["robots_disallowed"] = True
        result["blocked"] = True
        result["blocked_reason"] = "ROBOTS_DISALLOWED"
        return result

    # ── Step 2: Fetch ────────────────────────────────────────────────────────
    if delay > 0:
        time.sleep(delay)

    try:
        response = session.get(clean_url, timeout=timeout, allow_redirects=True)
        result["http_status"] = response.status_code
        result["final_url"] = response.url
    except requests.RequestException as exc:
        result["error"] = str(exc)
        result["blocked"] = True
        result["blocked_reason"] = "FETCH_ERROR"
        return result

    # ── Step 3: Bot-block detection ──────────────────────────────────────────
    if _is_bot_blocked(response):
        result["blocked"] = True
        result["blocked_reason"] = "BOT_BLOCK"
        return result

    # ── Step 4: Parse HTML ───────────────────────────────────────────────────
    html = response.text
    result["raw_html"] = html
    result["has_raw_html"] = True

    soup = BeautifulSoup(html, "html.parser")

    result["head"] = _parse_head(soup)
    result["noindex"] = result["head"]["noindex"]
    result["ldjson_blocks"] = _extract_ldjson(soup)

    body_text = _extract_body_text(soup)
    result["body_text"] = body_text
    result["content_word_count"] = len(body_text.split()) if body_text else 0

    result["internal_links"] = _extract_internal_links(soup, clean_url)

    # ── Step 5: Optional /llms.txt probe ─────────────────────────────────────
    if probe_llms:
        result["llms_txt_present"] = probe_llms_txt(clean_url, session)

    return result


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    sess = create_session()
    page = fetch_page(target, session=sess, probe_llms=True)

    # Don't dump the full raw_html in CLI output — show length instead
    display = {k: v for k, v in page.items() if k != "raw_html"}
    display["raw_html_length_chars"] = len(page.get("raw_html") or "")
    display["internal_links_count"] = len(page.get("internal_links") or [])
    display["internal_links_sample"] = (page.get("internal_links") or [])[:5]
    del display["internal_links"]

    print(json.dumps(display, indent=2, ensure_ascii=False))
