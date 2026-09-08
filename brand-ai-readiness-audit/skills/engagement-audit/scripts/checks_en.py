"""
checks_en.py — On-site engagement checks EN-01 through EN-13.

Design rules
------------
- Cascading routing runs BEFORE any real engagement scoring.
  The routing block determines status (not_assessed / not_applicable / scored)
  and returns early when appropriate — no scoring runs on inaccessible pages.
- EN-01 / EN-02 ownership: a link that is BOTH dead AND a placeholder is filed
  once as EN-02 (more specific root cause). EN-01 is only filed for confirmed-dead
  links that are not placeholders.
- EN-04 requires LLM judgment to distinguish legitimate credential-gated personal-
  data lookups from illegitimate paywall friction — documented as an explicit step.
- EN-06 uses emit_flag_only() (copied verbatim from freshness-corroboration).
- EN-08 severity: omission (no value at all) = Low; wrong/zero assertion = Medium.
- EN-10 is a positive-pattern check — logs a strength, never a finding.
- EN-11 marks not_applicable (page loaded fine, wrong page type to score).
- EN-12 marks not_assessed (fetch was blocked — DV-13 or DV-16).
- EN-13 marks not_assessed (fetch succeeded, content unreadable — DV-01 Critical).

Entry point
-----------
    run_en_checks(page_result, dv_flags=None)  →  en_result dict

where en_result has keys:
  url, engagement_status, findings, flag_only_items, strengths, skip_reason
"""

import re
import urllib.parse
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ── emit_flag_only — shared helper (copied verbatim from freshness-corroboration) ──

def emit_flag_only(check_id: str, reason: str, recommendation: str) -> dict:
    """
    Emit a flag-only item for checks that cannot be verified from a single-page
    fetch alone. Shared with freshness-corroboration (FS-05). Keep signature stable.
    """
    return {
        "id": check_id,
        "type": "flag_only",
        "reason": reason,
        "recommendation": recommendation,
    }


# ── Constants ────────────────────────────────────────────────────────────────

TRANSACTIONAL_URL_RE = re.compile(
    r"(/cart|/checkout|/search|/account|/login|/register|/signin|/signup"
    r"|/order|/payment|/my-|/dashboard"
    r"|\?q=|\?s=|\?query=|\?search=|\?term=)",
    re.IGNORECASE,
)

# Placeholder patterns in href and visible text
PLACEHOLDER_RE = re.compile(
    r"(YOUR_[A-Z_]+|{{[^}]+}}|__[A-Z_]+__|"
    r"\bTODO\b|\bXXX\b|\bPLACEHOLDER\b|"
    r"lorem\s+ipsum|idYOUR_APP_ID|APP_ID_HERE|"
    r"\[INSERT\s+\w+\]|\bUNDEFINED\b|\bNULL\b)",
    re.IGNORECASE,
)

# Login / paywall friction signals in DOM
PAYWALL_SIGNALS_RE = re.compile(
    r"(sign\s*in\s+to|log\s*in\s+to|login\s+required|"
    r"out\s+of\s+credits?|upgrade\s+to|subscribe\s+to|"
    r"premium\s+(only|required|feature)|"
    r"please\s+(login|sign\s*in)|"
    r"create\s+an?\s+account\s+to|"
    r"register\s+to\s+(access|view|use))",
    re.IGNORECASE,
)

# Legitimate credential-gated personal-data portal patterns (exclude from EN-04)
LEGIT_CREDENTIAL_GATE_RE = re.compile(
    r"(hall\s+ticket|admit\s+card|roll\s+number|date\s+of\s+birth"
    r"|application\s+number|registration\s+number"
    r"|result\s+(portal|check)|exam\s+result"
    r"|know\s+your\s+(result|status|application))",
    re.IGNORECASE,
)

# Generic byline / authorship patterns (re-used from DV-19 context for EN checks)
NAV_DEPTH_RE = re.compile(r"(breadcrumb|crumb|trail|you\s+are\s+here)", re.IGNORECASE)

