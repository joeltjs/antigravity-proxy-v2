# Antigravity Multi-Account Proxy

Lightweight Python proxy (100% standard library, zero external dependencies) for Google AI Pro and Antigravity.

Designed for local development machines and remote server environments.

## Core Features

- Multi-Account Round-Robin and Sticky Failover: Automatic rotation across Google AI Pro accounts.
- Auto-Failover on Rate Limits (429): If an account hits 429, a 5-minute cooldown is applied and requests reroute to the next available account.
- OpenAI Compatible API: `/v1/chat/completions` endpoint supporting Hermes, OpenWebUI, Cursor, Cline, Kilo, LangChain, etc.
- Zero External Dependencies: Built exclusively with Python 3 standard library (`http.server` and `urllib`).
- Dashboard and Usage Monitor: Per-model quota bars, active request indicators, real-time log stream, and token usage analytics.
- Tool Use Conversion: Converts OpenAI tool calls to Antigravity `functionCall` format with `thoughtSignature` support.

## Security Controls

- Secrets Isolation: API keys, passwords, and OAuth credentials load from `.env` (git-ignored). `.env.example` provided as template.
- XSS and Header Protections: Escaped dynamic strings, `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.
- Brute-Force Protection: 5 consecutive auth failures trigger a 15-minute IP lockout across API and dashboard endpoints.
- Constant-Time Comparison: Secret comparison uses `secrets.compare_digest` to prevent timing attacks.
- Secure Session Cookies: `HttpOnly` and `SameSite=Strict` flags applied to dashboard session cookies.
- Request Payload Limits: 25 MB cap for chat completions, 64 KB cap for administrative endpoints.
- Input Sanitization: Account emails validated against HTML and control characters to prevent injection attacks.

## Setup Instructions

Works on local environments (macOS, Linux, WSL, Windows) and remote VPS setups.

### 1. Clone Repository

```bash
git clone https://github.com/joeltjs/antigravity-proxy-v2.git
cd antigravity-proxy-v2
```

### 2. Configure Environment

Copy template files:

```bash
cp config.example.json config.json
cp .env.example .env
```

Edit `config.json`:

```json
{
  "port": 20130,
  "host": "0.0.0.0",
  "strategy": "round-robin",
  "api_key": "your_generated_api_key",
  "accounts": []
}
```

Host configuration:
- Use `"host": "0.0.0.0"` if running on a VPS or container to allow external or subdomain access.
- Use `"host": "127.0.0.1"` if running exclusively on your local machine.

Generate an API key with `openssl rand -hex 16` or use the dashboard endpoint `POST /v1/api-key/generate`.

Edit `.env` for dashboard basic auth credentials:

```env
AG_DASHBOARD_USER=admin
AG_DASHBOARD_PASSWORD=your_secure_password
```

### 3. Run the Proxy

**Option A: Local Development / Manual Execution**

```bash
python3 server.py
```

Access the dashboard at `http://localhost:20130` (or `http://YOUR-SERVER-IP:20130` if on remote host).

**Option B: Systemd Service (Linux / VPS)**

```bash
sudo cp ag-proxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ag-proxy
```

Verify service status:

```bash
sudo systemctl status ag-proxy
```

## How to Get Refresh Tokens & Add Accounts

Google Antigravity/CloudCode uses official developer OAuth scopes. You do **not** need to enable private Google APIs in your GCP Console. Use any of the verified methods below:

### Method 1: Fast Migration from 9router (Recommended if you use 9router)

If you already authenticated Google accounts in 9router:

1. Open 9router SQLite database (`data.sqlite`).
2. Query `providerConnections` where `provider = 'antigravity'`.
3. Extract `email` and `refreshToken` and paste directly into `config.json` under `accounts`.
4. Alternatively, use an AI agent or migration script to automate copying.

### Method 2: Official Google OAuth Consent (Standard Flow)

1. Obtain a valid Google OAuth `refresh_token` using official Antigravity/CloudCode client credentials.
2. Open your dashboard (`http://localhost:20130` or `http://YOUR-SERVER-IP:20130`).
3. Click **Add Account**.
4. Enter **Email** and **Refresh Token**, then click **Add**.

Tokens refresh automatically in the background every 5 minutes.

### Method 3: Web-Based OAuth Helper (`oauth_helper.py`)

If you have configured custom Google OAuth credentials in `.env` (`OAUTH_ACCESS_KEY`, `OAUTH_SECRET_KEY`, `OAUTH_REDIRECT_URI`):

```bash
python3 oauth_helper.py
```

Forward port 8085 if running remotely:

```bash
ssh -L 8085:localhost:8085 user@your-vps-ip
```

Open `http://localhost:8085/login` in your local browser to authenticate with Google.

## Rotation Strategies

| Strategy | Description |
|---|---|
| `round-robin` | Distributes requests sequentially across all active accounts. |
| `sticky` | Locks to a single account until rate-limited (429), then switches to next account. |

## Supported Models

| Model Name | Upstream Target |
|---|---|
| `gemini-3.7-flash-high` | `gemini-3.7-flash-high` |
| `gemini-3.7-flash-tiered` | `gemini-3.7-flash-tiered` |
| `gemini-3.6-flash-high` | `gemini-3.6-flash-high` |
| `gemini-3.1-pro-high` | `gemini-pro-agent` |
| `claude-sonnet-4-6-thinking` | `claude-sonnet-4-6` |
| `claude-opus-4-6-thinking` | `claude-opus-4-6-thinking` |

## Troubleshooting & Geo-restriction Fix

### 1. `HTTP 400: User location is not supported for the API use`
This error occurs when the server's IP region is restricted by the upstream API.

**Solution:** Route API requests through Cloudflare WARP SOCKS5 proxy.
👉 See setup guide: [`WARP_SETUP.md`](WARP_SETUP.md)

---

### 2. How to Import Accounts from 9router (Zero-Config)
If you already use 9router, you can easily copy your refresh tokens:
1. Open **9router Web UI** ➔ Go to **Settings** (`/settings`).
2. Check the **Local Mode** section at the top to view your SQLite database path (default: `~/.9router/db/data.sqlite` or `/app/data/db/data.sqlite` in Docker).
3. Copy the `refreshToken` entries under `providerConnections` where `provider = 'antigravity'` into `config.json`'s `accounts` list.

---

## License

MIT License
