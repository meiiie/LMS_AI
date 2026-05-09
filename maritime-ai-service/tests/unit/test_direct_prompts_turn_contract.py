from unittest.mock import MagicMock, patch


def _loader():
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
    return loader


def test_direct_prompt_adds_turn_contract_to_keep_current_instruction_authoritative():
    from app.engine.multi_agent.direct_prompts import _build_direct_system_messages

    state = {
        "context": {
            "response_language": "vi",
            "langchain_messages": [
                {"role": "user", "content": "@web-search hay tim tin moi"},
                {"role": "assistant", "content": "Da tim."},
            ],
        },
        "user_id": "user-1",
    }

    with patch("app.prompts.prompt_loader.get_prompt_loader", return_value=_loader()):
        messages = _build_direct_system_messages(
            state,
            "doi phet",
            "Maritime",
            tools_context_override="",
        )

    system_prompt = messages[0]["content"]
    assert "## WIII DIRECT TURN CONTRACT" in system_prompt
    assert "Current turn wins" in system_prompt
    assert "Never carry a previous turn's tool route" in system_prompt
    assert messages[-1] == {"role": "user", "content": "doi phet"}


def test_direct_prompt_turn_contract_documents_pointy_auto_ids_and_route_choice():
    from app.engine.multi_agent.direct_prompts import _build_direct_system_messages

    state = {
        "context": {
            "response_language": "vi",
            "force_skills": ["wiii-pointy"],
            "host_context": {
                "page": {
                    "metadata": {
                        "available_targets": [
                            {
                                "id": "auto:button:gui-tin-nhan",
                                "role": "button",
                                "label": "Gui tin nhan",
                            }
                        ]
                    }
                }
            },
        },
        "user_id": "user-1",
    }

    with patch("app.prompts.prompt_loader.get_prompt_loader", return_value=_loader()):
        messages = _build_direct_system_messages(
            state,
            "@wiii-pointy nut gui o dau",
            "Maritime",
            tools_context_override="",
        )

    system_prompt = messages[0]["content"]
    assert "Force-bound skills for THIS turn: wiii-pointy" in system_prompt
    assert "synthetic `auto:...` ids are valid" in system_prompt
    assert "call `tool_pointy_show` instead" in system_prompt
    assert "auto:button:gui-tin-nhan" in system_prompt
