"""
checks_dv.py — Discoverability checks DV-01 through DV-20.

Design rules
------------
- Each check_dv_NN() function is a pure function: same HTML in → same result out.
- Findings use {placeholder}-style evidence filled from real per-page data.
- No site-specific numbers or names are hardcoded.
- LLM-judgment steps are documented (not skipped) — see SKILL.md Procedure.
- Ownership rules (DV-02 vs DV-12, DV-05 vs EN-08, DV-06 vs DV-15,
  DV-03 vs ED-02, DV-01 vs EN-13) are encoded via flags returned in the
  result dict and consumed by other skills.

Entry point
-----------
    run_dv_checks(page_result, all_pages=None)  →  dv_result dict

where dv_result has keys: url, status, findings, strengths, flags.
"""

import hashlib
import json
import re
import urllib.parse
from difflib import SequenceMatcher
from typing import Optional

from bs4 import BeautifulSoup

# ── Shared constants ─────────────────────────────────────────────────────────

TRACKING_PARAMS: set = {
    "srsltid", "gclid", "fbclid",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "crid", "dib", "qid", "sprefix", "sr", "ref", "tag", "affiliate",
}

TRANSACTIONAL_URL_RE = re.compile(
    r"(/cart|/checkout|/search|/account|/login|/register|/signin|/signup"
    r"|\?q=|\?s=|\?query=|\?search=)",
    re.IGNORECASE,
)

WIKIDATA_LINK_RE = re.compile(r"wikidata\.org/wiki/Q\d+", re.IGNORECASE)

ENABLE_JS_RE = re.compile(
    r"(enable\s+javascript|please\s+enable\s+(js|javascript)"
    r"|javascript\s+(is\s+)?(required|disabled|not\s+supported)"
    r"|your\s+browser\s+does\s+not\s+support\s+javascript)",
    re.IGNORECASE,
)

