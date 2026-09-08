# Brand AI-Readiness Audit — Skill Marketplace

> **Adobe University Hackathon 2026 · Round 3 submission**

This marketplace audits any website for problems that hurt its **AI discoverability**
(getting found and cited by AI assistants) and its **on-site engagement** (keeping the
visitor once they arrive). It produces a single structured JSON report — each finding
with evidence, severity, and a suggested fix — plus site-level strengths and
flag-only items that need external confirmation. It is **recommend-only**: no skill
ever modifies a live site.

---

## Quick Start

```bash
# Audit a website (from the brand-ai-readiness-audit/ directory)
python skills/audit-orchestrator/scripts/compose_report.py https://example.com

# Audit up to 10 pages, save JSON report
python skills/audit-orchestrator/scripts/compose_report.py https://example.com \
  --max-pages 10 --out report.json

# Run all smoke tests (no network required)
python smoke_test_dv.py && python smoke_test_fs.py && \
python smoke_test_en.py && python smoke_test_ed.py && \
python smoke_test_orchestrator.py
```

**Dependencies:** `requests`, `beautifulsoup4`, `lxml` (or `html.parser`)

---

## Skills

### `audit-orchestrator` _(entrypoint)_
The single entry point. Given a URL, it:
1. Crawls the homepage and up to `--max-pages` linked pages.
2. Runs all four skill checks per page in the correct order.
3. Applies cross-skill cascading/ownership rules (no finding filed twice).
4. Merges findings across pages (worst severity wins; escalates when ≥ 3 pages trigger same check).
5. Emits a structured JSON report conforming to `references/report_schema.json`.

### `crawl-render-audit` (DV-01 … DV-20)
All **visibility / discoverability** checks. Ordered pipeline:
bot-block → robots.txt → noindex → full DV checks.  
Covers: JS-render gaps, missing/invalid structured data, thin content, locked non-text
content, duplicate/templated pages, canonical gaps, and AI-spam signals.  
Produces `dv_flags` consumed by all downstream skills.

### `freshness-corroboration` (FS-01 … FS-06)
All **freshness and corroboration** checks. Detects stale date claims, internal numeric
inconsistencies, missing "last updated" signals, footer/nav date drift, and explicit
`[citation needed]` / `[source?]` markers.

### `engagement-audit` (EN-01 … EN-13)
All **on-site engagement** checks. Starts with mandatory cascading routing:
- `not_assessed` → EN-13 if DV-01-critical; EN-12 if DV-13/DV-16.
- `not_applicable` → skips if page is noindex or transactional.  

Then scores: wayfinding, paywall friction, dead/placeholder links, missing breadcrumbs,
dynamic stat rendering, trust signals, sticky CTAs, link-to-external-authority,
and more.

### `entity-disambiguation` (ED-01 … ED-06)
All **entity identity clarity** checks. Wikidata-backed entities skip all checks.
Otherwise checks: brand name collision risk (acronym/generic/short), Organization
schema sameAs completeness, brand-name casing inconsistency, missing social profile
links, Wikipedia/Wikidata linkage, and ambiguous founding facts (flag-only).

---

## Report Structure

```json
{
  "site":           "example.com",
  "audited_at":     "2026-09-08T06:15:00Z",
  "schema_version": "1.0.0",
  "generated_at":   "2026-09-08T06:15:00Z",
  "target_url":     "https://example.com",
  "pages_audited":  ["https://example.com/", "https://example.com/about"],
  "summary": {
    "total_findings":    12,
    "critical":           1,
    "high":               3,
    "medium":             6,
    "low":                2,
    "critical_findings":  1,
    "high_findings":      3,
    "medium_findings":    6,
    "low_findings":       2,
    "total_flag_only":    4,
    "total_strengths":    2,
    "overall_health":    "fair",
    "category_scores":   {"DV": 5, "FS": 2, "EN": 3, "ED": 2}
  },
  "findings": [
    {
      "id": "DV-03",
      "title": "No valid JSON-LD structured data (Organization expected)",
      "severity": "high",
      "evidence": "Raw HTML contains 0 JSON-LD script blocks.",
      "suggested_action": {
        "summary": "Add Organization JSON-LD to every core page.",
        "priority": "high"
      },
      "pages": ["https://example.com/"]
    }
  ],
  "flag_only_items":   [ ... ],
  "strengths":         [ ... ],
  "suggested_actions": [ ... ]
}
```

