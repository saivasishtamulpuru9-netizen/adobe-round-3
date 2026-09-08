---
name: audit-orchestrator
description: >
  Entrypoint skill for the Brand AI-Readiness Audit marketplace. Given a URL,
  orchestrates crawl-render-audit, freshness-corroboration, engagement-audit,
  and entity-disambiguation; applies all cross-skill cascading/ownership rules;
  and emits a single structured JSON report of findings, strengths, flag-only
  items, and prioritised suggested actions.
license: MIT
allowed-tools:
  - web_fetch
  - python_interpreter
---

# Brand AI-Readiness Audit — Orchestrator

## When to use
Use this skill whenever you need to audit a website for AI-discoverability and
on-site-engagement problems. It is the **single entry point**; do not invoke
the sub-skills directly.

## Inputs
- `url` (required) — the target website URL (homepage or any page on the domain).
- `max_pages` (optional, default `5`) — how many pages to fetch.
- `timeout` (optional, default `30`) — per-page HTTP timeout in seconds.
- `verbose` (optional, default `False`) — if True, include raw per-page results.

## Procedure

1. **Fetch pages** — call `fetch_page(url)` for the root URL; discover up to
   `max_pages - 1` internal links from the homepage to audit additional pages.

2. **Per-page DV checks** — call `run_dv_checks(page_result)`.  
   Collect `dv_flags` (dv01_critical, dv13_fired, dv16_fired, wikidata_backed).

3. **Apply cascading gates** (see [`references/cascading_rules.md`](references/cascading_rules.md) §2):

   | Condition | Effect |
   |-----------|--------|
   | `dv13_fired` OR `dv16_fired` | EN routes to EN-12 only (page inaccessible) |
   | `dv01_critical` | EN routes to EN-13 only (no crawlable content) |
   | `wikidata_backed` | All ED checks skipped; log as site-level strength |
   | `page_result["error"]` | FS skipped |

4. **Per-page FS checks** — call `run_fs_checks(page_result)` (unless skipped by error gate).

5. **Per-page EN checks** — call `run_en_checks(page_result, dv_flags=dv_flags)`.

6. **Per-page ED checks** — call `run_ed_checks(page_result, dv_flags=dv_flags, dv_findings=...)`.  
   Suppress ED-02 if DV-03 fired on the same page (§3a of cascading rules).

7. **Aggregate findings** across all pages:
   - Merge findings by check ID; keep worst severity; list all affected pages.
   - Escalate severity by one level when same check ID fires on ≥ 3 pages.
   - Deduplicate strengths (once per site).
   - Flag-only items are NOT deduplicated (each page needs independent lookup).

8. **Build report** — compose summary scorecard (weighted defect score),
   sort suggested actions (critical → high → medium → low, then page-count desc),
   and serialise to JSON conforming to [`references/report_schema.json`](references/report_schema.json).

## Output

```json
{
  "schema_version": "1.0.0",
  "generated_at":   "2025-09-08T05:45:00Z",
  "target_url":     "https://example.com",
  "pages_audited":  ["https://example.com/", "https://example.com/about"],
  "summary": {
    "total_findings":    12,
    "critical_findings":  0,
    "high_findings":      3,
    "medium_findings":    7,
    "low_findings":       2,
    "total_flag_only":    4,
    "total_strengths":    2,
    "overall_health":    "fair",
    "category_scores":   {"DV": 5, "FS": 2, "EN": 3, "ED": 2}
  },
  "findings":         [ ... ],
  "flag_only_items":  [ ... ],
  "strengths":        [ ... ],
  "suggested_actions":[ ... ]
}
```

## CLI

```bash
python skills/audit-orchestrator/scripts/compose_report.py https://example.com
python skills/audit-orchestrator/scripts/compose_report.py https://example.com \
  --max-pages 10 --timeout 20 --verbose --out report.json
```
