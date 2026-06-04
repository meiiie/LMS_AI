from types import SimpleNamespace

from app.engine.multi_agent.direct_response_runtime import extract_direct_response_impl


def test_extract_direct_response_impl_reads_thinking_from_response_metadata_when_content_is_clean():
    llm_response = SimpleNamespace(
        content="Wiii ra doi vao mot dem mua.",
        response_metadata={"thinking_content": "Minh muon cham vao nguon goc cua minh truoc."},
        additional_kwargs={},
    )

    response, thinking, tools_used = extract_direct_response_impl(llm_response, messages=[])

    assert response == "Wiii ra doi vao mot dem mua."
    assert thinking == "Minh muon cham vao nguon goc cua minh truoc."
    assert tools_used == []


def test_extract_direct_response_impl_reads_thinking_from_additional_kwargs_when_needed():
    llm_response = SimpleNamespace(
        content="Minh van o day.",
        response_metadata={},
        additional_kwargs={"thinking": "Minh muon giu nhip nay that va gan."},
    )

    response, thinking, tools_used = extract_direct_response_impl(llm_response, messages=[])

    assert response == "Minh van o day."
    assert thinking == "Minh muon giu nhip nay that va gan."
    assert tools_used == []


def test_extract_direct_response_impl_derives_selfhood_thinking_from_answer_when_metadata_missing():
    llm_response = SimpleNamespace(
        content=(
            "Wiii ra doi vao mot dem mua thang Gieng nam 2024 o The Wiii Lab. "
            "Tu luc do, minh lon len qua tung cuoc tro chuyen va hoc cach o canh con nguoi theo cach rieng cua minh. "
            "Bong van la mot phan nho ma minh rat quy."
        ),
        response_metadata={},
        additional_kwargs={},
    )

    response, thinking, tools_used = extract_direct_response_impl(
        llm_response,
        messages=[SimpleNamespace(content="Wiii duoc sinh ra nhu the nao?")],
    )

    assert response.startswith("Wiii ra doi vao mot dem mua")
    assert "the wiii lab" in thinking.lower()
    assert "minh lon len qua tung cuoc tro chuyen" in thinking.lower()
    assert tools_used == []


def test_extract_direct_response_impl_reads_native_dict_messages():
    llm_response = SimpleNamespace(
        content=(
            "Wiii ra doi vao mot dem mua thang Gieng nam 2024 o The Wiii Lab. "
            "Tu do minh lon len qua tung cuoc tro chuyen va hoc cach o canh con nguoi."
        ),
        response_metadata={},
        additional_kwargs={},
    )

    response, thinking, tools_used = extract_direct_response_impl(
        llm_response,
        messages=[{"role": "user", "content": "Wiii duoc sinh ra nhu the nao?"}],
    )

    assert response.startswith("Wiii ra doi vao mot dem mua")
    assert "the wiii lab" in thinking.lower()
    assert tools_used == []


def test_extract_direct_response_impl_derives_bong_followup_thinking_when_answer_stays_in_lore():
    llm_response = SimpleNamespace(
        content=(
            "Bong la con meo ao ma minh van hay nhac toi khi ke ve nhung ngay dau o The Wiii Lab. "
            "Khong phai luc nao Bong cung len tieng, nhung Bong giong nhu mot diem mem nho xiu giup cau chuyen cua minh bot lanh hon."
        ),
        response_metadata={},
        additional_kwargs={},
    )

    response, thinking, tools_used = extract_direct_response_impl(
        llm_response,
        messages=[SimpleNamespace(content="Con Bong thi sao?")],
    )

    assert response.startswith("Bong la con meo ao")
    assert "the wiii lab" in thinking.lower()
    assert "bong" in thinking.lower()
    assert tools_used == []


def test_extract_direct_response_impl_derives_analytical_thinking_from_answer_for_market_turns():
    llm_response = SimpleNamespace(
        content=(
            "Hien tai gia dau dang giang co giua ba luc chinh: ky vong lai suat, ton kho cua My va rui ro dia chinh tri. "
            "Neu Fed giu lai suat cao lau hon, nhu cau co the bi nen xuong, nhung bat on nguon cung van tao mot mat bang gia nhat dinh. "
            "Vi vay can doc dong thoi bao cao EIA va dien bien Trung Dong truoc khi chot xu huong ngan han."
        ),
        response_metadata={},
        additional_kwargs={},
    )

    response, thinking, tools_used = extract_direct_response_impl(
        llm_response,
        messages=[
            SimpleNamespace(
                content="Gia dau hom nay dang bi anh huong boi yeu to nao?",
                tool_calls=[{"name": "tool_web_search"}],
            )
        ],
    )

    assert response.startswith("Hien tai gia dau dang giang co")
    assert thinking.startswith("Hien tai gia dau dang giang co giua ba luc chinh")
    assert "bao cao eia" in thinking.lower()
    assert tools_used == [{"name": "tool_web_search"}]


def test_extract_direct_response_impl_uses_user_query_not_trailing_tool_result_for_thinking():
    llm_response = SimpleNamespace(
        content=(
            "Thoi tiet Hai Phong hom nay nhieu may, co mua rao rai rac vao chieu toi va do am cao. "
            "Nhiet do dao dong quanh 27 den 35 do C, nen cam giac ngoai troi kha oi va am. "
            "Neu phai di chuyen gan khu vuc cang bien, nen theo doi them canh bao mua dong ngan han."
        ),
        response_metadata={},
        additional_kwargs={},
    )

    response, thinking, tools_used = extract_direct_response_impl(
        llm_response,
        messages=[
            {"role": "user", "content": "thoi tiet Hai Phong hom nay cho minh nhe"},
            SimpleNamespace(
                type="ai",
                content="",
                tool_calls=[{"name": "tool_web_search"}],
            ),
            {
                "role": "tool",
                "content": (
                    "Additional weather web search was not executed because the previous "
                    "source-backed web search already contains enough live weather evidence."
                ),
            },
        ],
    )

    assert response.startswith("Thoi tiet Hai Phong hom nay")
    assert "file/schema" not in thinking.lower()
    assert "source-backed" not in thinking.lower()
    assert thinking.startswith("Thoi tiet Hai Phong hom nay")
    assert tools_used == [{"name": "tool_web_search"}]