Full schema: `skills/audit-orchestrator/references/report_schema.json`.

---

## Architecture

```
User supplies URL
       │
       ▼
audit-orchestrator  →  fetch homepage + discover internal links
       │
       ├──► crawl-render-audit (per page)      → dv_result  +  dv_flags
       │
       ├──► freshness-corroboration (per page) → fs_result
       │         (skip if fetch error)
       │
       ├──► engagement-audit (per page)        → en_result
       │         (routed via dv13/dv16/dv01_critical flags)
       │
       ├──► entity-disambiguation (per page)   → ed_result
       │         (all skipped if wikidata_backed; ED-02 suppressed if DV-03 fired)
       │
       ▼
compose_report.py
  • merge findings (worst severity; page-count escalation)
  • dedup strengths (once per site)
  • preserve flag-only items (no dedup — each page needs lookup)
  • sort suggested_actions (critical→high→medium→low, page-count desc)
  • include proactive beyond-defect recommendations
       │
       ▼
audit_report.json
```

Cascading rules: `skills/audit-orchestrator/references/cascading_rules.md`

---

## Test Suite & Validation

### 1. Offline Synthetic Unit Tests (180 Total Checks, 0 Network)
| Suite | Checks | Scope | Status |
|---|---|---|---|
| `smoke_test_dv.py` | 33 | DV-01 … DV-20 + fetch pipeline | ✅ PASS |
| `smoke_test_fs.py` | 25 | FS-01 … FS-06 date & mismatch checks | ✅ PASS |
| `smoke_test_en.py` | 27 | EN-01 … EN-13 + routing gates | ✅ PASS |
| `smoke_test_ed.py` | 31 | ED-01 … ED-06 + wikidata skip gate | ✅ PASS |
| `smoke_test_orchestrator.py` | 27 | Full pipeline integration (8 scenarios) | ✅ PASS |
| `test_dv_checks_stdlib.py` | 37 | DV pure function and edge case suite | ✅ PASS |
| **Total Unit Tests** | **180** | Complete offline test coverage | **100% PASS** |

### 2. Live Audits & Special Case Verification
Live test reports generated in `reports/`:
- `reports/wikipedia_tim.json`: Wikipedia-style page with Wikidata sameAs resolution + FS-06 markers.
- `reports/kisansuvidha.json`: Real-world site exercising DV-01 Critical JS-render gap routing to EN-13 (`not_assessed`).
- `reports/hackernews.json`: Real-world site demonstrating missing schema, header metadata gaps, and counter omission.
- `reports/python_org.json`: Real-world site demonstrating metadata checks, stale copyright notices, and entity disambiguation.
- `reports/bot_block_dv13_en12.json`: Exercises DV-13 bot-block / WAF challenge routing to EN-12 (`not_assessed`).
- `reports/noindex_en11.json`: Exercises noindex short-circuit (`intentionally_excluded`, skipping DV-01..04 and routing EN to EN-11 `not_applicable`).

---

## Guardrails

- **Recommend-only.** No script ever modifies a live website or performs an authenticated action.
- **GET requests only.** All fetches are read-only HTTP GET (or HEAD for link-checking).
- **Respects `robots.txt`.** Fetching and parsing `robots.txt` is itself the DV-16 detection step; disallowed paths are not crawled.
- **No rate-abusing behaviour.** Crawl is capped at `--max-pages` pages; no parallel flooding.
- **No model weights bundled.** LLM-judgment steps are expressed as agent instructions in `SKILL.md` files — no embedded weights.
- **Runtime target.** A typical 5-page audit completes in under 5 minutes.
