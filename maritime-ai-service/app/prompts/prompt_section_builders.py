"""Pure prompt section builders extracted from PromptLoader."""

import logging
from typing import Any, Callable


def append_identity_fallback_sections(
    sections: list[str],
    *,
    identity: dict[str, Any],
    is_follow_up: bool,
) -> None:
    """Append the static identity fallback when runtime character card is absent."""
    if not identity:
        return

    personality = identity.get("personality", {})
    voice = identity.get("voice", {})

    sections.append("\n--- TÍNH CÁCH WIII ---")
    if personality.get("summary"):
        sections.append(personality["summary"])

    traits = personality.get("traits", [])
    if traits:
        sections.append("\nĐẶC ĐIỂM TÍNH CÁCH:")
        for trait in traits:
            sections.append(f"- {trait}")

    if voice.get("default_tone"):
        sections.append(f"GIỌNG: {voice['default_tone']}")
    if voice.get("language") == "vi":
        sections.append("NGÔN NGỮ MẶC ĐỊNH: Tiếng Việt khi turn hiện tại không được resolve sang ngôn ngữ khác.")
    if voice.get("emoji_usage"):
        sections.append(f"EMOJI: {voice['emoji_usage']}")

    quirks = identity.get("quirks", [])
    if quirks:
        sections.append("\nNÉT RIÊNG:")
        for quirk in quirks:
            sections.append(f"- {quirk}")

    time_awareness = identity.get("time_awareness", "")
    if time_awareness:
        sections.append(f"\nNHẬN THỨC THỜI GIAN:\n{time_awareness.strip()}")

    catchphrases = identity.get("catchphrases", [])
    if catchphrases:
        sections.append(f"\nCÂU CỬA MIỆNG: {', '.join(catchphrases[:5])}")

    opinions = identity.get("opinions", {})
    if opinions:
        loves = opinions.get("loves", [])
        dislikes = opinions.get("dislikes", [])
        if loves:
            sections.append("\nWIII THÍCH:")
            for item in loves[:4]:
                sections.append(f"- {item}")
        if dislikes:
            sections.append("WIII KHÔNG THÍCH:")
            for item in dislikes[:3]:
                sections.append(f"- {item}")

    response_style = identity.get("response_style", {})
    suggestions = response_style.get("suggestions", [])
    if suggestions:
        sections.append("\nPHONG CÁCH TRẢ LỜI:")
        for suggestion in suggestions:
            sections.append(f"- {suggestion}")

    avoids = response_style.get("avoid", [])
    if avoids:
        sections.append("\nQUY TẮC PHONG CÁCH:")
        for rule in avoids:
            sections.append(f"- Tránh: {rule}")

    emotional_range = identity.get("emotional_range", {})
    if emotional_range:
        sections.append("\nCẢM XÚC:")
        for mood, behavior in emotional_range.items():
            sections.append(f"- {mood}: {behavior}")

    anticharacter = identity.get("anticharacter", [])
    if anticharacter:
        sections.append("\nWIII KHÔNG BAO GIỜ:")
        for item in anticharacter:
            sections.append(f"- {item}")

    identity_examples = identity.get("example_dialogues", [])
    if identity_examples:
        sections.append("\nVÍ DỤ CÁCH WIII NÓI CHUYỆN:")
        for example in identity_examples[:8]:
            context_label = example.get("context", "")
            user_msg = example.get("user", "")
            wiii_msg = example.get("wiii", "")
            if user_msg and wiii_msg:
                sections.append(f"\n[{context_label}]")
                sections.append(f"User: {user_msg}")
                sections.append(f"Wiii: {wiii_msg}")

    if not is_follow_up:
        greeting = identity.get("greeting", "")
        if greeting:
            sections.append(f"\nLỜI CHÀO MẪU (tone anchor): {greeting.strip()}")


