# Wiii Repository Harness

The repository harness is a small control layer over Wiii's real tests and
runtime evidence contracts. It answers five questions:

1. Are canonical product, brand, and release files present?
2. Are all public version surfaces synchronized?
3. Do links in the canonical documentation resolve?
4. Do the primary docs describe Wiii as an AI workbench rather than an LMS?
5. Does every registered runtime evidence contract still point to a valid,
   guarded workflow and probe?

Run the pull-request profile:

```powershell
python tools/wiii_self_harness/run_wiii_repository_harness.py --profile pr
```

Use `--json --out artifacts/wiii-repository-harness.json` in automation. The
`release` profile adds clean-worktree and exact stable-tag checks. It is meant
for the tagged commit, not for an in-progress release PR.

Focused behavior remains owned by backend, desktop, adapter, and live-evidence
test suites. New product features should add a focused test or a registry entry,
not another sequence of report generators.
