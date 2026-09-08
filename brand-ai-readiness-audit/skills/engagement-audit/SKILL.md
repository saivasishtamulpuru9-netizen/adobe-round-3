---
name: engagement-audit
description: >
  Audits on-site engagement signals (EN-01 … EN-13) for pages that have passed
  the crawl-render-audit gate. Implements cascading routing first: pages blocked
  by WAF (DV-13/DV-16) route to EN-12 (not_assessed); pages with a JS-render gap
  (DV-01 Critical) route to EN-13 (not_assessed); noindex/transactional pages route
  to EN-11 (not_applicable). Remaining pages are scored for broken links, placeholder
  values, missing breadcrumbs, paywall friction, hidden interactive content, stat
  fallbacks, trust content, video captions, and navigation quality.
license: MIT
allowed-tools:
  - python_interpreter
---

# Engagement Audit (EN-01 … EN-13)

## When to use
Called by **audit-orchestrator** per page, after `crawl-render-audit` produces
its per-page result dict. The DV flags from that result are passed in as `dv_flags`.

## Inputs
- `page_result` (required) — per-page JSON dict from `crawl-render-audit`.
- `dv_flags` (required) — the `flags` sub-dict from the DV result:
  `{ "dv01_critical": bool, "dv13_fired": bool, "dv16_fired": bool, "wikidata_backed": bool }`.

## Procedure

**Critical rule:** Run the cascading routing block (steps 1–4) BEFORE any scoring.  
Return immediately at the first routing condition that matches.

1. **Routing — EN-12 (not_assessed):** If `dv13_fired = true` OR `dv16_fired = true` →  
   set `engagement_status = "not_assessed"`, set `skip_finding_ref = "DV-13"` or `"DV-16"`,  
   and **return**. No scoring is possible when the page fetch was blocked.

2. **Routing — EN-13 (not_assessed):** If `dv01_critical = true` →  
   set `engagement_status = "not_assessed"`, set `skip_finding_ref = "DV-01"`,  
   and **return**. Scoring on an empty page produces false positives.

3. **Routing — EN-11 (not_applicable):** If `meta[robots] = noindex` →  
   set `engagement_status = "not_applicable"` and **return**.

4. **Routing — EN-11 (not_applicable):** If the URL matches a transactional pattern  
   (`/cart`, `/checkout`, `/search`, `/account`, `/login`, `/register`, `/signin`,  
   `/signup`, `/order`, `/payment`, `/my-*`, `/dashboard`, `?q=`, `?s=`) →  
   set `engagement_status = "not_applicable"` and **return**.

5. **EN-01 / EN-02 (ownership rule built in — `check_en01_en02()`):**  
   Inspect `<a href>` in `<nav>` and `<footer>`. Apply EN-02 FIRST (more specific):  
   - Any link where `href` or visible text matches a placeholder pattern → EN-02 (High).  
   - Then, any remaining non-placeholder link in primary nav/footer where `href = "#"` or  
     empty → EN-01 (High).  
   If a link is BOTH dead AND a placeholder → file once as EN-02 only.

6. **EN-03:** Check for BreadcrumbList JSON-LD, breadcrumb CSS class/aria-label, or  
   `Home > Category` text pattern. Only fires on pages ≥ 2 URL levels deep. Severity: Medium.

7. **EN-04:** Scan the first ~8 KB of raw HTML for paywall/login friction signals.  
   *Exclusion:* Skip if body contains credential-gated personal-data portal phrases  
   ("hall ticket", "admit card", "application number", "date of birth").  
   *LLM judgment step (required before scoring):* Confirm friction is premature gating,  
   not a legitimate personal-data lookup. Severity: High.

8. **EN-05:** Find tab/accordion containers with labels but no readable content in raw HTML.  
   Skip if `_dv01_fired = True` (DV-01 owns the root cause). Severity: High.

9. **EN-06 (flag-only):** Always emit via `emit_flag_only()` for every non-excluded page.  
   "AI-referred visitors may land on the homepage rather than the specific page matching  
   their query." Not a scored finding — manual review required.  
   *(Uses `emit_flag_only()` — same helper as freshness-corroboration FS-05. Copy verbatim.)*

10. **EN-07:** Find `<video>` elements with no `<track>`, no `<figcaption>`, and no adjacent  
    descriptive text. Cap at 3 findings per page. Severity: Low.

11. **EN-08:** Find stat/counter containers with no digit value (Low — omission) or a literal  
    `0` value (Medium — false assertion). Cap at 4 findings per page.

12. **EN-09:** If no trust content exists on homepage/about/services pages:  
    testimonial, review, `<blockquote>`, case-study text, "client say" pattern.  
    *Distinct from DV-07:* DV-07 fires when trust content exists but is weak;  
    EN-09 fires when trust content is COMPLETELY ABSENT. Severity: Low.

13. **EN-10:** Count nav items and footer sitemap links. If ≥ 5 nav sections AND  
    ≥ 10 footer links → log as a **strength** (never a finding). No threshold absence = no defect.

14. **Return** the result dict (see Output).

> **Site-wide EN-13 deduplication:** The orchestrator spot-checks whether a DV-01-Critical  
> render gap is site-wide (home + 1–2 other pages). If so, the final report files one  
> site-architecture finding, not per-page EN-13 entries.

> **Full check details, severity tables, and templates:**  
> see [`references/en_checklist.md`](references/en_checklist.md)

## Output

```json
{
  "url": "https://example.com/about",
  "engagement_status": "scored",
  "skip_reason": null,
  "skip_finding_ref": null,
  "findings": [
    {
      "id": "EN-03",
      "title": "No breadcrumb trail on nested page (depth 2)",
      "severity": "medium",
      "evidence": "Page https://example.com/about is 2 levels deep with no breadcrumb...",
      "suggested_action": {
        "summary": "Add a breadcrumb trail (Home > About)...",
        "priority": "medium"
      }
    }
  ],
  "flag_only_items": [
    {
      "id": "EN-06",
      "type": "flag_only",
      "reason": "Deep-link matching cannot be verified from a single-page fetch...",
      "recommendation": "Ensure AI-referred visitors land on the specific product page..."
    }
  ],
  "strengths": []
}
```