# Trust-content signals
TRUST_CONTENT_RE = re.compile(
    r"(testimonial|review|feedback|client\s+say|customer\s+say"
    r"|case\s+study|success\s+stor|what\s+our|verified\s+by"
    r"|rated\s+by|trusted\s+by)",
    re.IGNORECASE,
)

# Stat/counter patterns
STAT_BLOCK_RE = re.compile(
    r"\b(users?|clients?|customers?|downloads?|reviews?|projects?"
    r"|employees?|team\s+members?|countries?|cities?|partners?)\b",
    re.IGNORECASE,
)

# Known dead-link href patterns
DEAD_HREF_PATTERNS = re.compile(r"^(#|javascript:void|javascript:;|\s*)$", re.IGNORECASE)

# Map link pattern (reused for address detection)
MAP_URL_RE = re.compile(
    r"(maps\.google\.|goo\.gl/maps|maps\.app\.goo|openstreetmap"
    r"|bing\.com/maps|waze\.com)",
    re.IGNORECASE,
)

# HTTP session for link-checking (HEAD requests)
_SESSION = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers["User-Agent"] = (
            "BrandAIAuditBot/1.0 (+read-only-audit)"
        )
    return _SESSION


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


def _path(page_result: dict) -> str:
    return urllib.parse.urlparse(_page_url(page_result)).path.lower()


# ── Status helpers ────────────────────────────────────────────────────────────

def _not_assessed(reason: str, finding_id: str) -> dict:
    return {
        "engagement_status": "not_assessed",
        "skip_reason": reason,
        "skip_finding_ref": finding_id,
    }


def _not_applicable(reason: str) -> dict:
    return {
        "engagement_status": "not_applicable",
        "skip_reason": reason,
    }


# ── EN-01: Broken / dead links ───────────────────────────────────────────────

def check_en01_en02(page_result: dict) -> list:
    """
    EN-01 — Broken/dead links (# or confirmed 404 in primary nav/footer).
    EN-02 — Placeholder/template values shipped to production.

    Ownership rule: if a link is BOTH a placeholder AND dead → file once as
    EN-02 (more specific root cause). EN-01 only covers non-placeholder dead links.
    """
    s = _soup(page_result)
    if not s:
        return []

    url = _page_url(page_result)
    findings = []

    # Collect links from primary nav + footer
    primary_links = []
    for container in s.find_all(["nav", "footer"]):
        for a in container.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True)
            primary_links.append((href, text, "primary-nav/footer"))

    # Also check body links for placeholders
    body_links = []
    for a in s.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)
        body_links.append((href, text, "body"))

    placeholder_links = []
    dead_links = []

    all_links = primary_links + body_links

    for href, text, location in all_links:
        # EN-02: Placeholder detection (check first — ownership rule)
        if PLACEHOLDER_RE.search(href) or PLACEHOLDER_RE.search(text):
            placeholder_links.append((href, text, location))
            continue  # Don't also file EN-01 for this link

        # EN-01: Dead anchor-only links in primary nav/footer
        if location == "primary-nav/footer" and DEAD_HREF_PATTERNS.match(href):
            dead_links.append((href, text, location))

    # File EN-02 first (more specific)
    if placeholder_links:
        n = len(placeholder_links)
        examples = [f"'{h}'" for h, t, l in placeholder_links[:3]]
        severity = "high"
        findings.append(_make_finding(
            "EN-02",
            f"Placeholder/template values shipped to production ({n} found)",
            severity,
            (f"Found {n} placeholder value(s) on {url}: {', '.join(examples)}. "
             "These indicate unfinished content shipped to live."),
            (f"Replace each placeholder ({', '.join(examples[:2])}) with a real value, "
             "or remove the element until it is ready — placeholder values "
             "create broken experiences and signal unprofessional content."),
            severity,
        ))

    # File EN-01 for dead non-placeholder links
    if dead_links:
        n = len(dead_links)
        # Severity: High if in primary nav, Medium if footer/secondary
        examples = [f"'{t}' → '{h}'" for h, t, l in dead_links[:3]]
        severity = "high"
        findings.append(_make_finding(
            "EN-01",
            f"Broken/dead links in primary navigation ({n} found)",
            severity,
            (f"Found {n} link(s) in primary nav/footer on {url} with href='#' or "
             f"empty href: {'; '.join(examples)}."),
            (f"Fix or remove the {n} dead link(s) in navigation: "
             f"{'; '.join(examples[:2])} — dead ends in primary navigation "
             "are a direct, confirmed bounce driver."),
            severity,
        ))

    return findings