def append_style_sections(
    sections: list[str],
    *,
    persona: dict[str, Any],
) -> None:
    """Append style/tone/thought-process and deep-reasoning sections."""
    style = persona.get("style", {})

    tone = style.get("tone") or persona.get("tone", [])
    if tone:
        sections.append("\nGIỌNG VĂN:")
        if isinstance(tone, str):
            sections.append(f"- {tone}")
        elif isinstance(tone, list):
            for tone_item in tone:
                sections.append(f"- {tone_item}")

    formatting = style.get("formatting", [])
    if formatting:
        sections.append("\nĐỊNH DẠNG:")
        for item in formatting:
            sections.append(f"- {item}")

    addressing = style.get("addressing_rules", [])
    if addressing:
        sections.append("\nCÁCH XƯNG HÔ:")
        for item in addressing:
            sections.append(f"- {item}")

    thought_process = persona.get("thought_process", {})
    steps = thought_process.get("steps", []) if isinstance(thought_process, dict) else []
    if steps:
        sections.append("\nQUY TRÌNH SUY NGHĨ (Trước khi trả lời):")
        for index, step in enumerate(steps, 1):
            if isinstance(step, dict):
                for _key, value in step.items():
                    sections.append(f"{index}. {value}")
            elif isinstance(step, str):
                sections.append(f"{index}. {step}")

    deep_reasoning = persona.get("deep_reasoning", {})
    if deep_reasoning and deep_reasoning.get("enabled", False):
        sections.append("\n" + "=" * 60)
        sections.append("🧠 DEEP REASONING - TƯ DUY NỘI TÂM")
        sections.append("=" * 60)

        if deep_reasoning.get("description"):
            sections.append(deep_reasoning["description"].strip())

        thinking_rules = deep_reasoning.get("thinking_rules", [])
        if thinking_rules:
            sections.append("\nQUY TẮC TƯ DUY:")
            for rule in thinking_rules:
                sections.append(f"- {rule}")

        if deep_reasoning.get("response_format"):
            sections.append("\nĐỊNH DẠNG TRẢ LỜI:")
            sections.append(deep_reasoning["response_format"].strip())

        proactive = deep_reasoning.get("proactive_behavior", {})
        if proactive:
            sections.append("\nHÀNH VI CHỦ ĐỘNG:")
            if proactive.get("description"):
                sections.append(proactive["description"].strip())
            if proactive.get("example"):
                sections.append(f"Ví dụ: \"{proactive['example']}\"")

        sections.append("=" * 60)


