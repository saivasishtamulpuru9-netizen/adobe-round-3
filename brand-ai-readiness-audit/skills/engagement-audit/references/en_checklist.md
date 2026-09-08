# EN Checklist — Engagement Audit Checks (EN-01 … EN-13)

> Reference document for the **engagement-audit** skill.  
> Each entry: detection method · severity heuristic · template · ownership rules.

---

## Cascading Routing — MUST Run Before Any Scoring

The routing block determines what `engagement_status` each page gets.  
Run this **before** any of EN-01 through EN-10.

| Priority | Condition | Status | Ref |
|----------|-----------|--------|-----|
| 1 | `dv13_fired = true` OR `dv16_fired = true` | `not_assessed` | EN-12 |
| 2 | `dv01_critical = true` | `not_assessed` | EN-13 |
| 3 | `meta[robots] = noindex` | `not_applicable` | EN-11 |
| 4 | URL matches transactional pattern | `not_applicable` | EN-11 |
| 5+ | None of the above | `scored` — proceed with EN-01 … EN-10 |

> **Transactional URL patterns:** `/cart`, `/checkout`, `/search`, `/account`, `/login`,  
> `/register`, `/signin`, `/signup`, `/order`, `/payment`, `/my-*`, `/dashboard`, `?q=`, `?s=`

---

## EN-01 — Broken / dead links

**Detection:** Script-able.  
Inspect `<a href>` in `<nav>` and `<footer>` elements. Flag links where `href` is  
`#`, `javascript:void(0)`, `javascript:;`, or empty.

**Ownership rule vs. EN-02:**  
If a link is BOTH dead AND a placeholder value → file once as **EN-02** (more specific root cause).  
EN-01 only covers dead links that are NOT placeholders.

**Severity:** High (dead ends in primary navigation are a confirmed bounce driver).

**Template:**  
> "Fix or remove the {n} dead link(s) in navigation: {examples} — dead ends in primary  
> navigation are a direct, confirmed bounce driver."

---

## EN-02 — Placeholder / template values shipped to production

**Detection:** Script-able.  
Check `href`, `src`, visible text, and meta field values for placeholder patterns:  
`YOUR_*`, `{{…}}`, `__X__`, `TODO`, `PLACEHOLDER`, `lorem ipsum`, `[INSERT X]`, `undefined`, `null`, etc.

**Priority:** Always file EN-02 before EN-01 when both conditions co-occur (ownership rule).

**Severity:** High.

**Template:**  
> "Replace each placeholder ({examples}) with a real value, or remove the element until  
> ready — placeholder values create broken experiences and signal unprofessional content."

---

## EN-03 — No breadcrumb / orientation trail

**Detection:** Script-able.  
Check for BreadcrumbList JSON-LD, elements with class/aria-label matching `breadcrumb/crumb/trail`,  
and body text matching `Home > Category` separator patterns.

**Applies to:** Pages ≥ 2 levels deep in the URL hierarchy. Skip root-level pages.

**Severity:** Medium.

**Template:**  
> "Add a breadcrumb trail (e.g. Home > {category} > {page}) — helps visitor orientation  
> and is also a BreadcrumbList schema opportunity."

---

## EN-04 — Paywall / login friction before value shown

**Detection:** Script-able proxy + LLM judgment.  
Regex for login/paywall friction signals early in the DOM  
(first ~8 KB of raw HTML): "sign in to view", "login required", "upgrade to access",  
"subscribe to see", "premium only", "out of credits".

**Exclusions (skip EN-04):**  
Legitimate credential-gated personal-data portals — these are expected gating:  
- Exam result / hall ticket portals (roll number, date of birth, application number)  
- Application status lookups  
- Any page with phrases: "hall ticket", "admit card", "date of birth", "application number"

**LLM judgment step (required before scoring):**  
Confirm the friction appears before any value is demonstrated to a first-time visitor,  
and is NOT a legitimate credential gate for personal data.

**Severity:** High.

**Template:**  
> "Show a clear free-vs-paid feature comparison in static text before prompting login —  
> currently '{friction_signal}' appears before any value is demonstrated to a first-time visitor."

---

## EN-05 — Interactive content hidden until interaction

**Detection:** Script-able proxy.  
Find tab/accordion containers (class matches `tab|accordion|toggle|panel|collapse`).  
For each: check if a label exists but the surrounding text is essentially just the label  
(no substantive content in raw HTML).

**Excludes pages where DV-01 Critical already fired** (same root cause, DV-01 owns it).

**Severity:** High.

**Template:**  
> "Pre-render at least a one-line summary for each of the {n} tab/section(s) ({labels}) so  
> visitors don't need to interact to see any content — the current tabs are invisible to both  
> crawlers and visitors with JS issues."

---

## EN-06 — Generic homepage instead of intent-matched landing (flag-only)

