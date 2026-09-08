---
name: freshness-corroboration
description: >
  Audits a page for freshness and corroboration problems (FS-01 … FS-06):
  stale "current" date claims, internal numeric mismatches, missing "last
  updated" signals (with the same confidence-tier rule as DV-03), nav/footer
  listing inconsistencies, external corroboration gaps (flag-only), and
  self-reported wiki-style citation markers. Also provides the emit_flag_only
  helper shared with engagement-audit (EN-06).
license: MIT
allowed-tools:
  - python_interpreter
---

# Freshness & Corroboration Audit (FS-01 … FS-06)

## When to use
Called by **audit-orchestrator** per page after `crawl-render-audit` confirms
a successful, readable fetch. Do not call on blocked or noindex pages — the
orchestrator enforces this gate.

## Inputs
- `page_result` (required) — per-page JSON dict produced by `crawl-render-audit`.
- `current_date` (optional) — ISO date string override; defaults to system date.
  Useful for deterministic test runs.

## Procedure

Run the checks in this exact order.

1. **FS-06 FIRST — self-reported wiki-style markers** (`checks_fs.py → check_fs06()`).  
   Regex-scan both raw HTML (`<sup>` tags) and body text for markers:
   `[citation needed]`, `[dead link]`, `[clarification needed]`, `[unreliable source?]`,  
   `[verification needed]`, `[dubious]`, `[disputed]`, `[needs update]`.  
   - `[citation needed]` / `[dubious]` / `[disputed]` → **Medium** (claim has zero support).  
   - `[dead link]` / `[needs update]` / `[clarification needed]` → **Low**.  
   Run this before any inferred corroboration check — these are free, high-confidence signals.

2. **FS-01 — stale date claims** (`check_fs01()`).  
   Extract date strings from banners, notices, copyright lines, and body sentences that also  
   contain a "current/upcoming" context keyword (scheduled, deadline, maintenance, ©, etc.).  
   Parse each date and compare against today's system date.  
   - Stale operational claim (maintenance, deadline, exam date) → **High**.  
   - Stale copyright year (lag > 2 years) or general date claim → **Medium**.  
   - Copyright lag ≤ 2 years: **do not flag** (normal update cycle).

3. **FS-02 — internal numeric inconsistency** (`check_fs02()`).  
   Use regex to extract numeric claims of the same fact-type from both `meta[description]`  
   and body text (years of experience, client count, country count, employee count, uptime %).  
   If the same pattern yields two or more different values → candidate mismatch.  
   *LLM judgment step (required): confirm the two figures refer to the same fact, not two  
   legitimately different metrics using similar phrasing before scoring.*  
   Severity: **Medium**.

4. **FS-03 — no freshness signal** (`check_fs03()`).  
   Check for `article:published_time`, `article:modified_time` meta tags, and visible  
   "last updated / as of [date] / version N" text in body.  
   - Confidence tier (same rule as DV-03): if only rendered text was available (not raw HTML),  
     emit `severity: "unscored", confidence: "not_detected_in_pass"` — log as to-verify,  
     **not a scored finding** (a "last edited" timestamp may live in a footer not captured).  
   - Content pages (blog, article, news, review, docs): **Medium**.  
   - Homepage: **Low**.  
   - Transactional/utility pages: **skip**.

5. **FS-04 — nav/footer listing mismatches** (`check_fs04()`).  
   Extract anchor text from `<nav>` and `<footer>` elements; lowercase and strip generic  
   navigation terms (home, contact, login, cart, privacy, terms, sitemap, search).  
   - Near-duplicate item names across nav and footer (60–99% similar): **Low** (possible typo/rename).  
   - ≥ 3 substantive items in nav absent from footer: **Low**.  
   Full spellchecking is a lower-automation step — similarity matching is a proxy.

6. **FS-05 — external corroboration gap** (`check_fs05_flag_only()`).  
   Detect whether the page explicitly attributes claims to named external sources  
   ("according to…", "as per the report…", "sourced from…").  
   - Explicit attribution found → log as a **strength** (positive pattern; no flag).  
   - No explicit attribution → emit via `emit_flag_only()` as a manual-audit recommendation  
     (not a scored finding — cannot verify external sources from a single-page fetch).  
   *The `emit_flag_only()` helper in this script is shared verbatim with `engagement-audit`  
   for the EN-06 deep-link gap check. Keep its signature stable.*

7. **Return** the result dict (see Output).

> **Full check details, severity heuristics, and templates:**  
> see [`references/fs_checklist.md`](references/fs_checklist.md)

## Output

```json
{
  "url": "https://example.com/about",
  "findings": [
    {
      "id": "FS-01",
      "title": "Stale copyright notice references 2020 (2,098 days ago)",
      "severity": "medium",
      "evidence": "Page https://example.com/about contains a copyright notice referencing 2020...",
      "suggested_action": {
        "summary": "Update the copyright notice from 2020 to the current year...",
        "priority": "medium"
      }
    }
  ],
  "flag_only_items": [
    {
      "id": "FS-05",
      "type": "flag_only",
      "reason": "Facts on this page should be spot-checked against third-party sources...",
      "recommendation": "Manually spot-check key facts against Google My Business, LinkedIn..."
    }
  ],
  "strengths": []
}
```
