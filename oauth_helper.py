#!/usr/bin/env python3
"""
OAuth Helper — tambah akun Google AI Pro ke Antigravity Proxy.

CARA KERJA (loopback OAuth — satu-satunya cara yang diterima Google
untuk client Antigravity):
  1. Jalankan script ini DI VPS.
  2. Dari laptop, buka SSH tunnel:
        ssh -L 8085:localhost:8085 <user>@<ip-vps-kamu>
  3. Buka http://localhost:8085/login di browser laptop.
  4. Login pakai akun Google AI Pro → consent → selesai.
  5. Ulangi langkah 3-4 untuk tiap akun.

KEAMANAN:
  - Server hanya bind ke 127.0.0.1 (tidak terbuka ke publik).
  - Refresh token TIDAK pernah mampir di laptop / jaringan publik —
    callback ditangkap di VPS, langsung di-POST ke proxy via localhost.
  - Credential (client id/secret + API key) dibaca dari .env proxy,
    tidak pernah ditampilkan.
  - Ada state parameter anti-CSRF, expire 10 menit.
"""

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

# ── Baca credential dari .env (tanpa pernah menampilkan nilainya) ────────────

def _load_env():
    env = {}
    path = os.path.join(PROXY_DIR, ".env")
    if not os.path.exists(path):
        print(f"❌ Tidak ada {path}")
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
    print("❌ OAUTH_ACCESS_KEY / OAUTH_SECRET_KEY tidak ada di .env")
    sys.exit(1)
if not API_KEY:
    print("❌ AG_PROXY_API_KEY tidak ada di .env")
    sys.exit(1)

_states = {}  # state -> timestamp
_lock = threading.Lock()

PAGE_OK = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Berhasil</title></head>
<body style="font-family:system-ui,sans-serif;background:#0f1117;color:#e4e4e7;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center;background:#16161e;padding:40px 56px;border-radius:16px;border:1px solid #1e1e26">
<h1 style="color:#4ade80;margin:0 0 12px">✅</h1>
<h2 style="margin:0 0 8px">Akun berhasil ditambahkan!</h2>
<p style="color:#a1a1aa;margin:4px 0">{email}</p>
<p style="color:#a1a1aa;font-size:14px">Total akun di pool: {total}</p>
<p style="margin-top:24px"><a href="/login" style="color:#60a5fa">➕ Tambah akun lagi</a></p>
<p style="color:#52525b;font-size:12px">Tab ini boleh ditutup.</p>
</div></body></html>"""

PAGE_ERR = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Gagal</title></head>
<body style="font-family:system-ui,sans-serif;background:#0f1117;color:#e4e4e7;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center;background:#16161e;padding:40px 56px;border-radius:16px;border:1px solid #450a0a">
<h1 style="color:#f87171;margin:0 0 12px">❌</h1>
<h2 style="margin:0 0 8px">{title}</h2>
<p style="color:#a1a1aa">{detail}</p>
<p style="margin-top:24px"><a href="/login" style="color:#60a5fa">🔄 Coba lagi</a></p>
</div></body></html>"""


def _redirect_uri():
    return f"http://localhost:{PORT}/callback"


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
            # Bersihkan state kedaluwarsa (>10 menit)
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
                    title="Google menolak login",
                    detail=f"Error dari Google: {error}. Coba lagi."))
                return
            code = qs.get("code", [None])[0]
            state = qs.get("state", [None])[0]
            with _lock:
                valid = _states.pop(state, None) if state else None
            if not code or valid is None:
                self._html(400, PAGE_ERR.format(
                    title="State tidak valid",
                    detail="Session OAuth kedaluwarsa atau tidak dikenal. Klik 'Coba lagi'."))
                return

            # Tukar authorization code → refresh token
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
                    title="Token exchange gagal",
                    detail=f"Google menolak code-nya: {e}"))
                return

            refresh_token = tokens.get("refresh_token")
            if not refresh_token:
                self._html(400, PAGE_ERR.format(
                    title="Tidak dapat refresh token",
                    detail="Google tidak memberikan refresh_token. Coba lagi dan pastikan pilih akun yang benar."))
                return

            # Ambil email akun
            email = "unknown"
            try:
                ureq = urllib.request.Request(
                    "https://www.googleapis.com/oauth2/v1/userinfo?alt=json",
                    headers={"Authorization": f"Bearer {tokens.get('access_token', '')}"})
                with urllib.request.urlopen(ureq, timeout=15) as uresp:
                    email = json.loads(uresp.read().decode()).get("email", "unknown")
            except Exception:
                pass

            # POST langsung ke proxy via localhost — token tidak pernah keluar VPS
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
                    title="Proxy menolak akun", detail=msg))
                return
            except Exception as e:
                self._html(500, PAGE_ERR.format(
                    title="Gagal menghubungi proxy",
                    detail=f"Proxy tidak merespons: {e}. Pastikan ag-proxy jalan."))
                return

            print(f"[OK] Ditambahkan: {email} (total akun: {total})")
            self._html(200, PAGE_OK.format(email=email, total=total))
            return

        self._html(404, PAGE_ERR.format(title="404", detail="Halaman tidak ditemukan."))

    def log_message(self, fmt, *args):
        # Log akses tanpa membocorkan query string (ada code/state di sana)
        print(f"[helper] {self.address_string()} {self.command} {self.path.split('?')[0]}")


def main():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("=" * 62)
    print("  OAuth Helper — Antigravity Proxy")
    print("=" * 62)
    print(f"  Server jalan di: http://localhost:{PORT}")
    print()
    print("  DARI LAPTOP, pastikan SSH tunnel aktif:")
    print("    ssh -L 8085:localhost:8085 <user>@<ip-vps-kamu>")
    print()
    print(f"  Lalu buka di browser: http://localhost:{PORT}/login")
    print("  Login pakai akun Google AI Pro → consent → selesai.")
    print("  Ulangi untuk tiap akun. Ctrl+C untuk berhenti.")
    print("=" * 62)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye!")
        server.shutdown()


if __name__ == "__main__":
    main()