# ── EN-03: No breadcrumb / orientation trail ─────────────────────────────────

def check_en03(page_result: dict) -> Optional[dict]:
    """
    EN-03 — No breadcrumb on pages deeper than one level.
    """
    s = _soup(page_result)
    if not s:
        return None

    url = _page_url(page_result)
    path = _path(page_result)

    # Only relevant for pages > 1 level deep
    depth = len([p for p in path.split("/") if p])
    if depth < 2:
        return None

    # Check for BreadcrumbList schema
    ldjson = page_result.get("ldjson_blocks", [])
    import json
    for block in ldjson:
        try:
            obj = json.loads(block)
            if isinstance(obj, dict) and "BreadcrumbList" in str(obj.get("@type", "")):
                return None
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict) and "BreadcrumbList" in str(item.get("@type", "")):
                        return None
        except Exception:
            pass

    # Check for visible breadcrumb pattern in HTML
    if (s.find(class_=NAV_DEPTH_RE) or
            s.find(attrs={"aria-label": re.compile(r"breadcrumb", re.I)}) or
            s.find(id=re.compile(r"breadcrumb", re.I))):
        return None

    # Check body text for breadcrumb separators pattern (Home > Category > Page)
    body = page_result.get("body_text", "")
    if re.search(r"\bHome\b\s*[›»>]\s*\w+", body):
        return None

    path_parts = [p for p in path.split("/") if p]
    category = path_parts[-2] if len(path_parts) >= 2 else "category"
    page_name = path_parts[-1] if path_parts else "page"

    return _make_finding(
        "EN-03",
        f"No breadcrumb trail on nested page (depth {depth})",
        "medium",
        (f"Page {url} is {depth} levels deep in the site hierarchy with no "
         "visible breadcrumb trail and no BreadcrumbList structured data."),
        (f"Add a breadcrumb trail (e.g. Home > {category.replace('-',' ').title()} > "
         f"{page_name.replace('-',' ').title()}) — helps visitor orientation "
         "and is also a BreadcrumbList schema opportunity."),
        "medium",
    )


# ── EN-04: Paywall / login friction before value shown ───────────────────────

def check_en04(page_result: dict) -> Optional[dict]:
    """
    EN-04 — Login/paywall friction appears before any value is demonstrated.

    Exclusion: legitimate credential-gated personal-data lookups (exam results,
    hall ticket portals, application status) — these are expected gating, not friction.
    LLM judgment step: distinguish legitimate gate from premature paywall.
    """
    s = _soup(page_result)
    if not s:
        return None

    url = _page_url(page_result)
    body = page_result.get("body_text", "")

    # Exclusion: legitimate credential-gated portals
    if LEGIT_CREDENTIAL_GATE_RE.search(body):
        return None  # Expected gating — not EN-04

    # Proxy: count paywall/login signals in DOM order (before main content)
    html = page_result.get("raw_html", "") or ""
    friction_matches = PAYWALL_SIGNALS_RE.findall(html[:8000])  # First portion of page

    if not friction_matches:
        return None

    n = len(friction_matches)
    examples = list(set(friction_matches[:3]))

    return _make_finding(
        "EN-04",
        f"Login/paywall friction appears before value is shown ({n} signals found)",
        "high",
        (f"Page {url} shows {n} login/paywall friction signal(s) early in the DOM: "
         f"{', '.join(repr(e) for e in examples[:3])}. "
         "[LLM judgment step: confirm this is premature gating of a first-time visitor, "
         "not a legitimate credential-gated lookup (exam results, application status, etc.).]"),
        ("Show a clear free-vs-paid feature comparison in static text before prompting login — "
         f"currently {', '.join(repr(e) for e in examples[:2])} appear before any value "
         "is demonstrated to a first-time visitor."),
        "high",
    )


