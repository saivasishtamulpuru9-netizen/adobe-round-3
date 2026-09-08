"""
smoke_test_fs.py — Smoke tests for checks_fs.py (no network required).
Run from brand-ai-readiness-audit/ directory:
    python smoke_test_fs.py
"""
import sys, os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skills", "freshness-corroboration", "scripts"))
import checks_fs as fs

PASS = "[PASS]"
FAIL = "[FAIL]"
errors = []

def check(label, condition):
    if condition:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}")
        errors.append(label)

def make_page(url="https://example.com/", body="", head=None, html=None, has_raw=True):
    if head is None:
        head = {
            "title": "Test Page", "meta_description": "A description.",
            "article_published_time": "", "article_modified_time": "",
            "og_title": "", "og_description": "", "og_image": "",
            "twitter_title": "", "twitter_description": "", "twitter_image": "",
            "canonical": "", "robots_meta": "", "noindex": False, "meta_keywords": "",
        }
    if html is None:
        html = f"<html><body>{body}</body></html>"
    return {
        "url": url, "clean_url": url, "head": head,
        "raw_html": html, "body_text": body,
        "content_word_count": len(body.split()),
        "has_raw_html": has_raw,
        "blocked": False, "robots_disallowed": False, "noindex": False, "error": None,
        "ldjson_blocks": [], "internal_links": [],
    }

TODAY = date(2026, 9, 8)   # Fixed test date

print("\n=== emit_flag_only helper ===")
item = fs.emit_flag_only("FS-05", "reason text", "recommendation text")
check("returns dict with id, type, reason, recommendation",
      item["id"] == "FS-05" and item["type"] == "flag_only"
      and "reason" in item and "recommendation" in item)


print("\n=== FS-01: Stale date claims ===")

# Stale operational notice
body_stale_op = "Scheduled for 5 Jan 2025: system maintenance. Please plan accordingly."
p_op = make_page(body=body_stale_op, html=f"<html><body>{body_stale_op}</body></html>")
f01 = fs.check_fs01(p_op, current_date=TODAY)
check("stale operational notice (Jan 2025) -> High",
      any(f["severity"] == "high" for f in f01))

# Stale copyright year (> 2 years ago) — use raw HTML with &copy; entity
body_copy = "some content here"
html_copy = "<html><body>some content here<footer>&copy; 2020 Example Corp</footer></body></html>"
p_copy = make_page(body=body_copy, html=html_copy)
f01b = fs.check_fs01(p_copy, current_date=TODAY)
check("stale copyright (2020) -> at least one finding",
      len(f01b) > 0)

# Recent copyright (1 year lag) -> no finding
html_recent = "<html><body>content<footer>&copy; 2025 Example Corp</footer></body></html>"
p_recent = make_page(body="content", html=html_recent)
f01c = fs.check_fs01(p_recent, current_date=TODAY)
check("recent copyright (2025) -> no finding", len(f01c) == 0)

# Future date -> no finding
body_future = "Registration open until 15 December 2027."
p_future = make_page(body=body_future)
f01d = fs.check_fs01(p_future, current_date=TODAY)
check("future date -> no finding", len(f01d) == 0)


print("\n=== FS-02: Internal numeric inconsistency ===")

body_mismatch = ("We have 11+ years of experience serving clients globally. "
                 "Our team brings 14+ Years of Leadership in the industry.")
p_mismatch = make_page(body=body_mismatch)
f02 = fs.check_fs02(p_mismatch)
check("11+ vs 14+ years -> FS-02 finding", any(f["id"] == "FS-02" for f in f02))

body_consistent = "We have 11+ years of experience. Our 11 years make us leaders."
p_consistent = make_page(body=body_consistent)
f02b = fs.check_fs02(p_consistent)
check("consistent numbers -> no FS-02", not any(f["id"] == "FS-02" for f in f02b))


print("\n=== FS-03: No freshness signal ===")

# Content page, no freshness signal, raw HTML available
body_article = " ".join(["word"] * 200)
p_article = make_page(url="https://example.com/blog/post", body=body_article)
f03 = fs.check_fs03(p_article)
check("content page, no freshness signal -> Medium",
      f03 is not None and f03["severity"] == "medium")

# Content page WITH article:published_time -> no finding
p_article2 = make_page(url="https://example.com/blog/post", body=body_article)
p_article2["head"]["article_published_time"] = "2026-09-01T10:00:00Z"
check("article:published_time present -> no finding", fs.check_fs03(p_article2) is None)

# Content page with "Last updated" in body -> no finding
body_updated = "Last updated: September 2026. " + " ".join(["word"] * 100)
p_updated = make_page(url="https://example.com/blog/post", body=body_updated)
check("'Last updated' in body -> no finding", fs.check_fs03(p_updated) is None)

# Non-content page (e.g. /products) -> no finding
p_prod = make_page(url="https://example.com/products", body=body_article)
check("non-content page -> no finding", fs.check_fs03(p_prod) is None)

# Text-only fetch -> unscored not_detected_in_pass
p_textonly = make_page(url="https://example.com/blog/post", body=body_article, has_raw=False)
f03t = fs.check_fs03(p_textonly)
check("text-only -> unscored not_detected_in_pass",
      f03t is not None and f03t.get("severity") == "unscored"
      and f03t.get("confidence") == "not_detected_in_pass")


