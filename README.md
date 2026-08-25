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
  "accounts": []
}
```

Host configuration:
- Use `"host": "0.0.0.0"` if running on a VPS or container to allow external or subdomain access.
- Use `"host": "127.0.0.1"` if running exclusively on your local machine.

Edit `.env` and set your credentials:

```env
AG_PROXY_API_KEY=your_generated_api_key
AG_DASHBOARD_USER=admin
AG_DASHBOARD_PASSWORD=your_secure_password
```

Generate an API key with `openssl rand -hex 16`.

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

## Adding Accounts

### Option 1: Fast Migration from 9router (Recommended if using 9router)

If you already logged into Google AI Pro accounts via 9router:

1. Open 9router database (`data.sqlite`).
2. Query `providerConnections` where `provider = 'antigravity'`.
3. Extract `email` and `refreshToken` and paste into `config.json` under `accounts`.
4. Alternatively, instruct an AI agent to copy tokens directly from the database into `config.json`.

### Option 2: Dashboard UI Entry

1. Open dashboard (`http://localhost:20130` or `http://YOUR-SERVER-IP:20130`).
2. Click **Add Account**.
3. Enter **Email** and **Refresh Token** then click **Add**.

Tokens refresh automatically in the background every 5 minutes.

### Option 3: Google OAuth Web Login (`oauth_helper.py`)

When `OAUTH_*` credentials are configured in `.env`:

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
| `gemini-3.7-flash-high` | `gemini-3.7-flash-tiered` |
| `gemini-3.7-flash-medium` | `gemini-3.7-flash-tiered` |
| `gemini-3.6-flash-high` | `gemini-3.6-flash-high` |
| `gemini-3.1-pro-high` | `gemini-pro-agent` |
| `claude-sonnet-4-6-thinking` | `claude-sonnet-4-6` |
| `claude-opus-4-6-thinking` | `claude-opus-4-6-thinking` |

## License

MIT License
