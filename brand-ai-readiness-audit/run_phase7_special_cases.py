import http.server
import threading
import json
import os
import sys

_SKILLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
for s in ["crawl-render-audit", "freshness-corroboration", "engagement-audit", "entity-disambiguation", "audit-orchestrator"]:
    p = os.path.join(_SKILLS, s, "scripts")
    if p not in sys.path:
        sys.path.insert(0, p)

import compose_report as orch

class SpecialCaseHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/robots.txt":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"User-agent: *\nAllow: /\n")
        elif self.path == "/bot-block":
            # DV-13 trigger: 403 Forbidden with bot-challenge signature
            self.send_response(403)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><head><title>Access Denied</title></head><body><h1>403 Forbidden</h1><p>Checking your browser... Cloudflare Ray ID: 89ab12cd</p></body></html>")
        elif self.path == "/noindex":
            # noindex trigger: normal page with robots meta noindex
            html = (
                "<!DOCTYPE html>\n"
                "<html>\n"
                "<head>\n"
                "    <title>Internal Search Results</title>\n"
                '    <meta name="robots" content="noindex, nofollow">\n'
                "</head>\n"
                "<body>\n"
                "    <h1>Search</h1>\n"
                "    <p>This is an internal search results page that should not be indexed.</p>\n"
                "</body>\n"
                "</html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def main():
    os.makedirs("reports", exist_ok=True)
    server = http.server.HTTPServer(("127.0.0.1", 8899), SpecialCaseHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    print("\n=== Running Special Case 1: Bot-Block (DV-13 / EN-12) ===")
    rep_block = orch.run_audit("http://127.0.0.1:8899/bot-block", max_pages=1)
    with open("reports/bot_block_dv13_en12.json", "w", encoding="utf-8") as f:
        json.dump(rep_block, f, indent=2)
    print("Bot block audit written to reports/bot_block_dv13_en12.json")
    print("DV-13 fired:", any(f["id"] == "DV-13" for f in rep_block["findings"]))
    print("Findings:", [f["id"] for f in rep_block["findings"]])

    print("\n=== Running Special Case 2: Noindex page (skips DV-01..04 / EN-11) ===")
    rep_noindex = orch.run_audit("http://127.0.0.1:8899/noindex", max_pages=1)
    with open("reports/noindex_en11.json", "w", encoding="utf-8") as f:
        json.dump(rep_noindex, f, indent=2)
    print("Noindex audit written to reports/noindex_en11.json")
    print("Findings count:", len(rep_noindex["findings"]))
    print("Findings:", [f["id"] for f in rep_noindex["findings"]])

    server.shutdown()
    print("\nDone!")

if __name__ == "__main__":
    main()