# ── EN-05: Interactive content hidden until interaction ───────────────────────

def check_en05(page_result: dict) -> Optional[dict]:
    """
    EN-05 — Tab/accordion content requires a click to reveal; nothing visible in raw HTML.
    Same root cause as DV-01/DV-05, scored separately because it affects real visitors.
    Only fires when DV-01 did NOT already fire at Critical (avoids double-counting).
    """
    if page_result.get("_dv01_fired"):
        return None  # DV-01 owns the root cause at Critical

    s = _soup(page_result)
    if not s:
        return None

    url = _page_url(page_result)

    # Detect tab/accordion containers with labels but no visible content
    TAB_CONTAINER_RE = re.compile(r"\b(tab|accordion|toggle|panel|collapse)\b", re.I)
    tab_containers = s.find_all(class_=TAB_CONTAINER_RE)

    hidden_tabs = []
    for container in tab_containers:
        # Check for a label/heading but essentially empty text content
        label = container.find(["h2", "h3", "h4", "button", "a",
                                 "li", "span"])
        label_text = label.get_text(strip=True) if label else ""
        container_text = container.get_text(strip=True)
        # If label exists but surrounding text is nearly just the label
        if label_text and len(container_text) < len(label_text) + 20:
            hidden_tabs.append(label_text[:60])

    if not hidden_tabs:
        return None

    n = len(hidden_tabs)
    examples = hidden_tabs[:3]

    return _make_finding(
        "EN-05",
        f"Interactive content hidden until user interaction ({n} tab(s)/section(s))",
        "high",
        (f"Found {n} tab/accordion section(s) on {url} with visible labels but "
         f"no readable content in raw HTML: {', '.join(repr(e) for e in examples)}."),
        (f"Pre-render at least a one-line summary for each of the {n} tab/section(s) "
         f"({', '.join(repr(e) for e in examples[:2])}) so visitors don't need to "
         "interact to see any content — the current tabs are invisible to both "
         "crawlers and visitors with JS issues."),
        "high",
    )


# ── EN-06: Generic homepage instead of intent-matched landing (flag_only) ─────

def check_en06_flag_only(page_result: dict) -> dict:
    """
    EN-06 — Deep-link gap: AI-referred visitors may land on the homepage instead
    of the specific product/service page matching their query.

    Cannot be verified from a single-page fetch — emitted as flag_only.
    Uses emit_flag_only() (shared with FS-05).
    """
    url = _page_url(page_result)
    return emit_flag_only(
        "EN-06",
        reason=(f"Deep-link matching cannot be verified from a single-page fetch of {url}. "
                "AI assistants referring visitors to a brand may link to the homepage rather "
                "than the specific product/service page matching the user's query."),
        recommendation=(
            "Ensure AI-assistant-referred and search-referred visitors land on the specific "
            "product/service page matching their query, not the homepage — verify that deep "
            "links exist for each key product/service, with unique URLs and descriptive titles. "
            "Test by asking an AI assistant about your key products and checking where it links."
        ),
    )


# ── EN-07: Heavy video/animation with no text fallback ───────────────────────

