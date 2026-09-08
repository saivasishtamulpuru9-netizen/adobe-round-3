"""
checks_fs.py — Freshness & Corroboration checks FS-01 through FS-06.

Design rules
------------
- Pure functions: same HTML in → same findings out (given the same current date).
- FS-02 numeric-mismatch and FS-05 external-corroboration require LLM judgment;
  those steps are documented (not skipped) — see SKILL.md Procedure.
- FS-06 wiki-style marker check runs FIRST on collaboratively-edited domains,
  before any inferred corroboration check.
- emit_flag_only() is the shared helper also used by engagement-audit (EN-06).
  Keep its signature stable; engagement-audit copies this helper verbatim.

Entry point
-----------
    run_fs_checks(page_result, current_date=None)  →  fs_result dict

where fs_result has keys: url, findings, flag_only_items, strengths.
"""

import re
import json
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from typing import Optional
import urllib.parse

from bs4 import BeautifulSoup

# ── Shared helper (also used verbatim by engagement-audit / EN-06) ────────────

def emit_flag_only(check_id: str, reason: str, recommendation: str) -> dict:
    """
    Emit a flag-only item for checks that cannot be verified from a single-page
    fetch alone. These are surfaced separately from scored findings in the final
    report — they are manual-audit recommendations, not evidence-backed defects.

    Shared with engagement-audit (EN-06). Keep this signature stable.
    """
    return {
        "id": check_id,
        "type": "flag_only",
        "reason": reason,
        "recommendation": recommendation,
    }


# ── Constants ────────────────────────────────────────────────────────────────

# Month name → integer for date parsing
MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

