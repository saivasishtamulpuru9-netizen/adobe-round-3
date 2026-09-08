"""
smoke_test_ed.py — Smoke tests for checks_ed.py (no network required).
Run from brand-ai-readiness-audit/ directory:
    python smoke_test_ed.py
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skills", "entity-disambiguation", "scripts"))
import checks_ed as ed

PASS = "[PASS]"
FAIL = "[FAIL]"
errors = []

def check(label, condition):
    if condition:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}")
        errors.append(label)

def make_page(url="https://example.com/", body="", head=None, html=None,
              ldjson=None, has_raw=True, wc=None):
    if head is None:
        head = {
            "title": "Test Page | Example", "meta_description": "",
            "og_title": "Test Page | Example", "og_description": "",
            "og_image": "", "og_site_name": "",
            "twitter_title": "", "twitter_description": "", "twitter_image": "",
            "canonical": "", "robots_meta": "", "noindex": False, "meta_keywords": "",
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
        "blocked": False, "blocked_reason": None,
        "robots_disallowed": False, "noindex": False, "error": None,
        "ldjson_blocks": ldjson or [], "internal_links": [],
    }

def ids(result): return [f["id"] for f in result.get("findings", [])]
def strength_ids(result): return [s.get("id") for s in result.get("strengths", [])]
def flag_ids(result): return [f["id"] for f in result.get("flag_only_items", [])]


print("\n=== wikidata_backed skip-all gate ===")

p_wd = make_page(html='<html><body><a href="https://www.wikidata.org/wiki/Q42">Wikidata</a></body></html>')
result_wd = ed.run_ed_checks(p_wd, dv_flags={"wikidata_backed": True}, dv_findings=[])
check("wikidata_backed -> 0 findings", len(result_wd["findings"]) == 0)
check("wikidata_backed -> 0 flag_only", len(result_wd["flag_only_items"]) == 0)
check("wikidata_backed -> strength logged", len(result_wd["strengths"]) > 0)


print("\n=== ED-01: Name collision ===")

# High: known acronym
p_acronym = make_page(url="https://hr.example.com/", body="HR solutions for enterprise.")
p_acronym["head"]["title"] = "HR | Enterprise"
p_acronym["head"]["og_title"] = "HR | Enterprise"
ed01_h = ed.check_ed01(p_acronym)
check("'HR' acronym -> High", ed01_h is not None and ed01_h["severity"] == "high")

# Medium: generic word
p_nexus = make_page(body="Welcome to Nexus. We provide services.")
p_nexus["head"]["og_title"] = "Nexus | Home"
ed01_m = ed.check_ed01(p_nexus)
check("'Nexus' generic word -> Medium", ed01_m is not None and ed01_m["severity"] == "medium")

# Low: very short name, no schema
p_short = make_page(body="AQ systems are the best.")
p_short["head"]["og_title"] = "AQ"
ed01_l = ed.check_ed01(p_short)
check("'AQ' short name -> Low", ed01_l is not None and ed01_l["severity"] == "low")

# Unique name: no finding
p_unique = make_page(body="Quintessential Analytics Platform.")
p_unique["head"]["og_title"] = "Quintessential Analytics Platform"
ed01_n = ed.check_ed01(p_unique)
check("unique name -> no finding", ed01_n is None)

# _ed01_fired flag set when collision detected
p_c = make_page(); p_c["head"]["og_title"] = "HR | Services"
ed.check_ed01(p_c)
check("_ed01_fired flag set on collision", p_c.get("_ed01_fired") is True)


print("\n=== ED-02: Org schema missing sameAs/identifier ===")

# ED-01 fired + Org schema present but no sameAs
org_no_sameas = [json.dumps({
    "@context": "https://schema.org", "@type": "Organization",
    "name": "HR Corp", "url": "https://example.com"
})]
p_ed02 = make_page(ldjson=org_no_sameas)
p_ed02["_ed01_fired"] = True
p_ed02["_ed01_brand"] = "HR Corp"
ed02 = ed.check_ed02(p_ed02)
check("org schema no sameAs + ED-01 fired -> ED-02", ed02 is not None and ed02["id"] == "ED-02")

# ED-01 NOT fired -> no ED-02
p_nofired = make_page(ldjson=org_no_sameas)
ed02b = ed.check_ed02(p_nofired)
check("ED-01 not fired -> no ED-02", ed02b is None)

# Org schema WITH sameAs -> no ED-02
org_with_sameas = [json.dumps({
    "@context": "https://schema.org", "@type": "Organization",
    "name": "HR Corp", "sameAs": ["https://wikidata.org/wiki/Q12345"],
    "identifier": "CIN:L12345", "legalName": "HR Corp Pvt Ltd"
})]
p_complete = make_page(ldjson=org_with_sameas)
p_complete["_ed01_fired"] = True
ed02c = ed.check_ed02(p_complete)
check("complete org schema -> no ED-02", ed02c is None)

# No org schema at all -> no ED-02 (DV-03 covers this)
p_noschema = make_page()
p_noschema["_ed01_fired"] = True
ed02d = ed.check_ed02(p_noschema)
check("no schema at all -> no ED-02 (DV-03 owns gap)", ed02d is None)


print("\n=== ED-03: Brand name casing inconsistency ===")

# Inconsistent casing (> 15% minority)
body_incons = ("MyBrand solutions are great. My Brand has 200 clients. "
               "MyBrand is trusted by everyone. MyBrand helps you grow. "
               "My Brand is the best option. MyBrand wins awards.")
p_incons = make_page(body=body_incons)
p_incons["head"]["og_title"] = "MyBrand | Home"
ed03 = ed.check_ed03(p_incons)
check("casing inconsistency (>15%) -> ED-03", ed03 is not None and ed03["id"] == "ED-03")

# Consistent brand name -> no finding
body_cons = ("MyBrand solutions are great. MyBrand has 200 clients. "
             "MyBrand is trusted by everyone. MyBrand helps you grow.")
p_cons = make_page(body=body_cons)
p_cons["head"]["og_title"] = "MyBrand | Home"
ed03b = ed.check_ed03(p_cons)
check("consistent casing -> no ED-03", ed03b is None)


print("\n=== ED-04: Social profile links ===")

# No social links at all -> Medium finding
p_nosocial = make_page(body="We are a company with no social presence listed.")
ed04 = ed.check_ed04(p_nosocial)
check("no social links -> Medium finding",
      ed04 is not None and not ed04.get("_strength") and ed04["severity"] == "medium")

# Social links in DOM only (footer) -> Low finding
html_dom_social = """<html><body>
<main><p>Company content.</p></main>
<footer>
  <a href="https://www.linkedin.com/company/example">LinkedIn</a>
  <a href="https://twitter.com/example">Twitter</a>
