import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ToolExecutionStrip } from "@/components/chat/ToolExecutionStrip";
import type { ToolExecutionBlockData } from "@/api/types";
import { useCodeStudioStore } from "@/stores/code-studio-store";

describe("ToolExecutionStrip", () => {
  beforeEach(() => {
    useCodeStudioStore.setState({
      activeSessionId: null,
      sessions: {},
    });
  });

  it("renders CodeStudioCard when tool_create_visual_code returns a visual_session_id in result payload", () => {
    useCodeStudioStore.setState({
      activeSessionId: "vs_app_1",
      sessions: {
        vs_app_1: {
          sessionId: "vs_app_1",
          title: "Pendulum App",
          language: "html",
          status: "complete",
          code: "<div>app</div>",
          versions: [
            {
              version: 1,
              code: "<div>app</div>",
              title: "Pendulum App",
              timestamp: Date.now(),
            },
          ],
          activeVersion: 1,
          chunkCount: 1,
          totalBytes: 14,
          visualSessionId: "vs_app_1",
          createdAt: Date.now(),
          metadata: { studioLane: "app" },
        },
      },
    });

    const block: ToolExecutionBlockData = {
      type: "tool_execution",
      id: "tool-code-1",
      status: "completed",
      tool: {
        id: "tool-code-1",
        name: "tool_create_visual_code",
        args: {
          title: "Pendulum App",
        },
        result: JSON.stringify({
          visual_session_id: "vs_app_1",
        }),
      },
    };

    render(<ToolExecutionStrip block={block} />);

    expect(screen.getByText("Pendulum App")).toBeTruthy();
    expect(screen.getByText("Xem mã")).toBeTruthy();
    expect(screen.getByText("Xem trước")).toBeTruthy();
  });

  it("resolves CodeStudioCard through a mapped visual_session_id", () => {
    const store = useCodeStudioStore.getState();
    store.openSession("cs_mapped", "Mapped Pendulum App", "html", 1, {
      studioLane: "app",
    });
    store.completeSession(
      "cs_mapped",
      "<div>app</div>",
      "html",
      1,
      undefined,
      "vs_mapped",
    );

    const block: ToolExecutionBlockData = {
      type: "tool_execution",
      id: "tool-code-mapped",
      status: "completed",
      tool: {
        id: "tool-code-mapped",
        name: "tool_create_visual_code",
        args: {
          title: "Mapped Pendulum App",
        },
        result: JSON.stringify({
          visual_session_id: "vs_mapped",
        }),
      },
    };

    render(<ToolExecutionStrip block={block} />);

    expect(screen.getByText("Mapped Pendulum App")).toBeTruthy();
    expect(screen.getByText("Xem trước")).toBeTruthy();
  });

  it("renders CodeStudioCard via _code_studio_session_id injected by SSE handler", () => {
    useCodeStudioStore.setState({
      activeSessionId: "cs_abc",
      sessions: {
        cs_abc: {
          sessionId: "cs_abc",
          title: "Wave Simulation",
          language: "html",
          status: "streaming",
          code: [
            "<style></style><canvas></canvas><button>Run</button>",
            "<script>window.WiiiVisualBridge.reportResult()</script>",
          ].join(""),
          versions: [],
          activeVersion: 1,
          chunkCount: 3,
          totalBytes: 22,
          createdAt: Date.now(),
          metadata: {},
        },
      },
    });

    const block: ToolExecutionBlockData = {
      type: "tool_execution",
      id: "tool-code-2",
      status: "pending",
      tool: {
        id: "tool-code-2",
        name: "tool_create_visual_code",
        args: {
          title: "Wave Simulation",
          _code_studio_session_id: "cs_abc",
        },
      },
    };

    render(<ToolExecutionStrip block={block} />);

    expect(screen.getByText("Wave Simulation")).toBeTruthy();
    expect(screen.getByText(/Điều khiển/)).toBeTruthy();
    expect(screen.getByText(/Kết nối/)).toBeTruthy();
  });

  it("hides raw python code and filesystem paths by default", () => {
    const block: ToolExecutionBlockData = {
      type: "tool_execution",
      id: "tool-1",
      status: "completed",
      tool: {
        id: "tool-1",
        name: "tool_execute_python",
        args: {
          code: "import matplotlib.pyplot as plt\nplt.savefig('chart.png')",
        },
        result: [
          "Output: Bieu do da tao thanh cong!",
          "Artifacts:",
          "- chart.png (image/png) -> /home/appuser/.wiii/workspace/generated/chart_20260309.png",
        ].join("\n"),
      },
    };

    render(<ToolExecutionStrip block={block} />);

    expect(
      screen.getByText("Script Python để tạo biểu đồ chart.png"),
    ).toBeTruthy();
    expect(screen.queryByText("Đã tạo 1 tệp: chart.png")).toBeNull();
    expect(screen.queryByText(/import matplotlib/i)).toBeNull();
    expect(screen.queryByText(/\/home\/appuser/i)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Chạy mã Python/i }));
    expect(screen.getByText("Đã tạo 1 tệp: chart.png")).toBeTruthy();
  });

  it("reveals sanitized technical detail only when expanded", () => {
    const block: ToolExecutionBlockData = {
      type: "tool_execution",
      id: "tool-2",
      status: "completed",
      tool: {
        id: "tool-2",
        name: "tool_execute_python",
        args: {
          code: "print('hello')\nplt.savefig('demo.png')",
        },
        result:
          "Output: done\nArtifacts:\n- demo.png (image/png) -> C:\\temp\\generated\\demo.png",
      },
    };

    render(<ToolExecutionStrip block={block} />);

    expect(
      screen.queryByRole("region", { name: "Chi tiết script" }),
    ).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Chạy mã Python/i }));

    const detail = screen.getByRole("region", { name: "Chi tiết script" });
    expect(detail).toBeTruthy();
    expect(screen.getByText(/print\('hello'\)/i)).toBeTruthy();
    expect(screen.queryByText(/C:\\temp\\generated/i)).toBeNull();
    expect(detail.textContent || "").toContain("demo.png");
  });

  it("uses softer phrasing for visual generation strips", () => {
    const block: ToolExecutionBlockData = {
      type: "tool_execution",
      id: "tool-visual-1",
      status: "completed",
      tool: {
        id: "tool-visual-1",
        name: "tool_generate_visual",
        args: {
          title: "Softmax vs linear attention",
        },
        result: '{"title":"Softmax vs linear attention"}',
      },
    };

    render(<ToolExecutionStrip block={block} />);

    expect(
      screen.getByText(
        "Đang phác thảo minh họa cho: Softmax vs linear attention",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText("Đã chèn minh họa ngay trong câu trả lời"),
    ).toBeNull();
    expect(screen.queryByText(/ky thuat/i)).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: /Dựng visual giải thích/i }),
    );
    expect(
      screen.getByText("Đã chèn minh họa ngay trong câu trả lời"),
    ).toBeTruthy();
  });

  it("shows a professional web-search trace while keeping results collapsed", () => {
    const block: ToolExecutionBlockData = {
      type: "tool_execution",
      id: "tool-search-1",
      status: "completed",
      tool: {
        id: "tool-search-1",
        name: "tool_web_search",
        args: {
          query: "thời tiết Hải Phòng hôm nay",
        },
        result: JSON.stringify([
          {
            title: "Dự báo thời tiết Hải Phòng",
            url: "https://weather.gov.vn/hai-phong",
            snippet: "Thông tin dự báo trong ngày.",
          },
        ]),
      },
    };

    render(<ToolExecutionStrip block={block} />);

    const strip = screen.getByTestId("tool-execution-strip");
    expect(strip.getAttribute("data-tool-kind")).toBe("search");
    expect(screen.getByText("Tìm kiếm web")).toBeTruthy();
    expect(screen.getByText("Đã xong")).toBeTruthy();
    expect(screen.getByText("Truy vấn")).toBeTruthy();
    expect(screen.getByText("thời tiết Hải Phòng hôm nay")).toBeTruthy();
    expect(screen.queryByText("Dự báo thời tiết Hải Phòng")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Tìm kiếm web/i }));

    expect(screen.getByText("Nguồn tìm được")).toBeTruthy();
    expect(screen.getByText("Dự báo thời tiết Hải Phòng")).toBeTruthy();
    expect(screen.getByText("weather.gov.vn")).toBeTruthy();
    expect(strip.textContent || "").not.toContain('"snippet"');
  });

  it("shows weather tool traces as location-aware status instead of a generic tool", () => {
    const block: ToolExecutionBlockData = {
      type: "tool_execution",
      id: "tool-weather-1",
      status: "completed",
      tool: {
        id: "tool-weather-1",
        name: "current_weather",
        args: {
          city: "Hải Phòng",
        },
        result: "Chưa có kết nối thời tiết trực tiếp.",
      },
    };

    render(<ToolExecutionStrip block={block} />);

    const strip = screen.getByTestId("tool-execution-strip");
    expect(strip.getAttribute("data-tool-kind")).toBe("weather");
    expect(screen.getByText("Tra thời tiết")).toBeTruthy();
    expect(screen.getByText("Địa điểm")).toBeTruthy();
    expect(screen.getByText("Hải Phòng")).toBeTruthy();
    expect(screen.queryByText("Tình trạng")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Tra thời tiết/i }));

    expect(screen.getByText("Tình trạng")).toBeTruthy();
    expect(
      screen.getByText("Chưa có kết nối thời tiết trực tiếp."),
    ).toBeTruthy();
  });

  it("uses structured weather status before falling back to text matching", () => {
    const block: ToolExecutionBlockData = {
      type: "tool_execution",
      id: "tool-weather-json",
      status: "completed",
      tool: {
        id: "tool-weather-json",
        name: "current_weather",
        args: {
          city: "Hải Phòng",
        },
        result: JSON.stringify({
          status: "error",
          reason_code: "no_data",
          message: "Provider returned an empty response.",
        }),
      },
    };

    render(<ToolExecutionStrip block={block} />);
    fireEvent.click(screen.getByRole("button", { name: /Tra thời tiết/i }));

    expect(screen.getByText("Chưa lấy được thời tiết hiện tại.")).toBeTruthy();
  });

  it("marks pending tool calls as busy without inventing output", () => {
    const block: ToolExecutionBlockData = {
      type: "tool_execution",
      id: "tool-search-pending",
      status: "pending",
      tool: {
        id: "tool-search-pending",
        name: "tool_web_search",
        args: {
          query: "NVIDIA models API",
        },
      },
    };

    render(<ToolExecutionStrip block={block} />);

    const strip = screen.getByTestId("tool-execution-strip");
    const button = screen.getByRole("button", { name: /Tìm kiếm web/i });
    expect(strip.getAttribute("aria-busy")).toBe("true");
    expect(button).toHaveProperty("disabled", true);
    expect(screen.getByText("Đang gọi")).toBeTruthy();
    expect(screen.getByText("NVIDIA models API")).toBeTruthy();
    expect(screen.queryByText("Nguồn tìm được")).toBeNull();
  });
});