# Patterns for extracting dates from body text / banners
# Captures: YYYY-MM-DD, DD Month YYYY, Month DD YYYY, DD/MM/YYYY, MM/DD/YYYY
DATE_PATTERNS = [
    # ISO: 2024-01-15
    re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b"),
    # "15 January 2024" or "January 15, 2024"
    re.compile(
        r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august"
        r"|september|october|november|december)\s+(20\d{2})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(january|february|march|april|may|june|july|august"
        r"|september|october|november|december)\s+(\d{1,2})[,\s]+(20\d{2})\b",
        re.IGNORECASE,
    ),
    # DD/MM/YYYY or MM/DD/YYYY (year >= 2000)
    re.compile(r"\b(0?[1-9]|[12]\d|3[01])/(0?[1-9]|1[0-2])/(20\d{2})\b"),
    # "Jan 2024" or "2024 Jan"
    re.compile(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(20\d{2})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(20\d{2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b",
        re.IGNORECASE,
    ),
    # Copyright year: © 2020 or (c) 2020
    re.compile(r"(?:©|\(c\)|copyright)\s*(20\d{2})", re.IGNORECASE),
]

# Patterns that indicate a claim is "current" or "upcoming"
CURRENT_CLAIM_CONTEXT_RE = re.compile(
    r"(scheduled\s+for|upcoming|current|now\s+live|maintenance|announcement"
    r"|registration\s+open|deadline|apply\s+before|last\s+date|due\s+date"
    r"|notice|alert|important\s+update|©|copyright)",
    re.IGNORECASE,
)

# Numeric fact patterns for FS-02 mismatch detection
NUMERIC_FACT_PATTERNS = [
    re.compile(r"(\d{1,3})\+?\s*years?\s+(?:of\s+)?(?:experience|leadership|expertise|in\s+business)", re.IGNORECASE),
    re.compile(r"(\d{1,5})\+?\s*(?:happy\s+)?(?:clients?|customers?|users?|projects?)", re.IGNORECASE),
    re.compile(r"(\d{1,3})\+?\s*(?:countries?|cities?|offices?|locations?)", re.IGNORECASE),
    re.compile(r"(\d{1,5})\+?\s*(?:employees?|team\s+members?|professionals?)", re.IGNORECASE),
    re.compile(r"(\d{1,3})\+?\s*(?:awards?|certifications?)", re.IGNORECASE),
    re.compile(r"(\d{1,3})%\s*(?:uptime|availability|satisfaction|success\s+rate)", re.IGNORECASE),
]

# Wiki-style self-reported corroboration markers (FS-06)
WIKI_MARKERS_RE = re.compile(
    r"\[(citation\s+needed|dead\s+link|clarification\s+needed"
    r"|unreliable\s+source\??|needs\s+update|verification\s+needed"
    r"|dubious|disputed)\]",
    re.IGNORECASE,
)

# Collaboratively-edited domain heuristics
WIKI_DOMAIN_RE = re.compile(
    r"(wikipedia\.org|wikia\.com|fandom\.com|mediawiki\.org"
    r"|wiki\.|\.wiki\.|wikimedia\.org)",
    re.IGNORECASE,
)

# Last-updated signal patterns in body text
FRESHNESS_SIGNAL_RE = re.compile(
    r"(last\s+updated?|last\s+modified|updated?\s+on|published\s+on"
    r"|as\s+of\s+\w+\s+\d{4}|version\s+\d|revision\s+\d"
    r"|effective\s+date|reviewed\s+on|fact.?checked)",
    re.IGNORECASE,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_finding(fid, title, severity, evidence, action_summary,
                  action_priority=None, **extra) -> dict:
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


def _page_url(page_result: dict) -> str:
    return page_result.get("url", "")


def _today(current_date=None) -> date:
    return current_date or date.today()


def _try_parse_date(text_snippet: str) -> Optional[date]:
    """
    Attempt to parse a date from a text snippet.
    Returns a date object or None.
    """
    text = text_snippet.strip()

    # ISO format
    m = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # DD Month YYYY
    m = re.search(
        r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august"
        r"|september|october|november|december)\s+(20\d{2})\b",
        text, re.IGNORECASE,
    )
    if m:
        try:
            mo = MONTH_MAP.get(m.group(2).lower()[:3])
            return date(int(m.group(3)), mo, int(m.group(1))) if mo else None
        except ValueError:
            pass

    # Month DD, YYYY
    m = re.search(
        r"\b(january|february|march|april|may|june|july|august"
        r"|september|october|november|december)\s+(\d{1,2})[,\s]+(20\d{2})\b",
        text, re.IGNORECASE,
    )
    if m:
        try:
            mo = MONTH_MAP.get(m.group(1).lower()[:3])
            return date(int(m.group(3)), mo, int(m.group(2))) if mo else None
        except ValueError:
            pass

    # Month YYYY (approximate to first of month)
    m = re.search(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(20\d{2})\b",
        text, re.IGNORECASE,
    )
    if m:
        try:
            mo = MONTH_MAP.get(m.group(1).lower()[:3])
            return date(int(m.group(2)), mo, 1) if mo else None
        except ValueError:
            pass

    # Copyright year only
    m = re.search(r"(?:©|\(c\)|copyright)\s*(20\d{2})", text, re.IGNORECASE)
    if m:
        try:
            return date(int(m.group(1)), 12, 31)  # Treat as end of that year
        except ValueError:
            pass

    return None


def _extract_sentences_with_dates(body_text: str) -> list:
    """
    Extract (sentence, date) pairs where the sentence contains a date-like
    pattern and a "current/upcoming" contextual keyword.
    Returns list of (sentence_snippet, parsed_date) tuples.
    """
    # Split into rough sentences
    sentences = re.split(r"(?<=[.!?])\s+", body_text)
    results = []
    for sent in sentences:
        if not CURRENT_CLAIM_CONTEXT_RE.search(sent):
            continue
        d = _try_parse_date(sent)
        if d:
            results.append((sent[:200], d))
    return results


# ── FS-01: Stale "current" claims vs. today's date ───────────────────────────

def check_fs01(page_result: dict, current_date: date = None) -> list:
    """
    FS-01 — Detect date strings paired with "current/upcoming" context keywords
    that refer to a date now in the past.

    High severity if the stale claim is operational (maintenance, deadline, registration).
    Medium severity otherwise (e.g. copyright year lagging by > 2 years).
    """
    today = _today(current_date)
    body_text = page_result.get("body_text", "")
    url = _page_url(page_result)
    findings = []
    seen_dates = set()

    # Also scan raw HTML for structured date contexts (footer copyright, banners)
    raw = page_result.get("raw_html", "") or ""

    # Combine body + raw for scanning (raw catches copyright in footer)
    combined = body_text + " " + raw[:10000]

    dated_claims = _extract_sentences_with_dates(combined)

    # Also look for isolated copyright year patterns even without full sentence context
    for m in re.finditer(r"(?:©|&copy;|\(c\)|copyright)\s*(20\d{2})", raw, re.IGNORECASE):
        try:
            yr = int(m.group(1))
            d = date(yr, 12, 31)
            snippet = raw[max(0, m.start()-30):m.end()+30].strip()
            dated_claims.append((snippet, d))
        except ValueError:
            pass

    for snippet, claim_date in dated_claims:
        if claim_date in seen_dates:
            continue
        seen_dates.add(claim_date)

        if claim_date >= today:
            continue  # Still in the future — not stale

        days_past = (today - claim_date).days

        # Don't flag copyright that's only 1-2 years old — normal lag
        is_copyright = bool(re.search(r"(?:©|&copy;|\(c\)|copyright)", snippet, re.IGNORECASE))
        if is_copyright and days_past < 365 * 2:
            continue

        # Determine severity: operational claims are High
        OPERATIONAL_RE = re.compile(
            r"(maintenance|scheduled|registration|deadline|last\s+date|apply\s+before"
            r"|due\s+date|notice|alert|exam|result|admission|fee)",
            re.IGNORECASE,
        )
        severity = "high" if OPERATIONAL_RE.search(snippet) else "medium"

        notice_type = "copyright notice" if is_copyright else "date claim / banner"
        stale_label = claim_date.strftime("%d %b %Y") if not is_copyright else str(claim_date.year)

        findings.append(_make_finding(
            "FS-01",
            f"Stale '{notice_type}' references {stale_label} ({days_past} days ago)",
            severity,
            (f"Page {url} contains a '{notice_type}' referencing {stale_label}, "
             f"which is {days_past} days in the past. Snippet: '{snippet[:150]}'."),
            (f"Remove or update the {notice_type} referencing {stale_label} — "
             "that date has passed, and a stale 'current' claim undermines freshness "
             "signals for the whole page, especially when other content is actively maintained."),
            severity,
        ))

    return findings


# ── FS-02: Internal numeric inconsistency ─────────────────────────────────────

def check_fs02(page_result: dict) -> list:
    """
    FS-02 — Detect the same numeric fact-type cited with different values on
    the same page (e.g. "11+ years" in meta vs "14+ Years" in stat block).

    Script-able pre-extraction (regex); LLM judgment step to confirm mismatch
    is genuine (not a different fact type using similar phrasing).
    """
    body = page_result.get("body_text", "")
    head = page_result.get("head", {})
    url = _page_url(page_result)
    findings = []

    # Combine meta description + body for cross-section comparison
    meta_desc = head.get("meta_description", "")
    full_text = meta_desc + " " + body

    for pattern in NUMERIC_FACT_PATTERNS:
        matches = pattern.findall(full_text)
        if len(matches) < 2:
            continue

        # Extract numeric values; if they differ, flag
        try:
            values = sorted(set(int(m) if isinstance(m, str) else int(m[0])
                               for m in matches))
        except (ValueError, TypeError):
            continue

        if len(values) > 1:
            # Find example contexts
            contexts = []
            for m in pattern.finditer(full_text):
                snippet = full_text[max(0, m.start()-30):m.end()+40]
                contexts.append(snippet.strip()[:100])
                if len(contexts) >= 2:
                    break

            fact_type = pattern.pattern.split("\\s+(?:of\\s+)?(?:")[0].replace("(\\d{1,", "~").replace("})", "")
            # Simplify pattern description for display
            fact_desc = "numeric claim about years/clients/countries/employees"

            findings.append(_make_finding(
                "FS-02",
                f"Internal numeric inconsistency: {values} for same fact type",
                "medium",
                (f"Page {url} cites the same fact type with conflicting values: "
                 f"{values}. "
                 f"Example contexts: '{contexts[0] if contexts else ''}' vs "
                 f"'{contexts[1] if len(contexts)>1 else ''}'. "
                 "[LLM judgment step: confirm these refer to the same fact, not two different metrics.]"),
                (f"Reconcile the two different figures on this page ({values[0]} vs {values[-1]}) — "
                 "an AI assistant reading only this page has no way to know which is correct."),
                "medium",
            ))

    return findings


# ── FS-03: No dated / "last updated" signal ───────────────────────────────────

def check_fs03(page_result: dict) -> Optional[dict]:
    """
    FS-03 — Page has no freshness signal: no article:published_time,
    no article:modified_time meta tag, and no visible "last updated" text.

    Same confidence-tier rule as DV-03: if only rendered text was available
    (not raw HTML), log as not_detected_in_pass — not a scored finding.
    """
    head = page_result.get("head", {})
    body = page_result.get("body_text", "")
    url = _page_url(page_result)
    has_raw = page_result.get("has_raw_html", False)

    # Check structured freshness signals in <head>
    has_published = bool(head.get("article_published_time", "").strip())
    has_modified = bool(head.get("article_modified_time", "").strip())

    if has_published or has_modified:
        return None  # Freshness signal present

    # Check for visible freshness text in body
    if FRESHNESS_SIGNAL_RE.search(body):
        return None

    # Confidence tier (same rule as DV-03)
    if not has_raw:
        return {
            "id": "FS-03",
            "title": "No freshness signal detected (needs raw-HTML verification)",
            "severity": "unscored",
            "confidence": "not_detected_in_pass",
            "evidence": (f"Only a rendered-text view was available for {url}; "
                         "a 'last edited' timestamp or article:published_time may "
                         "exist in the raw <head> not captured in this pass."),
            "suggested_action": {
                "summary": "Re-run with raw-HTML fetch to confirm presence/absence of freshness metadata.",
                "priority": "medium",
            },
        }

    # Only flag on content-style pages where freshness matters
    path = urllib.parse.urlparse(url).path.lower()
    content_page = any(x in path for x in
                       ["/blog", "/article", "/news", "/post", "/review",
                        "/guide", "/docs", "/documentation", "/help"])
    is_homepage = path.rstrip("/") in ("", "/", "/index.html", "/index.php", "/home")

    if not content_page and not is_homepage:
        return None  # Not a page type where freshness is expected

    severity = "medium" if content_page else "low"

    return _make_finding(
        "FS-03",
        "No 'last updated' or publication date signal on content page",
        severity,
        (f"Page {url} has no article:published_time, no article:modified_time meta tag, "
         "and no visible 'last updated / as of [date]' text in the body."),
        ("Add a visible 'last updated' or version note (e.g. 'Updated September 2026') "
         "so AI assistants have a freshness signal to cite confidently — "
         "undated content is treated as potentially stale."),
        severity,
    )


# ── FS-04: Internal listing / consistency mismatches (non-numeric) ────────────

def check_fs04(page_result: dict) -> list:
    """
    FS-04 — Navigation/footer listing inconsistencies: items in nav not in footer,
    or vice-versa. Also detects obvious typos in nav/footer labels (proxy only —
    full spellcheck is a lower-automation step).
    """
    s = _soup(page_result)
    if not s:
        return []

    url = _page_url(page_result)
    findings = []

    # Extract nav items
    nav_items = set()
    for nav in s.find_all("nav"):
        for a in nav.find_all("a"):
            text = a.get_text(strip=True)
            if text and 2 < len(text) < 50:
                nav_items.add(text.lower().strip())

    # Extract footer items
    footer_items = set()
    for footer in s.find_all("footer"):
        for a in footer.find_all("a"):
            text = a.get_text(strip=True)
            if text and 2 < len(text) < 50:
                footer_items.add(text.lower().strip())

    if not nav_items or not footer_items:
        return findings

    # Items in nav but NOT in footer (and vice-versa) — find near-matches first
    # (Allow for minor casing differences already handled by .lower())
    nav_only = nav_items - footer_items
    footer_only = footer_items - nav_items

    # Filter to substantive items (exclude generic nav words: home, contact, login, etc.)
    GENERIC_NAV = {"home", "contact", "about", "login", "register", "sign in",
                   "sign up", "menu", "back", "top", "search", "cart", "blog",
                   "faq", "help", "privacy", "terms", "sitemap", "newsletter"}
    nav_only_filtered = {i for i in nav_only if i not in GENERIC_NAV and len(i) > 4}
    footer_only_filtered = {i for i in footer_only if i not in GENERIC_NAV and len(i) > 4}

    # Find pairs that are similar but not identical (possible typos or name changes)
    mismatched_pairs = []
    for n in nav_only_filtered:
        for f in footer_only_filtered:
            sim = SequenceMatcher(None, n, f).ratio()
            if 0.6 < sim < 1.0:  # Similar but not identical
                mismatched_pairs.append((n, f, round(sim * 100)))

    if mismatched_pairs:
        pair = mismatched_pairs[0]
        findings.append(_make_finding(
            "FS-04",
            f"Nav/footer listing mismatch: '{pair[0]}' vs '{pair[1]}' ({pair[2]}% similar)",
            "low",
            (f"Page {url} nav contains '{pair[0]}' but footer contains '{pair[1]}' "
             f"({pair[2]}% similar — possible typo or inconsistent naming). "
             f"Total mismatched pairs: {len(mismatched_pairs)}."),
            (f"Reconcile the nav and footer listings — nav includes '{pair[0]}' but "
             f"footer shows '{pair[1]}'; a typo or inconsistent name reads as "
             "outdated/inconsistent to both visitors and crawlers."),
            "low",
        ))

    # Large discrepancy in item count (nav has many more items than footer, or vice-versa)
    if len(nav_only_filtered) >= 3:
        examples = list(nav_only_filtered)[:3]
        findings.append(_make_finding(
            "FS-04",
            f"Nav lists {len(nav_only_filtered)} items not reflected in footer",
            "low",
            (f"Page {url}: navigation contains {len(nav_only_filtered)} substantive items "
             f"absent from the footer: {', '.join(repr(e) for e in examples)}..."),
            (f"Reconcile nav and footer listings — nav includes "
             f"{len(nav_only_filtered)} items that footer omits, which reads as "
             "inconsistent/outdated to crawlers that use both components for site mapping."),
            "low",
        ))

    return findings


# ── FS-05: External corroboration gap (flag-only) ─────────────────────────────

def check_fs05_flag_only(page_result: dict) -> dict:
    """
    FS-05 — External mismatch / disputed-fact attribution check.

    This is a flag-only check — the claim cannot be verified from a single-page
    fetch alone. Surface as a manual-audit recommendation.

    Positive contrast: pages that explicitly attribute disputed facts to named
    sources ("a British Council letter... a Portuguese document...") rather than
    silently picking one version should be logged as a STRENGTH.
    """
    body = page_result.get("body_text", "")
    url = _page_url(page_result)

    # Heuristic: does the page explicitly attribute claims to named external sources?
    ATTRIBUTION_RE = re.compile(
        r"(according\s+to|cited\s+by|sourced\s+from|as\s+per|based\s+on"
        r"|referenced\s+in|as\s+reported\s+by|per\s+the\s+report)",
        re.IGNORECASE,
    )
    has_attribution = bool(ATTRIBUTION_RE.search(body))

    if has_attribution:
        # Positive pattern — return as a strength note instead of a flag
        return {
            "_strength": True,
            "id": "FS-05-POSITIVE",
            "title": (f"Disputed/attributed facts are explicitly sourced on {url} — "
                      "strong corroboration pattern."),
        }

    return emit_flag_only(
        "FS-05",
        reason=(f"Facts on {url} should be spot-checked against third-party directories, "
                "retailers, or press coverage for outdated versions (old price, old logo, "
                "discontinued product, changed leadership). "
                "This requires checking sources beyond this page and cannot be "
                "confirmed from a single-page fetch."),
        recommendation=(
            "Manually spot-check key facts (pricing, team, product specs, statistics) "
            "against third-party sources (Google My Business, LinkedIn, press coverage, "
            "industry directories) to identify and correct any outdated information "
            "circulating externally."
        ),
    )


# ── FS-06: Self-reported corroboration gaps (wiki-style markers) ──────────────

def check_fs06(page_result: dict) -> list:
    """
    FS-06 — Self-reported corroboration gaps: wiki-style inline markers
    ([citation needed], [dead link], etc.).

    Run this check FIRST on collaboratively-edited domains, before falling
    back to inferred corroboration checks. These markers are free, high-confidence
    signals that the page itself already surfaces.

    Severity:
    - [citation needed] / [verification needed] / [dubious]: Medium
      (a claim is asserted with zero support)
    - [dead link] / [needs update]: Low
      (claim was sourced but link rotted or content may be outdated)
    - [clarification needed] / [disputed]: Low
      (structural gap, not necessarily a false claim)
    """
    body = page_result.get("body_text", "")
    raw = page_result.get("raw_html", "") or ""
    url = _page_url(page_result)
    findings = []

    # Only run on collaboratively-edited domains OR any page with these markers
    is_wiki_domain = bool(WIKI_DOMAIN_RE.search(url))

    # Check both body text and raw HTML (markers may be in <sup> tags)
    combined = body + " " + raw[:50000]
    markers_found = WIKI_MARKERS_RE.findall(combined)

    if not markers_found:
        return findings

    # Group by marker type
    marker_counts = {}
    for m in markers_found:
        key = m.lower().replace(" ", "_")
        marker_counts[key] = marker_counts.get(key, 0) + 1

    HIGH_SEVERITY_MARKERS = {"citation_needed", "verification_needed", "dubious", "disputed"}
    LOW_SEVERITY_MARKERS = {"dead_link", "needs_update", "clarification_needed",
                            "unreliable_source?", "unreliable_source"}

    for marker, count in marker_counts.items():
        if marker in HIGH_SEVERITY_MARKERS:
            severity = "medium"
        else:
            severity = "low"

        # Find a claim snippet near the marker
        clean_marker = marker.replace("_", " ")
        pattern = re.compile(
            r"(.{0,80})\[" + re.escape(clean_marker) + r"\](.{0,80})",
            re.IGNORECASE,
        )
        m_obj = pattern.search(combined)
        claim_snippet = (
            (m_obj.group(1) + f"[{clean_marker}]" + m_obj.group(2)).strip()[:160]
            if m_obj else f"[{clean_marker}]"
        )

        findings.append(_make_finding(
            "FS-06",
            f"Self-reported corroboration gap: [{clean_marker}] ({count}× on page)",
            severity,
            (f"Page {url} contains {count} instance(s) of '[{clean_marker}]' — "
             f"a self-reported corroboration gap. Example: '{claim_snippet}'."),
            (f"Source or remove the flagged claim — the page already self-reports "
             f"a corroboration gap via an inline '[{clean_marker}]' marker. "
             "Unsourced claims reduce AI assistant trust in the page's factual content."),
            severity,
        ))

    return findings


# ── Main entry point ──────────────────────────────────────────────────────────

def run_fs_checks(page_result: dict, current_date: date = None) -> dict:
    """
    Run all FS checks on a single page_result dict.

    Returns:
    {
      "url":            str,
      "findings":       [ <scored finding dicts> ],
      "flag_only_items":[ <flag_only dicts from emit_flag_only()> ],
      "strengths":      [ <strength dicts> ],
    }

    Precondition: call only after crawl-render-audit has confirmed the page
    is accessible (not blocked/noindex). The orchestrator enforces this.
    """
    url = _page_url(page_result)
    out = {
        "url": url,
        "findings": [],
        "flag_only_items": [],
        "strengths": [],
    }
    F = out["findings"]
    FL = out["flag_only_items"]
    S = out["strengths"]

    # ── FS-06 FIRST on wiki-style domains (free, high-confidence signal) ─────
    # Even on non-wiki domains, FS-06 runs — markers can appear anywhere.
    fs06 = check_fs06(page_result)
    F.extend(fs06)

    # ── FS-01: Stale date claims ──────────────────────────────────────────────
    fs01 = check_fs01(page_result, current_date=current_date)
    F.extend(fs01)

    # ── FS-02: Internal numeric inconsistency ─────────────────────────────────
    # LLM judgment step: confirm mismatches are genuine (documented in SKILL.md)
    fs02 = check_fs02(page_result)
    F.extend(fs02)

    # ── FS-03: No freshness signal ────────────────────────────────────────────
    # Same confidence-tier rule as DV-03 (not_detected_in_pass if text-only)
    fs03 = check_fs03(page_result)
    if fs03:
        F.append(fs03)

    # ── FS-04: Nav/footer listing mismatches ─────────────────────────────────
    fs04 = check_fs04(page_result)
    F.extend(fs04)

    # ── FS-05: External corroboration gap (flag-only) ─────────────────────────
    fs05 = check_fs05_flag_only(page_result)
    if fs05.get("_strength"):
        S.append(fs05)
    else:
        FL.append(fs05)

    return out
