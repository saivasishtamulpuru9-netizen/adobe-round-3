"""
checks_ed.py — Entity disambiguation checks ED-01 through ED-06.

Design rules
------------
- All ED checks skip if `wikidata_backed = true` from DV flags — entity
  identity is already resolved via the Wikidata graph.
- ED-01 (name collision) runs first; its output sets `_ed01_fired` on the
  page_result so ED-02 and ED-06 can use it as a precondition gate.
- ED-02 only fires when ED-01 fired (collision risk exists) AND DV-03 also fired
  or Organization schema is present but lacks `identifier`/`sameAs` fields.
- ED-06 is flag_only (requires external search — cannot verify from one fetch).
- The `emit_flag_only` helper is copied verbatim from freshness-corroboration.

Entry point
-----------
    run_ed_checks(page_result, dv_flags=None, dv_findings=None)  →  ed_result dict

where ed_result has keys: url, findings, flag_only_items, strengths.
"""

import json
import re
import urllib.parse
from typing import Optional

from bs4 import BeautifulSoup

# ── emit_flag_only — shared helper ────────────────────────────────────────────

def emit_flag_only(check_id: str, reason: str, recommendation: str) -> dict:
    return {
        "id": check_id,
        "type": "flag_only",
        "reason": reason,
        "recommendation": recommendation,
    }


# ── Constants ─────────────────────────────────────────────────────────────────

# Common English words / generic terms that brand names often collide with
GENERIC_WORDS = frozenset({
    "apple", "amazon", "oracle", "lotus", "spring", "mercury", "aurora",
    "atlas", "nexus", "apex", "vertex", "prism", "fusion", "vector",
    "matrix", "alpha", "beta", "gamma", "delta", "sigma", "omega",
    "nova", "sol", "arc", "peak", "edge", "core", "base", "hub",
    "cloud", "wave", "flow", "link", "bridge", "forge", "spark",
    "bolt", "blade", "flash", "stream", "pulse", "signal", "echo",
    "canvas", "frame", "scale", "shift", "stride", "sprint", "agile",
    "lean", "boost", "surge", "lift", "launch", "prime", "first",
    "global", "national", "united", "central", "general", "standard",
    "universal", "pacific", "pioneer", "frontier", "horizon", "summit",
    "pinnacle", "zenith", "acme", "star", "moon", "sun", "sky",
})

# Brand name casing inconsistency patterns
CAMEL_SPLIT_RE = re.compile(r'(?<=[a-z])(?=[A-Z])')

# Social profile domain patterns
SOCIAL_DOMAINS_RE = re.compile(
    r"(linkedin\.com|twitter\.com|x\.com|facebook\.com|instagram\.com"
    r"|youtube\.com|github\.com|threads\.net|tiktok\.com|pinterest\.com"
    r"|crunchbase\.com|glassdoor\.com|g2\.com|clutch\.co)",
    re.IGNORECASE,
)

# Known ambiguous abbreviation patterns (org names that are also well-known acronyms)
KNOWN_ACRONYM_COLLISIONS = frozenset({
    "AI", "ML", "IT", "HR", "PR", "CX", "UX", "UI", "ERP", "CRM",
    "SAP", "IBM", "HP", "GE", "GM", "AMD", "ARM", "API", "SDK",
    "SaaS", "PaaS", "IaaS", "B2B", "B2C", "SEO", "SEM", "ROI",
    "KPI", "OKR", "MVP", "POC", "RFP", "EOD", "ETA", "SLA",
})

# Wikipedia URL pattern
WIKI_URL_RE = re.compile(r"en\.wikipedia\.org/wiki/", re.IGNORECASE)
WIKIDATA_URL_RE = re.compile(r"wikidata\.org/wiki/Q\d+", re.IGNORECASE)

# Legal suffixes to strip when normalizing brand names
LEGAL_SUFFIX_RE = re.compile(
    r"\b(pvt|private|limited|ltd|llc|llp|inc|corp|corporation|co\.|group|holdings?)\b",
    re.IGNORECASE,
)

# Inconsistency patterns across text: detect the same "word" in different cases
INCONSISTENCY_SCORE_THRESHOLD = 0.15  # 15% or more instances in a different case → flag


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _netloc(page_result: dict) -> str:
    return urllib.parse.urlparse(_page_url(page_result)).netloc


