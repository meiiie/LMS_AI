import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Bot,
  BriefcaseBusiness,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Cloud,
  Folder,
  FolderOpen,
  LoaderCircle,
  Plus,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { TitleBar } from "@/components/layout/TitleBar";
import { WiiiMark } from "@/components/common/WiiiMark";
import { getNekoControlClient } from "@/neko/control-client";
import NekoChillApp from "@/neko-chill/NekoChillApp";
import type { NekoTaskLaunchRequest } from "@/neko-chill/components/NewSessionView";
import { useNekoSessionStore } from "@/neko-chill/stores/neko-session-store";
import { chooseWorkspaceFolder, workspaceFromPath, type WorkspaceRef } from "@/neko-chill/workspace";
import type { AdeRun, AdeRunState, AdeTask } from "./domain";
import {
  deriveAdeOutcomeFromNativeRecord,
  deriveAdeOutcomeFromSessionEvents,
  nativeOutcomeTransitionPath,
  type AdeNativeOutcome,
} from "./native-lifecycle";
import { useAdeWorkStore } from "./store";
import "@/neko-chill/theme.css";

const RUN_LABELS: Record<AdeRunState, string> = {
  queued: "Đang xếp hàng",
  starting: "Đang chuẩn bị thực thi",
  running: "Đang thực hiện",
  waiting: "Đang chờ bạn",
  verifying: "Đang kiểm chứng",
  review: "Sẵn sàng duyệt",
  completed: "Đã hoàn thành",
  failed: "Thực thi thất bại",
  cancelled: "Đã hủy",
  unknown_outcome: "Chưa rõ kết quả",
};

function statusTone(state: AdeRunState): string {
  if (["running", "starting", "verifying"].includes(state)) return "text-[var(--nk-accent)]";
  if (state === "completed") return "text-[var(--nk-success)]";
  if (["failed", "unknown_outcome"].includes(state)) return "text-[var(--nk-danger)]";
  if (state === "review" || state === "waiting") return "text-[var(--nk-warning)]";
  return "text-[var(--nk-text-3)]";
}

function shortId(value: string): string {
  return value.length > 10 ? value.slice(0, 8) : value;
}

function latestRun(task: AdeTask, runs: AdeRun[]): AdeRun | null {
  return [...runs].reverse().find((run) => run.taskId === task.id) ?? null;
}

function WorkRecovery({ error, retry }: { error: string | null; retry: () => void }) {
  return (
    <main className="grid min-h-0 flex-1 place-items-center px-6">
      {error ? (
        <section className="w-full max-w-md rounded-2xl border border-[var(--nk-border-strong)] bg-[var(--nk-raised)] p-6" role="alert">
          <span className="grid h-9 w-9 place-items-center rounded-full bg-[var(--nk-danger-soft)] text-[var(--nk-danger)]">
            <AlertTriangle aria-hidden="true" className="h-4 w-4" />
          </span>
          <h1 className="mt-4 text-[15px] font-semibold">Chưa thể mở dữ liệu công việc</h1>
          <p className="mt-2 text-[12.5px] leading-5 text-[var(--nk-text-3)]">
            Wiii đã khóa việc ghi mới để không biến lỗi đọc thành một workspace trống.
          </p>
          <p className="mt-3 break-words rounded-lg bg-[var(--nk-inset)] px-3 py-2 text-[11px] text-[var(--nk-text-3)]">{error}</p>
          <button type="button" className="mt-4 inline-flex h-8 items-center gap-2 rounded-lg bg-[var(--nk-inverse)] px-3 text-[12px] font-medium text-[var(--nk-on-inverse)]" onClick={retry}>
            <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" /> Thử tải lại
          </button>
        </section>
      ) : (
        <div className="flex items-center gap-3 text-[13px] text-[var(--nk-text-3)]" role="status">
          <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" />
          Wiii đang khôi phục công việc…
        </div>
      )}
    </main>
  );
}

function NewTaskForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: (launch: NekoTaskLaunchRequest) => void;
}) {
  const createTaskRun = useAdeWorkStore((state) => state.createTaskRun);
  const [workspace, setWorkspace] = useState<WorkspaceRef | null>(null);
  const [title, setTitle] = useState("");
  const [criteria, setCriteria] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chooseWorkspace = async () => {
    setError(null);
    try {
      const selected = await chooseWorkspaceFolder();
      if (selected) setWorkspace(selected);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const submit = async () => {
    if (!workspace || !title.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createTaskRun({
        workspace,
        title,
        acceptanceCriteria: criteria.split("\n").map((item) => item.trim()).filter(Boolean),
      });
      onCreated({
        execution: created.execution,
        workspace,
        title: title.trim(),
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="min-w-0 flex-1 overflow-y-auto" data-testid="new-task-view">
      <div className="mx-auto w-full max-w-[780px] px-8 pb-14 pt-[7vh]">
        <button type="button" className="mb-7 inline-flex items-center gap-1.5 text-[11.5px] text-[var(--nk-text-3)] hover:text-[var(--nk-text)]" onClick={onCancel}>
          <ArrowLeft aria-hidden="true" className="h-3.5 w-3.5" /> Công việc
        </button>
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--nk-accent)]">Công việc mới</p>
        <h1 className="text-[29px] font-normal tracking-[-0.03em]" style={{ fontFamily: "var(--font-serif)" }}>
          Bạn muốn hoàn thành việc gì?
        </h1>
        <p className="mt-2 max-w-[620px] text-[13px] leading-5 text-[var(--nk-text-2)]">
          Wiii giữ mục tiêu và tiêu chí. Neko Chill sẽ điều hành agent trong môi trường bạn chọn.
        </p>

        <div className="mt-8 space-y-6">
          <section>
            <label className="mb-2 block text-[11.5px] font-semibold uppercase tracking-wide text-[var(--nk-text-3)]">Project</label>
            <button
              type="button"
              data-testid="choose-task-workspace"
              className="flex min-h-[62px] w-full items-center gap-3 rounded-xl border border-[var(--nk-border-strong)] bg-[var(--nk-composer)] px-4 text-left hover:bg-[var(--nk-raised)]"
              onClick={() => void chooseWorkspace()}
            >
              <span className="grid h-9 w-9 place-items-center rounded-lg bg-[var(--nk-inset)] text-[var(--nk-text-2)]"><FolderOpen aria-hidden="true" className="h-4 w-4" /></span>
              <span className="min-w-0 flex-1">
                <strong className="block truncate text-[13.5px] font-medium">{workspace?.name ?? "Mở một thư mục dự án"}</strong>
                <small className="block truncate text-[11.5px] text-[var(--nk-text-3)]">{workspace?.path ?? "Mã nguồn vẫn ở trên máy này"}</small>
              </span>
              <span className="text-[11px] text-[var(--nk-text-3)]">{workspace ? "Đổi" : "Chọn"}</span>
            </button>
          </section>

          <section>
            <label htmlFor="wiii-task-title" className="mb-2 block text-[11.5px] font-semibold uppercase tracking-wide text-[var(--nk-text-3)]">Mục tiêu</label>
            <textarea
              id="wiii-task-title"
              data-testid="task-title"
              rows={3}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Ví dụ: Refactor luồng đăng nhập và giữ nguyên toàn bộ hành vi hiện có"
              className="w-full resize-none rounded-xl border border-[var(--nk-border-strong)] bg-[var(--nk-composer)] px-4 py-3 text-[14px] leading-6 outline-none placeholder:text-[var(--nk-ghost)] focus:ring-2 focus:ring-[var(--nk-focus-soft)]"
            />
          </section>

          <section>
            <label htmlFor="wiii-task-criteria" className="mb-2 block text-[11.5px] font-semibold uppercase tracking-wide text-[var(--nk-text-3)]">Tiêu chí chấp nhận <span className="font-normal normal-case text-[var(--nk-ghost)]">· tùy chọn, mỗi dòng một tiêu chí</span></label>
            <textarea
              id="wiii-task-criteria"
              rows={3}
              value={criteria}
              onChange={(event) => setCriteria(event.target.value)}
              placeholder={"Đăng nhập hiện tại không regression\nTypeScript và test đều pass"}
              className="w-full resize-none rounded-xl border border-[var(--nk-border)] bg-[var(--nk-composer)] px-4 py-3 text-[13px] leading-5 outline-none placeholder:text-[var(--nk-ghost)] focus:ring-2 focus:ring-[var(--nk-focus-soft)]"
            />
          </section>
        </div>

        {error ? <p className="mt-4 text-[12px] text-[var(--nk-danger)]">{error}</p> : null}
        <div className="mt-7 flex items-center justify-between gap-4 border-t border-[var(--nk-border)] pt-5">
          <p className="flex items-center gap-2 text-[10.5px] text-[var(--nk-ghost)]"><ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" />Task và Run được lưu trước khi agent khởi động.</p>
          <button
            type="button"
            data-testid="continue-task"
            disabled={!workspace || !title.trim() || submitting}
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-[var(--nk-inverse)] px-4 text-[12.5px] font-medium text-[var(--nk-on-inverse)] disabled:cursor-not-allowed disabled:opacity-30"
            onClick={() => void submit()}
          >
            {submitting ? <LoaderCircle aria-hidden="true" className="h-3.5 w-3.5 animate-spin" /> : null}
            Chọn agent <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </main>
  );
}

export default function WiiiAdeApp({ onOpenManaged = () => {} }: { onOpenManaged?: () => void }) {
  const hydrate = useAdeWorkStore((state) => state.hydrate);
  const hydrated = useAdeWorkStore((state) => state.hydrated);
  const error = useAdeWorkStore((state) => state.error);
  const graph = useAdeWorkStore((state) => state.graph);
  const [surface, setSurface] = useState<"work" | "neko">("work");
  const [newTask, setNewTask] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [pendingLaunch, setPendingLaunch] = useState<NekoTaskLaunchRequest | null>(null);
  const lifecycleSyncs = useRef(new Set<string>());
  const sessions = useNekoSessionStore((state) => state.sessions);
  const desktopChrome = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

  useEffect(() => {
    void hydrate().catch(() => {});
    void useNekoSessionStore.getState().hydrate().catch(() => {});
  }, [hydrate]);

  useEffect(() => {
    if (!hydrated) return;
    const terminalStates: AdeRunState[] = [
      "completed",
      "failed",
      "cancelled",
      "unknown_outcome",
    ];

    const projectOutcome = async (runId: string, outcome: AdeNativeOutcome) => {
      const key = `${runId}:${outcome}`;
      if (lifecycleSyncs.current.has(key)) return;
      lifecycleSyncs.current.add(key);
      try {
        let current = useAdeWorkStore.getState().graph.runs.find((run) => run.id === runId)?.state;
        if (!current || terminalStates.includes(current)) return;
        for (const nextState of nativeOutcomeTransitionPath(current, outcome)) {
          await useAdeWorkStore.getState().transitionRun(runId, nextState);
          current = nextState;
        }
      } finally {
        lifecycleSyncs.current.delete(key);
      }
    };

    for (const session of Object.values(sessions)) {
      const execution = session.execution;
      if (!execution) continue;
      const run = graph.runs.find((candidate) => candidate.id === execution.runId);
      if (!run || terminalStates.includes(run.state)) continue;

      const durableOutcome = deriveAdeOutcomeFromSessionEvents(session.events, execution.runId);
      if (durableOutcome) {
        void projectOutcome(execution.runId, durableOutcome).catch(() => {});
        continue;
      }

      // A renderer exit is only a notification. Re-read the Rust projection,
      // whose exit event is emitted only after terminal state was persisted.
      if (session.status === "exited") {
        const key = `${execution.runId}:native-read`;
        if (lifecycleSyncs.current.has(key)) continue;
        lifecycleSyncs.current.add(key);
        void getNekoControlClient().listSessions(execution.runId).then((records) => {
          const bound = graph.agentSessions.find((item) => item.runId === execution.runId);
          const record = records.find((item) => item.agentSessionId === bound?.id)
            ?? records[records.length - 1];
          const outcome = record ? deriveAdeOutcomeFromNativeRecord(record) : null;
          if (outcome) return projectOutcome(execution.runId, outcome);
          return undefined;
        }).catch(() => {}).finally(() => {
          lifecycleSyncs.current.delete(key);
        });
      }
    }
  }, [graph.agentSessions, graph.runs, hydrated, sessions]);

  const visibleTasks = useMemo(() => graph.tasks.filter((task) =>
    !selectedProjectId || task.projectId === selectedProjectId), [graph.tasks, selectedProjectId]);
  const selectedTask = graph.tasks.find((task) => task.id === selectedTaskId) ?? null;
  const selectedRun = selectedTask ? latestRun(selectedTask, graph.runs) : null;
  const selectedSpec = selectedTask
    ? [...graph.specs].reverse().find((spec) => spec.taskId === selectedTask.id) ?? null
    : null;
  const selectedProject = selectedTask
    ? graph.projects.find((project) => project.id === selectedTask.projectId) ?? null
    : null;
  const selectedSession = selectedRun
    ? Object.values(sessions).find((session) => session.execution?.runId === selectedRun.id) ?? null
    : null;
  const selectedEnvironment = selectedRun
    ? graph.environments.find((environment) => environment.id === selectedRun.environmentId) ?? null
    : null;
  const selectedWorkspace = selectedEnvironment?.workspaceId
    ? graph.workspaces.find((workspace) => workspace.id === selectedEnvironment.workspaceId) ?? null
    : null;

  const openNeko = (sessionId?: string) => {
    if (sessionId) useNekoSessionStore.getState().setActiveSession(sessionId);
    setSurface("neko");
  };

  const beginTaskExecution = (launch: NekoTaskLaunchRequest) => {
    setSelectedTaskId(launch.execution.taskId);
    const onSessionCreated = async (sessionId: string) => {
      try {
        const session = useNekoSessionStore.getState().sessions[sessionId];
        const runtimeId = session?.runtime?.providerExtensions?.nativeAgentSessionId;
        if (session?.runtime && session.status !== "error") {
          await useAdeWorkStore.getState().attachAgentSession({
            id: typeof runtimeId === "string" ? runtimeId : sessionId,
            runId: launch.execution.runId,
            providerId: session.agentId,
            providerSessionId: session.backendSessionId,
          });
        } else {
          const uncertain = session?.statusDetail?.includes("unknown_outcome") ?? false;
          await useAdeWorkStore.getState().transitionRun(
            launch.execution.runId,
            uncertain ? "unknown_outcome" : "failed",
          );
        }
      } catch (cause) {
        // The provider already exists. Losing its Wiii binding is uncertain and
        // must never leave the launcher armed for a duplicate start.
        try {
          await useAdeWorkStore.getState().transitionRun(
            launch.execution.runId,
            "unknown_outcome",
          );
        } catch {
          // Preserve the original durability error; recovery can use the Neko
          // session's execution binding after storage becomes available again.
        }
        throw cause;
      } finally {
        setPendingLaunch(null);
        setSelectedTaskId(launch.execution.taskId);
      }
    };
    const onLaunchError = async (cause: unknown) => {
      const uncertain = (cause instanceof Error ? cause.message : String(cause)).includes("unknown_outcome");
      await useAdeWorkStore.getState().transitionRun(
        launch.execution.runId,
        uncertain ? "unknown_outcome" : "failed",
      );
      setPendingLaunch(null);
      setSelectedTaskId(launch.execution.taskId);
      setSurface("work");
    };
    setPendingLaunch({ ...launch, onSessionCreated, onLaunchError });
    useNekoSessionStore.getState().setActiveSession(null);
    setNewTask(false);
    setSurface("neko");
  };

  if (surface === "neko") {
    return (
      <NekoChillApp
        onOpenManaged={onOpenManaged}
        onOpenWork={() => {
          setPendingLaunch(null);
          setSurface("work");
        }}
        taskLaunch={pendingLaunch}
      />
    );
  }

  return (
    <div className="nk-root flex h-screen flex-col bg-[var(--nk-canvas)] text-[var(--nk-text)]" data-testid="wiii-ade-app">
      <TitleBar
        minimal
        leading={<span className="flex h-8 items-center gap-2 px-2.5 text-[13px] font-semibold"><WiiiMark size={17} /> Wiii</span>}
      />
      {!desktopChrome ? (
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-[var(--nk-border)] bg-[var(--nk-sidebar)] px-3">
          <WiiiMark size={17} /><span className="text-[13px] font-semibold">Wiii</span>
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[268px] shrink-0 flex-col border-r border-[var(--nk-border)] bg-[var(--nk-sidebar)]" aria-label="Điều hướng Wiii">
          <div className="px-2 pb-3 pt-3">
            <button type="button" data-testid="new-task" className="flex h-9 w-full items-center gap-2 rounded-lg bg-[var(--nk-inverse)] px-3 text-[12.5px] font-medium text-[var(--nk-on-inverse)]" onClick={() => { setNewTask(true); setSelectedTaskId(null); }}>
              <Plus aria-hidden="true" className="h-3.5 w-3.5" /> Công việc mới
            </button>
          </div>
          <nav className="px-2" aria-label="Công việc">
            <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.09em] text-[var(--nk-ghost)]">Công việc</p>
            <button type="button" className={`flex h-8 w-full items-center gap-2 rounded-lg px-2.5 text-[12.5px] font-medium ${selectedProjectId === null ? "bg-[var(--nk-item-active)]" : "hover:bg-[var(--nk-overlay)]"}`} onClick={() => { setSelectedProjectId(null); setSelectedTaskId(null); setNewTask(false); }}><BriefcaseBusiness aria-hidden="true" className="h-3.5 w-3.5" />Tất cả<span className="ml-auto text-[10px] tabular-nums text-[var(--nk-ghost)]">{graph.tasks.length}</span></button>
            <div className="mt-1 grid grid-cols-3 gap-1 px-1 text-center text-[9.5px] text-[var(--nk-ghost)]">
              <span>{graph.tasks.filter((task) => task.state === "blocked").length} cần bạn</span>
              <span>{graph.tasks.filter((task) => task.state === "running").length} đang chạy</span>
              <span>{graph.tasks.filter((task) => task.state === "review").length} cần duyệt</span>
            </div>
          </nav>
          <div className="mt-5 min-h-0 flex-1 overflow-y-auto px-2">
            <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.09em] text-[var(--nk-ghost)]">Projects</p>
            {graph.projects.length ? graph.projects.map((project) => (
              <button key={project.id} type="button" className={`flex h-8 w-full items-center gap-2 rounded-lg px-2.5 text-left text-[12.5px] ${selectedProjectId === project.id ? "bg-[var(--nk-item-active)]" : "hover:bg-[var(--nk-overlay)]"}`} onClick={() => { setSelectedProjectId(project.id); setSelectedTaskId(null); setNewTask(false); }}>
                <Folder aria-hidden="true" className="h-3.5 w-3.5 text-[var(--nk-text-3)]" /><span className="min-w-0 flex-1 truncate">{project.name}</span><ChevronRight aria-hidden="true" className="h-3 w-3 text-[var(--nk-ghost)]" />
              </button>
            )) : <p className="px-2 py-2 text-[11.5px] leading-5 text-[var(--nk-ghost)]">Project xuất hiện khi bạn tạo công việc đầu tiên.</p>}
          </div>
          <div className="border-t border-[var(--nk-border)] p-2">
            <button type="button" data-testid="open-neko" className="flex min-h-10 w-full items-center gap-2 rounded-lg px-2.5 text-left hover:bg-[var(--nk-overlay)]" onClick={() => openNeko()}><Bot aria-hidden="true" className="h-3.5 w-3.5 text-[var(--nk-text-3)]" /><span><strong className="block text-[12.5px] font-medium">Neko Chill</strong><small className="block text-[10px] text-[var(--nk-ghost)]">Agent Fabric · phiên thủ công</small></span></button>
            <button type="button" className="mt-1 flex min-h-10 w-full items-center gap-2 rounded-lg px-2.5 text-left hover:bg-[var(--nk-overlay)]" onClick={onOpenManaged}><Cloud aria-hidden="true" className="h-3.5 w-3.5 text-[var(--nk-text-3)]" /><span><strong className="block text-[12.5px] font-medium">Wiii Service</strong><small className="block text-[10px] text-[var(--nk-ghost)]">Kết nối tùy chọn</small></span></button>
          </div>
        </aside>

        {!hydrated ? (
          <WorkRecovery error={error} retry={() => void hydrate().catch(() => {})} />
        ) : newTask ? (
          <NewTaskForm onCancel={() => setNewTask(false)} onCreated={beginTaskExecution} />
        ) : selectedTask && selectedRun ? (
          <main className="min-w-0 flex-1 overflow-y-auto px-8 py-10" data-testid="task-detail">
            <div className="mx-auto max-w-[920px]">
              <button type="button" className="mb-6 inline-flex items-center gap-1.5 text-[11.5px] text-[var(--nk-text-3)] hover:text-[var(--nk-text)]" onClick={() => setSelectedTaskId(null)}><ArrowLeft aria-hidden="true" className="h-3.5 w-3.5" />Công việc</button>
              <p className="text-[11px] uppercase tracking-[0.1em] text-[var(--nk-ghost)]">{selectedProject?.name ?? "Project"}</p>
              <h1 className="mt-2 text-[28px] font-normal tracking-[-0.025em]" style={{ fontFamily: "var(--font-serif)" }}>{selectedTask.title}</h1>
              <div className={`mt-3 inline-flex items-center gap-2 text-[12px] font-medium ${statusTone(selectedRun.state)}`}><CircleDot aria-hidden="true" className="h-3.5 w-3.5" />{RUN_LABELS[selectedRun.state]} · Run {shortId(selectedRun.id)}</div>
              <div className="mt-8 grid gap-4 lg:grid-cols-[1fr_300px]">
                <section className="rounded-2xl border border-[var(--nk-border)] bg-[var(--nk-composer)] p-5">
                  <h2 className="text-[12px] font-semibold uppercase tracking-wide text-[var(--nk-text-3)]">Tiêu chí chấp nhận</h2>
                  {selectedSpec?.acceptanceCriteria.length ? <ul className="mt-4 space-y-3">{selectedSpec.acceptanceCriteria.map((criterion) => <li key={criterion} className="flex gap-2 text-[13px] leading-5"><CheckCircle2 aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-[var(--nk-ghost)]" />{criterion}</li>)}</ul> : <p className="mt-3 text-[12.5px] text-[var(--nk-text-3)]">Chưa có tiêu chí riêng. Mục tiêu Task vẫn là yêu cầu gốc.</p>}
                </section>
                <aside className="rounded-2xl border border-[var(--nk-border)] bg-[var(--nk-raised)] p-5">
                  <h2 className="text-[12px] font-semibold uppercase tracking-wide text-[var(--nk-text-3)]">Execution</h2>
                  <dl className="mt-4 space-y-3 text-[11.5px]"><div><dt className="text-[var(--nk-ghost)]">Môi trường</dt><dd className="mt-0.5">Local workspace</dd></div><div><dt className="text-[var(--nk-ghost)]">Agent</dt><dd className="mt-0.5">{selectedSession?.agentName ?? "Chưa gắn"}</dd></div><div><dt className="text-[var(--nk-ghost)]">Phiên</dt><dd className="mt-0.5 font-mono text-[10.5px]">{selectedSession ? shortId(selectedSession.id) : "—"}</dd></div></dl>
                  {selectedSession ? <button type="button" className="mt-5 flex h-8 w-full items-center justify-center gap-2 rounded-lg bg-[var(--nk-inverse)] text-[11.5px] font-medium text-[var(--nk-on-inverse)]" onClick={() => openNeko(selectedSession.id)}>Mở phiên agent <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" /></button> : selectedRun.state === "starting" && selectedWorkspace?.roots[0] ? <button type="button" className="mt-5 flex h-8 w-full items-center justify-center gap-2 rounded-lg bg-[var(--nk-inverse)] text-[11.5px] font-medium text-[var(--nk-on-inverse)]" onClick={() => beginTaskExecution({ execution: { taskId: selectedTask.id, runId: selectedRun.id, environmentId: selectedRun.environmentId }, workspace: workspaceFromPath(selectedWorkspace.roots[0]), title: selectedTask.title })}>Chọn agent <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" /></button> : null}
                </aside>
              </div>
            </div>
          </main>
        ) : (
          <main className="min-w-0 flex-1 overflow-y-auto px-8 py-9" data-testid="work-home">
            <div className="mx-auto max-w-[980px]">
              <div className="flex items-end justify-between gap-6"><div><p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--nk-accent)]">Wiii ADE</p><h1 className="mt-2 text-[30px] font-normal tracking-[-0.03em]" style={{ fontFamily: "var(--font-serif)" }}>Công việc</h1><p className="mt-2 text-[13px] text-[var(--nk-text-2)]">Theo dõi điều cần hoàn thành; Neko lo phần thực thi.</p></div><button type="button" className="inline-flex h-9 items-center gap-2 rounded-lg bg-[var(--nk-inverse)] px-4 text-[12.5px] font-medium text-[var(--nk-on-inverse)]" onClick={() => setNewTask(true)}><Plus aria-hidden="true" className="h-3.5 w-3.5" />Công việc mới</button></div>
              {visibleTasks.length ? <div className="mt-8 space-y-2">{[...visibleTasks].reverse().map((task) => { const run = latestRun(task, graph.runs); const project = graph.projects.find((item) => item.id === task.projectId); return <button key={task.id} type="button" className="group flex w-full items-center gap-4 rounded-xl border border-[var(--nk-border)] bg-[var(--nk-composer)] px-4 py-3.5 text-left hover:border-[var(--nk-border-strong)] hover:bg-[var(--nk-raised)]" onClick={() => setSelectedTaskId(task.id)}><span className="grid h-9 w-9 place-items-center rounded-lg bg-[var(--nk-inset)]"><BriefcaseBusiness aria-hidden="true" className="h-4 w-4 text-[var(--nk-text-2)]" /></span><span className="min-w-0 flex-1"><strong className="block truncate text-[13.5px] font-medium">{task.title}</strong><small className="mt-0.5 block truncate text-[10.5px] text-[var(--nk-ghost)]">{project?.name ?? "Project"} · {run ? `Run ${shortId(run.id)}` : "Chưa có Run"}</small></span>{run ? <span className={`shrink-0 text-[11px] ${statusTone(run.state)}`}>{RUN_LABELS[run.state]}</span> : null}<ChevronRight aria-hidden="true" className="h-3.5 w-3.5 text-[var(--nk-ghost)] transition-transform group-hover:translate-x-0.5" /></button>; })}</div> : <section className="mt-8 rounded-2xl border border-dashed border-[var(--nk-border-strong)] bg-[var(--nk-composer)] px-8 py-14 text-center"><span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-[var(--nk-inset)]"><BriefcaseBusiness aria-hidden="true" className="h-5 w-5 text-[var(--nk-text-3)]" /></span><h2 className="mt-5 text-[16px] font-medium">Chưa có công việc nào</h2><p className="mx-auto mt-2 max-w-md text-[12.5px] leading-5 text-[var(--nk-text-3)]">Bắt đầu bằng mục tiêu cần hoàn thành. Wiii sẽ giữ Task; Neko Chill tạo Run và phiên agent bên dưới.</p><button type="button" className="mt-5 inline-flex h-9 items-center gap-2 rounded-lg bg-[var(--nk-inverse)] px-4 text-[12px] font-medium text-[var(--nk-on-inverse)]" onClick={() => setNewTask(true)}><Plus aria-hidden="true" className="h-3.5 w-3.5" />Tạo công việc đầu tiên</button></section>}
            </div>
          </main>
        )}
      </div>
    </div>
  );
}
