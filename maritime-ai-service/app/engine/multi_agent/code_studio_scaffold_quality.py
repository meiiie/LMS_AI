"""Quality gates for deterministic Code Studio scaffold fallbacks."""

from __future__ import annotations

import unicodedata
from typing import Any

from app.engine.multi_agent.code_studio_scaffold_contract import (
    PRIMITIVE_DATA_BAND,
    PRIMITIVE_SCENE,
)


_EXPLICIT_SIMULATION_MARKERS = (
    "canvas",
    "mo phong",
    "simulation",
    "simulate",
    "tao mo phong",
    "truc quan hoa",
    "visualization",
    "visualize",
)


def _fold_scaffold_quality_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(stripped.lower().replace("đ", "d").split())


def looks_explicit_scaffold_simulation_request(query: str) -> bool:
    """Return True when the user explicitly asks for a visual simulation."""
    folded = _fold_scaffold_quality_text(query)
    return bool(folded and any(marker in folded for marker in _EXPLICIT_SIMULATION_MARKERS))


def apply_scaffold_quality_gate(query: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Upgrade generic fallbacks when the user explicitly asked for simulation."""
    if spec.get("primitive") != PRIMITIVE_DATA_BAND:
        return spec
    if not looks_explicit_scaffold_simulation_request(query):
        return spec

    upgraded = dict(spec)
    upgraded.update(
        {
            "primitive": PRIMITIVE_SCENE,
            "slider_label": "Nhịp cảnh",
            "scene_figure": "character",
            "moments": [
                {
                    "key": "Khởi tạo",
                    "quote": "Bắt đầu dựng cảnh tương tác.",
                    "sky_blend": 0.0,
                },
                {
                    "key": "Biến chuyển",
                    "quote": "Kéo thanh trượt để thấy trạng thái và quan hệ trong cảnh thay đổi.",
                    "sky_blend": 0.5,
                },
                {
                    "key": "Kết quả",
                    "quote": "Cảnh giữ được nhịp tương tác tối thiểu thay vì chỉ là template dữ liệu.",
                    "sky_blend": 1.0,
                },
            ],
            "quality_gate": {
                "name": "explicit_simulation_not_generic_data_band",
                "from": PRIMITIVE_DATA_BAND,
                "to": PRIMITIVE_SCENE,
            },
        }
    )
    return upgraded
