# Adobe University Hackathon 2026 — Round 3: Build the Agent Skill Marketplace

[![Adobe Hackathon](https://img.shields.io/badge/Adobe%20University%20Hackathon-2026%20Round%203-FF0000?style=for-the-badge&logo=adobe)](https://github.com/adityagudipati05/adobe-round-3)
[![Agent Skills Spec](https://img.shields.io/badge/Spec-AgentSkills.io-blue?style=for-the-badge)](https://agentskills.io)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen?style=for-the-badge&logo=python)](https://python.org)
[![Tests Passed](https://img.shields.io/badge/Tests-184%2F184%20Passing-success?style=for-the-badge)](https://github.com/adityagudipati05/adobe-round-3)

This repository contains the official submission for **Adobe University Hackathon 2026 — Round 3: Build the Agent Skill Marketplace**. The project implements a composable, multi-skill Agent Skill Marketplace compliant with the official `agentskills.io` specification. Pointed at any website URL, the marketplace entrypoint (`audit-orchestrator`) automatically audits the site for both **off-site AI discoverability** problems (why a brand is missing, ignored, or misquoted by AI assistants like ChatGPT, Claude, or Perplexity) and **on-site visitor engagement** friction (why human visitors who arrive fail to stay or convert), emitting a single, structured JSON report containing evidence-backed findings, site-level strengths, flag-only items, and prioritized suggested actions.

For complete technical documentation, detailed check-ID reference, architecture diagrams, schema specifications, and rubric self-check, see [**`brand-ai-readiness-audit/README.md`**](./brand-ai-readiness-audit/README.md).

---

## 📂 Repository Structure

The actual file and directory layout of this repository:

```
adobe-round-3/
├── README.md                                      # Repository root documentation (this file)
├── build_submission.py                            # Automated test runner & submission packaging script
├── build_submission.sh                            # Cross-platform shell wrapper for submission build
└── brand-ai-readiness-audit/                      # Marketplace root directory (what is zipped)
    ├── README.md                                  # Complete technical marketplace documentation
    ├── marketplace.json                           # Marketplace manifest (lists 5 skills, entrypoint)
    ├── run_phase7_special_cases.py                # Verification script for edge case scenarios
    ├── smoke_test_dv.py                           # Discoverability test suite (33 check assertions)
    ├── smoke_test_fs.py                           # Freshness test suite (25 check assertions)
    ├── smoke_test_en.py                           # Engagement test suite (27 check assertions)
    ├── smoke_test_ed.py                           # Entity disambiguation test suite (31 check assertions)
    ├── smoke_test_orchestrator.py                 # Orchestration integration test suite (27 check assertions)
    ├── test_dv_checks_stdlib.py                   # Pure stdlib unit test suite (41 test functions)
    ├── reports/                                   # Real-world & synthetic validation audit reports
    │   ├── bot_block_dv13_en12.json
    │   ├── hackernews.json
    │   ├── kisansuvidha.json
    │   ├── noindex_en11.json
    │   ├── python_org.json
    │   ├── synthetic_bot_block_dv13.json
    │   └── wikipedia_tim.json
    └── skills/                                    # Modular Agent Skills (agentskills.io compliant)
        ├── audit-orchestrator/                    # [ENTRYPOINT: true] Orchestrates sub-skills & emits report
        │   ├── SKILL.md
        │   ├── references/
        │   │   ├── cascading_rules.md
        │   │   └── report_schema.json
        │   └── scripts/
        │       └── compose_report.py              # Entrypoint CLI & orchestration script
        ├── crawl-render-audit/                    # Skill: Discoverability & JS render (DV-01..DV-20)
        │   ├── SKILL.md
        │   ├── references/
        │   │   └── dv_checklist.md
        │   └── scripts/
        │       ├── checks_dv.py
        │       └── fetch_page.py
        ├── freshness-corroboration/               # Skill: Freshness & date claims (FS-01..FS-06)
        │   ├── SKILL.md
        │   ├── references/
        │   │   └── fs_checklist.md
        │   └── scripts/
        │       └── checks_fs.py
        ├── engagement-audit/                      # Skill: Visitor friction & retention (EN-01..EN-13)
        │   ├── SKILL.md
        │   ├── references/
        │   │   └── en_checklist.md
        │   └── scripts/
        │       └── checks_en.py
        └── entity-disambiguation/                 # Skill: Brand identity & Wikidata (ED-01..ED-06)
            ├── SKILL.md
            ├── references/
            │   └── ed_checklist.md
            └── scripts/
                └── checks_ed.py
```

---

## 🚀 Quick Start

### Prerequisites & Dependencies
The project requires **Python 3.10+** and the following third-party packages (derived directly from imports in `skills/*/scripts/*.py`):
- `requests` — HTTP fetching with User-Agent configuration
- `beautifulsoup4` — HTML DOM parsing and navigation
- `lxml` — Fast HTML parsing backend (falls back to `html.parser` if absent)

Install dependencies:
```bash
pip install requests beautifulsoup4 lxml
```

### Running an Audit via CLI
All audits are executed through the entrypoint script `skills/audit-orchestrator/scripts/compose_report.py`. 

```bash
# Basic single-page audit (printed to stdout)
python brand-ai-readiness-audit/skills/audit-orchestrator/scripts/compose_report.py https://example.com

# Audit up to 10 pages, set custom HTTP timeout (20s), and save report to file
python brand-ai-readiness-audit/skills/audit-orchestrator/scripts/compose_report.py https://example.com \
  --max-pages 10 --timeout 20 --out audit_report.json

# Verbose audit (includes raw per-page skill outputs in JSON report)
python brand-ai-readiness-audit/skills/audit-orchestrator/scripts/compose_report.py https://example.com \
  --verbose --out report_verbose.json
```

### CLI Flag Reference
The CLI flags supported by `compose_report.py` (verified against `argparse` definition):
- `url` *(positional, required)*: Target website URL (e.g. `https://example.com`).
- `--max-pages INT` *(optional, default: 5)*: Maximum number of internal pages to crawl and audit.
- `--timeout INT` *(optional, default: 30)*: Per-page HTTP fetch timeout in seconds.
- `--verbose` *(optional flag)*: Includes raw per-page skill outputs (`raw_per_page`) in the emitted report.
- `--out FILE` *(optional)*: Writes JSON report to specified file path instead of stdout.

---

## 📦 Building the Submission Archive

To generate the official `brand-ai-readiness-audit-submission.zip` archive prior to submission, run the automated build script from the repository root:

```bash
# Cross-platform execution (Linux / macOS / Windows):
python build_submission.py

# Or via shell wrapper on Unix/macOS:
./build_submission.sh
```

**Automated Build Pipeline:**
1. **Pre-flight Testing**: Runs all 6 test drivers (184 unit test assertions across discoverability, freshness, engagement, entity disambiguation, and orchestration). If any test suite fails, packaging is immediately aborted.
2. **Clean Packaging**: Packages `brand-ai-readiness-audit/` into `brand-ai-readiness-audit-submission.zip` at the repository root, excluding temporary files, bytecode, caches (`__pycache__`, `.pytest_cache`, `.git`, `.DS_Store`, `*.pyc`), and binary archives.
3. **Checksum & Metrics**: Outputs a PASS/FAIL summary, archive size, and SHA-256 checksum for verification.

---


## 🛡️ Scope & Guardrails Compliance

This submission strictly complies with Section 5 ("Scope & guardrails") of the competition handout:

| Handout Guardrail | Status | Implementation Details in Codebase |
|---|---|---|
| **Recommend-only** | ✅ Satisfied | The marketplace only audits and emits recommendations. No skill contains logic to edit, modify, or post changes to any live site. |
| **Read-only Sandbox** | ✅ Satisfied | All network operations in `fetch_page.py` use read-only HTTP `GET` requests (or `HEAD` requests for link verification). No POST, PUT, DELETE, or authenticated requests are performed. |
| **Respects `robots.txt`** | ✅ Satisfied | `fetch_page.py` fetches and parses `https://{domain}/robots.txt` before crawling (`check_robots()`). If disallowed, `DV-16` is emitted and crawl stops. |
| **No Pre-trained Weights** | ✅ Satisfied | Zero pre-trained neural network weights or binary model files are included. Reasoning logic is encoded into deterministic Python heuristics and portable `SKILL.md` instructions. |
| **Submission Size ≤ 50 MB** | ✅ Satisfied | The sanitized submission archive `brand-ai-readiness-audit-submission.zip` is **0.130 MB** (well under the 50 MB limit). |
| **Runtime < 5 Minutes** | ✅ Satisfied | A typical 5-page crawl and audit completes in **< 10 seconds** (bounded by `--max-pages` and per-page `--timeout`). |

---

## 📄 Documentation Link

For the full technical manual, detailed check listings (`DV-01..20`, `FS-01..06`, `EN-01..13`, `ED-01..06`), complete report schema documentation, cascading routing rules, report file audit notes, and test suite details, please refer to:

👉 [**`brand-ai-readiness-audit/README.md`**](./brand-ai-readiness-audit/README.md)
