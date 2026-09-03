# CHANGELOG

All notable changes to `antigravity-proxy-v2` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.1.1] - 2026-09-02

### Added
- **1-Click & Fallback 9router Importer:** Web UI button to scan default 9router SQLite database paths, with manual prompt fallback that auto-saves verified paths to `config.json` (`router_db_path`).
- **Cloudflare WARP SOCKS5 Routing Support:** Outbound proxy routing support for upstream API calls (`WARP_ENABLED` flag in `server.py`).
- **Setup Documentation:** Added standalone `WARP_SETUP.md` for geo-restriction troubleshooting.
- **Auto-Reset Account Error State:** Successfully processed requests automatically clear account error badges and reset failure counters.
- **Full Error Modal Inspection:** Clickable error badges on account cards to inspect full response bodies.

### Changed
- **UI Design System Upgrade:** Clean Deep Ocean dark theme (`#07090e` base, `#0d111a` card surface, solid `#0284c7` buttons) replacing legacy gradients.
- **Documentation Cleanup:** Streamlined `README.md` with concise 3-method account setup guide and removed redundant formatting.

---

## [2.1.0] - 2026-09-02

### Added
- **Multi-API Key Management:** Generate and revoke client API keys via `/v1/api-keys` endpoints and dashboard UI.
- **Session-Based Authentication:** Replaced basic auth with standalone `login.html` and secure `HttpOnly` session cookies.

---

## [2.0.0] - 2026-08-20

### Added
- Initial v2 release featuring multi-account pool aggregation, quota tracking via `fetchAvailableModels`, round-robin/sticky routing, and web dashboard.