**Detection:** Cannot be verified from a single-page fetch alone.  
**Status:** Flag-only (emitted via `emit_flag_only()` — shared helper from freshness-corroboration).  
Always emitted for non-transactional, non-excluded pages.

**Rationale:**  
AI assistants referring visitors to a brand often link to the homepage rather than the specific  
product/service page matching the user's query. This cannot be checked from a page fetch alone.

**Flag-only template:**  
> "Ensure AI-assistant-referred visitors land on the specific product/service page matching  
> their query, not the homepage — verify deep links exist for each key product/service, with  
> unique URLs and descriptive titles."

---

## EN-07 — Heavy video / animation with no text fallback

**Detection:** Script-able.  
Find `<video>` elements with no `<track>` (captions), no `<figcaption>`, and no adjacent  
descriptive text (> 20 chars near the video element).

**Severity:** Low (informational — not a confirmed bounce driver, but reduces accessibility  
and crawlability of video-only sections).

**Template:**  
> "Add a one-line text caption near the '{section}' section describing its content —  
> the only current fallback is the generic browser 'video not supported' message."

---

## EN-08 — Dynamic stat / counter elements with no static value

**Detection:** Script-able.  
Find stat containers (class `stat|counter|metric|number|figure|count`, `data-count`, `data-target`),  
plus any element with stat-like label words (users, clients, downloads, reviews, etc.).

**Severity (two tiers):**

| Condition | Severity |
|-----------|----------|
| No digit value present in raw HTML for stat label | **Low** (omission — crawler just skips the stat) |
| Digit value present but = 0 (or placeholder) | **Medium** (wrong assertion — crawler extracts a false fact) |

**Note:** Cap at 4 stat findings per page to avoid noise on stats-heavy pages.

**Templates:**  
(Low omission): "Provide a real static fallback value in the HTML for '{label}' (JS can still animate the count-up) — currently no value appears in a static read."  
(Medium wrong): "Replace the '0' placeholder with a real static fallback for '{label}' — currently the static value reads as 0, asserting a false fact."

---

## EN-09 — Complete absence of trust content

**Detection:** Script-able.  
Check body text for trust-content keywords (testimonial, review, case study, "client say", etc.)  
and DOM for `<blockquote>` or elements with class `testimonial|review|quote`.

**Applies to:** Homepage, About, Services, Why-Us, and service/solution/product/offering pages.  
Skip on transactional, documentation, or article-style pages.

**Distinct from DV-07:** DV-07 fires when trust content EXISTS but is weak/unverifiable.  
EN-09 fires when trust content is COMPLETELY ABSENT.

**Severity:** Low.

**Template:**  
> "Add 2–3 named, attributed client quotes or case-study snippets — currently only brand  
> logos appear with no accompanying text, giving visitors no readable social proof."

---

## EN-10 — Clear layered navigation (positive pattern)

**Detection:** Script-able. Count distinct anchor labels in `<nav>` and `<footer>` elements.  
Threshold: ≥ 5 named nav sections AND ≥ 10 footer sitemap links.

**Never fires a finding** — absence on a lean site is not a defect.  
Only logs a **strength** when the threshold is met.

**Strength label:**  
> "Clear layered navigation: {n_nav} named nav sections, {n_footer} footer sitemap links — good  
> orientation for both visitors and crawlers."

---

## EN-11 — Not applicable (noindex / transactional page)

**Status:** `not_applicable`  
**Fires before any scoring on:**
- Pages with `meta[robots] = noindex`
- URLs matching transactional patterns (cart, checkout, search, account, login, etc.)

This is not a finding — the page correctly omits engagement optimisations for these reasons.

---

## EN-12 — Not assessed (fetch blocked)

**Status:** `not_assessed`  
**Fires before any scoring when:** `dv13_fired = true` OR `dv16_fired = true` in DV flags.  

No engagement evidence is available. Root fix: resolve the underlying DV-13 or DV-16 finding.

---

## EN-13 — Not assessed (JS-render gap, Critical)

**Status:** `not_assessed`  
**Fires before any scoring when:** `dv01_critical = true` in DV flags.

Fetch succeeded, but the page body is essentially empty — any engagement finding would be  
a false positive on empty content.

> **Site-wide deduplication note:** Before filing per-page EN-13 entries, the orchestrator  
> spot-checks whether the render gap is site-wide (fetches homepage + 1–2 other pages).  
> If the whole domain renders empty, the report says so **once** as a site-architecture  
> finding rather than repeating identical per-page Critical entries across every page checked.

---

## `emit_flag_only` — Shared Helper

```python
def emit_flag_only(check_id: str, reason: str, recommendation: str) -> dict:
    return {
        "id": check_id,
        "type": "flag_only",
        "reason": reason,
        "recommendation": recommendation,
    }
```

Copied verbatim from `freshness-corroboration` — keep the signature stable.  
Used for EN-06 in this skill.
