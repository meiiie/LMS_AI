from app.services.input_processor_context_runtime import _infer_force_skills_from_message


def test_infer_force_skills_from_raw_mentions():
    assert _infer_force_skills_from_message(
        "@wiii-pointy chi vao nut gui va @web-search neu can"
    ) == ["wiii-pointy", "web-search"]


def test_infer_force_skills_supports_aliases_and_dedupes():
    assert _infer_force_skills_from_message(
        "@pointy @cursor @studio tao widget"
    ) == ["wiii-pointy", "visual-code-gen"]


def test_infer_force_skills_ignores_unknown_mentions():
    assert _infer_force_skills_from_message("@unknown noi chuyen binh thuong") == []