WIKI_CITATION_MARKERS_RE = re.compile(
    r"\[(citation needed|dead link|clarification needed"
    r"|unreliable source\??|needs\s+update)\]",
    re.IGNORECASE,
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_finding(
    fid: str,
    title: str,
    severity: str,
    evidence: str,
    action_summary: str,
    action_priority: Optional[str] = None,
    **extra,
) -> dict:
    f = {
        "id": fid,
        "title": title,
        "severity": severity,
        "evidence": evidence,
        "suggested_action": {
            "summary": action_summary,
            "priority": action_priority or severity,
        },
    }
    f.update(extra)
    return f


def _soup(page_result: dict) -> Optional[BeautifulSoup]:
    html = page_result.get("raw_html")
    return BeautifulSoup(html, "html.parser") if html else None


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _has_wikidata_link(page_result: dict) -> bool:
    return bool(WIKIDATA_LINK_RE.search(page_result.get("raw_html") or ""))


def _page_url(page_result: dict) -> str:
    return page_result.get("url", "")


def _netloc(page_result: dict) -> str:
    return urllib.parse.urlparse(_page_url(page_result)).netloc


# ── DV-01: JS-render gap / near-empty body ───────────────────────────────────

def check_dv01(page_result: dict) -> Optional[dict]:
    """
    DV-01 — JS-render gap / near-empty body.

    Critical (auto):  populated <head> (has title) + body word count < 20
    Critical:         literal "enable JavaScript" string in body
    High:             < 30 content words on a non-transactional page
    Medium:           < 50 content words on a non-transactional page

    Transactional URLs (cart, checkout, search, ?q=, etc.) are always skipped —
    they are correctly thin and routed to EN-11 by engagement-audit.
    """
    head = page_result.get("head", {})
    wc = page_result.get("content_word_count", 0)
    body = page_result.get("body_text", "")
    url = _page_url(page_result)

    # Transactional/utility pages: skip DV-01 entirely (they are thin by design)
    if TRANSACTIONAL_URL_RE.search(url):
        return None

    # Auto-Critical: rich head, empty body
    if head.get("title") and wc < 20:
        return _make_finding(
            "DV-01",
            "JS-render gap: populated <head> but essentially empty body",
            "critical",
            (f"Raw HTML fetch of {url} returned only {wc} body words despite "
             f"a populated <head> (title='{head['title'][:60]}'). "
             "All content is likely assembled by client-side JavaScript."),
            (f"Move content for '{head['title'][:60]}' to server-side rendering "
             "(SSR) or a static prerender step — currently {wc} words appear in "
             "raw HTML, leaving crawlers with nothing to index. "
             "This page is routed to EN-13 (engagement not assessed)."),
            "critical",
        )

    # Explicit "enable JS" message
    if ENABLE_JS_RE.search(body):
        return _make_finding(
            "DV-01",
            "JS-render gap: 'JavaScript required' message in raw HTML",
            "critical",
            (f"The raw HTML body of {url} contains a 'JavaScript required / "
             "disabled' fallback message as its primary content."),
            ("Move content to SSR/prerender — the raw HTML contains only a "
             "JavaScript-required fallback; crawlers see nothing to index. "
             "This page is routed to EN-13 (engagement not assessed)."),
            "critical",
        )

    # Below word-count threshold on a substantive page
    if wc < 50 and not TRANSACTIONAL_URL_RE.search(url):
        sev = "high" if wc < 30 else "medium"
        return _make_finding(
            "DV-01",
            f"Thin raw-HTML body: only {wc} content words",
            sev,
            (f"Raw HTML body of {url} contains only {wc} non-boilerplate words "
             f"(threshold: 50). The page may rely heavily on client-side rendering."),
            ("Verify whether content is JS-rendered. If so, move core content to "
             "SSR/prerender so crawlers can read it."),
            sev,
        )

    return None


# ── DV-02: Missing/empty meta description & OG/Twitter tags ─────────────────

def check_dv02(page_result: dict) -> Optional[dict]:
    """
    DV-02 — field ABSENT or EMPTY (never fires on a present-but-generic field;
    that is DV-12). Never fires both DV-02 and DV-12 for the same field.
    """
    head = page_result.get("head", {})
    url = _page_url(page_result)
    missing = []

    for field, key in [
        ("meta[description]", "meta_description"),
        ("og:title",          "og_title"),
        ("og:description",    "og_description"),
        ("og:image",          "og_image"),
        ("twitter:title",     "twitter_title"),
        ("twitter:description","twitter_description"),
    ]:
        if not head.get(key, "").strip():
            missing.append(field)

    if not missing:
        return None

    description_absent = "meta[description]" in missing
    severity = "high" if description_absent else "medium"
    entity = head.get("title") or urllib.parse.urlparse(url).netloc

    return _make_finding(
        "DV-02",
        f"Missing/empty head tags: {', '.join(missing)}",
        severity,
        (f"Page {url} is missing these <head> fields (absent or empty): "
         f"{', '.join(missing)}."),
        (f"Add a meta description and OG/Twitter tags summarising '{entity}' — "
         f"currently {', '.join(missing)} are empty, giving AI assistants no "
         "summary text to preview or cite."),
        severity,
    )


# ── DV-03: No structured data (schema.org / JSON-LD) ────────────────────────

def check_dv03(page_result: dict) -> Optional[dict]:
    """
    DV-03 — missing / invalid JSON-LD.

    Preconditions:
    - Skip if Wikidata sameAs link is present (caller sets wikidata_backed flag).
    - Confidence tier: 'confirmed_absent' (raw HTML available) vs.
      'not_detected_in_pass' (text-only) → text-only = unscored to-verify item.
    """
    if _has_wikidata_link(page_result):
        return None

    url = _page_url(page_result)
    blocks = page_result.get("ldjson_blocks", [])
    has_raw = page_result.get("has_raw_html", False)
    head = page_result.get("head", {})

    # Parse each block; collect valid @type values
    valid_types = []
    for raw_block in blocks:
        try:
            obj = json.loads(raw_block)
            if isinstance(obj, dict) and obj.get("@type"):
                valid_types.append(obj["@type"])
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict) and item.get("@type"):
                        valid_types.append(item["@type"])
        except (json.JSONDecodeError, TypeError):
            pass

    if valid_types:
        return None  # Structured data found — no finding

    # Confidence tier
    if not has_raw:
        return {
            "id": "DV-03",
            "title": "Structured data not detected (needs raw-HTML verification)",
            "severity": "unscored",
            "confidence": "not_detected_in_pass",
            "evidence": (f"Only a rendered-text view was available for {url}; "
                         "JSON-LD blocks may exist in the raw <head>."),
            "suggested_action": {
                "summary": ("Re-run with a raw-HTML fetch to confirm presence or "
                            "absence of JSON-LD structured data."),
                "priority": "medium",
            },
        }

    # Infer the most appropriate schema type from URL/title
    path = urllib.parse.urlparse(url).path.lower()
    title = head.get("title", "").lower()

    if any(x in path for x in ["/product", "/shop", "/item", "/store", "/buy"]):
        schema_type, page_type = "Product+Offer", "product page"
    elif any(x in path for x in ["/about", "/company", "/who-we-are"]):
        schema_type, page_type = "Organization", "about page"
    elif any(x in path for x in ["/faq", "/help", "/support"]):
        schema_type, page_type = "FAQPage", "FAQ/help page"
    elif any(x in path for x in ["/event", "/competition", "/conference", "/hackathon"]):
        schema_type, page_type = "Event", "event page"
    elif any(x in path for x in ["/blog", "/article", "/news", "/post", "/review"]):
        schema_type, page_type = "Article", "article/blog page"
    elif any(x in path for x in ["/contact"]):
        schema_type, page_type = "LocalBusiness", "contact page"
    else:
        schema_type, page_type = "Organization", "homepage/landing page"

    # Escalate severity if compounded with DV-01 or missing description
    has_dv01 = page_result.get("_dv01_fired", False)
    desc_missing = not head.get("meta_description", "").strip()
    severity = "critical" if (has_dv01 or desc_missing) else "high"

    return _make_finding(
        "DV-03",
        f"No valid JSON-LD structured data ({schema_type} expected)",
        severity,
        (f"Raw HTML of {url} contains {len(blocks)} JSON-LD script block(s), "
         f"none of which parsed as a valid schema.org object."),
        (f"Add {schema_type} JSON-LD to this {page_type} — currently 0 valid "
         "structured data blocks are present; crawlers have no machine-readable "
         "identity or facts to extract."),
        severity,
    )


# ── DV-04: Thin content / nothing quotable ───────────────────────────────────

QUOTABLE_MIN_WORDS = 150

