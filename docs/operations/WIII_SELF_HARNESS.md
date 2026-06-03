# Wiii Self-Harness

Status: Active

Owner: Project leadership

Last updated: 2026-06-02

## Purpose

Wiii Self-Harness is the repository-owned harness for Wiii's active system
contracts. It keeps critical product paths explicit, typed where possible, and
traceable to living runtime, test, docs, and CI evidence.

This harness does not replace backend unit tests, desktop tests, browser smoke
tests, or LMS product E2E. It is the thin deterministic layer that answers:

```text
Do Wiii's critical contracts still have named scenarios, evidence files, and
focused verification commands?
```

## Current Scenarios

The canonical manifest lives at:

```text
tools/wiii_self_harness/wiii_self_harness_scenarios.json
```

The system-level operating map lives at:

```text
docs/operations/WIII_SYSTEM_CONTROL_PLANE.md
```

The first scenario set covers the active product risk surface:

- `system-flow-observability-map`: the control-plane map stays available and
  describes the active flow-monitoring ladder.
- `system-comprehension-reference-harness`: Understand-Anything remains a
  guarded, local-only comprehension reference with generated graph output
  ignored, and the repo-owned flow-map wrapper stays available for scoped
  audits.
- `memory-context-provenance-ledger`: Runtime Flow Ledger embeds privacy-safe
  context provenance for conversation, document, memory, and host sources.
- `chat-baseline-acceptance-harness`: ordinary Vietnamese chat remains on the
  safe chat lane with terminal ledger, finalization, heartbeat, and tool
  suppression evidence.
- `visual-tool-capability-sync`: visual intent selects the right tool lane.
- `code-studio-scaffold-boundary`: Code Studio scaffold fallback is typed and
  policy-gated.
- `lms-document-preview-apply-approval`: uploaded LMS documents use preview and
  approval before apply.
- `host-action-audit-route`: host action audit remains route-available and
  token-safe.
- `frontend-visual-code-studio-shell`: VisualBlock and CodeStudioPanel avoid
  raw output drift and keep app previews host-owned.

## How To Run

From the repository root:

```powershell
python tools/wiii_self_harness/run_wiii_self_harness.py
python tools/wiii_self_harness/validate_runtime_evidence_registry.py
python tools/wiii_self_harness/report_runtime_evidence_coverage.py --format markdown --require-no-synthetic-gaps --require-credentialed-external-contracts
python tools/wiii_self_harness/report_runtime_evidence_coverage.py --format json --require-no-synthetic-gaps
python tools/wiii_self_harness/report_runtime_evidence_coverage.py --format json --require-no-synthetic-gaps --require-credentialed-external-contracts
python tools/wiii_self_harness/validate_self_harness_report_bundle.py <downloaded-self-harness-reports-dir>
python tools/wiii_self_harness/validate_self_harness_report_bundle.py <downloaded-self-harness-reports-dir> --json --require-no-synthetic-gaps
python tools/wiii_self_harness/validate_self_harness_report_bundle.py <downloaded-self-harness-reports-dir> --json --require-no-synthetic-gaps --require-credentialed-external-contracts
python tools/wiii_self_harness/validate_runtime_evidence_bundle.py <downloaded-artifact-dir>
python tools/wiii_self_harness/validate_runtime_evidence_preflight.py <preflight-json> --requirement-id <runtime-evidence-requirement-id>
python tools/wiii_self_harness/validate_runtime_evidence_bundle.py <downloaded-artifact-dir> --self-harness-report-bundle <downloaded-self-harness-reports-dir> --require-completion-audit-link --format json
python tools/wiii_self_harness/generate_completion_audit_handoff.py <downloaded-artifact-dir> --self-harness-report-bundle <downloaded-self-harness-reports-dir> --out-dir artifacts/wiii-completion-audit --json --allow-not-ready
python tools/wiii_self_harness/validate_completion_audit_handoff.py artifacts/wiii-completion-audit --json --out artifacts/wiii-completion-audit-handoff-validation.json
python tools/wiii_self_harness/validate_completion_audit_handoff.py artifacts/wiii-completion-audit --json --require-completion-audit-ready
python tools/wiii_self_harness/generate_completion_audit_recovery_plan.py artifacts/wiii-completion-audit/completion-audit-handoff.json --format json --out artifacts/wiii-completion-audit-recovery-plan.json
python tools/wiii_self_harness/validate_completion_audit_recovery_plan.py artifacts/wiii-completion-audit-recovery-plan.json --handoff-json artifacts/wiii-completion-audit/completion-audit-handoff.json --json --out artifacts/wiii-completion-audit-recovery-plan-validation.json
python tools/wiii_self_harness/run_completion_audit_recovery_queue.py artifacts/wiii-completion-audit-recovery-plan.json --handoff-json artifacts/wiii-completion-audit/completion-audit-handoff.json --out artifacts/wiii-completion-audit-recovery-queue.json
python tools/wiii_self_harness/validate_completion_audit_recovery_queue.py artifacts/wiii-completion-audit-recovery-queue.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan.json --handoff-json artifacts/wiii-completion-audit/completion-audit-handoff.json --json --out artifacts/wiii-completion-audit-recovery-queue-validation.json
python tools/wiii_self_harness/generate_completion_audit_recovery_work_order.py artifacts/wiii-completion-audit-recovery-queue.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan.json --handoff-json artifacts/wiii-completion-audit/completion-audit-handoff.json --out artifacts/wiii-completion-audit-recovery-work-order.json
python tools/wiii_self_harness/validate_completion_audit_recovery_work_order.py artifacts/wiii-completion-audit-recovery-work-order.json --recovery-queue artifacts/wiii-completion-audit-recovery-queue.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan.json --handoff-json artifacts/wiii-completion-audit/completion-audit-handoff.json --json --out artifacts/wiii-completion-audit-recovery-work-order-validation.json
python tools/wiii_self_harness/report_completion_audit_recovery_work_order_status.py artifacts/wiii-completion-audit-recovery-work-order.json --recovery-queue artifacts/wiii-completion-audit-recovery-queue.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan.json --handoff-json artifacts/wiii-completion-audit/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state.json --out artifacts/wiii-completion-audit-recovery-work-order-status.json
python tools/wiii_self_harness/validate_completion_audit_recovery_work_order_status.py artifacts/wiii-completion-audit-recovery-work-order-status.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order.json --recovery-queue artifacts/wiii-completion-audit-recovery-queue.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan.json --handoff-json artifacts/wiii-completion-audit/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state.json --json --out artifacts/wiii-completion-audit-recovery-work-order-status-validation.json
python tools/wiii_self_harness/generate_completion_audit_recovery_queue_progress.py artifacts/wiii-completion-audit-recovery-queue.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan.json --work-order-status artifacts/wiii-completion-audit-recovery-work-order-status.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order.json --handoff-json artifacts/wiii-completion-audit/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state.json --out artifacts/wiii-completion-audit-recovery-queue-progress.json
python tools/wiii_self_harness/validate_completion_audit_recovery_queue_progress.py artifacts/wiii-completion-audit-recovery-queue-progress.json --source-recovery-queue artifacts/wiii-completion-audit-recovery-queue.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan.json --work-order-status artifacts/wiii-completion-audit-recovery-work-order-status.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order.json --handoff-json artifacts/wiii-completion-audit/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state.json --json --out artifacts/wiii-completion-audit-recovery-queue-progress-validation.json
python tools/wiii_self_harness/generate_completion_audit_recovery_dispatch_authorization.py artifacts/wiii-completion-audit-recovery-queue-progress.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan.json --source-recovery-queue artifacts/wiii-completion-audit-recovery-queue.json --work-order-status artifacts/wiii-completion-audit-recovery-work-order-status.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order.json --handoff-json artifacts/wiii-completion-audit/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state.json --out artifacts/wiii-completion-audit-recovery-dispatch-authorization.json
python tools/wiii_self_harness/validate_completion_audit_recovery_dispatch_authorization.py artifacts/wiii-completion-audit-recovery-dispatch-authorization.json --queue-progress artifacts/wiii-completion-audit-recovery-queue-progress.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan.json --source-recovery-queue artifacts/wiii-completion-audit-recovery-queue.json --work-order-status artifacts/wiii-completion-audit-recovery-work-order-status.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order.json --handoff-json artifacts/wiii-completion-audit/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state.json --json --out artifacts/wiii-completion-audit-recovery-dispatch-authorization-validation.json
python tools/wiii_self_harness/run_completion_audit_recovery_dispatch_authorization.py artifacts/wiii-completion-audit-recovery-dispatch-authorization.json --queue-progress artifacts/wiii-completion-audit-recovery-queue-progress.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan.json --source-recovery-queue artifacts/wiii-completion-audit-recovery-queue.json --work-order-status artifacts/wiii-completion-audit-recovery-work-order-status.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order.json --handoff-json artifacts/wiii-completion-audit/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state.json --allow-blocked-report --out artifacts/wiii-completion-audit-recovery-dispatch-run.json
python tools/wiii_self_harness/validate_completion_audit_recovery_dispatch_run.py artifacts/wiii-completion-audit-recovery-dispatch-run.json --recovery-dispatch-authorization artifacts/wiii-completion-audit-recovery-dispatch-authorization.json --queue-progress artifacts/wiii-completion-audit-recovery-queue-progress.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan.json --source-recovery-queue artifacts/wiii-completion-audit-recovery-queue.json --work-order-status artifacts/wiii-completion-audit-recovery-work-order-status.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order.json --handoff-json artifacts/wiii-completion-audit/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state.json --json --out artifacts/wiii-completion-audit-recovery-dispatch-run-validation.json
python tools/wiii_self_harness/validate_completion_audit_recovery_control_chain.py --recovery-plan artifacts/wiii-completion-audit-recovery-plan.json --recovery-queue artifacts/wiii-completion-audit-recovery-queue.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order.json --work-order-status artifacts/wiii-completion-audit-recovery-work-order-status.json --queue-progress artifacts/wiii-completion-audit-recovery-queue-progress.json --recovery-dispatch-authorization artifacts/wiii-completion-audit-recovery-dispatch-authorization.json --recovery-dispatch-run artifacts/wiii-completion-audit-recovery-dispatch-run.json --handoff-json artifacts/wiii-completion-audit/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state.json --dispatch-gate artifacts/wiii-completion-audit-dispatch-gate.json --launch-pack artifacts/wiii-completion-audit-launch-pack.json --json --out artifacts/wiii-completion-audit-recovery-control-chain.json
python tools/wiii_self_harness/generate_completion_audit_recovery_checkpoint.py artifacts/wiii-completion-audit-recovery-control-chain.json --repo-root . --json --out artifacts/wiii-completion-audit-recovery-checkpoint.json
python tools/wiii_self_harness/validate_completion_audit_recovery_checkpoint.py artifacts/wiii-completion-audit-recovery-checkpoint.json --recovery-control-chain artifacts/wiii-completion-audit-recovery-control-chain.json --repo-root . --json --out artifacts/wiii-completion-audit-recovery-checkpoint-validation.json
python tools/wiii_self_harness/smoke_completion_audit_handoff.py --self-harness-report-bundle artifacts/wiii-self-harness --artifact-bundle-root artifacts/runtime-evidence-empty --out-dir artifacts/wiii-completion-audit-smoke --json-out artifacts/wiii-completion-audit-smoke.json --release-gate-json-out artifacts/wiii-completion-audit-smoke-release-gate-validation.json
python tools/wiii_self_harness/validate_completion_audit_smoke.py artifacts/wiii-completion-audit-smoke.json --release-gate-json artifacts/wiii-completion-audit-smoke-release-gate-validation.json --structural-validation-json artifacts/wiii-completion-audit-smoke-validation.json --require-handoff-root-source --json --out artifacts/wiii-completion-audit-smoke-sidecars-validation.json
python tools/wiii_self_harness/report_completion_audit_readiness.py artifacts/runtime-evidence-empty --self-harness-report-bundle artifacts/wiii-self-harness --exclude-requirement-id lms-test-course-replay --preflight-dir artifacts --format json --out artifacts/wiii-completion-audit-readiness-non-lms.json
python tools/wiii_self_harness/report_completion_audit_readiness.py artifacts/runtime-evidence-empty --self-harness-report-bundle artifacts/wiii-self-harness --exclude-requirement-id lms-test-course-replay --preflight-dir artifacts --format markdown --out artifacts/wiii-completion-audit-readiness-non-lms.md
python tools/wiii_self_harness/validate_completion_audit_readiness.py artifacts/wiii-completion-audit-readiness-non-lms.json --preflight-dir artifacts --markdown-report artifacts/wiii-completion-audit-readiness-non-lms.md --self-harness-report-bundle artifacts/wiii-self-harness --json --out artifacts/wiii-completion-audit-readiness-validation-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_run_plan.py artifacts/wiii-completion-audit-readiness-non-lms.json --preflight-dir artifacts --format json --out artifacts/wiii-completion-audit-run-plan-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_run_plan.py artifacts/wiii-completion-audit-readiness-non-lms.json --preflight-dir artifacts --format markdown --out artifacts/wiii-completion-audit-run-plan-non-lms.md
python tools/wiii_self_harness/validate_completion_audit_run_plan.py artifacts/wiii-completion-audit-run-plan-non-lms.json --readiness-report artifacts/wiii-completion-audit-readiness-non-lms.json --readiness-markdown-report artifacts/wiii-completion-audit-readiness-non-lms.md --readiness-preflight-dir artifacts --self-harness-report-bundle artifacts/wiii-self-harness --markdown-report artifacts/wiii-completion-audit-run-plan-non-lms.md --json --out artifacts/wiii-completion-audit-run-plan-validation-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_launch_pack.py artifacts/wiii-completion-audit-run-plan-non-lms.json --format json --out artifacts/wiii-completion-audit-launch-pack-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_launch_pack.py artifacts/wiii-completion-audit-run-plan-non-lms.json --format markdown --out artifacts/wiii-completion-audit-launch-pack-non-lms.md
python tools/wiii_self_harness/validate_completion_audit_launch_pack.py artifacts/wiii-completion-audit-launch-pack-non-lms.json --run-plan artifacts/wiii-completion-audit-run-plan-non-lms.json --repo-root . --markdown-report artifacts/wiii-completion-audit-launch-pack-non-lms.md --json --out artifacts/wiii-completion-audit-launch-pack-validation-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_setup_state.py artifacts/wiii-completion-audit-launch-pack-non-lms.json --repo-root . --out artifacts/wiii-completion-audit-setup-state-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_setup_state.py artifacts/wiii-completion-audit-setup-state-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --json --out artifacts/wiii-completion-audit-setup-state-validation-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_setup_handle_plan.py artifacts/wiii-completion-audit-setup-state-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --out artifacts/wiii-completion-audit-setup-handle-plan-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_setup_handle_plan.py artifacts/wiii-completion-audit-setup-handle-plan-non-lms.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --json --out artifacts/wiii-completion-audit-setup-handle-plan-validation-non-lms.json
python tools/wiii_self_harness/report_completion_audit_setup_gaps.py artifacts/wiii-completion-audit-setup-handle-plan-non-lms.json --format json --out artifacts/wiii-completion-audit-setup-gaps-non-lms.json
python tools/wiii_self_harness/report_completion_audit_setup_gaps.py artifacts/wiii-completion-audit-setup-handle-plan-non-lms.json --format markdown --out artifacts/wiii-completion-audit-setup-gaps-non-lms.md
python tools/wiii_self_harness/validate_completion_audit_setup_gaps.py artifacts/wiii-completion-audit-setup-gaps-non-lms.json --setup-handle-plan artifacts/wiii-completion-audit-setup-handle-plan-non-lms.json --markdown-report artifacts/wiii-completion-audit-setup-gaps-non-lms.md --json --out artifacts/wiii-completion-audit-setup-gaps-validation-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_setup_attestation_template.py artifacts/wiii-completion-audit-setup-handle-plan-non-lms.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --out artifacts/wiii-completion-audit-setup-attestation-template-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_setup_attestation_template.py artifacts/wiii-completion-audit-setup-attestation-template-non-lms.json --setup-handle-plan artifacts/wiii-completion-audit-setup-handle-plan-non-lms.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --json --out artifacts/wiii-completion-audit-setup-attestation-template-validation-non-lms.json
python tools/wiii_self_harness/smoke_completion_audit_setup_attestation.py --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --setup-handle-plan artifacts/wiii-completion-audit-setup-handle-plan-non-lms.json --template artifacts/wiii-completion-audit-setup-attestation-template-non-lms.json --out-dir artifacts/wiii-completion-audit-setup-attestation-smoke --json-out artifacts/wiii-completion-audit-setup-attestation-smoke.json --repo-root .
python tools/wiii_self_harness/validate_completion_audit_setup_attestation_smoke.py artifacts/wiii-completion-audit-setup-attestation-smoke.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --setup-handle-plan artifacts/wiii-completion-audit-setup-handle-plan-non-lms.json --template artifacts/wiii-completion-audit-setup-attestation-template-non-lms.json --out-dir artifacts/wiii-completion-audit-setup-attestation-smoke --repo-root . --json --out artifacts/wiii-completion-audit-setup-attestation-smoke-validation-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_dispatch_gate.py artifacts/wiii-completion-audit-launch-pack-non-lms.json artifacts/wiii-completion-audit-setup-state-non-lms.json --out artifacts/wiii-completion-audit-dispatch-gate-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_dispatch_gate.py artifacts/wiii-completion-audit-dispatch-gate-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --json --out artifacts/wiii-completion-audit-dispatch-gate-validation-non-lms.json
python tools/wiii_self_harness/run_completion_audit_dispatch_gate.py artifacts/wiii-completion-audit-dispatch-gate-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --repo-root . --allow-pending-report --out artifacts/wiii-completion-audit-dispatch-run-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_dispatch_run.py artifacts/wiii-completion-audit-dispatch-run-non-lms.json --dispatch-gate artifacts/wiii-completion-audit-dispatch-gate-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --repo-root . --json --out artifacts/wiii-completion-audit-dispatch-run-validation-non-lms.json
python tools/wiii_self_harness/run_completion_audit_dispatch_diagnostics.py artifacts/wiii-completion-audit-dispatch-run-non-lms.json --dispatch-gate artifacts/wiii-completion-audit-dispatch-gate-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --repo-root . --out artifacts/wiii-completion-audit-dispatch-diagnostics-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_dispatch_diagnostics.py artifacts/wiii-completion-audit-dispatch-diagnostics-non-lms.json --dispatch-run artifacts/wiii-completion-audit-dispatch-run-non-lms.json --dispatch-gate artifacts/wiii-completion-audit-dispatch-gate-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --repo-root . --json --out artifacts/wiii-completion-audit-dispatch-diagnostics-validation-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_handoff.py artifacts/runtime-evidence-empty --self-harness-report-bundle artifacts/wiii-self-harness --readiness-report artifacts/wiii-completion-audit-readiness-non-lms.json --setup-gap-report artifacts/wiii-completion-audit-setup-gaps-non-lms.json --setup-gap-markdown-report artifacts/wiii-completion-audit-setup-gaps-non-lms.md --out-dir artifacts/wiii-completion-audit-handoff-non-lms --allow-not-ready
python tools/wiii_self_harness/validate_completion_audit_handoff.py artifacts/wiii-completion-audit-handoff-non-lms --json --out artifacts/wiii-completion-audit-handoff-validation-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_recovery_plan.py artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --format json --out artifacts/wiii-completion-audit-recovery-plan-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_recovery_plan.py artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --format markdown --out artifacts/wiii-completion-audit-recovery-plan-non-lms.md
python tools/wiii_self_harness/validate_completion_audit_recovery_plan.py artifacts/wiii-completion-audit-recovery-plan-non-lms.json --handoff-json artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --json --out artifacts/wiii-completion-audit-recovery-plan-validation-non-lms.json
python tools/wiii_self_harness/run_completion_audit_recovery_queue.py artifacts/wiii-completion-audit-recovery-plan-non-lms.json --handoff-json artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --out artifacts/wiii-completion-audit-recovery-queue-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_recovery_queue.py artifacts/wiii-completion-audit-recovery-queue-non-lms.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan-non-lms.json --handoff-json artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --json --out artifacts/wiii-completion-audit-recovery-queue-validation-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_recovery_work_order.py artifacts/wiii-completion-audit-recovery-queue-non-lms.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan-non-lms.json --handoff-json artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --out artifacts/wiii-completion-audit-recovery-work-order-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_recovery_work_order.py artifacts/wiii-completion-audit-recovery-work-order-non-lms.json --recovery-queue artifacts/wiii-completion-audit-recovery-queue-non-lms.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan-non-lms.json --handoff-json artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --json --out artifacts/wiii-completion-audit-recovery-work-order-validation-non-lms.json
python tools/wiii_self_harness/report_completion_audit_recovery_work_order_status.py artifacts/wiii-completion-audit-recovery-work-order-non-lms.json --recovery-queue artifacts/wiii-completion-audit-recovery-queue-non-lms.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan-non-lms.json --handoff-json artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --out artifacts/wiii-completion-audit-recovery-work-order-status-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_recovery_work_order_status.py artifacts/wiii-completion-audit-recovery-work-order-status-non-lms.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order-non-lms.json --recovery-queue artifacts/wiii-completion-audit-recovery-queue-non-lms.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan-non-lms.json --handoff-json artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --json --out artifacts/wiii-completion-audit-recovery-work-order-status-validation-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_recovery_queue_progress.py artifacts/wiii-completion-audit-recovery-queue-non-lms.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan-non-lms.json --work-order-status artifacts/wiii-completion-audit-recovery-work-order-status-non-lms.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order-non-lms.json --handoff-json artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --out artifacts/wiii-completion-audit-recovery-queue-progress-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_recovery_queue_progress.py artifacts/wiii-completion-audit-recovery-queue-progress-non-lms.json --source-recovery-queue artifacts/wiii-completion-audit-recovery-queue-non-lms.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan-non-lms.json --work-order-status artifacts/wiii-completion-audit-recovery-work-order-status-non-lms.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order-non-lms.json --handoff-json artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --json --out artifacts/wiii-completion-audit-recovery-queue-progress-validation-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_recovery_dispatch_authorization.py artifacts/wiii-completion-audit-recovery-queue-progress-non-lms.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan-non-lms.json --dispatch-gate artifacts/wiii-completion-audit-dispatch-gate-non-lms.json --source-recovery-queue artifacts/wiii-completion-audit-recovery-queue-non-lms.json --work-order-status artifacts/wiii-completion-audit-recovery-work-order-status-non-lms.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order-non-lms.json --handoff-json artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --out artifacts/wiii-completion-audit-recovery-dispatch-authorization-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_recovery_dispatch_authorization.py artifacts/wiii-completion-audit-recovery-dispatch-authorization-non-lms.json --queue-progress artifacts/wiii-completion-audit-recovery-queue-progress-non-lms.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan-non-lms.json --dispatch-gate artifacts/wiii-completion-audit-dispatch-gate-non-lms.json --source-recovery-queue artifacts/wiii-completion-audit-recovery-queue-non-lms.json --work-order-status artifacts/wiii-completion-audit-recovery-work-order-status-non-lms.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order-non-lms.json --handoff-json artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --json --out artifacts/wiii-completion-audit-recovery-dispatch-authorization-validation-non-lms.json
python tools/wiii_self_harness/run_completion_audit_recovery_dispatch_authorization.py artifacts/wiii-completion-audit-recovery-dispatch-authorization-non-lms.json --queue-progress artifacts/wiii-completion-audit-recovery-queue-progress-non-lms.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan-non-lms.json --dispatch-gate artifacts/wiii-completion-audit-dispatch-gate-non-lms.json --source-recovery-queue artifacts/wiii-completion-audit-recovery-queue-non-lms.json --work-order-status artifacts/wiii-completion-audit-recovery-work-order-status-non-lms.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order-non-lms.json --handoff-json artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --allow-blocked-report --out artifacts/wiii-completion-audit-recovery-dispatch-run-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_recovery_dispatch_run.py artifacts/wiii-completion-audit-recovery-dispatch-run-non-lms.json --recovery-dispatch-authorization artifacts/wiii-completion-audit-recovery-dispatch-authorization-non-lms.json --queue-progress artifacts/wiii-completion-audit-recovery-queue-progress-non-lms.json --recovery-plan artifacts/wiii-completion-audit-recovery-plan-non-lms.json --dispatch-gate artifacts/wiii-completion-audit-dispatch-gate-non-lms.json --source-recovery-queue artifacts/wiii-completion-audit-recovery-queue-non-lms.json --work-order-status artifacts/wiii-completion-audit-recovery-work-order-status-non-lms.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order-non-lms.json --handoff-json artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --json --out artifacts/wiii-completion-audit-recovery-dispatch-run-validation-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_recovery_control_chain.py --recovery-plan artifacts/wiii-completion-audit-recovery-plan-non-lms.json --recovery-queue artifacts/wiii-completion-audit-recovery-queue-non-lms.json --recovery-work-order artifacts/wiii-completion-audit-recovery-work-order-non-lms.json --work-order-status artifacts/wiii-completion-audit-recovery-work-order-status-non-lms.json --queue-progress artifacts/wiii-completion-audit-recovery-queue-progress-non-lms.json --recovery-dispatch-authorization artifacts/wiii-completion-audit-recovery-dispatch-authorization-non-lms.json --recovery-dispatch-run artifacts/wiii-completion-audit-recovery-dispatch-run-non-lms.json --handoff-json artifacts/wiii-completion-audit-handoff-non-lms/completion-audit-handoff.json --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --dispatch-gate artifacts/wiii-completion-audit-dispatch-gate-non-lms.json --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --json --out artifacts/wiii-completion-audit-recovery-control-chain-non-lms.json
python tools/wiii_self_harness/generate_completion_audit_recovery_checkpoint.py artifacts/wiii-completion-audit-recovery-control-chain-non-lms.json --repo-root . --json --out artifacts/wiii-completion-audit-recovery-checkpoint-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_recovery_checkpoint.py artifacts/wiii-completion-audit-recovery-checkpoint-non-lms.json --recovery-control-chain artifacts/wiii-completion-audit-recovery-control-chain-non-lms.json --repo-root . --json --out artifacts/wiii-completion-audit-recovery-checkpoint-validation-non-lms.json
python tools/wiii_self_harness/validate_completion_audit_control_chain.py --readiness-report artifacts/wiii-completion-audit-readiness-non-lms.json --readiness-markdown-report artifacts/wiii-completion-audit-readiness-non-lms.md --readiness-preflight-dir artifacts --self-harness-report-bundle artifacts/wiii-self-harness --run-plan artifacts/wiii-completion-audit-run-plan-non-lms.json --run-plan-markdown artifacts/wiii-completion-audit-run-plan-non-lms.md --launch-pack artifacts/wiii-completion-audit-launch-pack-non-lms.json --launch-pack-markdown artifacts/wiii-completion-audit-launch-pack-non-lms.md --setup-state artifacts/wiii-completion-audit-setup-state-non-lms.json --setup-handle-plan artifacts/wiii-completion-audit-setup-handle-plan-non-lms.json --setup-gap-report artifacts/wiii-completion-audit-setup-gaps-non-lms.json --setup-gap-markdown-report artifacts/wiii-completion-audit-setup-gaps-non-lms.md --setup-attestation-template artifacts/wiii-completion-audit-setup-attestation-template-non-lms.json --setup-attestation-smoke artifacts/wiii-completion-audit-setup-attestation-smoke.json --setup-attestation-smoke-out-dir artifacts/wiii-completion-audit-setup-attestation-smoke --setup-attestation artifacts/wiii-completion-audit-setup-attestation-smoke/setup-attestation.json --setup-attestation-patch artifacts/wiii-completion-audit-setup-attestation-smoke/setup-handle-patch.json --attested-setup-state artifacts/wiii-completion-audit-setup-attestation-smoke/setup-state-attested.json --attested-dispatch-gate artifacts/wiii-completion-audit-setup-attestation-smoke/dispatch-gate-attested.json --attested-dispatch-run artifacts/wiii-completion-audit-setup-attestation-smoke/dispatch-run-dry.json --dispatch-gate artifacts/wiii-completion-audit-dispatch-gate-non-lms.json --dispatch-run artifacts/wiii-completion-audit-dispatch-run-non-lms.json --dispatch-diagnostics artifacts/wiii-completion-audit-dispatch-diagnostics-non-lms.json --recovery-control-chain artifacts/wiii-completion-audit-recovery-control-chain-non-lms.json --recovery-checkpoint artifacts/wiii-completion-audit-recovery-checkpoint-non-lms.json --repo-root . --json --out artifacts/wiii-completion-audit-control-chain-non-lms.json
python -m unittest discover -s tools/wiii_self_harness -p "test_*.py"
python -m unittest discover -s tools/wiii_understand_harness -p "test_*.py"
```