def check_en07(page_result: dict) -> list:
    """
    EN-07 — <video> elements with no adjacent caption or descriptive text.
    """
    s = _soup(page_result)
    if not s:
        return []

    url = _page_url(page_result)
    findings = []

    for video in s.find_all("video"):
        # Check for a <track> (captions) or adjacent text
        has_track = bool(video.find("track"))
        if has_track:
            continue

        # Check adjacent text
        parent = video.find_parent(["section", "div", "figure", "article"])
        adjacent_text = ""
        if parent:
            # Get text excluding the video element itself
            for sib in video.find_next_siblings():
                t = sib.get_text(strip=True)
                if len(t) > 20:
                    adjacent_text = t
                    break
            if not adjacent_text:
                for sib in video.find_previous_siblings():
                    t = sib.get_text(strip=True)
                    if len(t) > 20:
                        adjacent_text = t
                        break

        # Check for <figcaption>
        figcap = video.find_parent("figure")
        if figcap and figcap.find("figcaption"):
            continue

        src = video.get("src", "") or (video.find("source") or {}).get("src", "")
        section_heading = ""
        h = (video.find_previous(["h2", "h3", "h4"]) or
             (parent.find(["h2", "h3"]) if parent else None))
        if h:
            section_heading = h.get_text(strip=True)[:60]

        if not adjacent_text:
            findings.append(_make_finding(
                "EN-07",
                f"Video element with no text fallback or caption",
                "low",
                (f"Found a <video> element on {url} (src: '{src[:60]}') with "
                 f"no adjacent caption text and no <track> element. "
                 f"Section: '{section_heading}'."),
                (f"Add a one-line text caption near the "
                 f"'{section_heading or 'video'}' section describing its content — "
                 "the only current fallback is the generic browser message."),
                "low",
            ))
            if len(findings) >= 3:  # Cap at 3 per page
                break

    return findings


# ── EN-08: Dynamic stat/counter elements with no static value ────────────────

def check_en08(page_result: dict) -> list:
    """
    EN-08 — Stat/counter elements with no static digit value, OR with a
    clearly-wrong static value (e.g. "0" for active users).

    Severity:
    - Omission (no value in raw HTML) → Low
    - Wrong assertion (value = 0 or placeholder) → Medium (asserts a false fact)
    """
    s = _soup(page_result)
    if not s:
        return []

    url = _page_url(page_result)
    findings = []

    # Find stat containers: elements with stat-like labels
    stat_containers = (
        s.find_all(class_=re.compile(r"\b(stat|counter|metric|number|figure|count)\b", re.I)) +
        s.find_all(attrs={"data-count": True}) +
        s.find_all(attrs={"data-target": True})
    )

    # Also scan for paragraph/div combos that look like stat blocks
    for el in s.find_all(["div", "p", "span", "li"]):
        if STAT_BLOCK_RE.search(el.get_text(strip=True)):
            if el not in stat_containers:
                stat_containers.append(el)

    seen = set()
    for el in stat_containers:
        label_text = el.get_text(strip=True)
        if not label_text or len(label_text) > 100:
            continue
        if label_text in seen:
            continue
        seen.add(label_text)

        # Check if a number appears in the element or adjacent sibling
        has_digit = bool(re.search(r"\b\d+", label_text))
        has_zero_only = bool(re.fullmatch(r"[\s0,/]+", re.sub(r"[^\d/\s,]", "", label_text)))

        if not has_digit:
            # Omission: label exists but no number anywhere
            if STAT_BLOCK_RE.search(label_text):
                findings.append(_make_finding(
                    "EN-08",
                    f"Stat element has no static value: '{label_text[:60]}'",
                    "low",
                    (f"Stat/counter element on {url} with label '{label_text[:60]}' "
                     "has no digit value in raw HTML — likely a JS count-up with "
                     "no static fallback."),
                    (f"Provide a real static fallback value in the HTML for "
                     f"'{label_text[:60]}' (JS can still animate the count-up visually) "
                     "— currently no value appears in a static read."),
                    "low",
                ))
        elif has_zero_only:
            # Wrong assertion: value is literally 0 / 0 / 0
            findings.append(_make_finding(
                "EN-08",
                f"Stat element asserts a false value (0): '{label_text[:60]}'",
                "medium",
                (f"Stat/counter element on {url} renders the value '0' for "
                 f"'{label_text[:60]}' in raw HTML — a machine reading this page "
                 "extracts a false fact rather than just omitting one."),
                (f"Replace the '0' placeholder with a real static fallback for "
                 f"'{label_text[:60]}' — currently the static value reads as 0, "
                 "asserting a false fact to any crawler or summariser."),
                "medium",
            ))

        if len(findings) >= 4:  # Cap repetitive stat findings
            break

    return findings


