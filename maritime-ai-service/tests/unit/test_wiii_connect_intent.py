def test_facebook_post_intent_detects_natural_chat_phrasing():
    from app.engine.multi_agent.wiii_connect_intent import (
        looks_wiii_connect_facebook_post_request,
    )

    assert looks_wiii_connect_facebook_post_request(
        "Wiii đăng một bài Facebook, bài nào cũng được"
    )
    assert looks_wiii_connect_facebook_post_request(
        "Wiii tao cho toi bai viet tren facebook, bai nao cung duoc"
    )
    assert looks_wiii_connect_facebook_post_request(
        "ảnh thì là ảnh này đi còn nội dung thì là nội dung test bạn tự đăng đi, đăng lên trang cá nhân thử xem"
    )
    assert not looks_wiii_connect_facebook_post_request("đăng bài chưa ?")


def test_external_app_action_intent_detects_registered_provider_action():
    from app.engine.multi_agent.wiii_connect_intent import (
        looks_wiii_connect_external_app_action_request,
        resolve_wiii_connect_status_provider_slugs,
        resolve_wiii_connect_target_provider_slugs,
    )

    assert looks_wiii_connect_external_app_action_request(
        "Wiii \u0111\u1ecdc Gmail t\u1eeb gi\u00e1o vi\u00ean gi\u00fap t\u00f4i"
    )
    assert resolve_wiii_connect_target_provider_slugs(
        "Wiii doc Gmail tu giao vien giup toi"
    ) == ("gmail",)
    assert looks_wiii_connect_external_app_action_request(
        "t\u1ea1o issue GitHub cho l\u1ed7i \u0111\u0103ng nh\u1eadp"
    )
    assert resolve_wiii_connect_target_provider_slugs(
        "tao issue GitHub cho loi dang nhap"
    ) == ("github",)
    assert set(
        resolve_wiii_connect_target_provider_slugs(
            "doc Gmail roi tao issue GitHub giup toi"
        )
    ) == {"gmail", "github"}
    assert resolve_wiii_connect_status_provider_slugs(
        "Gmail đã kết nối chưa?"
    ) == ("gmail",)
    assert not looks_wiii_connect_external_app_action_request(
        "Gmail đã kết nối chưa?"
    )
    assert not looks_wiii_connect_external_app_action_request(
        "Wiii c\u00f3 k\u1ebft n\u1ed1i \u0111\u01b0\u1ee3c Facebook kh\u00f4ng?"
    )
    assert looks_wiii_connect_external_app_action_request(
        "dang bai len mang xa hoi di"
    )
    assert looks_wiii_connect_external_app_action_request(
        "gui len ung dung nao do di"
    )
    assert not looks_wiii_connect_external_app_action_request(
        "viet mot bai ve ngay moi"
    )
    assert not looks_wiii_connect_external_app_action_request("ch\u00e0o Wiii")
    assert not looks_wiii_connect_external_app_action_request(
        "Tao mot mini app Code Studio mo phong COLREG Rule 15 co slider va canvas tuong tac."
    )


def test_providerless_external_action_detects_missing_provider_without_guessing():
    from app.engine.multi_agent.wiii_connect_intent import (
        looks_wiii_connect_external_app_action_request,
        looks_wiii_connect_external_app_action_request_for_state,
        resolve_wiii_connect_target_provider_slugs_for_state,
    )

    query = "dang bai len mang xa hoi di"
    state = {"messages": []}

    assert looks_wiii_connect_external_app_action_request_for_state(query, state)
    assert resolve_wiii_connect_target_provider_slugs_for_state(query, state) == ()
    visual_query = (
        "Tao mot mini app Code Studio mo phong COLREG Rule 15 "
        "co slider va canvas tuong tac."
    )
    assert not looks_wiii_connect_external_app_action_request(visual_query)
    assert not looks_wiii_connect_external_app_action_request_for_state(
        visual_query,
        {"messages": []},
    )


