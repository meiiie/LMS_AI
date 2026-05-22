from app.engine.multi_agent.direct_node_final_state import finalize_direct_node_state


def test_finalize_direct_node_state_records_final_thinking_snapshot():
    state = {
        "thinking": "Minh da co ket luan cuoi.",
        "routing_metadata": {"intent": "social"},
    }
    snapshots = []

    result = finalize_direct_node_state(
        state=state,
        response="Cau tra loi cuoi.",
        domain_name_vi="Hang hai",
        resolve_public_thinking_content=lambda *_args, **_kwargs: (
            "Minh da co ket luan cuoi."
        ),
        record_thinking_snapshot_fn=lambda *args, **kwargs: snapshots.append(
            (args, kwargs)
        ),
        enable_org_knowledge=False,
        get_current_org_id_fn=lambda: None,
    )

    assert result is state
    assert state["thinking_content"] == "Minh da co ket luan cuoi."
    assert state["final_response"] == "Cau tra loi cuoi."
    assert state["agent_outputs"] == {"direct": "Cau tra loi cuoi."}
    assert state["current_agent"] == "direct"
    assert snapshots[0][1]["node"] == "direct"
    assert snapshots[0][1]["provenance"] == "final_snapshot"


def test_finalize_direct_node_state_marks_aligned_cleanup_when_thinking_differs():
    state = {"thinking": "raw", "routing_metadata": {"intent": "social"}}
    snapshots = []

    finalize_direct_node_state(
        state=state,
        response="answer",
        domain_name_vi="Hang hai",
        resolve_public_thinking_content=lambda *_args, **_kwargs: "clean",
        record_thinking_snapshot_fn=lambda *args, **kwargs: snapshots.append(
            (args, kwargs)
        ),
        enable_org_knowledge=False,
        get_current_org_id_fn=lambda: None,
    )

    assert snapshots[0][1]["provenance"] == "aligned_cleanup"


def test_finalize_direct_node_state_adds_general_domain_notice_without_org_context():
    state = {"routing_metadata": {"intent": "general"}}

    finalize_direct_node_state(
        state=state,
        response="answer",
        domain_name_vi="Hang hai",
        resolve_public_thinking_content=lambda *_args, **_kwargs: "",
        record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
        enable_org_knowledge=False,
        get_current_org_id_fn=lambda: None,
    )

    assert "Hang hai" in state["domain_notice"]
    assert "hoi ve Hang hai" in state["domain_notice"]


def test_finalize_direct_node_state_suppresses_domain_notice_with_org_knowledge():
    state = {"routing_metadata": {"intent": "general"}}

    finalize_direct_node_state(
        state=state,
        response="answer",
        domain_name_vi="Hang hai",
        resolve_public_thinking_content=lambda *_args, **_kwargs: "",
        record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
        enable_org_knowledge=True,
        get_current_org_id_fn=lambda: "org-1",
    )

    assert "domain_notice" not in state
