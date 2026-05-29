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