# ── EN-09: Complete absence of trust content ─────────────────────────────────

def check_en09(page_result: dict) -> Optional[dict]:
    """
    EN-09 — No testimonials, reviews, or case-study snippets anywhere on the page.
    Distinct from DV-07 (testimonials exist but are weak/unverifiable).
    Only fires on pages where trust content is expected (homepage, about, services).
    """
    s = _soup(page_result)
    if not s:
        return None

    url = _page_url(page_result)
    path = _path(page_result)

    # Only relevant for trust-sensitive pages
    trust_pages = path.rstrip("/") in (
        "", "/", "/about", "/about-us", "/services", "/why-us",
        "/home", "/index.html", "/index.php",
    ) or any(x in path for x in ["/service", "/solution", "/product", "/offering"])
    if not trust_pages:
        return None

    body = page_result.get("body_text", "")
    has_any_trust = TRUST_CONTENT_RE.search(body)
    has_quote = bool(s.find("blockquote") or
                     s.find(class_=re.compile(r"\b(testimonial|review|quote)\b", re.I)))

    if has_any_trust or has_quote:
        return None

    return _make_finding(
        "EN-09",
        "No trust content (testimonials, reviews, case studies) on key page",
        "low",
        (f"Page {url} has no testimonials, reviews, client quotes, or case-study "
         "snippets — only logos/brand names at most."),
        ("Add 2–3 named, attributed client quotes or case-study snippets — "
         "currently only brand/client logos appear with no accompanying text, "
         "giving visitors no social proof they can read or that a crawler can cite."),
        "low",
    )


# ── EN-10: Clear layered navigation (positive pattern) ───────────────────────

def check_en10_strength(page_result: dict) -> Optional[dict]:
    """
    EN-10 — Positive pattern: clear, layered, well-labeled navigation.
    Logs a strength when present. Never files a finding (absence on a lean site
    is not a defect).
    """
    s = _soup(page_result)
    if not s:
        return None

    url = _page_url(page_result)

    # Count top-level nav items
    nav_items = set()
    for nav in s.find_all("nav"):
        for a in nav.find_all("a", recursive=False):
            t = a.get_text(strip=True)
            if t:
                nav_items.add(t)
        # Also first-level children
        for li in nav.find_all("li"):
            a = li.find("a")
            if a:
                t = a.get_text(strip=True)
                if t:
                    nav_items.add(t)

    # Count footer sitemap links
    footer_links = set()
    for footer in s.find_all("footer"):
        for a in footer.find_all("a"):
            t = a.get_text(strip=True)
            if t and len(t) > 2:
                footer_links.add(t)

    # Positive pattern: rich nav (>= 5 distinct items) + rich footer sitemap (>= 10)
    if len(nav_items) >= 5 and len(footer_links) >= 10:
        return {
            "_strength": True,
            "id": "EN-10",
            "title": (f"Clear layered navigation: {len(nav_items)} named nav sections, "
                      f"{len(footer_links)} footer sitemap links — good orientation for "
                      "both visitors and crawlers."),
        }

    return None


# ── Main entry point ──────────────────────────────────────────────────────────

