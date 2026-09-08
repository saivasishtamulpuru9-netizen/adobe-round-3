"""
smoke_test_dv.py — Quick smoke tests for checks_dv.py (no network required).
Run from brand-ai-readiness-audit/ directory:
    python smoke_test_dv.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skills", "crawl-render-audit", "scripts"))
import checks_dv as dv

PASS = "[PASS]"
FAIL = "[FAIL]"
errors = []

def check(label, condition):
    if condition:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}")
        errors.append(label)

def make_page(url="https://example.com/", wc=200, body=None, head=None, ldjson=None,
              html=None, has_raw=True, blocked=False, reason=None, robots=False,
              noindex=False, error=None):
    if body is None:
        body = " ".join(["word"] * wc)
    if head is None:
        head = {
            "title": "Test Page", "meta_description": "Desc.", "meta_keywords": "",
            "og_title": "OG Title", "og_description": "OG Desc",
            "og_image": "https://example.com/img.png",
            "twitter_title": "TW Title", "twitter_description": "TW Desc",
            "twitter_image": "", "canonical": "", "robots_meta": "",
            "noindex": noindex, "article_published_time": "", "article_modified_time": "",
        }
    if html is None:
        html = f"<html><head><title>Test</title></head><body>{body}</body></html>"
    return {
        "url": url, "clean_url": url, "http_status": 200,
        "blocked": blocked, "blocked_reason": reason,
        "robots_disallowed": robots, "noindex": noindex,
        "head": head, "raw_html": html, "body_text": body,
        "content_word_count": wc, "has_raw_html": has_raw,
        "ldjson_blocks": ldjson or [], "internal_links": [], "error": error,
    }

print("\n=== DV-01 ===")
p_crit = make_page(url="https://example.com/", wc=5, body="Loading...",
                   head={"title":"MySite","meta_description":"","og_title":"",
                         "og_description":"","og_image":"","twitter_title":"",
                         "twitter_description":"","twitter_image":"","canonical":"",
                         "robots_meta":"","noindex":False,"meta_keywords":"",
                         "article_published_time":"","article_modified_time":""})
f01 = dv.check_dv01(p_crit)
check("populated head + empty body → Critical", f01 and f01["severity"] == "critical")

p_js = make_page(wc=8, body="Please enable JavaScript to view this site.")
f01b = dv.check_dv01(p_js)
check("enable JS message → Critical", f01b and f01b["severity"] == "critical")

p_thin = make_page(url="https://example.com/about", wc=25)
f01c = dv.check_dv01(p_thin)
check("25 words on /about → High", f01c and f01c["severity"] == "high")

p_ok = make_page(wc=200)
check("200 words → no finding", dv.check_dv01(p_ok) is None)

p_tx = make_page(url="https://example.com/search?q=test", wc=10)
check("transactional URL skipped", dv.check_dv01(p_tx) is None)

print("\n=== DV-02 ===")
p_full = make_page()
check("all fields present → no finding", dv.check_dv02(p_full) is None)

p_nodesc = make_page(); p_nodesc["head"]["meta_description"] = ""
f02 = dv.check_dv02(p_nodesc)
check("missing description → High", f02 and f02["severity"] == "high")

p_noimg = make_page(); p_noimg["head"]["og_image"] = ""
f02b = dv.check_dv02(p_noimg)
check("missing og:image only → Medium", f02b and f02b["severity"] == "medium")

print("\n=== DV-03 ===")
p_nold = make_page(ldjson=[])
f03 = dv.check_dv03(p_nold)
check("no JSON-LD → finding", f03 is not None)

p_ld = make_page(ldjson=['{"@context":"https://schema.org","@type":"Organization","name":"Test"}'])
check("valid JSON-LD → no finding", dv.check_dv03(p_ld) is None)

p_wiki = make_page(html='<html><body><a href="https://www.wikidata.org/wiki/Q42">Wikidata</a></body></html>', ldjson=[])
check("Wikidata link → skip DV-03", dv.check_dv03(p_wiki) is None)

p_textonly = make_page(ldjson=[], has_raw=False)
f03t = dv.check_dv03(p_textonly)
check("text-only → unscored not_detected_in_pass", f03t and f03t.get("severity") == "unscored")

print("\n=== DV-04 ===")
p_thin2 = make_page(wc=80, body=" ".join(["word"]*80))
f04 = dv.check_dv04(p_thin2)
check("80 words → High thin content", f04 and f04["severity"] == "high")

p_fired = make_page(wc=30); p_fired["_dv01_fired"] = True
check("dv01_fired → DV-04 skipped", dv.check_dv04(p_fired) is None)

print("\n=== DV-08 ===")
p_track = make_page(url="https://example.com/?srsltid=abc123")
p_track["clean_url"] = "https://example.com/"
f08 = dv.check_dv08(p_track)
check("tracking param + no canonical → Low", f08 and f08["severity"] == "low")

p_canon = make_page(url="https://example.com/?utm_source=google")
p_canon["clean_url"] = "https://example.com/"
p_canon["head"]["canonical"] = "https://example.com/"
check("canonical present → no finding", dv.check_dv08(p_canon) is None)

print("\n=== DV-09 ===")
p_kw = make_page()
p_kw["head"]["meta_keywords"] = ",".join([f"kw{i}" for i in range(20)])
findings09 = dv.check_dv09(p_kw)
check("20 keywords → DV-09b", any(f["id"]=="DV-09b" for f in findings09))

print("\n=== DV-12 multipage ===")
def mp(url, title, desc):
    return {"url":url,"head":{"title":title,"meta_description":desc},"noindex":False,"blocked":False}
dup = dv.check_dv12_multipage([mp("https://a.com/p1","Same Title","Same Desc"),
                                mp("https://a.com/p2","Same Title","Same Desc")])
check("same title on 2 pages → DV-12", any(f["id"]=="DV-12" for f in dup))

uniq = dv.check_dv12_multipage([mp("https://a.com/p1","About Us","Who we are"),
                                 mp("https://a.com/p2","Contact","Get in touch")])
check("unique titles → no finding", len(uniq) == 0)

print("\n=== DV-18 ===")
s1 = dv.check_dv18(True, "example.com")
check("/llms.txt present → strength", s1.get("_strength") is True)
s2 = dv.check_dv18(False, "example.com")
check("/llms.txt absent → Low proactive", s2["severity"]=="low" and s2.get("proactive"))

print("\n=== Cascading rules (run_dv_checks) ===")
# DV-13: bot-block
p13 = make_page(blocked=True, reason="BOT_BLOCK"); p13["raw_html"]=None; p13["has_raw_html"]=False
r13 = dv.run_dv_checks(p13)
check("DV-13 → status=blocked, flag set", r13["status"]=="blocked" and r13["flags"]["dv13_fired"])
check("DV-13 → DV-13 + DV-17 in findings", "DV-13" in [f["id"] for f in r13["findings"]] and "DV-17" in [f["id"] for f in r13["findings"]])
check("DV-13 → no DV-01/DV-03 fired", "DV-01" not in [f["id"] for f in r13["findings"]])

# DV-16: robots
p16 = make_page(robots=True); p16["blocked"]=True; p16["blocked_reason"]="ROBOTS_DISALLOWED"
r16 = dv.run_dv_checks(p16)
check("DV-16 → status=robots_disallowed", r16["status"]=="robots_disallowed")
check("DV-16 + DV-17 in findings", "DV-16" in [f["id"] for f in r16["findings"]])

# noindex
p_ni = make_page(noindex=True)
r_ni = dv.run_dv_checks(p_ni)
check("noindex → intentionally_excluded, no findings", r_ni["status"]=="intentionally_excluded" and len(r_ni["findings"])==0)

# DV-01 critical suppresses DV-04
r_crit = dv.run_dv_checks(p_crit)
check("DV-01 critical sets flag", r_crit["flags"]["dv01_critical"])
check("DV-01 critical → DV-04 absent", "DV-04" not in [f["id"] for f in r_crit["findings"]])

# Wikidata skips DV-03
p_wd = make_page(wc=200, html='<html><body><a href="https://www.wikidata.org/wiki/Q42">Wikidata</a> '+" ".join(["word"]*200)+"</body></html>", ldjson=[])
r_wd = dv.run_dv_checks(p_wd)
check("wikidata_backed → DV-03 absent", "DV-03" not in [f["id"] for f in r_wd["findings"]])
check("wikidata_backed flag set", r_wd["flags"]["wikidata_backed"])

print("\n" + "="*50)
if errors:
    print(f"FAILED ({len(errors)} errors):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print(f"ALL {sum(1 for l in open(__file__).readlines() if 'check(' in l)} CHECKS PASSED")
