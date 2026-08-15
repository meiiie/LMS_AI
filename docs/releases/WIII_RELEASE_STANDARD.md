# Wiii Release Standard

**Status:** Canonical
**Owner:** The Wiii Lab
**Version source:** `VERSION`
**Stable tag:** `wiii-v<SemVer>`

## 1. Release model

Wiii uses Semantic Versioning for the public product line:

- **MAJOR** — an intentional compatibility break in public APIs, persisted
  session formats, extension contracts, or supported upgrade paths.
- **MINOR** — a backward-compatible capability release.
- **PATCH** — a backward-compatible correction or security hardening release.
- Prereleases use SemVer suffixes such as `1.3.0-rc.1`.

`VERSION` is authoritative. The release tool checks every duplicated version
surface used by npm, Tauri, Cargo, structured metadata, splash UI, and installer
art. A release is invalid when any surface diverges.

## 2. Channels

### Candidate

A maintainer starts `Desktop Release` manually. The workflow validates and
tests the exact commit once, then builds this release matrix:

| Target | Runner | Public packages | Trust state |
| --- | --- | --- | --- |
| Windows x64 | `windows-latest` | NSIS `.exe` | Unsigned candidate |
| Linux x64 | Ubuntu 22.04 | Debian `.deb`, portable `.AppImage` | Checksummed, no platform signing |
| macOS Apple Silicon | `macos-latest`, explicit `aarch64-apple-darwin` target | `.dmg` | Ad-hoc signed, not Apple-notarized |
| macOS Intel | `macos-latest`, explicit `x86_64-apple-darwin` target | `.dmg` | Ad-hoc signed, not Apple-notarized |

Each matrix member emits professionally named packages, SHA-256 sidecars,
release notes, and a platform manifest. Candidate artifacts are internal
evaluation builds and must never be presented as a public stable release.

Ubuntu 22.04 is intentional. Tauri v2 requires WebKitGTK 4.1 and recommends
building on the oldest supported Linux baseline to avoid raising the required
glibc version. Linux ARM is outside the current release contract.

### Stable

A stable run is triggered only by a pushed `wiii-v<version>` tag. The tag must
match `VERSION` and point to the reviewed release commit. Stable Windows builds
require an Authenticode certificate and pass signature verification. Linux and
macOS packages are built from that same commit. All packages, checksums, and
manifests receive GitHub artifact provenance attestations before publication.

The current macOS packages are deliberately named `unnotarized`. Tauri applies
an ad-hoc signature so Apple Silicon can execute the application, but the files
do not carry an Apple Developer identity or notarization ticket. This is a
transparent transitional channel, not a claim of Apple trust. Users must verify
the checksum and use macOS Privacy & Security to approve the application. Do
not suggest disabling Gatekeeper globally.

The workflow expects these protected repository or environment secrets:

- `WIII_WINDOWS_CERTIFICATE_PFX_BASE64`
- `WIII_WINDOWS_CERTIFICATE_PASSWORD`

Use two GitHub environments: `candidate` contains no secrets and may run without
approval; `release` contains the signing secrets and requires human approval.
Use a code-signing certificate controlled by the project owner. Restrict the
secrets to the `release` environment, rotate before expiry, and revoke
immediately after suspected exposure. Never commit a PFX, password, private
updater key, or decoded certificate.

## 3. Required gates

Before a stable tag is created:

1. The release PR is merged with required review and checks.
2. `python tools/release/wiii_release.py check` passes.
3. `CHANGELOG.md` contains a dated, non-empty section for the version.
4. The repository harness and desktop test/build gates pass.
5. Upgrade, persistence, and rollback risks are recorded in the PR.
6. The tagged commit is the exact commit approved for release.

The stable workflow additionally verifies the tag, Windows installer
Authenticode status, the complete five-binary/four-manifest matrix, SHA-256
sidecars, JSON manifests, and GitHub provenance attestation.

## 4. Operator commands

Prepare a version on a release branch:

```powershell
python tools/release/wiii_release.py set 1.3.0
# Move CHANGELOG entries from Unreleased into a dated [1.3.0] section.
python tools/release/wiii_release.py check
```

After the release PR is merged and its commit is known:

```powershell
git switch main
git pull --ff-only
git tag -s wiii-v1.3.0 -m "Wiii 1.3.0"
git push origin wiii-v1.3.0
```

Signed tags are preferred. If the maintainer cannot use a signing key, an
annotated tag is the minimum; branch protection and the stable workflow remain
mandatory.

## 5. Artifact contract

Public desktop package names are stable and architecture-explicit:

- `Wiii-Workbench_<version>_windows-x64-setup.exe`
- `Wiii-Workbench_<version>_linux-x64.deb`
- `Wiii-Workbench_<version>_linux-x64.AppImage`
- `Wiii-Workbench_<version>_macos-arm64-unnotarized.dmg`
- `Wiii-Workbench_<version>_macos-x64-unnotarized.dmg`

Every binary is published with `<binary>.sha256`. Each build target also emits
`Wiii-Workbench_<version>_<target>_release-manifest.json`; the Linux manifest
contains both Linux packages. A manifest binds file name, byte length, SHA-256
digest, git commit, tag, and version. Stable publication also attaches
GitHub-generated provenance attestations and release notes extracted from
`CHANGELOG.md`.

Internal executable and Tauri bundle identifiers remain stable to protect
upgrades and installed application state.

## 6. Installation and verification

Verify the sidecar before opening a downloaded package. On PowerShell:

```powershell
$expected = (Get-Content .\Wiii-Workbench_1.2.0_windows-x64-setup.exe.sha256).Split()[0]
$actual = (Get-FileHash .\Wiii-Workbench_1.2.0_windows-x64-setup.exe -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'Wiii checksum mismatch' }
```

On Linux:

```bash
sha256sum -c Wiii-Workbench_<version>_<package>.sha256
```

On macOS:

```bash
shasum -a 256 -c Wiii-Workbench_<version>_<package>.sha256
```

- Windows: run the NSIS installer normally. Managed automation may use the
  standard NSIS `/S` silent switch.
- Debian/Ubuntu: install the `.deb` with the system package manager.
- Other supported x64 Linux distributions: mark the AppImage executable and
  run it without installation. The AppImage includes Tauri's media framework
  bundle so Wiii voice playback does not depend on host GStreamer packages.
- macOS: open the DMG and drag Wiii to Applications. Until notarization is
  enabled, verify the checksum first, then approve Wiii through System Settings
  > Privacy & Security if Gatekeeper blocks the first launch.

## 7. Rollback and incident response

Do not move or reuse a published tag. If a release is defective:

1. Mark the GitHub release as withdrawn or prerelease and state why.
2. Preserve its artifacts and manifest for audit unless they expose a secret.
3. Revert or correct on a new branch.
4. Publish a higher version with explicit changelog and migration notes.
5. Revoke credentials or certificates immediately if compromise is suspected.

Automatic desktop updates are deliberately not enabled until The Wiii Lab can
guarantee long-term custody and recovery of the Tauri updater signing key. Once
enabled, updater signatures are a permanent trust contract and cannot be
treated as an optional release detail.
