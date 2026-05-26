def test_current_weather_tool_fails_closed_when_provider_unconfigured(monkeypatch):
    from app.core.config import settings
    from app.engine.tools.utility_tools import tool_current_weather

    monkeypatch.setattr(settings, "living_agent_enable_weather", False)
    monkeypatch.setattr(settings, "living_agent_weather_api_key", None)
    monkeypatch.setattr(settings, "living_agent_weather_city", "Ho Chi Minh City")

    result = tool_current_weather.invoke({"city": ""})

    assert "chưa có kết nối thời tiết trực tiếp" in result
    assert "Ho Chi Minh City" in result


def test_current_weather_tool_ignores_full_question_as_city(monkeypatch):
    from app.core.config import settings
    from app.engine.tools.utility_tools import tool_current_weather

    monkeypatch.setattr(settings, "living_agent_enable_weather", False)
    monkeypatch.setattr(settings, "living_agent_weather_api_key", None)
    monkeypatch.setattr(settings, "living_agent_weather_city", "Ho Chi Minh City")

    result = tool_current_weather.invoke(
        {"city": "ý là thời tiết nóng đó. Bạn biết nay bao độ không?"}
    )

    assert "Ho Chi Minh City" in result
    assert "ý là" not in result.lower()