To list scenarios:

```powershell
python tools/wiii_self_harness/run_wiii_self_harness.py --list
```

To emit JSON for another tool:

```powershell
python tools/wiii_self_harness/run_wiii_self_harness.py --json
python tools/wiii_self_harness/run_wiii_self_harness.py --json --out artifacts/wiii-self-harness-validation.json
python tools/wiii_self_harness/validate_runtime_evidence_registry.py --json --out artifacts/wiii-runtime-evidence-registry-validation.json
python tools/wiii_self_harness/run_wiii_self_harness.py --json --out artifacts/wiii-self-harness/self-harness-validation.json
python tools/wiii_self_harness/validate_runtime_evidence_registry.py --json --out artifacts/wiii-self-harness/runtime-evidence-registry-validation.json
python tools/wiii_self_harness/generate_self_harness_report_bundle.py --out-dir artifacts/wiii-self-harness
python tools/wiii_self_harness/generate_self_harness_report_bundle.py --out-dir artifacts/wiii-self-harness --json --require-no-synthetic-gaps
python tools/wiii_self_harness/generate_self_harness_report_bundle.py --out-dir artifacts/wiii-self-harness --json --require-no-synthetic-gaps --require-credentialed-external-contracts
```

## How It Works

The runner is standard-library Python. It validates:

- manifest identity and version
- required scenario IDs, lowercase kebab-case shape, and active-scenario coverage
- lowercase kebab-case scenario IDs
- scenario status, Wiii layer, risk, owner, contract, and invariants
- repo-relative evidence paths
- required tokens inside each evidence file
- verification command and purpose metadata

It fails closed when a scenario is malformed, a file disappears, or a required
contract token no longer exists in the evidence file. The manifest root,
scenario entries, verification entries, and evidence entries are closed-schema
objects, and string-list proof fields reject duplicate values so a typoed field
or repeated token cannot inflate contract coverage. Every active scenario must
also appear in `required_scenarios`, so a live product contract cannot remain in
the manifest while silently dropping out of the required control-plane set.
Every required scenario must also have `status: active`, so deferred or blocked
contracts cannot stay in the required set without first being reactivated.
Every active scenario must include at least one `runtime` evidence file and one
`test` evidence file, so required product contracts cannot be proven by docs or
governance metadata alone. Within a scenario, the same `kind` plus normalized
repo-relative `path` evidence entry may appear only once; additional required
tokens must be merged into that entry so `evidence_count` cannot be inflated by
repeated file references or equivalent path spellings such as `./` and doubled
slashes.

The runner's JSON and summary output are self-described with
`wiii.self_harness_validation.v1`, the manifest integer version, a SHA-256
fingerprint over the harness contract fields, and normalized `error_codes`.
That keeps the scenario-manifest gate consumable by CI and handoff automation
without scraping prose output.
The central `.github/workflows/wiii-self-harness.yml` gate writes the manifest
and registry validations as standalone uploaded sidecars at
`artifacts/wiii-self-harness-validation.json` and
`artifacts/wiii-runtime-evidence-registry-validation.json`, so operators can
inspect the exact control-plane contracts validated by the run even when a
later gate fails. These sidecars are emitted immediately after report-bundle
validation and before completion-audit smoke steps, so downstream handoff
failures do not erase the manifest/registry proof for the run.
`validate_self_harness_sidecar_parity.py` then compares those standalone JSON
sidecars against the matching reports inside `artifacts/wiii-self-harness/` and
writes `artifacts/wiii-self-harness-sidecar-parity-validation.json`, so the
uploaded run artifact cannot silently carry divergent operator sidecars and
bundle reports. The parity report includes one comparison row per checked
report with the bundle path, sidecar path, matched flag, and canonical JSON
SHA-256 values for both payloads, making the sidecar proof independently
inspectable after CI artifact download. The parity validator also rejects
`--out` targets inside the report bundle or equal to any input report/sidecar,
so running the validator cannot pollute the bundle or overwrite the evidence it
is checking.