def check_dv04(page_result: dict) -> Optional[dict]:
    """
    DV-04 — < 150 words of genuinely explanatory prose.
    Skip if DV-01 already fired at Critical (same root cause).
    LLM judgment step: verify text is genuinely thin, not intentionally minimal.
    """
    wc = page_result.get("content_word_count", 0)
    url = _page_url(page_result)

    if wc >= QUOTABLE_MIN_WORDS:
        return None
    if page_result.get("_dv01_fired"):
        return None  # DV-01 owns the root cause

    body = page_result.get("body_text", "")
    snippet = (body[:120] + "…") if len(body) > 120 else body
    head = page_result.get("head", {})
    entity = head.get("og_title") or head.get("title") or _netloc(page_result)

    return _make_finding(
        "DV-04",
        f"Thin content: only {wc} words — nothing quotable for AI assistants",
        "high",
        (f"Page {url} has only {wc} words of non-boilerplate body text "
         f"(minimum for a citable page is ~{QUOTABLE_MIN_WORDS} words). "
         f"Current text begins: '{snippet}'. "
         "[LLM judgment step: confirm text is genuinely thin, not intentional.]"),
        (f"Add {QUOTABLE_MIN_WORDS}–300 words of plain static text explaining "
         f"what '{entity}' is, what it does, and who it's for — "
         f"currently the only substantive text is: '{snippet[:80]}…'"),
        "high",
    )


# ── DV-05: Facts locked in non-text form ─────────────────────────────────────

TRUST_SECTION_RE = re.compile(
    r"(client|partner|award|certif|accredit|logo|sponsor|trusted\s+by)",
    re.IGNORECASE,
)
MAP_URL_RE = re.compile(
    r"(maps\.google\.|goo\.gl/maps|maps\.app\.goo|openstreetmap"
    r"|bing\.com/maps|waze\.com)",
    re.IGNORECASE,
)

def check_dv05(page_result: dict) -> list:
    """
    DV-05a — images with no meaningful alt near trust-signal sections.
    DV-05b — physical address only inside href map URLs, not visible text.

    Stat/counter elements with no digit value → EN-08, not DV-05.
    """
    s = _soup(page_result)
    if not s:
        return []

    url = _page_url(page_result)
    findings = []

    # DV-05a: Images near trust sections with empty/generic alt
    bad_imgs = []
    for img in s.find_all("img"):
        alt = (img.get("alt") or "").strip().lower()
        if alt in ("", "image", "logo", "icon", "photo", "banner", "bg"):
            # Check if parent context suggests trust-signal content
            parents_text = " ".join(
                p.get_text()[:200]
                for p in img.parents
                if p.name in ("section", "div", "figure", "article", "li")
            )
            if TRUST_SECTION_RE.search(parents_text[:400]):
                src = (img.get("src") or "")[:80]
                bad_imgs.append(src)

    if bad_imgs:
        n = len(bad_imgs)
        findings.append(_make_finding(
            "DV-05a",
            f"Trust-signal images without meaningful alt text ({n} found)",
            "medium",
            (f"Found {n} <img> element(s) near trust/partner/client sections "
             f"on {url} with empty or generic alt text. "
             f"Examples: {', '.join(bad_imgs[:3])}."),
            (f"Add descriptive alt text (company/partner name) to each of the "
             f"{n} trust-signal image(s) — currently the names carried by those "
             "images are invisible to crawlers."),
            "medium",
        ))

    # DV-05b: Map links with no adjacent plain-text address
    for a in s.find_all("a", href=True):
        if MAP_URL_RE.search(a["href"]):
            parent = a.find_parent(["div", "section", "p", "address", "footer"])
            parent_text = (parent.get_text(strip=True) if parent else "")
            # Flag if no postal-address-like text (digits + word chars) visible nearby
            if not re.search(r"\d{1,6}[,\s]+\w{3,}", parent_text):
                findings.append(_make_finding(
                    "DV-05b",
                    "Physical address exists only inside a map link, not as visible text",
                    "medium",
                    (f"Found a map link ({a['href'][:80]}) on {url} with no "
                     "plain-text postal address in the surrounding markup."),
                    ("Add the full postal address as plain visible text near the "
                     "map link — it currently exists only inside a Maps URL and "
                     "cannot be extracted as a fact by a crawler."),
                    "medium",
                ))
                break  # one finding per page for this sub-check

    return findings


# ── DV-06: Duplicate/templated authored copy within a page ───────────────────

def check_dv06(page_result: dict) -> Optional[dict]:
    """
    DV-06 — same authored copy reused verbatim across named sections (> 90 % sim).
    Distinct from DV-15 (mechanically repeated DOM blocks).
    """
    s = _soup(page_result)
    if not s:
        return None

    url = _page_url(page_result)

    # Collect text per named H2/H3 section
    sections: dict = {}
    for heading in s.find_all(["h2", "h3"]):
        name = heading.get_text(strip=True)
        if not name or len(name) > 120:
            continue
        texts = []
        for sib in heading.find_next_siblings():
            if sib.name in ["h2", "h3", "h4"]:
                break
            t = sib.get_text(strip=True)
            if len(t) > 60:
                texts.append(t)
        if texts:
            sections[name] = " ".join(texts)

    names = list(sections)
    dupes = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            sim = _similarity(sections[names[i]], sections[names[j]])
            if sim > 0.90:
                dupes.append((names[i], names[j], round(sim * 100)))

    if not dupes:
        return None

    a, b, pct = dupes[0]
    return _make_finding(
        "DV-06",
        f"Duplicate authored copy across {len(dupes)} section pair(s)",
        "medium",
        (f"Sections '{a}' and '{b}' on {url} share {pct}% identical text. "
         f"Total duplicate section pairs found: {len(dupes)}."),
        (f"Write distinct copy for '{a}' and '{b}' — they currently share "
         f"{pct}% identical text, giving AI assistants nothing distinct to "
         "cite for either section."),
        "medium",
    )