def _extract_brand_name(page_result: dict) -> str:
    """
    Extract the brand name from (in order of preference):
    1. Organization JSON-LD 'name' field
    2. og:site_name
    3. og:title (first token before ' – ' or ' | ')
    4. <title> prefix
    5. Domain name (fallback)
    """
    head = page_result.get("head", {})

    # 1. Organization JSON-LD
    for block in page_result.get("ldjson_blocks", []):
        try:
            obj = json.loads(block)
            items = [obj] if isinstance(obj, dict) else (obj if isinstance(obj, list) else [])
            for item in items:
                t = item.get("@type", "")
                types = [t] if isinstance(t, str) else t
                if any(tp in ("Organization", "LocalBusiness", "Corporation",
                              "NGO", "EducationalOrganization", "CollegeOrUniversity")
                       for tp in types):
                    name = item.get("name", "").strip()
                    if name:
                        return name
        except (json.JSONDecodeError, TypeError):
            pass

    # 2. og:site_name
    og_site = head.get("og_site_name", "").strip()
    if og_site:
        return og_site

    # 3. og:title — extract prefix before separator, or use directly if short
    og_title = head.get("og_title", "").strip()
    if og_title:
        for sep in [" – ", " | ", " - ", " :: "]:
            if sep in og_title:
                return og_title.split(sep)[0].strip()
        # No separator found — if it's short enough, it IS the brand name
        if len(og_title) < 40:
            return og_title

    # 4. <title> prefix
    title = head.get("title", "").strip()
    if title:
        for sep in [" – ", " | ", " - ", " :: "]:
            if sep in title:
                return title.split(sep)[0].strip()
        if len(title) < 40:
            return title

    # 5. Domain fallback
    domain = _netloc(page_result).lstrip("www.").split(".")[0]
    return domain.replace("-", " ").replace("_", " ").title()


def _parse_org_schema(page_result: dict) -> Optional[dict]:
    """Return the first Organization-type JSON-LD object found, or None."""
    for block in page_result.get("ldjson_blocks", []):
        try:
            obj = json.loads(block)
            items = [obj] if isinstance(obj, dict) else (obj if isinstance(obj, list) else [])
            for item in items:
                t = item.get("@type", "")
                types = [t] if isinstance(t, str) else t
                if any(tp in ("Organization", "LocalBusiness", "Corporation",
                              "NGO", "EducationalOrganization", "CollegeOrUniversity",
                              "GovernmentOrganization", "SportsOrganization")
                       for tp in types):
                    return item
        except (json.JSONDecodeError, TypeError):
            pass
    return None


# ── ED-01: Name collision risk ────────────────────────────────────────────────

def check_ed01(page_result: dict) -> Optional[dict]:
    """
    ED-01 — Brand name is a common word, short acronym, or generic term that
    collides with other well-known entities.

    Collision tiers:
    - High: name is a known high-collision acronym (IBM, HP, AI, etc.)
    - Medium: name is a generic English word in our collision wordlist
    - Low: name is very short (≤ 3 chars) with no disambiguating schema
    - No finding: name is unique enough (not in any collision category)

    Side effect: sets page_result['_ed01_fired'] = True when a finding is emitted,
    so ED-02 and ED-06 can use it as a gate.
    """
    brand = _extract_brand_name(page_result)
    if not brand:
        return None

    url = _page_url(page_result)
    brand_clean = LEGAL_SUFFIX_RE.sub("", brand).strip()
    brand_lower = brand_clean.lower().strip()
    brand_upper = brand_clean.upper().strip()

    # Check for disambiguating context in structured data
    org_schema = _parse_org_schema(page_result)
    has_same_as = bool(org_schema and org_schema.get("sameAs"))
    has_identifier = bool(org_schema and org_schema.get("identifier"))

    # High: known acronym collision
    if brand_upper in KNOWN_ACRONYM_COLLISIONS:
        page_result["_ed01_fired"] = True
        page_result["_ed01_brand"] = brand
        return _make_finding(
            "ED-01",
            f"Brand name '{brand}' is a high-collision acronym",
            "high",
            (f"The brand name '{brand}' ('{brand_upper}') is a well-known acronym used by "
             f"multiple entities. Page: {url}. "
             f"Organization schema sameAs: {'present' if has_same_as else 'absent'}. "
             f"identifier: {'present' if has_identifier else 'absent'}."),
            (f"Add a sameAs identifier (Wikidata Q-number, CIN, or official registry ID) "
             f"to the Organization JSON-LD for '{brand}' — the acronym is shared by "
             "multiple entities and gives AI assistants no way to distinguish this "
             "entity from others using the same letters."),
            "high",
        )

    # Medium: generic word collision
    if brand_lower in GENERIC_WORDS:
        page_result["_ed01_fired"] = True
        page_result["_ed01_brand"] = brand
        return _make_finding(
            "ED-01",
            f"Brand name '{brand}' collides with a common English word",
            "medium",
            (f"Brand name '{brand}' is a common English word in the known collision list. "
             f"Page: {url}. "
             f"Without a disambiguating sameAs or identifier in structured data, "
             f"AI assistants may conflate this entity with other '{brand}' references."),
            (f"Add a sameAs field pointing to a unique external registry (Wikidata, LinkedIn, "
             f"Companies House, GLEIF LEI, or official government registry) to the "
             f"Organization JSON-LD for '{brand}'."),
            "medium",
        )

    # Low: very short name (≤ 3 chars) with no disambiguating schema
    if len(brand_clean) <= 3 and not has_same_as and not has_identifier:
        page_result["_ed01_fired"] = True
        page_result["_ed01_brand"] = brand
        return _make_finding(
            "ED-01",
            f"Brand name '{brand}' is very short and lacks disambiguation",
            "low",
            (f"Brand name '{brand}' is only {len(brand_clean)} character(s). "
             f"Page: {url}. "
             "Short names are inherently ambiguous without an external identifier."),
            (f"Add a sameAs or legalName field to the Organization JSON-LD to disambiguate "
             f"'{brand}' — short names can collide with many other entities of the same letters."),
            "low",
        )

    return None


