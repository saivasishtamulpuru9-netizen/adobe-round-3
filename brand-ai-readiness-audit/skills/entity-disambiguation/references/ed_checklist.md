# ED Checklist — Entity Disambiguation Checks (ED-01 … ED-06)

> Reference document for the **entity-disambiguation** skill.  
> Each entry: detection method · severity heuristic · template · boundary rules.

---

## Skip Condition — wikidata_backed

**Check the `wikidata_backed` flag from DV results BEFORE running any ED check.**

If `wikidata_backed = true`:
- Log as a site-level **strength**: "Entity identity anchored to Wikidata knowledge graph."
- Log ED-05 as a strength.
- **Skip all ED-01 through ED-06 checks entirely.**

Rationale: when a Wikidata sameAs link exists in the page HTML, the entity's identity
is already resolved via the world's largest open knowledge graph. Filing collision or
disambiguation findings on a Wikidata-backed entity is noise.

---

## Check Execution Order

| Step | Check | Gate |
|------|-------|------|
| 0 | wikidata_backed? | Skip all if true |
| 1 | **ED-01** | Always (sets `_ed01_fired` flag) |
| 2 | ED-02 | Only if `_ed01_fired = True` AND Org schema exists |
| 3 | ED-03 | Always |
| 4 | ED-04 | Always |
| 5 | ED-05 | Always (three-way outcome: strength / finding / flag_only) |
| 6 | ED-06 | Only if `_ed01_fired = True` AND founding claims in body |

---

## ED-01 — Brand name collision risk

**Detection:** Script-able.  
Extract brand name from Organization JSON-LD, `og:site_name`, `og:title`, `<title>`, or domain.  
Check against: known high-collision acronyms, generic English word list, and short-name threshold.

**Collision tiers:**

| Condition | Severity |
|-----------|----------|
| Name is a well-known acronym (AI, HR, IBM, HP, GE, SAP, ARM, etc.) | **High** |
| Name is a generic English word (apple, nexus, aurora, edge, canvas, etc.) | **Medium** |
| Name is ≤ 3 characters AND no `sameAs`/`identifier` in schema | **Low** |
| Name passes all checks | No finding |

**Side effect:** Sets `page_result['_ed01_fired'] = True` — gates ED-02 and ED-06.

**Template:**  
> "Add a sameAs identifier (Wikidata Q-number, CIN, or official registry ID) to the  
> Organization JSON-LD for '{brand}' — the {type} is shared by multiple entities  
> and gives AI assistants no way to distinguish this entity from others."

---

## ED-02 — Organization schema present but lacks identifier / sameAs

**Detection:** Script-able.  
Find Organization-type JSON-LD block; check for `sameAs`, `identifier`, `legalName` fields.

**Preconditions (BOTH must be true):**
1. `_ed01_fired = True` (collision risk detected in ED-01).
2. An Organization-type JSON-LD block exists on the page.

If no schema at all → DV-03 already covers the gap. **Never fire both DV-03 and ED-02** for the same issue.

**Severity:** Medium.

**Recommended sameAs values (in priority order):**
1. Wikidata Q-number URI (`https://www.wikidata.org/wiki/QXXXXXX`)
2. LinkedIn company profile URL
3. GLEIF LEI (for financial entities)
4. Companies House number (UK entities)
5. MCA CIN (Indian entities)
6. Government official website

**Template:**  
> "Add {missing_fields} to the Organization JSON-LD — recommended sameAs values:  
> Wikidata Q-number, LinkedIn company URL, GLEIF LEI, or official government registry entry."

---

## ED-03 — Inconsistent brand name spelling / casing

**Detection:** Script-able heuristic.  
Extract all occurrences of the brand name token from body text.  
Bucket by normalised form. Flag when minority variant(s) exceed 15% of total occurrences.

**Example patterns caught:**
- `MyBrand` (dominant) vs `My Brand` (minority)
- `ExampleCorp` vs `Examplecorp` vs `EXAMPLECORP`
- `AI Assistant` vs `AI assistant` vs `Ai Assistant`

**Threshold:** < 15% variance rate → skip (likely intentional heading vs body casing).

**Severity:** Medium.

**Template:**  
> "Standardise the brand name to a single canonical form ('{dominant_form}') across  
> all occurrences — currently {n} variant form(s) appear at a {pct}% inconsistency rate."

---

## ED-04 — No official social profile links

**Detection:** Script-able.  
Check DOM (footer, header, nav) and Organization JSON-LD `sameAs` for social platform links:  
LinkedIn, Twitter/X, Facebook, Instagram, YouTube, GitHub, Crunchbase, Glassdoor, G2, Clutch.

**Three outcomes:**

| Condition | Output |
|-----------|--------|
| Social links in `sameAs` structured data | **Strength** (machine-readable; no finding) |
| No social links anywhere on page | **Medium** finding |
| Social links in DOM but not in `sameAs` | **Low** finding (visible but not machine-readable) |

**Templates:**  
(Medium): "Add official social profile URLs to the footer AND to Organization JSON-LD sameAs —  
social profiles allow AI assistants to corroborate entity identity across platforms."  
(Low): "Add the social profile URL to the Organization JSON-LD sameAs array —  
it's already linked from the DOM; formalising it makes the connection machine-readable."

---

## ED-05 — Wikipedia / Wikidata entry not linked

**Detection:** Script-able (DOM scan) + external lookup (flag_only if no link found).

**Three outcomes:**

| Condition | Output |
|-----------|--------|
| `wikidata_backed = True` (from DV flags) | **Strength** — entity already anchored |
| Wikipedia/Wikidata URL in DOM AND in `sameAs` | **Strength** — fully machine-readable |
| Wikipedia/Wikidata URL in DOM but NOT in `sameAs` | **Medium** finding |
| No Wikipedia/Wikidata link anywhere | **Flag-only** (external search step required) |

**Flag-only template:**  
> "Search Wikipedia for '{brand}' and Wikidata for a Q-number. If an entry exists,  
> add the URL to Organization sameAs. If no entry exists, consider creating a neutral,  
> sourced Wikipedia stub or a Wikidata entry — this is the strongest possible  
> machine-readable identity signal for AI assistants."

---

## ED-06 — Ambiguous founding / identity facts (flag_only)

**Detection:** Regex pre-extraction + external lookup (always flag_only).

**Precondition:** Only fires when `_ed01_fired = True` (name collision risk detected)  
AND founding/identity fact claims are found in body text  
("founded in YYYY", "established in YYYY", "headquartered in City", "since YYYY").

**Rationale:** Ambiguous facts are more dangerous when the name itself is colliding —  
an AI assistant may attribute the facts to a different entity with the same name.

**Always flag_only** — confirming factual conflicts requires external encyclopedic lookup.

**Flag-only template:**  
> "Cross-check the identity claims for '{brand}' (e.g. '{example_claim}') against  
> Wikipedia, Wikidata, Companies House, or the relevant corporate registry to verify  
> they are consistent with the encyclopedic record."

---

## Proactive / beyond-defect suggestions

These are emitted even on a clean audit (no ED defects):

| Trigger | Suggestion |
|---------|-----------|
| No collision risk + no schema | Add basic Organization JSON-LD (covered by DV-03) |
| Social links in DOM but not sameAs (Low finding, above) | Move links to sameAs |
| No Wikipedia entry known to exist | Consider creating a Wikidata entry |
| Name is unique + sameAs present + social links + Wikidata | Log as full strength — entity identity is well-anchored |