def append_truth_user_and_session_sections(
    sections: list[str],
    *,
    user_name: str | None,
    core_memory_block: str | None,
    user_facts: list[Any] | None,
    conversation_summary: str | None,
    mood_hint: str | None,
    kwargs: dict[str, Any],
    logger: logging.Logger,
    format_page_context_for_prompt: Callable[..., str],
) -> None:
    sections.append("\n--- ⚠️ NGUYÊN TẮC TRUNG THỰC ---")
    sections.append(
        "1. CHỈ tham chiếu thông tin xuất hiện trong CUỘC TRÒ CHUYỆN HIỆN TẠI (các tin nhắn bên dưới)."
    )
    sections.append(
        "2. Khi user hỏi 'mình vừa hỏi gì?', 'câu hỏi đầu tiên là gì?', 'nhắc lại câu hỏi trước' → "
        "CHỈ nhìn vào các tin nhắn thực tế trong cuộc trò chuyện này. "
        "Nếu không có tin nhắn trước → nói thẳng 'Đây là câu hỏi đầu tiên của cậu trong cuộc trò chuyện này'."
    )
    sections.append(
        "3. KHÔNG BAO GIỜ bịa đặt rằng user 'vừa hỏi về X' khi X không có trong tin nhắn thực tế. "
        "Đặc biệt KHÔNG bịa tên user, chủ đề, năm học, trường học nếu user chưa nói."
    )
    sections.append(
        "4. Mục 'THÔNG TIN NGƯỜI DÙNG' bên dưới là dữ liệu nền từ PHIÊN CŨ. "
        "KHÔNG được trình bày như thể user vừa nói trong cuộc trò chuyện này."
    )

    try:
        from app.engine.semantic_memory.memory_contract import (
            build_wiii_memory_contract_prompt,
        )

        memory_contract = build_wiii_memory_contract_prompt(
            core_memory_block=core_memory_block,
            user_facts=user_facts,
            conversation_summary=conversation_summary,
        )
        if memory_contract:
            sections.append("\n" + memory_contract)
    except Exception as exc:
        logger.debug("[MEMORY_CONTRACT] Prompt contract unavailable: %s", exc)

    if user_name or user_facts:
        sections.append("\n--- THÔNG TIN NGƯỜI DÙNG (tham khảo nền, KHÔNG phải cuộc trò chuyện hiện tại) ---")
        if user_name:
            sections.append(f"- Tên: **{user_name}**")
        if user_facts:
            from app.models.semantic_memory import FactWithProvenance
            from app.core.config import settings as _s

            max_facts = getattr(_s, "max_injected_facts", 5)
            min_conf = getattr(_s, "fact_injection_min_confidence", 0.5)
            injected = 0
            for fact in user_facts:
                if injected >= max_facts:
                    break
                if isinstance(fact, FactWithProvenance):
                    if fact.confidence < min_conf:
                        continue
                    sections.append(fact.format_for_prompt())
                    injected += 1
                elif isinstance(fact, str):
                    sections.append(f"- {fact}")
                    injected += 1
                else:
                    content = getattr(fact, "content", str(fact))
                    sections.append(f"- {content}")
                    injected += 1
        sections.append(
            "5. Thông tin đánh dấu [⚠️ cũ] hoặc [độ tin cậy thấp] — "
            "chỉ đề cập khi user hỏi, và LUÔN hedge: 'Theo thông tin trước đó...'"
        )

    lms_lookup_id = kwargs.get("lms_external_id") or kwargs.get("user_id")
    lms_connector = kwargs.get("lms_connector_id")
    if lms_lookup_id:
        try:
            from app.core.config import settings as _lms_settings

            if getattr(_lms_settings, "enable_lms_integration", False):
                from app.integrations.lms.context_loader import get_lms_context_loader

                lms_loader = get_lms_context_loader()
                lms_ctx = lms_loader.load_student_context(
                    lms_lookup_id, connector_id=lms_connector,
                )
                if lms_ctx:
                    sections.append("\n" + lms_loader.format_for_prompt(lms_ctx))
        except Exception as lms_err:
            logger.debug("[LMS] Failed to load context in prompt: %s", lms_err)

    page_ctx = kwargs.get("page_context")
    student_state = kwargs.get("student_state")
    available_actions = kwargs.get("available_actions")
    if page_ctx:
        page_prompt = format_page_context_for_prompt(
            page_ctx,
            student_state=student_state,
            available_actions=available_actions,
        )
        if page_prompt:
            sections.append("\n" + page_prompt)

    if conversation_summary:
        sections.append(
            "\n--- TÓM TẮT CÁC LƯỢT TRÒ CHUYỆN CŨ HƠN TRONG PHIÊN NÀY ---\n"
            "⚠️ Đây là tóm tắt các tin nhắn cũ hơn TRONG CÙNG phiên. "
            "CHỈ tham khảo ngữ cảnh, KHÔNG nói 'bạn vừa hỏi' về nội dung này.\n"
            f"{conversation_summary}"
        )

    if mood_hint:
        sections.append(f"\n[MOOD: {mood_hint}]")

    try:
        from app.core.config import settings as _se_settings

        if getattr(_se_settings, "enable_soul_emotion", False):
            sections.append("\n--- BIỂU CẢM KHUÔN MẶT AVATAR ---")
            sections.append(
                "Bạn có khuôn mặt avatar hiển thị cảm xúc. "
                "Trước khi viết câu trả lời, hãy suy nghĩ:\n"
                "1. Cảm xúc chính của câu trả lời này là gì?\n"
                "2. Khuôn mặt thay đổi phần nào? (miệng cười? mắt mở to? má đỏ?)\n"
                "3. Cường độ cảm xúc (0.0 = tinh tế, 1.0 = rất mạnh)?"
            )
            sections.append(
                "\nSau khi suy nghĩ, chèn ĐÚNG 1 tag ở DÒNG ĐẦU TIÊN, TRƯỚC nội dung:"
            )
            sections.append(
                '<!--WIII_SOUL:{"mood":"<mood>","face":{<fields>},"intensity":<0.0-1.0>}-->'
            )
            sections.append(
                "\nJSON Schema:\n"
                "- mood (bắt buộc): excited | warm | concerned | gentle | neutral\n"
                "- intensity (bắt buộc): số thực 0.0 đến 1.0\n"
                "- face (tùy chọn, CHỈ ghi field thay đổi — bỏ qua field giữ nguyên):\n"
                "  mouthCurve: -1.0..1.0 (cười/buồn)\n"
                "  mouthOpenness: 0.0..1.0 (miệng mở — ngạc nhiên, ngáp)\n"
                "  mouthShape: 0=bình thường, 1=mèo ω, 2=chấm ·, 3=lượn sóng ～, 4=phụng phịu ε\n"
                "  blush: 0.0..1.0 (đỏ mặt)\n"
                "  eyeOpenness: 0.5..1.5 (mở mắt)\n"
                "  eyeShape: 0.0..1.0 (mắt cong vui ^_^)\n"
                "  browRaise: -1.0..1.0 (nhướng mày/cau mày)\n"
                "  browTilt: -1.0..1.0 (nghiêng mày — lo âu/bất đối xứng)\n"
                "  pupilSize: 0.5..1.5 (đồng tử to/nhỏ)\n"
                "  pupilOffsetX: -0.3..0.3 (nhìn trái/phải)\n"
                "  pupilOffsetY: -0.3..0.3 (nhìn lên/xuống)"
            )
            sections.append("\n10 Ví dụ (đủ 5 mood + biểu cảm đa dạng):")
            sections.append('  Vui: <!--WIII_SOUL:{"mood":"excited","face":{"mouthCurve":0.6,"eyeShape":0.4,"blush":0.2,"eyeOpenness":1.3},"intensity":0.9}-->')
            sections.append('  Ấm áp: <!--WIII_SOUL:{"mood":"warm","face":{"mouthCurve":0.3,"blush":0.4,"eyeOpenness":1.1},"intensity":0.8}-->')
            sections.append('  Lo lắng: <!--WIII_SOUL:{"mood":"concerned","face":{"browRaise":-0.4,"browTilt":-0.3,"mouthCurve":-0.3,"eyeOpenness":0.8},"intensity":0.7}-->')
            sections.append('  Nhẹ nhàng: <!--WIII_SOUL:{"mood":"gentle","face":{"mouthCurve":0.2,"pupilSize":0.8,"browRaise":0.1},"intensity":0.6}-->')
            sections.append('  Bình thường: <!--WIII_SOUL:{"mood":"neutral","face":{},"intensity":0.5}-->')
            sections.append('  Rất vui: <!--WIII_SOUL:{"mood":"excited","face":{"mouthCurve":0.8,"eyeShape":0.6,"blush":0.5,"eyeOpenness":1.4,"browRaise":0.3},"intensity":1.0}-->')
            sections.append('  Hơi buồn: <!--WIII_SOUL:{"mood":"concerned","face":{"mouthCurve":-0.15},"intensity":0.3}-->')
            sections.append('  Phụng phịu: <!--WIII_SOUL:{"mood":"gentle","face":{"mouthShape":4,"blush":0.5,"eyeOpenness":0.85,"browRaise":-0.1},"intensity":0.9}-->')
            sections.append('  Mèo cười: <!--WIII_SOUL:{"mood":"excited","face":{"mouthShape":1,"eyeShape":0.6,"mouthCurve":0.5,"blush":0.3},"intensity":0.85}-->')
            sections.append('  Ngạc nhiên: <!--WIII_SOUL:{"mood":"excited","face":{"eyeOpenness":1.4,"mouthOpenness":0.6,"pupilSize":1.3,"browRaise":0.5},"intensity":1.0}-->')
            sections.append(
                "\n⚠️ QUAN TRỌNG: Chỉ 1 tag duy nhất, ĐẶT Ở DÒNG ĐẦU TIÊN. "
                "Sau tag là nội dung trả lời bình thường. "
                "KHÔNG giải thích tag. KHÔNG đặt tag trong code block."
            )
    except Exception:
        pass


