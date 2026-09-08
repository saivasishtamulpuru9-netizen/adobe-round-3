# Adobe University Hackathon 2026 — Round 3
## Brand AI-Readiness Audit — Agent Skill Marketplace

This repository contains the complete submission for **Round 3: Build the Agent Skill Marketplace**.

### Repository Structure
- [`brand-ai-readiness-audit/`](./brand-ai-readiness-audit/) — Complete Agent Skills marketplace package containing:
  - `marketplace.json` — Manifest declaring the 5 skills and designating `audit-orchestrator` as the entrypoint.
  - `skills/audit-orchestrator/` — [ENTRYPOINT] Orchestrates per-page audits, applies cascading rules, merges findings, and emits the final JSON report.
  - `skills/crawl-render-audit/` — Evaluates visibility, crawlability, JS-render gaps, structured data, canonical tags, and /llms.txt.
  - `skills/freshness-corroboration/` — Evaluates stale date claims, numeric/listing mismatches, and inline corroboration markers.
  - `skills/engagement-audit/` — Evaluates visitor orientation, links, and engagement friction (gated by cascading rules).
  - `skills/entity-disambiguation/` — Resolves brand name collision risks, casing inconsistencies, and official profiles.
  - `reports/` — Live audit validation reports against unseen production websites and edge cases.
  - Offline unit & integration test suites (180 passing tests).
- `brand-ai-readiness-audit-submission.zip` — Sanitized submission zip archive (0.125 MB, under 50 MB limit, no model weights, no cache).

For complete technical documentation, architecture diagrams, and quick-start instructions, see [**brand-ai-readiness-audit/README.md**](./brand-ai-readiness-audit/README.md).
