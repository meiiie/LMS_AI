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

`VERSION` is authoritative for the coordinated source and package version. It
is a release target, not evidence of publication. The release tool checks every
duplicated version surface used by npm, Tauri, Cargo, structured metadata,
splash UI, and installer art. A candidate is invalid when any surface diverges;
a stable release additionally requires its immutable tag, dated changelog
section, verified artifacts, and GitHub Release.

The product name in public release metadata and package filenames is `Wiii`.
Names such as Workbench, ADE, Neko Chill, and Wiii Service describe Wiii
surfaces; they do not create independent version lines. Internal executable and
bundle identifiers may retain older names to preserve upgrades.

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
Candidate notes come from the non-empty `Unreleased` changelog section.
Candidate filenames include `candidate` plus the source commit prefix so two
builds with the same coordinated `VERSION` can never masquerade as the same
binary.

Ubuntu 22.04 is intentional. Tauri v2 requires WebKitGTK 4.1 and recommends
building on the oldest supported Linux baseline to avoid raising the required
glibc version. Linux ARM is outside the current release contract.

### Stable

Owner decision, 2026-09-06: official public releases may ship without a publisher
certificate. Release channel and platform trust are separate facts. The governed
workflow defaults to `unsigned`. A manual dispatch may explicitly select
`windows_signing=authenticode`; missing credentials never silently downgrade
that selection. The emergency scope requires the Authenticode selection.
For a signed release, set the repository variable `WIII_WINDOWS_SIGNING` to
`authenticode` before pushing its tag, so the automatic tag run uses that same
trust selection. With no variable, tag runs remain explicitly unsigned. Do not
attempt to change an already published release from unsigned to signed.

A stable run is triggered only by a pushed `wiii-v<version>` tag. The tag must
match `VERSION` and point to the reviewed release commit. Windows builds marked
`signed` require an Authenticode certificate and signature verification. Builds
explicitly configured `unsigned` must verify `NotSigned` and disclose that state
in the installer filename, manifest and public release notes. Linux and
macOS packages are built from that same commit. All packages, checksums, and
manifests receive GitHub artifact provenance attestations before publication.

The current macOS packages are deliberately named `unnotarized`. Tauri applies
an ad-hoc signature so Apple Silicon can execute the application, but the files
do not carry an Apple Developer identity or notarization ticket. This is a
transparent transitional channel, not a claim of Apple trust. Users must verify
the checksum and use macOS Privacy & Security to approve the application. Do
not suggest disabling Gatekeeper globally.

For the Authenticode configuration, the workflow expects these protected secrets:

- `WIII_WINDOWS_CERTIFICATE_PFX_BASE64`
- `WIII_WINDOWS_CERTIFICATE_PASSWORD`

No certificate is required for the explicitly unsigned configuration. Keep two
GitHub environments: `candidate` contains no secrets and may run without
approval; `release` contains the signing secrets and requires approval from the
project owner or an explicitly delegated release/security maintainer. Use a
code-signing certificate controlled by the project owner. Restrict the secrets
to the `release` environment, rotate before expiry, and revoke immediately after
suspected exposure. Never commit a PFX, password, private updater key, or
decoded certificate.

## 3. Required gates

Before a stable tag is created:

1. The release PR is merged through the required PR/check gates; independent
   release or security review is requested when an eligible reviewer is available.
2. `python tools/release/wiii_release.py check` passes.
3. `CHANGELOG.md` contains a dated, non-empty section for the version.
4. The repository harness and desktop test/build gates pass.
5. Upgrade, persistence, and rollback risks are recorded in the PR.
6. The tagged commit is the exact commit approved for release.

The stable workflow additionally verifies the tag, declared Windows trust state
(Authenticode status and exact signer thumbprint when signed), the complete
five-binary/four-manifest matrix, every SHA-256 sidecar, manifest version and
commit bindings, and GitHub provenance attestation.

## 4. Operator commands

Prepare a version on a release branch:

