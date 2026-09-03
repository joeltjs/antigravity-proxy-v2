#!/usr/bin/env python3
"""
Antigravity Multi-Account Proxy Server v2
==========================================
OpenAI-compatible proxy that aggregates multiple Google Antigravity accounts.

v2 improvements:
- Quota tracking (fetchAvailableModels API)
- Web dashboard with dark theme, quota bars
- Password-protected UI
- Account management (add/remove/disable)
- Exposed on port 20130 (requires OCI Security List + password)
"""

import json
import os
import secrets
import time
import threading
import urllib.request
import urllib.parse
import urllib.error
import socket

# WARP SOCKS5 Proxy for routing Google API requests through Cloudflare
# Only outbound requests to Google APIs go through WARP. All other traffic stays local.
WARP_SOCKS5_HOST = "127.0.0.1"
WARP_SOCKS5_PORT = 40000
WARP_ENABLED = os.environ.get("WARP_ENABLED", "true").lower() == "true"

GOOGLE_API_DOMAINS = [
    'daily-cloudcode-pa.googleapis.com',
    'cloudcode-pa.googleapis.com',
    'oauth2.googleapis.com',
    'www.googleapis.com',
    'generativelanguage.googleapis.com'
]

def _is_google_api(host):
    return any(host.endswith(d) for d in GOOGLE_API_DOMAINS)

if WARP_ENABLED:
    try:
        import socks as _socks_mod
        _original_create_connection = socket.create_connection
        
        def _warp_create_connection(address, *args, **kwargs):
            host, port = address
            if _is_google_api(host):
                return _socks_mod.create_connection(
                    dest_pair=(host, port),
                    proxy_type=_socks_mod.SOCKS5,
                    proxy_addr=WARP_SOCKS5_HOST,
                    proxy_port=WARP_SOCKS5_PORT,
                    timeout=kwargs.get('timeout', 300)
                )
            return _original_create_connection(address, *args, **kwargs)
        
        socket.create_connection = _warp_create_connection
        print(f"[WARP] SOCKS5 proxy enabled on {WARP_SOCKS5_HOST}:{WARP_SOCKS5_PORT} (Google API traffic only)")
    except ImportError:
        print("[WARP] PySocks not installed, using direct connection")
        WARP_ENABLED = False
else:
    print("[WARP] Proxy disabled, using direct connection")
import urllib.parse
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

CONFIG_PATH = "/home/ubuntu/ag-proxy/config.json"
ENV_PATH = "/home/ubuntu/ag-proxy/.env"

def _load_env_file(path):
    """Load KEY=VALUE lines from .env file (stdlib only, no deps)."""
    if not os.path.exists(path):
        return {}
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip("'\"")
    return env

_ENV_FILE = _load_env_file(ENV_PATH)

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

PORT = CONFIG.get("port", 20130)
HOST = CONFIG.get("host", "0.0.0.0")
# API keys for /v1/* endpoints (multiple keys supported: config.json or environment)
def _load_api_keys():
    keys = []
    # From config.json api_keys list
    if "api_keys" in CONFIG and isinstance(CONFIG["api_keys"], list):
        for k in CONFIG["api_keys"]:
            if isinstance(k, dict) and k.get("key"):
                keys.append(k)
            elif isinstance(k, str) and k.strip():
                keys.append({"id": f"key-{len(keys)+1}", "name": "Default Key", "key": k.strip(), "created": int(time.time())})
    # From legacy single api_key in config.json
    elif CONFIG.get("api_key"):
        keys.append({"id": "key-1", "name": "Default Key", "key": CONFIG["api_key"].strip(), "created": int(time.time())})
    # Fallback to env var
    env_key = os.environ.get("AG_PROXY_API_KEY")
    if env_key and not any(k["key"] == env_key for k in keys):
        keys.append({"id": f"key-{len(keys)+1}", "name": "Env Key", "key": env_key.strip(), "created": int(time.time())})
    # If completely empty, generate a default one
    if not keys:
        default_k = "ag-proxy-" + secrets.token_hex(16)
        keys.append({"id": "key-1", "name": "Default Key", "key": default_k, "created": int(time.time())})
        CONFIG["api_keys"] = keys
        CONFIG.pop("api_key", None)
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(CONFIG, f, indent=2)
        except Exception: pass
    return keys

API_KEYS = _load_api_keys()

def _save_api_keys():
    CONFIG["api_keys"] = API_KEYS
    CONFIG.pop("api_key", None)
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(CONFIG, f, indent=2)
    except Exception as e:
        print(f"  [WARN] Save API keys error: {e}")
DASHBOARD_USER = os.environ.get("AG_DASHBOARD_USER") or _ENV_FILE.get("AG_DASHBOARD_USER") or CONFIG.get("dashboard_user", "admin")
DASHBOARD_PASSWORD = os.environ.get("AG_DASHBOARD_PASSWORD") or _ENV_FILE.get("AG_DASHBOARD_PASSWORD") or CONFIG.get("dashboard_password", "")
# OAuth (Google Cloud Console): env var > .env > config.json (Optional: for web OAuth login like 9router)
OAUTH = dict(CONFIG.get("oauth", {}))
OAUTH["client_id"] = os.environ.get("OAUTH_ACCESS_KEY") or _ENV_FILE.get("OAUTH_ACCESS_KEY") or OAUTH.get("client_id", "")
OAUTH["client_secret"] = os.environ.get("OAUTH_SECRET_KEY") or _ENV_FILE.get("OAUTH_SECRET_KEY") or OAUTH.get("client_secret", "")
ACCOUNTS = CONFIG["accounts"]
STRATEGY = CONFIG.get("strategy", "round-robin")
MAX_RETRIES = CONFIG.get("max_retries", 3)
API_ENDPOINT = CONFIG["api_endpoint"]
QUOTA_API = "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels"
OAUTH_SCOPES = CONFIG.get("oauth_scopes",
    "https://www.googleapis.com/auth/cloud-platform "
    "https://www.googleapis.com/auth/userinfo.email "
    "https://www.googleapis.com/auth/userinfo.profile "
    "https://www.googleapis.com/auth/cclog "
    "https://www.googleapis.com/auth/experimentsandconfigs openid")
# Redirect URI for Google OAuth: env var > .env > config > derive from Host header.
# Google requires redirect_uri to match Cloud Console configuration exactly.
OAUTH_REDIRECT_URI = (os.environ.get("OAUTH_REDIRECT_URI")
                      or _ENV_FILE.get("OAUTH_REDIRECT_URI")
                      or CONFIG.get("oauth_redirect_uri", ""))

# Circular buffer for dashboard logs
from collections import deque
import datetime
RECENT_LOGS = deque(maxlen=100)

# Active request tracker for dashboard indicator light
# key: request_id, value: {model, account, started, status}
ACTIVE_REQUESTS = {}
_active_lock = threading.Lock()

def track_start(rid, model, account_email):
    with _active_lock:
        ACTIVE_REQUESTS[rid] = {
            "model": model, "account": account_email,
            "started": time.time(), "status": "connecting"
        }

def track_streaming(rid):
    with _active_lock:
        if rid in ACTIVE_REQUESTS:
            ACTIVE_REQUESTS[rid]["status"] = "streaming"

def track_end(rid):
    with _active_lock:
        ACTIVE_REQUESTS.pop(rid, None)

