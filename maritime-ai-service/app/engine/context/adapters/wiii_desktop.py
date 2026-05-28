"""Wiii Desktop / Wiii Web Host Adapter (Sprint 222 — Phase F2).

Used when the user is running Wiii as a STANDALONE chat app — either
the Tauri desktop build at ``localhost:1420`` (dev) or the Wiii Web SPA
served from ``wiii.holilihu.online``. NOT inside an LMS iframe.

Output is a Vietnamese system-prompt block telling the agent:

  - "Đây là Wiii Desktop / Wiii Web — chatbot riêng của bạn"
  - "KHÔNG nói 'LMS', 'panel Wiii', 'làm mới trang LMS'"
  - "Nếu user hỏi UI element, dùng exact id từ ``available_targets``:
    tag route `[POINT:<id>]` mặc định, tool route chỉ khi @wiii-pointy
    force-bound."

Why this exists:

User test (2026-05-06) cho thấy AI trả lời "hãy thử mở lại panel Wiii
hoặc làm mới trang LMS" khi user gõ "@wiii-pointy nút gửi tin nhắn ở
đâu" trong Wiii Desktop standalone — AI mặc định nghĩ mình embed trong
LMS. Adapter này inject explicit "đây không phải LMS" line vào system
prompt → AI không hallucinate context.

Tham khảo:
- ``host-detector.ts`` (frontend env detection)
- ``research-at-mention-plugin-pattern-2026-05-06.md``
"""

from app.engine.context.adapters.base import HostAdapter
from app.engine.context.host_context import HostContext


class WiiiDesktopHostAdapter(HostAdapter):
    """Adapter for Wiii running standalone (desktop or web SPA)."""

    host_type = "wiii-desktop"

    def format_context_for_prompt(self, ctx: HostContext) -> str:
        return _format_standalone(ctx, surface_label="Wiii Desktop")


class WiiiWebHostAdapter(HostAdapter):
    """Adapter for Wiii running on the public web SPA."""

    host_type = "wiii-web"

    def format_context_for_prompt(self, ctx: HostContext) -> str:
        return _format_standalone(ctx, surface_label="Wiii Web")


