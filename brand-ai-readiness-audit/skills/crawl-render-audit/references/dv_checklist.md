# DV Checklist — Discoverability Checks (DV-01 … DV-20)

> Reference document for the **crawl-render-audit** skill.  
> Each entry: detection method · severity heuristic · suggested_action template · ownership rules.

---

## Fetch Pipeline (execute in this exact order per page)

| Step | Condition | Action |
|------|-----------|--------|
| 1 | `robots_disallowed = true` | Emit DV-16 · STOP — do not fetch page |
| 2 | Response is bot-block / WAF challenge | Emit DV-13 · STOP |
| 3 | `meta[robots]` contains `noindex` | Mark `intentionally_excluded` · skip DV-01/02/03/04 |
| 4 | Wikidata sameAs link in HTML | Set `wikidata_backed` flag · skip DV-03 / ED-0x |
| 5+ | Otherwise | Run DV-01 → DV-20 in order |

---

## DV-01 — JS-render gap / near-empty body

**Detection:** Script-able.  
Fetch raw HTML, strip nav/footer/script/style boilerplate, count remaining words.

| Condition | Severity |
|-----------|----------|
| Populated `<head>` (has `<title>`) + body word count < 20 | **Critical** (auto) |
| Literal "enable JavaScript" / "JavaScript required" in body | **Critical** |
| Body word count < 30 on non-transactional page | **High** |
| Body word count < 50 on non-transactional page | **Medium** |

**Cascading rule:** When DV-01 fires Critical, set `dv01_critical = true` flag.  
`engagement-audit` **must** route this page to EN-13 (not_assessed) instead of scoring it.  
`checks_dv.py` also sets `page_result["_dv01_fired"] = True` to suppress DV-04 (same root cause).

**Template:**  
> "Move {content_type} to server-side rendering (SSR/prerender) — currently absent from raw HTML  
> on {n_pages} page(s) checked."

**Priority:** Always `high`; `critical` if core page (home/product/competition detail).

---

## DV-02 — Missing/empty meta description & OG/Twitter tags

**Detection:** Script-able. Parse `<head>`, check presence + non-empty value of each field.

| Field absent/empty | Severity |
|--------------------|----------|
| `meta[description]` | **High** |
| `og:title`, `og:description` | **Medium** |
| `og:image`, `twitter:*` | **Medium** |

**Ownership boundary vs. DV-12:**  
- DV-02 fires when a field is **absent or empty**.  
- DV-12 fires when a field is **present but generic/duplicated across distinct pages**.  
- Never fire both for the same field on the same page.

**Template:**  
> "Add a meta description and OG/Twitter tags summarising {entity_name} — currently {missing_fields} are  
> empty, giving assistants no summary text to preview or cite."

---

## DV-03 — No structured data (schema.org / JSON-LD)

**Detection:** Script-able. Search HTML for `<script type="application/ld+json">`; parse; check `@type`.

**Preconditions:**
1. If `wikidata_backed` flag is set → **skip DV-03** (entity identity resolved via Wikidata graph).
2. Confidence tier: `confirmed_absent` if raw HTML was checked; `not_detected_in_pass` if only rendered text → log as to-verify, **not a scored finding**.

**Severity:**

| Condition | Severity |
|-----------|----------|
| Default (no other compounding factors) | **High** |
| Compounded with DV-01 Critical OR meta_description also missing | **Critical** |

**Schema type selection by page role:**

| Page path/context | Recommended schema |
|-------------------|--------------------|
| Home / About | `Organization` / `LocalBusiness` |
| Product / Collection | `Product` + `Offer` |
| FAQ / Help (Q&A content exists) | `FAQPage` |
| Event / Competition / Program | `Event` |
| Blog / Article / News | `Article` |
| Academic / College | `CollegeOrUniversity` / `EducationalOrganization` |
| App / Tool | `SoftwareApplication` |
| Review / Ratings content | `Review` / `CriticReview` |

**Ownership boundary vs. ED-02:**  
DV-03 fires "no Organization schema" as a general gap when no name-collision risk exists.  
If collision risk exists AND the missing schema lacks `identifier`/`sameAs` fields → routes to ED-02.

**Template:**  
> "Add {schema_type} JSON-LD to {page_type} — {found}/{total} relevant pages currently have valid markup."

---

## DV-04 — Thin content / nothing quotable