print("\n=== FS-04: Nav/footer listing mismatches ===")

# Nav has 3+ substantive items not in footer (threshold is >= 3)
html_mismatch = """<html><body>
<nav>
  <a href="/services">Services</a>
  <a href="/global-capability">Global Capability Center</a>
  <a href="/products">Products</a>
  <a href="/consulting">Consulting</a>
  <a href="/cloud-solutions">Cloud Solutions</a>
  <a href="/data-analytics">Data Analytics</a>
  <a href="/devops-practice">DevOps Practice</a>
</nav>
<footer>
  <a href="/services">Services</a>
  <a href="/products">Products</a>
  <a href="/consulting">Consulting</a>
  <a href="/privacy">Privacy</a>
  <a href="/terms">Terms</a>
</footer>
</body></html>"""
p_nav = make_page(html=html_mismatch, body="content")
f04 = fs.check_fs04(p_nav)
check("3+ nav items absent from footer -> FS-04 finding",
      any(f["id"] == "FS-04" for f in f04))

# Matching nav and footer -> no finding
html_match = """<html><body>
<nav><a href="/about">About</a><a href="/contact">Contact</a></nav>
<footer><a href="/about">About</a><a href="/contact">Contact</a></footer>
</body></html>"""
p_match = make_page(html=html_match, body="content")
f04b = fs.check_fs04(p_match)
check("matching nav/footer -> no FS-04 finding",
      not any(f["id"] == "FS-04" for f in f04b))


print("\n=== FS-05: External corroboration (flag_only / strength) ===")

# No attribution -> flag_only
body_no_attr = "We are the best company with great products and amazing services."
p_noattr = make_page(body=body_no_attr)
r05 = fs.check_fs05_flag_only(p_noattr)
check("no attribution -> flag_only", r05.get("type") == "flag_only")

# Explicit attribution -> strength
body_attr = "According to the Gartner report, our platform ranks in the top 5."
p_attr = make_page(body=body_attr)
r05b = fs.check_fs05_flag_only(p_attr)
check("explicit attribution -> strength", r05b.get("_strength") is True)


print("\n=== FS-06: Wiki-style citation markers ===")

# [citation needed] -> Medium finding
body_wiki = "Shivaji was born in 1630 [citation needed] and founded the Maratha Empire."
p_wiki = make_page(url="https://en.wikipedia.org/wiki/Shivaji",
                   body=body_wiki,
                   html=f"<html><body>{body_wiki}</body></html>")
f06 = fs.check_fs06(p_wiki)
check("[citation needed] -> Medium finding",
      any(f["severity"] == "medium" for f in f06))
check("[citation needed] -> FS-06 id", any(f["id"] == "FS-06" for f in f06))

# [dead link] -> Low finding
body_dead = "See the referenced paper for details. [dead link] The study showed results."
p_dead = make_page(body=body_dead, html=f"<html><body>{body_dead}</body></html>")
f06b = fs.check_fs06(p_dead)
check("[dead link] -> Low finding",
      any(f["severity"] == "low" and f["id"] == "FS-06" for f in f06b))

# No markers -> no findings
body_clean = "A well-sourced article with complete references and citations."
p_clean = make_page(body=body_clean)
f06c = fs.check_fs06(p_clean)
check("no markers -> no findings", len(f06c) == 0)


print("\n=== run_fs_checks integration ===")

# Wikipedia-style page with multiple issues
wiki_html = """<html>
<head><title>Test Article</title></head>
<body>
Shivaji was born in 1630 [citation needed] near Pune.
The battle of 1674 [dead link] is documented.
See the old announcement scheduled for 5 Jan 2025 for details.
We have 11+ years of experience. Our 14+ Years of Leadership speak for themselves.
<footer>&copy; 2020 Wikipedia</footer>
</body></html>"""
p_full = make_page(url="https://en.wikipedia.org/wiki/Test",
                   body="Shivaji was born in 1630 [citation needed] near Pune. The battle of 1674 [dead link] is documented. See the old announcement scheduled for 5 Jan 2025 for details. We have 11+ years of experience. Our 14+ Years of Leadership speak for themselves.",
                   html=wiki_html)
result = fs.run_fs_checks(p_full, current_date=TODAY)
ids = [f["id"] for f in result["findings"]]
check("integration: FS-06 fires (citation needed)", "FS-06" in ids)
check("integration: FS-01 fires (stale operational)", "FS-01" in ids)
check("integration: FS-02 fires (11 vs 14 years)", "FS-02" in ids)
check("integration: flag_only_items emitted", len(result["flag_only_items"]) > 0)
check("integration: FS-06 runs before FS-01 (check order)",
      ids.index("FS-06") < ids.index("FS-01") if ("FS-06" in ids and "FS-01" in ids) else True)

print("\n" + "="*50)
if errors:
    print(f"FAILED ({len(errors)} errors):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    total = sum(1 for line in open(__file__).readlines() if line.strip().startswith("check("))
    print(f"ALL {total} CHECKS PASSED")
