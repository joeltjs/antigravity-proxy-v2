# Antigravity Multi-Account Proxy v2.1.1

![Version](https://img.shields.io/badge/version-2.1.1-0284c7)
![License](https://img.shields.io/badge/license-MIT-green)

OpenAI-compatible reverse proxy that aggregates multiple Google Antigravity accounts into a single load-balanced endpoint with automatic rate-limit failover, quota tracking, session authentication, and multi-API key support.

---

## Features

- Multi-Account Aggregation: Pool multiple Google AI accounts into a single unified endpoint.
- Auto-Failover on Rate Limits (429): Applies a 5-minute cooldown and seamlessly reroutes to available accounts.
- Multiple API Keys Management: Generate and revoke client API keys (/v1/api-keys) directly via dashboard.
- Secure Web Dashboard: Real-time quota metrics, usage counters, and account controls protected by session authentication.
- WARP SOCKS5 Routing: Built-in support to route upstream API calls through local proxy when datacenter IPs are restricted.

---

## Account Setup & Import Methods

There are 3 standard ways to add accounts:

### Method 1: Import from 9router (Automatic or Manual)

- Automatic Scan:
  Click "Import 9router" in the web dashboard navigation bar. The server automatically scans default SQLite database locations:
  - `~/.9router/db/data.sqlite` (Native install)
  - `/app/data/db/data.sqlite` (Docker container)

- Manual Input (If default locations are not found):
  If the automatic scan cannot find the database, a path input prompt will appear. You can find your database location in 9router web interface:
  1. Open 9router web dashboard and click the Settings menu.
  2. In the Local Mode section at the top, copy the database path shown (e.g. `/path/to/data.sqlite`).
  3. Paste the path into the input prompt, or set `"router_db_path": "/path/to/data.sqlite"` directly in `config.json`. Once verified, the path is saved automatically for future scans.

### Method 2: OAuth 2.0 Web Authorization

Authenticate accounts directly via your browser:
1. Open the dashboard at `http://localhost:20130/`.
2. Click "Add Account via OAuth".
3. Sign in with your Google account and grant permissions.

### Method 3: Direct Refresh Token Entry

Add accounts directly into `config.json`:
```json
{
  "accounts": [
    {
      "email": "user@example.com",
      "refresh_token": "1//0g..."
    }
  ]
}
```

---

## Quick Start

### 1. Installation
```bash
git clone https://github.com/joeltjs/antigravity-proxy-v2.git
cd antigravity-proxy-v2
pip install -r requirements.txt
```

### 2. Configuration
Copy sample configuration:
```bash
cp config.example.json config.json
cp .env.example .env
```
Fill in your OAuth credentials and dashboard password in `.env`.

### 3. Run Server
```bash
python3 server.py
```
Or run as a systemd background service.

---

## Supported Models

| Model Name (OpenAI Format) | Upstream Model Mapping |
|---|---|
| `gemini-3.7-flash-high` | `gemini-2.5-flash` |
| `gemini-3.7-flash-medium` | `gemini-2.5-flash` |
| `gemini-3.6-flash-high` | `gemini-2.5-flash` |
| `claude-sonnet-4-6-thinking` | `claude-sonnet-4-6` |
| `claude-opus-4-6-thinking` | `claude-opus-4-6-thinking` |

---

## Troubleshooting & Geo-restriction

### `HTTP 400: User location is not supported for the API use`
This error occurs when the server IP region is restricted by the upstream API.
Follow the setup guide: [WARP_SETUP.md](WARP_SETUP.md)

---

## License

MIT License (c) 2026 Julian Efendi