def test_provider_capability_question_routes_to_status_not_action():
    from app.engine.multi_agent.wiii_connect_intent import (
        looks_wiii_connect_external_app_action_request,
        looks_wiii_connect_facebook_post_request,
        resolve_wiii_connect_status_provider_slugs,
    )

    query = "Wiii co the dang bai len Facebook khong?"

    assert resolve_wiii_connect_status_provider_slugs(query) == ("facebook",)
    assert not looks_wiii_connect_facebook_post_request(query)
    assert not looks_wiii_connect_external_app_action_request(query)


def test_providerless_action_continuation_inherits_single_wiii_connect_provider():
    from app.engine.multi_agent.wiii_connect_intent import (
        looks_wiii_connect_external_app_action_request_for_state,
        looks_wiii_connect_facebook_post_request_for_state,
        resolve_wiii_connect_target_provider_slugs_for_state,
    )

    state = {
        "messages": [
            {
                "role": "user",
                "content": "Wiii co the dang bai len Facebook khong?",
            },
            {
                "role": "assistant",
                "content": (
                    "Facebook chua agent-ready trong Wiii Connect; "
                    "can policy/gateway truoc khi publish."
                ),
            },
        ]
    }
    query = 'dang bai: "xin chao minh la AI" la duoc'

    assert resolve_wiii_connect_target_provider_slugs_for_state(query, state) == (
        "facebook",
    )
    assert looks_wiii_connect_facebook_post_request_for_state(query, state)
    assert looks_wiii_connect_external_app_action_request_for_state(query, state)


def test_providerless_generic_action_continuation_inherits_single_provider():
    from app.engine.multi_agent.wiii_connect_intent import (
        looks_wiii_connect_external_app_action_request_for_state,
        resolve_wiii_connect_target_provider_slugs_for_state,
    )

    state = {
        "messages": [
            {
                "role": "user",
                "content": "Wiii co the doc Gmail khong?",
            },
            {
                "role": "assistant",
                "content": "Gmail chua agent-ready trong Wiii Connect.",
            },
        ]
    }
    query = "doc email moi nhat di"

    assert resolve_wiii_connect_target_provider_slugs_for_state(query, state) == (
        "gmail",
    )
    assert looks_wiii_connect_external_app_action_request_for_state(query, state)


def test_providerless_action_continuation_does_not_guess_without_context():
    from app.engine.multi_agent.wiii_connect_intent import (
        looks_wiii_connect_external_app_action_request_for_state,
        resolve_wiii_connect_target_provider_slugs_for_state,
    )

    query = 'dang bai: "xin chao minh la AI" la duoc'

    assert resolve_wiii_connect_target_provider_slugs_for_state(
        query,
        {"messages": [{"role": "user", "content": "chao Wiii"}]},
    ) == ()
    assert not looks_wiii_connect_external_app_action_request_for_state(
        query,
        {"messages": []},
    )


def test_facebook_post_unavailable_answer_uses_backend_snapshot_without_host_snapshot(
    monkeypatch,
):
    from app.engine.multi_agent import wiii_connect_intent as module

    class FakeSnapshot:
        def provider_status(self, provider_slug):
            assert provider_slug == "facebook"
            return {
                "status": "disabled",
                "agent_ready": False,
                "reason": "provider_adapter_disabled",
                "connection_count": 0,
                "active_connection_count": 0,
            }

    monkeypatch.setattr(
        module,
        "build_wiii_connect_snapshot",
        lambda **_kwargs: FakeSnapshot(),
    )

    answer = module.build_wiii_connect_facebook_post_unavailable_answer(
        {"context": {}}
    )

    assert answer is not None
    assert "provider_adapter_disabled" in answer


def test_facebook_status_answer_reports_pending_connection():
    from app.engine.multi_agent.wiii_connect_intent import (
        build_wiii_connect_facebook_status_answer,
    )

    answer = build_wiii_connect_facebook_status_answer(
        {
            "context": {
                "host_context": {
                    "page": {
                        "metadata": {
                            "wiii_connect": {
                                "provider_slug": "facebook",
                                "status": "not_connected",
                                "connection_count": 1,
                                "active_connection_count": 0,
                                "connection_state": "waiting",
                            }
                        }
                    }
                }
            }
        }
    )

    assert "provider chưa ở trạng thái active" in answer
    assert "waiting" in answer