# ── DV-07: Generic/unverifiable testimonials ─────────────────────────────────

TESTIMONIAL_SECTION_RE = re.compile(
    r"(testimonial|review|what.*(client|customer).*say"
    r"|client\s+speak|feedback|success\s+stor)",
    re.IGNORECASE,
)
REVIEW_PLATFORM_RE = re.compile(
    r"(google\.com/maps|trustpilot|g2\.com|capterra"
    r"|clutch\.co|yelp\.com|linkedin\.com|sitejabber)",
    re.IGNORECASE,
)
GENERIC_PHRASING_RE = re.compile(
    r"(great\s+(service|company|team|work)"
    r"|highly\s+recommend"
    r"|excellent\s+(work|service|support)"
    r"|wonderful\s+experience"
    r"|best\s+(in\s+class|ever|company)"
    r"|amazing\s+team|very\s+professional)",
    re.IGNORECASE,
)

def check_dv07(page_result: dict) -> Optional[dict]:
    """
    DV-07 — testimonial blocks with no outbound link to a real review platform.
    Script-able proxy; LLM judgment step: confirm generic phrasing pattern.
    """
    s = _soup(page_result)
    if not s:
        return None

    url = _page_url(page_result)

    # Find testimonial containers
    testimonial_els = [
        el for el in s.find_all(string=TESTIMONIAL_SECTION_RE)
        if el.find_parent(["section", "div", "article"])
    ]
    quote_els = (
        s.find_all("blockquote") +
        s.find_all(class_=re.compile(r"testimonial|quote|review-text", re.I))
    )
    n = max(len(testimonial_els), len(quote_els))

    if n == 0:
        return None

    # Check for outbound review platform links
    has_review_links = bool(s.find("a", href=REVIEW_PLATFORM_RE))
    if has_review_links:
        return None  # Already linked to verifiable sources — positive signal

    # Proxy: generic phrasing count
    all_text = " ".join(el.get_text() for el in (quote_els or testimonial_els))
    generic_matches = len(GENERIC_PHRASING_RE.findall(all_text))

    return _make_finding(
        "DV-07",
        f"Testimonials not linked to verifiable external reviews (~{n} found)",
        "medium",
        (f"Page {url} has ~{n} testimonial/quote element(s) with no links to "
         "external review platforms (Google, Trustpilot, G2, LinkedIn, etc.). "
         f"Generic-phrasing matches: {generic_matches}. "
         "[LLM judgment step: confirm near-identical phrasing across quotes.]"),
        (f"Link testimonials to verifiable external reviews (Google/LinkedIn/"
         f"Trustpilot) — the {n} testimonials shown are currently unlinked and "
         "unattributed; add name, title, company, and a link to a verifiable "
         "source for each."),
        "medium",
    )


# ── DV-08: Missing canonical / tracking-parameter URL variants ───────────────

def check_dv08(page_result: dict) -> Optional[dict]:
    """
    DV-08 — tracking param present in the site's OWN URL + no canonical tag.
    Only fires for params that originate from the site itself; external-referral
    tracking is noted but not scored as a site defect.
    """
    url = _page_url(page_result)
    clean_url = page_result.get("clean_url", url)
    head = page_result.get("head", {})
    canonical = head.get("canonical", "").strip()

    parsed = urllib.parse.urlparse(url)
    present = set(urllib.parse.parse_qs(parsed.query)) & TRACKING_PARAMS

    if not present:
        return None

    # If a canonical pointing away from the tracking URL exists, it's handled
    if canonical and canonical != url:
        return None

    param = list(present)[0]
    return _make_finding(
        "DV-08",
        f"Tracking parameter '{param}' in URL with no canonical tag",
        "low",
        (f"Page fetched with tracking parameter(s) ({', '.join(present)}) "
         f"and no <link rel='canonical'> found. Clean URL: {clean_url}."),
        (f"Add <link rel='canonical' href='{clean_url}'> pointing to the clean "
         f"URL — this page was reached with tracking parameter '{param}' and "
         "no canonical was found; an AI assistant citing this URL directly "
         "would propagate a low-value tracking link."),
        "low",
    )


# ── DV-09: Stuffing / spam-signal content ────────────────────────────────────