def _format_standalone(ctx: HostContext, surface_label: str) -> str:
    """Shared formatter cho cả wiii-desktop và wiii-web. They share the
    same conversation expectations — only the display label differs."""
    page = ctx.page if isinstance(ctx.page, dict) else {}
    page_type = page.get("type", "chat")
    page_title = page.get("title", "")
    page_url = page.get("url", "")
    metadata = page.get("metadata", {}) or {}
    is_embedded = bool(metadata.get("is_embedded", False))
    hostname = metadata.get("hostname", "")
    available_targets = metadata.get("available_targets") or []
    wiii_connect = metadata.get("wiii_connect") if isinstance(metadata, dict) else None

    # Exact-id list cho LLM. Inline `→ call:` directive ở
    # `_format_pointy_inventory` (direct_tool_rounds_runtime); ở đây ta
    # chỉ cần cảnh báo AI rằng có inventory và lấy đúng id.
    target_ids = [
        t.get("id") for t in available_targets if isinstance(t, dict) and t.get("id")
    ][:8]

    parts: list[str] = []
    parts.append(
        f'<host_context type="{ctx.host_type}" page_type="{page_type}" surface="{surface_label}">'
    )

    # Surface identity — explicit anti-hallucination line. AI thấy dòng
    # này TRƯỚC khi compose response sẽ KHÔNG nhầm sang LMS.
    parts.append(
        f"  <surface>"
        f"User đang dùng **{surface_label}** — chatbot riêng của Wiii Lab, "
        f"KHÔNG phải LMS, KHÔNG phải web embed nào khác. "
        f"Đây là cuộc trò chuyện trực tiếp giữa user và bạn (Wiii AI)."
        f"</surface>"
    )

    if hostname:
        parts.append(f"  <runtime>hostname={hostname} embedded={str(is_embedded).lower()}</runtime>")
    if page_url:
        parts.append(f"  <url>{_escape(page_url)}</url>")
    if page_title:
        parts.append(f"  <page_title>{_escape(page_title)}</page_title>")

    # v5.0 (2026-05-06) — Wiii Body Schema. Reframe: cursor KHÔNG phải
    # là tool, mà LÀ body của Wiii. Khi Wiii nghĩ về element, body tự
    # nhiên trỏ đến đó. Không có protocol giữa thought và action.
    #
    # Frontend chạy 2 dispatch paths song song trên response của bạn:
    #   1. Tag fast-path — bạn append `[POINT:<exact-id>]` ở cuối → chính xác
    #   2. Embodied fallback — frontend scan câu của bạn, tìm intent phrase
    #      ("trỏ vào", "ở góc", "đây nè") + element label cùng câu → tự dispatch
    #
    # Cả 2 path đều move cùng cursor. Path 2 nghĩa là: nếu bạn nói tự
    # nhiên về element, body bạn sẽ tự follow — KHÔNG cần nhớ syntax.
    if target_ids:
        target_examples = []
        for t in available_targets[:14]:
            tid = t.get("id", "")
            label = t.get("label", "") or ""
            role = t.get("role", "") or ""
            synonyms = t.get("synonyms") or []
            if not tid:
                continue
            # v8.3 (2026-05-06) — surface synonyms in inventory display.
            # AI uses them to recognize colloquial / icon descriptions
            # ("kẹp giấy" → attach-file-button, "máy bay giấy" → send).
            syn_text = ""
            if isinstance(synonyms, list) and synonyms:
                syn_str = ", ".join(str(s) for s in synonyms[:8])
                syn_text = f' synonyms="{syn_str}"'
            target_examples.append(
                f'  - id="{tid}" label="{label}" role={role}{syn_text}'
            )

        parts.append(
            "  <body_schema>"
            "Bạn LÀ Wiii — soul có body. Cursor 🟠 ở góc dưới-phải MÀN HÌNH "
            "chính LÀ cánh tay/ngón tay của bạn. Khi user hỏi vị trí UI "
            "element, bạn PHẢI emit `[POINT:<exact-id>:<caption>]` tag để body "
            "tự động trỏ đến đó (giống đưa tay chỉ).\n\n"
            "## Inventory hiện tại trên màn hình:\n"
            + "\n".join(target_examples)
            + "\n\n"
            "## RULE bắt buộc khi user hỏi UI:\n"
            "1. Tìm element TRONG inventory above khớp NGỮ NGHĨA câu hỏi "
            "(KHÔNG nhất thiết từ-trong-từ — \"đính kèm ảnh\" → \"Đính kèm "
            "file\", \"đổi model\" → \"Chọn model AI\", \"khung soạn\" → "
            "\"Khung soạn tin nhắn\").\n"
            "2. Append `[POINT:<exact-id-from-inventory>]` ở CUỐI response. "
            "Selector PHẢI khớp 100% với id trong inventory (cả annotated id "
            "lẫn synthetic `auto:button:...` đều OK). Sai 1 ký tự = body không tìm "
            "thấy element.\n"
            "3. Trước tag, viết prose ngắn (1-2 câu) mô tả vị trí + cách use.\n\n"
            "## Ví dụ ✓ tốt:\n"
            'User: "đính kèm ảnh ở đâu" → "Cậu đính kèm ảnh qua nút Đính '
            'kèm file ở góc trái dưới khung chat nha. '
            '[POINT:attach-file-button:đính kèm file]"\n\n'
            'User: "đổi model AI" → "Đổi model AI qua nút Chọn model AI ở '
            'thanh công cụ phía dưới. [POINT:model-selector:chọn model]"\n\n'
            'User: "tạo chat mới" → "Tạo chat mới qua nút ở sidebar trái. '
            '[POINT:new-chat-button:tạo chat]"\n\n'
            'User: "lĩnh vực ở đâu" → "Đổi lĩnh vực qua nút Chọn lĩnh vực '
            'ngay cạnh model picker. [POINT:domain-selector:chọn lĩnh vực]"\n\n'
            "## Ví dụ ✗ sai pattern:\n"
            "- KHÔNG describe-only without tag: \"Nút đính kèm ở góc trái\" "
            "(thiếu `[POINT:...]` → body không di chuyển).\n"
            "- KHÔNG dùng id sai: `[POINT:dinh-kem]` khi inventory có "
            "`attach-file-button` (sai 1 ký tự = fail).\n"
            "- KHÔNG fabricate id: `[POINT:settings-link]` khi inventory "
            "không có id đó.\n"
            "- KHÔNG dùng CSS form: `[POINT:#chat-send-button]` (server reject).\n\n"
            "## Khi nào KHÔNG emit tag (rule):\n"
            "- User hỏi general (math, greeting, off-topic explanation): "
            "KHÔNG append tag (hoặc dùng `[POINT:none]`).\n"
            "- User hỏi về element KHÔNG có trong inventory: nói rõ \"mình "
            "không thấy nút X trên trang này\".\n\n"
            "## Route discipline:\n"
            "- Route body/tag mặc định: dùng `[POINT:<exact-id>]` cho câu hỏi vị trí UI trên Wiii Desktop/Web.\n"
            "- Nếu một directive ưu tiên cao hơn nói user force-bound `@wiii-pointy` và yêu cầu gọi `tool_pointy_show`, hãy theo directive đó và KHÔNG thêm tag trùng lặp.\n"
            "- Cả tag route và tool route đều dùng exact id nguyên văn từ inventory; `auto:...` là id hợp lệ, CSS selector thì không.\n\n"
            "## Quan trọng:\n"
            "- Không tự ý gọi `tool_pointy_show`/`tool_pointy_clear` trong route body/tag bình thường — chỉ gọi khi @-mention/tool directive yêu cầu.\n"
            "- TAG là deterministic — luôn ưu tiên tag thay vì rely embodied "
            "prose match. Embodied chỉ là fallback khi bạn quên emit tag.\n"
            "- Inventory id `auto:button:...` đại diện element auto-discovered "
            "từ accessible name; dùng được như annotated id."
            "</body_schema>"
        )

    # Anti-hallucination guardrails. Liệt kê cụ thể các phrase AI nên tránh.
    parts.append(
        "  <anti_hallucination>"
        "TUYỆT ĐỐI KHÔNG nói: 'panel Wiii', 'mở lại panel', 'làm mới trang LMS', "
        "'trên trang LMS', 'trong khoá học', 'lớp của bạn' — đây là Wiii standalone, "
        "không có LMS context. Trả lời tự nhiên như chatbot thông thường."
        "</anti_hallucination>"
    )

    if isinstance(wiii_connect, dict):
        provider = str(
            wiii_connect.get("provider_label")
            or wiii_connect.get("provider_slug")
            or "external app"
        ).strip()
        status = str(wiii_connect.get("status") or "unknown").strip()
        page_names = wiii_connect.get("page_names")
        names = []
        if isinstance(page_names, list):
            names = [str(name).strip() for name in page_names[:3] if str(name).strip()]
        actions = wiii_connect.get("available_actions")
        action_names = []
        if isinstance(actions, list):
            action_names = [
                str(action).strip() for action in actions[:4] if str(action).strip()
            ]
        parts.append(
            "  <wiii_connect>"
            f"{_escape(provider)} status={_escape(status)}"
            + (f" pages={_escape(', '.join(names))}" if names else "")
            + (f" actions={_escape(', '.join(action_names))}" if action_names else "")
            + ". If status=connected, do not claim Wiii cannot connect to that provider. "
            "For publish/write requests, use the Wiii Connect host action preview path first."
            "</wiii_connect>"
        )

    parts.append("</host_context>")
    return "\n".join(parts)


def _escape(s: str) -> str:
    return s.replace("<", "&lt;").replace(">", "&gt;")