```powershell
python tools/release/wiii_release.py set 1.3.0
# Candidate mode validates non-empty [Unreleased] notes.
python tools/release/wiii_release.py check
# Before tagging, move those notes into a dated [1.3.0] section and validate
# the exact stable tag contract.
python tools/release/wiii_release.py check --tag wiii-v1.3.0
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

- Candidate Windows: `Wiii-<version>-candidate-<sha8>-windows-x64-unsigned-setup.exe`
- Stable Windows: `Wiii-<version>-windows-x64-signed-setup.exe`
- Explicitly unsigned stable Windows: `Wiii-<version>-windows-x64-unsigned-setup.exe`
- Candidate Linux: `Wiii-<version>-candidate-<sha8>-linux-x64.{deb,AppImage}`
- Stable Linux: `Wiii-<version>-linux-x64.{deb,AppImage}`
- Candidate macOS: `Wiii-<version>-candidate-<sha8>-macos-<arch>-unnotarized.dmg`
- Stable macOS: `Wiii-<version>-macos-<arch>-unnotarized.dmg`

Every binary is published with `<binary>.sha256`. Each build target also emits
`Wiii-<build-identity>-<target>-release-manifest.json`; the Linux manifest
contains both Linux packages. A manifest binds product, channel, trust state,
file name, byte length, SHA-256 digest, git commit, tag, and version. Stable publication also attaches
GitHub-generated provenance attestations and release notes extracted from
`CHANGELOG.md`.

Internal executable and Tauri bundle identifiers remain stable to protect
upgrades and installed application state.

## 6. Installation and verification

Verify the sidecar before opening a downloaded package. On PowerShell:

```powershell
$expected = (Get-Content .\Wiii-1.2.0-windows-x64-unsigned-setup.exe.sha256).Split()[0]
$actual = (Get-FileHash .\Wiii-1.2.0-windows-x64-unsigned-setup.exe -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'Wiii checksum mismatch' }
```

For an Authenticode release, use its `signed-setup.exe` filename instead.

On Linux:

```bash
sha256sum -c Wiii-<version>-<package>.sha256
```

On macOS:

```bash
shasum -a 256 -c Wiii-<version>-<package>.sha256
```

- Windows: run the NSIS installer normally. Managed automation may use the
  standard NSIS `/S` silent switch.
  Unsigned builds can trigger SmartScreen or enterprise-policy blocks; verify
  source, checksum and provenance before deciding whether to allow that app.
  Never disable Windows protection globally. SHA-256 verifies integrity, not
  publisher identity or absence of malicious behavior.
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

## 8. Protected emergency publication

The normal stable contract is the complete four-target matrix. A Windows-only
break-glass release is allowed only when all of these conditions hold:

1. A reviewed stable tag contains a time-critical security or recovery fix.
2. A confirmed GitHub-hosted Linux or macOS runner outage prevents the complete
   matrix from finishing; a failing Wiii build is not an outage exemption.
3. The maintainer manually dispatches `Desktop Release` on that tag with
   `release_scope=windows-only-emergency` and a meaningful public incident or
   outage reason.
4. The project owner or delegated release/security maintainer approves the
   protected `release` environment deployment.
5. Tag/version validation, the Windows Authenticode signer/thumbprint gate,
   checksum and manifest verification, and provenance attestation all pass.

The GitHub Release notes must state that Linux and macOS are missing and include
the submitted reason. No unsigned Windows package or unreviewed commit may use
this path. When hosted runners recover, rerun the workflow on the same tag with
`release_scope=complete`; the workflow verifies and attests the full matrix,
backfills the missing assets, and replaces the temporary availability notice.
Existing assets must be byte-identical to any regenerated names; publication
must refuse replacement and upload only missing assets, never use `--clobber`.

Every break-glass use must be recorded in a public issue or security advisory,
reviewed after recovery, and included in the next changelog. Repeated platform
build failures require a fix or a new release; they must not be normalized into
routine emergency publication.