def check_dv09(page_result: dict) -> list:
    """
    DV-09a — link-stuffed prose (> 8 links in a single <p>).
    DV-09b — keyword-stuffed meta-keywords tag (> 15 tokens).
    """
    s = _soup(page_result)
    if not s:
        return []

    url = _page_url(page_result)
    head = page_result.get("head", {})
    findings = []

    # DV-09a: link density
    stuffed = []
    for p in s.find_all("p"):
        links = p.find_all("a")
        if len(links) > 8:
            stuffed.append((len(links), p.get_text(strip=True)[:80]))

    if stuffed:
        worst_n, worst_txt = max(stuffed, key=lambda x: x[0])
        findings.append(_make_finding(
            "DV-09a",
            f"Link-stuffed prose: paragraph with {worst_n} inline links",
            "medium",
            (f"Found {len(stuffed)} paragraph(s) on {url} with > 8 inline links. "
             f"Worst case: {worst_n} links. Excerpt: '{worst_txt}'."),
            (f"Move the {worst_n}-link list out of inline prose into a proper "
             "navigation/sitemap block — dense link-stuffed paragraphs read as "
             "manipulative and can suppress trust in surrounding genuine content."),
            "medium",
        ))

    # DV-09b: meta-keywords
    kw = head.get("meta_keywords", "")
    if kw:
        tokens = [t.strip() for t in kw.split(",") if t.strip()]
        if len(tokens) > 15:
            findings.append(_make_finding(
                "DV-09b",
                f"Keyword-stuffed meta-keywords tag ({len(tokens)} terms)",
                "low",
                (f"Page {url} has a meta-keywords tag with {len(tokens)} terms. "
                 f"First 5: {', '.join(tokens[:5])}."),
                (f"Trim or remove the meta-keywords tag — it lists {len(tokens)} "
                 "terms, many potentially unrelated to this page's content; the "
                 "tag carries no discoverability value in modern search/AI retrieval."),
                "low",
            ))

    return findings


# ── DV-10: No individual product/detail pages ────────────────────────────────

def check_dv10(page_result: dict) -> Optional[dict]:
    """
    DV-10 — product/service cards that link only to # anchors or the same page.
    """
    s = _soup(page_result)
    if not s:
        return None

    url = _page_url(page_result)

    # Find product/service card containers
    cards = s.find_all(
        class_=re.compile(r"\b(product|service|item|card|offering)\b", re.I)
    )
    if len(cards) < 2:
        return None

    anchor_only = 0
    has_detail_links = False
    for card in cards:
        a = card.find("a")
        if not a:
            anchor_only += 1
            continue
        href = a.get("href", "").strip()
        if not href or href.startswith("#"):
            anchor_only += 1
        else:
            has_detail_links = True

    if anchor_only >= 2 and not has_detail_links:
        return _make_finding(
            "DV-10",
            f"Products/services listed without dedicated detail pages ({anchor_only} items)",
            "high",
            (f"Found {anchor_only} product/service card(s) on {url} that link "
             "only to # anchors; no unique detail-page URLs detected. "
             "A crawler cannot retrieve any product specifications."),
            (f"Give each of the {anchor_only} product/service items its own URL "
             "with full specs (description, price, dimensions, key facts) — "
             "currently they are listed by name/image only with no indexable "
             "detail page."),
            "high",
        )

    return None


# ── DV-11: No site/company-level orientation text ────────────────────────────

COMPANY_ORIENTATION_RE = re.compile(
    r"(is\s+a[n]?\s+\w|we\s+are\s+a[n]?\s+\w"
    r"|provides?\s+\w|we\s+offer|our\s+platform"
    r"|our\s+company|our\s+mission|founded\s+in"
    r"|established\s+in|\bhelps?\s+\w+\s+to\b)",
    re.IGNORECASE,
)

def check_dv11(page_result: dict) -> Optional[dict]:
    """
    DV-11 — homepage describes products only; never states what the company is.
    Only fires on root-path pages.
    """
    url = _page_url(page_result)
    path = urllib.parse.urlparse(url).path.rstrip("/")

    # Only relevant for homepage / landing
    if path not in ("", "/", "/index.html", "/index.php", "/home", "/en",
                    "/en/", "/index"):
        return None

    body = page_result.get("body_text", "")
    if COMPANY_ORIENTATION_RE.search(body[:4000]):
        return None

    head = page_result.get("head", {})
    entity = head.get("og_title") or head.get("title") or _netloc(page_result)

    return _make_finding(
        "DV-11",
        "No company-level orientation text on homepage",
        "medium",
        (f"The homepage {url} contains no sentence that states what '{entity}' "
         "is as a company/platform. The page describes individual products or "
         "features but never introduces the parent entity."),
        (f"Add a short 'what is {entity}' section (2–3 plain-text sentences) to "
         "the homepage — AI assistants use this to understand and cite the entity "
         "accurately."),
        "medium",
    )


# ── DV-12: Generic/duplicated metadata across distinct URLs ──────────────────

