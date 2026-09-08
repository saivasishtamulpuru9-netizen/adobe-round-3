---
name: crawl-render-audit
description: >
  Fetches a page (raw HTML) and runs all visibility/discoverability checks
  DV-01 through DV-20: JS-render gaps, missing/invalid structured data, thin
  content, facts locked in non-text form, duplicate/templated content, canonical
  gaps, spam signals, and crawler-access issues. Produces a per-page JSON object
  (with findings, strengths, and cascade flags) that freshness-corroboration,
  engagement-audit, and entity-disambiguation consume.
license: MIT
allowed-tools:
  - web_fetch
  - python_interpreter
---

# Crawl & Render Audit (DV-01 … DV-20)

## When to use
Called by **audit-orchestrator** for each page in the crawl set.  
Do not invoke directly unless you are testing a single page in isolation.

## Inputs
- `url` (required) — absolute URL of the page to audit.
- `raw_html` (optional) — pre-fetched HTML string; if absent, `fetch_page.py` fetches it.
- `all_pages` (optional) — list of other page-result dicts; required only for the DV-12 multi-page check.

## Procedure

Run the steps below **in the exact order listed**. Stop early where indicated.

1. **Check `robots.txt`** (`scripts/fetch_page.py → check_robots()`).  
   Fetch `https://{domain}/robots.txt` and parse it for the audit user-agent.  
   If the URL is disallowed → set `robots_disallowed = true`, emit **DV-16**, and **stop**.

2. **GET the URL** (`fetch_page.py → fetch_page()`).  
   Inspect HTTP status code, response headers, and first 4 KB of body for bot-block signatures  
   (Cloudflare challenge, 403/429/503, WAF patterns).  
   If blocked → set `blocked = true`, emit **DV-13**, emit **DV-17** (external search instruction), and **stop**.

3. **Check `meta[robots]`** in `<head>`.  
   If `noindex` is present → mark `status: intentionally_excluded` and **stop** (skip DV-01/02/03/04).  
   Rationale: transactional/search/account pages are correctly excluded — flagging them is a false positive.

4. **Run DV-01** — count non-boilerplate body words.
   - Populated `<head>` (has `<title>`) + body word count < 20 → **Critical** (set `dv01_critical` flag; engagement-audit routes to EN-13).
   - Literal "enable JavaScript" / "JavaScript required" string in body → **Critical**.
   - < 30 words on a non-transactional page → **High**; < 50 words → **Medium**.

5. **Check for Wikidata sameAs link** in raw HTML.  
   If found → set `wikidata_backed = true` flag, log as a strength, and skip DV-03 and all ED-0x checks  
   (entity identity is resolved via the Wikidata graph, not on-page schema.org markup).

6. **Run DV-02** — check presence and non-emptiness of `meta[description]`, `og:title`, `og:description`,  
   `og:image`, `twitter:title`, `twitter:description`.  
   Absent/empty field = DV-02. *(Present-but-generic/duplicated across URLs = DV-12 — never fire both for the same field.)*

7. **Run DV-03** — search for `<script type="application/ld+json">` blocks; parse and validate each.  
   No valid block found → **High** (escalate to **Critical** if compounded with DV-01 Critical or missing meta description).  
   Confidence tier: `confirmed_absent` if raw HTML available; `not_detected_in_pass` if text-only → log as to-verify, **not a scored finding**.  
   *(Skip entirely if `wikidata_backed` flag is set.)*

8. **Run DV-04** — if body word count < 150 and DV-01 did **not** fire Critical → **High** thin content.  
   *LLM judgment step: verify the text is genuinely thin, not intentionally minimal copy.*  
   *(Skip if `_dv01_fired` is set — same root cause.)*

9. **Run DV-05** — (a) `<img>` with empty/generic alt near trust-signal sections → **Medium**;  
   (b) physical address present only inside a map `href`, not as visible text → **Medium**.  
   *(Stat/counter elements with no static digit value → EN-08, not DV-05.)*

10. **Run DV-06** — collect paragraph text per named H2/H3 section; fuzzy-match across sections;  
    > 90 % similarity between two distinct named sections → **Medium**.  
    *(DOM block repeated 3+ times mechanically → DV-15 — different root cause.)*

11. **Run DV-07** — detect testimonial/review blocks with no outbound link to a real review platform.  
    Script-able proxy (link-check). *LLM judgment step: confirm near-identical phrasing across quotes.*

12. **Run DV-08** — if URL contains known tracking parameters AND no `<link rel="canonical">` is present → **Low**.  
    Only flag if tracking parameter appears in the **site's own** URL or the site's canonical gap.  
    Do not flag if tracking parameter clearly arrived via external referral context.

13. **Run DV-09** — (a) any `<p>` with > 8 inline links → **Medium**;  
    (b) `meta[keywords]` with > 15 tokens → **Low**.

14. **Run DV-10** — product/service cards linking only to `#` anchors with no unique detail URL → **High**.

15. **Run DV-11** — homepage with no company-level "what is X" orientation sentence → **Medium**.  
    *(Only fires on root-path pages: `/`, `/index.html`, `/index.php`, `/home`.)*

16. **Run DV-15** — fingerprint sibling DOM blocks; > 3 near-identical repeats of a substantial block → flag  
    (severity scales: Low < 6, Medium 6–10, High > 10 repeats).

17. **Run DV-19** — on article/review/news pages, detect generic byline patterns ("Team", "Staff", "Desk").  
    *LLM judgment step: confirm the byline is genuinely generic, not an unusual real name.*

18. **Run DV-20** — ratio of primary-content words (in `<article>`/`<main>`) to total page words.  
    Ratio < 20 % OR no semantic boundary → **Medium** (on content-style pages only).

19. **Multi-page DV-12** — after all pages are fetched, compare `<title>` and `meta[description]` across pages.  
    Identical values on topically distinct pages → **High**.  
    *(Absent field = DV-02; present-but-duplicated = DV-12 — never both for same field on same page.)*

20. **DV-17 follow-up** — if DV-13 or DV-16 fired: instruct the agent to search  
    `"{domain} [key service or product]"` and verify whether unofficial/proxy sites fill the citation gap.

21. **DV-18** — `GET /llms.txt` at domain root. Present → log as **strength**. Absent → log as proactive **Low** suggestion.

22. **Collect strengths** — positive patterns (Wikidata-backed identity, /llms.txt present, valid JSON-LD found,  
    rich canonical usage) recorded in the `strengths` array.

23. **Return** the per-page result dict (see Output).

> **Full check details, severity heuristics, and templates:**  
> see [`references/dv_checklist.md`](references/dv_checklist.md)

## Output

A per-page JSON dict passed to the other skills and to `compose_report.py`:

```json
{
  "url": "https://example.com/about",
  "status": "checked | blocked | robots_disallowed | intentionally_excluded | fetch_error",
  "findings": [
    {
      "id": "DV-03",
      "title": "No valid JSON-LD structured data (Organization expected)",
      "severity": "high",
      "evidence": "Raw HTML of https://example.com/about contains 0 valid JSON-LD blocks.",
      "suggested_action": {
        "summary": "Add Organization JSON-LD to this about page — 0 structured data blocks present.",
        "priority": "high"
      }
    }
  ],
  "strengths": [],
  "flags": {
    "dv01_critical": false,
    "dv13_fired": false,
    "dv16_fired": false,
    "wikidata_backed": false
  }
}
```
