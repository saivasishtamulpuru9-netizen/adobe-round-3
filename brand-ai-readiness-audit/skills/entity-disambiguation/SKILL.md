---
name: entity-disambiguation
description: >
  Audits entity identity clarity (ED-01 … ED-06): name collision risk,
  missing disambiguation fields in Organization schema, brand-name casing
  inconsistencies, missing social profile links, Wikipedia/Wikidata linkage,
  and ambiguous founding facts (flag_only). All checks are skipped when
  the wikidata_backed flag from crawl-render-audit is true — entity identity
  is already resolved via the Wikidata graph.
license: MIT
allowed-tools:
  - python_interpreter
---

# Entity Disambiguation Audit (ED-01 … ED-06)

## When to use
Called by **audit-orchestrator** per page, after `crawl-render-audit` produces
its result dict. The DV flags and DV findings from that result are passed in.

## Inputs
- `page_result` (required) — per-page JSON dict from `crawl-render-audit`.
- `dv_flags` (required) — the `flags` sub-dict from the DV result:
  `{ "dv01_critical": bool, "dv13_fired": bool, "dv16_fired": bool, "wikidata_backed": bool }`.
- `dv_findings` (optional) — list of DV findings (used to check whether DV-03 fired).

## Procedure

1. **Skip gate:** If `dv_flags["wikidata_backed"] = true` →  
   log a site-level strength ("entity anchored to Wikidata knowledge graph"),  
   log ED-05 as a strength, and **return**. All ED-01…ED-06 checks are skipped.

2. **ED-01 (MUST run first)** (`check_ed01()`):  
   Extract brand name from Organization JSON-LD > `og:site_name` > `og:title` prefix >  
   `<title>` prefix > domain name.  
   Check against collision tiers:  
   - Known high-collision acronym (AI, HR, HP, IBM, GE, SAP…) → **High**.  
   - Generic English word (apple, nexus, edge, canvas…) → **Medium**.  
   - Name ≤ 3 chars with no `sameAs`/`identifier` in schema → **Low**.  
   When a finding is emitted, set `page_result['_ed01_fired'] = True` and  
   `page_result['_ed01_brand'] = brand` — gates ED-02 and ED-06.

3. **ED-02** (`check_ed02()`):  
   Only fires when `_ed01_fired = True` AND an Organization-type JSON-LD block exists.  
   Check for `sameAs`, `identifier`, `legalName` in the block.  
   Missing fields → **Medium** finding.  
   *Boundary vs. DV-03:* If no schema exists at all, DV-03 covers the gap — ED-02 does  
   NOT fire. Never file both DV-03 and ED-02 for the same missing-schema issue.

4. **ED-03** (`check_ed03()`):  
   Extract all occurrences of the brand name token from body text.  
   If minority variant(s) exceed 15% of total occurrences → **Medium** inconsistency finding.  
   Skip if total occurrences < 2 or if brand token < 3 chars.

5. **ED-04** (`check_ed04()`):  
   Check DOM (footer, header, nav) and Organization JSON-LD `sameAs` for social platform links.  
   - In `sameAs` → **strength** (no finding).  
   - Nowhere → **Medium** finding.  
   - DOM only, not in `sameAs` → **Low** finding.

6. **ED-05** (`check_ed05()`):  
   Three-way outcome:  
   - Wikipedia/Wikidata URL in DOM AND in `sameAs` → **strength**.  
   - Wikipedia/Wikidata URL in DOM but NOT in `sameAs` → **Medium** finding.  
   - No Wikipedia/Wikidata link found → **flag_only** (external search required).

7. **ED-06** (`check_ed06_flag_only()`):  
   Only fires when `_ed01_fired = True` AND founding/identity fact phrases  
   ("founded in YYYY", "established in YYYY", "headquartered in City") are found in body.  
   Always flag_only — confirming factual conflicts requires external encyclopedic lookup.

8. **Return** the result dict (see Output).

> **Full check details, severity tables, and boundary rules:**  
> see [`references/ed_checklist.md`](references/ed_checklist.md)

## Output

```json
{
  "url": "https://example.com/",
  "findings": [
    {
      "id": "ED-01",
      "title": "Brand name 'Oracle' collides with a common English word",
      "severity": "medium",
      "evidence": "Brand name 'Oracle' is a common English word...",
      "suggested_action": {
        "summary": "Add a sameAs field pointing to a unique external registry...",
        "priority": "medium"
      }
    }
  ],
  "flag_only_items": [
    {
      "id": "ED-05",
      "type": "flag_only",
      "reason": "No Wikipedia or Wikidata link found...",
      "recommendation": "Search Wikipedia for 'Oracle' and Wikidata for a Q-number..."
    }
  ],
  "strengths": []
}
```
