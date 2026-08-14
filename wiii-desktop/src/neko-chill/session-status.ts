import type { NekoSessionStatus } from "./stores/neko-session-store";

export const NEKO_SESSION_STATUS_LABELS = {
  connecting: "đang kết nối",
  stopping: "đang dừng",
  dispatching: "đang lưu & gửi",
  idle: "sẵn sàng",
  streaming: "đang làm việc",
  exited: "runtime đã dừng",
  error: "có lỗi",
} satisfies Record<NekoSessionStatus, string>;