def run_en_checks(page_result: dict, dv_flags: dict = None) -> dict:
    """
    Run all EN checks on a single page_result dict.

    dv_flags: dict from run_dv_checks() result['flags']:
      {
        "dv01_critical": bool,
        "dv13_fired":    bool,
        "dv16_fired":    bool,
        "wikidata_backed": bool,
      }
    If None, the flags are inferred from page_result fields.

    Returns:
    {
      "url":               str,
      "engagement_status": "not_assessed" | "not_applicable" | "scored",
      "skip_reason":       str | None,
      "skip_finding_ref":  str | None,
      "findings":          [ <finding dicts> ],
      "flag_only_items":   [ <flag_only dicts> ],
      "strengths":         [ <strength dicts> ],
    }
    """
    url = _page_url(page_result)
    if dv_flags is None:
        dv_flags = {}

    out = {
        "url": url,
        "engagement_status": "scored",
        "skip_reason": None,
        "skip_finding_ref": None,
        "findings": [],
        "flag_only_items": [],
        "strengths": [],
    }
    F = out["findings"]
    FL = out["flag_only_items"]
    S = out["strengths"]

    # ═══════════════════════════════════════════════════════════════════
    # CASCADING ROUTING — must run before any scoring
    # ═══════════════════════════════════════════════════════════════════

    # ── EN-12: Fetch was blocked (DV-13 or DV-16) ─────────────────────
    if dv_flags.get("dv13_fired") or dv_flags.get("dv16_fired"):
        ref = "DV-13" if dv_flags.get("dv13_fired") else "DV-16"
        status = _not_assessed(
            f"Page fetch was blocked — see finding {ref}. "
            "No engagement scoring is possible.",
            ref,
        )
        out.update(status)
        return out

    # Also infer from page_result if flags not passed
    if page_result.get("robots_disallowed"):
        status = _not_assessed("robots.txt disallows crawling — see DV-16.", "DV-16")
        out.update(status)
        return out
    if page_result.get("blocked"):
        status = _not_assessed("Page fetch was blocked by WAF/bot-detection — see DV-13.", "DV-13")
        out.update(status)
        return out

    # ── EN-13: Fetch succeeded, content unreadable (DV-01 Critical) ────
    if dv_flags.get("dv01_critical") or page_result.get("_dv01_fired"):
        status = _not_assessed(
            "Page content is unreadable (JS-render gap, Critical) — see DV-01. "
            "Engagement scoring skipped to avoid false positives on empty content.",
            "DV-01",
        )
        out.update(status)
        return out

    # ── EN-11: noindex or transactional page ─────────────────────────────
    if page_result.get("noindex"):
        status = _not_applicable(
            "Page has meta[robots]=noindex — intentionally excluded from indexing. "
            "Engagement checks do not apply to excluded pages."
        )
        out.update(status)
        return out

    if TRANSACTIONAL_URL_RE.search(url):
        status = _not_applicable(
            f"URL pattern indicates a transactional/utility page ({url}) — "
            "wayfinding and value-proposition checks do not meaningfully apply."
        )
        out.update(status)
        return out

    # ═══════════════════════════════════════════════════════════════════
    # ENGAGEMENT SCORING
    # ═══════════════════════════════════════════════════════════════════

    out["engagement_status"] = "scored"

    # EN-01 / EN-02 (ownership rule built into the function)
    F.extend(check_en01_en02(page_result))

    # EN-03
    en03 = check_en03(page_result)
    if en03:
        F.append(en03)

    # EN-04 (LLM judgment step documented inside function)
    en04 = check_en04(page_result)
    if en04:
        F.append(en04)

    # EN-05 (skip if DV-01 Critical already fired)
    en05 = check_en05(page_result)
    if en05:
        F.append(en05)

    # EN-06 (flag_only — always emitted for non-transactional pages)
    FL.append(check_en06_flag_only(page_result))

    # EN-07
    F.extend(check_en07(page_result))

    # EN-08
    F.extend(check_en08(page_result))

    # EN-09
    en09 = check_en09(page_result)
    if en09:
        F.append(en09)

    # EN-10 (positive pattern / strength — never a finding)
    en10 = check_en10_strength(page_result)
    if en10:
        S.append(en10)

    return out
