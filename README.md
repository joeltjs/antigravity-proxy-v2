# 🚀 Antigravity Multi-Account Proxy

Proxy lightweight Python (100% standard library, tanpa dependensi eksternal) untuk **Google AI Pro / Antigravity**.

## Fitur Utama

- 🔄 **Multi-Account Round-Robin & Sticky Failover** — rotasi otomatis antar akun Google AI Pro.
- ⚡ **Auto-Failover 429 / Rate Limit** — akun kena 429 → cooldown 5 menit → request otomatis dilempar ke akun lain.
- 🧠 **OpenAI Compatible API** — format `/v1/chat/completions` yang kompatibel dengan Hermes, OpenWebUI, Cursor, LangChain, dll.
- 🛡️ **Zero Dependencies** — murni `http.server` & `urllib` bawaan Python 3.
- 📊 **Dashboard UI** — kuota per model, status token, live log konsol, indikator request aktif (model + akun yang sedang konsumsi token), toggle strategi rotasi.
- 🔧 **Tool Use Conversion** — konversi otomatis tool calls OpenAI → Antigravity `functionCall` dengan `thoughtSignature` & `functionResponse`.

## Keamanan (Hardened)

- 🔑 **Semua secret di `.env`** — API key, password dashboard, dan OAuth credentials tidak pernah masuk git (`.env` di-gitignore; `.env.example` sebagai template).
- 🚫 **Anti-XSS** — semua data dinamis di dashboard di-escape; server mengirim `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.
- 🔒 **Anti-Brute-Force** — 5x gagal auth → IP lockout 15 menit (berlaku untuk API key & dashboard login).
- ⏱️ **Constant-Time Comparison** — perbandingan secret pakai `secrets.compare_digest` (anti timing attack).
- 🍪 **Session Cookie httpOnly + SameSite=Strict** — dashboard browser tidak menyimpan secret di JavaScript/localStorage; cookie tidak bisa dibaca JS.
- 📏 **Request Body Limit** — 25 MB untuk chat, 64 KB untuk endpoint admin (anti DoS).
- 🧹 **Input Validation** — email akun divalidasi & ditolak jika mengandung karakter kontrol/HTML (anti injection).
- 🌐 **Error Sanitization** — error internal tidak pernah dibocorkan ke client.

## Instalasi (VPS / Server)

### 1. Clone repo

```bash
git clone https://github.com/joeltjs/antigravity-proxy-v2.git
cd antigravity-proxy-v2
```

### 2. Buat file konfigurasi

Salin template, lalu isi:

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

`accounts` mulai kosong — diisi otomatis saat kamu menambah akun (Cara A/B di bawah).
Setiap entry berbentuk `{ "email": ..., "refresh_token": ..., "disabled": false }`.
**Jangan pernah commit `config.json`** — sama seperti `.env`, file ini berisi secret.

Edit `.env` — isi secret kamu sendiri (generate API key: `openssl rand -hex 16`):

```env
AG_PROXY_API_KEY=***
AG_DASHBOARD_USER=admin
AG_DASHBOARD_PASSWORD=your-d…here
OAUTH_ACCESS_KEY=your-o…here
OAUTH_SECRET_KEY=your-o…here
```

> ⚠️ **Jangan pernah commit `.env`.** File `.gitignore` sudah melindungi, tapi selalu cek `git status` sebelum push.

### 3. Pasang systemd service

```bash
sudo cp ag-proxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ag-proxy
```

Cek status:

```bash
sudo systemctl status ag-proxy
```

Akses dashboard: `http://IP-VPS-KAMU:20130` — login dengan user & password dari `.env`.

## Integrasi Hermes

### 1. Custom provider di `~/.hermes/config.yaml`

```yaml
custom_providers:
  - name: ag-proxy
    base_url: http://localhost:20130/v1
    key_env: AG_PROXY_API_KEY
    models:
      - gemini-3.6-flash-high
      - gemini-3.6-flash-tiered
      - gemini-3.1-pro-high
      - claude-sonnet-4-6-thinking
      - claude-opus-4-6-thinking
```

### 2. API key di `~/.hermes/.env`

```env
AG_PROXY_API_KEY=*** AG_PROXY_API_KEY dari .env proxy>
```

### 3. Pakai model

```bash
hermes model ag2/gemini-3.6-flash-high
```

## Cara Tambah Akun

### CARA A: Manual via Refresh Token (paling mudah)

1. Ambil `refresh_token` dari database/log 9router atau OAuth flow di laptop.
2. Buka dashboard `http://IP-VPS:20130` → **➕ Add Account**.
3. Masukkan **Email** & **Refresh Token** → klik **Tambah**.

Token akan di-refresh otomatis setiap ~1 jam.

### CARA B: Google OAuth Login (via `oauth_helper.py`)

Google menolak redirect URI non-loopback untuk OAuth client Antigravity, jadi
login lewat browser hanya bisa dari **localhost** (SSH tunnel):

```bash
# Dari laptop kamu:
ssh -L 8085:localhost:8085 user@ip-vps-kamu
# Di VPS:
python3 oauth_helper.py
# Buka di browser laptop: http://localhost:8085/login
# Login Google → token otomatis masuk ke pool proxy
```

Ulangi untuk setiap akun. Refresh token tidak pernah meninggalkan VPS.

## Strategi Rotasi

| Strategi | Deskripsi |
|---|---|
| `round-robin` | Ganti akun setiap request secara bergiliran. |
| `sticky` | Pakai 1 akun sampai kena 429/limit, lalu pindah ke akun lain (cooldown 5 menit). |

Ganti kapan saja via tombol **🔀 Ganti Mode** di dashboard.

## Model yang Didukung

| Nama Model | Upstream Antigravity |
|---|---|
| `gemini-3.6-flash-high` | `gemini-3.6-flash-high` |
| `gemini-3.6-flash-tiered` | `gemini-3.6-flash-tiered` |
| `gemini-3.1-pro-high` | `gemini-pro-agent` |
| `claude-sonnet-4-6-thinking` | `claude-sonnet-4-6` |
| `claude-opus-4-6-thinking` | `claude-opus-4-6-thinking` |

> Kuota Antigravity bersifat **shared pool per keluarga model** (pool Gemini & pool Claude), bukan per nama model.

## Lisensi

MIT License — bebas digunakan & dimodifikasi.