# ── ED-02: Organization schema missing identifier / sameAs ───────────────────

def check_ed02(page_result: dict) -> Optional[dict]:
    """
    ED-02 — Organization schema present but lacks `identifier`, `sameAs`, or
    `legalName` — fires only when ED-01 (collision risk) also fired.

    Boundary vs. DV-03: DV-03 fires "no schema at all"; ED-02 fires "schema present
    but lacks disambiguation fields" — AND only when a name-collision risk exists.
    Never fire DV-03 and ED-02 for the same issue.
    """
    if not page_result.get("_ed01_fired"):
        return None  # Only relevant when collision risk has been identified

    org = _parse_org_schema(page_result)
    if not org:
        # No schema at all → DV-03 already fired or will fire; ED-02 does not fire
        return None

    url = _page_url(page_result)
    brand = page_result.get("_ed01_brand", _extract_brand_name(page_result))

    missing = []
    if not org.get("sameAs"):
        missing.append("sameAs")
    if not org.get("identifier"):
        missing.append("identifier")
    if not org.get("legalName"):
        missing.append("legalName")

    if not missing:
        return None  # All disambiguation fields present

    return _make_finding(
        "ED-02",
        f"Organization schema present for '{brand}' but lacks: {', '.join(missing)}",
        "medium",
        (f"Page {url} has an Organization JSON-LD block for '{brand}' but is "
         f"missing disambiguation fields: {', '.join(missing)}. "
         f"Combined with the name-collision risk (ED-01), this leaves AI assistants "
         "with no machine-readable way to uniquely identify this entity."),
        (f"Add {', '.join(missing)} to the Organization JSON-LD — "
         f"recommended sameAs values: Wikidata Q-number, LinkedIn company URL, "
         "GLEIF LEI, or official government registry entry."),
        "medium",
    )


# ── ED-03: Inconsistent brand name spelling / casing ────────────────────────

