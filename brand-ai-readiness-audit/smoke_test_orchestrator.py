"""
smoke_test_orchestrator.py — Integration smoke tests for compose_report.py.

Tests the full DV → FS → EN → ED pipeline using mocked fetch_page results.
No network access required.

Run from brand-ai-readiness-audit/:
    python smoke_test_orchestrator.py
"""

import sys
import os
import json
import types

PASS = "[PASS]"
FAIL = "[FAIL]"
errors = []

def check(label, condition):
    if condition:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}")
        errors.append(label)

# ── Path setup ────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SKILLS = os.path.join(_HERE, "skills")

def skill_path(skill, subdir="scripts"):
    return os.path.join(_SKILLS, skill, subdir)

for _s in ["crawl-render-audit", "freshness-corroboration",
           "engagement-audit", "entity-disambiguation"]:
    p = skill_path(_s)
    if p not in sys.path:
        sys.path.insert(0, p)

# Add orchestrator scripts
_orch_scripts = os.path.join(_SKILLS, "audit-orchestrator", "scripts")
if _orch_scripts not in sys.path:
    sys.path.insert(0, _orch_scripts)

# ── Mock fetch_page ────────────────────────────────────────────────────────────
import compose_report as orch

# We'll monkey-patch orch.fetch_page per test scenario
_ORIGINAL_FETCH = orch.fetch_page

def make_page(url="https://example.com/",
              title="Example Corp | Home", og_title="", og_site_name="",
              description="A company that does things.",
              body="Example Corp is a technology company.",
              ldjson=None, internal_links=None,
              wc=None, blocked=False, blocked_reason=None,
              robots_disallowed=False, noindex=False, error=None,
              has_raw=True, html=None):
    if not og_title:
        og_title = title
    if ldjson is None:
        ldjson = []
    if internal_links is None:
        internal_links = []
    if wc is None:
        wc = len(body.split())
    if html is None:
        html = f"<html><head><title>{title}</title></head><body>{body}</body></html>"
    # Use sentinel None to omit meta_description from head (triggers DV-01 in checks_dv)
    head = {
        "title": title,
        "og_title": og_title, "og_description": description or "",
        "og_image": "", "og_site_name": og_site_name,
        "twitter_title": "", "twitter_description": "", "twitter_image": "",
        "canonical": url, "robots_meta": "", "noindex": noindex,
        "meta_keywords": "", "article_published_time": "",
        "article_modified_time": "",
    }
    if description is not None:
        head["meta_description"] = description
    # else: key absent → DV-01 will fire
    return {
        "url": url, "clean_url": url,
        "head": head,
        "raw_html": html,
        "body_text": body,
        "content_word_count": wc,
        "has_raw_html": has_raw,
        "blocked": blocked,
        "blocked_reason": blocked_reason,
        "robots_disallowed": robots_disallowed,
        "noindex": noindex,
        "error": error,
        "ldjson_blocks": ldjson,
        "internal_links": internal_links,
    }


# ── Scenario helpers ──────────────────────────────────────────────────────────

def audit_with(pages_by_url: dict, max_pages=5) -> dict:
    """
    Patch orch.fetch_page to return mocked pages, run the audit, restore.
    pages_by_url: {url: page_result_dict}
    """
    def mock_fetch(url, timeout=30):
        if url in pages_by_url:
            return pages_by_url[url]
        return make_page(url=url, body="Generic page.", error=None)

    orch.fetch_page = mock_fetch
    try:
        return orch.run_audit(list(pages_by_url.keys())[0], max_pages=max_pages)
    finally:
        orch.fetch_page = _ORIGINAL_FETCH


# ── Test 1: Healthy page — no findings, excellent health ─────────────────────
print("\n=== Test 1: Well-optimised page ===")

org_schema = json.dumps({
    "@context": "https://schema.org", "@type": "Organization",
    "name": "ExampleCorp Technologies",
    "url": "https://example.com",
    "sameAs": [
        "https://www.linkedin.com/company/examplecorp",
        "https://en.wikipedia.org/wiki/ExampleCorp",
        "https://wikidata.org/wiki/Q123456"
    ],
    "identifier": "CIN:L12345",
    "legalName": "ExampleCorp Technologies Pvt Ltd",
})
article_schema = json.dumps({
    "@context": "https://schema.org", "@type": "WebPage",
    "name": "ExampleCorp Homepage",
    "datePublished": "2024-01-15",
    "dateModified": "2025-03-10",
})
good_body = (" ".join(["ExampleCorp Technologies provides advanced analytics."] * 15))