def log_event(level, msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    RECENT_LOGS.append({"ts": ts, "level": level, "msg": msg})
    print(f"[{ts}] [{level}] {msg}")


# ─── Usage Monitor: token stats per completed request ────────────────────────
# Append-only JSONL log + in-memory daily rollups. /v1/usage always answers
# from memory; the file is scanned once at most (lazy first access).
USAGE_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage.jsonl")
USAGE_MAX_BYTES = 5 * 1024 * 1024   # rotate to usage.jsonl.1 above this
USAGE_KEEP_DAYS = 60                # longest window served

_usage_lock = threading.Lock()
_usage_days = {}                    # "YYYY-MM-DD" -> {requests, input, output, cached}
_usage_recent = deque(maxlen=50)    # raw records, oldest first
_usage_h24 = deque()                # (ts, in, out, cached) for the rolling 24h window
_usage_loaded = False


def _usage_day(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _usage_prune_locked(now):
    # Drop 24h entries and day buckets older than the longest window.
    cutoff = now - 86400
    while _usage_h24 and _usage_h24[0][0] < cutoff:
        _usage_h24.popleft()
    oldest = _usage_day(now - (USAGE_KEEP_DAYS - 1) * 86400)
    for k in [k for k in _usage_days if k < oldest]:
        del _usage_days[k]


def _usage_load_locked():
    # One-time rebuild of rollups from the JSONL file (bounded by the 5MB cap).
    global _usage_loaded
    _usage_loaded = True  # set first so a broken file is never re-read per request
    if not os.path.exists(USAGE_LOG):
        return
    now = time.time()
    try:
        with open(USAGE_LOG, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ts = rec.get("ts", 0)
                d = _usage_days.setdefault(_usage_day(ts),
                    {"requests": 0, "input": 0, "output": 0, "cached": 0})
                d["requests"] += 1
                d["input"] += rec.get("in", 0)
                d["output"] += rec.get("out", 0)
                d["cached"] += rec.get("cached", 0)
                if now - ts <= 86400:
                    _usage_h24.append((ts, rec.get("in", 0), rec.get("out", 0), rec.get("cached", 0)))
                _usage_recent.append(rec)
        _usage_prune_locked(now)
    except Exception as e:
        print(f"  [WARN] Usage load: {e}")


def record_usage(model, input_tokens, output_tokens, cached_tokens, status, elapsed_ms):
    # Additive by design — must never break a response, so guard everything.
    try:
        now = time.time()
        rec = {"ts": round(now, 3), "model": model,
               "in": int(input_tokens or 0), "out": int(output_tokens or 0),
               "cached": int(cached_tokens or 0), "status": status,
               "ms": int(elapsed_ms or 0)}
        with _usage_lock:
            if not _usage_loaded:
                _usage_load_locked()
            d = _usage_days.setdefault(_usage_day(now),
                {"requests": 0, "input": 0, "output": 0, "cached": 0})
            d["requests"] += 1
            d["input"] += rec["in"]
            d["output"] += rec["out"]
            d["cached"] += rec["cached"]
            _usage_recent.append(rec)
            _usage_h24.append((now, rec["in"], rec["out"], rec["cached"]))
            _usage_prune_locked(now)
            with open(USAGE_LOG, "a") as f:
                f.write(json.dumps(rec) + "\n")
            if os.path.getsize(USAGE_LOG) > USAGE_MAX_BYTES:
                os.replace(USAGE_LOG, USAGE_LOG + ".1")
    except Exception as e:
        print(f"  [WARN] Usage record: {e}")


def usage_snapshot():
    # Served entirely from memory: 5 window sums + last 15 requests.
    now = time.time()
    with _usage_lock:
        if not _usage_loaded:
            _usage_load_locked()
        _usage_prune_locked(now)

        def blank():
            return {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0}

        windows = {"today": blank(), "h24": blank(), "d7": blank(), "d30": blank(), "d60": blank()}
        today = datetime.datetime.strptime(_usage_day(now), "%Y-%m-%d")
        for day, d in _usage_days.items():
            try:
                age = (today - datetime.datetime.strptime(day, "%Y-%m-%d")).days
            except Exception:
                continue
            if age < 0 or age >= USAGE_KEEP_DAYS:
                continue
            for name, span in (("today", 1), ("d7", 7), ("d30", 30), ("d60", 60)):
                if age < span:
                    w = windows[name]
                    w["requests"] += d["requests"]
                    w["input_tokens"] += d["input"]
                    w["output_tokens"] += d["output"]
                    w["cached_tokens"] += d["cached"]
        for ts, i, o, c in _usage_h24:
            w = windows["h24"]
            w["requests"] += 1
            w["input_tokens"] += i
            w["output_tokens"] += o
            w["cached_tokens"] += c
        # Filter out zero-token OK noise from recent requests if real requests exist
        raw_recent = list(_usage_recent)
        filtered_recent = [r for r in raw_recent if r.get("in", 0) > 0 or r.get("out", 0) > 0 or r.get("status") != "ok"]
        display_recent = filtered_recent[-15:] if filtered_recent else raw_recent[-15:]
        recent = [{"model": r.get("model", ""), "in": r.get("in", 0), "out": r.get("out", 0),
                   "cached": r.get("cached", 0), "status": r.get("status", ""),
                   "ts": r.get("ts", 0), "ms": r.get("ms", 0)}
                  for r in display_recent]
        recent.reverse()  # newest first
    return {"windows": windows, "recent": recent}


# ─── Security: brute-force protection & request limits ───────────────────────
_auth_failures = {}   # ip -> [fail_count, window_start, locked_until]
_auth_lock = threading.Lock()
AUTH_MAX_FAILURES = 5
AUTH_WINDOW = 900     # 15 min window
AUTH_LOCKOUT = 900    # 15 min lockout
MAX_BODY_BYTES = 25 * 1024 * 1024  # 25 MB request body cap

def _auth_allowed(ip):
    with _auth_lock:
        rec = _auth_failures.get(ip)
        if rec and rec[2] > time.time():
            return False
    return True

def _auth_fail(ip):
    with _auth_lock:
        now = time.time()
        rec = _auth_failures.get(ip)
        if not rec or now - rec[1] > AUTH_WINDOW:
            rec = [0, now, 0]
        rec[0] += 1
        if rec[0] >= AUTH_MAX_FAILURES:
            rec[2] = now + AUTH_LOCKOUT
            rec[0] = 0
            log_event("WARN", f"IP {ip} locked out {AUTH_LOCKOUT//60} min after {AUTH_MAX_FAILURES} auth failures")
        _auth_failures[ip] = rec

def _auth_success(ip):
    with _auth_lock:
        _auth_failures.pop(ip, None)


# Per-session random tokens with expiry. The old design derived ONE static
# HMAC from the dashboard password — forgeable offline, shared by every
# browser, never expired, impossible to revoke (Strix finding vuln-0001).
_SESSION_TOKENS = {}  # token -> expiry ts
SESSION_TTL = 24 * 3600


def _issue_session_token():
    tok = secrets.token_urlsafe(32)
    now = time.time()
    with _auth_lock:
        for k in [k for k, exp in _SESSION_TOKENS.items() if exp < now]:
            del _SESSION_TOKENS[k]
        _SESSION_TOKENS[tok] = now + SESSION_TTL
    return tok


def _session_token_valid(tok):
    with _auth_lock:
        exp = _SESSION_TOKENS.get(tok)
        if exp is None:
            return False
        if exp < time.time():
            del _SESSION_TOKENS[tok]
            return False
    return True


# ─── Account State ────────────────────────────────────────────────────────────

class AccountState:
    def __init__(self, cfg):
        self.email = cfg["email"]
        self.refresh_token = cfg["refresh_token"]
        self.disabled = cfg.get("disabled", False)
        self.access_token = None
        self.expires_at = 0
        self.lock = threading.Lock()
        self.request_count = 0
        self.error_count = 0
        self.last_error = None
        self.rate_limited_until = 0
        self.quota = {}  # model -> {remainingFraction, resetTime}
        self.quota_fetched_at = 0

    def get_token(self):
        with self.lock:
            now = time.time()
            if not self.access_token or now >= self.expires_at - 300:
                self._refresh()
            return self.access_token

    def _refresh(self):
        data = urllib.parse.urlencode({
            "client_id": OAUTH["client_id"],
            "client_secret": OAUTH["client_secret"],
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token"
        }).encode()
        req = urllib.request.Request(OAUTH["token_url"], data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                self.access_token = result["access_token"]
                self.expires_at = time.time() + result.get("expires_in", 3599)
                self.error_count = 0
                self.last_error = None
                print(f"  [TOKEN] Refreshed {self.email} ({result.get('expires_in',3599)}s)")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()
            self.last_error = f"HTTP {e.code}: {err_body[:200]}"
            self.error_count += 1
            if "invalid_grant" in err_body:
                self.disabled = True
            raise
        except Exception as e:
            self.last_error = str(e)
            self.error_count += 1
            raise

    def fetch_quota(self):
        """Fetch quota info from Antigravity API."""
        try:
            token = self.get_token()
            req = urllib.request.Request(QUOTA_API,
                data=b'{}',
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "User-Agent": "antigravity/ide/2.1.1 darwin/arm64"
                })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                models = data.get("models", {})
                self.quota = {}
                for model_id, info in models.items():
                    qi = info.get("quotaInfo", {})
                    if qi:
                        self.quota[model_id] = {
                            "remainingFraction": qi.get("remainingFraction", 0),
                            "resetTime": qi.get("resetTime", ""),
                            "displayName": info.get("displayName", model_id),
                            "maxOutputTokens": info.get("maxOutputTokens", 0)
                        }
                self.quota_fetched_at = time.time()
                return True
        except Exception as e:
            print(f"  [QUOTA] Failed for {self.email}: {e}")
            return False

    def status(self):
        return {
            "email": self.email,
            "disabled": self.disabled,
            "has_token": bool(self.access_token),
            "expires_in": max(0, int(self.expires_at - time.time())),
            "requests": self.request_count,
            "errors": self.error_count,
            "last_error": self.last_error,
            "quota": self.quota,
            "quota_age": int(time.time() - self.quota_fetched_at) if self.quota_fetched_at else -1
        }


ACCOUNT_STATES = [AccountState(a) for a in ACCOUNTS]
_round_robin_idx = 0
_rr_lock = threading.Lock()


def get_next_account():
    global _round_robin_idx
    now = time.time()
    with _rr_lock:
        available = [a for a in ACCOUNT_STATES if not a.disabled]
        if not available:
            return None
        if STRATEGY == "sticky":
            # Use the first non-rate-limited account; only fall back if all limited
            for acc in available:
                if now >= acc.rate_limited_until:
                    return acc
            return available[0]
        for _ in range(len(available)):
            idx = _round_robin_idx % len(ACCOUNT_STATES)
            _round_robin_idx += 1
            acc = ACCOUNT_STATES[idx]
            if not acc.disabled and now >= acc.rate_limited_until:
                return acc
        # All rate-limited — still return something rather than failing
        return available[0]


def get_fallback_account(exclude_email):
    """Pick an account different from the excluded one (for sticky failover)."""
    now = time.time()
    with _rr_lock:
        global _round_robin_idx
        candidates = [a for a in ACCOUNT_STATES
                      if not a.disabled and a.email != exclude_email and now >= a.rate_limited_until]
        if not candidates:
            candidates = [a for a in ACCOUNT_STATES if not a.disabled and a.email != exclude_email]
        if not candidates:
            return None
        idx = _round_robin_idx % len(candidates)
        _round_robin_idx += 1
        return candidates[idx]


def add_account_to_pool(email, refresh_token):
    global ACCOUNT_STATES
    with _rr_lock:
        for i, acc in enumerate(ACCOUNT_STATES):
            if acc.email == email:
                ACCOUNT_STATES[i] = AccountState({"email": email, "refresh_token": refresh_token})
                break
        else:
            ACCOUNT_STATES.append(AccountState({"email": email, "refresh_token": refresh_token}))
        _save_accounts()
    for acc in ACCOUNT_STATES:
        if acc.email == email:
            try: acc.get_token()
            except Exception: pass
            break


def remove_account_from_pool(email):
    global ACCOUNT_STATES
    with _rr_lock:
        before = len(ACCOUNT_STATES)
        ACCOUNT_STATES = [a for a in ACCOUNT_STATES if a.email != email]
        if len(ACCOUNT_STATES) == before:
            return False
        _save_accounts()
    return True


def _save_accounts():
    config_accounts = []
    for acc in ACCOUNT_STATES:
        config_accounts.append({
            "email": acc.email, "refresh_token": acc.refresh_token, "disabled": acc.disabled
        })
    try:
        CONFIG["accounts"] = config_accounts
        with open(CONFIG_PATH, "w") as f:
            json.dump(CONFIG, f, indent=2)
    except Exception as e:
        print(f"  [WARN] Save config: {e}")


# ─── Model Mapping ────────────────────────────────────────────────────────────

MODEL_MAP = {
    "gemini-3.7-flash-high": "gemini-3.7-flash-tiered",
    "gemini-3.7-flash-medium": "gemini-3.7-flash-tiered",
    "gemini-3.6-flash-high": "gemini-3.6-flash-high",
    "gemini-3.1-pro-high": "gemini-pro-agent",
    "claude-sonnet-4-6-thinking": "claude-sonnet-4-6",
    "claude-opus-4-6-thinking": "claude-opus-4-6-thinking",
}

# Full upstream catalog (for dashboard "show all models" button).
# Source: Antigravity API; includes image & completion models not exposed to Hermes.
FULL_MODEL_CATALOG = [
    {"id": "gemini-3.7-flash-high", "display": "Gemini 3.7 Flash (High)", "kind": "chat"},
    {"id": "gemini-3.7-flash-tiered", "display": "Gemini 3.7 Flash (Tiered)", "kind": "chat"},
    {"id": "gemini-3.6-flash-tiered", "display": "Gemini 3.6 Flash (Tiered)", "kind": "chat"},
    {"id": "gemini-3.6-flash-high", "display": "Gemini 3.6 Flash (High)", "kind": "chat"},
    {"id": "gemini-3.6-flash-medium", "display": "Gemini 3.6 Flash (Medium)", "kind": "chat"},
    {"id": "gemini-3.6-flash-low", "display": "Gemini 3.6 Flash (Low)", "kind": "chat"},
    {"id": "gemini-3.5-flash-high", "display": "Gemini 3.5 Flash (High)", "kind": "chat"},
    {"id": "gemini-3-flash-agent", "display": "Gemini 3 Flash Agent", "kind": "chat"},
    {"id": "gemini-3.5-flash-low", "display": "Gemini 3.5 Flash (Medium)", "kind": "chat"},
    {"id": "gemini-3.5-flash-extra-low", "display": "Gemini 3.5 Flash (Low)", "kind": "chat"},
    {"id": "gemini-pro-agent", "display": "Gemini 3.1 Pro (High)", "kind": "chat"},
    {"id": "gemini-3.1-pro-low", "display": "Gemini 3.1 Pro (Low)", "kind": "chat"},
    {"id": "claude-sonnet-4-6", "display": "Claude Sonnet 4.6 (Thinking)", "kind": "chat"},
    {"id": "claude-opus-4-6-thinking", "display": "Claude Opus 4.6 (Thinking)", "kind": "chat"},
    {"id": "gpt-oss-120b-medium", "display": "GPT-OSS 120B (Medium)", "kind": "completion"},
    {"id": "gemini-3-flash", "display": "Gemini 3 Flash", "kind": "chat"},
    {"id": "gemini-3.1-flash-image", "display": "Gemini 3.1 Flash (Image)", "kind": "image"},
]

# ─── OpenAI → Antigravity Translation ────────────────────────────────────────

def _sanitize_fn_name(name):
    """Gemini/Antigravity function name rules (mirrors 9router):
    only [a-zA-Z0-9_.:-], first char letter/underscore, max 64 chars."""
    if not name:
        return "_unknown"
    import re
    s = re.sub(r"[^a-zA-Z0-9_.:\-]", "_", name)
    if not re.match(r"^[a-zA-Z_]", s):
        s = "_" + s
    return s[:64]


def _clean_schema_for_gemini(schema):
    """Recursively clean JSON Schema for Gemini/Antigravity API:
    Only allow fields supported by Google CloudCode Schema proto:
    type, format, description, nullable, enum, properties, required, items.
    Converts and strips all draft-04/07/2020 validation keys."""
    if not isinstance(schema, dict):
        return schema

    ALLOWED_KEYS = {
        "type", "format", "description", "nullable", "enum",
        "properties", "required", "items"
    }

    cleaned = {}
    for k, v in schema.items():
        if k not in ALLOWED_KEYS:
            continue
        if k == "properties" and isinstance(v, dict):
            cleaned[k] = {pk: _clean_schema_for_gemini(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            cleaned[k] = _clean_schema_for_gemini(v)
        elif isinstance(v, dict):
            cleaned[k] = _clean_schema_for_gemini(v)
        elif isinstance(v, list):
            cleaned[k] = [_clean_schema_for_gemini(item) if isinstance(item, dict) else item for item in v]
        else:
            cleaned[k] = v
    return cleaned


# Antigravity requires a thought_signature on functionCall parts for tool use.
# 9router uses this static default signature and it works (verified in its
# openai-to-gemini.js translator: DEFAULT_THINKING_AG_SIGNATURE).
DEFAULT_THOUGHT_SIGNATURE = (
    "EuwGCukGAXLI2nxwZIq54WWSoL/YN0P3TsDZ7zRnLi8g0S4aVr2HUGxvaHKySuY6HAVzcE0GPGjXrytLIldxthSvfxgUlJh6Qa9Z"
    "+Oj5QZBlYdg6HaJ6yuY5R7waE6rdwBsRf7Ft2j3DJ9rMi9qhWFqApewYtPhls3VHtuvND3l8Rm09+lbAXQs6KKWEWrxNLKTBkfpMg"
    "XhRERc/TQRMZu1twAablm6/Zk1tsYRvfWKLsNbeKF+CCojJdXJKvnR/8Ouuoa+Y2Ti20hcW7aZIIjZDFYPU//k6Ybmhg69J/imbFa"
    "i2ckhfLaisqdDkdoIiBJScTOUvYqP6AE9d4MsydSC+UlhIMk4hoP76R8vUSCZRMkjOaDXstf/QoVZKbt94wyRZgAJ1G0BqI8L5ow8"
    "6kLpA4wJEtxsRGymOE4bKUvApveBakYDNM9APkf+LbtbzWSseGjoZcSlycF9iN8Q2XNYKRrHbv3Lr5Y8JjdH/5y/6SHkNehTEZugae"
    "GnSPSyCTWto1kQgHpxdWmhkLfJGNUGLmue7Mesj4TSms4J33mRpYVhNB/J333FCqIP0hr/E7BkkjEn7yZ4X7SQlh+xKPurapsnHRwi"
    "KmtsilmEFrnTE9iQr+pMr6M29qqFNv1tr5yumbaJw8JW9sB15tNsRv+dW6BjNanbsKz7HCgKUBc8tGy+7YuhXzAfViyRefcjK7eZW0"
    "Fbyt7AbybJTKz78W8NH7ye6LAwzOebXpeZ4D43fNIt8bKh26qgduSQv/7o+pAflkuqHZ99YWgHQ8h8OkZFi3eOiSYjsjhdZ/czWOdo"
    "PI/OnqIldzMPF5YlrKBLFX8VhRKVmqgsmWf5PHGulHhMkVlS+XG2UIseGy69ARa93D78Gsa+1n1kJr7EEB7Rh+27vUMxVYLdz1yMSv"
    "E5nalTAlg/ZeG8+XQ0cHuAI3KbQpHW2Q++RdXfm5JzD5WdJZUU+Zn8t8UUn85BH4RxZLeE0qJikgSsKoYVBc6YhiMjhPgkR95ReimY4"
    "Z0xCJdRo1gjexOFeODZMpQF6Yxnoic7IrdgsFA3iePTbFnPp3IAM1fAThWhXJUn3QInUOTd5o1qmTmn6REbL15g/JQNl+dqUoPkhle"
    "eb2V3kjqp1okmO3wMZbPknR3S1LZNmlS72/iBQUm+n2b/RCn4PjmM2"
)


def openai_to_antigravity(body):
    messages = body.get("messages", [])
    model = body.get("model", "gemini-3-flash")
    stream = body.get("stream", False)
    max_tokens = body.get("max_tokens") or 8192
    temperature = body.get("temperature")
    top_p = body.get("top_p")
    # Strip provider prefix (e.g. "ag2/gemini-3-flash" → "gemini-3-flash")
    bare_model = model.split("/", 1)[1] if "/" in model and model.split("/", 1)[0] not in MODEL_MAP else model
    # Per-model max output limits (Antigravity rejects values above these)
    MODEL_MAX_TOKENS = {"claude-sonnet-4-6-thinking": 64000, "claude-opus-4-6-thinking": 64000}
    if bare_model in MODEL_MAX_TOKENS and max_tokens > MODEL_MAX_TOKENS[bare_model]:
        max_tokens = MODEL_MAX_TOKENS[bare_model]
    ag_model = MODEL_MAP.get(bare_model, bare_model)

    # Build tool_call_id -> sanitized function name map (Gemini requires
    # functionResponse.name to match the original functionCall name)
    tool_id_to_name = {}
    for msg in messages:
        for tc in msg.get("tool_calls") or []:
            tc_id = tc.get("id")
            fn_name = (tc.get("function") or {}).get("name")
            if tc_id and fn_name:
                tool_id_to_name[tc_id] = _sanitize_fn_name(fn_name)

    contents = []
    system_instruction = None
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")
        if role == "system":
            if isinstance(content, str):
                system_instruction = {"parts": [{"text": content}]}
            elif isinstance(content, list):
                texts = [p.get("text", "") for p in content if p.get("type") == "text"]
                system_instruction = {"parts": [{"text": " ".join(texts)}]}
            continue
        ag_role = "model" if role == "assistant" else "user"
        if role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            content_str = content if isinstance(content, str) else json.dumps(content)
            resolved_name = tool_id_to_name.get(tool_call_id, "tool")
            contents.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {
                        "id": tool_call_id or None,
                        "name": resolved_name,
                        "response": {"result": content_str}
                    }
                }]
            })
            continue
        parts = []
        tool_calls = msg.get("tool_calls")
        if isinstance(content, str) and content:
            parts.append({"text": content})
        elif isinstance(content, list):
            for p in content:
                if p.get("type") == "text" and p.get("text"):
                    parts.append({"text": p["text"]})
                elif p.get("type") == "image_url":
                    url = p.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        header, b64data = url.split(",", 1)
                        mime = header.split(":")[1].split(";")[0]
                        parts.append({"inlineData": {"mimeType": mime, "data": b64data}})
                elif p.get("type") == "input_audio":
                    # OpenAI audio part -> Gemini inlineData. Only runs when
                    # the request actually carries audio; plain chat is untouched.
                    audio = p.get("input_audio") or {}
                    data = audio.get("data")
                    if data:
                        fmt = (audio.get("format") or "wav").lower()
                        mime = {"wav": "audio/wav", "mp3": "audio/mp3", "m4a": "audio/mp4",
                                "flac": "audio/flac", "ogg": "audio/ogg", "aac": "audio/aac"}.get(fmt, f"audio/{fmt}")
                        parts.append({"inlineData": {"mimeType": mime, "data": data}})
                elif p.get("type") == "audio_url":
                    # Alternate style: base64 data URL
                    url = (p.get("audio_url") or {}).get("url", "")
                    if url.startswith("data:"):
                        header, b64data = url.split(",", 1)
                        mime = header.split(":")[1].split(";")[0]
                        parts.append({"inlineData": {"mimeType": mime, "data": b64data}})
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except: args = {}
                if not isinstance(args, dict):
                    args = {"value": args}
                tc_id = tc.get("id", "")
                parts.append({"thoughtSignature": DEFAULT_THOUGHT_SIGNATURE,
                    "functionCall": {
                    "id": tc_id or None,
                    "name": tool_id_to_name.get(tc_id, _sanitize_fn_name(fn.get("name", ""))),
                    "args": args}})
        if parts:
            contents.append({"role": ag_role, "parts": parts})
    # Gemini requires strict user/model alternation — merge adjacent same-role entries
    merged = []
    for c in contents:
        if merged and merged[-1]["role"] == c["role"]:
            merged[-1]["parts"].extend(c["parts"])
        else:
            merged.append({"role": c["role"], "parts": list(c["parts"])})
    contents = merged
    gen_config = {"maxOutputTokens": max_tokens}
    if temperature is not None: gen_config["temperature"] = temperature
    if top_p is not None: gen_config["topP"] = top_p
    reasoning_effort = body.get("reasoning_effort")
    if reasoning_effort:
        budget_map = {"low": 1024, "medium": 8192, "high": 24576}
        budget = budget_map.get(reasoning_effort, 8192)
        gen_config["thinkingConfig"] = {"thinkingBudget": budget}
        # Claude requires max_tokens > thinking budget — bump if needed
        if max_tokens <= budget:
            gen_config["maxOutputTokens"] = budget + 4096
    tools = []
    for tool in body.get("tools", []):
        if tool.get("type") == "function":
            fn = tool.get("function", {})
            raw_params = fn.get("parameters", {"type": "object", "properties": {}})
            cleaned_params = _clean_schema_for_gemini(raw_params)
            tools.append({"functionDeclarations": [{
                "name": _sanitize_fn_name(fn.get("name", "")),
                "description": fn.get("description", ""),
                "parameters": cleaned_params}]})
    ag_request = {"model": ag_model, "userAgent": "antigravity",
        "request": {"contents": contents, "generationConfig": gen_config}}
    if system_instruction: ag_request["request"]["systemInstruction"] = system_instruction
    if tools: ag_request["request"]["tools"] = tools
    return ag_request, stream


def antigravity_to_openai(ag_response, model_name, request_id):
    candidates = ag_response.get("response", {}).get("candidates", [])
    usage = ag_response.get("response", {}).get("usageMetadata", {})
    content = ""
    reasoning_content = ""
    tool_calls = []
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            if part.get("thought") and part.get("text"):
                reasoning_content += part["text"]
            elif part.get("text"):
                content += part["text"]
            elif part.get("functionCall"):
                fc = part["functionCall"]
                tool_calls.append({"id": fc.get("id", f"call_{fc.get('name','')}"),
                    "type": "function", "function": {
                        "name": fc.get("name", ""),
                        "arguments": json.dumps(fc.get("args", {}))}})
    message = {"role": "assistant"}
    if content: message["content"] = content
    if reasoning_content: message["reasoning_content"] = reasoning_content
    if tool_calls: message["tool_calls"] = tool_calls
    if not content and not tool_calls: message["content"] = ""
    return {"id": request_id, "object": "chat.completion", "created": int(time.time()),
        "model": model_name,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
            "reasoning_tokens": usage.get("thoughtsTokenCount", 0),
            "prompt_tokens_details": {
                "cached_tokens": usage.get("cachedContentTokenCount", 0)
            }}}


