# Cloudflare WARP Setup (Geo-restriction Fix)

If you encounter the following error when making requests:
```
HTTP 400: User location is not supported for the API use (FAILED_PRECONDITION)
```

This indicates your server's IP region is currently restricted by the upstream API. You can resolve this by routing API requests through Cloudflare WARP in local proxy mode.

---

## 🚀 Quick Setup (Ubuntu / Debian)

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
`ag-proxy` automatically detects and routes API traffic through `127.0.0.1:40000` when WARP is active.

Make sure dependencies are installed:
```bash
pip install PySocks
sudo systemctl restart ag-proxy
```

---

## 🔧 Troubleshooting

### Check WARP Status
```bash
sudo warp-cli status
```

### Restart Service
```bash
sudo warp-cli disconnect
sudo warp-cli connect
sudo systemctl restart ag-proxy
```
