# Cascading Rules — Cross-Skill Ownership & Routing

> This document is the authoritative reference for how findings are **gated**,
> **routed**, and **deduplicated** across the four audit skills.  
> `compose_report.py` implements every rule listed here.

---

## 1. Ownership boundary: DV owns fetch-layer problems

| Problem | Owner | Notes |
|---------|-------|-------|
| Page blocked by bot-detect | **DV-13** | Entire page result skipped; EN/FS/ED not run |
| Page disallowed by robots.txt | **DV-16** | As above |
| Page has noindex | DV (no finding emitted) | Page marked `intentionally_excluded`; other skills skip |
| No `<meta>` description | **DV-01** | FS/EN/ED still run |
| No Organization schema | **DV-03** | ED-02 must NOT fire when no schema exists |

---

## 2. Cascading gates: DV flags feed downstream skills

### 2a. DV-13 / DV-16 → Engagement gate

```
if dv_flags["dv13_fired"] or dv_flags["dv16_fired"]:
    route EN to → EN-12 ("Page inaccessible to AI crawlers") only
    suppress all other EN checks
```

Rationale: engagement problems are irrelevant when the page isn't crawled at all.

### 2b. DV-01 critical → Engagement gate

```
if dv_flags["dv01_critical"]:
    route EN to → EN-13 ("No crawlable content: engagement moot") only
    suppress all other EN checks
```

`dv01_critical` is set on the DV flags when DV-01 fires AND the page has
< 50 words of body text (the `dv01_critical` flag from `run_dv_checks`).

### 2c. wikidata_backed → Entity-Disambiguation skip

```
if dv_flags["wikidata_backed"]:
    log site-level strength: "Entity anchored to Wikidata knowledge graph"
    skip ED-01 through ED-06 entirely
    ED-05 logged as strength
```

### 2d. No skip for FS

Freshness checks run regardless of DV flags — a bot-blocked page still has
a freshness problem worth surfacing (via the "no cache headers" or
"no date metadata" findings).  
Exception: if `page_result["error"]` is set (network failure), FS is skipped.

---

## 3. Deduplication rules

### 3a. DV-03 vs ED-02

- DV-03: **No Organization schema at all** — fires when `_parse_org_schema()` returns `None`.
- ED-02: **Schema present but lacks sameAs/identifier** — fires ONLY when
  (a) `_ed01_fired = True`, AND (b) an Organization schema exists.

**Never fire both DV-03 and ED-02 for the same page.** The orchestrator must
check: if DV-03 is in `dv_result["findings"]`, suppress ED-02 even if it fires.

### 3b. Cross-page deduplication

When the same check ID fires on multiple pages:
- **Merge into a single finding**: take the worst-severity instance; list all
  affected page URLs in the `pages` array.
- Exception: flag_only items are NOT deduplicated (each page may need
  independent external lookup).

### 3c. Strength deduplication

Log a strength **once per site** (not once per page). The orchestrator
collapses duplicate strength IDs.

---

## 4. Severity escalation

| Condition | Action |
|-----------|--------|
| Same finding ID fires on ≥ 3 pages | Escalate severity by one level (low→medium, medium→high) |
| DV-01 fires AND page has 0 indexable words | Keep as `critical` (already set by `dv01_critical` flag) |

---

## 5. Overall health scoring

The `overall_health` field in the summary scorecard is derived from a
**weighted defect score**:

```
score = (critical × 10) + (high × 4) + (medium × 1) + (low × 0.25)
```

| Score range | Label |
|-------------|-------|
| 0 | `excellent` |
| 1–3 | `good` |
| 4–9 | `fair` |
| 10–24 | `poor` |
| ≥ 25 | `critical` |

---

## 6. Suggested actions ordering

The `suggested_actions` array in the report is sorted by:
1. `priority` (critical → high → medium → low)
2. Finding frequency (how many pages triggered it — descending)
3. Skill order: DV → FS → EN → ED (for ties)