def check_ed03(page_result: dict) -> Optional[dict]:
    """
    ED-03 — Same brand name appears with different spelling or casing across
    the page (e.g. 'MyBrand' vs 'My Brand' vs 'mybrand' vs 'MYBRAND').

    Script-able heuristic: extract all instances of the inferred brand name
    token from body text, then bucket by normalized form and check variance.
    """
    brand = _extract_brand_name(page_result)
    if not brand or len(brand) < 3:
        return None

    url = _page_url(page_result)
    body = page_result.get("body_text", "")

    # Build variants of the brand name to search for
    brand_core = LEGAL_SUFFIX_RE.sub("", brand).strip()
    # Remove spaces for token comparison
    brand_token = re.sub(r"\s+", "", brand_core)
    if len(brand_token) < 3:
        return None

    # Find all occurrences of the brand token (as a word boundary match, case-insensitive)
    # Allow for spaces within the brand (e.g. "My Brand" and "MyBrand")
    pattern_nospace = re.compile(
        r"\b" + re.escape(brand_token) + r"\b", re.IGNORECASE
    )
    # Also find spaced variants
    spaced = " ".join(CAMEL_SPLIT_RE.sub(" ", brand_token).split())
    pattern_spaced = re.compile(
        r"\b" + re.escape(spaced) + r"\b", re.IGNORECASE
    ) if spaced != brand_token else None

    found_forms: dict = {}
    for m in pattern_nospace.finditer(body):
        form = m.group()
        found_forms[form] = found_forms.get(form, 0) + 1

    if pattern_spaced:
        for m in pattern_spaced.finditer(body):
            form = m.group()
            found_forms[form] = found_forms.get(form, 0) + 1

    if len(found_forms) < 2:
        return None  # Only one form found — no inconsistency

    total = sum(found_forms.values())
    dominant_form = max(found_forms, key=found_forms.get)
    dominant_count = found_forms[dominant_form]
    minority_forms = {k: v for k, v in found_forms.items() if k != dominant_form}

    minority_count = sum(minority_forms.values())
    inconsistency_ratio = minority_count / total if total else 0

    if inconsistency_ratio < INCONSISTENCY_SCORE_THRESHOLD:
        return None  # Negligible variance — likely a heading vs body casing difference

    minority_examples = list(minority_forms.keys())[:3]

    return _make_finding(
        "ED-03",
        (f"Brand name casing inconsistency: '{dominant_form}' ({dominant_count}×) "
         f"vs {[repr(f) for f in minority_examples]} ({minority_count}×)"),
        "medium",
        (f"Page {url} uses '{dominant_form}' as the brand name {dominant_count} time(s) "
         f"but also uses {minority_examples} ({minority_count} total minority instances, "
         f"{round(inconsistency_ratio * 100)}% inconsistency rate). "
         "AI assistants that extract brand names from text will encounter multiple "
         "forms and may treat them as different entities."),
        (f"Standardise the brand name to a single canonical form ('{dominant_form}') "
         f"across all occurrences — currently {len(minority_forms)} variant form(s) appear "
         f"at a {round(inconsistency_ratio * 100)}% inconsistency rate."),
        "medium",
    )


# ── ED-04: No official social profile links ──────────────────────────────────

def check_ed04(page_result: dict) -> Optional[dict]:
    """
    ED-04 — No official social profile links in footer, header, or Organization
    schema sameAs — prevents corroboration of entity identity via social graph.

    Strength: if social links ARE present in sameAs structured data (machine-readable).
    Finding: if no social links anywhere (text OR structured data).
    Medium finding: if social links exist in DOM but not in sameAs (less machine-readable).
    """
    s = _soup(page_result)
    if not s:
        return None

    url = _page_url(page_result)
    brand = _extract_brand_name(page_result)

    # Check structured data sameAs (machine-readable)
    org = _parse_org_schema(page_result)
    schema_social_links = []
    if org:
        same_as = org.get("sameAs", [])
        if isinstance(same_as, str):
            same_as = [same_as]
        schema_social_links = [l for l in same_as if SOCIAL_DOMAINS_RE.search(l)]

    # Check DOM links (footer, header) for social profiles
    dom_social_links = []
    for container in s.find_all(["footer", "header", "nav"]):
        for a in container.find_all("a", href=True):
            if SOCIAL_DOMAINS_RE.search(a["href"]):
                dom_social_links.append(a["href"])

    # Also check all links on page
    all_social_links = []
    for a in s.find_all("a", href=True):
        if SOCIAL_DOMAINS_RE.search(a["href"]):
            all_social_links.append(a["href"])

    if schema_social_links:
        # Machine-readable social identity — log as strength, no finding
        return {
            "_strength": True,
            "id": "ED-04-STRENGTH",
            "title": (f"Social profile links present in Organization sameAs for '{brand}': "
                      f"{schema_social_links[:2]} — entity identity corroborable via social graph."),
        }

    if not all_social_links:
        # Completely absent — Medium finding
        return _make_finding(
            "ED-04",
            f"No official social profile links found for '{brand}'",
            "medium",
            (f"Page {url} has no links to official social profiles (LinkedIn, Twitter/X, "
             f"Facebook, GitHub, etc.) in DOM or structured data sameAs."),
            (f"Add official social profile URLs for '{brand}' to the footer "
             f"AND to the Organization JSON-LD sameAs field — social profiles "
             "allow AI assistants to corroborate entity identity across platforms."),
            "medium",
        )

    if dom_social_links and not schema_social_links:
        # DOM links present but not in schema — Low finding (usability ≥ 0, machine-readability < ideal)
        examples = dom_social_links[:2]
        return _make_finding(
            "ED-04",
            f"Social links present in DOM but not in Organization schema sameAs",
            "low",
            (f"Page {url} links to social profiles ({', '.join(examples[:2])}) "
             "from the page DOM, but these are not included in the Organization "
             "JSON-LD sameAs field for machine-readable entity corroboration."),
            (f"Add the social profile URLs ({', '.join(examples[:2])}) to the "
             f"Organization JSON-LD sameAs array — DOM links help human visitors "
             "but structured-data sameAs is what AI assistants and knowledge graph "
             "indexers use to associate social profiles with the brand entity."),
            "low",
        )

    return None


