# 🚀 Antigravity Multi-Account Proxy

Lightweight Python proxy (100% standard library, zero external dependencies) for **Google AI Pro / Antigravity**.

## Core Features

- 🔄 **Multi-Account Round-Robin & Sticky Failover** — Automatic rotation across Google AI Pro accounts.
- ⚡ **Auto-Failover on Rate Limits (429)** — Account hit 429 → 5-minute cooldown → Request rerouted to next available account.
- 🧠 **OpenAI Compatible API** — `/v1/chat/completions` endpoint supporting Hermes, OpenWebUI, Cursor, LangChain, etc.
- 🛡️ **Zero External Dependencies** — Built exclusively with Python 3 standard library (`http.server` & `urllib`).
- 📊 **Dashboard & Usage Monitor** — Per-model quota bars, active request state, real-time log stream, and token usage analytics.
- 🔧 **Tool Use Conversion** — Converts OpenAI tool calls to Antigravity `functionCall` format with `thoughtSignature` support.

## Security Controls

- 🔑 **Secrets Isolation** — API keys, passwords, and OAuth credentials load from `.env` (git-ignored). `.env.example` provided as template.
- 🚫 **XSS & Header Protections** — Escaped dynamic strings; `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` headers.
- 🔒 **Brute-Force Protection** — 5 consecutive auth failures trigger a 15-minute IP lockout across API and dashboard endpoints.
- ⏱️ **Constant-Time Comparison** — Secret comparison uses `secrets.compare_digest` to prevent timing attacks.
- 🍪 **Secure Session Cookies** — `HttpOnly` and `SameSite=Strict` flags applied to dashboard session cookies.
- 📏 **Request Payload Limits** — 25 MB cap for chat completions, 64 KB cap for administrative endpoints.
- 🧹 **Input Sanitization** — Account emails validated against HTML/control characters to prevent injection attacks.

## Setup Instructions

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
  "accounts": []
}
```

The `accounts` array populates automatically when adding accounts via dashboard or API.

Edit `.env` and set your credentials (generate API key with `openssl rand -hex 16`):

```env
AG_PROXY_API_KEY=your_generated_api_key
AG_DASHBOARD_USER=admin
AG_DASHBOARD_PASSWORD=your_secure_password
```

> **Optional OAuth Setup:** If you want web-based Google OAuth authentication (similar to 9router), fill in `OAUTH_ACCESS_KEY`, `OAUTH_SECRET_KEY`, and `OAUTH_REDIRECT_URI` in `.env`. If left empty, manual refresh token addition remains fully functional.

### 3. Deploy Systemd Service

```bash
sudo cp ag-proxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ag-proxy
```

Verify service status:

```bash
sudo systemctl status ag-proxy
```

Access dashboard at `http://YOUR-SERVER-IP:20130` using the Basic Auth credentials set in `.env`.

## Adding Accounts

### Option A: Direct Refresh Token Entry (Recommended)

1. Obtain a Google OAuth `refresh_token` from your laptop or existing configuration.
2. Open dashboard (`http://YOUR-SERVER-IP:20130`) → **➕ Add Account**.
3. Enter **Email** & **Refresh Token** → click **Add**.

Tokens refresh automatically background every ~5 minutes.

### Option B: Google OAuth Web Login (`oauth_helper.py`)

When `OAUTH_*` credentials are configured in `.env`:

```bash
# Run local loopback helper on VPS
python3 oauth_helper.py
```

Forward port 8085 via SSH tunnel from your laptop:

```bash
ssh -L 8085:localhost:8085 user@your-vps-ip
```

Open `http://localhost:8085/login` in your local browser to authenticate with Google. Refresh tokens add directly to the pool upon success.

## Rotation Strategies

| Strategy | Description |
|---|---|
| `round-robin` | Distributes requests sequentially across all active accounts. |
| `sticky` | Locks to a single account until rate-limited (429), then switches to next account. |

Switch modes anytime via the dashboard control panel.

## Supported Models

| Model Name | Upstream Target |
|---|---|
| `gemini-3.7-flash-high` | `gemini-3.7-flash-high` |
| `gemini-3.6-flash-high` | `gemini-3.6-flash-high` |
| `gemini-3.6-flash-tiered` | `gemini-3.6-flash-tiered` |
| `gemini-3.1-pro-high` | `gemini-pro-agent` |
| `claude-sonnet-4-6-thinking` | `claude-sonnet-4-6` |
| `claude-opus-4-6-thinking` | `claude-opus-4-6-thinking` |

## License

MIT License
