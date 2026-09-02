# Cloudflare WARP Setup for ag-proxy (Geo-restriction Fix)

If your VPS IP is geo-blocked by Google Cloud Code API with the error:
`HTTP 400: User location is not supported for the API use (FAILED_PRECONDITION)`

You can route only Google API requests through Cloudflare WARP via local SOCKS5 proxy on `127.0.0.1:40000`.

---

## 🚀 Quick Setup (Ubuntu / Debian ARM64 & AMD64)

### 1. Install Cloudflare WARP Client
```bash
# Add Cloudflare GPG Key & Repository
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | sudo gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ bookworm main" | sudo tee /etc/apt/sources.list.d/cloudflare-client.list

# Update and install
sudo apt-get update -qq
sudo apt-get install -y -qq cloudflare-warp expect
```

### 2. Register & Connect in Proxy Mode
```bash
# Register with automatic Terms of Service acceptance
sudo expect -c '
spawn warp-cli registration new
expect {
    "Accept Terms" { send "y\r"; exp_continue }
    "y/N" { send "y\r"; exp_continue }
    eof
}
'

# Set to Proxy mode (port 40000) and Connect
sudo warp-cli mode proxy
sudo expect -c '
spawn warp-cli connect
expect {
    "Terms" { send "y\r"; exp_continue }
    "y/N" { send "y\r"; exp_continue }
    eof
}
'

# Verify status
sudo warp-cli status
```

### 3. Enable in `ag-proxy`
`ag-proxy` automatically detects and routes Google API traffic through `127.0.0.1:40000` when WARP is active.

Make sure dependencies are installed:
```bash
pip install PySocks
sudo systemctl restart ag-proxy
```

---

## 🛡️ Privacy & Isolation Guarantees

* **SOCKS5 Proxy Only (`127.0.0.1:40000`):** WARP does **NOT** touch your VPS default network route.
* **Targeted Routing:** Only outbound HTTPS requests matching `*.googleapis.com` are forwarded.
* **100% Local Services:** RustDesk, WireGuard, SSH, databases, and other apps continue using your server's native IP without going through WARP.
* **End-to-End Encrypted:** Google API traffic remains encrypted with TLS 1.3 directly to Google servers. Cloudflare cannot read prompts or credentials.

---

## 🔧 Troubleshooting

### Check WARP Status
```bash
sudo warp-cli status
```

### Test Outbound IP through WARP
```bash
curl -s --socks5 127.0.0.1:40000 https://ifconfig.me
```

### Restart Service
```bash
sudo warp-cli disconnect
sudo warp-cli connect
sudo systemctl restart ag-proxy
```
