# Changelog

All notable changes to Wiii are documented here.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [Semantic Versioning](https://semver.org/). `VERSION` is the repository's
single source of truth. A stable release tag is always `wiii-v<version>`.

## [Unreleased]

### Added

- Nothing yet.

## [1.2.0] - 2026-08-15

### Added

- Neko Chill, a desktop-first agent workspace with durable ACP sessions,
  session replay, model/profile/reasoning controls, slash commands, and explicit
  handling of mutations whose outcome is unknown after a crash.
- A live workspace pane for files, diffs, previews, and artifacts beside the
  conversation.
- The Neko mascot family, Peek application icon, motion research lab, and a
  coherent visual identity across the desktop app, installer, repository, and
  social surfaces.
- A repository-wide release tool for synchronized versions, release notes,
  checksums, and machine-readable artifact manifests.

### Changed

- Repositioned Wiii as an open AI workbench and runtime. Learning-management
  systems are supported through Wiii Connect adapters rather than defining the
  product itself.
- Rebuilt the desktop information architecture around sessions, workspaces,
  inspectable artifacts, and resilient local-first interaction.
- Standardized public release assets under the `Wiii Workbench` name while
  retaining stable internal identifiers for upgrade compatibility.
- Unified backend package/runtime and desktop metadata under the repository
  `VERSION` source of truth.

### Fixed

- Window controls now route through native Tauri commands with explicit
  minimize, maximize/restore, and close behavior.
- ACP sessions survive process restarts and recover checkpoint metadata,
  provider continuation state, usage, tool calls, and cursor-based replay.
- Tool calls are checkpointed before side effects; interrupted mutations are
  restored as `unknown_outcome` and are never silently replayed.

### Security

- Durable session storage uses a single-writer lease, backup checkpoint
  recovery, and process-scoped permission grants.
- Release policy distinguishes unsigned internal candidates from signed public
  stable builds and requires provenance plus checksums for published binaries.

[Unreleased]: https://github.com/meiiie/wiii/compare/wiii-v1.2.0...HEAD
[1.2.0]: https://github.com/meiiie/wiii/releases/tag/wiii-v1.2.0