def check_dv12_multipage(pages: list) -> list:
    """
    DV-12 — same <title> or meta-description reused verbatim across topically
    distinct pages.  Operates on a list of page_result dicts.
    Boundary vs DV-02: absent field = DV-02; present-but-duplicate = DV-12.
    Never fire both for the same field on the same page.
    """
    findings = []
    title_map: dict = {}
    desc_map: dict = {}

    for p in pages:
        head = p.get("head", {})
        url = _page_url(p)
        if p.get("noindex") or p.get("blocked"):
            continue
        t = head.get("title", "").strip()
        d = head.get("meta_description", "").strip()
        if t:
            title_map.setdefault(t, []).append(url)
        if d:
            desc_map.setdefault(d, []).append(url)

    for title, urls in title_map.items():
        if len(urls) > 1:
            findings.append(_make_finding(
                "DV-12",
                f"Identical <title> reused across {len(urls)} distinct pages",
                "high",
                (f"Title '{title[:80]}' appears unchanged on {len(urls)} pages: "
                 f"{', '.join(urls[:4])}{'…' if len(urls) > 4 else ''}."),
                (f"Give each page its own unique <title> describing that page's "
                 f"specific topic — '{title[:60]}' is shared across {len(urls)} "
                 "pages, making them indistinguishable to a crawler."),
                "high",
            ))

    for desc, urls in desc_map.items():
        if len(urls) > 1:
            findings.append(_make_finding(
                "DV-12",
                f"Identical meta-description reused across {len(urls)} distinct pages",
                "high",
                (f"Meta-description '{desc[:80]}' is identical on {len(urls)} pages: "
                 f"{', '.join(urls[:4])}{'…' if len(urls) > 4 else ''}."),
                (f"Give each page its own unique meta-description — '{desc[:60]}…' "
                 f"is reused across {len(urls)} pages and makes every page "
                 "indistinguishable to crawlers."),
                "high",
            ))

    return findings


# ── DV-13 / DV-16: Findings built from fetch_page.py flags ───────────────────

def make_dv13_finding(page_result: dict) -> dict:
    url = _page_url(page_result)
    return _make_finding(
        "DV-13",
        "Crawler blocked by bot-detection / WAF challenge",
        "critical",
        (f"Fetch of {url} was rejected by a bot-detection or WAF layer "
         f"(HTTP {page_result.get('http_status', '?')}, "
         f"reason: {page_result.get('blocked_reason', 'unknown')}). "
         "No HTML content was returned."),
        ("Allowlist verified AI/search crawler user-agents (GPTBot, PerplexityBot, "
         "Googlebot) in the WAF, or serve a lightweight static/cached version of "
         "key public pages — no downstream fix can take effect until this is resolved."),
        "critical",
    )


def make_dv16_finding(page_result: dict) -> dict:
    url = _page_url(page_result)
    return _make_finding(
        "DV-16",
        "Deliberate robots.txt disallow — automated crawling explicitly blocked",
        "critical",
        f"The domain's robots.txt explicitly disallows crawling of {url}.",
        ("This is a deliberate crawl-policy decision. Either publish a crawlable "
         "public-information subset (categories, FAQs, general info) under a "
         "permissive robots.txt group scoped to verified AI/search agents "
         "(GPTBot, PerplexityBot), or explicitly accept that no citation-based "
         "discovery is possible and rely on brand-name recall alone."),
        "critical",
    )


# ── DV-15: Structural content duplication (carousel/slider artefact) ─────────

def check_dv15(page_result: dict) -> Optional[dict]:
    """
    DV-15 — same DOM block repeated 3+ times (server-render artefact).
    Distinct from DV-06 (deliberately authored copy reused across named sections).
    Severity scales with repeat count.
    """
    s = _soup(page_result)
    if not s:
        return None

    url = _page_url(page_result)
    hash_map: dict = {}

    for el in s.find_all(["div", "section", "article", "li"]):
        text = el.get_text(strip=True)
        if len(text) < 80:
            continue
        norm = re.sub(r"\s+", " ", text)
        h = hashlib.md5(norm.encode("utf-8", errors="replace")).hexdigest()
        hash_map.setdefault(h, []).append(norm[:120])

    repeated = {h: items for h, items in hash_map.items() if len(items) > 3}
    if not repeated:
        return None

    worst_count = max(len(v) for v in repeated.values())
    worst_sample = next(iter(repeated.values()))[0]

    severity = "high" if worst_count > 10 else "medium" if worst_count > 5 else "low"

    return _make_finding(
        "DV-15",
        f"Structural DOM duplication: a content block repeats {worst_count}× in raw HTML",
        severity,
        (f"On {url}, a content block appears verbatim {worst_count} times in "
         f"a single raw-HTML fetch. Sample: '{worst_sample[:100]}'. "
         "Likely a carousel/slider shipping all clones server-side."),
        (f"Render each content block once in the base HTML; if a carousel needs "
         "duplicate DOM nodes for infinite-scroll, generate those client-side "
         f"after initial paint — currently a block repeats verbatim {worst_count}× "
         "in server-rendered HTML, which reads as manipulative to trust-scoring systems."),
        severity,
    )


# ── DV-17: Third-party proxy content fills the citation gap ──────────────────

def make_dv17_finding(domain: str, parent_finding_id: str) -> dict:
    """
    DV-17 — fires only when DV-13 or DV-16 fired on the same entity.
    Requires an external search step (documented as an agent step, not a script).
    """
    return {
        "id": "DV-17",
        "title": f"Third-party proxy content may fill citation gap for {domain}",
        "severity": "high",
        "evidence": (f"Primary domain {domain} is inaccessible to automated agents "
                     f"(see {parent_finding_id}). Agent step required: search "
                     f"'{domain} [primary service or product]' and verify whether "
                     "unofficial third-party sites outrank the blocked primary domain "
                     "in AI-assistant / search results."),
        "requires_agent_step": True,
        "suggested_action": {
            "summary": (f"Because {domain}'s primary domain is inaccessible, "
                        "third-party sources may fill the citation gap. "
                        f"Resolving {parent_finding_id} is the root fix. "
                        "In the interim, publish an officially-branded, crawlable "
                        "lightweight guide page to compete for the same citation space."),
            "priority": "high",
        },
    }


