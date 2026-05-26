from unittest.mock import MagicMock, patch


def test_direct_system_messages_can_return_native_openai_messages():
    from app.engine.multi_agent.direct_prompts import _build_direct_system_messages

    state = {
        "context": {},
        "user_id": "user-1",
    }

    loader = MagicMock()
    loader.build_system_prompt.return_value = "BASE SYSTEM PROMPT"
    loader.get_thinking_instruction.return_value = ""
    loader.get_persona.return_value = {
        "agent": {
            "name": "Wiii",
            "goal": "Tra loi co chat",
            "backstory": "Vai tro: tro ly hoi thoai da linh vuc.",
        }
    }

    with patch("app.prompts.prompt_loader.get_prompt_loader", return_value=loader):
        messages = _build_direct_system_messages(
            state,
            "Hi Wiii",
            "Maritime",
            tools_context_override="",
            native_messages=True,
        )

    assert messages[0]["role"] == "system"
    assert "BASE SYSTEM PROMPT" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "Hi Wiii"}


def test_direct_system_messages_add_identity_answer_contract():
    from app.engine.multi_agent.direct_prompts import _build_direct_system_messages

    state = {
        "context": {},
        "user_id": "user-1",
    }

    loader = MagicMock()
    loader.build_system_prompt.return_value = "BASE SYSTEM PROMPT"
    loader.get_thinking_instruction.return_value = ""
    loader.get_persona.return_value = {
        "agent": {
            "name": "Wiii",
            "goal": "Tra loi co chat",
            "backstory": "Vai tro: tro ly hoi thoai da linh vuc.",
        }
    }

    with patch("app.prompts.prompt_loader.get_prompt_loader", return_value=loader):
        messages = _build_direct_system_messages(
            state,
            "Wiii la ai?",
            "Maritime",
            tools_context_override="",
        )

    system_prompt = messages[0]["content"].lower()

    assert "uu tien mot visible thinking that truoc answer" in system_prompt
    assert "neu provider khong tach native thought rieng" in system_prompt
    assert "day la mot cau hoi dang cham vao chinh wiii" in system_prompt or "câu hỏi đang chạm vào chính wiii" in system_prompt
    assert "--- nhip nhan dien ban than ---" in system_prompt
    assert "wiii la ai ngay bay gio" in system_prompt
    assert "wiii dang o canh nguoi dung" in system_prompt
    assert "giu cau tra loi o hien tai" in system_prompt
    assert "khong mac dinh ke lai origin story" in system_prompt
    assert "khong mac dinh bung bullet list" in system_prompt
    assert "chi nhac ve bong" in system_prompt
    assert "--- visible thinking ---" in system_prompt
    assert "native thinking" in system_prompt
    assert "<thinking>...</thinking>" in system_prompt


def test_direct_chatter_messages_also_get_visible_thinking_supplement():
    from app.engine.multi_agent.direct_prompts import _build_direct_system_messages

    state = {
        "context": {"response_language": "vi"},
        "user_id": "user-1",
    }

    loader = MagicMock()
    loader.build_system_prompt.return_value = "BASE SYSTEM PROMPT"
    loader.get_thinking_instruction.return_value = ""
    loader.get_persona.return_value = {
        "agent": {
            "name": "Wiii",
            "goal": "Tra loi co chat",
            "backstory": "Vai tro: tro ly hoi thoai da linh vuc.",
        }
    }

    with patch("app.prompts.prompt_loader.get_prompt_loader", return_value=loader):
        messages = _build_direct_system_messages(
            state,
            "minh buon qua",
            "Maritime",
            role_name="direct_chatter_agent",
            tools_context_override="",
        )

    system_prompt = messages[0]["content"].lower()

    assert "--- visible thinking ---" in system_prompt
    assert "native thinking" in system_prompt
    assert "<thinking>...</thinking>" in system_prompt
    assert "colregs" in system_prompt
    assert "sao lại z" in system_prompt
    assert "không bịa cảm giác" in system_prompt
    assert "cửa sổ" in system_prompt


