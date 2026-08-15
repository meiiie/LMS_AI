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

A maintainer starts `Desktop Release` manually. The workflow builds and tests
the exact commit, emits a professionally named installer, checksum, release
notes, and manifest, then uploads them as a GitHub Actions artifact. Candidate
artifacts are internal evaluation builds and may be unsigned. They must never be
presented as a public stable release.

### Stable

A stable run is triggered only by a pushed `wiii-v<version>` tag. The tag must
match `VERSION` and point to the reviewed release commit. Stable Windows builds
require an Authenticode certificate, pass signature verification, receive a
GitHub artifact provenance attestation, and are published as a GitHub Release.

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

The stable workflow additionally verifies the tag, installer Authenticode
status, SHA-256 checksum, JSON manifest, and GitHub provenance attestation.

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

The public Windows installer name is:

`Wiii-Workbench_<version>_windows-x64-setup.exe`

It is published with:

- `<installer>.sha256`
- `Wiii-Workbench_<version>_release-manifest.json`
- GitHub-generated provenance attestation
- release notes extracted from `CHANGELOG.md`

The manifest binds file name, byte length, SHA-256 digest, git commit, tag, and
version. Internal executable and Tauri bundle identifiers remain stable to
protect upgrades and installed application state.

## 6. Rollback and incident response

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