# ── ED-05: Wikipedia/Wikidata entry not linked ───────────────────────────────

def check_ed05(page_result: dict, wikidata_backed: bool = False) -> dict:
    """
    ED-05 — Wikipedia/Wikidata relationship check.

    Three outcomes:
    - wikidata_backed = True (set by DV flags): log as STRENGTH (sameAs already linked)
      and return early — no finding.
    - Wikipedia/Wikidata link found in DOM but NOT in sameAs: Medium finding
      (free knowledge-graph signal wasted by not formalising it in schema).
    - No Wikipedia/Wikidata link at all: flag_only (external search step required
      to confirm whether an entry exists).
    """
    url = _page_url(page_result)
    brand = _extract_brand_name(page_result)
    raw = page_result.get("raw_html", "") or ""

    if wikidata_backed:
        return {
            "_strength": True,
            "id": "ED-05-STRENGTH",
            "title": (f"Wikidata sameAs link confirmed for '{brand}' — "
                      "entity identity is anchored to the Wikidata knowledge graph."),
        }

    # Check for Wikipedia link in DOM
    has_wiki_dom = bool(WIKI_URL_RE.search(raw))
    has_wikidata_dom = bool(WIKIDATA_URL_RE.search(raw))

    # Check whether it's also in sameAs
    org = _parse_org_schema(page_result)
    same_as = org.get("sameAs", []) if org else []
    if isinstance(same_as, str):
        same_as = [same_as]
    wiki_in_schema = any(WIKI_URL_RE.search(l) or WIKIDATA_URL_RE.search(l) for l in same_as)

    if has_wiki_dom or has_wikidata_dom:
        if wiki_in_schema:
            return {
                "_strength": True,
                "id": "ED-05-STRENGTH",
                "title": (f"Wikipedia/Wikidata link present in both DOM and Organization "
                          f"sameAs for '{brand}' — entity identity machine-readable."),
            }
        else:
            # DOM link present but not in schema
            return _make_finding(
                "ED-05",
                f"Wikipedia/Wikidata linked in DOM but not in Organization schema sameAs",
                "medium",
                (f"Page {url} links to Wikipedia/Wikidata from the DOM but does not "
                 "include this URL in the Organization JSON-LD sameAs field."),
                (f"Add the Wikipedia/Wikidata URL to the Organization JSON-LD sameAs array "
                 f"for '{brand}' — it's already linked from the DOM; formalising it in "
                 "structured data makes the entity-identity connection machine-readable."),
                "medium",
            )

    # No Wikipedia/Wikidata link at all — flag_only (external search required)
    return emit_flag_only(
        "ED-05",
        reason=(f"No Wikipedia or Wikidata link found on {url} for '{brand}'. "
                "An external search step is required to determine whether a Wikipedia "
                "or Wikidata entry exists for this entity."),
        recommendation=(
            f"Search Wikipedia for '{brand}' and Wikidata for a Q-number. "
            "If an entry exists: add the URL to the Organization sameAs field "
            "to anchor entity identity. "
            "If no entry exists: consider creating a neutral, sourced Wikipedia "
            "stub or a Wikidata entry — this provides the strongest possible "
            "machine-readable identity signal for AI assistants."
        ),
    )


# ── ED-06: Ambiguous founding / identity facts (flag_only) ───────────────────

