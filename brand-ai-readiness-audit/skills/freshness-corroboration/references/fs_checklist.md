# FS Checklist — Freshness & Corroboration Checks (FS-01 … FS-06)

> Reference document for the **freshness-corroboration** skill.  
> Each entry: detection method · severity heuristic · template · ownership/boundary rules.

---

## Execution Order

Run checks in this order:

| Step | Check | Why first? |
|------|-------|-----------|
| 1 | **FS-06** | Wiki-style markers are free, high-confidence signals — run before any inferred corroboration check |
| 2 | FS-01 | Stale date claims are script-detectable and high-confidence |
| 3 | FS-02 | Numeric inconsistency — regex pre-extraction + LLM confirmation |
| 4 | FS-03 | Missing freshness signal — confidence-tier check |
| 5 | FS-04 | Nav/footer listing diff |
| 6 | FS-05 | Flag-only external corroboration recommendation (always emitted) |

> **Precondition:** Only run on pages where `crawl-render-audit` confirmed successful fetch  
> (not blocked, not noindex). The orchestrator enforces this gate.

---

## FS-01 — Stale "current" claims vs. today's date

**Detection:** Script-able.  
Extract date strings from banners, notices, copyright lines, and body text.  
Cross-reference with a "current/upcoming" context keyword in the same sentence.  
Compare parsed date against today's system date; flag if in the past.

**Context keywords triggering comparison:**  
`scheduled for`, `upcoming`, `current`, `now live`, `maintenance`, `registration open`,  
`deadline`, `apply before`, `last date`, `due date`, `notice`, `alert`, `©`, `copyright`

**Severity:**

| Condition | Severity |
|-----------|----------|
| Stale operational claim (maintenance window, exam date, deadline, fee notice, result date) | **High** |
| Stale copyright year (lag > 2 years) | **Medium** |
| Stale general date claim | **Medium** |

**Note:** Copyright year lagging ≤ 2 years is **not** flagged (normal update lag).

**Template:**  
> "Remove or update the {notice_type} referencing {stale_date} — that date has passed,  
> and a stale 'current' claim undermines freshness signals for the whole page,  
> especially given other content on the page is actively maintained."

---

## FS-02 — Internal numeric inconsistency

**Detection:** Regex pre-extraction + LLM judgment confirmation.

Script extracts numeric claims of the same fact-type pattern (years of experience, client count,  
country count, employee count, uptime %, awards) from the full page (meta description + body).  
If the same pattern yields two or more different numbers, flag as a mismatch candidate.

**LLM judgment step (required before scoring):**  
Confirm the two figures refer to the *same* fact, not two legitimately different metrics using  
similar phrasing (e.g. "11 years of company history" vs "14 years of combined team experience").

**Fact-type patterns detected:**
- `{N}+ years of [experience / leadership / expertise]`
- `{N}+ [clients / customers / users / projects]`
- `{N}+ [countries / cities / offices / locations]`
- `{N}+ [employees / team members / professionals]`
- `{N}+ [awards / certifications]`
- `{N}% [uptime / availability / satisfaction / success rate]`

**Severity:** Medium.

**Consistency family:** FS-02 (conflicting numbers), DV-06 (within-page duplicate copy),  
FS-04 (mismatched listings), DV-12 (duplicate title/meta across URLs) — same root cause.

**Template:**  
> "Reconcile the two different {fact_type} figures on this page ({value_a} vs {value_b}) —  
> an AI assistant reading only this page has no way to know which is correct."

---

## FS-03 — No dated / "last updated" signal

**Detection:** Script-able.  
Check for: `article:published_time`, `article:modified_time` meta tags, and visible "last updated /  
as of [date] / version N" text in the body.