`runtime_evidence_registry.json` is the narrower machine-readable registry for
live/runtime artifacts such as provider, subagent, scheduler, heartbeat,
proactive-channel, semantic-memory write doctor, Wiii Connect external-app
action replay, credentialed Composio acceptance, Wiii Connect Facebook post
preview/apply replay, LMS test-course preview/apply, and browser Runtime-tab
replay evidence.
`validate_runtime_evidence_registry.py` checks that
each registered artifact still has a workflow, uploaded artifact name, schema
version, payload checks, opt-in live env flag, guard token, dispatch/schedule
gate, contract tests, `contents: read`, unique JSON artifact names, and no
`pull_request_target`. Registered evidence workflow paths must live directly
under `.github/workflows/`, so a registry entry cannot point at an arbitrary
YAML file that GitHub Actions would never execute. Every registered artifact
must forbid the baseline
secret payload tokens `api_key`, `access_token`, and `authorization`, so live
evidence privacy does not depend only on probe-specific raw markers. Any
registry root, requirement, freshness, payload-check, or payload-check `when`
key outside the validator allowlist is rejected, so typoed fields or
decorative config cannot silently bypass the machine-readable contract.
Freshness timestamps, payload-check paths, `length_equals_path`, and
payload-check `when` paths must use validator-approved dot-path syntax; only
payload-check target paths may use explicit `*` wildcard segments.
Payload-check operations are also typed at registry-validation time: `min` must
be a JSON number, `sorted_equals` must be a list, and each payload-check `when`
clause must choose exactly one explicit `equals` or `not_equals` condition.
Expected `equals`, `sorted_equals` entries, and `when` comparison values must
be non-null JSON scalars, keeping proof expectations simple and deterministic. Any
registered `forbidden_payload_regexes` must compile and must not duplicate
another registered regex for the same artifact, so privacy guards fail closed
before runtime artifact validation. Registry string-list obligations such as
forbidden tokens, contract tests, live env flags, guard tokens, gates, and
artifact tokens must not contain duplicate values, so a requirement cannot
inflate proof coverage by repeating the same token or path. Optional
`diagnostic_uploads` entries are allowed only for preflight/setup diagnostics:
each sidecar must declare one safe JSON artifact name, the exact repo-relative
upload path, a unique artifact token, `if_no_files_found: warn`, and a
retention period of 30 days or less. Because forbidden
payload token matching is case-insensitive, the registry also rejects
case-insensitive duplicates such as `api_key` plus `API_KEY`. The
top-level workflow permission block must be exactly
`contents: read`; extra scopes, `write` permissions, `read-all`, and job-level
permission overrides are rejected. Critical top-level workflow keys (`on`,
`permissions`, `concurrency`, and `jobs`) must be unique, so a later duplicate
block or scalar assignment cannot override the safe block that the validator
inspected. It also requires every `actions/checkout`
step in a registered evidence workflow to set `persist-credentials: false`, so
proof jobs do not leave the GitHub token in the job's git configuration after
checkout. Every `uses:` step in registered evidence workflows must be a real
step field directly under a job-level `steps:` list, stay on the approved
core-action allowlist, and be pinned to a 40-character commit SHA instead of a
mutable version tag; third-party, local, and shell-text action references are
rejected unless the allowlist is intentionally changed.
Registered evidence workflows must declare top-level concurrency with
`group: ${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}` and
`cancel-in-progress: ${{ github.event_name == 'pull_request' }}`, so only
superseded PR proof runs are canceled while scheduled or manually dispatched
runtime evidence runs remain inspectable.
Manual live-evidence gates registered as lowercase snake-case `allow_*` or
`run_*` tokens must be `workflow_dispatch` boolean inputs with `default: false`
and must be referenced by an `inputs.<name> == true` dispatch condition.
Scheduled live-evidence gates registered as uppercase
`WIII_*_EVIDENCE_ENABLED` tokens must be guarded by
`vars.<name> == '1'`, so nightly runtime evidence stays opt-in at the
repository/environment variable boundary. Each registry entry must declare
exactly one manual dispatch gate and exactly one scheduled vars gate; unsupported
gate-token shapes fail in the registry before workflow inspection. The live
evidence job's job-level `if:` must bind those registered manual and scheduled
gate tokens as the exact dispatch-or-schedule expression and must not add
fallback events such as `push`; the validator reads job `if:` expressions
rather than whole-file text, so mentioning the same token in an env block,
comment, setup step, or echo is not accepted as job scheduling proof.
Manual dispatch inputs must be real children of the top-level `on:
workflow_dispatch` event and declare non-comment `type: boolean` and
`default: false` fields, so commented schema hints or copied fake event blocks
cannot turn an unsafe manual input into an accepted live-run gate. Manual
dispatch input names and schema fields that control description, required
status, type, and default must not be duplicated, so a later YAML key cannot
override the opt-in `default: false` gate the validator inspected. Event names
directly under the top-level `on:` map must be unique, so a later duplicate
`push` or `workflow_dispatch` block cannot override the filtered/gated event
block the validator inspected.
Registered live env flags must be uppercase `WIII_*` environment variables,
must not reuse scheduled `_EVIDENCE_ENABLED` gate tokens, and must be assigned
as `WIII_*: "1"` inside a real workflow `env:` map. A shell `run: |` line or
unrelated YAML field that only spells the same flag is not accepted as live
runtime enablement. Workflow `env:` maps must not duplicate registered live
env flags, so a later YAML key cannot override the `WIII_*: "1"` value the
validator inspected. Every registered guard token must be an
explicit `--allow-*` lowercase kebab-case CLI flag and must appear in the same
workflow step that invokes the registered probe script. Registered probes must
be Python `.py` or Node ESM `.mjs` scripts, preventing registry entries from
pointing at arbitrary text, docs, or data files as live proof. This prevents a
workflow from passing registry validation by mentioning live-run tokens in
comments, echo statements, or unrelated setup steps. The registered probe path
is matched as a bounded command token after shell comments are stripped, so a
commented-out probe command or path-prefix spoof such as `probe.py.disabled`
cannot stand in for live evidence execution.
The live evidence job must also run `actions/checkout` with
`persist-credentials: false` before the registered probe invocation, so
artifact generation cannot rely on a checkout from another job or a checkout
that happens after registered code has already run. The checkout credential
setting must be a direct `with:` map scalar on a real checkout `uses:` step, so
commented `persist-credentials: false` hints, fake `uses: actions/checkout`
lines, or YAML-looking `- uses:` list items inside `run: |` cannot stand in for
a hardened checkout.
When a registered live probe uses a multiline `run: |` step, that step must
start with `set -euo pipefail`, so missing shell inputs and pipeline failures
fail closed before an artifact can be uploaded.
The registered probe must be invoked by a direct shell command line whose first
executed argument is the probe path (`python` / `python3` for `.py` probes or
`node` for `.mjs` probes); `echo`, `python -m ...`, or wrapper text that merely
mentions the probe path does not count. Probe guard tokens and the Python probe
`--out <artifact>` argument must be argv on that same direct probe command,
before any shell control operator; text after `;`, `&&`, pipes, or another
command cannot satisfy the probe contract.
For Python probes, the same invocation step must write the registered artifact
with `--out <artifact>` using an exact artifact filename match. Each runtime
evidence requirement must also have one workflow job that binds the registered
live env flag, probe guard, artifact validator command with the matching
`--requirement-id`, exact artifact filename, and exact artifact upload token,
so validation and upload cannot drift into a different job from the probe that
produced the payload or pass through path-prefix/token-prefix spoofing. The
artifact validator proof must be a Python command that invokes
the canonical `tools/wiii_self_harness/validate_runtime_evidence_artifact.py`
path, or `../tools/wiii_self_harness/validate_runtime_evidence_artifact.py`
from component working directories, so an `echo`, text-only mention, or
same-named validator script in another directory does not count as artifact
validation. The validator command must pass exactly one artifact positional and
exactly one `--requirement-id` value matching the registry entry, so later text
or extra arguments cannot spoof a different validation target. The same job
must order those steps as probe, then artifact validation, then upload, so
unvalidated payloads cannot be uploaded as runtime evidence. That live evidence
job must either execute
all registered contract tests itself or declare `needs: contract` against a
contract job that checks out the repo with `persist-credentials: false` before
running those registered tests and has no job-level `if:`, so scheduled/manual
evidence cannot bypass or conditionally skip the contract job. Any workflow
reference to the GitHub Actions `secrets` context, including dot or bracket
syntax, must stay inside a job whose `if:` exactly matches one registered
workflow-dispatch/schedule evidence gate pair and that job must declare
`needs: contract`. The same job must also match a registered live evidence
requirement by live env flag, probe guard, validator command, and
validation-derived upload path, so a gated sidecar job cannot hold credentials
outside the runtime proof chain; top-level, contract-job, PR, or push secret
references fail registry validation.
When a registered live probe exposes `allow_production`, its workflow must
expose a manual `allow_production` gate; the input must be manual-only,
boolean, default false, unique by input name, and free of duplicated schema
fields such as `description`, `required`, `type`, or `default`;
`ALLOW_PRODUCTION_INPUT` must derive only from `workflow_dispatch &&
inputs.allow_production || false` inside a real workflow `env:` map rather
than a comment or text block, must not duplicate within that map, and must be
bound on the same registered live probe step that appends the production
override flag; each registered probe command must receive the appended
production-override args array without resetting, unsetting, or redeclaring
that array after the append, including through shell read/mapfile builtins;
`--allow-production` may only be appended inside the explicit
`ALLOW_PRODUCTION_INPUT == "true"` shell guard. The production-override scan
ignores heredoc bodies, including non-identifier delimiter words, so copied
guard text inside generated files cannot stand in for executed shell control
flow, and it does not treat shell here-strings as heredocs.
For registered Python probes, every live guard token must also be a real
`argparse` `add_argument(..., action="store_true")` CLI flag, so comments,
constants, and docstrings cannot spoof probe-side operator acknowledgements.
For registered MJS probes, every live guard token must be enforced through a
top-level fail-closed `process.argv.includes(...)` check, and registry
validation ignores comments, nested unused functions, and template-literal
usage text when proving that guard. The MJS
`fail()` helper must exit with a non-zero literal status so a missing operator
acknowledgement cannot be logged as a successful run.
The probe-level unit contracts also force `settings.environment=production`
and prove each production-aware live probe refuses without `--allow-production`
while accepting the same guard path with the explicit acknowledgement.
Every registered live evidence job must also declare
`environment: wiii-runtime-evidence`, giving maintainers one GitHub
Environment where approvals, environment-scoped secrets, and deployment history
can be configured for runtime evidence collection.
Every registered evidence workflow job must declare a bounded
`timeout-minutes` value, which keeps stalled live probes or browser replays from
consuming runner time indefinitely and turns hangs into visible failed evidence.
Workflow job IDs must be unique inside the `jobs:` map, so a later duplicate
job cannot override the contract job or guarded live-evidence job that the
validator inspected.
Job-level control fields that determine execution order, gating, environment,
runner, timeout, or steps must not be duplicated, so a later YAML field cannot
override the safe contract dependency or live-run gate the validator inspected.
Registered evidence workflows must not enable `continue-on-error`; probe,
validator, upload, and contract failures must stop as failed CI evidence rather
than being masked by a later artifact upload.
Registered evidence workflows must also not enable shell xtrace (`set -x`,
`set -o xtrace`, `bash -x`, or `sh -x`) because traced commands can leak
secret-bearing provider and runtime arguments into GitHub Actions logs.
Registered artifact uploads must use `if: always()`,
`if-no-files-found: error`, and a bounded `retention-days` value, so failed
probe or validator runs still leave an operator-inspectable evidence artifact
when the workflow produced one, and missing evidence files fail loudly instead
of becoming upload warnings. Those upload fail-safe fields must be non-comment
YAML scalars on the real upload step or its `with:` map, so commented
`if: always()` / `if-no-files-found: error` hints or matching lines inside
multiline `path: |` bodies cannot stand in for real upload behavior. Upload
step fields and upload `with:` fields that control action identity, failure
preservation, retention, and paths must not be duplicated, so a later YAML
field cannot override the safe value the validator inspected. Each upload path
must stay to exactly one explicit repo-relative JSON evidence file whose
basename matches the registered artifact, with no globs, directory-only paths,
expressions, environment-variable or home-directory expansion, absolute paths,
repo escapes, or extra JSON sidecars, so runtime evidence uploads cannot
silently grow into raw logs or workspace snapshots.
Every `actions/upload-artifact` step in a registered evidence
workflow must bind one of that workflow's registered evidence or diagnostic
artifact filenames and upload tokens exactly through real `with:` map fields; a token that only
appears inside a multiline `path: |` scalar is ignored. The registry check also
uses the job-local artifact validation step to derive the only allowed upload
path for release evidence, while diagnostic sidecars must match their declared
registry path, missing-file policy, and retention exactly. An extra upload step
cannot reuse a registered token for a different same-basename sidecar. Extra
upload steps outside the registry contract are rejected. Registry
artifact tokens must be unique lowercase kebab-case names ending in
`${{ github.run_id }}`, so uploaded evidence can be traced to one workflow run
without mutable aliases.
Each registered evidence workflow must also include PR and push path filters as
real children of the top-level `on:` event for its own workflow file,
`tools/wiii_self_harness/**`, its probe file, and every registered
contract-test path; copied `push.paths` or `pull_request.paths` blocks under
unrelated YAML maps are ignored. Event filter keys that control paths, ignored
paths, branches, or ignored branches must not be duplicated inside `push` or
`pull_request`, so a later YAML key cannot override the path filters the
validator inspected. `paths-ignore` and `branches-ignore` are not allowed on
those events, and any explicit `branches` filter must include `main`, so a
valid-looking path filter cannot be paired with an event filter that prevents
proof-code changes from running evidence workflows. Each registered contract-test path must also
appear in the workflow text, so adding a test to the registry cannot silently
leave the GitHub Actions contract job behind. The workflow must execute each
registered contract test from a `run` step through `pytest` or `vitest`; an
`echo` line, path filter, commented-out command, or path-prefix spoof such as
`test_file.py.disabled` is not accepted as contract-test proof. The runner must
start the shell command line directly, so text emitted by `echo` or another
wrapper command cannot masquerade as a test run.
Registered contract tests must be actual Python `test_*.py` files or
TypeScript `*.test.ts`/`*.spec.ts` test files, so the registry cannot satisfy a
proof obligation with helper modules, docs, or data files. Registered workflow,
probe, and contract-test paths must not contain symlinks, so the registry
cannot read proof code through a pointer to another local file. Contract-test paths
must also be unique after normalized repo-relative path comparison, so the same
test cannot inflate coverage through equivalent path spellings.
Artifact validation commands must pass the exact registered artifact filename
after `./` normalization; validating a nested file such as
`tmp/<artifact>.json` is not accepted as proof for the artifact path that the
workflow uploads. The upload path must also match the validation step's
`working-directory` plus that filename, or the bare filename when the validation
step has no working directory, so validation and upload cannot point at
different same-basename files.
The registry validator's JSON and text summary output is self-described with
`wiii.runtime_evidence_registry_validation.v1`, so CI handoff tooling can pin
the registry-validation report contract separately from evidence payload and
bundle report contracts. It also reports the registry integer version and a
registry contract SHA-256 fingerprint over the registry name, version, and
requirements, so operators can compare the exact contract validated by CI.
Registry validation JSON and failure summaries also expose normalized
`error_codes` for registry-shape, workflow, upload, permissions, path-filter,
artifact-name, payload-check, and freshness failures, so automation does not
need to scrape raw validation text.
`validate_runtime_evidence_artifact.py` validates produced JSON artifacts
against the same registry, including artifact freshness, instead of relying on
copied inline workflow scripts. When run from the CLI, it first revalidates the
registry contract before reading the artifact payload, so a standalone artifact
gate cannot silently trust a malformed registry file. Forbidden payload tokens are matched
case-insensitively, so secret-like labels cannot bypass validation through
capitalization changes; the registry mirrors that by rejecting
case-insensitive duplicate forbidden-token entries before CI evidence runs.
Payload dot-paths support `*` only for list-wide checks, so multi-case evidence
such as browser Runtime-tab replay summaries must remain arrays and must
satisfy the registry contract for every replay case, not only the first.
The registry also supports `length_equals_path` for array cross-field
consistency, such as proving a summary's declared `case_count` equals the
actual replay case array length; object maps cannot stand in for ordered replay
arrays.
Per-artifact validation rejects symlink artifact paths before reading JSON, so
the workflow gate cannot validate a pointer to local state instead of the
produced evidence file.
Artifact JSON parsing rejects non-finite constants such as `NaN` or `Infinity`,
and numeric `min` checks treat booleans and numeric-looking strings as
non-numeric, so runtime evidence cannot satisfy duration/count thresholds with
JSON-adjacent values that are not strict finite numbers. `sorted_equals` checks
compare JSON-canonical multiset values instead of Python's native mixed-type
ordering, so malformed mixed-type lists fail as payload mismatches rather than
crashing the validator.
Manifest, registry, report, and freshness version/count fields also reject
boolean-as-integer values, so `true` cannot stand in for `1` in control-plane
contracts.
The same strict JSON stance applies to manifest, registry, report-bundle, and
bundle freshness reads: non-finite JSON constants are treated as parse failures
before report contracts or evidence freshness can be trusted, and duplicate
object keys are rejected before a later key can silently override an earlier
contract value. That parser policy is centralized in
`tools/wiii_self_harness/strict_json.py` so new control-plane readers inherit
the same behavior instead of copying local parser hooks. The strict JSON tests
also guard the runtime reader modules against direct `json.load` or
`json.loads` use, so future readers cannot bypass the shared policy silently.
Self-harness, registry, coverage, runtime-evidence bundle, and report-bundle
CLIs also reject direct/parent symlink and directory paths as `--out` report targets, so CI
handoff failures stay typed JSON errors instead of filesystem redirects or
crashes.
The artifact validator's JSON and text summary output is self-described with
`wiii.runtime_evidence_artifact_validation.v1`, distinct from the produced
artifact payload `schema_version`, so downstream gates can tell validation
result contracts apart from evidence payload contracts. Its JSON output and
failure summary also expose normalized `error_codes` and `error_code_counts`,
so CI and handoff tooling can classify and count schema, privacy, freshness,
and payload-check failures without scraping raw error text. Bundle validation
reuses the same artifact error-code taxonomy for payload validation failures,
preventing drift between per-artifact workflow gates and downloaded-bundle
handoff reports.
Even when a caller passes `--requirement-id`, artifact validation rejects files
whose filename does not match the registered artifact name, so a valid payload
cannot be silently substituted under the wrong evidence handle.
Every registered runtime evidence requirement must include payload checks that
prove raw content is absent through a `raw_content_included == false` field and
that identifiers use an approved `identifier_strategy` such as
`hash_or_count_only`, `hashes_and_counts`, `aggregate_counts_only`, or
`status_only`. This keeps OpenHuman-style provenance evidence explicit instead
of relying only on forbidden-token scans. Payload checks must also be unique by
path, operation, and condition, so a requirement cannot carry duplicate or
contradictory proof obligations for the same payload field.
Artifact upload tokens must include either the requirement ID or the artifact
stem, so a valid-looking upload name cannot drift into an opaque evidence
handle that reviewers cannot tie back to the registered proof.
For `provider-runtime-evidence.json`, the contract is scoped to the live
provider/tool-loop boundary: the direct lane must prove provider/model
authority, request/session/org hash presence, exactly one hashed tool call,
linked tool-result evidence, Wiii-native runtime boundary evidence, forced
tool-choice/tool-schema evidence, argument/content value omission, tracing-span
duration evidence, and trace-attribute omission. When the optional stream lane
is enabled, the artifact must also prove terminal runtime-ledger provider/model
authority, metadata and done events, done-count parity with the ledger, saved
finalization, sanitized post-turn-lifecycle evidence, request/session/org hash
presence, and omission of SSE data, request payloads, stream prompts, auth
secrets, provider responses, and stream payloads.
The provider workflow first runs
`scripts/probe_live_provider_runtime.py --preflight-only` to fail fast on
operator setup issues without calling a provider or replacing the live
evidence artifact. The preflight output is hash/count/status-only and does not
archive credential names or values. The workflow prints the preflight JSON to
the step log and GitHub step summary before exiting with the preflight status;
it also validates the diagnostic with
`validate_runtime_evidence_preflight.py --requirement-id provider-runtime-tool-loop`
and does not upload a separate diagnostic artifact. For the `vertex` provider,
the workflow must pass the same secret the runtime reads, `VERTEX_API_KEY`
(`settings.vertex_api_key`), before `provider-runtime-evidence.json` can be
generated.
Failed provider runtime artifacts are also redacted before upload for raw
request/session/user/org identifiers, stream prompts, API-key values, provider
credential markers, sensitive field names, UUID-like identifiers, and forced
tool argument values; they remain diagnostic-only because the registered
payload checks require a credentialed `status=pass` provider/tool roundtrip.
For `runtime-flow-browser-replay-summary.json`, the contract is scoped to the
backend-to-browser evidence lane: the exact backend artifact must render in the
desktop Runtime tab, acceptance checks must have zero failures, every replay
case must carry valid ledger/trace schemas plus route-reason hash evidence, at
least three safe sync-parity checks must pass, the summary must include backend
route counts for `lms_document_preview`,
`external_connection_status`, `external_app_action`, and `visual_generation`,
every replay case must be browser-validated via `validated_case_id_hashes`, at
least one source/document/preview case must exist, at least one complete visual
and Code Studio lifecycle case must exist, and no apply attempt may occur. The
visual lifecycle case must include terminal runtime trace evidence, and the
Code Studio case must stay on the visual/code lane instead of providerless
external-app or domain-search fallback routes.
The summary must also prove the exact backend evidence file was replayed, the
evidence SHA-256 is present, every case has a case hash, event-name hash, and
raw prompt/answer/SSE/assistant-content absence flags, and all cases were
validated by Playwright.
Every replay case must also report saved backend finalization with no
finalization error, and
`len(browser_replay.finalized_case_id_hashes) == evidence.case_count` prevents
partially finalized replay matrices from passing. The same summary must include
`wiii_connect_capability` from the live backend
snapshot endpoint with hash/count connection evidence, connected-provider/scope
hashes, five path-readiness entries, per-path reason hashes, and
`raw_content_included=false`; the path list length must match the path-readiness
count. The retained summary archive must also expose the
`wiii.runtime_flow_browser_replay_summary_archive.v1` index contract without raw
turn payloads. The summary can report aggregate doctor status
such as `degraded` when optional local or staging integrations are missing, as
long as at least one doctor path is ready; raw approval-token proof belongs to
the LMS host bridge and test-course evidence lanes.
For `lms-test-course-evidence.json`, the contract is scoped to the safe
test-course preview/apply loop: the live probe must stream through SSE V3,
finish on `lms_document_preview`, emit a preview host action, persist preview
and apply audit events, and still prove runtime apply was not attempted before
host approval. It must also post the approved patch to a credentialed external
LMS test-course endpoint using `WIII_LMS_TEST_COURSE_APPLY_URL`,
`WIII_LMS_TEST_COURSE_APPLY_TOKEN`, and `--allow-external-lms-write`; the
artifact records only endpoint/credential/request/content hashes, source-ref
counts, status-code buckets, and raw-external-request/response/token absence.
The artifact must cross-check context provenance, runtime source refs,
host-action source refs, preview audit counts, and apply audit counts; prove
preview-to-apply linkage through hashed request/preview identifiers; and carry
hash/count-only privacy flags for raw LMS documents, host-action params, audit
payloads, request identifiers, auth headers, preview credentials, approval
credentials, and external LMS credentials.
The LMS test-course lane also has a diagnostic preflight sidecar:
`scripts/probe_live_lms_test_course_replay.py --preflight-only` emits
`wiii.lms_test_course_preflight.v1` without chat, audit, or external LMS writes.
The preflight reports missing live flags, write acknowledgements, external LMS
endpoint/token setup, backend transport, and privacy-safe setup handles through
`wiii.live_evidence_setup_contract.v1`. `.github/workflows/lms-test-course-evidence.yml`
validates this JSON with `validate_runtime_evidence_preflight.py`, uploads
`lms-test-course-preflight-${{ github.run_id }}` as a 14-day diagnostic
artifact, and `--failure-from-preflight --failure-preflight-json` can materialize
a failed registered evidence artifact whose embedded `preflight` comes from the
validated sidecar. That diagnostic artifact remains fail-closed and cannot
replace a passing credentialed LMS replay.
For `subagent-boundary-evidence.json`, the contract is scoped to the live
parallel parent/child executor boundary: the replay must prove request,
session, and org hash presence, parallel task count, result count parity,
runtime-ledger `done` observation, subagent report-count parity, handoff
projected/dropped-key aggregates, result sanitization, counts for evidence
images, sources, and tools, dropped private-thinking counts, doctor aggregate
parity, and explicit raw-request, raw-secret, and raw-child-content absence.
Failed replay artifacts are also sanitized before upload: exception text is
redacted for raw markers, bearer values, sensitive field names, and raw
request/session/org identifiers. A failed artifact still cannot satisfy the
release gate because the registered payload checks require `status=pass`.
The workflow runs contract tests on PR/push, but evidence generation itself is
gated behind explicit `run_subagent_boundary_replay=true` dispatch or scheduled
`WIII_SUBAGENT_BOUNDARY_EVIDENCE_ENABLED=1`.
For `autonomy-proactive-channel-evidence.json`, the contract is scoped to
credentialed outbound autonomy: one guarded send must pass channel readiness,
database reachability for opt-out/audit behavior, request-org context, the
`can_send=allowed` guardrail, delivery, and duration telemetry. The artifact
must carry recipient/org/message hash-presence, supported-channel and credential
configuration proof, selected trigger/priority evidence, single-send contract
evidence, bounded metric-label strategy, zero blocked-guardrail metrics,
request-org opt-out/audit scope proof, send-duration observation counts,
metric-label privacy, and explicit flags proving no raw message, recipient,
organization, trigger target, metrics payload, delivery payload, credential
name/value pair, or channel credential value is archived.
The autonomy workflow runs
`scripts/probe_live_proactive_channel.py --preflight-only` before the live
send so missing recipient, channel enablement, live env flag, production
acknowledgement, or channel credentials fail early without producing a
substitute release artifact. The preflight payload uses
`wiii.proactive_channel_preflight.v1`, does not send a message, and omits raw
recipient values plus credential names and values. The workflow prints the
preflight JSON to the step log and GitHub step summary after validating the
diagnostic with
`validate_runtime_evidence_preflight.py --requirement-id autonomy-proactive-channel`;
the workflow validates before printing or uploading the preflight payload, and
removes the preflight file if validation fails. It also uploads
`autonomy-proactive-channel-preflight-${{ github.run_id }}` as a 14-day
diagnostic sidecar after validation. The registered live evidence JSON remains
the only artifact that can satisfy Runtime Evidence Registry coverage.
When the validated preflight is not dispatch-ready, the workflow materializes
the failed registered diagnostic with
`--failure-from-preflight --failure-preflight-json autonomy-proactive-channel-preflight.json`,
so the embedded `preflight` and `setup_contract` are copied from the same
validated setup diagnostic rather than rebuilt from drift-prone argv/env state.
Failed proactive-channel artifacts are also redacted before upload for
recipient identifiers, organization identifiers, message text, UUID-like
identifiers, credential name/value markers, and sensitive field names; they
remain diagnostic-only because the registered payload checks require delivery
and `status=pass`.
For `autonomy-scheduler-evidence.json`, the contract is scoped to autonomous
scheduled execution: one task must be created through the scheduler tool, found
through an org-scoped due poll, executed through the worker observability path,
delivered through WebSocket, transitioned from active to completed in the DB,
and cleaned up by default. The artifact must prove the scheduler-tool,
repository-poll, executor, delivery, DB lifecycle, metric-label, and cleanup
contracts with hashes/counts only, including explicit absence of raw scheduler
tool results, task IDs, database rows, metric payloads, descriptions, user/org
identifiers, and delivery payloads. Failed replay artifacts are also redacted
before upload for task IDs, user/session/org identifiers, descriptions, and
sensitive field names; they still cannot satisfy release evidence because the
registered payload checks require `status=pass`.
For `autonomy-heartbeat-evidence.json`, the contract is scoped to Wiii's
living-agent heartbeat boundary: a controlled heartbeat plan must be executed
by `HeartbeatScheduler`, not simulated through prompt text, and the recorded
actions must match the planned reflect/journal actions. The artifact must prove
request-scoped DB writes, core living tables checked, heartbeat/briefing deltas,
reflection and journal scope evidence, bounded action/duration metrics, and
explicit absence of raw DB rows, metric payloads, emotional state, action
targets, metadata values, briefing content, and socket payloads.
Failed heartbeat artifacts are also redacted before upload for user/session/org
identifiers, UUID-like identifiers, action targets containing those identifiers,
and sensitive field names; they remain diagnostic-only because the registered
payload checks still require `status=pass`.
For `semantic-memory-write-evidence.json`, the contract is scoped to OpenHuman-
style memory provenance: semantic-memory writes must append audit payloads
through the session-event-log boundary, the recent doctor must aggregate only
the selected org's write events, cross-org events and raw non-memory session
events must not affect the org-scoped report, blocked missing-org writes must
remain countable, and the artifact must omit raw message, response, user,
session, org, and secret-like values. The artifact and repository scenario also
require `/admin/semantic-memory/doctor/history`,
`wiii.semantic_memory_write_doctor_history.v1`, and an org-scoped
`recent_semantic_memory_write_history` bucket so memory-write trend evidence
stays aggregate-only. The same artifact now carries the runtime-flow doctor and
history response for the replayed turn, and validation requires
`wiii.post_turn_lifecycle_ledger.v1` durable counts from
`finalization.post_turn_lifecycle`, so post-turn lifecycle scheduling proof must
survive the session-event-log boundary instead of only existing in process
metrics. The frontend scenario also requires the Wiii Connect
Runtime tab to render `wiii-connect-semantic-memory-doctor-panel` and
`wiii-connect-semantic-memory-doctor-history` without raw memory markers, and
the browser Runtime-tab acceptance mocks those endpoints as part of the rendered
operator workflow.
Failed semantic-memory write artifacts are also redacted before upload for raw
memory markers, message/response text, cross-org markers, user/session/org/
request identifiers, UUID-like identifiers, and sensitive field names; they
remain diagnostic-only because the registered payload checks require
`status=pass` plus doctor/history/lifecycle evidence.
For `wiii-connect-action-evidence.json`, the contract is scoped to the backend
external-app action lane: the plan and integration lane must be ready for
`external_app_action`, the provider worker must complete through the backend
gateway/schema/audit/execute path, final answer synthesis must come from the
action-result envelope, and the artifact must omit raw provider arguments,
connection refs, account IDs, and secret-like tokens. The artifact also carries
hash-presence proof for request/session/user/org/prompt identity, provider
worker stage sequence, argument-plan keys/counts, org/user-scoped connection
lookup, execution audit stages/statuses, and privacy flags proving no raw
prompt, request identifier, audit metadata, provider payload, or final-answer
text is archived.
Failed Wiii Connect action replay artifacts are also redacted before upload for
raw prompt text, request/session/user/org identifiers, connection identifiers,
provider markers, argument markers, bearer/API-key fields, and sensitive field
names; they remain diagnostic-only because the registered payload checks
require `status=pass` plus backend gateway/audit/final-answer proof.
For `wiii-connect-facebook-post-replay-evidence.json`, the contract is scoped
to the Facebook post preview/apply mutation lane: preview must record a pending
operation approval, first apply must consume it, replay must block before
gateway/schema/provider execution, provider execution must happen exactly once,
request/session/user/org hashes must be present, approval credential and
preview evidence IDs must be represented only as hash-presence flags, storage
lookups must stay user/org scoped, audit stages must be count/status-only, and
the artifact must omit post text, Page values, connection refs, approval
tokens, API keys, account IDs, provider arguments, provider responses, request
payloads, and raw replay responses.
Failed Facebook post replay artifacts are also redacted before upload for raw
message markers, Page values, request/session/user/org identifiers, connection
identifiers, approval credentials, provider markers, bearer/API-key fields, and
sensitive field names; they remain diagnostic-only because the registered
payload checks require `status=pass` plus preview/apply/replay-block proof.
For `wiii-connect-composio-acceptance-evidence.json`, the contract is scoped to
the credentialed external-provider lane: a connected Gmail account must be
execution-ready, gateway fail-closed must reject missing connection selection,
gateway allowed must prove read scope, and a read-only provider action must
complete. The artifact now records structured, hash/count-only observations for
backend health, authentication source, provider registry, Composio adapter
readiness, durable storage, audit ledger persistence, activation readiness,
curated action enablement, fail-closed gateway behavior, selected-account
presence, live schema readiness, required argument coverage, provider execution
metadata, and privacy flags proving bearer values/env names, connection refs,
account IDs, raw schemas, provider arguments, provider responses, and provider
payloads are not archived.
The Composio acceptance workflow runs
`scripts/wiii_connect_composio_acceptance.py --preflight-only` before the live
backend run. The preflight payload uses
`wiii.connect_composio_acceptance_preflight.v1`, does not call the backend or
provider, and reports only setup booleans plus `required_next` hints for live
flag, `--allow-live`, backend URL, bearer/auth mode, connected-account flags,
and argument JSON. It omits raw backend URLs, bearer values/env names,
connection refs, and raw arguments, and it is never a substitute for the
registered credentialed execution artifact. The workflow validates this
diagnostic with
`validate_runtime_evidence_preflight.py --requirement-id wiii-connect-composio-acceptance`
before printing or uploading the payload to the step log and GitHub step
summary, removes the preflight file if
validation fails, and uploads
`wiii-connect-composio-acceptance-preflight-${{ github.run_id }}` as a 14-day
diagnostic sidecar after validation. The registered credentialed execution
artifact remains the only artifact that can satisfy Runtime Evidence Registry
coverage.
When the validated preflight is not dispatch-ready, the workflow materializes
the failed registered diagnostic with
`--failure-from-preflight --failure-preflight-json wiii-connect-composio-acceptance-preflight.json`,
so the embedded `preflight_summary` and `setup_contract` come from the validated
preflight file instead of being recomputed from current argv/env state.
`report_runtime_evidence_coverage.py` renders the registry as an
operator-readable coverage table showing requirement IDs, layers, artifacts,
artifact upload tokens, diagnostic upload counts/artifacts, schemas, workflows,
probes, tests, payload-check counts, raw-content absence counts,
identifier-strategy coverage, guards, and gates. It is also a CI gate:
each registered runtime evidence artifact must keep
`payload_checks >= freshness_hours`, so a 72-hour freshness policy cannot be
paired with a shallow proof contract.
The coverage report JSON/Markdown output uses
`wiii.runtime_evidence_coverage_report.v1` as the report-level schema, distinct
from each row's evidence payload `schema_version`. It also carries the registry
name, integer version, and contract SHA-256 fingerprint used to build the
coverage table. Registry validation failures and coverage-density gate failures
are exposed as `validation_error_codes`, `coverage_error_codes`, and a
top-level `error_codes` union plus `error_code_counts`, so handoff automation
can route and count failures without scraping Markdown text. Markdown table
cells collapse line breaks and tabs before rendering, so malformed registry
text cannot reshape the operator handoff table. When invoked with `--out`, the
coverage report refuses to write over the runtime evidence registry contract
file, direct/parent symlink output targets, or directory output targets.
Completion and release audits can invoke the report with
`--require-no-synthetic-gaps`; while any registered row remains
`synthetic_external_gap`, the report fails with
`coverage_synthetic_external_gap_present`.
The stricter `--require-credentialed-external-contracts` mode also fails
credentialed external rows that lack credential flags, live env flags, live
guard tokens, at least two dispatch/schedule gates, raw-content absence checks,
or identifier-strategy checks, returning
`coverage_credentialed_external_contract_incomplete`.
`validate_runtime_evidence_bundle.py` validates a directory of downloaded
GitHub Actions or staging artifacts against every registered runtime evidence
requirement, failing if an artifact is missing, duplicated, or violates its
payload contract. Its JSON and Markdown output use
`wiii.runtime_evidence_bundle_report.v1`, so downstream handoff tooling can
pin the report contract. When invoked with `--format json`, early CLI failures
also return that schema with `ok: false`, structured `errors`, and normalized
`error_codes`, so automation does not need to scrape stderr. Reports also
expose the validated registry name and
integer registry version next to the registry fingerprint, so operators can read
the source contract without reverse-mapping a hash. The bundle validator CLI
first revalidates the full runtime evidence registry contract, including the
workflow and proof-shape checks, so handoff cannot run against a malformed,
unversioned, unrelated, or empty registry-shaped file. The optional
`--self-harness-report-bundle` argument first validates that downloaded
self-harness report bundle with self-validation required plus
`--require-no-synthetic-gaps` and
`--require-credentialed-external-contracts`, then reads its
`runtime-evidence-coverage.json` and requires its registry fingerprint,
registry version, and `requirement_count` to match the runtime evidence
registry being used for artifact validation. This prevents a completion audit
from pairing an invalid or stale self-harness bundle generated from one
registry contract with runtime artifacts validated against another. When that
link is present, the runtime evidence bundle report includes the
self-harness report-bundle root, its bundle fingerprint SHA-256, and its
validation schema. Standalone artifact validation can still return `ok: true`;
full completion audit handoff should pass `--require-completion-audit-link` and
require the report's `completion_audit_ready` field to be `true`. The report
also emits a separate
`completion_audit_fingerprint_sha256` over the runtime evidence bundle
fingerprint plus the linked self-harness report-bundle fingerprint/schema, so
the completion-audit output is self-describing rather than relying on a
separate operator note.
`generate_completion_audit_handoff.py` wraps that strict path into a single
handoff command, writes top-level `completion-audit-handoff.json` and
`completion-audit-handoff.md` files plus `runtime-evidence-bundle-report.json`
and `runtime-evidence-bundle-report.md`, and rejects output directories inside
the runtime artifact bundle or self-harness report bundle, as well as non-empty
directories, file targets, direct symlinks, and symlink parents, so the audit
report cannot mutate the evidence set it is validating or mix old handoff files
into a new audit. After writing the four handoff reports, the generator runs
`validate_completion_audit_handoff.py` against the generated directory and
fails with `completion_audit_generated_handoff_invalid` if the final downloadable
bundle does not validate. The handoff JSON repeats the
completion-audit, runtime-bundle, and self-harness-bundle fingerprints at the
top level before nesting the full runtime evidence bundle report. When supplied
with `--allow-not-ready`, the CLI returns success only after writing and
validating a structurally valid not-ready bundle; it does not change
`release_handoff_ready`, and release gates should still require readiness
through the handoff/control-chain validators. When supplied
with `--control-chain-report`, `--setup-gap-report`, and
`--setup-gap-markdown-report`, it also binds SHA-256 source summaries for the
validated control-chain and setup-gap reports, exposes `release_handoff_ready`
separately from runtime-only `completion_audit_ready`, and carries bounded
diagnostic/non-diagnostic setup keys plus top-level `runtime_blockers` derived
from non-passed runtime rows. It also emits top-level `release_blocker_count`
and `release_blockers`, a deterministic union of runtime evidence failures,
runtime readiness fallback blockers, control-chain readiness blockers, dispatch
readiness blockers, setup-gap requirement keys, and setup-gap summary blockers
for invalid setup-gap summaries or diagnostic mismatches. Setup-gap blockers
also carry privacy-safe `resolution_actions` copied from the setup-gap report:
category/key, recommended evidence kind, safe source-handle options, binding
token count, and attestation option count. When supplied with
`--readiness-report`, the handoff also embeds a source SHA-256 summary of the
readiness report and binds each matching runtime-evidence release blocker to a
privacy-safe `recovery_action` derived from `scoped_next_actions`: workflow,
probe, live env flag, live guard, dispatch/schedule gate, artifact token,
preflight `required_next`, and normalized error-code evidence. Operators can
see the exact runtime and external setup blockers plus the next auditable
recovery action without credential values, local paths, raw error text, or raw
identifiers. The bundle
report includes each artifact's SHA-256
digest so
release and incident handoff can refer to immutable evidence bytes, plus a
registry contract SHA-256 fingerprint and bundle-level SHA-256 fingerprint over
the canonical artifact manifest, including relative artifact paths, so an
operator can compare the exact evidence contract and complete evidence set with
two stable values. Failed-row fingerprints also include normalized error codes,
not raw error text, so failure-mode changes are visible without leaking local
paths into the fingerprint manifest. The JSON and Markdown reports expose those
same normalized error codes alongside raw error text, so operators can compare
failure classes without parsing free-form messages, and include bundle-level
`error_codes` plus `error_code_counts` for quick bundle-level triage. CLI JSON
errors that occur before bundle scanning, such as malformed registries or
unsafe `--out` paths including direct/parent symlink and directory output targets, use the same
`error_code_counts` shape instead of a smaller ad hoc error payload. It also records
`validated_at`, the normalized UTC timestamp used for freshness decisions, so
handoff notes can be audited against the same clock. Each
registered runtime artifact also has a freshness policy
(`generated_at` plus `max_age_hours`) so stale evidence cannot stand in for a
current staging or release proof. Bundle validation rejects symlinked artifacts
and symlinked bundle roots, rejects resolved paths outside the bundle root
before reading JSON, and applies the same safe lowercase kebab-case
artifact-name rule before filesystem matching, so release handoff cannot
satisfy evidence with a pointer to local state or a widened glob pattern. It
also rejects duplicate requirement IDs and artifact names in the provided
registry before looking up files, so a malformed handoff contract cannot
validate the same evidence twice. Non-object registry requirement entries
become failed bundle rows instead of being skipped, so malformed handoff
contracts cannot silently reduce the evidence set. Extra non-directory bundle
entries whose artifact names are not registered, including non-JSON sidecars
such as raw logs, become failed rows, keeping bundle contents strictly tied to
the evidence registry. The bundle report surfaces an
`unexpected_count` so operators can distinguish registry-contract failures from
extra bundle contents during handoff, and keeps `requirement_count` tied to the
registry while `row_count` includes extra failed handoff rows.
`validate_completion_audit_handoff.py` validates a downloaded completion-audit
handoff bundle after upload/download. It requires the exact four generated
reports, rejects unexpected files, directories, and symlinks with distinct
`unexpected_handoff_report_file`, `unexpected_handoff_report_directory`, and
`unexpected_handoff_report_symlink` error codes, parses JSON with the strict
duplicate-key and non-finite-number checks, requires the top-level handoff
fingerprints to match the nested runtime evidence bundle report, requires
`runtime-evidence-bundle-report.json` to match the nested report as a JSON
object, rejects top-level fields outside the runtime bundle report schema with
`runtime_bundle_json_unsupported_fields`, requires the complete canonical
runtime bundle schema to be present, and verifies the registry name/version,
normalized UTC `validated_at`, bundle roots, self-harness validation schema,
and required SHA-256 fingerprints. It also requires `rows` to be a list with
canonical row fields, recomputes `bundle_fingerprint_sha256` from the row
manifest, recomputes `completion_audit_fingerprint_sha256` from the runtime
bundle and self-harness report bundle manifest, requires the handoff artifact
and self-harness roots to match the runtime report roots, requires runtime
`completion_audit_ready` to match row status plus self-harness link readiness,
requires `ok` to match `release_handoff_ready`, and recomputes
`release_handoff_ready` from runtime readiness plus any embedded control-chain
and setup-gap summaries. It also recomputes top-level `runtime_blockers` from
the nested runtime report rows, recomputes `release_blockers` and
`release_blocker_count` from runtime rows, runtime readiness, and embedded
control/setup summaries, including setup-gap blocker `resolution_actions`
parity with the summary's pending setup checks and runtime blocker
`recovery_action` parity with the embedded readiness summary's
`scoped_next_actions`,
and separately requires `row_count` to match runtime rows,
`requirement_count` to match
registered rows, registered row requirement/artifact identities to be non-empty
and unique, passed rows to have no errors, non-passed rows to carry errors,
`error_codes` to be unique, and each row's `error_codes` to match normalized
row `errors`, with `error_code_counts` holding positive counts whose keys match
`error_codes`. The canonical runtime bundle fingerprint also includes the
runtime report `schema_version`, `validated_at`, each row's reported
`age_hours`, and each row's `errors`, so handoff cannot rewrite the schema
contract, freshness decision point, rendered freshness age, or operator-facing
failure detail while preserving the same normalized error code. Row freshness
fields are also checked against the report `validated_at`: `age_hours` must
match `generated_at`, stale rows must carry
`freshness_stale`, and future timestamps must carry
`freshness_timestamp_future`. Passed rows must carry artifact path, SHA-256,
and freshness proof fields, row paths must stay under `bundle_root` with a
basename matching `artifact`, while missing rows must not carry artifact proof.
It also recomputes `passed_count`, `missing_count`, `failed_count`,
`unexpected_count`, and `error_code_counts` from row status/error-code data so
forged bundle summaries cannot pass handoff validation, then checks the
Markdown reports exactly match the JSON-derived document, including readiness,
status, roots, fingerprints, counts, error codes, report names, and each
runtime-evidence artifact table row, so extra operator prose cannot override
the machine report. Its
output uses `wiii.completion_audit_handoff_validation.v1` and includes a bundle
fingerprint over the validation schema version, report names, report SHA-256
digests, row status, raw validation error text, and normalized error codes. By
default it validates handoff integrity even when
`completion_audit_ready` is `false`, which is useful for empty-evidence smoke
runs. Release gates should add `--require-completion-audit-ready`, which fails
with `handoff_completion_audit_not_ready` unless the handoff proves
`release_handoff_ready: true`; this prevents a runtime-evidence-green handoff
from passing while setup-gap/control-chain summaries still show pending
external work. The validation policy flag itself participates
in the validation `bundle_fingerprint_sha256`, so structural handoff validation
and release-gate validation produce distinct machine fingerprints even when the
handoff is ready and both modes pass.
`generate_completion_audit_recovery_plan.py` consumes the validated
`completion-audit-handoff.json` and expands its release blockers into a
source-bound recovery artifact. Runtime evidence blockers become
`workflow_probe_recovery` action items from readiness-derived
`recovery_action`; setup-gap blockers become one `setup_resolution` action item
per privacy-safe `resolution_actions` entry; and control-chain, runtime
readiness, or setup-summary blockers become `gate_dependency` items. The plan
records action counts, the handoff SHA-256, an
`action_items_fingerprint_sha256`, closed privacy flags, and typed errors such
as `completion_audit_recovery_plan_runtime_action_missing` when a runtime
blocker lacks a concrete recovery action. The same plan also emits execution
groups with `execution_groups_fingerprint_sha256`: `setup-resolution` for
operator-owned credential/external setup, `runtime-evidence-dispatch` for
guarded workflow/probe recovery, and `release-gate-validation` for the final
validation gates. Each group carries item IDs, dependency group IDs,
`blocked_by_external_setup`, and `ready_for_autonomous_dispatch`, so later
automation can tell which work is safe to dispatch and which work is still
waiting on external setup. `validate_completion_audit_recovery_plan.py`
checks the closed plan schema, action-item and execution-group
fingerprints/counts, dependency references, privacy flags, and, when supplied
`--handoff-json`, regenerates the expected plan from the handoff source and
fails with
`completion_audit_recovery_plan_handoff_mismatch` if an operator or agent edits
the action list away from the audited handoff.
`run_completion_audit_recovery_queue.py` then turns the execution groups into a
dry-run queue report with `queue_state`, per-group `status`, dependency-blocked
groups, `next_group_ids`, and `group_status_fingerprint_sha256`. For current
upload-123 evidence the next queue entry is `setup-resolution` with
`blocked_on_external_setup`, while runtime dispatch and release-gate validation
remain dependency-blocked. `validate_completion_audit_recovery_queue.py`
checks that queue schema, counts, next groups, privacy flags, and fingerprints
match the recovery plan; with `--recovery-plan` and `--handoff-json` it
regenerates the queue from source and fails with
`completion_audit_recovery_queue_source_mismatch` on drift.
`generate_completion_audit_recovery_work_order.py` consumes the validated queue
and recovery plan to produce the next machine-readable work order. It expands
only `next_group_ids` into tasks, marks setup items as
`operator_setup_required`, marks ready runtime recovery items as
`safe_to_execute_autonomously`, records `autonomous_dispatch_allowed`, and
hashes the selected groups and tasks with `work_order_fingerprint_sha256`.
`validate_completion_audit_recovery_work_order.py` checks the closed task
schema, counts, privacy flags, state consistency, and source equality against
the queue/plan/handoff. This gives Wiii a deterministic boundary between
credential/external setup work and autonomous dispatch instead of relying on an
agent to infer next steps from prose.
`report_completion_audit_recovery_work_order_status.py` closes the next
control gap by comparing that work order with a validated setup-state artifact.
It reports each selected task as `satisfied`, `pending`,
`blocked_by_missing_setup_state`, or `ready_for_dispatch`, derives
`completed_group_ids`, `pending_group_ids`, `selected_group_complete`, and
`status_state`, and fingerprints the task statuses with
`task_status_fingerprint_sha256`. `validate_completion_audit_recovery_work_order_status.py`
regenerates the report from the work order, queue, plan, handoff, and optional
setup state, so an applied setup attestation can become auditable evidence for
advancing from `setup-resolution` to guarded runtime dispatch without letting an
agent mark a dependency complete by assertion.
`generate_completion_audit_recovery_queue_progress.py` then applies validated
work-order status evidence to the recovery queue. It treats
`completed_group_ids` as the only dependency-completion source, recomputes
per-group queue status from the recovery plan, and can advance
`runtime-evidence-dispatch` to `ready` only after `setup-resolution` is
complete. The progress artifact records `previous_queue_state`, `queue_state`,
`advancement_applied`, `next_group_ids`, `group_status_fingerprint_sha256`, and
`queue_progress_fingerprint_sha256`. `validate_completion_audit_recovery_queue_progress.py`
regenerates that artifact from the source queue, plan, work-order status,
work-order, handoff, and optional setup-state evidence, preventing an agent from
unlocking runtime dispatch without the audited setup-state transition.
`generate_completion_audit_recovery_dispatch_authorization.py` then converts a
progressed queue into a source-bound dry-run authorization artifact. It emits
`wiii.completion_audit_recovery_dispatch_authorization.v1` with
`authorization_state`, `autonomous_dispatch_allowed`, `authorized_group_ids`,
`blocked_group_ids`, `dispatch_gate_enforced`, `live_command_specs_included`,
per-item guard tokens, and `authorization_fingerprint_sha256`. Runtime
authorization is fail-closed: setup-blocked queues produce no dispatch items,
ready runtime groups must still carry workflow/probe/artifact/env/guard/gate
tokens from the recovery plan, and optional dispatch-gate evidence can further
require matched ready live command specs before commands are exposed.
`validate_completion_audit_recovery_dispatch_authorization.py` checks the
closed schema, item consistency, counts, privacy flags, fingerprint, and source
equality against queue progress, recovery plan, and optional dispatch-gate
inputs, so Wiii can decide what recovery dispatch is allowed without prompt
inference or stale hand edits.
`run_completion_audit_recovery_dispatch_authorization.py` consumes that
authorization and emits `wiii.completion_audit_recovery_dispatch_run.v1`.
Blocked authorizations stay `blocked_by_authorization` with no commands;
authorized items without dispatch-gate command specs stay
`blocked_by_missing_live_command_specs`; and command materialization happens
only when the authorization is ready and carries unlocked `workflow_dispatch`
and `local_live_probe` specs. Dry-run is the default, live execution requires
both `--execute` and `--allow-live-dispatch`, and raw stdout/stderr are never
stored. `validate_completion_audit_recovery_dispatch_run.py` checks the closed
run schema, command safety, denial rows, privacy flags, fingerprint, and
dry-run source equality against the recovery authorization chain.
`validate_completion_audit_recovery_control_chain.py` is the recovery-side
aggregate gate. It validates the recovery plan, queue, work order, work-order
status, queue progress, dispatch authorization, and dispatch run as one
source-bound chain; compares source SHA-256 and fingerprint handoffs between
each adjacent artifact; and emits
`wiii.completion_audit_recovery_control_chain_validation.v1` with
`chain_state`, `recovery_chain_ready`, `operator_setup_required`,
`autonomous_dispatch_allowed`, group lists, command count, and
`chain_fingerprint_sha256`. A setup-blocked chain can pass validation while
remaining `operator_setup_required`; any stale artifact, mismatched group
transition, or command materialized from a blocked queue fails the chain.
`generate_completion_audit_recovery_checkpoint.py` then emits a compact
source-bound resume checkpoint from that validated chain, and
`validate_completion_audit_recovery_checkpoint.py` regenerates it from the
referenced control-chain source. The checkpoint records `resume_state`, next
groups, completed/pending/authorized/blocked groups, required next inputs,
command count, the control-chain SHA-256, and
`resume_checkpoint_fingerprint_sha256`, with explicit false privacy flags for
raw output, raw evidence payload, and secret values. This gives the next
automation run a deterministic resume boundary such as `collect_operator_setup`
or `dispatch_recovery` without trusting operator prose or hand-edited JSON.
Valid local unexpected files also receive SHA-256 digests and participate in
the handoff validation bundle fingerprint, while unexpected directories and
symlinks are not hashed. Duplicate artifact matches receive a manifest
digest over relative duplicate paths, valid per-file hashes, and path errors,
so duplicate evidence also affects the bundle fingerprint without following
unsafe links. Markdown bundle output collapses table cell line breaks and tab
spacing, so malformed paths or error text cannot corrupt the operator handoff
table. CLI `--registry` and `--out` sidecar paths,
including direct symlink locations, symlink parents, and resolved targets, must be outside the bundle
root, so the validator cannot read or add unregistered files inside the evidence
directory it just checked; `--out` also rejects direct/parent symlink and directory targets
outside the bundle so report generation cannot be redirected.
Core report-output CLIs (`run_wiii_self_harness.py`,
`validate_runtime_evidence_registry.py`,
`validate_runtime_evidence_bundle.py`,
`validate_self_harness_report_bundle.py`, and
`report_runtime_evidence_coverage.py`) route final `--out` writes through
`safe_report_output.safe_write_report_text`, so their manifest/registry/bundle
specific path checks are followed by the same shared directory, direct-symlink,
and parent-symlink guard at write time.
All non-test `tools/wiii_self_harness/*.py` file writes are centralized through
that helper; `safe_report_output.py` is the only non-test module allowed to
call `Path.write_text(...)` directly. The helper writes to a same-directory
temporary file, flushes/fsyncs it, and atomically replaces the target, so CI
cannot publish half-written JSON or Markdown reports after an interrupted write.
The registry validator also binds each requirement to the exact workflow
commands that prove it: the evidence workflow must reference every registered
contract-test path, invoke `validate_runtime_evidence_artifact.py` against the
registered artifact with the matching `--requirement-id`, and upload that same
artifact path under the registered artifact token. Loose mentions of artifact
names or validator filenames are not enough to satisfy the control-plane gate;
the validator proof must be a Python command, not an `echo` or comment.
Artifact names must also stay safe lowercase kebab-case JSON file names, so
bundle validation cannot be widened by glob-pattern metacharacters.
The Python runtime probes share `scripts/runtime_evidence_output.py` and accept
`--out <artifact>.json` for UTF-8 JSON artifact writes; operators should prefer
that path over shell redirection, especially from Windows PowerShell. The shared
helper rejects direct symlink, parent symlink, and directory output targets,
then writes through a same-directory temporary file, flushes/fsyncs it, and
atomically replaces the target. Registry validation also reads the helper next
to registered Python probes and fails if the atomic temp-file primitives are
removed; it also requires the workflow contract job and path filters to include
the Python runtime evidence output helper test. The central self-harness
workflow path filters also include the Python and MJS shared output helpers and
their helper tests, so changes to evidence writer contracts rerun the manifest
and registry gates. Registry validation requires registered Python probes
to define `--out` as an actual `argparse.add_argument(...)` CLI flag and to
import `emit_json_payload` from that helper, so a local function with the same
name cannot bypass the shared output guard. It also requires an
`emit_json_payload(..., out_path)` call, so a probe cannot merely mention
`--out` while silently writing evidence through a side channel. Registered
Python probes are also forbidden from direct evidence file writes such as
`write_text`, write-mode `open` with literal or constant write modes, aliased
`io.open`/`codecs.open`/`builtins.open`, aliased `json.dump`, imported `dump`,
and low-level `os.open`/`os.write`, keeping evidence emission behind the shared
guard.
Registry validation also requires
registered MJS evidence wrappers to
parse `--out` from `process.argv`, assign the same returned output property
from both `--out <path>` and `--out=<path>` branches, and forward that parsed
path into `WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON`; their workflow
command must pass the exact registered artifact path on the `node ...probe...`
invocation, and the parsed summary env binding must live inside the
`spawnSync(process.execPath, [runner, ...forwarded], ...)` runner options before
the wrapper reaches the shared `runtime-evidence-output.mjs` writer, which
rejects direct symlink, parent symlink, and directory output targets, then
writes through a same-directory temporary file, fsyncs it, and atomically
renames it into place. Registry validation reads the sibling
`runtime-evidence-output.mjs` helper and fails if its atomic temp-file
primitives are removed; it also requires the workflow contract job and path
filters to include `test-runtime-evidence-output.mjs`. Registered MJS probes are also forbidden from raw `node:fs`
and `node:fs/promises` evidence writes such as `writeFileSync`,
`fs.writeFileSync`, `fs.promises.writeFile`, or aliased `writeFile` imports
from `node:fs/promises`, including destructured dynamic-import aliases from
`await import("node:fs")` or `await import("node:fs/promises")`, plus
destructured `require("node:fs")` or `require("node:fs/promises")` aliases,
and default-export aliases such as `fs.default[writer](...)` or
`fsDefault[writer](...)`; destructured aliases with default initializers such
as `writeFileSync: writer = null` are rejected the same way; destructured
`promises` namespaces from `node:fs`, such as
`const { promises: fsPromises } = require("node:fs")`, are also rejected when
they call `writeFile`/`appendFile` directly or through a computed writer; inline
module expressions such as `require("node:fs")[writer](...)` or
`(await import("node:fs/promises"))[writer](...)` are rejected as well;
dot, bracket, and optional-chain property calls such as `fs.writeFileSync(...)`,
`fs["writeFileSync"](...)`, `fs[writer](...)`, and
`fs[promisesBucket][writer](...)`, including `fs?.[writer](...)` and
`fs?.[promisesBucket]?.[writer](...)`, are rejected when the computed property
is a literal string or string constant. Dynamic `import(...)` and
`require(...)` module specifiers are also rejected when `node:fs` or
`node:fs/promises` is hidden behind a string constant, including simple
concatenated constants such as `"node:" + "fs"` or `"write" + "FileSync"`.
The only accepted file write path for browser replay JSON remains the shared
`runtime-evidence-output.mjs`
helper reached through the guarded summary environment.
The backend runtime-flow acceptance harness also routes its
`--evidence-json` backend replay export through `emit_json_payload`, so the
exact-file browser replay input gets the same UTF-8, direct-symlink,
parent-symlink, and directory output-target guard as live Python evidence
probes.