</footer>
</body></html>"""
p_domsocial = make_page(html=html_dom_social, body="Company content.")
ed04b = ed.check_ed04(p_domsocial)
check("social in DOM only -> Low finding",
      ed04b is not None and not ed04b.get("_strength") and ed04b["severity"] == "low")

# Social links in sameAs -> strength
org_social = [json.dumps({
    "@context": "https://schema.org", "@type": "Organization",
    "name": "Example Corp",
    "sameAs": ["https://www.linkedin.com/company/example",
               "https://twitter.com/example"]
})]
p_schema_social = make_page(ldjson=org_social)
ed04c = ed.check_ed04(p_schema_social)
check("social in sameAs -> strength",
      ed04c is not None and ed04c.get("_strength") is True)


print("\n=== ED-05: Wikipedia/Wikidata linkage ===")

# No Wikipedia link -> flag_only
p_nowiki = make_page(body="A company with no Wikipedia link.")
ed05 = ed.check_ed05(p_nowiki, wikidata_backed=False)
check("no wiki link -> flag_only",
      isinstance(ed05, dict) and ed05.get("type") == "flag_only")

# Wikipedia in DOM but NOT in sameAs -> Medium finding
html_wiki_dom = """<html><body>
<p>See our <a href="https://en.wikipedia.org/wiki/ExampleCorp">Wikipedia page</a>.</p>
</body></html>"""
p_wikidom = make_page(html=html_wiki_dom, body="See our Wikipedia page.")
ed05b = ed.check_ed05(p_wikidom, wikidata_backed=False)
check("wiki in DOM not in sameAs -> Medium finding",
      isinstance(ed05b, dict) and ed05b.get("severity") == "medium")

# wikidata_backed=True -> strength
ed05c = ed.check_ed05(make_page(), wikidata_backed=True)
check("wikidata_backed -> ED-05 strength", ed05c.get("_strength") is True)

# Wikipedia in DOM AND in sameAs -> strength
org_wiki = [json.dumps({
    "@context": "https://schema.org", "@type": "Organization",
    "name": "Example Corp",
    "sameAs": ["https://en.wikipedia.org/wiki/ExampleCorp"]
})]
p_wiki_schema = make_page(html=html_wiki_dom, body="See our Wikipedia page.", ldjson=org_wiki)
ed05d = ed.check_ed05(p_wiki_schema, wikidata_backed=False)
check("wiki in DOM AND in sameAs -> strength", ed05d.get("_strength") is True)


print("\n=== ED-06: Founding facts flag_only ===")

# ED-01 fired + founding claim -> flag_only
body_founded = "HR Corp was founded in 2005 and headquartered in Mumbai."
p_founded = make_page(body=body_founded)
p_founded["_ed01_fired"] = True
p_founded["_ed01_brand"] = "HR"
ed06 = ed.check_ed06_flag_only(p_founded)
check("ED-01 fired + founding claim -> ED-06 flag_only",
      ed06 is not None and ed06.get("type") == "flag_only")

# ED-01 NOT fired -> no ED-06
body_founded2 = "We were founded in 2005 and headquartered in Mumbai."
p_founded2 = make_page(body=body_founded2)
ed06b = ed.check_ed06_flag_only(p_founded2)
check("ED-01 not fired -> no ED-06", ed06b is None)

# No founding claims -> no ED-06 even if ED-01 fired
p_nofounding = make_page(body="We build great software for everyone.")
p_nofounding["_ed01_fired"] = True
ed06c = ed.check_ed06_flag_only(p_nofounding)
check("no founding claims -> no ED-06", ed06c is None)


print("\n=== run_ed_checks integration ===")

# Full page with collision risk + missing schema + no social links
body_full = ("HR solutions for enterprise. HR Corp was founded in 2010. "
             "MyBrand is the best. My Brand also helps SMEs. "
             "We have 500+ clients across 20 countries.")
org_incomplete = [json.dumps({
    "@context": "https://schema.org", "@type": "Organization",
    "name": "HR", "url": "https://example.com"
})]
html_full = f"""<html>
<head><title>HR Corp | Enterprise</title></head>
<body>{body_full}</body>
</html>"""
p_full = make_page(url="https://example.com/", body=body_full,
                   html=html_full, ldjson=org_incomplete)
p_full["head"]["og_title"] = "HR Corp | Enterprise"

result_full = ed.run_ed_checks(p_full, dv_flags={"wikidata_backed": False}, dv_findings=[])
all_ids = ids(result_full)
check("integration: ED-01 fires (HR acronym)", "ED-01" in all_ids)
check("integration: ED-02 fires (schema no sameAs)", "ED-02" in all_ids)
check("integration: ED-04 fires (no social links)", "ED-04" in all_ids)
check("integration: ED-05 flag_only (no wiki link)", "ED-05" in flag_ids(result_full))
check("integration: ED-06 flag_only (HR + founded claim)", "ED-06" in flag_ids(result_full))

# Wikidata-backed: all ED checks skipped
result_wd2 = ed.run_ed_checks(p_full, dv_flags={"wikidata_backed": True}, dv_findings=[])
check("wikidata_backed integration: 0 findings", len(result_wd2["findings"]) == 0)
check("wikidata_backed integration: 0 flag_only", len(result_wd2["flag_only_items"]) == 0)


print("\n" + "="*50)
if errors:
    print(f"FAILED ({len(errors)} errors):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    total = sum(1 for line in open(__file__).readlines() if line.strip().startswith("check("))
    print(f"ALL {total} CHECKS PASSED")
