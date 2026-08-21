#!/usr/bin/env python3
"""
OAuth Helper — Adds Google AI Pro accounts to Antigravity Proxy.

HOW IT WORKS (loopback OAuth — the only flow accepted by Google for Antigravity clients):
  1. Run this script ON THE VPS.
  2. Open an SSH tunnel from your laptop:
        ssh -L 8085:localhost:8085 <user>@<your-vps-ip>
  3. Open http://localhost:8085/login in your laptop's browser.
  4. Authenticate with your Google AI Pro account → grant consent → complete.
  5. Repeat steps 3-4 for each account.

SECURITY:
  - Server binds strictly to 127.0.0.1 (not exposed publicly).
  - Refresh tokens NEVER pass through the laptop or public network;
    callbacks are captured on the VPS and POSTed directly to the proxy via localhost.
  - Credentials (client_id, client_secret, API key) are loaded from .env and never displayed.
  - Includes an anti-CSRF state parameter with a 10-minute expiry window.
"""

import html
import http.server
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

PROXY_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("OAUTH_HELPER_PORT", "8085"))
PROXY_URL = "http://127.0.0.1:20130"

# ── Load credentials from .env ────────────────────────────────────────────────

def _load_env():
    env = {}
    path = os.path.join(PROXY_DIR, ".env")
    if not os.path.exists(path):
        print(f"❌ Missing {path}")
        sys.exit(1)
    with open(path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

_ENV = _load_env()
CLIENT_ID = os.environ.get("OAUTH_ACCESS_KEY") or _ENV.get("OAUTH_ACCESS_KEY", "")
CLIENT_SECRET = os.environ.get("OAUTH_SECRET_KEY") or _ENV.get("OAUTH_SECRET_KEY", "")
API_KEY = _ENV.get("AG_PROXY_API_KEY", "")
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = ("https://www.googleapis.com/auth/cloud-platform "
          "https://www.googleapis.com/auth/userinfo.email "
          "https://www.googleapis.com/auth/userinfo.profile "
          "https://www.googleapis.com/auth/cclog "
          "https://www.googleapis.com/auth/experimentsandconfigs openid")

if not CLIENT_ID or not CLIENT_SECRET:
    print("❌ OAUTH_ACCESS_KEY / OAUTH_SECRET_KEY missing in .env")
    sys.exit(1)
if not API_KEY:
    print("❌ AG_PROXY_API_KEY missing in .env")
    sys.exit(1)

_states = {}  # state -> timestamp
_lock = threading.Lock()

PAGE_OK = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Success</title></head>
<body style="font-family:system-ui,sans-serif;background:#0f1117;color:#e4e4e7;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center;background:#16161e;padding:40px 56px;border-radius:16px;border:1px solid #1e1e26">
<h1 style="color:#4ade80;margin:0 0 12px">✅</h1>
<h2 style="margin:0 0 8px">Account added successfully!</h2>
<p style="color:#a1a1aa;margin:4px 0">{email}</p>
<p style="color:#a1a1aa;font-size:14px">Total accounts in pool: {total}</p>
<p style="margin-top:24px"><a href="/login" style="color:#60a5fa">➕ Add another account</a></p>
<p style="color:#52525b;font-size:12px">You may close this tab.</p>
</div></body></html>"""

PAGE_ERR = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Failed</title></head>
<body style="font-family:system-ui,sans-serif;background:#0f1117;color:#e4e4e7;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center;background:#16161e;padding:40px 56px;border-radius:16px;border:1px solid #450a0a">
<h1 style="color:#f87171;margin:0 0 12px">❌</h1>
<h2 style="margin:0 0 8px">{title}</h2>
<p style="color:#a1a1aa">{detail}</p>
<p style="margin-top:24px"><a href="/login" style="color:#60a5fa">🔄 Try again</a></p>
</div></body></html>"""


def _redirect_uri():
    return (os.environ.get("OAUTH_REDIRECT_URI")
            or _ENV.get("OAUTH_REDIRECT_URI")
            or f"http://localhost:{PORT}/callback")


class Handler(http.server.BaseHTTPRequestHandler):
    def _html(self, code, body):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path in ("/", "/login"):
            # Purge expired states (>10 min)
            state = secrets.token_urlsafe(24)
            with _lock:
                now = time.time()
                for k in list(_states):
                    if now - _states[k] > 600:
                        del _states[k]
                _states[state] = now
            params = urllib.parse.urlencode({
                "client_id": CLIENT_ID,
                "redirect_uri": _redirect_uri(),
                "response_type": "code",
                "scope": SCOPES,
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            })
            self.send_response(302)
            self.send_header("Location",
                             f"https://accounts.google.com/o/oauth2/v2/auth?{params}")
            self.end_headers()
            return

        if parsed.path == "/callback":
            qs = urllib.parse.parse_qs(parsed.query)
            error = qs.get("error", [None])[0]
            if error:
                self._html(400, PAGE_ERR.format(
                    title="Google rejected login",
                    detail=f"Google error: {html.escape(error)}. Try again."))
                return
            code = qs.get("code", [None])[0]
            state = qs.get("state", [None])[0]
            with _lock:
                valid = _states.pop(state, None) if state else None
            if not code or valid is None:
                self._html(400, PAGE_ERR.format(
                    title="Invalid state",
                    detail="OAuth session expired or unrecognized. Click 'Try again'."))
                return

            # Exchange authorization code -> refresh token
            data = urllib.parse.urlencode({
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": _redirect_uri(),
            }).encode()
            try:
                req = urllib.request.Request(
                    TOKEN_URL, data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    tokens = json.loads(resp.read().decode())
            except Exception as e:
                self._html(500, PAGE_ERR.format(
                    title="Token exchange failed",
                    detail=f"Google rejected code: {e}"))
                return

            refresh_token = tokens.get("refresh_token")
            if not refresh_token:
                self._html(400, PAGE_ERR.format(
                    title="Could not obtain refresh token",
                    detail="Google did not issue a refresh_token. Ensure you consent and select the correct account."))
                return

            # Fetch account email
            email = "unknown"
            try:
                ureq = urllib.request.Request(
                    "https://www.googleapis.com/oauth2/v1/userinfo?alt=json",
                    headers={"Authorization": f"Bearer {tokens.get('access_token', '')}"})
                with urllib.request.urlopen(ureq, timeout=15) as uresp:
                    email = json.loads(uresp.read().decode()).get("email", "unknown")
            except Exception:
                pass

            # POST directly to proxy via localhost — token stays on VPS
            try:
                add_body = json.dumps({
                    "email": email, "refresh_token": refresh_token}).encode()
                add_req = urllib.request.Request(
                    f"{PROXY_URL}/v1/accounts/add", data=add_body,
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {API_KEY}"})
                with urllib.request.urlopen(add_req, timeout=15) as aresp:
                    total = json.loads(aresp.read().decode()).get("total", "?")
            except urllib.error.HTTPError as e:
                body_txt = e.read().decode(errors="replace")
                try:
                    msg = json.loads(body_txt)["error"]["message"]
                except Exception:
                    msg = body_txt[:120]
                self._html(500, PAGE_ERR.format(
                    title="Proxy rejected account", detail=msg))
                return
            except Exception as e:
                self._html(500, PAGE_ERR.format(
                    title="Failed connecting to proxy",
                    detail=f"Proxy unresponsive: {e}. Ensure ag-proxy is running."))
                return

            print(f"[OK] Added: {email} (total pool: {total})")
            self._html(200, PAGE_OK.format(email=email, total=total))
            return

        self._html(404, PAGE_ERR.format(title="404", detail="Page not found."))

    def log_message(self, fmt, *args):
        # Log request without leaking code/state query params
        print(f"[helper] {self.address_string()} {self.command} {self.path.split('?')[0]}")


def main():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("=" * 62)
    print("  OAuth Helper — Antigravity Proxy")
    print("=" * 62)
    print(f"  Server listening on: http://localhost:{PORT}")
    print()
    print("  FROM LAPTOP, verify active SSH tunnel:")
    print("    ssh -L 8085:localhost:8085 <user>@<your-vps-ip>")
    print()
    print(f"  Then open in browser: http://localhost:{PORT}/login")
    print("  Authenticate with Google AI Pro → grant consent → complete.")
    print("  Repeat for additional accounts. Ctrl+C to terminate.")
    print("=" * 62)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye!")
        server.shutdown()


if __name__ == "__main__":
    main()
