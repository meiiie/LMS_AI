# Next-session prompt - 2026-05-07

Paste the fenced block below into a fresh Codex session when continuing Pointy/Wiii work.

```text
Bạn là Codex trong repo E:\Sach\Sua\AI_v1. Tiếp tục Wiii Agentic / Pointy theo handoff 2026-05-07. Báo cáo lần này quan trọng, nên ưu tiên chính xác, source-backed, và giữ worktree an toàn.

Mở đầu cố định:
"Mình sẽ tiếp tục Pointy theo đúng handoff 2026-05-07: đọc 8 nguồn trước, kiểm tra contract hai đường dispatch, rồi mới sửa nhỏ và verify."

Đọc 8 nguồn theo thứ tự này trước khi viết code:

1. AGENTS.md
2. .agents/skills/git-management/SKILL.md
3. .agents/skills/wiii-app-widget-bridge/SKILL.md
4. memory/MEMORY.md
5. memory/handoff-pointy-v9-f18-2026-05-07.md
6. maritime-ai-service/app/engine/skills/library/wiii-pointy/SKILL.md
7. wiii-desktop/src/hooks/useSSEStream.ts
8. maritime-ai-service/app/api/v1/chat_stream_presenter.py

7 quy tắc tư duy:

1. LLM-first: khóa language/inventory/body-schema contract trước, rồi mới tối ưu motion/art.
2. Quality > speed: báo cáo quan trọng hơn tốc độ; viết ít nhưng đúng, có test.
3. Source-backed: mọi kết luận kỹ thuật phải bám file, line, test, hoặc capture.
4. Two-step before write: đọc code/test liên quan, nêu plan ngắn, rồi mới sửa.
5. SKILL rules: nếu task chạm git/bridge/visual/runtime, đọc SKILL.md tương ứng trong turn đó.
6. Two Pointy paths: luôn bảo toàn cả explicit tag path và embodied prose fallback.
7. Realistic threshold: embodied threshold 0.6 không phải phép màu; chỉ dispatch khi có target inventory + intent signal đủ rõ.

Priority 1 - cursor motion math:

Plan đề xuất:
1. Đọc wiii-desktop/src/pointy-host/min-jerk-trajectory.ts.
2. Đọc wiii-desktop/src/pointy-host/motion-engine.ts.
3. Đọc wiii-desktop/src/pointy-host/registry.ts và api.ts.
4. Thêm failing tests trước nếu cần cho very small target, long-distance move, mid-flight redirect, dock return, reduced motion, transform rounding.
5. Sửa surgical, không đụng parser/SSE nếu không bắt buộc.
6. Verify bằng vitest Pointy suite.

Priority 2 - awareness and feedback:

Plan đề xuất:
1. Đọc awareness.ts, integration.ts, user-attention.ts, user-cursor.ts.
2. Xác định snapshot nào thật sự cần đưa vào host_context.
3. Chuẩn hóa feedback theo WidgetResultV1-style thinking: widget_id, widget_kind, status, summary, payload, session_id, message_id, timestamp.
4. Đảm bảo dispatch failure có semantic feedback, không dump raw payload.
5. Giữ LMS/WebMCP/host bridge backward-compatible.

Priority 3 - cursor art:

Plan đề xuất:
1. Chỉ làm sau khi P1/P2 ổn.
2. Giữ pointer-events:none, reduced-motion, transform JS-driven.
3. Không thêm CSS keyframe transform gây jitter.
4. Tạo visual polish có test hoặc manual screenshot/smoke rõ ràng.

Quy trình làm việc 6 bước:

1. Chạy git status --short --branch; ghi nhận dirty worktree, không revert gì không phải của mình.
2. Đọc nguồn liên quan; nếu có nghi ngờ, dùng rg/Select-String thay vì đoán.
3. Viết plan nhỏ, nêu risk và verification trước khi edit.
4. Thêm hoặc cập nhật test trước nếu behavior chưa được khóa.
5. Sửa tối thiểu, dùng apply_patch cho manual edits.
6. Chạy verification hẹp trước, rồi git diff --check và git status --short.

Đừng làm:

1. Đừng dùng tool_pointy_show/tool_pointy_clear làm primary architecture; đó chỉ là compatibility.
2. Đừng guess selector/id ngoài inventory.
3. Đừng dùng [POINT:#css-selector] hoặc [POINT:.class]; tag phải là bare id.
4. Đừng strip [POINT:...] khỏi raw stream trước khi frontend parser đọc.
5. Đừng chỉ test explicit tag rồi tuyên bố embodied fallback ổn.
6. Đừng sửa parser, SSE, motion, art, docs trong một patch lẫn lộn.
7. Đừng bỏ qua SSE wire khi bug là "backend nói đã dispatch nhưng cursor không chạy".
8. Đừng chạm file unrelated trong dirty worktree.

Context hiện tại:

- Ngày handoff: 2026-05-07.
- Repo: E:\Sach\Sua\AI_v1.
- Branch quan sát: main...origin/main.
- Worktree rất bẩn; bảo vệ thay đổi sẵn có.
- Backend verification gần nhất: python -m pytest tests/unit/test_chat_stream_presenter.py -q -p no:capture --tb=short -> 12 passed.
- Frontend verification gần nhất: npx vitest run dispatch/inline/embodied/min-jerk/motion tests -> 5 files, 91 tests passed.
- SSE capture hiện có cho thấy stream kết thúc done; không xem đó là bằng chứng Pointy đầy đủ.
- Capture có model deepseek-ai/deepseek-v4-flash, provider nvidia.

Bắt đầu bằng câu mở đầu cố định, rồi thực hiện đọc 8 nguồn. Nếu task là code, sau khi đọc hãy chọn đúng priority và triển khai end-to-end.
```
