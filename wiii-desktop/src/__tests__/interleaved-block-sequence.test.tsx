import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ContentBlock } from "@/api/types";
import { InterleavedBlockSequence } from "@/components/chat/InterleavedBlockSequence";
import { useCodeStudioStore } from "@/stores/code-studio-store";

vi.mock("@/components/common/MarkdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}));

vi.mock("@/components/chat/ThinkingBlock", () => ({
  ThinkingBlock: ({ content }: { content: string }) => (
    <div data-testid="thinking-block">{content}</div>
  ),
}));

vi.mock("@/components/chat/ScreenshotBlock", () => ({
  ScreenshotBlock: () => <div data-testid="screenshot-block">screenshot</div>,
}));

vi.mock("@/components/chat/SubagentGroup", () => ({
  SubagentGroup: () => <div data-testid="subagent-group">group</div>,
}));

vi.mock("@/components/chat/PreviewGroup", () => ({
  PreviewGroup: () => <div data-testid="preview-group">preview</div>,
}));

vi.mock("@/components/chat/ArtifactCard", () => ({
  ArtifactCard: ({ artifact }: { artifact: { title: string } }) => (
    <div data-testid="artifact-card">{artifact.title}</div>
  ),
}));

vi.mock("@/components/chat/VisualBlock", () => ({
  VisualBlock: ({
    block,
    embedded,
    onSuggestedQuestion,
  }: {
    block: { visual: { title: string } };
    embedded?: boolean;
    onSuggestedQuestion?: (q: string) => void;
  }) => (
    <div data-testid="visual-block" data-embedded={embedded ? "yes" : "no"}>
      {block.visual.title}
      {onSuggestedQuestion ? (
        <button type="button" onClick={() => onSuggestedQuestion("open as artifact")}>
          artifact handoff
        </button>
      ) : null}
    </div>
  ),
}));

vi.mock("@/components/common/InlineHtmlWidget", () => ({
  default: ({ code }: { code: string }) => (
    <div data-testid="inline-html-widget">{code.slice(0, 48)}</div>
  ),
}));

vi.mock("@/components/chat/ToolExecutionStrip", () => ({
  ToolExecutionStrip: ({ block }: { block: { tool: { name: string } } }) => (
    <div data-testid="tool-strip">{block.tool.name}</div>
  ),
  summarizeToolExecutionBlock: (block: { tool: { name: string; result?: string }; status: string }) => ({
    label: block.tool.name,
    argsLine: "",
    resultLine: block.tool.result || "",
    technicalDetail: undefined,
    detailLabel: "Chi tiet cong cu",
    isPending: block.status === "pending",
    Icon: () => <span data-testid="tool-strip-icon" />,
  }),
}));

function createThinking(
  content: string,
  overrides: Partial<Extract<ContentBlock, { type: "thinking" }>> = {},
): Extract<ContentBlock, { type: "thinking" }> {
  return {
    type: "thinking",
    id: "thinking-1",
    content,
    toolCalls: [],
    ...overrides,
  };
}

function createAction(
  content: string,
  overrides: Partial<Extract<ContentBlock, { type: "action_text" }>> = {},
): Extract<ContentBlock, { type: "action_text" }> {
  return {
    type: "action_text",
    id: "action-1",
    content,
    ...overrides,
  };
}

function createTool(
  name: string,
  status: "pending" | "completed" = "completed",
  overrides: Partial<Extract<ContentBlock, { type: "tool_execution" }>> = {},
): Extract<ContentBlock, { type: "tool_execution" }> {
  return {
    type: "tool_execution",
    id: `${name}-1`,
    tool: { id: `${name}-1`, name },
    status,
    ...overrides,
  };
}

function createAnswer(
  content: string,
  overrides: Partial<Extract<ContentBlock, { type: "answer" }>> = {},
): Extract<ContentBlock, { type: "answer" }> {
  return {
    type: "answer",
    id: "answer-1",
    content,
    ...overrides,
  };
}

function createVisual(
  overrides: Partial<Extract<ContentBlock, { type: "visual" }>> = {},
): Extract<ContentBlock, { type: "visual" }> {
  return {
    type: "visual",
    id: "visual-1",
    sessionId: "vs-1",
    visual: {
      id: "visual-1",
      visual_session_id: "vs-1",
      type: "comparison",
      renderer_kind: "template",
      shell_variant: "editorial",
      patch_strategy: "spec_merge",
      figure_group_id: "fg-1",
      figure_index: 1,
      figure_total: 1,
      pedagogical_role: "comparison",
      chrome_mode: "editorial",
      claim: "Dat hai goc nhin canh nhau de thay khac biet chinh.",
      narrative_anchor: "after-lead",
      runtime: "svg",
      title: "Softmax vs linear",
      summary: "Quick visual summary",
      spec: {},
      scene: { kind: "comparison", nodes: [], panels: [] },
      controls: [],
      annotations: [],
      interaction_mode: "static",
      ephemeral: true,
      lifecycle_event: "visual_open",
    },
    ...overrides,
  };
}

describe("InterleavedBlockSequence", () => {
  beforeEach(() => {
    useCodeStudioStore.setState({
      activeSessionId: null,
      sessions: {},
    });
  });

  it("dedupes action bridges that repeat adjacent thinking text", () => {
    const blocks: ContentBlock[] = [
      createThinking("Dang soi lai du lieu can bam.", {
        summary: "Dang soi lai du lieu can bam.",
      }),
      createAction("Dang soi lai du lieu can bam."),
      createAnswer("Du lieu da du de chot cau tra loi."),
    ];

    const { container } = render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
        thinkingLevel="detailed"
      />,
    );

    expect(screen.getAllByTestId("reasoning-interval")).toHaveLength(1);
    expect(container.querySelectorAll(".reasoning-op-row")).toHaveLength(0);
    expect(screen.getByTestId("answer-block").textContent || "").toContain("Du lieu da du de chot cau tra loi.");
  });

  it("renders answer before artifact even when artifact arrives earlier in block order", () => {
    const blocks: ContentBlock[] = [
      {
        type: "artifact",
        id: "art-1",
        artifact: {
          artifact_id: "art-1",
          artifact_type: "html",
          title: "Landing page",
          content: "<html />",
          metadata: {},
        },
      },
      createAnswer("Minh da tao landing page cho ban."),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
      />,
    );

    const answer = screen.getByTestId("answer-block");
    const artifact = screen.getByTestId("artifact-card");
    const bodyText = document.body.textContent || "";
    expect(bodyText.indexOf(answer.textContent || "")).toBeLessThan(bodyText.indexOf(artifact.textContent || ""));
  });

  it("renders tool execution directly inside the detailed reasoning rail", () => {
    const blocks: ContentBlock[] = [
      createThinking("Can goi cong cu de doi chieu."),
      createTool("tool_web_search"),
      createAnswer("Minh da doi chieu xong va day la ket qua."),
    ];

    const { container } = render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
        thinkingLevel="detailed"
      />,
    );

    expect(screen.getAllByTestId("reasoning-interval")).toHaveLength(1);
    expect(container.querySelectorAll(".reasoning-op-row").length).toBeGreaterThan(0);
    expect(screen.getByText("tool_web_search")).toBeTruthy();
    expect(screen.getByTestId("answer-block").textContent || "").toContain("Minh da doi chieu xong va day la ket qua.");
  });

  it("keeps reasoning and visual tool execution visible while a visual is still pending", () => {
    const blocks: ContentBlock[] = [
      createThinking("Dang sap xep lai y de chuyen sang visual."),
      createTool("tool_generate_visual", "pending", { stepId: "step-visual" }),
      createAnswer("Minh dang dung visual cho doan nay."),
    ];

    const { container } = render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
        thinkingLevel="balanced"
      />,
    );

    expect(screen.getAllByTestId("reasoning-interval")).toHaveLength(1);
    expect(container.querySelectorAll(".reasoning-op-row").length).toBeGreaterThan(0);
    expect(screen.getByText("tool_generate_visual")).toBeTruthy();
    expect(screen.getByTestId("answer-block").textContent || "").toContain("Minh dang dung visual cho doan nay.");
  });

  it("keeps reasoning visible when an inline visual arrives in balanced mode", () => {
    const blocks: ContentBlock[] = [
      createThinking("Dang canh chinh huong giai thich."),
      createAction("Dang chuyen sang visual."),
      createVisual(),
      createAnswer("Day la phan giai thich bang loi."),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
        thinkingLevel="balanced"
      />,
    );

    expect(screen.getAllByTestId("reasoning-interval")).toHaveLength(1);
    expect(screen.queryByTestId("thinking-block")).toBeNull();
    expect(screen.getByTestId("visual-block")).toBeTruthy();
    expect(screen.getByTestId("answer-block")).toBeTruthy();
  });

  it("keeps balanced mode free of the trace launcher while still surfacing tool execution", () => {
    const blocks: ContentBlock[] = [
      createThinking("Dang nghien cuu co che va chuan bi minh hoa.", {
        summary: "Dang nghien cuu co che",
      }),
      createTool("tool_web_search"),
      createAnswer("Minh da tong hop xong phan mo dau."),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
        thinkingLevel="balanced"
      />,
    );

    expect(screen.getAllByTestId("reasoning-interval")).toHaveLength(1);
    expect(screen.queryByTestId("reasoning-inspector-toggle")).toBeNull();
    expect(screen.getByText("tool_web_search")).toBeTruthy();
  });

  it("keeps inline visual visible while tool history also appears in the main flow", () => {
    const blocks: ContentBlock[] = [
      createTool("tool_generate_visual", "completed", { stepId: "step-visual" }),
      createVisual({ stepId: "step-visual" }),
      createAnswer("Day la phan giai thich bang loi."),
    ];

    const { container } = render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
        thinkingLevel="detailed"
      />,
    );

    expect(screen.queryByTestId("reasoning-interval")).toBeNull();
    expect(screen.getByTestId("tool-strip").textContent || "").toContain("tool_generate_visual");
    expect(screen.getByTestId("visual-block")).toBeTruthy();
  });

  it("keeps Code Studio-owned visual blocks as transcript anchors", () => {
    const store = useCodeStudioStore.getState();
    store.openSession("cs-code-visual", "Pendulum App", "html", 1, {
      studioLane: "app",
    });
    store.completeSession(
      "cs-code-visual",
      "<main>Pendulum</main>",
      "html",
      1,
      undefined,
      "vs-code-visual",
    );

    const baseVisual = createVisual().visual;
    const blocks: ContentBlock[] = [
      createAnswer("Minh da dung mot app nho de minh hoa chuyen dong."),
      createVisual({
        id: "visual-code",
        sessionId: "vs-code-visual",
        visual: {
          ...baseVisual,
          id: "visual-code",
          visual_session_id: "vs-code-visual",
          title: "Pendulum App",
          renderer_kind: "app",
          shell_variant: "immersive",
          patch_strategy: "app_state",
          chrome_mode: "app",
          runtime: "sandbox_html",
          fallback_html: "<main>Pendulum</main>",
        },
      }),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
        thinkingLevel="balanced"
      />,
    );

    expect(screen.getByTestId("visual-block")).toBeTruthy();
    expect(screen.getByText("Pendulum App")).toBeTruthy();
  });

  it("renders detailed trace in the main flow and still keeps the inspector available", () => {
    const blocks: ContentBlock[] = [
      createThinking("Can goi cong cu de doi chieu.", { summary: "Dang doi chieu" }),
      createTool("tool_web_search"),
      createAnswer("Minh da doi chieu xong va day la ket qua."),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
        thinkingLevel="detailed"
      />,
    );

    expect(screen.getAllByTestId("reasoning-interval")).toHaveLength(1);
    expect(screen.queryByTestId("thinking-block")).toBeNull();
    expect(screen.getByText("tool_web_search")).toBeTruthy();

    fireEvent.click(screen.getByTestId("reasoning-inspector-toggle"));

    expect(screen.getByTestId("reasoning-inspector-drawer")).toBeTruthy();
    expect(screen.getByTestId("thinking-block").textContent || "").toContain("Can goi cong cu de doi chieu.");
    expect(screen.getByTestId("tool-strip").textContent || "").toContain("tool_web_search");
  });

  it("pins visuals under the answer once prose arrives", () => {
    const blocks: ContentBlock[] = [
      createVisual(),
      createAnswer("Day la phan giai thich bang loi."),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
      />,
    );

    const visual = screen.getByTestId("visual-block");
    const answer = screen.getByTestId("answer-block");
    const bodyText = document.body.textContent || "";
    expect(bodyText.indexOf(answer.textContent || "")).toBeLessThan(bodyText.indexOf(visual.textContent || ""));
  });

  it("composes long-form prose and an inline visual into one editorial flow", () => {
    const blocks: ContentBlock[] = [
      createAnswer([
        "Kimi linear attention giai bai toan O(n^2) bang cach doi lai thu tu nhan ma tran.",
        "Trong softmax attention, ban phai vat chat hoa ma tran n x n, nen chi phi tang rat nhanh khi context dai.",
        "Neu doi sang running state co dinh, moi buoc chi cap nhat mot trang thai nho gon va truy van tren trang thai do.",
      ].join("\n\n"), { id: "ans-editorial" }),
      createVisual({
        id: "visual-editorial",
        sessionId: "vs-editorial",
        visual: {
          id: "visual-editorial",
          visual_session_id: "vs-editorial",
          type: "comparison",
          renderer_kind: "template",
          shell_variant: "editorial",
          patch_strategy: "spec_merge",
          figure_group_id: "fg-editorial",
          figure_index: 1,
          figure_total: 1,
          pedagogical_role: "comparison",
          chrome_mode: "editorial",
          claim: "Figure nay dat hai co che canh nhau de doc nhanh.",
          narrative_anchor: "after-lead",
          runtime: "svg",
          title: "Softmax vs linear attention",
          summary: "Quick visual summary",
          spec: {},
          scene: { kind: "comparison", nodes: [], panels: [] },
          controls: [],
          annotations: [],
          interaction_mode: "static",
          ephemeral: true,
          lifecycle_event: "visual_open",
        },
      }),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
      />,
    );

    const flow = screen.getByTestId("editorial-visual-flow");
    const answers = screen.getAllByTestId("answer-block");
    const visual = screen.getByTestId("visual-block");

    expect(flow).toBeTruthy();
    expect(answers).toHaveLength(2);
    expect(visual.getAttribute("data-embedded")).toBe("yes");
    expect(screen.getByText("Minh họa so sánh")).toBeTruthy();
    expect(answers[0]?.textContent).toContain("Kimi linear attention");
    expect(answers[1]?.textContent).toContain("running state");

    const bodyText = flow.textContent || "";
    expect(bodyText.indexOf(answers[0]?.textContent || "")).toBeLessThan(bodyText.indexOf(visual.textContent || ""));
    expect(bodyText.indexOf(visual.textContent || "")).toBeLessThan(bodyText.indexOf(answers[1]?.textContent || ""));
  });

  it("composes a pinned visual plus trailing prose into one editorial flow", () => {
    const blocks: ContentBlock[] = [
      createVisual({
        id: "visual-pinned",
        sessionId: "vs-pinned",
        visual: {
          id: "visual-pinned",
          visual_session_id: "vs-pinned",
          type: "process",
          renderer_kind: "template",
          shell_variant: "editorial",
          patch_strategy: "spec_merge",
          figure_group_id: "fg-pinned",
          figure_index: 1,
          figure_total: 1,
          pedagogical_role: "mechanism",
          chrome_mode: "editorial",
          claim: "Figure nay tach co che thanh tung buoc noi tiep.",
          narrative_anchor: "after-lead",
          runtime: "svg",
          title: "Quy trinh Linear Attention",
          summary: "Quick visual summary",
          spec: {},
          scene: { kind: "process", nodes: [], panels: [] },
          controls: [],
          annotations: [],
          interaction_mode: "static",
          ephemeral: true,
          lifecycle_event: "visual_open",
        },
      }),
      createAnswer([
        "Linear attention doi bai toan full matrix thanh mot running state nho gon.",
        "Ban van can theo doi noi xuat hien approximation error de hieu trade-off giua toc do va do chinh xac.",
        "Tu do, visual co the patch tiep thanh tung buoc ma khong can tao block moi.",
      ].join("\n\n"), { id: "ans-pinned" }),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
      />,
    );

    const flow = screen.getByTestId("editorial-visual-flow");
    const answers = screen.getAllByTestId("answer-block");
    const visual = screen.getByTestId("visual-block");

    expect(flow).toBeTruthy();
    expect(answers).toHaveLength(2);
    expect(visual.getAttribute("data-embedded")).toBe("yes");
    expect(screen.getByText("Minh họa theo bước")).toBeTruthy();
    expect(answers[0]?.textContent).toContain("running state");
    expect(answers[1]?.textContent).toContain("patch tiep");
  });

  it("composes multiple inline figures into a single article flow", () => {
    const blocks: ContentBlock[] = [
      createAnswer([
        "Kimi Linear giai bai toan chi phi bo nho bang cach tranh ma tran day du.",
        "Figure dau tien nen chot van de chi phi, con figure thu hai nen mo ta co che running state va gate.",
        "Sau do ket luan vi sao nhom figure nay hop thanh mot bai giai thich lien mach.",
      ].join("\n\n"), { id: "ans-multi" }),
      createVisual({
        id: "visual-problem",
        sessionId: "vs-problem",
        visual: {
          id: "visual-problem",
          visual_session_id: "vs-problem",
          type: "chart",
          renderer_kind: "template",
          shell_variant: "editorial",
          patch_strategy: "spec_merge",
          figure_group_id: "fg-kimi",
          figure_index: 1,
          figure_total: 2,
          pedagogical_role: "problem",
          chrome_mode: "editorial",
          claim: "Figure nay chung minh chi phi cua softmax tang rat nhanh theo context.",
          narrative_anchor: "after-lead",
          runtime: "svg",
          title: "Compute cost",
          summary: "Chi phi tang nhanh theo context",
          spec: {},
          scene: { kind: "chart", nodes: [], panels: [] },
          controls: [],
          annotations: [],
          interaction_mode: "static",
          ephemeral: true,
          lifecycle_event: "visual_open",
        },
      }),
      createVisual({
        id: "visual-mechanism",
        sessionId: "vs-mechanism",
        visual: {
          id: "visual-mechanism",
          visual_session_id: "vs-mechanism",
          type: "process",
          renderer_kind: "template",
          shell_variant: "editorial",
          patch_strategy: "spec_merge",
          figure_group_id: "fg-kimi",
          figure_index: 2,
          figure_total: 2,
          pedagogical_role: "mechanism",
          chrome_mode: "editorial",
          claim: "Figure nay mo ta running state va gate de giam chi phi.",
          narrative_anchor: "after-summary",
          runtime: "svg",
          title: "Running state",
          summary: "Co che cap nhat trang thai",
          spec: {},
          scene: { kind: "process", nodes: [], panels: [] },
          controls: [],
          annotations: [],
          interaction_mode: "static",
          ephemeral: true,
          lifecycle_event: "visual_open",
        },
      }),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
      />,
    );

    const flow = screen.getByTestId("editorial-visual-flow");
    const visuals = screen.getAllByTestId("visual-block");
    const answers = screen.getAllByTestId("answer-block");

    expect(flow.getAttribute("data-figure-count")).toBe("2");
    expect(visuals).toHaveLength(2);
    expect(answers.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Figure nay chung minh chi phi cua softmax tang rat nhanh theo context.")).toBeTruthy();
    expect(screen.getByText("Figure nay mo ta running state va gate de giam chi phi.")).toBeTruthy();
  });

  it("passes the suggested-question callback down to visual blocks", () => {
    const onSuggestedQuestion = vi.fn();
    const blocks: ContentBlock[] = [
      createVisual(),
      createAnswer("Day la phan giai thich bang loi."),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
        onSuggestedQuestion={onSuggestedQuestion}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "artifact handoff" }));
    expect(onSuggestedQuestion).toHaveBeenCalledWith("open as artifact");
  });

  it("strips visual placeholders and rendered-above markers from editorial prose", () => {
    const blocks: ContentBlock[] = [
      createAnswer([
        "1. Van de: Softmax ton bo nho rat nhanh.",
        "{visual_1}",
        "2. Co che: Kimi Linear doi sang running state gon hon.",
        "{visual_2}",
        "3. Ket qua: mo rong duoc context dai hon.",
        "",
        "(Cac bieu do duoi day se giup cu hinh dung ro hon ve su khac biet nay nhe.)",
        "[Visual: Linear Attention Process & Approximation Error]",
        "[Visuals rendered above]",
        "Takeaway: Linear attention giam ap luc bo nho nhung van giu y chinh.",
      ].join("\n\n"), { id: "ans-marker-flow" }),
      createVisual({
        id: "visual-marker-a",
        sessionId: "vs-marker-a",
        visual: {
          ...createVisual().visual,
          id: "visual-marker-a",
          visual_session_id: "vs-marker-a",
          figure_group_id: "fg-marker-flow",
          figure_index: 1,
          figure_total: 2,
          title: "Problem",
        },
      }),
      createVisual({
        id: "visual-marker-b",
        sessionId: "vs-marker-b",
        visual: {
          ...createVisual().visual,
          id: "visual-marker-b",
          visual_session_id: "vs-marker-b",
          type: "process",
          figure_group_id: "fg-marker-flow",
          figure_index: 2,
          figure_total: 2,
          title: "Mechanism",
        },
      }),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
        thinkingLevel="detailed"
      />,
    );

    const flow = screen.getByTestId("editorial-visual-flow");
    const bodyText = flow.textContent || "";

    expect(flow.getAttribute("data-figure-count")).toBe("2");
    expect(bodyText).toContain("1. Van de: Softmax ton bo nho rat nhanh.");
    expect(bodyText).toContain("2. Co che: Kimi Linear doi sang running state gon hon.");
    expect(bodyText).toContain("3. Ket qua: mo rong duoc context dai hon.");
    expect(bodyText).toContain("Takeaway: Linear attention giam ap luc bo nho nhung van giu y chinh.");
    expect(bodyText).not.toContain("{visual_1}");
    expect(bodyText).not.toContain("{visual_2}");
    expect(bodyText).not.toContain("[Visual: Linear Attention Process & Approximation Error]");
    expect(bodyText).not.toContain("[Visuals rendered above]");
  });

  it("keeps grouped visuals inside an editorial flow even when prose is missing", () => {
    const blocks: ContentBlock[] = [
      createVisual({
        id: "visual-problem-only",
        sessionId: "vs-problem-only",
        visual: {
          id: "visual-problem-only",
          visual_session_id: "vs-problem-only",
          type: "chart",
          renderer_kind: "template",
          shell_variant: "editorial",
          patch_strategy: "spec_merge",
          figure_group_id: "fg-no-answer",
          figure_index: 1,
          figure_total: 2,
          pedagogical_role: "problem",
          chrome_mode: "editorial",
          claim: "Figure dau tien dat van de chi phi quadratic.",
          narrative_anchor: "after-lead",
          runtime: "svg",
          title: "Compute cost",
          summary: "Chi phi cua softmax tang nhanh theo context.",
          spec: {},
          scene: { kind: "chart", nodes: [], panels: [] },
          controls: [],
          annotations: [],
          interaction_mode: "static",
          ephemeral: true,
          lifecycle_event: "visual_open",
        },
      }),
      createVisual({
        id: "visual-result-only",
        sessionId: "vs-result-only",
        visual: {
          id: "visual-result-only",
          visual_session_id: "vs-result-only",
          type: "infographic",
          renderer_kind: "template",
          shell_variant: "editorial",
          patch_strategy: "spec_merge",
          figure_group_id: "fg-no-answer",
          figure_index: 2,
          figure_total: 2,
          pedagogical_role: "conclusion",
          chrome_mode: "editorial",
          claim: "Figure thu hai chot lai diem loi cua co che moi.",
          narrative_anchor: "after-figure-1",
          runtime: "svg",
          title: "Takeaway",
          summary: "Linear attention giu chi phi gon hon va de patch tiep.",
          spec: {},
          scene: { kind: "infographic", nodes: [], panels: [] },
          controls: [],
          annotations: [],
          interaction_mode: "static",
          ephemeral: true,
          lifecycle_event: "visual_open",
        },
      }),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
      />,
    );

    const flow = screen.getByTestId("editorial-visual-flow");
    const answers = screen.getAllByTestId("answer-block");
    const visuals = screen.getAllByTestId("visual-block");

    expect(flow.getAttribute("data-figure-count")).toBe("2");
    expect(visuals).toHaveLength(2);
    expect(answers.length).toBeGreaterThanOrEqual(2);
    expect(flow.textContent || "").toContain("Minh se di qua 2 figure nho");
    expect(flow.textContent || "").toContain("diem chot la");
  });

  it("merges multiple answer blocks into the same article flow", () => {
    const blocks: ContentBlock[] = [
      createAnswer("Figure dau tien dat van de bo nho.", { id: "ans-a" }),
      createAnswer("Figure thu hai giai thich running state va gate.", { id: "ans-b" }),
      createVisual({
        id: "visual-a",
        sessionId: "vs-a",
        visual: {
          id: "visual-a",
          visual_session_id: "vs-a",
          type: "chart",
          renderer_kind: "template",
          shell_variant: "editorial",
          patch_strategy: "spec_merge",
          figure_group_id: "fg-answers",
          figure_index: 1,
          figure_total: 2,
          pedagogical_role: "problem",
          chrome_mode: "editorial",
          claim: "Figure nay chung minh chi phi tang nhanh theo context.",
          narrative_anchor: "after-lead",
          runtime: "svg",
          title: "Problem",
          summary: "Chi phi quadratic",
          spec: {},
          scene: { kind: "chart", nodes: [], panels: [] },
          controls: [],
          annotations: [],
          interaction_mode: "static",
          ephemeral: true,
          lifecycle_event: "visual_open",
        },
      }),
      createVisual({
        id: "visual-b",
        sessionId: "vs-b",
        visual: {
          id: "visual-b",
          visual_session_id: "vs-b",
          type: "process",
          renderer_kind: "template",
          shell_variant: "editorial",
          patch_strategy: "spec_merge",
          figure_group_id: "fg-answers",
          figure_index: 2,
          figure_total: 2,
          pedagogical_role: "mechanism",
          chrome_mode: "editorial",
          claim: "Figure nay mo ta running state va gate.",
          narrative_anchor: "after-figure-1",
          runtime: "svg",
          title: "Mechanism",
          summary: "Co che cap nhat trang thai",
          spec: {},
          scene: { kind: "process", nodes: [], panels: [] },
          controls: [],
          annotations: [],
          interaction_mode: "static",
          ephemeral: true,
          lifecycle_event: "visual_open",
        },
      }),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
      />,
    );

    const flow = screen.getByTestId("editorial-visual-flow");
    expect(flow.getAttribute("data-figure-count")).toBe("2");
    expect(flow.textContent || "").toContain("Figure dau tien dat van de bo nho.");
    expect(flow.textContent || "").toContain("Figure thu hai giai thich running state va gate.");
  });

  it("falls back to grouping contiguous editorial visuals when figure groups are missing", () => {
    const blocks: ContentBlock[] = [
      createAnswer("Minh se tach bai giai thich thanh nhieu figure nho.", { id: "ans-fallback-group" }),
      createVisual({
        id: "visual-fallback-a",
        sessionId: "vs-fallback-a",
        visual: {
          ...createVisual().visual,
          id: "visual-fallback-a",
          visual_session_id: "vs-fallback-a",
          figure_group_id: "fg-a",
          figure_index: 1,
          figure_total: 1,
          title: "Problem",
          claim: "Figure A chot bai toan chi phi.",
        },
      }),
      createVisual({
        id: "visual-fallback-b",
        sessionId: "vs-fallback-b",
        visual: {
          ...createVisual().visual,
          id: "visual-fallback-b",
          visual_session_id: "vs-fallback-b",
          figure_group_id: "fg-b",
          figure_index: 1,
          figure_total: 1,
          title: "Mechanism",
          claim: "Figure B mo ta running state.",
        },
      }),
      createVisual({
        id: "visual-fallback-c",
        sessionId: "vs-fallback-c",
        visual: {
          ...createVisual().visual,
          id: "visual-fallback-c",
          visual_session_id: "vs-fallback-c",
          figure_group_id: "fg-c",
          figure_index: 1,
          figure_total: 1,
          title: "Result",
          claim: "Figure C tong hop ket qua.",
        },
      }),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
      />,
    );

    const flow = screen.getByTestId("editorial-visual-flow");
    expect(flow.getAttribute("data-figure-count")).toBe("3");
    expect(screen.getAllByTestId("visual-block")).toHaveLength(3);
    expect(flow.textContent || "").toContain("Figure A chot bai toan chi phi.");
    expect(flow.textContent || "").toContain("Figure C tong hop ket qua.");
  });

  it("hides superseded visual sessions that were already disposed", () => {
    const blocks: ContentBlock[] = [
      createVisual({
        id: "visual-old",
        sessionId: "vs-old",
        status: "disposed",
        visual: {
          ...createVisual().visual,
          id: "visual-old",
          visual_session_id: "vs-old",
          title: "Old visual",
        },
      }),
      createVisual({
        id: "visual-current",
        sessionId: "vs-current",
        status: "committed",
        visual: {
          ...createVisual().visual,
          id: "visual-current",
          visual_session_id: "vs-current",
          title: "Current visual",
        },
      }),
    ];

    render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
        thinkingLevel="detailed"
      />,
    );

    expect(screen.getAllByTestId("visual-block")).toHaveLength(1);
    expect(screen.queryByText("Old visual")).toBeNull();
    expect(screen.getByText("Current visual")).toBeTruthy();
  });

  it("groups post-tool thinking with the same step into a single interval while keeping tool trace visible", () => {
    const blocks: ContentBlock[] = [
      createThinking("Can chuan bi du lieu.", {
        id: "t1",
        stepId: "step-1",
        label: "Chuan bi",
      }),
      createTool("tool_execute_python", "completed", {
        id: "tool-1",
        stepId: "step-1",
      }),
      createThinking("Minh vua nhin lai ket qua chay code.", {
        id: "t2",
        stepId: "step-1",
        label: "code_studio_agent",
      }),
    ];

    const { container } = render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
        thinkingLevel="detailed"
      />,
    );

    const intervals = screen.getAllByTestId("reasoning-interval");
    expect(intervals).toHaveLength(1);
    const interval = intervals[0];
    expect(interval.textContent || "").toContain("Can chuan bi du lieu.");
    expect(interval.textContent || "").toContain("Minh vua nhin lai ket qua chay code.");
    expect(interval.textContent || "").toContain("tool_execute_python");
    expect(container.querySelectorAll(".reasoning-op-row").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByTestId("reasoning-inspector-toggle"));
    expect(screen.getByTestId("tool-strip").textContent || "").toContain("tool_execute_python");
  });

  it("compacts balanced reasoning to the opening beat and the latest beat while keeping tool trace visible", () => {
    const blocks: ContentBlock[] = [
      createThinking("Can chuan bi du lieu dau vao.", {
        id: "t1",
        stepId: "step-2",
        summary: "Dang chuan bi du lieu",
      }),
      createThinking("Da tach nhom du lieu de so sanh tung lop.", {
        id: "t2",
        stepId: "step-2",
      }),
      createTool("tool_execute_python", "completed", {
        id: "tool-2",
        stepId: "step-2",
      }),
      createThinking("Minh vua doi chieu xong va chot duoc diem lech lon nhat.", {
        id: "t3",
        stepId: "step-2",
      }),
    ];

    const { container } = render(
      <InterleavedBlockSequence
        blocks={blocks}
        showThinking
        thinkingLevel="balanced"
      />,
    );

    const interval = screen.getAllByTestId("reasoning-interval")[0];
    expect(interval.textContent || "").toContain("Can chuan bi du lieu dau vao.");
    expect(interval.textContent || "").not.toContain("Da tach nhom du lieu de so sanh tung lop.");
    expect(interval.textContent || "").toContain("tool_execute_python");
    expect(container.querySelectorAll(".reasoning-op-row").length).toBeGreaterThan(0);
    fireEvent.click(interval.querySelector(".reasoning-interval__header-btn") as HTMLButtonElement);
    expect(interval.textContent || "").toContain("Minh vua doi chieu xong va chot duoc diem lech lon nhat.");
  });
});
