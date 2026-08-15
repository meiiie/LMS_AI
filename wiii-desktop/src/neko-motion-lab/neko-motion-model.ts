export const NEKO_MOTION_STATES = [
  "ready",
  "listening",
  "thinking",
  "tool-running",
  "success",
  "attention",
  "idle",
  "recover",
] as const;

export type NekoMotionState = (typeof NEKO_MOTION_STATES)[number];

export interface NekoMotionPreset {
  label: string;
  shortLabel: string;
  meaning: string;
  evidence: string;
  tilt: number;
  lift: number;
  scale: number;
  eyeOpen: number;
  gazeX: number;
  gazeY: number;
  tail: number;
  statusDot: boolean;
  holdMs: number;
}
export interface NekoMotionControls {
  energy: number;
  gazeX: number;
  gazeY: number;
  tail: number;
}

export interface NekoResolvedPose {
  tilt: number;
  lift: number;
  scale: number;
  eyeOpen: number;
  gazeX: number;
  gazeY: number;
  tail: number;
  statusDot: boolean;
}

export const NEKO_MOTION_PRESETS: Record<NekoMotionState, NekoMotionPreset> = {
  ready: {
    label: "Sẵn sàng",
    shortLabel: "Ready",
    meaning: "Có mặt, bình tĩnh, sẵn sàng lắng nghe.",
    evidence: "Phiên đã sẵn sàng và không có lượt chạy.",
    tilt: 0,
    lift: 0,
    scale: 1,
    eyeOpen: 1,
    gazeX: 0,
    gazeY: 0,
    tail: 0,
    statusDot: false,
    holdMs: 1700,
  },
  listening: {
    label: "Đang lắng nghe",
    shortLabel: "Listening",
    meaning: "Chú ý hơn một chút nhưng không thúc giục.",
    evidence: "Ô soạn thảo hoặc đầu vào giọng nói đang hoạt động.",
    tilt: 0,
    lift: -3,
    scale: 1.015,
    eyeOpen: 1,
    gazeX: 0,
    gazeY: 0.08,
    tail: 0.05,
    statusDot: false,
    holdMs: 1600,
  },
  thinking: {
    label: "Đang suy nghĩ",
    shortLabel: "Thinking",
    meaning: "Nghiêng nhẹ và nhìn về vùng làm việc.",
    evidence: "Model turn hoặc reasoning đã bắt đầu.",
    tilt: 7,
    lift: -2,
    scale: 1,
    eyeOpen: 0.94,
    gazeX: 0.42,
    gazeY: -0.24,
    tail: 0.12,
    statusDot: false,
    holdMs: 2100,
  },
  "tool-running": {
    label: "Đang dùng công cụ",
    shortLabel: "Tool",
    meaning: "Giữ vững, đuôi lắng một nhịp ngắn.",
    evidence: "Runtime đã phát tool-call start.",
    tilt: 0,
    lift: 0,
    scale: 1,
    eyeOpen: 0.98,
    gazeX: 0.18,
    gazeY: 0,
    tail: 0.72,
    statusDot: false,
    holdMs: 1900,
  },
  success: {
    label: "Đã hoàn thành",
    shortLabel: "Success",
    meaning: "Một nhịp nâng nhỏ, rồi trở về nghỉ.",
    evidence: "Lượt hoặc tác vụ đã hoàn tất thành công.",
    tilt: 0,
    lift: -8,
    scale: 1.025,
    eyeOpen: 0.78,
    gazeX: 0,
    gazeY: -0.08,
    tail: 0.36,
    statusDot: false,
    holdMs: 1450,
  },
  attention: {
    label: "Cần bạn chú ý",
    shortLabel: "Attention",
    meaning: "Nghiêng về phía đối diện và bật dấu trạng thái ngoài mặt.",
    evidence: "Runtime đang chờ quyền, lựa chọn hoặc thông tin làm rõ.",
    tilt: -6,
    lift: -1,
    scale: 1.005,
    eyeOpen: 1,
    gazeX: -0.34,
    gazeY: -0.12,
    tail: -0.08,
    statusDot: true,
    holdMs: 2200,
  },
  idle: {
    label: "Đang nghỉ",
    shortLabel: "Idle / Nap",
    meaning: "Hạ thấp, khép mắt và đứng yên.",
    evidence: "Phiên được tạm dừng hoặc không còn hoạt động có chủ đích.",
    tilt: 0,
    lift: 7,
    scale: 0.985,
    eyeOpen: 0.13,
    gazeX: 0,
    gazeY: 0.2,
    tail: -0.1,
    statusDot: false,
    holdMs: 1800,
  },
  recover: {
    label: "Đã ổn định lại",
    shortLabel: "Recover",
    meaning: "Trở về trung tính; lỗi được giải thích bằng UI, không bằng mặt buồn.",
    evidence: "Kết nối đã phục hồi hoặc giao diện đang mô tả lỗi.",
    tilt: 0,
    lift: 1,
    scale: 0.995,
    eyeOpen: 0.9,
    gazeX: 0,
    gazeY: 0,
    tail: 0,
    statusDot: false,
    holdMs: 1650,
  },
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function resolveNekoPose(
  state: NekoMotionState,
  controls: NekoMotionControls,
  reducedMotion: boolean,
): NekoResolvedPose {
  const preset = NEKO_MOTION_PRESETS[state];
  const energy = clamp(controls.energy, 0, 1);
  const manualGazeX = clamp(controls.gazeX, -1, 1);
  const manualGazeY = clamp(controls.gazeY, -1, 1);
  const manualTail = clamp(controls.tail, -1, 1);

  return {
    tilt: reducedMotion ? 0 : clamp(preset.tilt * energy, -8, 8),
    lift: reducedMotion ? 0 : clamp(preset.lift * energy, -9, 9),
    scale: reducedMotion ? 1 : 1 + (preset.scale - 1) * energy,
    eyeOpen: clamp(preset.eyeOpen, 0.12, 1),
    gazeX: clamp((preset.gazeX + manualGazeX) * energy, -1, 1),
    gazeY: clamp((preset.gazeY + manualGazeY) * energy, -1, 1),
    tail: reducedMotion ? 0 : clamp((preset.tail + manualTail) * energy, -1, 1),
    statusDot: preset.statusDot,
  };
}

export function nextNekoMotionState(state: NekoMotionState): NekoMotionState {
  const index = NEKO_MOTION_STATES.indexOf(state);
  return NEKO_MOTION_STATES[(index + 1) % NEKO_MOTION_STATES.length];
}
