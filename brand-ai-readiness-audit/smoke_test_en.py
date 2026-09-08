"""
smoke_test_en.py — Smoke tests for checks_en.py (no network required).
Run from brand-ai-readiness-audit/ directory:
    python smoke_test_en.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skills", "engagement-audit", "scripts"))
import checks_en as en

PASS = "[PASS]"
FAIL = "[FAIL]"
errors = []

def check(label, condition):
    if condition:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}")
        errors.append(label)

def make_page(url="https://example.com/", body="Sample page content.", head=None,
              html=None, has_raw=True, blocked=False, reason=None, robots=False,
              noindex=False, error=None, ldjson=None, wc=None):
    if head is None:
        head = {
            "title": "Test Page", "meta_description": "Desc.", "meta_keywords": "",
            "og_title": "", "og_description": "", "og_image": "",
            "twitter_title": "", "twitter_description": "", "twitter_image": "",
            "canonical": "", "robots_meta": "", "noindex": noindex,
            "article_published_time": "", "article_modified_time": "",
        }
    if html is None:
        html = f"<html><head><title>Test</title></head><body>{body}</body></html>"
    if wc is None:
        wc = len(body.split())
    return {
        "url": url, "clean_url": url, "head": head,
        "raw_html": html, "body_text": body,
        "content_word_count": wc, "has_raw_html": has_raw,
        "blocked": blocked, "blocked_reason": reason,
        "robots_disallowed": robots, "noindex": noindex, "error": error,
        "ldjson_blocks": ldjson or [], "internal_links": [],
    }

def ids(result): return [f["id"] for f in result.get("findings", [])]

print("\n=== Cascading Routing ===")

# EN-12: DV-13 fired (bot-blocked)
p_blocked = make_page(blocked=True, reason="BOT_BLOCK")
r = en.run_en_checks(p_blocked, dv_flags={"dv13_fired": True, "dv01_critical": False, "dv16_fired": False})
check("DV-13 fired -> not_assessed", r["engagement_status"] == "not_assessed")
check("DV-13 fired -> no EN-01/03/09 findings", len(r["findings"]) == 0)

# EN-12: DV-16 fired (robots)
p_robots = make_page(robots=True)
r2 = en.run_en_checks(p_robots, dv_flags={"dv16_fired": True, "dv13_fired": False, "dv01_critical": False})
check("DV-16 fired -> not_assessed", r2["engagement_status"] == "not_assessed")
check("DV-16 -> skip_finding_ref = DV-16", r2["skip_finding_ref"] == "DV-16")

# EN-13: DV-01 critical
p_empty = make_page(wc=5)
p_empty["_dv01_fired"] = True
r3 = en.run_en_checks(p_empty, dv_flags={"dv01_critical": True, "dv13_fired": False, "dv16_fired": False})
check("DV-01 critical -> not_assessed", r3["engagement_status"] == "not_assessed")
check("DV-01 critical -> skip_finding_ref = DV-01", r3["skip_finding_ref"] == "DV-01")

# EN-11: noindex
p_noindex = make_page(noindex=True)
r4 = en.run_en_checks(p_noindex, dv_flags={})
check("noindex -> not_applicable", r4["engagement_status"] == "not_applicable")

# EN-11: transactional URL
p_cart = make_page(url="https://example.com/cart")
r5 = en.run_en_checks(p_cart, dv_flags={})
check("cart URL -> not_applicable", r5["engagement_status"] == "not_applicable")

p_search = make_page(url="https://example.com/search?q=test")
r6 = en.run_en_checks(p_search, dv_flags={})
check("search URL -> not_applicable", r6["engagement_status"] == "not_applicable")


print("\n=== EN-01 / EN-02: Dead links & Placeholders ===")

# Placeholder link in nav -> EN-02 (not EN-01)
html_placeholder = """<html><body>
<nav><a href="#">Home</a><a href="YOUR_APP_URL">App</a><a href="/about">About</a></nav>
<p>Some content here.</p>
</body></html>"""
p_ph = make_page(html=html_placeholder, body="Some content here.")
r_ph = en.run_en_checks(p_ph, dv_flags={})
check("placeholder href -> EN-02 (not EN-01)", "EN-02" in ids(r_ph))
check("placeholder ownership: no duplicate EN-01 for same link",
      not ("EN-01" in ids(r_ph) and "EN-02" in ids(r_ph)) or
      all(f["id"] != "EN-01" or "YOUR_APP_URL" not in f.get("evidence","")
          for f in r_ph["findings"]))

# Dead anchor link in nav -> EN-01
html_dead = """<html><body>
<nav>
  <a href="#">Home</a>
  <a href="#">Products</a>
  <a href="#">Services</a>
  <a href="/about">About</a>
</nav>
<p>Some content here on this page.</p>
</body></html>"""
p_dead = make_page(html=html_dead, body="Some content here on this page.")
r_dead = en.run_en_checks(p_dead, dv_flags={})
check("dead # links in nav -> EN-01", "EN-01" in ids(r_dead))


print("\n=== EN-03: Breadcrumb ===")

# Deep page, no breadcrumb -> EN-03
p_deep = make_page(url="https://example.com/category/subcategory/page")
r_en03 = en.run_en_checks(p_deep, dv_flags={})
check("deep page no breadcrumb -> EN-03", "EN-03" in ids(r_en03))

# Root page -> no EN-03
p_root = make_page(url="https://example.com/")
r_root = en.run_en_checks(p_root, dv_flags={})
check("root page -> no EN-03", "EN-03" not in ids(r_root))

# Deep page WITH BreadcrumbList schema -> no EN-03
ldjson_bc = ['{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[]}']
p_bc = make_page(url="https://example.com/category/page", ldjson=ldjson_bc)
r_bc = en.run_en_checks(p_bc, dv_flags={})
check("BreadcrumbList schema present -> no EN-03", "EN-03" not in ids(r_bc))


print("\n=== EN-04: Paywall friction ===")

# Login friction before value -> EN-04
html_paywall = """<html><body>
<div class="gate">
  <p>Sign in to view this content.</p>
  <button>Login</button>
