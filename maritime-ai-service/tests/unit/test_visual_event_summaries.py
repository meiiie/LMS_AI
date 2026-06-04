from app.engine.multi_agent.visual_events import _summarize_tool_result_for_stream
from app.engine.multi_agent.direct_tool_sources import (
    extract_source_infos_from_tool_result,
)


def test_weather_tool_result_summary_keeps_unconfigured_status():
    result = _summarize_tool_result_for_stream(
        "current_weather",
        "Mình hiện chưa có kết nối thời tiết trực tiếp cho Hải Phòng, nên không nên đoán nhiệt độ.",
    )

    assert result == "Chưa có kết nối thời tiết trực tiếp."


def test_weather_tool_result_summary_requests_location_when_missing():
    result = _summarize_tool_result_for_stream(
        "tool_current_weather",
        "Bạn muốn xem nhiệt độ ở thành phố nào?",
    )

    assert result == "Cần thêm địa điểm để tra thời tiết."


def test_web_search_result_summary_uses_structured_source_count():
    result = _summarize_tool_result_for_stream(
        "tool_web_search",
        "\n\n---\n\n".join(
            [
                "**Weather Hải Phòng today**\nCloudy and warm.\nURL: https://weather.example/hai-phong",
                "**Local forecast**\nRain chance later.\nURL: https://meteo.example/forecast",
            ]
        ),
    )

    assert result == "Tìm được 2 nguồn: weather.example, meteo.example"


def test_extract_source_infos_from_web_search_markdown():
    sources = extract_source_infos_from_tool_result(
        "tool_web_search",
        "**Weather Hải Phòng today**\nCloudy and warm.\nURL: https://weather.example/hai-phong",
    )

    assert sources == [
        {
            "title": "Weather Hải Phòng today",
            "content": "Cloudy and warm.",
            "url": "https://weather.example/hai-phong",
            "source_type": "web",
        }
    ]
