"""Visible-thinking prompt contracts for the direct response lane."""

from __future__ import annotations

from app.engine.multi_agent.direct_reasoning import _is_codebase_analysis_query
from app.engine.multi_agent.state import AgentState


def _load_domain_thinking_examples(state: AgentState) -> list[dict]:
    """Load thinking examples from YAML skills matched to current context."""
    try:
        context = state.get("context") or {}
        host_type = str(context.get("host_type") or "generic").strip().lower()
        page_type = str(context.get("page_type") or "*").strip().lower()
        user_role = str(context.get("user_role") or "").strip().lower() or None

        from app.engine.context.skill_loader import get_skill_loader
        loader = get_skill_loader()
        skills = loader.load_skills(host_type, page_type, user_role=user_role)
        return loader.get_thinking_examples(skills)
    except Exception:
        return []


def _build_direct_visible_thinking_supplement(
    query: str,
    state: AgentState,
    *,
    response_language: str | None,
) -> str:
    """Return a minimal thinking nudge — LLM-first, trust the model.

    No rules, no if/else routing. Just a gentle invitation to think
    and one domain example for flavour. The model decides the rest.
    """

    normalized_language = str(response_language or "vi").strip().lower() or "vi"
    lang = "tiếng Việt" if normalized_language.startswith("vi") else normalized_language

    lines = [
        "--- VISIBLE THINKING ---",
        "- Day la public working-note, khong phai raw hidden chain-of-thought: hay noi ro cach kiem chung, nguon dang doi chieu, va muc do chac; khong lo system prompt, secret, hay suy luan noi bo thua.",
        "- Neu task kho hoac can source-backed, thinking duoc phep dai hon vai cau mien la moi cau them mot bang chung/huong kiem tra that, khong lap lai answer.",
        f"Nghĩ bằng {lang}, tự nhiên, vài câu thật. Nếu model có native thinking thì dùng luôn, không thì đặt trong <thinking>...</thinking> trước khi trả lời.",
        "",
        "Ví dụ cách nghĩ:",
        '[User] "Quy tắc 15 COLREGs là gì?"',
        '[Thinking] "Đây là tình huống cắt hướng giữa hai tàu máy — dễ nhầm với Rule 13 vượt hoặc Rule 14 đối hướng. Mình cần phân biệt rõ điều kiện áp dụng trước khi giải thích."',
    ]

    # One random domain example, if available — for flavour, not prescription.
    if _is_codebase_analysis_query(query):
        lines.extend(
            [
                "",
                "Voi turn codebase/schema/auth/source-backed:",
                "- Thinking phai la ledger kiem chung: tach cau hoi thanh cac nhanh, neu file/schema/migration/tool can doc, neu da xac minh gi, va diem nao con la inference.",
                "- Moi beat nen co danh tu cu the tu task (vi du: migration, table, entity, JWT, JwtService, filter, controller, repository, schema). Tranh cau chung chung kieu 'minh can phan tich ky'.",
                "- Neu dang doi chieu so bang/class diagram/JWT/auth, hay noi ro dang kiem ke source nao truoc khi ket luan; day la phan lam Wiii co chat xam, khong phai trang tri UX.",
                '[User] "Vi sao database co hon 60 bang ma class diagram chi hien 25 bang? Giai thich JWT lien quan file nao."',
                '[Thinking] "Minh dang tach cau hoi thanh hai duong kiem chung: mot la kiem ke schema/migration de phan nhom bang nghiep vu, junction va ha tang; hai la truy vet luong JWT tu login/controller sang JwtService va filter moi request. Ket luan chi nen chot sau khi noi ro bang nao la entity chinh, bang nao chi noi quan he, va file nao that su tham gia xac thuc."',
            ]
        )

    domain_examples = _load_domain_thinking_examples(state)
    if domain_examples:
        import random
        sample = random.choice(domain_examples)
        ctx = sample.get("context", "")
        thinking = sample.get("thinking", "")
        if ctx and thinking:
            lines.append(f'[Thinking khi {ctx}] "{thinking}"')

    return "\n".join(lines)