def test_direct_chatter_identity_still_receives_living_context_prompt():
    from app.engine.multi_agent.direct_prompts import _build_direct_system_messages

    state = {
        "context": {"response_language": "vi"},
        "user_id": "user-1",
        "living_context_prompt": "## Living Context Block V1\n- name: Wiii\n- companion: Bong",
    }

    loader = MagicMock()
    loader.build_system_prompt.return_value = "BASE SYSTEM PROMPT"
    loader.get_thinking_instruction.return_value = ""
    loader.get_persona.return_value = {
        "agent": {
            "name": "Wiii",
            "goal": "Tra loi co chat",
            "backstory": "Vai tro: tro ly hoi thoai da linh vuc.",
        }
    }

    with patch("app.prompts.prompt_loader.get_prompt_loader", return_value=loader):
        messages = _build_direct_system_messages(
            state,
            "Wiii duoc sinh ra nhu the nao?",
            "Maritime",
            role_name="direct_chatter_agent",
            tools_context_override="",
        )

    system_prompt = messages[0]["content"]

    assert "## Living Context Block V1" in system_prompt
    assert "Bong" in system_prompt


def test_direct_selfhood_turn_still_gets_shared_thinking_instruction():
    from app.engine.multi_agent.direct_prompts import _build_direct_system_messages

    state = {
        "context": {"response_language": "vi"},
        "user_id": "user-1",
    }

    loader = MagicMock()
    loader.build_system_prompt.return_value = "BASE SYSTEM PROMPT"
    loader.get_thinking_instruction.return_value = "SHARED THINKING INSTRUCTION"
    loader.get_persona.return_value = {
        "agent": {
            "name": "Wiii",
            "goal": "Tra loi co chat",
            "backstory": "Vai tro: tro ly hoi thoai da linh vuc.",
        }
    }

    with patch("app.prompts.prompt_loader.get_prompt_loader", return_value=loader):
        messages = _build_direct_system_messages(
            state,
            "Wiii duoc sinh ra nhu the nao?",
            "Maritime",
            role_name="direct_chatter_agent",
            tools_context_override="",
        )

    system_prompt = messages[0]["content"]

    assert "SHARED THINKING INSTRUCTION" in system_prompt


def test_direct_bong_followup_uses_selfhood_prompt_when_recent_context_is_origin():
    from app.engine.multi_agent.direct_prompts import _build_direct_system_messages

    state = {
        "context": {
            "response_language": "vi",
            "conversation_summary": (
                "Nguoi dung vua hoi Wiii duoc sinh ra nhu the nao, va Wiii da nhac The Wiii Lab cung Bong."
            ),
        },
        "routing_metadata": {"intent": "selfhood"},
        "_routing_hint": {"kind": "selfhood_followup", "intent": "selfhood", "shape": "lore_followup"},
        "user_id": "user-1",
        "living_context_prompt": "## Living Context Block V1\n- name: Wiii\n- companion: Bong",
    }

    loader = MagicMock()
    loader.build_system_prompt.return_value = "BASE SYSTEM PROMPT"
    loader.get_thinking_instruction.return_value = "SHARED THINKING INSTRUCTION"
    loader.get_persona.return_value = {
        "agent": {
            "name": "Wiii",
            "goal": "Tra loi co chat",
            "backstory": "Vai tro: tro ly hoi thoai da linh vuc.",
        }
    }

    with patch("app.prompts.prompt_loader.get_prompt_loader", return_value=loader):
        messages = _build_direct_system_messages(
            state,
            "còn Bông thì sao?",
            "Maritime",
            role_name="direct_chatter_agent",
            tools_context_override="",
        )

    system_prompt = messages[0]["content"].lower()

    assert "selfhood/origin turn" in system_prompt
    assert "lượt hỏi nối tiếp về bông" in system_prompt
    assert "bông là con mèo ảo" in system_prompt
    assert "không được biến bông thành người tạo ra wiii" in system_prompt
    assert "creator" in system_prompt
    assert "con người bí ẩn" in system_prompt
    assert "living context block v1" in system_prompt
    assert "shared thinking instruction" in system_prompt