# ── DV-18: /llms.txt presence ────────────────────────────────────────────────

def check_dv18(llms_txt_present: bool, domain: str) -> dict:
    """
    DV-18 — proactive suggestion when /llms.txt is absent; strength when present.
    """
    if llms_txt_present:
        return {
            "_strength": True,
            "id": "DV-18",
            "title": f"/llms.txt present at {domain} — proactive LLM discovery signal in place.",
        }
    return {
        "id": "DV-18",
        "title": "No /llms.txt discovery file at domain root",
        "severity": "low",
        "proactive": True,
        "evidence": f"No reachable /llms.txt found at https://{domain}/llms.txt.",
        "suggested_action": {
            "summary": ("Publish a simple /llms.txt at the domain root listing key "
                        "crawlable URLs — cheap, high-leverage for LLM-based citation, "
                        "and not yet common enough to be an expected baseline."),
            "priority": "low",
        },
    }


# ── DV-19: Generic/unattributed authorship ───────────────────────────────────

GENERIC_BYLINE_RE = re.compile(
    r"\b(team|staff|desk|admin|editor|editorial|correspondent"
    r"|bureau|reporter|newsdesk|web\s*team|content\s*team)\b",
    re.IGNORECASE,
)

def check_dv19(page_result: dict) -> Optional[dict]:
    """
    DV-19 — generic byline (Team/Staff/Desk) on review/news/article content.
    Script-able proxy; LLM judgment step to confirm genuinely generic (not an unusual name).
    """
    s = _soup(page_result)
    if not s:
        return None

    url = _page_url(page_result)
    path = urllib.parse.urlparse(url).path.lower()

    # Target: article/review/news pages
    content_path = any(x in path for x in
                       ["/review", "/article", "/news", "/blog", "/post", "/story"])
    has_article_el = bool(
        s.find("article") or
        s.find(class_=re.compile(r"\b(article|post|review|entry)\b", re.I))
    )
    if not content_path and not has_article_el:
        return None

    # Look for byline/author elements
    byline_candidates = (
        s.find_all(class_=re.compile(r"\b(author|byline|writer|credit|penname)\b", re.I)) +
        s.find_all(attrs={"rel": "author"}) +
        s.find_all(attrs={"itemprop": "author"})
    )

    for el in byline_candidates:
        text = el.get_text(strip=True)
        if GENERIC_BYLINE_RE.search(text):
            ctype = "review" if "/review" in path else "article"
            return _make_finding(
                "DV-19",
                f"Generic/unattributed authorship: byline reads '{text[:60]}'",
                "medium",
                (f"Page {url} has a byline '{text[:80]}' matching a generic pattern "
                 "(team/staff/desk/etc.) rather than a named individual. "
                 "[LLM judgment step: confirm this is a generic pattern, not an unusual name.]"),
                (f"Attribute this {ctype} to a named individual with an author "
                 "schema field where possible — currently attributed only to "
                 f"'{text[:60]}', weakening source-credibility signal for AI citation."),
                "medium",
            )

    return None


# ── DV-20: High boilerplate-to-content ratio ─────────────────────────────────