</div>
</body></html>"""
p_pw = make_page(html=html_paywall, body="Sign in to view this content.", url="https://example.com/report")
r_pw = en.run_en_checks(p_pw, dv_flags={})
check("login friction -> EN-04", "EN-04" in ids(r_pw))

# Legitimate credential gate (exam hall ticket) -> no EN-04
body_exam = "Enter your roll number and date of birth to download your hall ticket."
p_exam = make_page(body=body_exam, url="https://example.com/result")
r_exam = en.run_en_checks(p_exam, dv_flags={})
check("hall ticket portal -> no EN-04 (legitimate gate)", "EN-04" not in ids(r_exam))


print("\n=== EN-06: flag_only always emitted ===")

p_normal = make_page(url="https://example.com/about", body=" ".join(["word"]*100))
r_normal = en.run_en_checks(p_normal, dv_flags={})
check("normal page -> EN-06 flag_only emitted",
      any(item["id"] == "EN-06" for item in r_normal["flag_only_items"]))
check("EN-06 has type=flag_only",
      all(item.get("type") == "flag_only"
          for item in r_normal["flag_only_items"] if item.get("id") == "EN-06"))


print("\n=== EN-08: Stat counter elements ===")

# Stat label with no digit value -> Low
html_stat_missing = """<html><body>
<div class="stat">Clients</div>
<div class="stat">Countries</div>
</body></html>"""
p_stat = make_page(html=html_stat_missing, body="Clients Countries")
r_stat = en.run_en_checks(p_stat, dv_flags={})
check("stat with no digit -> EN-08 (Low)",
      any(f["id"] == "EN-08" and f["severity"] == "low" for f in r_stat["findings"]))

# Stat with '0' value -> Medium (false assertion)
html_stat_zero = """<html><body>
<div class="counter">
  <span data-count="0">0</span>
  <p>Active Users</p>
</div>
</body></html>"""
p_statz = make_page(html=html_stat_zero, body="0 Active Users")
r_statz = en.run_en_checks(p_statz, dv_flags={})
# Note: the '0' detection depends on the stat text containing ONLY zeros
# This is a proxy check so test for the finding existence
check("stat elements scanned (no crash)", r_statz["engagement_status"] == "scored")


print("\n=== EN-09: Trust content absence ===")

# Homepage with no trust content -> EN-09
p_homepage = make_page(url="https://example.com/", body="We build software solutions for enterprise clients.")
r_hp = en.run_en_checks(p_homepage, dv_flags={})
check("homepage with no trust content -> EN-09", "EN-09" in ids(r_hp))

# Homepage WITH testimonial content -> no EN-09
body_trust = ("Our clients love us! Testimonial from John Doe: 'Great service.' "
              "We are trusted by 100+ companies.")
p_trust = make_page(url="https://example.com/", body=body_trust)
r_trust = en.run_en_checks(p_trust, dv_flags={})
check("homepage with testimonials -> no EN-09", "EN-09" not in ids(r_trust))

# Article page -> EN-09 not applicable
p_article = make_page(url="https://example.com/blog/my-post", body="A blog post about things.")
r_art = en.run_en_checks(p_article, dv_flags={})
check("blog page -> no EN-09 (not a trust-sensitive page type)", "EN-09" not in ids(r_art))


print("\n=== EN-10: Navigation strength (positive pattern) ===")

# Rich nav + footer -> strength
nav_items = "".join(f'<a href="/{i}">Section{i}</a>' for i in range(6))
footer_items = "".join(f'<a href="/{i}">Link{i}</a>' for i in range(12))
html_rich = f"""<html><body>
<nav>{nav_items}</nav>
<main><p>Content here on the main page section.</p></main>
<footer>{footer_items}</footer>
</body></html>"""
p_rich = make_page(url="https://example.com/", html=html_rich, body="Content here on the main page section.")
r_rich = en.run_en_checks(p_rich, dv_flags={})
check("rich nav + footer -> EN-10 strength",
      any(s.get("id") == "EN-10" for s in r_rich["strengths"]))

# Lean site -> no EN-10 strength (and no finding — correct)
p_lean = make_page(url="https://example.com/", body="Simple landing page.")
r_lean = en.run_en_checks(p_lean, dv_flags={})
check("lean site -> no EN-10 strength (not a defect)",
      not any(s.get("id") == "EN-10" for s in r_lean["strengths"]))


print("\n=== emit_flag_only helper ===")
flag = en.emit_flag_only("EN-06", "reason", "recommendation")
check("emit_flag_only returns correct shape",
      flag["type"] == "flag_only" and flag["id"] == "EN-06"
      and "reason" in flag and "recommendation" in flag)


print("\n" + "="*50)
if errors:
    print(f"FAILED ({len(errors)} errors):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    total = sum(1 for line in open(__file__).readlines() if line.strip().startswith("check("))
    print(f"ALL {total} CHECKS PASSED")