def test_provider_status_answer_reports_connected_but_not_agent_ready(monkeypatch):
    from app.engine.multi_agent import wiii_connect_intent as module

    class FakeSnapshot:
        def provider_status(self, provider_slug):
            assert provider_slug == "gmail"
            return {
                "status": "connected",
                "agent_ready": False,
                "reason": "connected_provider_not_agent_ready",
                "connection_count": 1,
                "active_connection_count": 1,
                "connection_state": "connected",
            }

    monkeypatch.setattr(
        module,
        "build_wiii_connect_snapshot",
        lambda **_kwargs: FakeSnapshot(),
    )

    answer = module.build_wiii_connect_provider_status_answer(
        {"context": {}},
        provider_slug="gmail",
    )

    assert "Gmail" in answer
    assert "connected chưa đồng nghĩa agent-ready" in answer
    assert "connected_provider_not_agent_ready" in answer


def test_provider_status_answer_prefers_backend_connection_lifecycle(monkeypatch):
    from app.engine.multi_agent import wiii_connect_intent as module

    class FakeSnapshot:
        def provider_status(self, provider_slug):
            assert provider_slug == "gmail"
            return {
                "status": "not_connected",
                "agent_ready": False,
                "reason": "legacy_status",
                "connection_count": 0,
                "active_connection_count": 0,
                "connection_state": "waiting",
                "connection_lifecycle": {
                    "version": "wiii_connect_connection_lifecycle.v1",
                    "provider_slug": "gmail",
                    "status": "expired",
                    "reason": "oauth_token_expired",
                    "active": False,
                    "connection_present": True,
                    "agent_ready": False,
                    "ready_to_connect": True,
                    "ready_to_execute_action": False,
                    "required_next": ["reconnect_provider_account"],
                    "connection_ref": "wcn_must_not_render",
                    "access_token": "secret",
                },
            }

    monkeypatch.setattr(
        module,
        "build_wiii_connect_snapshot",
        lambda **_kwargs: FakeSnapshot(),
    )

    answer = module.build_wiii_connect_provider_status_answer(
        {"context": {}},
        provider_slug="gmail",
    )

    assert "Gmail" in answer
    assert "oauth_token_expired" in answer
    assert "wcn_must_not_render" not in answer
    assert "secret" not in answer


def test_facebook_post_unavailable_answer_blocks_pending_connection():
    from app.engine.multi_agent.wiii_connect_intent import (
        build_wiii_connect_facebook_post_unavailable_answer,
    )

    answer = build_wiii_connect_facebook_post_unavailable_answer(
        {
            "context": {
                "host_context": {
                    "page": {
                        "metadata": {
                            "wiii_connect": {
                                "provider_slug": "facebook",
                                "status": "not_connected",
                                "connection_count": 1,
                                "active_connection_count": 0,
                                "connection_state": "waiting",
                            }
                        }
                    }
                }
            }
        }
    )

    assert answer is not None
    assert "chưa có account Facebook active" in answer


def test_facebook_post_unavailable_answer_reports_connected_not_agent_ready(
    monkeypatch,
):
    from app.engine.multi_agent import wiii_connect_intent as module

    class FakeSnapshot:
        def provider_status(self, provider_slug):
            assert provider_slug == "facebook"
            return {
                "status": "connected",
                "agent_ready": False,
                "reason": "provider_adapter_not_bound",
                "connection_count": 4,
                "active_connection_count": 3,
                "connection_state": "connected",
            }

    monkeypatch.setattr(
        module,
        "build_wiii_connect_snapshot",
        lambda **_kwargs: FakeSnapshot(),
    )

    answer = module.build_wiii_connect_facebook_post_unavailable_answer(
        {"context": {}}
    )

    assert answer is not None
    assert "connected chưa đồng nghĩa agent-ready" in answer
    assert "provider_adapter_not_bound" in answer
    assert "chưa có account Facebook active" not in answer