def check_ed06_flag_only(page_result: dict) -> Optional[dict]:
    """
    ED-06 — Founding year, HQ location, or key identity facts that may conflict
    with third-party encyclopedic sources.

    Only fires when ED-01 (collision risk) also fired — ambiguity is more
    dangerous when the name itself is colliding.

    Always flag_only — confirming factual conflicts requires an external
    encyclopedic lookup (Wikipedia, Wikidata, Companies House, etc.).
    """
    if not page_result.get("_ed01_fired"):
        return None  # Only fire when name-collision risk exists

    brand = page_result.get("_ed01_brand", _extract_brand_name(page_result))
    url = _page_url(page_result)
    body = page_result.get("body_text", "")

    # Proxy: detect founding year, HQ city, or registered name claims in body
    FOUNDING_RE = re.compile(
        r"(founded\s+in\s+\d{4}|established\s+in\s+\d{4}"
        r"|incorporated\s+in\s+\d{4}|since\s+\d{4}"
        r"|headquartered\s+in\s+\w+|registered\s+in\s+\w+"
        r"|our\s+\d{4}\s+founding|born\s+in\s+\d{4})",
        re.IGNORECASE,
    )
    found_claims = FOUNDING_RE.findall(body)
    if not found_claims:
        return None  # No identity facts to check — no value in flagging

    example_claim = found_claims[0][:80]

    return emit_flag_only(
        "ED-06",
        reason=(f"'{brand}' has a high-collision name (see ED-01) and makes "
                f"founding/identity claims (e.g. '{example_claim}') that cannot be "
                f"cross-checked from a single-page fetch alone. "
                f"Page: {url}."),
        recommendation=(
            f"Cross-check the identity claims for '{brand}' "
            f"(e.g. '{example_claim}') against Wikipedia, Wikidata, Companies House, "
            "or the relevant corporate registry to verify they are consistent "
            "with the encyclopedic record. "
            "Incorrect or conflicting founding facts can cause AI assistants "
            "to confuse this entity with another of the same name."
        ),
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def run_ed_checks(page_result: dict,
                  dv_flags: dict = None,
                  dv_findings: list = None) -> dict:
    """
    Run all ED checks on a single page_result dict.

    dv_flags: dict from run_dv_checks() result['flags'].
    dv_findings: list of DV findings (used to check whether DV-03 fired,
                 which affects ED-02 boundary rule).

    Returns:
    {
      "url":             str,
      "findings":        [ <scored finding dicts> ],
      "flag_only_items": [ <flag_only dicts> ],
      "strengths":       [ <strength dicts> ],
    }

    All checks are skipped if wikidata_backed = True in dv_flags.
    """
    url = _page_url(page_result)
    if dv_flags is None:
        dv_flags = {}
    if dv_findings is None:
        dv_findings = []

    out = {
        "url": url,
        "findings": [],
        "flag_only_items": [],
        "strengths": [],
    }
    F = out["findings"]
    FL = out["flag_only_items"]
    S = out["strengths"]

    # ── Skip all ED checks if Wikidata backs the entity ──────────────────────
    wikidata_backed = dv_flags.get("wikidata_backed", False)
    if wikidata_backed:
        S.append({
            "_strength": True,
            "id": "ED-WIKIDATA-SKIP",
            "title": ("All ED checks skipped — entity identity is already anchored to "
                      "the Wikidata knowledge graph (wikidata_backed = true from DV flags)."),
        })
        # ED-05 still gets logged as a strength
        ed05 = check_ed05(page_result, wikidata_backed=True)
        if ed05.get("_strength"):
            S.append(ed05)
        return out

    # ── ED-01: Name collision (must run first; sets _ed01_fired) ──────────────
    ed01 = check_ed01(page_result)
    if ed01:
        F.append(ed01)

    # ── ED-02: Org schema missing identifier/sameAs (gate: ED-01 must fire) ──
    # Also require that at least one Organization schema exists (else DV-03 covers the gap)
    ed02 = check_ed02(page_result)
    if ed02:
        F.append(ed02)

    # ── ED-03: Brand name casing inconsistency ────────────────────────────────
    ed03 = check_ed03(page_result)
    if ed03:
        F.append(ed03)

    # ── ED-04: Social profile links ───────────────────────────────────────────
    ed04 = check_ed04(page_result)
    if ed04:
        if ed04.get("_strength"):
            S.append(ed04)
        else:
            F.append(ed04)

    # ── ED-05: Wikipedia/Wikidata entry not linked ────────────────────────────
    ed05 = check_ed05(page_result, wikidata_backed=False)
    if isinstance(ed05, dict):
        if ed05.get("_strength"):
            S.append(ed05)
        elif ed05.get("type") == "flag_only":
            FL.append(ed05)
        else:
            F.append(ed05)

    # ── ED-06: Ambiguous founding/identity facts (gate: ED-01 must fire) ──────
    ed06 = check_ed06_flag_only(page_result)
    if ed06:
        FL.append(ed06)

    return out
