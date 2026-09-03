# CHANGELOG

All notable changes to `antigravity-proxy-v2` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.1.1] - 2026-09-02

### Added
- **1-Click & Fallback 9router Importer:** Web UI button to scan default 9router SQLite database paths, with manual prompt fallback that auto-saves verified paths to `config.json` (`router_db_path`).
- **Cloudflare WARP SOCKS5 Routing:** Auto-routes Google API requests (`*.googleapis.com`) via `127.0.0.1:40000` to bypass datacenter IP restrictions.
- **Dedicated Geo-restriction Guide:** Added standalone `WARP_SETUP.md` documentation.
- **Auto-Reset Error State:** Successfully processed upstream requests automatically clear account error counters and error badges.
- **Full Error Modal Inspection:** Clickable error badges with modal stacktrace view.

### Changed
- **UI Design System Upgrade:** Clean Deep Ocean theme (`#07090e` base, `#0d111a` surface, solid `#0284c7` buttons) replacing legacy gradients.
- **Documentation Cleanup:** Removed AI slop, emojis, and internal infrastructure references across all docs.

---

## [2.1.0] - 2026-09-02

### Added
- **Multi-API Key Management:** Generate and revoke client API keys via `/v1/api-keys` endpoints and dashboard UI.
- **Session-Based Authentication:** Replaced basic auth popup with standalone `login.html` and secure `HttpOnly` session cookies.

---

## [2.0.0] - 2026-08-20

### Added
- Initial v2 release featuring multi-account pool aggregation, quota tracking via `fetchAvailableModels`, round-robin/sticky routing, and web dashboard.