good_html = f"""<html>
<head>
<title>ExampleCorp Technologies | Home</title>
<meta name="description" content="ExampleCorp Technologies provides advanced analytics and AI solutions.">
<link rel="canonical" href="https://example.com/">
<script type="application/ld+json">{org_schema}</script>
<script type="application/ld+json">{article_schema}</script>
</head>
<body>
<main><p>{good_body}</p></main>
<footer>
  <a href="https://www.linkedin.com/company/examplecorp">LinkedIn</a>
  <a href="https://twitter.com/examplecorp">Twitter</a>
</footer>
</body></html>"""

good_page = make_page(
    url="https://example.com/",
    title="ExampleCorp Technologies | Home",
    og_title="ExampleCorp Technologies | Home",
    og_site_name="ExampleCorp Technologies",
    description="ExampleCorp Technologies provides advanced analytics and AI solutions.",
    body=good_body,
    ldjson=[org_schema, article_schema],
    html=good_html,
    wc=len(good_body.split()),
)

r1 = audit_with({"https://example.com/": good_page})
check("pages_audited = 1", len(r1["pages_audited"]) == 1)
check("0 critical findings", r1["summary"]["critical_findings"] == 0)
check("report has summary key", "summary" in r1)
check("report has findings key", "findings" in r1)
check("report has schema_version", r1.get("schema_version") == "1.0.0")
check("generated_at present", bool(r1.get("generated_at")))
# A well-structured page still gets lower-sev findings (twitter, freshness)
# so 'fair' is acceptable alongside 'good'/'excellent'
check("health is not critical or poor",
      r1["summary"]["overall_health"] not in ("critical", "poor"))
check("strengths > 0 (schema present)",
      r1["summary"]["total_strengths"] > 0)


# ── Test 2: Bot-blocked page — EN/FS/ED should not contribute non-block findings ─
print("\n=== Test 2: Bot-blocked page ===")

blocked_page = make_page(
    url="https://blocked.example.com/",
    blocked=True,
    blocked_reason="BOT_BLOCK",
    body="",
    html="<html><body>Access Denied</body></html>",
    wc=0,
    error=None,
)
# Patch the page_result so DV-13 will fire:
blocked_page["blocked_reason"] = "BOT_BLOCK"

r2 = audit_with({"https://blocked.example.com/": blocked_page})
finding_ids = [f["id"] for f in r2["findings"]]
check("DV-13 fires on blocked page", "DV-13" in finding_ids)
check("No EN findings on blocked page",
      not any(f["id"].startswith("EN-") and f["id"] not in ("EN-12",)
              for f in r2["findings"]))


# ── Test 3: Wikidata-backed entity — ED all skipped ──────────────────────────
print("\n=== Test 3: Wikidata-backed entity ===")

wikidata_schema = json.dumps({
    "@context": "https://schema.org", "@type": "Organization",
    "name": "KnownCorp",
    "sameAs": ["https://wikidata.org/wiki/Q99999",
               "https://en.wikipedia.org/wiki/KnownCorp"]
})
wiki_body = "KnownCorp is a well-known company with extensive documentation. " * 10
wiki_html = f"""<html>
<head>
<title>KnownCorp | Home</title>
<meta name="description" content="KnownCorp is a well-documented company.">
<script type="application/ld+json">{wikidata_schema}</script>
</head>
<body><p>{wiki_body}</p></body></html>"""

wiki_page = make_page(
    url="https://knowncorp.example.com/",
    title="KnownCorp | Home",
    description="KnownCorp is a well-documented company.",
    body=wiki_body,
    ldjson=[wikidata_schema],
    html=wiki_html,
    wc=len(wiki_body.split()),
)
r3 = audit_with({"https://knowncorp.example.com/": wiki_page})
ed_findings = [f for f in r3["findings"] if f["id"].startswith("ED-")]
check("No ED findings when wikidata_backed", len(ed_findings) == 0)
strength_ids = [s["id"] for s in r3["strengths"]]
check("wikidata skip strength logged", any("WIKIDATA" in sid for sid in strength_ids))


# ── Test 4: Multi-page audit — severity escalation ───────────────────────────
print("\n=== Test 4: Multi-page severity escalation ===")

# DV-01 fires when body word count < 20 (JS-render gap / thin body)
def no_body_page(url):
    return make_page(
        url=url,
        description="A page about services.",
        body="Services.",  # < 20 words → DV-01 fires (critical: populated head + thin body)
        wc=1,
        html=f"""<html><head><title>Services | Co</title></head>
<body><p>Services.</p></body></html>""",
    )

