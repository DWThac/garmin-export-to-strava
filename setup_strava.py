#!/usr/bin/env python3
"""Interactive Strava OAuth setup. Saves credentials to .env."""

import http.server
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import requests

ENV_FILE = Path(__file__).parent / ".env"


def write_env(values: dict):
    existing = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
    existing.update(values)
    ENV_FILE.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n")
    print(f"  Saved to {ENV_FILE}")


def main():
    print("=== Strava API setup ===\n")
    print("  1. Go to https://www.strava.com/settings/api")
    print("  2. Create an app — Authorization Callback Domain: localhost")
    client_id = input("\n  Client ID: ").strip()
    client_secret = input("  Client Secret: ").strip()

    auth_url = (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={client_id}"
        "&response_type=code"
        "&redirect_uri=http://localhost:8765"
        "&approval_prompt=force"
        "&scope=activity:write,activity:read_all"
    )

    code_holder = {}
    server_done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in params:
                code_holder["code"] = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h2>Auth complete - return to terminal</h2>")
                server_done.set()
            else:
                self.send_response(204)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("localhost", 8765), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    print(f"\n  Opening browser...")
    webbrowser.open(auth_url)
    print("  (If browser didn't open, visit this URL manually:)")
    print(f"  {auth_url}\n")
    print("  Waiting for authorization...")

    server_done.wait(timeout=120)
    server.shutdown()

    if "code" not in code_holder:
        sys.exit("  ERROR: did not receive auth code. Re-run setup.")

    resp = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code_holder["code"],
        "grant_type": "authorization_code",
    })
    resp.raise_for_status()
    tokens = resp.json()
    print(f"  Authorized as: {tokens['athlete']['firstname']} {tokens['athlete']['lastname']}")

    write_env({
        "STRAVA_CLIENT_ID": client_id,
        "STRAVA_CLIENT_SECRET": client_secret,
        "STRAVA_REFRESH_TOKEN": tokens["refresh_token"],
    })
    print("\nDone. Now run upload_export.py — see README.md")


if __name__ == "__main__":
    main()