The comprehension-reference scenario is intentionally static. It validates the
adoption decision, ignore rules, wrapper files, wrapper unit tests, and workflow
triggers; it does not require generated `.understand-anything/` output to
exist.

## Extension Rules

Add or change a scenario when a product-critical contract becomes important
enough that losing it would create high-risk debt.

Each scenario should include:

- the active Wiii layer affected by the contract
- the risk level
- the concrete contract in one sentence
- invariants that should stay true
- runtime, test, docs, or CI evidence files
- focused verification commands

Do not add broad directory checks or vague evidence. A path should prove a
specific contract, not merely show that a subsystem exists.

## CI

`.github/workflows/wiii-self-harness.yml` runs the manifest validator, runtime
evidence registry validator, runtime evidence coverage report, Self-Harness
unit tests, and Understand-Anything wrapper unit tests when harness files,
evidence workflows, or covered product contracts change. The workflow uses
only Python and does not install backend or desktop dependencies. The
`self-harness` job declares `timeout-minutes: 20`, and the harness unit tests
assert that bounded timeout stays present, so the central control-plane gate
fails clearly instead of hanging indefinitely. Those tests also require every
`uses:` step in the central workflow to stay on the approved core-action
allowlist and be pinned to a 40-character commit SHA. They also require the
central workflow to keep top-level `permissions: contents: read`, avoid
job-level permission overrides, and keep pull-request-scoped concurrency
cancellation. After the validators, smoke, Self-Harness unit tests, and
Understand-Anything wrapper unit tests have run, the final `if: always()`
upload step archives `wiii-self-harness-reports-${{ github.run_id }}` with
`self-harness-validation.json`, `runtime-evidence-registry-validation.json`,
`runtime-evidence-coverage.json`, `runtime-evidence-coverage.md`, and
`self-harness-report-bundle-validation.json`, plus a completion-audit smoke
handoff report generated from an intentionally empty runtime-evidence directory,
so CI handoff can inspect machine-readable report contracts after success or
failure without uploading before later gates have executed. The workflow calls
`tools/wiii_self_harness/generate_self_harness_report_bundle.py`, so report
generation, UTF-8 writes, pre-self validation, self-validation report creation,
and final `--require-self-validation` checking stay inside Python instead of a
multi-command shell script. The generator requires its output path to be a real
directory when it already exists, and that directory must be empty or absent
before generation, so stale report files cannot be mixed into a new CI handoff
bundle or overwritten through a file path. It also rejects symlink output
directories and symlink output-directory parents before writing any report, so
CI cannot write the handoff through an unexpected resolved target.
The workflow then runs `validate_self_harness_report_bundle.py` as an explicit
CLI step with `--require-self-validation`, `--require-no-synthetic-gaps`, and
`--require-credentialed-external-contracts`, writing
`artifacts/wiii-self-harness-report-bundle-validation.json` outside the report
bundle. That sidecar is uploaded with the bundle so operators can inspect an
independent validation result without trusting only the generator summary or
the recursive in-bundle self-validation file.
The workflow also renders runtime evidence coverage Markdown with
`--require-no-synthetic-gaps` and
`--require-credentialed-external-contracts`, so the operator-facing coverage
table fails under the same strict external-evidence contract as the generated
bundle and sidecar validation.
The workflow then runs `smoke_completion_audit_handoff.py` against the
generated self-harness bundle and an empty runtime-evidence directory. The smoke
script calls `generate_completion_audit_handoff.py` internally and asserts
`completion_audit_ready: false` with `missing_artifact` errors, then validates
the generated smoke handoff bundle with `validate_completion_audit_handoff.py`.
The smoke summary also includes `release_gate_validation`, proving the same
handoff fails the release gate with `handoff_completion_audit_not_ready` when
`--require-completion-audit-ready` is enforced. The smoke assertion requires
the structural validation payload to carry `require_completion_audit_ready:
false`, the release-gate payload to carry `require_completion_audit_ready:
true`, and their validation fingerprints to differ. The workflow writes that
strict release-gate result to
`artifacts/wiii-completion-audit-smoke-release-gate-validation.json` as a
separate uploaded artifact, so release-gate rejection remains inspectable
without parsing the smoke summary. The smoke command rejects `--json-out` and
`--release-gate-json-out` sidecars inside the generated handoff bundle, the
empty runtime-evidence input bundle, or the self-harness report input bundle,
including resolved symlink targets, and rejects duplicate sidecar paths,
direct/parent symlink targets, or directory targets before generation. This
prevents the smoke summary from mutating a bundle after structural validation
has already read it. The workflow also runs the validator CLI as a separate
step and writes
`artifacts/wiii-completion-audit-smoke-validation.json`, so the uploaded CI
artifact contains the smoke summary, the strict release-gate validation, and the
standalone structural handoff validation report. The next workflow step runs
`validate_completion_audit_smoke.py` against those three JSON files and rejects
any mismatch between the smoke payload's embedded structural/release-gate
validation objects and the uploaded sidecars. It also re-checks the empty
evidence contract, opposite `require_completion_audit_ready` policy modes, and
distinct validation fingerprints. With `--require-handoff-root-source`, it
reruns both structural and release-gate validation against the current
`handoff_root` and rejects stale sidecars that no longer match the generated
bundle. That smoke path proves the
strict completion-audit handoff path is wired
into CI without requiring live evidence artifacts on every self-harness run.
The workflow also writes
`artifacts/wiii-completion-audit-readiness-non-lms.json` with
`report_completion_audit_readiness.py` using
`--exclude-requirement-id lms-test-course-replay`. That report gives operators a
machine-readable non-LMS progress view with both `full_completion_audit_ready`
and `scoped_completion_audit_ready`; it also exposes the linked self-harness
report bundle fingerprint and validation schema used to compute readiness. With
`--preflight-dir`, it also attaches privacy-safe setup diagnostics from known
live-evidence preflight JSON files to the matching requirement after validating
the raw diagnostic with `validate_runtime_evidence_preflight.py`. Validation
commands that consume readiness can supply `--preflight-dir` or
`--readiness-preflight-dir` more than once, so downloaded runtime-evidence
artifacts and separately uploaded setup-preflight artifacts stay source-bound
without copying them into a staging directory. When `--preflight-dir` is absent,
the reporter can fall back to a valid embedded
`preflight` or `preflight_summary` inside the registered failure artifact for
the same requirement; this only carries setup diagnostics into next actions and
does not turn failed runtime evidence into passed evidence. Proactive
channel, LMS test-course, and Composio acceptance preflights also carry a closed
`setup_contract` with safe workflow input names, credential slot categories,
external setup categories, `required_next`, and `dispatch_ready`; the validator
checks this contract against the preflight status without allowing raw secret
values or credential env names into the diagnostic. The report
includes `scoped_next_actions` for every included missing/failed requirement,
carrying the registry workflow, probe, dispatch/schedule gates, live guard
tokens, expected artifact token, registered diagnostic upload metadata, current
error codes, `blocked_by_live_setup`, and any matching preflight status plus
`required_next` hints. The report also exposes
`full_live_setup_blocked_count`,
`full_live_setup_blocked_requirement_ids`,
`scoped_live_setup_blocked_count`, and
`scoped_live_setup_blocked_requirement_ids`, so operators can separate real
runtime evidence failures from requirements still waiting on live credentials,
approved recipients, backend URLs, or other external setup. The
report also exposes
`preflight_summary_count`, `preflight_summaries`, each preflight source
SHA-256, validation schema, validation `ok` flag, and validation error codes,
`scoped_next_action_count` and
`scoped_next_actions_fingerprint_sha256`, a canonical SHA-256 digest of the
readiness report schema plus action list.
`validate_completion_audit_readiness.py` then checks that JSON artifact for
schema, count/list consistency, scope/exclusion consistency, readiness blocker
parity, live-setup-blocked count/list parity, next-action count/fingerprint
parity, preflight summary/next-action parity, optional raw preflight source
SHA-256/source-payload parity when
`--preflight-dir` is supplied, including embedded `artifact.json#preflight`
and `artifact.json#preflight_summary` sources, error-code provenance, and
self-harness link fields. With `--markdown-report`, it also compares the operator-facing
readiness Markdown to the validated JSON payload, so uploaded readiness prose
cannot drift from the machine contract. With `--self-harness-report-bundle`,
it revalidates the supplied self-harness report bundle with self-validation
required and compares its fingerprint/schema to the readiness JSON, so a
readiness report cannot silently point at a stale harness bundle.
`generate_completion_audit_run_plan.py` turns that validated readiness report
into a closed-schema operator run plan. Its `--preflight-dir` option may also
be repeated, because the generator validates readiness source parity before it
emits a plan. Each run item preserves the readiness
requirement ID, workflow, workflow-dispatch input, schedule env flag, live probe
env flag, live guard token, expected artifact token, diagnostic artifact token,
current error codes, preflight source SHA-256, preflight validation
schema/result, and translated operator setup actions such as approved
recipient, backend URL, or credential configuration. Its `execution_state`
remains `blocked_on_live_setup` while a preflight is `fail`, while
`validate_completion_audit_run_plan.py` recomputes the run-item fingerprint from
the run-plan schema, readiness schema, `scoped_next_actions` fingerprint, and
run-item payload, and can match the plan back to the readiness report SHA-256.
The run plan also emits structured
post-run verification specs with `step_id`, `working_directory`, `argv`, and
`uses_shell=false`, and validates that the human-readable command strings match
the rendered argv sequence. The canonical post-run sequence regenerates
readiness JSON and readiness Markdown, then validates the readiness JSON with
`--markdown-report <readiness-markdown>` before regenerating the downstream
run-plan, launch-pack, setup-state, and dispatch-gate artifacts. Those specs
also carry their own schema-bound SHA-256
fingerprint, so automation can detect verification-contract drift without
hashing the whole artifact. The run plan also fingerprints the operator setup
contract for each live blocker: required actions, credential/external setup
tokens, workflow gates, and preflight required-next state. It also fingerprints
the acceptance contract: expected artifact, expected schema/result, and
accepted-when checks for every live blocker. Those setup and acceptance
fingerprints are also bound to the run-plan schema. With `--markdown-report`,
`validate_completion_audit_run_plan.py` compares the operator-facing Markdown
handoff to the run plan regenerated from the supplied readiness report, so
uploaded run-plan prose cannot drift from the JSON contract. When supplied with
`--readiness-markdown-report`, `--readiness-preflight-dir`, and
`--self-harness-report-bundle`, the same validator also asks the readiness
validator to re-check the source readiness Markdown, preflight diagnostics, and
self-harness bundle before trusting the run-plan source. The
`--readiness-preflight-dir` option may be repeated, matching the control-chain
validator and keeping mixed embedded/raw preflight sources bound to their
original uploaded artifacts. The plan is an
operator handoff for closing blockers; it is not a substitute for live evidence
and does not change the full completion-audit release gate.
`generate_completion_audit_launch_pack.py` then converts the run plan into
privacy-safe launch templates for the supported live blockers. For the current
non-LMS blockers it emits `gh workflow run` commands, local preflight commands,
local failure-from-preflight commands bound to the validated preflight JSON,
local live probe commands, preflight/artifact validator commands, artifact
download commands, preflight diagnostic artifact download commands, and the
required GitHub input/var/secret names for `autonomy-proactive-channel` and
`wiii-connect-composio-acceptance`. Each launch command also carries a
structured `working_directory` plus `argv` spec with `uses_shell=false`; the
human-readable command string is a template, while the structured spec is the
machine-validated execution contract. Validation also requires the template to
match the rendered `argv`, so operator-facing prose cannot drift away from the
machine-run command. The failure-from-preflight specs must include
`--failure-from-preflight`, `--failure-preflight-json`, the local preflight
output path, and the registered failed-evidence artifact path, keeping setup
diagnostics source-bound without shell branching. The launch pack also binds each safe
`setup_contract` token to concrete launch surfaces through
`preflight_setup_contract_bindings`: workflow input names/CLI flags,
live-env flags, credential handles, and external setup handles. The launch-pack
validator requires those bindings to cover every contract token and to point at
tokens that actually appear in the command specs, GitHub input/var/secret
lists, environment variables, or operator action tokens. This keeps setup
contracts actionable without adding secret values or raw recipient/backend
payloads to the contract itself. The launch item fingerprint is bound to the
launch schema, run-plan schema, run-plan item fingerprint, run-plan setup
fingerprint, and run-plan acceptance fingerprint. Launch setup, acceptance,
command-spec, and post-launch verification fingerprints are also schema-bound
and source-bound to their matching run-plan fingerprints, so the launch handoff
cannot silently relax setup, command, verification, or acceptance proof after
the run-plan handoff is generated. The launch pack also preserves the run-plan's
source fingerprints as explicit fields, and source validation checks those
values against the supplied run plan.
`validate_completion_audit_launch_pack.py` checks the launch pack schema,
command coverage, structured launch-command specs, structured post-launch
verification specs, setup fingerprints, acceptance fingerprints,
command/spec fingerprints, privacy flags, launch-item fingerprint, and optional
run-plan SHA-256/source parity. The post-launch verification contract preserves
the run-plan's readiness Markdown generation and validation step, and also
regenerates the setup-state plus fail-closed dispatch-gate artifacts from the
validated launch pack, so operators cannot complete a launch with stale
readiness prose or a detached live-dispatch gate. With `--markdown-report`,
it also compares the
operator-facing Markdown handoff to the launch pack regenerated from the
supplied run plan, so uploaded prose/templates cannot drift from the
machine-validated JSON contract. With `--repo-root`, the validator also checks
that each referenced workflow and probe source file exists and that the
workflow still contains the declared input, variable, secret, artifact, and
conditional-secret tokens. The launch pack contains only placeholder values and
secret names, never credential values or raw recipient/backend payloads.
`generate_completion_audit_setup_state.py` then converts the launch pack's
binding map into a privacy-safe setup-state JSON artifact. With `--repo-root`,
the generator marks only workflow-input handles that are proven by the
source-controlled launch command contract. Environment flags, credential
slots, approved recipients, backend connectivity, and external account setup
stay pending until separate live setup evidence supplies them. The state can be
structurally valid with `ok=true` while `dispatch_ready=false`, because those
live setup requirements are still unresolved. Operator or CI automation can
mark individual setup checks as present only by using a safe `source_handle`
that already appears in the launch pack binding tokens, not by writing secret
values, backend URLs, recipient IDs, or other raw identifiers into the state.
`validate_completion_audit_setup_state.py` checks
the closed setup-state schema, per-check privacy flags, source-handle binding,
ready/pending count parity, setup-state fingerprint, and optional launch-pack
source parity. When `--launch-pack` is supplied, the validator rejects stale
launch-pack hashes and any changed setup requirement shape, while still
allowing operator-owned `present`/`source_handle` readiness changes.
`generate_completion_audit_setup_handle_plan.py` then renders the pending
checks into a privacy-safe handle plan with exact recommended
`requirement_id:category:key=source_handle` specs and matching
`requirement_id:category:key=source_handle@evidence_kind:evidence_ref`
attestation specs for every available binding token.
`validate_completion_audit_setup_handle_plan.py` checks the plan against the
setup-state source, plan fingerprint, allowlisted evidence kinds, and
per-token attestation coverage.
`report_completion_audit_setup_gaps.py` renders the same pending setup plan
as `wiii.completion_audit_setup_gap_report.v1` and can merge the current
failed proactive, LMS test-course, and Composio evidence artifacts from
`--runtime-evidence-dir` or explicit `--proactive-channel-evidence`,
`--lms-test-course-evidence`, and `--composio-acceptance-evidence` paths.
It stays privacy-safe by reporting only counts, source-handle options,
artifact SHA-256s, `required_next` labels, and mapped setup keys. When a
failed preflight says a handle is still required but the setup-state claims
that handle is present, the report sets `setup_diagnostics_consistent=false`
and records `diagnostic_present_setup_mismatches`; this is a diagnostic for
stale or miswired live-evidence runs and never unlocks dispatch.
The summary also splits pending checks into
`diagnostic_pending_setup_check_count` and
`non_diagnostic_pending_setup_check_count`, so operators can separate the
current preflight blocker from remaining setup-contract attestations. Each
requirement also carries bounded `diagnostic_pending_setup_keys` and
`non_diagnostic_pending_setup_keys` entries in `category:key` form for the same
handoff without exposing credential values or raw identifiers.
`validate_completion_audit_control_chain.py --setup-gap-report` can then bind
that gap report back to the exact setup-handle plan SHA-256 and requires the
report to keep its privacy flags false, so stale or hand-edited setup-gap
diagnostics cannot pass the source-bound control chain.
`validate_completion_audit_setup_gaps.py` provides the standalone gate for the
same artifact: it validates the closed report schema, count/fingerprint
consistency, diagnostic mapping/mismatch parity, privacy flags, and optional
`--setup-handle-plan` source parity before CI or an operator trusts the report.
With `--markdown-report`, it also checks that the operator-facing Markdown
summary and per-requirement lines match the JSON report, and control-chain can
carry that same Markdown path with `--setup-gap-markdown-report`.
`generate_completion_audit_setup_attestation_template.py` converts that plan
into a pending operator template containing only safe source-handle options and
attestation spec options. It leaves `selected_attestation_spec` and
`operator_evidence_ref_handle` empty by contract, and
`validate_completion_audit_setup_attestation_template.py` rejects any template
that tries to preselect evidence, carry raw identifiers, or drift from the
source setup-handle plan. The template is an operator handoff artifact only; it
does not unlock dispatch.
After an operator chooses safe options from that template,
`generate_completion_audit_setup_attestation_from_template.py` converts those
exact `--select` values into the stricter setup-attestation artifact and
optional setup-handle patch. It rejects selections that do not come from the
template, duplicate choices for the same setup check, and incomplete selections
when `--require-all-pending` is used.
`smoke_completion_audit_setup_attestation.py` exercises that path in CI as a
sidecar-only mechanism check: it selects one safe option for each pending
template check, emits a strict setup attestation, applies it to a copied
setup-state artifact, generates an attested dispatch gate, and materializes the
dispatch run in dry-run mode only. The smoke proves the template-to-dispatch
unlock path remains wired, while the production non-LMS setup-state,
dispatch-gate, dispatch-run, and control-chain artifacts still reflect the
real current readiness state and remain fail-closed until live setup evidence
is actually supplied. `validate_completion_audit_setup_attestation_smoke.py`
then reloads that sidecar JSON and revalidates the generated attestation,
derived patch, attested setup-state, dispatch gate, and dispatch-run reports
against their source artifacts, so a hand-edited smoke sidecar cannot pass CI.
`generate_completion_audit_setup_handle_patch.py` turns explicit operator or
CI setup handles into a source-bound patch without requiring hand-written JSON:
each repeated `--handle` uses
`requirement_id:category:key=source_handle`, and the generator copies the
current setup-state SHA-256/schema/fingerprint into the patch before validating
that every handle is bound to the target setup check.
`generate_completion_audit_setup_attestation.py` is the stricter live-setup
path: each repeated `--attest` binds a setup handle to an allowlisted evidence
kind and safe evidence reference using
`requirement_id:category:key=source_handle@evidence_kind:evidence_ref`. It can
also emit the matching setup-handle patch with `--patch-out`, and
`validate_completion_audit_setup_attestation.py` verifies that the attestation,
patch, and current setup-state source all match before anything is applied.
This lets CI or operators unlock dispatch through a machine-checkable setup
evidence artifact without storing credential values, raw recipients, backend
URLs, provider account IDs, or provider payloads.
`generate_completion_audit_setup_attestation_from_handles.py` is the
automation-friendly variant: it consumes a closed-schema
`wiii.completion_audit_setup_handle_evidence.v1` file bound to the current
setup-handle plan SHA-256/fingerprint and setup-state source, then emits the
same attestation plus optional patch. It only accepts handles for pending setup
checks when the source handle matches a binding token and the evidence kind
matches the plan recommendation, so CI can draft setup attestations from safe
proof handles without reading credential values or raw external identifiers.
`probe_completion_audit_setup_handle_evidence.py` can produce that evidence
file from local CI/runtime environment presence after explicit
`--allow-env-read`. It supports truthy environment-flag proof,
secret-present, variable-present, approved-recipient, and backend-health
handles, writes only source handles and evidence refs, and requires
`--allow-network` before checking backend health.
It can also consume a sanitized
`wiii-connect-composio-acceptance-evidence.json` pass artifact through
`--composio-acceptance-evidence` to prove only the Composio connected-provider,
execution-gateway policy, and read-only schema handles. The probe requires the
artifact to be a registered pass artifact with passing check statuses, safe
privacy flags, and read-only scope/schema proof; failure and preflight-only
artifacts produce no handles. Composio-derived evidence refs include the
acceptance artifact SHA-256 and still omit provider account IDs, connection
refs, backend URLs, provider arguments, provider responses, and raw schemas.
It can also consume a sanitized `autonomy-proactive-channel-evidence.json`
pass artifact through `--proactive-channel-evidence` to prove only the
proactive runtime channel credential, approved-recipient, and selected-channel
handles. That path requires delivered live-send proof, operator approval
acknowledgement, recipient hash presence, configured channel/credential proof,
database guardrail scope, delivered metrics, and false raw-identifier/raw-
payload privacy flags. Failure and preflight-only artifacts produce no handles;
proactive-derived evidence refs include the artifact SHA-256 and still omit raw
recipient IDs, organization IDs, message text, credential values, delivery
payloads, and metric payloads.
For normal post-run operation, pass the downloaded runtime evidence bundle with
`--runtime-evidence-dir <bundle-dir>` instead of naming each artifact. The probe
only inspects the canonical `autonomy-proactive-channel-evidence.json` and
`wiii-connect-composio-acceptance-evidence.json` files from that directory,
including standard downloaded-artifact subdirectories. Duplicate canonical
matches and symlinked artifact paths fail closed; the explicit artifact flags
remain available when a caller needs to bind a single known file. Missing,
failed, preflight-only, or schema-drifted bundle artifacts still produce no
setup handles. In the generated post-run chain,
`validate_runtime_evidence_bundle.py` first writes
`<runtime-evidence-bundle-report-json>`, and the setup-handle probe receives
that report through `--runtime-evidence-bundle-report`; canonical artifacts
must have passed bundle rows with matching SHA-256 before they can contribute
setup handles.
`promote_completion_audit_runtime_evidence.py` wraps that post-run promotion
path for repeatable CI/operator use: it requires the validated bundle report to
be `ok=true` and `completion_audit_ready=true`, probes setup handles from the
bundle with matching row SHA-256, writes setup-handle evidence, generates and
applies the setup attestation, emits an attested dispatch gate, and materializes
a dry-run dispatch report. It never executes live dispatch; incomplete bundle
reports, missing handles, stale sources, or still-pending setup produce
`wiii.completion_audit_runtime_evidence_promotion.v1` with `promotion_ready=false`.
Generated run plans and launch packs include a source-bound sidecar path that
uses this bundle probe to write `<setup-handle-evidence-json>`, generate
`<setup-attestation-json>`, apply it into `<setup-state-attested-json>`, and
materialize `<dispatch-gate-attested-json>` / `<dispatch-run-attested-json>` in
dry-run. The canonical pending setup-state and control-chain reports remain
available, so partial evidence produces an explicit pending sidecar report
rather than silently unlocking live dispatch.
It fails closed with no usable handles rather than marking setup ready from
absence of evidence.
`apply_completion_audit_setup_attestation.py` is the direct apply path for
that stricter artifact: it validates the attestation against the current
setup-state and optional launch-pack source, derives the setup-handle patch
internally, calls the canonical setup-state applier, and emits a standard
setup-state artifact. CI does not need to persist or hand-edit a separate patch
file, while stale sources, raw evidence references, unbound handles, secrets,
backend URLs, recipients, provider account IDs, and provider payloads remain
rejected before dispatch can unlock.
`apply_completion_audit_setup_state.py` is the canonical way for an operator
or CI job to apply those readiness changes: it consumes a closed-schema
`wiii.completion_audit_setup_handle_patch.v1` patch, accepts only safe
`source_handle` values that already appear in the target check's
`binding_tokens`, requires the patch's setup-state SHA-256/schema/fingerprint
to match the current source setup-state, recomputes the setup-state counts and
fingerprint, and emits another standard setup-state artifact. Raw secrets,
backend URLs, recipient IDs, provider account IDs, stale setup-state sources,
and free-form identifiers are rejected before the state can be used to unlock
dispatch. `validate_completion_audit_setup_handle_patch.py` runs the same
schema, source-binding, setup-check, and privacy checks as a standalone CI or
operator preflight before the patch is applied.
`generate_completion_audit_dispatch_gate.py` consumes the launch pack and
setup-state together and emits a fail-closed dispatch gate. While any setup
requirement is pending, the gate remains structurally valid but keeps
`dispatch_ready=false` and requires `unlocked_live_command_specs` to be empty.
Pending items may carry `blocked_diagnostic_command_specs.local_failure_from_preflight`
from the validated launch pack so operators and CI can materialize a source-bound
failed diagnostic artifact without opening live dispatch.
Only after the setup-state proves every setup check present through safe source
handles does the gate copy the launch pack's `workflow_dispatch` and
`local_live_probe` command specs into the unlocked section and clears blocked
diagnostic command specs. The gate still
contains templates and handles only; it does not store secret values,
credential values, raw recipient IDs, backend URLs, provider account IDs, or
raw probe payloads. `validate_completion_audit_dispatch_gate.py` recomputes
the dispatch-gate fingerprint, checks setup-handle safety, command-spec shape,
pending/ready count parity, and source parity against both `--launch-pack` and
`--setup-state`, so automation cannot unlock live dispatch by editing the gate
artifact alone.
`run_completion_audit_dispatch_gate.py` is the final command boundary: it
validates the gate against launch-pack and setup-state sources, refuses to
materialize live commands while `dispatch_ready=false`, and writes a
privacy-safe dispatch-run report with `ok=false` when `--allow-pending-report`
is used for the current not-ready handoff. Pending reports may expose
`diagnostic_commands` materialized from
`blocked_diagnostic_command_specs.local_failure_from_preflight`; those commands
remain unexecuted, do not count toward `command_count`, and only describe how to
write the failed registered diagnostic from the validated preflight JSON.
Actual live execution requires both `--execute` and `--allow-live-dispatch`;
even then the report records only argv, exit codes, and booleans, never raw
stdout, stderr, secrets, credentials, or recipient/backend identifiers.
`validate_completion_audit_dispatch_run.py` then checks that report as a
closed-schema artifact and, with source paths, regenerates the dry-run report
from the current dispatch gate so stale, hand-edited, live-command-materializing
pending reports or ready reports carrying blocked diagnostics cannot pass.
`run_completion_audit_dispatch_diagnostics.py` consumes that validated pending
dispatch-run report and creates a separate
`wiii.completion_audit_dispatch_diagnostics.v1` artifact for the non-live
diagnostic commands. It is dry-run by default, refuses ready dispatch reports,
can add `--preflight-source-dir <dir>` to prove each command's preflight source
from the launch-pack `preflight_source_file`, and requires
`--execute --allow-diagnostic-execution --preflight-source-dir <dir>` before it
stages a validated preflight JSON into the probe working directory and writes
failed registered diagnostics. Source-bound dry-runs also rebind placeholder
argv values such as `<approved-channel>`, `<backend-url>`, and
`<backend-base-url>` to parse-safe diagnostic values derived from the validated
preflight contract, so execute mode no longer depends on operator-side shell
substitution. A diagnostic command may return the probe's intentional failure
code after writing a failed registered artifact; the runner marks it
`execution_ok=true` only when the output artifact exists, hashes cleanly, and
contains an embedded preflight that still validates. The report records
`preflight_stages`, `source_sha256`, `target_sha256`, `argv_rebound`,
`unresolved_placeholder_count`, `output_artifact_sha256`,
`output_artifact_validated`, validation status, and whether staging occurred,
while still omitting raw stdout, stderr, secret values, credential values, and
raw identifiers.
`validate_completion_audit_dispatch_diagnostics.py` validates that diagnostic
artifact as a separate source-bound report, regenerating the dry-run from the
current dispatch-run source and the same optional `--preflight-source-dir`
inputs so diagnostic command execution cannot be confused with live dispatch
readiness or an unstaged local file.
`validate_completion_audit_control_chain.py` ties those artifacts together as
one source-bound chain: readiness, run-plan, launch-pack, setup-state,
setup-handle plan, optional setup-attestation template/smoke unlock path,
optional real attested setup/dispatch chain, dispatch-gate, dispatch-run,
optional dispatch-diagnostics, and optional `--recovery-control-chain` must all
validate against their immediate sources. Their SHA-256 links must match,
repeated readiness preflight source directories must bind mixed embedded/raw
preflight summaries back to their original artifacts, the setup-attestation
smoke sidecar must revalidate its generated attestation, patch, attested setup
state, attested dispatch gate, and dry-run dispatch reports when supplied, and
the same generated attested artifacts can be supplied directly with
`--setup-attestation`,
`--setup-attestation-patch`, `--attested-setup-state`,
`--attested-dispatch-gate`, and `--attested-dispatch-run`. When that real
attested chain is supplied, the control-chain requires the attested setup
state, attested dispatch gate, and attested dispatch run to be dispatch-ready
and the attested dispatch run to be `ok=true`. The base pending dispatch path
must still keep live commands empty, keep diagnostic commands unexecuted, keep
diagnostic materialization source-bound when supplied, and remain marked
`gate_not_ready`. When a recovery control-chain report is supplied, the
top-level validator replays it from embedded recovery source paths, compares
state and fingerprint fields, exposes recovery readiness flags, and requires
`release_gate_ready: true` before aggregate `control_chain_ready` can become
true. When `--recovery-checkpoint` is also supplied, the validator validates
the checkpoint against the same recovery control-chain, compares its state,
group, command-count, and fingerprint fields back to that chain, and exposes
the aggregate `recovery_resume_state` plus `recovery_required_resume_inputs`.
The same validator supports `--out <json>` for CI handoff; output paths are
rejected when they are directories, direct symlinks, or under symlink parents,
so the aggregate control-chain report can be uploaded without relying on
stdout scraping or unsafe report redirection.
Completion-audit validators also write `--out` validation sidecars for smoke
sidecars, readiness, run-plan, launch-pack, setup-state, setup-handle,
setup-gap, setup-attestation, dispatch, and recovery boundaries, so operators
can inspect each machine-checked step without scraping CI stdout.
Those validator-sidecar writes go through the shared
`safe_report_output.safe_write_report_text` helper, which rejects directory,
direct-symlink, and parent-symlink report targets before creating parent
directories or writing UTF-8 text.
Completion-audit artifact CLIs (`generate_*`, `run_*`, `report_*`, `apply_*`,
`probe_*`, and `promote_*`) use the same helper for `--out` and `--patch-out`
artifact writes after their domain-specific output-path validation, so the
audit chain has one shared write-time guard rather than per-script raw
`Path.write_text(...)` calls.
The self-harness workflow uploads the launch-pack JSON and Markdown beside the
non-LMS readiness, run-plan, setup-state, setup-attestation-template,
setup-attestation-smoke, dispatch-gate, dispatch-run, dispatch-diagnostics,
structural handoff, recovery plan, recovery queue, recovery work-order/status,
recovery queue progress, recovery dispatch authorization/run, and recovery
control-chain/checkpoint artifacts plus their validation sidecars, so operators
get the same validated execution handoff and resume boundary on every harness
run.
The non-LMS report does not change the release gate, and full completion audit
readiness still requires every registered artifact.
The final validation uses `--require-self-validation`, so the uploaded report
bundle cannot pass if `self-harness-report-bundle-validation.json` is missing.
That self-validation payload must describe the pre-self canonical bundle:
`report_count=4`, `fingerprinted_report_count=4`, and
`self_validation_report_present=false`, with `rows` matching the four canonical
report names in canonical order plus their statuses, schema versions, SHA-256
digests, and normalized error lists/codes. Top-level pass/fail/unexpected and
error-code-count fields must also match those canonical rows. Row entries may
contain only those canonical fields, and the top-level payload must match the
self-validation report schema exactly, so the self-validation report cannot
hide raw payloads in extra properties. This keeps the recursive report boundary
explicit.
The report-bundle CLI rejects `--out` locations inside the bundle root,
including resolved symlink targets, and rejects direct/parent symlink or
directory paths as report outputs, so validation cannot create an unexpected
report file in the directory it is checking or crash on a non-file output target.
`validate_self_harness_report_bundle.py` validates that downloaded report
artifact directory, including required files, report schemas, fingerprints,
per-report SHA-256 digests, a bundle SHA-256 fingerprint, error-code lists,
typed `error_code_counts` on every child JSON report, Markdown coverage
markers, child JSON report success (`ok: true` with empty `error_codes` and
empty `error_code_counts`), empty child-report internal error lists such as
`errors`, `validation_errors`, `coverage_errors`, `validation_error_codes`, and
`coverage_error_codes`, absence of unexpected files or directories, and the
optional self-validation report without adding that self-report to the canonical
bundle fingerprint. The bundle shape is intentionally flat: only the five
report files named by the contract may appear in the uploaded directory.
Unexpected entries are scanned before the optional self-validation report is
validated, so a stale self-validation JSON cannot keep passing after a file or
directory is added to the bundle.
The self-harness validation report must match the current repository
`wiii_self_harness_scenarios.json` manifest fingerprint, and the registry
validation report must match the current `runtime_evidence_registry.json`
fingerprint. This prevents a green bundle generated from an older control-plane
contract or older runtime-evidence registry from being accepted by the current
checkout.
The coverage JSON must also match the registry-validation JSON in the same
bundle for `registry_name`, `registry_path`, `registry_fingerprint_sha256`,
`registry_version`, and `requirement_count`, so CI cannot upload a coverage
report generated from a different registry contract or carrying stale
operator-facing registry identity/path metadata.
The report-bundle validator also compares each coverage row back to the
current `runtime_evidence_registry.json` for registry-derived fields including
title, layer, artifact, schema, workflow, probe, artifact upload tokens,
diagnostic upload count/artifacts/paths, payload-check count, freshness hours,
raw-content absence counts, identifier-strategy counts/lists, external evidence
mode, synthetic/credentialed external flags, forbidden token/regex counts, live
guards, and dispatch/schedule gates. A row that is valid JSON and matches the
Markdown table still fails with `report_registry_coverage_row_mismatch` if it
drifts from the current registry contract.
The coverage Markdown must also match the coverage JSON for operator-facing
summary values, including registry identity, status, error-code counts,
external-evidence counts, table row count, and each per-requirement coverage
table row, so humans do not review a stale Markdown artifact while automation
validates a different JSON payload.
The three child JSON reports use closed top-level schemas in the bundle
validator; unsupported fields fail validation instead of being archived as
unchecked metadata. Known top-level values are also type/range validated, so
allowed fields such as counts, labels, paths, layers, warnings, and error lists
cannot carry raw objects, boolean-as-integer counts, or negative summary values.
The runtime evidence coverage report also uses an exact row schema and the
row count must match `requirement_count`; row values must also keep expected
string, string-list, boolean, and non-negative integer shapes, so nested
coverage rows cannot carry unchecked payloads, invalid counts, or silently drop
a registered evidence requirement. For rows with a numeric freshness target,
`coverage_target_met` must equal `payload_checks >= freshness_hours`, so a
hand-edited coverage JSON cannot claim a target status that contradicts the
registered proof density. The top-level `layers` summary must also
match the distinct layer values present in the coverage rows, so operator
handoff cannot advertise a stale or invented product layer. Coverage rows also expose
`external_evidence_mode`, `synthetic_gap_flags`, and
`credentialed_external_flags`, so operator handoff can distinguish
credentialed external evidence, including the LMS test-course external write
contract, from any future synthetic external gaps without scraping prose notes.
The coverage report also
exposes top-level `synthetic_external_gap_count`, `credentialed_external_count`,
and `local_or_backend_count`, and bundle validation requires those counts to
match the coverage rows.
The optional `--require-no-synthetic-gaps` coverage gate turns the same row
classification into a failing completion criterion with stable error code
`coverage_synthetic_external_gap_present`.
The downloaded report-bundle validator exposes the same
`--require-no-synthetic-gaps` gate and reports
`report_coverage_synthetic_external_gap_present`, so release handoff can reject
a stale or incomplete bundle even after the coverage JSON has been uploaded.
It can also enforce `--require-credentialed-external-contracts`, returning
`report_coverage_credentialed_external_contract_incomplete` when a bundled
credentialed external coverage row lacks its guard, gate, privacy, or
identifier proof. The report-bundle generator accepts both strict flags; when
strict pre-validation fails, it stops before writing the self-validation report
so the generated output does not archive a stale successful self-validation.
For every child JSON report, `error_code_counts` keys must match
`error_codes`, `error_codes` must not contain duplicates, and listed error-code
counts must be positive, so handoff automation cannot receive contradictory
failure summaries.
The report-bundle validator exposes `fingerprinted_report_count` and
`self_validation_report_present` so automation can distinguish the canonical
fingerprint scope from the optional self-validation file, and emits
bundle-level `error_code_counts` for quick CI triage without scraping prose.

## Non-Goals

Wiii Self-Harness does not:

- execute LMS mutations
- replace upload DOCX/PDF preview/apply E2E
- inspect production environments
- replace CodeRabbit, branch protection, or human review
- guarantee every possible architectural debt is gone

It is a deterministic guardrail for active product-path contracts. Runtime
behavior still needs the focused verification commands listed by each scenario
and the normal issue, branch, PR, risk, rollback, and review process.

Use `WIII_SYSTEM_CONTROL_PLANE.md` before adding new scenarios. If the issue is
not mapped to a Wiii layer, active runtime flow, and observable signal, it is
not ready to become a durable Self-Harness scenario.