def antigravity_chunk_to_openai(chunk_data, model_name, request_id, state):
    response = chunk_data.get("response", {})
    candidates = response.get("candidates", [])
    usage = response.get("usageMetadata", {})
    if usage:
        state["usage"] = usage
    if not candidates:
        return None
    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    finish_reason = candidate.get("finishReason")
    delta = {}
    content = ""
    reasoning = ""
    tool_calls = []
    for part in parts:
        if part.get("thought") and part.get("text"):
            reasoning += part["text"]
        elif part.get("text"):
            content += part["text"]
        elif part.get("functionCall"):
            fc = part["functionCall"]
            tool_calls.append({"index": len(state.get("tool_calls", [])),
                "id": fc.get("id", f"call_{fc.get('name','')}"), "type": "function",
                "function": {"name": fc.get("name", ""),
                    "arguments": json.dumps(fc.get("args", {}))}})
    if reasoning: delta["reasoning_content"] = reasoning
    if content: delta["content"] = content
    if tool_calls:
        delta["tool_calls"] = tool_calls
        state.setdefault("tool_calls", []).extend(tool_calls)
    openai_finish = None
    if finish_reason:
        finish_map = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "content_filter", "RECITATION": "content_filter"}
        openai_finish = finish_map.get(finish_reason, "stop")
    if not delta and not openai_finish: return None
    chunk = {"id": request_id, "object": "chat.completion.chunk", "created": int(time.time()),
        "model": model_name,
        "choices": [{"index": 0, "delta": delta, "finish_reason": openai_finish}]}
    if usage:
        chunk["usage"] = {"prompt_tokens": usage.get("promptCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
            "reasoning_tokens": usage.get("thoughtsTokenCount", 0)}
    return chunk


# ─── Request Handler ──────────────────────────────────────────────────────────

class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress default logging

    def _client_ip(self):
        # Trust X-Forwarded-For only if behind a known proxy; otherwise peer IP
        return self.client_address[0] if self.client_address else "unknown"

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")

    def _send_json(self, code, data, account_email=None, set_cookie=None):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        if account_email:
            self.send_header("X-Account-Used", account_email)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self, max_bytes=None):
        """Read request body with size cap (DoS protection)."""
        try:
            cl = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            return None, "Invalid Content-Length"
        limit = max_bytes or MAX_BODY_BYTES
        if cl < 0 or cl > limit:
            return None, f"Request body too large (max {limit // (1024*1024)}MB)"
        if cl == 0:
            return b"", None
        return self.rfile.read(cl), None

    def _bearer_ok(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
            for k in API_KEYS:
                if secrets.compare_digest(token, k["key"]):
                    return True
        return False

    def _cookie_session_ok(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("ag_session="):
                if _session_token_valid(part[11:]):
                    return True
        return False

    def _basic_auth_ok(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return False
        import base64
        try:
            decoded = base64.b64decode(auth[6:]).decode()
        except Exception:
            return False
        expected = f"{DASHBOARD_USER}:{DASHBOARD_PASSWORD}"
        return secrets.compare_digest(decoded, expected)

    def _check_auth(self):
        """API auth: Bearer API key, or dashboard session cookie (browser)."""
        ip = self._client_ip()
        if not _auth_allowed(ip):
            self._send_json(429, {"error": {"message": "Too many failed attempts. Try again later."}})
            return False
        if self._cookie_session_ok() or self._bearer_ok():
            return True
        # Missing or expired session cookie on API call should return 401, NOT count as a password brute-force failure
        self._send_json(401, {"error": {"message": "Invalid or missing credentials"}})
        return False

    def _check_dashboard_auth(self):
        """Dashboard auth: session cookie or Basic Auth (sets cookie on success)."""
        if not DASHBOARD_PASSWORD:
            return True
        ip = self._client_ip()
        if not _auth_allowed(ip):
            self.send_response(429)
            self.send_header("Content-Type", "text/plain")
            self._security_headers()
            self.end_headers()
            self.wfile.write(b"Too many failed attempts. Try again later.")
            return False
        if self._cookie_session_ok():
            return True
        if self._basic_auth_ok():
            _auth_success(ip)
            return True
        
        # Serve modern dark login UI instead of browser popup
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._security_headers()
        self.end_headers()
        login_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "login.html")
        if os.path.exists(login_path):
            with open(login_path, "rb") as lf:
                self.wfile.write(lf.read())
        else:
            self.wfile.write(b"<h1>Please login</h1>")
        return False

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True})
            return

        # Dashboard routes (password protected)
        if self.path == "/" or self.path == "/index.html" or self.path.startswith("/auth/"):
            if not self._check_dashboard_auth():
                return

        if self.path == "/" or self.path == "/index.html":
            self._serve_dashboard()
            return

        if self.path == "/auth/login":
            self._oauth_login()
            return

        if self.path.startswith("/auth/callback"):
            self._oauth_callback()
            return

        if self.path == "/v1/models":
            if not self._check_auth(): return
            models = [{"id": n, "object": "model", "created": 1700000000, "owned_by": "antigravity"} for n in MODEL_MAP]
            self._send_json(200, {"object": "list", "data": models})
            return

        if self.path == "/v1/accounts":
            if not self._check_auth(): return
            self._send_json(200, {"accounts": [a.status() for a in ACCOUNT_STATES], "strategy": STRATEGY})
            return

        if self.path == "/v1/quota":
            if not self._check_auth(): return
            # Force refresh quota for all accounts
            for acc in ACCOUNT_STATES:
                if not acc.disabled:
                    acc.fetch_quota()
            self._send_json(200, {"accounts": [a.status() for a in ACCOUNT_STATES]})
            return

        if self.path == "/v1/logs":
            if not self._check_auth(): return
            self._send_json(200, {"logs": list(RECENT_LOGS)})
            return

        if self.path == "/v1/all-models":
            if not self._check_auth(): return
            self._send_json(200, {"models": FULL_MODEL_CATALOG})
            return

        if self.path == "/v1/api-keys":
            if not self._check_auth(): return
            self._send_json(200, {"api_keys": API_KEYS})
            return

        if self.path == "/v1/api-key":
            if not self._check_auth(): return
            primary_key = API_KEYS[0]["key"] if API_KEYS else ""
            self._send_json(200, {"api_key": primary_key, "api_keys": API_KEYS})
            return

        if self.path == "/v1/active":
            if not self._check_auth(): return
            with _active_lock:
                active = [
                    {"model": r["model"], "account": r["account"],
                     "status": r["status"], "elapsed": round(time.time() - r["started"], 1)}
                    for r in ACTIVE_REQUESTS.values()
                ]
            self._send_json(200, {"active": active})
            return

        if self.path == "/v1/usage":
            if not self._check_auth(): return
            self._send_json(200, usage_snapshot())
            return

        self._send_json(404, {"error": {"message": "Not found"}})

    def do_PUT(self):
        """PUT /v1/strategy — switch between round-robin and sticky."""
        global STRATEGY
        if not self._check_auth(): return
        if self.path == "/v1/strategy":
            body_raw, err = self._read_body(4096)
            if err:
                self._send_json(413, {"error": {"message": err}})
                return
            try:
                req = json.loads(body_raw)
                strategy = req.get("strategy", "").strip()
            except Exception:
                self._send_json(400, {"error": {"message": "Invalid JSON"}})
                return
            if strategy not in ("round-robin", "sticky"):
                self._send_json(400, {"error": {"message": "strategy must be 'round-robin' or 'sticky'"}})
                return
            STRATEGY = strategy
            CONFIG["strategy"] = strategy
            try:
                with open(CONFIG_PATH, "w") as f:
                    json.dump(CONFIG, f, indent=2)
            except Exception as e:
                print(f"  [WARN] Save strategy: {e}")
            print(f"[CONFIG] Strategy changed to: {strategy}")
            self._send_json(200, {"ok": True, "strategy": strategy})
            return
        self._send_json(404, {"error": {"message": "Not found"}})

    def _serve_dashboard(self):
        dashboard_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
        try:
            with open(dashboard_path, "rb") as f:
                html = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self._security_headers()
            # Content-Security-Policy: block inline injection & external scripts
            self.send_header("Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
            # Fresh per-session token (httpOnly — JS can't read it)
            self.send_header("Set-Cookie", f"ag_session={_issue_session_token()}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400")
            self.end_headers()
            self.wfile.write(html)
        except Exception:
            # Never expose internal details to the client
            self._send_json(500, {"error": {"message": "Internal server error"}})

    # ── OAuth ──

    _oauth_states = {}

    def _redirect_uri(self):
        """Redirect URI: dari .env/env, atau loopback Host (ssh -L flow)."""
        if OAUTH_REDIRECT_URI:
            return OAUTH_REDIRECT_URI
        # Fallback only ever serves the ssh -L localhost flow. Trusting an
        # arbitrary Host header here let an attacker point redirect_uri at
        # their own domain and steal the OAuth code (Strix vuln-0001).
        host_hdr = self.headers.get("Host") or ""
        host = host_hdr.split(":")[0]
        if host not in ("localhost", "127.0.0.1", "[::1]", "::1"):
            return None
        return f"http://{host_hdr}/auth/callback"

    def _oauth_login(self):
        redirect_uri = self._redirect_uri()
        if not redirect_uri:
            self._send_json(400, {"error": {"message":
                "Set OAUTH_REDIRECT_URI in .env before using OAuth login"}})
            return
        state = secrets.token_urlsafe(24)
        self._oauth_states[state] = time.time()
        for k in list(self._oauth_states):
            if time.time() - self._oauth_states[k] > 600:
                del self._oauth_states[k]
        params = urllib.parse.urlencode({
            "client_id": OAUTH["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": OAUTH_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state
        })
        self.send_response(302)
        self.send_header("Location", f"https://accounts.google.com/o/oauth2/v2/auth?{params}")
        self.end_headers()

    def _oauth_callback(self):
        import html as _html
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        state = qs.get("state", [None])[0]
        code = qs.get("code", [None])[0]
        error = qs.get("error", [None])[0]
        if error:
            # Never reflect raw upstream input without sanitizing
            self._send_json(400, {"error": {"message": "OAuth error"}})
            return
        if not code or not state or state not in self._oauth_states:
            self._send_json(400, {"error": {"message": "Invalid or expired OAuth state"}})
            return
        del self._oauth_states[state]
        redirect_uri = self._redirect_uri()
        if not redirect_uri:
            self._send_json(400, {"error": {"message":
                "Set OAUTH_REDIRECT_URI in .env before using OAuth login"}})
            return
        data = urllib.parse.urlencode({
            "client_id": OAUTH["client_id"], "client_secret": OAUTH["client_secret"],
            "code": code, "grant_type": "authorization_code",
            "redirect_uri": redirect_uri
        }).encode()
        req = urllib.request.Request(OAUTH["token_url"], data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
        except urllib.error.HTTPError:
            self._send_json(500, {"error": {"message": "Token exchange failed"}})
            return
        refresh_token = result.get("refresh_token")
        if not refresh_token:
            self._send_json(400, {"error": {"message": "No refresh_token (re-consent needed)"}})
            return
        email = "unknown"
        try:
            ureq = urllib.request.Request("https://www.googleapis.com/oauth2/v1/userinfo?alt=json",
                headers={"Authorization": f"Bearer {result.get('access_token', '')}"})
            with urllib.request.urlopen(ureq, timeout=15) as uresp:
                email = json.loads(uresp.read().decode()).get("email", "unknown")
        except Exception:
            pass
        add_account_to_pool(email, refresh_token)
        # Escape all dynamic values — email comes from external source (XSS prevention)
        safe_email = _html.escape(str(email), quote=True)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._security_headers()
        self.end_headers()
        self.wfile.write(f"""<!DOCTYPE html><html><body style="font-family:sans-serif;padding:40px;text-align:center;background:#0f1117;color:#e4e4e7">
<h2 style="color:#4ade80">Account successfully added!</h2><p style="color:#a1a1aa">Email: {safe_email}</p>
<p style="color:#a1a1aa">Total accounts: {len(ACCOUNT_STATES)}</p>
<p><a href="/" style="color:#3b82f6">&larr; Back to Dashboard</a></p></body></html>""".encode())
        print(f"[AUTH] Added {email}. Total: {len(ACCOUNT_STATES)}")

    def do_POST(self):
        global API_KEYS

        if self.path == "/auth/login-web":
            body_raw, err = self._read_body(64 * 1024)
            ip = self._client_ip()
            if not _auth_allowed(ip):
                self._send_json(429, {"error": {"message": "Too many failed attempts. Please wait."}})
                return
            if err or not body_raw:
                self._send_json(400, {"error": {"message": "Missing credentials"}})
                return
            try:
                data = json.loads(body_raw)
                u = data.get("username", "").strip()
                p = data.get("password", "")
                if secrets.compare_digest(u, DASHBOARD_USER) and secrets.compare_digest(p, DASHBOARD_PASSWORD):
                    _auth_success(ip)
                    tok = _issue_session_token()
                    cookie_val = f"ag_session={tok}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400"
                    self.send_response(200)
                    self.send_header("Set-Cookie", cookie_val)
                    self.send_header("Content-Type", "application/json")
                    self._security_headers()
                    self.end_headers()
                    self.wfile.write(b'{"ok": true}')
                    log_event("INFO", f"Dashboard login success from {ip}")
                else:
                    _auth_fail(ip)
                    log_event("WARN", f"Dashboard login failed from {ip}")
                    self._send_json(401, {"error": {"message": "Invalid username or password"}})
            except Exception as e:
                self._send_json(400, {"error": {"message": str(e)}})
            return

        if not self._check_auth(): return

        if self.path == "/api/import-9router":
            body_raw, _ = self._read_body(64 * 1024)
            custom_path = None
            if body_raw:
                try:
                    req_data = json.loads(body_raw)
                    custom_path = req_data.get("path", "").strip() or None
                except Exception: pass

            import sqlite3
            candidate_paths = []
            if custom_path:
                candidate_paths.append(os.path.expanduser(custom_path))
            
            # Check configured path in config.json
            saved_router_path = CONFIG.get("router_db_path")
            if saved_router_path:
                candidate_paths.append(os.path.expanduser(saved_router_path))

            # Default search paths
            candidate_paths.extend([
                os.path.expanduser("~/.9router/db/data.sqlite"),
                "/app/data/db/data.sqlite",
                "/home/ubuntu/.9router/db/data.sqlite"
            ])

            found_db = None
            for p in candidate_paths:
                if os.path.exists(p) and os.path.isfile(p):
                    found_db = p
                    break

            if not found_db:
                self._send_json(404, {
                    "error": {
                        "message": "9router database not found in default locations. Please provide custom SQLite path.",
                        "searched_paths": candidate_paths
                    }
                })
                return

            imported_count = 0
            updated_count = 0
            try:
                conn = sqlite3.connect(f"file:{found_db}?mode=ro", uri=True)
                cursor = conn.cursor()
                rows = cursor.execute("SELECT email, data FROM providerConnections WHERE provider = 'antigravity'").fetchall()
                
                existing_emails = {a.email: a for a in ACCOUNT_STATES}
                for email, data_str in rows:
                    if not email: continue
                    try:
                        conn_data = json.loads(data_str) if isinstance(data_str, str) else {}
                        rt = conn_data.get("refreshToken")
                        if not rt: continue

                        if email in existing_emails:
                            existing_emails[email].refresh_token = rt
                            updated_count += 1
                        else:
                            acc_obj = AccountState({"email": email, "refresh_token": rt, "disabled": False})
                            ACCOUNT_STATES.append(acc_obj)
                            imported_count += 1
                    except Exception: pass
                conn.close()

                # Save to config.json and remember path
                CONFIG["router_db_path"] = found_db
                _save_accounts()
                log_event("INFO", f"Imported {imported_count} new accounts ({updated_count} updated) from 9router at {found_db}")
                self._send_json(200, {
                    "success": True,
                    "imported": imported_count,
                    "updated": updated_count,
                    "db_path": found_db,
                    "total_accounts": len(ACCOUNT_STATES)
                })
            except Exception as e:
                self._send_json(500, {"error": {"message": f"Failed to read 9router database: {str(e)}"}})
            return
            body_raw, _ = self._read_body(64 * 1024)
            name = "API Key"
            if body_raw:
                try:
                    req_data = json.loads(body_raw)
                    name = req_data.get("name", "API Key").strip() or "API Key"
                except Exception: pass
            new_key = "ag-proxy-" + secrets.token_hex(16)
            new_entry = {
                "id": f"key-{int(time.time()*1000)}",
                "name": name,
                "key": new_key,
                "created": int(time.time())
            }
            API_KEYS.append(new_entry)
            _save_api_keys()
            log_event("INFO", f"Created new API key: {name}")
            self._send_json(200, {"success": True, "api_key": new_key, "entry": new_entry, "api_keys": API_KEYS})
            return

        if self.path == "/v1/api-keys/delete":
            body_raw, err = self._read_body(64 * 1024)
            if err or not body_raw:
                self._send_json(400, {"error": {"message": err or "Missing request body"}})
                return
            try:
                req_data = json.loads(body_raw)
                target_key = req_data.get("key", "").strip()
                target_id = req_data.get("id", "").strip()
                
                initial_len = len(API_KEYS)
                API_KEYS = [k for k in API_KEYS if (k["key"] != target_key and k["id"] != target_id)]
                if len(API_KEYS) < initial_len:
                    _save_api_keys()
                    log_event("INFO", f"Deleted API key: {target_id or target_key[:12]}")
                    self._send_json(200, {"success": True, "api_keys": API_KEYS})
                else:
                    self._send_json(404, {"error": {"message": "Key not found"}})
            except Exception as e:
                self._send_json(400, {"error": {"message": f"Invalid request: {e}"}})
            return

        if self.path == "/v1/accounts/add":
            body_raw, err = self._read_body(64 * 1024)
            if err:
                self._send_json(413, {"error": {"message": err}})
                return
            try:
                req = json.loads(body_raw)
                email = req.get("email", "").strip()
                refresh_token = req.get("refresh_token", "").strip()
                if not email or not refresh_token:
                    self._send_json(400, {"error": {"message": "email and refresh_token are required"}})
                    return
                # Basic email format validation
                if "@" not in email or len(email) > 320:
                    self._send_json(400, {"error": {"message": "Invalid email format"}})
                    return
                # Reject control chars / HTML in email (defense in depth)
                if any(ord(c) < 32 for c in email) or "<" in email or ">" in email:
                    self._send_json(400, {"error": {"message": "Email contains forbidden characters"}})
                    return
            except Exception:
                self._send_json(400, {"error": {"message": "Invalid JSON"}})
                return
            add_account_to_pool(email, refresh_token)
            self._send_json(200, {"ok": True, "email": email, "total": len(ACCOUNT_STATES)})
            return

        if self.path == "/v1/accounts/remove":
            body_raw, err = self._read_body(64 * 1024)
            if err:
                self._send_json(413, {"error": {"message": err}})
                return
            try:
                req = json.loads(body_raw)
                email = req.get("email", "")
            except Exception:
                self._send_json(400, {"error": {"message": "Invalid JSON"}})
                return
            if remove_account_from_pool(email):
                self._send_json(200, {"ok": True, "removed": email})
            else:
                self._send_json(404, {"error": {"message": "Not found"}})
            return

        if self.path == "/v1/accounts/toggle":
            body_raw, err = self._read_body(64 * 1024)
            if err:
                self._send_json(413, {"error": {"message": err}})
                return
            try:
                req = json.loads(body_raw)
                email = req.get("email", "")
            except Exception:
                self._send_json(400, {"error": {"message": "Invalid JSON"}})
                return
            target_acc = None
            for acc in ACCOUNT_STATES:
                if acc.email == email:
                    acc.disabled = not acc.disabled
                    target_acc = acc
                    break
            if target_acc:
                for c_acc in CONFIG.get("accounts", []):
                    if c_acc.get("email") == email:
                        c_acc["disabled"] = target_acc.disabled
                        _save_accounts()
                        break
                self._send_json(200, {"ok": True, "email": email, "disabled": target_acc.disabled})
            else:
                self._send_json(404, {"error": {"message": "Not found"}})
            return

        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": {"message": "Not found"}})
            return

        body_raw, err = self._read_body()
        if err:
            self._send_json(413, {"error": {"message": err}})
            return
        try:
            body = json.loads(body_raw)
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"message": "Invalid JSON"}})
            return

        model = body.get("model", "gemini-3-flash")
        stream = body.get("stream", False)
        request_id = f"chatcmpl-{int(time.time()*1000)}"
        usage_start = time.time()  # for usage stats; never affects the request
        print(f"\n[REQ] model={model} stream={stream} msgs={len(body.get('messages',[]))} keys={sorted(body.keys())}")
        # NOTE: debug dump ke /tmp/last_req.json DIHAPUS — request body bisa
        # berisi data sensitif (prompt, tool calls). Enable via env DEBUG_DUMP=1.
        if os.environ.get("DEBUG_DUMP") == "1":
            try:
                with open("/tmp/last_req.json", "w") as _f:
                    json.dump(body, _f, indent=1)
            except Exception:
                pass
        ag_body, ag_stream = openai_to_antigravity(body)

        excluded_email = None
        for attempt in range(MAX_RETRIES):
            if STRATEGY == "sticky" and excluded_email:
                account = get_fallback_account(excluded_email)
            else:
                account = get_next_account()
            if not account:
                self._send_json(503, {"error": {"message": "No active accounts"}})
                return
            try:
                token = account.get_token()
                account.request_count += 1
            except:
                continue
            print(f"  [ACC] {account.email} (attempt {attempt+1})")
            track_start(request_id, model, account.email)
            ag_body_json = json.dumps(ag_body).encode()
            req = urllib.request.Request(API_ENDPOINT, data=ag_body_json,
                headers={"Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "User-Agent": "antigravity/ide/2.1.1 darwin/arm64"})
            try:
                resp = urllib.request.urlopen(req, timeout=300)
                # Auto-clear error state on successful connection
                account.error_count = 0
                account.last_error = None
            except urllib.error.HTTPError as e:
                err_body = e.read().decode()
                account.error_count += 1
                account.last_error = f"HTTP {e.code}: {err_body[:500]}"
                print(f"  [ERR] {account.email}: {account.last_error}")
                log_event("ERR", f"{account.email}: {account.last_error}")
                if e.code == 401:
                    account.access_token = None
                    account.expires_at = 0
                elif e.code == 429:
                    account.rate_limited_until = time.time() + 300
                    log_event("WARN", f"Account {account.email} RATE LIMITED (429) - cooldown 5 min, switching account")
                    excluded_email = account.email
                    continue
                else:
                    excluded_email = account.email
                    continue
            except Exception as e:
                account.error_count += 1
                account.last_error = str(e)
                continue

            if stream:
                self._handle_stream(resp, model, request_id, account, usage_start)
            else:
                self._handle_nonstream(resp, model, request_id, account, usage_start)
            return

        last_err = account.last_error if account else "No accounts"
        track_end(request_id)
        record_usage(model, 0, 0, 0, "error", (time.time() - usage_start) * 1000)
        self._send_json(502, {"error": {"message": f"All {MAX_RETRIES} attempts failed. Last: {last_err}"}})

    def _handle_nonstream(self, resp, model, request_id, account, started=0.0):
        raw = resp.read().decode()
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                # Merge all chunks into one consolidated response
                data = self._merge_chunks(data)
            if "error" in data:
                track_end(request_id)
                record_usage(model, 0, 0, 0, "error", (time.time() - started) * 1000)
                self._send_json(502, {"error": {"message": f"Antigravity: {data['error'].get('message','?')}"}})
                return
            openai_resp = antigravity_to_openai(data, model, request_id)
            try:
                um = data.get("response", {}).get("usageMetadata", {})
                record_usage(model, um.get("promptTokenCount", 0), um.get("candidatesTokenCount", 0),
                             um.get("cachedContentTokenCount", 0), "ok", (time.time() - started) * 1000)
            except Exception:
                pass  # usage is additive; never fail the response
            log_event("INFO", f"✅ {model} via {account.email} → {openai_resp['usage']['total_tokens']} tokens")
            self._send_json(200, openai_resp, account_email=account.email)
            track_end(request_id)
            print(f"  [OK] {account.email} → {openai_resp['usage']['total_tokens']} tokens")
        except Exception as e:
            track_end(request_id)
            record_usage(model, 0, 0, 0, "error", (time.time() - started) * 1000)
            self._send_json(500, {"error": {"message": f"Parse error: {e}"}})

    def _merge_chunks(self, chunks):
        """Merge a list of Antigravity response chunks into a single response."""
        if not chunks:
            return {}
        if len(chunks) == 1:
            return chunks[0]
        merged_parts = []
        usage = {}
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            if "error" in chunk:
                return chunk
            resp = chunk.get("response", {})
            for cand in resp.get("candidates", []):
                merged_parts.extend(cand.get("content", {}).get("parts", []))
            if resp.get("usageMetadata"):
                usage = resp["usageMetadata"]
        return {"response": {"candidates": [{"content": {"parts": merged_parts}, "finishReason": "STOP"}], "usageMetadata": usage}}

    def _handle_stream(self, resp, model, request_id, account, started=0.0):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.close_connection = True
        if account:
            self.send_header("X-Account-Used", account.email)
        self.end_headers()
        track_streaming(request_id)
        state = {}
        buffer = ""
        try:
            for line in resp:
                buffer += line.decode()
                while buffer:
                    try:
                        data = json.loads(buffer)
                        if isinstance(data, list):
                            for chunk_data in data:
                                openai_chunk = antigravity_chunk_to_openai(chunk_data, model, request_id, state)
                                if openai_chunk:
                                    self.wfile.write(f"data: {json.dumps(openai_chunk)}\n\n".encode())
                                    self.wfile.flush()
                            buffer = ""
                            break
                        else:
                            break
                    except json.JSONDecodeError:
                        break
            final = {"id": request_id, "object": "chat.completion.chunk", "created": int(time.time()),
                "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            um = state.get("usage", {})
            if um:
                final["usage"] = {
                    "prompt_tokens": um.get("promptTokenCount", 0),
                    "completion_tokens": um.get("candidatesTokenCount", 0),
                    "total_tokens": um.get("totalTokenCount", 0),
                    "reasoning_tokens": um.get("thoughtsTokenCount", 0),
                    "prompt_tokens_details": {
                        "cached_tokens": um.get("cachedContentTokenCount", 0)
                    }
                }
            self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            # Usage arrives in the final chunk (usageMetadata, no candidates)
            try:
                record_usage(model, um.get("promptTokenCount", 0), um.get("candidatesTokenCount", 0),
                             um.get("cachedContentTokenCount", 0), "ok", (time.time() - started) * 1000)
            except Exception:
                pass  # usage is additive; never fail the response
            log_event("INFO", f"STREAM {model} via {account.email} done")
            print(f"  [OK] {account.email} -> stream done")
        except Exception as e:
            record_usage(model, 0, 0, 0, "error", (time.time() - started) * 1000)
            err_chunk = {"id": request_id, "object": "chat.completion.chunk", "created": int(time.time()),
                "model": model, "choices": [{"index": 0, "delta": {"content": f"\n[Proxy Error: {e}]"}, "finish_reason": "stop"}]}
            try:
                self.wfile.write(f"data: {json.dumps(err_chunk)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except Exception:
                pass
        finally:
            track_end(request_id)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Antigravity Multi-Account Proxy v2")
    print("=" * 60)
    print(f"  Port: {PORT} | Strategy: {STRATEGY}")
    print(f"  Accounts: {len(ACCOUNTS)} | Models: {len(MODEL_MAP)}")
    for a in ACCOUNTS:
        print(f"    - {a['email']}")
    print(f"  Dashboard: {'password protected' if DASHBOARD_PASSWORD else 'OPEN (no password!)'}")
    print("=" * 60)
    print("\n[INIT] Pre-refreshing tokens...")
    for acc in ACCOUNT_STATES:
        if acc.disabled:
            print(f"  [DISABLED] {acc.email}: disabled (token still refreshed)")
        try:
            acc.get_token()
            acc.fetch_quota()
            print(f"  [READY] {acc.email}: token + quota OK")
        except:
            print(f"  [FAIL] {acc.email}: failed")
    # Background quota refresh every 5 min
    def _quota_loop():
        while True:
            time.sleep(300)
            for acc in ACCOUNT_STATES:
                if not acc.disabled:
                    acc.fetch_quota()
    threading.Thread(target=_quota_loop, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), ProxyHandler)
    server.daemon_threads = True
    print(f"\n[SERVER] Listening on {HOST}:{PORT}")
    print(f"[SERVER] Dashboard: http://localhost:{PORT}/")
    print(f"[SERVER] API: http://localhost:{PORT}/v1/chat/completions")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down...")
        server.server_close()


if __name__ == "__main__":
    main()