**Detection:** Script-able heuristic (word count < 150). LLM judgment step: confirm text is genuinely thin, not intentionally minimal.

**Severity:** High.  
**Skip if:** DV-01 already fired Critical (same root cause — don't double-count).

**Template:**  
> "Add 150–300 words of plain static text explaining what {entity_name} is, what it does, and who it's for  
> — currently the only substantive text is '{shortest_summary}'."

---

## DV-05 — Facts locked in non-text form

**Detection:** Script-able per sub-case.

| Sub-check | Method | Severity |
|-----------|--------|----------|
| (a) Images near trust sections with empty/generic alt | Inspect `<img alt>` + parent context | **Medium** |
| (b) Address inside Google Maps `href` only, not visible text | Detect map link; check adjacent text | **Medium** |
| Email obfuscation via Cloudflare scraper shield | Detect JS-encoded mailto | **Low** (legitimate anti-spam) |

**Ownership boundary vs. EN-08:**  
- Stat/counter `<span>` elements with no static digit value → **EN-08** (not DV-05).  
- Images or href-only addresses → **DV-05**.

**Template:**  
> "Add {fact} as plain visible text near {location} — it currently exists only inside {non_text_container}  
> and isn't extractable as a fact."

---

## DV-06 — Duplicate/templated authored copy within a page

**Detection:** Script-able. Hash/fuzzy-match paragraph text per named H2/H3 section across the same page. Flag when similarity > 90 % between two distinct named sections.

**Severity:** Medium.

**Consistency family:** DV-06 (within-page duplicate text), FS-02 (conflicting numbers), FS-04 (mismatched listings), DV-12 (duplicate title/meta across URLs) — four variants of the same root cause.

**Ownership boundary vs. DV-15:**  
- DV-06 = deliberately authored copy reused verbatim across different **named sections** (lazy authoring).  
- DV-15 = same DOM block mechanically repeated many times (rendering bug).

**Template:**  
> "Write distinct copy for {section_a} and {section_b} — they currently share identical text, giving  
> assistants nothing distinct to cite for either."

---

## DV-07 — Generic/unverifiable testimonials

**Detection:** Partially script-able; LLM judgment recommended.
- Script-able proxy: count testimonial/blockquote elements; detect outbound links to review platforms (Trustpilot, Google, G2, Capterra, LinkedIn, Clutch).
- LLM judgment step: confirm near-identical phrasing pattern across quotes (e.g. all say "great service / highly recommend").

**Severity:** Medium.  
**No finding if:** outbound links to real review platforms are present.

**Template:**  
> "Link testimonials to verifiable external reviews (Google/LinkedIn) — the {n} testimonials shown are  
> currently unlinked, unattributed, or template-like."

---

## DV-08 — Missing canonical / tracking-parameter URL variants

**Detection:** Script-able. Check for `<link rel="canonical">`; compare against URL stripped of known tracking params.

**Nuance:**  
- Only flag tracking-parameter/canonical issues that originate from the **site's own internal links** or the site's own missing canonical tag.  
- If the parameter clearly arrived via external referral context (search result, ad, another site's link), do **not** flag as a site defect — note only that an assistant citing this URL would propagate a low-value link.

**Severity:** Low.

**Template:**  
> "Add `<link rel='canonical'>` pointing to the clean URL — this page was fetched with a tracking  
> parameter ({param}) and no canonical was found."

---

## DV-09 — Stuffing / spam-signal content

**Sub-checks:**

| Sub-check | Detection | Threshold | Severity |
|-----------|-----------|-----------|----------|
| (a) Link-stuffed prose | Count `<a>` inside each `<p>` | > 8 links in one `<p>` | **Medium** |
| (b) Keyword-stuffed meta-keywords | Token count in `meta[keywords]` | > 15 tokens | **Low** |

**Templates:**  
(a) > "Move the {n}-link list out of inline prose into a normal navigation block — dense link-stuffed paragraphs  
> read as manipulative."  
(b) > "Trim or remove the meta-keywords tag — it lists {n} largely unrelated terms and carries no discoverability value."

---

## DV-10 — No individual product/detail pages

**Detection:** Script-able proxy. Check whether product/service names link to unique URLs vs. `#` anchors or the same listing page.

**Severity:** High.

**Template:**  
> "Give each product its own URL with specs (dimensions, capacity, material, price) — currently {n}  
> products are listed by name/image only with no detail page."

---

## DV-11 — No site/company-level orientation text

**Detection:** Script-able proxy. Check for a company-level "what is X" sentence on the homepage, distinct from product-level copy. Only fires on root-path pages.

**Severity:** Medium.

**Template:**  
> "Add a short 'what is {company_name}' section (2–3 sentences) — the page describes individual products  
> but never states what the parent company/platform is."

---

## DV-12 — Generic/duplicated metadata reused across distinct URLs

**Detection:** Script-able across multi-URL crawl. Compare `<title>` and `meta[description]` across ≥ 2 pages; flag exact matches on pages that should be topically distinct.

**Severity:** High.

**Ownership boundary vs. DV-02:** Absent field = DV-02; present-but-generic-duplicate = DV-12. Never fire both for the same field.

**Consistency family:** Fourth member (see DV-06).

**Template:**  
> "Give this page its own unique `<title>` and meta-description describing {specific_topic} — it currently  
> reuses the sitewide tagline/title, making it indistinguishable from every other page on the site to a crawler."

---

## DV-13 — Crawler blocked via bot-detection / WAF challenge

**Detection:** Script-able. HTTP 403/429/503 OR Cloudflare/WAF challenge body patterns OR WAF-specific response headers. Distinguish from DV-01 (returns 200 with empty body) by inspecting the response itself.

**Severity:** **Critical** always.

**Cascading rule:** Set `dv13_fired = true`. `engagement-audit` **must** route to EN-12 (not_assessed). Also trigger DV-17 (external search step).

**Template:**  
> "Allowlist verified AI/search crawler user-agents (GPTBot, PerplexityBot, Googlebot) in the WAF, or  
> serve a lightweight static/cached version of key public pages — the site currently rejects automated  
> fetches outright, so no downstream fix can take effect until this is resolved."

---

## DV-15 — Structural content duplication (broken carousel/slider render)

**Detection:** Script-able. Hash/fingerprint DOM blocks (`div`, `section`, `article`, `li`); count identical or near-identical (> 95 % similarity) sibling blocks. Threshold: > 3 exact repeats of a substantial block (> 80 chars).

| Repeat count | Severity |
|-------------|----------|
| 4–5 | Low |
| 6–10 | Medium |
| > 10 | High |

**Ownership boundary vs. DV-06:**  
- DV-15 = same DOM block mechanically repeated (rendering artefact).  
- DV-06 = same authored text reused across named sections (lazy authoring).

**Template:**  
> "Render each {block_type} once in the base HTML; generate carousel duplicates client-side after initial  
> paint — currently {block_type} repeats verbatim {n}+ times in a single fetch."

---

## DV-16 — Deliberate robots.txt disallow

**Detection:** Script-able. `robots.txt` was fetched **successfully (HTTP 200)**, parsed, and explicitly disallows `/` (or the specific path) for crawl agents. Distinguishes a declared policy from DV-13's unstated network-layer block.

**Severity:** **Critical** always.

**Cascading rule:** Same as DV-13 → EN-12 + DV-17.

### How 401/403 on the robots.txt URL is disambiguated from a real declared policy

Per **RFC 9309 §2.3.1**, a 4xx response when fetching `robots.txt` means the file is **"unavailable"** — not that the site declares a crawl disallow. The correct crawler behavior for "unavailable" is **fail-open** (assume unrestricted access).

**Fail-closed** (assume complete disallow) is reserved for RFC 9309's **"unreachable"** case: `5xx` responses and network-level failures (timeout, DNS, connection refused).

The implementation in `fetch_page.py :: check_robots()` follows this exactly:

| robots.txt fetch result | RFC 9309 case | `allowed` | `inconclusive_bot_block` | DV fired |
|-------------------------|---------------|-----------|--------------------------|----------|
| HTTP 200 + Disallow rule matches | — | `False` | `False` | **DV-16** |
| HTTP 200 + no matching Disallow | — | `True` | `False` | None |
| HTTP 401 or 403 | "unavailable" | `True` | `True` | None (note logged; DV-13 may fire if main page also blocked) |
| HTTP 5xx | "unreachable" | `False` | `False` | Blocked (ROBOTS\_UNREACHABLE, not DV-16) |
| Network timeout / DNS fail | "unreachable" | `False` | `False` | Blocked (ROBOTS\_UNREACHABLE, not DV-16) |
| HTTP 404 or other 4xx | "unavailable" | `True` | `False` | None |

**Critical invariant:** `make_dv16_finding()` in `checks_dv.py` must only be called when `robots_disallowed=True` AND `blocked_reason="ROBOTS_DISALLOWED"` — which only happens when robots.txt was HTTP-200-fetched, parsed, and contained a matching rule. A 401/403 on robots.txt must never reach DV-16.

**Template:**
> "This is a deliberate robots.txt policy. Publish a crawlable public-information subset (non-transactional:
> categories, FAQs, general info) under a permissive robots.txt group scoped to verified AI/search agents,
> or explicitly accept that no citation-based discovery is possible."

---

## DV-17 — Third-party proxy content fills the citation gap

**Detection:** External lookup (LLM/agent step). Fires only as a consequence of DV-13/DV-16. Search `"{domain} [key service]"` and check whether unofficial guide sites outrank or substitute for the blocked primary domain.

**Severity:** High.

**Template:**  
> "Because {entity}'s primary domain is inaccessible (see {DV-13/DV-16 finding id}), third-party sources  
> ({proxy_domains}) are filling the citation gap. Resolving the underlying access block is the root fix;  
> in the interim, publish an official, crawlable lightweight guide page."

---

## DV-18 — Publishes a /llms.txt discovery file

**Detection:** Script-able. `GET /llms.txt` at domain root.

- **Present:** Log as a **strength** (no finding).
- **Absent on a content-rich/docs-heavy site:** Log as a **proactive suggestion** (Low severity, `proactive: true`).

**Template (absence case):**  
> "Publish a simple /llms.txt at the domain root listing key crawlable URLs — cheap, high-leverage for  
> LLM-based citation, and not yet common enough to be an expected baseline."

---

## DV-19 — Generic/unattributed authorship on review or news-style content

**Detection:** Script-able proxy + LLM judgment.  
- Regex for generic byline patterns in `[class*=author]`, `[class*=byline]`, `[rel=author]`, `[itemprop=author]`.  
- Generic patterns: "Team", "Staff", "Desk", "Admin", "Editorial", "Correspondent", "Bureau".  
- LLM judgment step: confirm the byline is genuinely generic, not an unusual real name.

**Applies to:** Pages with `/review`, `/article`, `/news`, `/blog`, `/post`, `/story` in path, or with an `<article>` element.

**Severity:** Medium.

**Template:**  
> "Attribute {content_type} to a named individual with an author schema field where possible — currently  
> attributed only to '{generic_byline}', weakening the source-credibility signal."

---

## DV-20 — High boilerplate-to-content ratio

**Detection:** Script-able. Ratio of words inside `<article>`/`<main>`/`role=main` to total page word count. Absence of a semantic `<article>` boundary is itself a contributing signal.

**Fires on:** Content-style pages (path contains `/review`, `/article`, `/news`, `/blog`, `/post`, `/story`).  
**Threshold:** Ratio < 20 % **or** no semantic boundary found.  
**Severity:** Medium.

**Template:**  
> "Wrap the primary content in a clear semantic boundary (`<article>`) so extraction tools can reliably  
> isolate it from surrounding site chrome — currently the {content_type} is diluted by a high ratio of  
> repeated boilerplate."

---

## Precondition — noindex short-circuit

Before firing any DV-0x finding, check `meta[robots]` for `noindex`.  
If present: mark `status: intentionally_excluded` and skip DV-01/02/03/04.  
Rationale: transactional/personalized/per-query pages (cart, search results, account) are correctly excluded — flagging them is a false positive.

## Proactive suggestions (no defect required)

These are emitted by `checks_dv.py` / `compose_report.py` even on a clean audit:

| Trigger | Suggestion |
|---------|-----------|
| FAQ-shaped content exists, no FAQPage schema | Add FAQPage JSON-LD |
| Strong identity facts (CIN, founding year) + no schema + no collision risk | Add Organization JSON-LD |
| Named/attributed testimonials, no Review schema | Add Review/AggregateRating JSON-LD |
| Third-party press citations not linked as structured data | Add sameAs / citation structured data |
| No /llms.txt on a content-rich site | Publish /llms.txt (DV-18) |