**Confidence tier (same rule as DV-03):**  
- Raw HTML available: `confirmed_absent` → scored finding.  
- Only rendered text available: `not_detected_in_pass` → log as to-verify, **not a scored finding**.  
  (A "last edited" timestamp may live in a footer that the text extraction didn't capture.)

**Applies to:** Content-style pages (path contains `/blog`, `/article`, `/news`, `/post`, `/review`,  
`/guide`, `/docs`, `/help`) and homepages. Skipped on transactional/utility pages.

**Severity:**

| Page type | Severity |
|-----------|----------|
| Content/article/blog page | **Medium** |
| Homepage | **Low** |

**Template:**  
> "Add a visible 'last updated' or version note (e.g. 'Updated September 2026')  
> so assistants have a freshness signal to cite confidently — undated content  
> is treated as potentially stale."

---

## FS-04 — Internal listing / consistency mismatches (non-numeric)

**Detection:** Script-able for nav/footer item diff; typo detection is a proxy (similarity matching).

Extract anchor text from `<nav>` elements and `<footer>` elements.  
Diff the two sets after lowercasing and stripping generic navigation words  
(home, contact, login, search, cart, privacy, terms, sitemap, etc.).

| Signal | Severity |
|--------|----------|
| An item in nav has a near-duplicate in footer (60–99% similarity — possible typo/rename) | **Low** |
| ≥ 3 substantive items in nav absent from footer (or vice-versa) | **Low** |

**Note:** Full automated spellchecking of nav labels is lower-automation priority;  
the similarity proxy catches obvious transpositions and missing letters.

**Consistency family:** Fourth member (see FS-02, DV-06, DV-12).

**Template:**  
> "Reconcile the {location_a} and {location_b} listings — {location_a} includes {extra_items}  
> that {location_b} omits, which reads as inconsistent/outdated to both visitors and crawlers."

---

## FS-05 — External corroboration / disputed-fact attribution

**Detection:** Cannot be verified from a single-page fetch alone.  
**Status:** Flag-only (emitted via `emit_flag_only()` — not a scored finding).

**Two outcomes:**

| Condition | Output |
|-----------|--------|
| Page explicitly attributes claims to named external sources (e.g. "according to a British Council letter...") | **Strength** — log as a positive pattern; no flag |
| No explicit attribution to external sources | **Flag-only** — manual-audit recommendation |

**Flag-only template:**  
> "Facts on this page should be spot-checked against third-party directories/retailers  
> for outdated versions (old price, old logo, discontinued product) —  
> this requires checking sources beyond this page."

**Positive example pattern:**  
Pages that surface genuine factual disagreement *with attribution* (named sources, multiple  
references, caveated phrasing) rather than silently picking one version — this is the  
opposite of the FS-02 internal-inconsistency failure mode and should be logged as a strength.

---

## FS-06 — Self-reported corroboration gaps (wiki-style markers)

**Detection:** Script-able.  
Regex for inline wiki-style markers in both raw HTML (`<sup>` tags) and body text.  
**Run this check FIRST** on any collaboratively-edited domain, before falling back  
to inferred corroboration checks — these are free, high-confidence signals.

**Markers detected:**

| Marker | Severity |
|--------|----------|
| `[citation needed]` | **Medium** — claim asserted with zero support |
| `[verification needed]` | **Medium** |
| `[dubious]` / `[disputed]` | **Medium** |
| `[dead link]` | **Low** — claim was sourced but link rotted |
| `[needs update]` | **Low** — content may be outdated |
| `[clarification needed]` | **Low** — structural gap, not necessarily false |
| `[unreliable source?]` | **Low** |

**Template:**  
> "Source or remove the flagged claim — the page already self-reports a corroboration  
> gap via an inline '[{tag}]' marker at '{claim_snippet}'."

**Note:** Applies to any page, not just Wikipedia — other wiki-style platforms, knowledge bases,  
and collaboratively-edited documentation pages may use the same conventions.

---

## `emit_flag_only` Helper (shared with engagement-audit)

```python
def emit_flag_only(check_id: str, reason: str, recommendation: str) -> dict:
    return {
        "id": check_id,
        "type": "flag_only",
        "reason": reason,
        "recommendation": recommendation,
    }
```

This helper is **shared verbatim** with `engagement-audit` for EN-06 (deep-link gap check).  
Keep its signature stable. The orchestrator surfaces `flag_only` items in a dedicated  
section of the final report, separate from scored `findings`.

---

## Proactive / beyond-defect suggestions

These are emitted even on a clean audit (no FS defects found):

| Trigger | Suggestion |
|---------|-----------|
| Content-rich page, no `article:published_time` | Add structured freshness metadata |
| Press mentions or case studies exist on-page but are not linked as corroborating sources in structured data | Add `sameAs` / citation structured data |
| Facts are internally consistent but sourced from a single domain only | Recommend cross-referencing with third-party industry databases |