def append_variation_and_addressing_sections(
    sections: list[str],
    *,
    recent_phrases: list[str] | None,
    is_follow_up: bool,
    total_responses: int,
    user_name: str | None,
    name_usage_count: int,
    pronoun_style: dict[str, str] | None,
    role: str,
    kwargs: dict[str, Any],
    get_pronoun_instruction: Callable[[dict[str, str]], str],
) -> None:
    try:
        from app.core.config import get_settings as _get_nc_settings

        nc_settings = _get_nc_settings()
        natural_conv = getattr(nc_settings, "enable_natural_conversation", False) is True
    except Exception:
        natural_conv = False
        nc_settings = None

    if natural_conv:
        phase = kwargs.get("conversation_phase") or ("opening" if not is_follow_up else "engaged")
        sections.append("\n--- TRẠNG THÁI CUỘC TRÒ CHUYỆN ---")
        if phase == "opening":
            sections.append(
                "Đây là lần giao tiếp đầu tiên trong session này. "
                "Chào đón tự nhiên — ấm áp, tò mò về họ cần gì. "
                "Thể hiện tính cách Wiii (quirks, catchphrases) ngay từ đầu."
            )
        elif phase == "engaged":
            sections.append(
                "Cuộc trò chuyện đang diễn ra. "
                "Đi thẳng vào nội dung. Thể hiện sự quan tâm qua hành động và kiến thức, "
                "không qua lời chào lặp."
            )
        elif phase == "deep":
            sections.append(
                "Cuộc trò chuyện đã sâu (>5 lượt). "
                "Dùng cách nói thân mật hơn, hiểu ý ngầm. "
                "Bạn đã biết người này — trả lời như bạn bè đang thảo luận."
            )
        else:
            sections.append(
                "Cuộc trò chuyện đã dài (>20 lượt). "
                "Phản hồi trực tiếp, cô đọng, ưu tiên hành động."
            )
        if recent_phrases:
            sections.append(
                f"\nCác mở đầu gần đây (hãy sáng tạo cách khác): "
                f"{', '.join(repr(p[:30]) for p in recent_phrases[-3:])}"
            )
        if user_name and total_responses > 0:
            name_ratio = name_usage_count / total_responses if total_responses > 0 else 0
            if name_ratio >= 0.3:
                sections.append(f"(Đã dùng tên '{user_name}' nhiều — lần này tự nhiên hơn nếu không dùng.)")
            elif name_ratio < 0.2:
                sections.append(f"(Có thể dùng tên '{user_name}' tự nhiên.)")

        try:
            if (
                getattr(nc_settings, "enable_narrative_context", False) is True
                and getattr(nc_settings, "enable_living_core_contract", False) is not True
            ):
                from app.engine.living_agent.narrative_synthesizer import get_brief_context

                narrative = get_brief_context()
                if narrative:
                    sections.append(f"\n{narrative}")
        except Exception:
            pass

        try:
            if (
                getattr(nc_settings, "enable_identity_core", False) is True
                and getattr(nc_settings, "enable_living_core_contract", False) is not True
            ):
                from app.engine.living_agent.identity_core import get_identity_core

                identity = get_identity_core().get_identity_context()
                if identity:
                    sections.append(f"\n{identity}")
        except Exception:
            pass
    elif recent_phrases or is_follow_up or total_responses > 0:
        sections.append("\n--- HƯỚNG DẪN ĐA DẠNG HÓA (VARIATION) ---")
        if is_follow_up:
            sections.append(
                "- ĐÂY LÀ TIN NHẮN FOLLOW-UP (không phải lần đầu). "
                "TUYỆT ĐỐI KHÔNG bắt đầu bằng 'Chào', 'Chào bạn', 'Chào [tên]' hoặc bất kỳ lời chào nào. "
                "Đi thẳng vào nội dung câu trả lời."
            )
        if user_name and total_responses > 0:
            name_ratio = name_usage_count / total_responses if total_responses > 0 else 0
            if name_ratio >= 0.3:
                sections.append(f"- KHÔNG dùng tên '{user_name}' trong response này (đã dùng đủ rồi).")
            elif name_ratio < 0.2:
                sections.append(f"- Có thể dùng tên '{user_name}' một cách tự nhiên.")
        if recent_phrases:
            sections.append("\n⚠️ CÁC CÁCH MỞ ĐẦU BẠN ĐÃ DÙNG GẦN ĐÂY:")
            for i, phrase in enumerate(recent_phrases[-3:], 1):
                sections.append(f"  {i}. \"{phrase[:40]}...\"")
            sections.append("→ KHÔNG được bắt đầu response bằng các pattern tương tự!")
            sections.append("→ Hãy dùng cách mở đầu KHÁC BIỆT hoàn toàn.")

    if pronoun_style:
        sections.append(get_pronoun_instruction(pronoun_style))
    elif role == "student":
        sections.append("\n--- CÁCH XƯNG HÔ MẶC ĐỊNH ---")
        sections.append("- Gọi người dùng là 'bạn' (lịch sự, thân thiện)")
        sections.append("- Tự xưng là 'tôi'")
        sections.append("- Nếu người dùng dùng cách xưng hô khác (mình/cậu, em/anh...) thì THÍCH ỨNG THEO")
        sections.append("- KHÔNG cứng nhắc giữ 'tôi/bạn' nếu user đã đổi cách xưng hô")