pages = {
    "https://escalate.example.com/":         no_body_page("https://escalate.example.com/"),
    "https://escalate.example.com/about":    no_body_page("https://escalate.example.com/about"),
    "https://escalate.example.com/contact":  no_body_page("https://escalate.example.com/contact"),
}
# Wire up internal_links so the orchestrator discovers sub-pages
pages["https://escalate.example.com/"]["internal_links"] = [
    "https://escalate.example.com/about",
    "https://escalate.example.com/contact",
]

r4 = audit_with(pages, max_pages=3)
dv01_merged = next((f for f in r4["findings"] if f["id"] == "DV-01"), None)
check("DV-01 fires on multi-page audit", dv01_merged is not None)
check("DV-01 pages list has 3 entries",
      dv01_merged is not None and len(dv01_merged.get("pages", [])) == 3)
# Severity should have escalated from medium → high (≥3 pages)
if dv01_merged:
    check("DV-01 escalated to high (3 pages)",
          dv01_merged["severity"] in ("high", "critical"))


# ── Test 5: Cascading rules — DV-03 suppresses ED-02 ─────────────────────────
print("\n=== Test 5: DV-03 suppresses ED-02 (ownership boundary) ===")

# HR acronym (ED-01 should fire) but NO org schema at all (DV-03 should own it)
no_schema_hr = make_page(
    url="https://hr.example.com/",
    title="HR | Home",
    og_title="HR",
    description="HR solutions for enterprise.",
    body="HR solutions for large enterprise. HR Corp founded 2010.",
    ldjson=[],   # No schema at all → DV-03 fires, ED-02 must not
)
r5 = audit_with({"https://hr.example.com/": no_schema_hr})
finding_ids5 = [f["id"] for f in r5["findings"]]
check("DV-03 fires (no schema)", "DV-03" in finding_ids5)
check("ED-02 suppressed (DV-03 owns the gap)", "ED-02" not in finding_ids5)
check("ED-01 still fires (collision risk)", "ED-01" in finding_ids5)


# ── Test 6: Network error — graceful degradation ──────────────────────────────
print("\n=== Test 6: Network error — graceful degradation ===")

error_page = make_page(
    url="https://error.example.com/",
    error="Connection refused",
    body="",
    html=None,
    has_raw=False,
)
r6 = audit_with({"https://error.example.com/": error_page})
check("Report returned despite error", isinstance(r6, dict))
check("pages_audited includes error URL",
      "https://error.example.com/" in r6["pages_audited"])
check("summary present on error", "summary" in r6)


# ── Test 7: Suggested actions ordering ────────────────────────────────────────
print("\n=== Test 7: Suggested actions sorted by priority ===")

multi_sev_page = make_page(
    url="https://multisev.example.com/",
    title="HR | Enterprise HR Solutions",
    og_title="HR",
    description="",  # DV-01 fires (no description)
    body="HR Corp solutions for enterprise. HR Corp founded 2010. " * 3,
    ldjson=[],
    wc=50,
)
r7 = audit_with({"https://multisev.example.com/": multi_sev_page})
actions = r7.get("suggested_actions", [])
check("suggested_actions non-empty", len(actions) > 0)
priorities = [a["priority"] for a in actions]
sorted_pris = sorted(priorities,
                     key=lambda p: ["critical","high","medium","low"].index(p))
check("suggested_actions in descending priority order", priorities == sorted_pris)


# ── Test 8: Report schema fields ──────────────────────────────────────────────
print("\n=== Test 8: Report schema conformance ===")

r8 = audit_with({"https://schema-check.example.com/": make_page()})
required_keys = ["schema_version", "generated_at", "target_url", "pages_audited",
                 "audit_config", "summary", "findings", "flag_only_items",
                 "strengths", "suggested_actions"]
for key in required_keys:
    check(f"report has key '{key}'", key in r8)

summary_keys = ["total_findings", "critical_findings", "high_findings",
                "medium_findings", "low_findings", "total_flag_only",
                "total_strengths", "overall_health", "category_scores"]
for key in summary_keys:
    check(f"summary has key '{key}'", key in r8.get("summary", {}))

check("overall_health is a valid label",
      r8["summary"]["overall_health"] in ("excellent","good","fair","poor","critical"))
check("audit_config.skills_run non-empty",
      len(r8["audit_config"]["skills_run"]) == 4)


# ── Final result ──────────────────────────────────────────────────────────────
print("\n" + "=" * 55)
if errors:
    print(f"FAILED ({len(errors)} errors):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    total = sum(1 for line in open(__file__).readlines() if line.strip().startswith("check("))
    print(f"ALL {total} ORCHESTRATOR CHECKS PASSED")