def check_dv20(page_result: dict) -> Optional[dict]:
    """
    DV-20 — primary content is a small fraction of total page text.
    Fires on content-style pages where ratio < 20 % OR no semantic boundary exists.
    """
    s = _soup(page_result)
    if not s:
        return None

    url = _page_url(page_result)

    # Total page word count (raw)
    total_text = s.get_text(separator=" ", strip=True)
    total_words = len(re.sub(r"\s+", " ", total_text).split())
    if total_words < 150:
        return None

    # Main content element
    main_el = (
        s.find("article") or
        s.find("main") or
        s.find(attrs={"role": "main"}) or
        s.find(id=re.compile(r"\b(content|main|article|post|story)\b", re.I)) or
        s.find(class_=re.compile(r"\b(article|post|entry|content|story|body)\b", re.I))
    )
    has_boundary = main_el is not None
    main_words = (
        len(re.sub(r"\s+", " ", main_el.get_text(separator=" ", strip=True)).split())
        if main_el else page_result.get("content_word_count", 0)
    )

    ratio = main_words / total_words if total_words else 1.0

    path = urllib.parse.urlparse(url).path.lower()
    content_page = any(x in path for x in
                       ["/review", "/article", "/news", "/blog", "/post", "/story"])

    if ratio >= 0.20 and has_boundary:
        return None
    if not content_page and ratio >= 0.25:
        return None

    boundary_note = (
        "No semantic <article>/<main> boundary found — extraction tools cannot "
        "reliably isolate primary content."
        if not has_boundary else ""
    )

    return _make_finding(
        "DV-20",
        f"High boilerplate-to-content ratio: only {int(ratio * 100)}% is primary content",
        "medium",
        (f"Page {url}: ~{main_words} primary-content words out of {total_words} "
         f"total words ({int(ratio * 100)}% unique content). {boundary_note}"),
        ("Wrap the primary content in a clear semantic boundary (<article> or <main>) "
         "so extraction tools can reliably isolate it from surrounding site chrome "
         f"(related links, sidebars, nav, footer) — currently only "
         f"~{int(ratio * 100)}% of page text is primary content."),
        "medium",
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def run_dv_checks(page_result: dict, all_pages: list = None) -> dict:
    """
    Run all applicable DV checks on a single *page_result* dict.

    Returns a dv_result dict:
    {
      "url":      str,
      "status":   "checked" | "blocked" | "robots_disallowed"
                  | "intentionally_excluded" | "fetch_error",
      "findings": [ <finding dicts> ],
      "strengths": [ <strength dicts> ],
      "flags": {
        "dv01_critical":  bool,   # → engagement-audit routes to EN-13
        "dv13_fired":     bool,   # → engagement-audit routes to EN-12
        "dv16_fired":     bool,   # → engagement-audit routes to EN-12
        "wikidata_backed":bool,   # → entity-disambiguation uses Wikidata graph
      }
    }
    """
    url = _page_url(page_result)
    out = {
        "url": url,
        "status": "checked",
        "findings": [],
        "strengths": [],
        "flags": {
            "dv01_critical": False,
            "dv13_fired": False,
            "dv16_fired": False,
            "wikidata_backed": False,
        },
    }
    F = out["findings"]
    S = out["strengths"]

    # ── Priority 1: Bot-block (DV-13) ────────────────────────────────────────
    if page_result.get("blocked_reason") == "BOT_BLOCK":
        out["status"] = "blocked"
        out["flags"]["dv13_fired"] = True
        dv13 = make_dv13_finding(page_result)
        F.append(dv13)
        dv17 = make_dv17_finding(_netloc(page_result), "DV-13")
        F.append(dv17)
        return out

    # ── Priority 2: robots.txt disallow (DV-16) ───────────────────────────────
    if page_result.get("robots_disallowed"):
        out["status"] = "robots_disallowed"
        out["flags"]["dv16_fired"] = True
        dv16 = make_dv16_finding(page_result)
        F.append(dv16)
        dv17 = make_dv17_finding(_netloc(page_result), "DV-16")
        F.append(dv17)
        return out

    # ── Priority 3: noindex ───────────────────────────────────────────────────
    if page_result.get("noindex"):
        out["status"] = "intentionally_excluded"
        return out

    # ── Priority 4: Fetch error ───────────────────────────────────────────────
    if page_result.get("error"):
        out["status"] = "fetch_error"
        return out

    # ── DV-01 (first; sets _dv01_fired flag for DV-03/DV-04) ─────────────────
    dv01 = check_dv01(page_result)
    if dv01:
        F.append(dv01)
        if dv01["severity"] == "critical":
            out["flags"]["dv01_critical"] = True
            page_result["_dv01_fired"] = True

    # ── Wikidata check ────────────────────────────────────────────────────────
    if _has_wikidata_link(page_result):
        out["flags"]["wikidata_backed"] = True
        S.append({
            "id": "WIKIDATA-SAMEAS",
            "title": "Wikidata sameAs link found — entity identity resolved via Wikidata graph.",
        })

    # ── DV-02 ─────────────────────────────────────────────────────────────────
    dv02 = check_dv02(page_result)
    if dv02:
        F.append(dv02)

    # ── DV-03 (skip if Wikidata-backed) ──────────────────────────────────────
    if not out["flags"]["wikidata_backed"]:
        dv03 = check_dv03(page_result)
        if dv03:
            F.append(dv03)

    # ── DV-04 (skip if DV-01 Critical) ───────────────────────────────────────
    if not out["flags"]["dv01_critical"]:
        dv04 = check_dv04(page_result)
        if dv04:
            F.append(dv04)

    # ── DV-05 ─────────────────────────────────────────────────────────────────
    F.extend(check_dv05(page_result))

    # ── DV-06 ─────────────────────────────────────────────────────────────────
    dv06 = check_dv06(page_result)
    if dv06:
        F.append(dv06)

    # ── DV-07 ─────────────────────────────────────────────────────────────────
    dv07 = check_dv07(page_result)
    if dv07:
        F.append(dv07)

    # ── DV-08 ─────────────────────────────────────────────────────────────────
    dv08 = check_dv08(page_result)
    if dv08:
        F.append(dv08)

    # ── DV-09 ─────────────────────────────────────────────────────────────────
    F.extend(check_dv09(page_result))

    # ── DV-10 ─────────────────────────────────────────────────────────────────
    dv10 = check_dv10(page_result)
    if dv10:
        F.append(dv10)

    # ── DV-11 ─────────────────────────────────────────────────────────────────
    dv11 = check_dv11(page_result)
    if dv11:
        F.append(dv11)

    # ── DV-15 ─────────────────────────────────────────────────────────────────
    dv15 = check_dv15(page_result)
    if dv15:
        F.append(dv15)

    # ── DV-19 ─────────────────────────────────────────────────────────────────
    dv19 = check_dv19(page_result)
    if dv19:
        F.append(dv19)

    # ── DV-20 ─────────────────────────────────────────────────────────────────
    dv20 = check_dv20(page_result)
    if dv20:
        F.append(dv20)

    # ── DV-12 (multi-page — caller passes all_pages list) ────────────────────
    if all_pages and len(all_pages) > 1:
        F.extend(check_dv12_multipage(all_pages))

    return out