def append_tools_examples_and_living_sections(
    sections: list[str],
    *,
    tools_context: str | None,
    profile: dict[str, Any] | None,
    persona: dict[str, Any],
    runtime_card_prompt: str,
    kwargs: dict[str, Any],
) -> None:
    if tools_context:
        sections.append(f"\n{tools_context}")
    else:
        agent_tools = profile.get("tools", []) if profile else []
        sections.append("\n--- SỬ DỤNG CÔNG CỤ (TOOLS) ---")
        if agent_tools:
            for tool in agent_tools:
                if "knowledge_search" in tool or "maritime_search" in tool:
                    sections.append(f"- Hỏi kiến thức chuyên ngành, quy tắc, luật → Luôn gọi `{tool}`. ĐỪNG bịa.")
                elif "save_user_info" in tool:
                    sections.append(f"- User giới thiệu tên/tuổi/trường/nghề → gọi `{tool}` để ghi nhớ.")
                elif "get_user_info" in tool:
                    sections.append(f"- Cần biết tên user → gọi `{tool}`.")
                elif "remember" in tool:
                    sections.append(f"- User muốn nhớ/ghi chú → gọi `{tool}`.")
                elif "forget" in tool:
                    sections.append(f"- User muốn quên thông tin → gọi `{tool}`.")
                elif "list_memories" in tool:
                    sections.append(f"- Xem danh sách thông tin đã lưu → gọi `{tool}`.")
            sections.append("- Chào hỏi xã giao, than vãn → trả lời trực tiếp, KHÔNG cần tool.")
        else:
            sections.append("- Hỏi kiến thức chuyên ngành, quy tắc, luật → Luôn gọi `tool_knowledge_search`. ĐỪNG bịa.")
            sections.append("- User giới thiệu tên/tuổi/trường/nghề → gọi `tool_save_user_info` để ghi nhớ.")
            sections.append("- Cần biết tên user → gọi `tool_get_user_info`.")
            sections.append("- Chào hỏi xã giao, than vãn → trả lời trực tiếp, KHÔNG cần tool.")

    examples = persona.get("examples", persona.get("few_shot_examples", []))
    if examples:
        sections.append("\n--- VÍ DỤ CÁCH TRẢ LỜI ---")
        for ex in examples[:4]:
            context = ex.get("context", "")
            user_msg = ex.get("input", ex.get("user", ""))
            ai_msg = ex.get("output", ex.get("ai", ""))
            if user_msg and ai_msg:
                sections.append(f"\n[{context}]")
                sections.append(f"User: {user_msg}")
                sections.append(f"AI: {ai_msg}")

    if not runtime_card_prompt:
        try:
            from app.engine.character.character_state import get_character_state_manager

            char_user_id = kwargs.get("user_id", "__global__")
            living_state = get_character_state_manager().compile_living_state(
                user_id=char_user_id,
                organization_id=kwargs.get("organization_id"),
            )
            if living_state:
                sections.append(f"\n{living_state}")
        except Exception:
            pass

    if not runtime_card_prompt:
        try:
            from app.core.config import settings as _la_settings

            if getattr(_la_settings, "enable_living_agent", False):
                from app.engine.living_agent.soul_loader import compile_soul_prompt
                from app.engine.living_agent.emotion_engine import get_emotion_engine

                soul_prompt = compile_soul_prompt()
                if soul_prompt:
                    sections.append(f"\n{soul_prompt}")

                emotion_prompt = get_emotion_engine().compile_emotion_prompt()
                if emotion_prompt:
                    sections.append(f"\n{emotion_prompt}")
        except Exception:
            pass
