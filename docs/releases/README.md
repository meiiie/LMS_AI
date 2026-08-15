# Wiii releases

This directory defines how Wiii becomes a verifiable product release. Start
with the [release standard](WIII_RELEASE_STANDARD.md); use `CHANGELOG.md` for
human-facing release notes and `VERSION` for the current version.

## Release surfaces

| Surface | Source | Purpose |
| --- | --- | --- |
| Version | `VERSION` | Single source of truth |
| History | `CHANGELOG.md` | User-visible changes and migration notes |
| Automation | `tools/release/wiii_release.py` | Synchronization, notes, hashes, manifest |
| CI/CD | `.github/workflows/release-desktop.yml` | Windows, Linux, and macOS candidate builds plus stable publication |
| Bundle normalization | `tools/release/normalize_desktop_bundle.py` | Exact package discovery, public names, checksums, and per-target manifests |
| Publication verification | `tools/release/verify_desktop_release.py` | Exact inventory, checksum, manifest, version, and commit validation before attestation |
| Runtime confidence | `tools/wiii_self_harness/` | Repository and evidence contracts |

The governed desktop matrix covers Windows x64, Linux x64, macOS Apple Silicon,
and macOS Intel. macOS files remain visibly marked `unnotarized` until The Wiii
Lab provisions Apple signing and notarization credentials. Backend and web
deployments retain their own operational promotion gates, but use the same Wiii
version whenever they are included in a coordinated public release.

Normal stable publication requires the complete matrix. The release standard
defines a protected, disclosed Windows-only break-glass path for a confirmed
hosted-runner outage affecting a time-critical security release.
