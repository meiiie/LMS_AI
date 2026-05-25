from pathlib import Path


CODE_STUDIO_TOOL_ROUNDS = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "engine"
    / "multi_agent"
    / "code_studio_tool_rounds.py"
).read_text(encoding="utf-8")


def test_code_studio_tool_round_copy_uses_accented_vietnamese() -> None:
    old_accentless_phrases = [
        "Mo cong cu can thiet roi xac minh output co the dung that.",
        "Sap goi",
        "Rut gon thanh mot buoc thuc hien tiep theo roi moi chot.",
        "Da co them ket qua moi va dang can khau lai.",
        "Noi ro da tao xong san pham nao",
    ]
    expected_accented_phrases = [
        "Mở công cụ cần thiết rồi xác minh đầu ra có thể dùng thật.",
        "Sắp gọi",
        "Rút gọn thành một bước thực hiện tiếp theo rồi mới chốt.",
        "Đã có thêm kết quả mới và đang cần khâu lại.",
        "Nói rõ đã tạo xong sản phẩm nào",
    ]

    for phrase in old_accentless_phrases:
        assert phrase not in CODE_STUDIO_TOOL_ROUNDS

    for phrase in expected_accented_phrases:
        assert phrase in CODE_STUDIO_TOOL_ROUNDS
