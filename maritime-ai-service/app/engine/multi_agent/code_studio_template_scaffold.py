"""Spec-driven graceful HTML scaffold for Code Studio (Sprint 35i SOTA refactor).

When the Code Studio tool-planning LLM call times out or fails (NVIDIA NIM
connection errors, DeepSeek streaming stalls), we still owe the user a
visible canvas instead of a canned "Mình gặp trục trặc" message.

## Why this exists (the 10 000-topic problem)

Sprint 35e/35f/35g built one HTML template per topic kind (literary,
physics, math, history, celestial, default). Sprint 35h replaced that
with 16 INTENT_PATTERNS — better, but still topic-bound: adding "lá rụng
mùa thu" needed a dict entry, "mưa rơi" needed another, "đại bàng săn
mồi" needed another. With 10 000 possible Vietnamese queries it didn't
scale.

Sprint 35i fixes the architecture, not the count.

## Architecture — three-tier resolution

### Tier 1: ``TOPIC_LIBRARY`` (rich content overrides, ~5 entries)

Hand-curated event/moment lists for famous, recurring topics: Thế chiến
II, Khởi nghĩa Lam Sơn, Bạch Đằng, Truyện Kiều, văn học Việt Nam. When
matched, scaffold ships concrete years/quotes instead of placeholder
structure. Adding a new famous topic = +1 entry (~10 lines).

### Tier 2: ``PRIMITIVE_CONCEPTS`` (concept-level patterns, 7 entries)

Universal motion/structure/atmosphere signals → primitive type. NOT
topic-bound: "rụng/rơi/lả tả" matches falling autumn leaves, snow, rain,
ash, petals, tears — anything that falls. "lịch sử/triều đại/chiến
tranh" matches WW2, Lê Lợi, Roman empire, Genghis Khan. "hàm/đồ thị/sin"
matches any math curve.

The 7 concepts cover every primitive family the renderers can produce:
``particle_drift_down``, ``particle_float``, ``particle_twinkle``,
``oscillation``, ``function_plot``, ``timeline``, ``scene``.

### Tier 3: smart inference defaults (handles infinite novel topics)

When no concept matches, ``_build_default_spec`` returns a ``DATA_BAND``
canvas with all fields filled by deterministic inference helpers run on
the query alone:

- ``_extract_visual_title`` — strips command words ("mô phỏng", "vẽ",
  "tạo") so the title focuses on the noun phrase.
- ``_infer_palette`` — picks palette from atmospheric/seasonal keywords
  ("đêm" → night_sky, "mùa thu" → autumn, "biển" → ocean, etc.).
- ``_infer_object_name`` — detects object noun ("lá", "tuyết", "giọt",
  "ngôi sao", "đom đóm") for slider labels.
- ``_infer_drift_direction`` — extracts motion verb ("rơi" → down,
  "bay" → float, "lung linh" → twinkle) for particle behaviour.
- ``_infer_count_range`` — quantity hints ("dày đặc" → 250 default,
  "lác đác" → 25 default).

All deterministic, microsecond-fast, no LLM dependency. Adding 10 000
novel topics = 0 lines of code.

## Primitives (6 universal canvas families, unchanged from 35h)

- ``PARTICLE_FIELD`` — stars, dust, leaves, snow, fireflies, plankton…
- ``OSCILLATION`` — pendulum, spring, transverse wave, harmonic motion
- ``TIMELINE`` — historical events, project plan, life cycle, story arc
- ``FUNCTION_PLOT`` — math curves, value-over-x with draggable probe
- ``SCENE`` — atmospheric scene with optional figure(s) + landmark
- ``DATA_BAND`` — abstract sine wave (true topic-agnostic placeholder)

Each primitive accepts the same ``ScaffoldSpec`` shape (now richer
thanks to ``_enrich_spec``) and emits canvas + slider + aria-live
readout + RAF state engine + WiiiVisualBridge feedback hook — passing
every requirement of ``validate_code_studio_output`` for premium
simulations.

## Public API (backward-compatible)

- ``INTENT_PATTERNS`` — alias = TOPIC_LIBRARY + PRIMITIVE_CONCEPTS
  (existing tests still import this).
- ``extract_scaffold_spec(query)`` — runs the 3-tier resolution.
- ``detect_scaffold_kind(query)`` — returns legacy kind name
  (``literary``, ``physics``, ``math``, ``history``, ``celestial``,
  ``default``) for callers/tests that depend on the older surface.
- ``build_code_studio_scaffold(query, kind=None)`` — returns full HTML.
- ``build_scaffold_visible_caption(query, kind=None)`` — short caption.

Pure functions — no LLM, no async, no I/O. Pattern reference:
- Anthropic Claude Artifacts 2026 — spec-driven primitives
- Vercel v0 — parameterized React templates
- Bolt.new — WebContainer scaffolds + theme inheritance
- Cursor Composer 2026 — LLM-as-renderer fallback chain
- W3C CSS Custom Properties Level 3 — variable inheritance

Wiii references:
- ``app/engine/reasoning/skills/subagents/code_studio_agent/VISUAL_CODE_GEN.md``
- ``app/engine/tools/visual_code_quality.py`` (validator the scaffold
  output must satisfy)
"""

from __future__ import annotations

import html
import unicodedata

from app.engine.multi_agent.code_studio_scaffold_core_renderers import (
    render_function_plot_scaffold,
    render_oscillation_scaffold,
    render_particle_field_scaffold,
    render_timeline_scaffold,
)
from app.engine.multi_agent.code_studio_scaffold_contract import (
    PRIMITIVE_DATA_BAND,
    PRIMITIVE_FUNCTION_PLOT,
    PRIMITIVE_OSCILLATION,
    PRIMITIVE_PARTICLE_FIELD,
    PRIMITIVE_SCENE,
    PRIMITIVE_TIMELINE,
    legacy_kind_for_primitive,
    primitive_for_legacy_kind,
)
from app.engine.multi_agent.code_studio_scaffold_captions import (
    caption_for_scaffold_primitive,
)
from app.engine.multi_agent.code_studio_scaffold_quality import (
    apply_scaffold_quality_gate,
)
from app.engine.multi_agent.code_studio_scaffold_registry import (
    ScaffoldRendererRegistry,
)
from app.engine.multi_agent.code_studio_scaffold_scene_renderers import (
    render_data_band_scaffold,
    render_scene_scaffold,
)

# ============================================================================
# Primitive identifiers + legacy kind mapping contract
# ============================================================================

# Primitive and legacy-kind names live in ``code_studio_scaffold_contract``.
# This renderer imports them so public routing/metrics code can depend on the
# contract without importing the full HTML scaffold module.

# ============================================================================
# Palette library (CSS variable-aware, host theme-overridable)
# ============================================================================

# Each palette is a dict with sky_top, sky_mid, sky_bottom, accent, fg, fg_muted.
# Hardcoded fallbacks; the iframe inherits ``--wiii-*`` overrides from the
# host theme bridge (``InlineVisualFrame.readHostThemeOverrides``).
_PALETTES = {
    "night_sky": {
        "sky_top": "#02030f", "sky_mid": "#08102a", "sky_bottom": "#1a1f2e",
        "accent": "#fef9e7", "fg": "#e8e1d0", "fg_muted": "rgba(232,225,208,.85)",
    },
    "deep_space": {
        "sky_top": "#0e0530", "sky_mid": "#241750", "sky_bottom": "#5a3088",
        "accent": "#ff86d2", "fg": "#e8d5ff", "fg_muted": "rgba(232,213,255,.85)",
    },
    "warm_dusk": {
        "sky_top": "#1f1c33", "sky_mid": "#3b2c4a", "sky_bottom": "#d2a673",
        "accent": "#ffe5c1", "fg": "#fff8ec", "fg_muted": "rgba(255,248,236,.85)",
    },
    "autumn": {
        "sky_top": "#3a1f0a", "sky_mid": "#7a3a14", "sky_bottom": "#d97744",
        "accent": "#ffba6b", "fg": "#fff0d6", "fg_muted": "rgba(255,240,214,.85)",
    },
    "winter": {
        "sky_top": "#1a2a3f", "sky_mid": "#3e5878", "sky_bottom": "#a3c5e0",
        "accent": "#ffffff", "fg": "#e8f0f8", "fg_muted": "rgba(232,240,248,.85)",
    },
    "spring": {
        "sky_top": "#fff5d6", "sky_mid": "#fbe5a6", "sky_bottom": "#a3d495",
        "accent": "#ff8fa3", "fg": "#3a2a1f", "fg_muted": "rgba(58,42,31,.78)",
    },
    "ocean": {
        "sky_top": "#0a3a5c", "sky_mid": "#1a6b8a", "sky_bottom": "#5fb3c9",
        "accent": "#fff6a3", "fg": "#e3f2f9", "fg_muted": "rgba(227,242,249,.85)",
    },
    "forest": {
        "sky_top": "#0e2a14", "sky_mid": "#2a5a30", "sky_bottom": "#7ba85c",
        "accent": "#ffd66b", "fg": "#dff0d2", "fg_muted": "rgba(223,240,210,.85)",
    },
    "physics_warm": {
        "sky_top": "#fff7e8", "sky_mid": "#f4dfae", "sky_bottom": "#dfa667",
        "accent": "#d97757", "fg": "#3a2a1f", "fg_muted": "rgba(58,42,31,.7)",
    },
    "math_cream": {
        "sky_top": "#fff8f1", "sky_mid": "#fce6c7", "sky_bottom": "#fde9d3",
        "accent": "#d97757", "fg": "#3a2a1f", "fg_muted": "rgba(58,42,31,.7)",
    },
    "historical_dark": {
        "sky_top": "#0e1230", "sky_mid": "#1f1c33", "sky_bottom": "#1a1f2e",
        "accent": "#d97757", "fg": "#e8e1d0", "fg_muted": "rgba(232,225,208,.85)",
    },
    "lab_bright": {
        "sky_top": "#fdf6ef", "sky_mid": "#f9e6c5", "sky_bottom": "#f3dcc4",
        "accent": "#d97757", "fg": "#3a2a1f", "fg_muted": "rgba(58,42,31,.78)",
    },
}

# ============================================================================
# Topic library — rich content overrides for famous, recurring topics.
#
# Additive, optional layer. Provides hand-curated event/moment lists for
# topics the platform knows are popular (WW2 timeline, Truyện Kiều scene,
# kháng chiến chống Nguyên, etc.). Falls through to PRIMITIVE_CONCEPTS for
# anything not in this library.
#
# Adding rich content for a new famous topic = +1 entry (~10 lines).
# Adding 10 000 novel topics = +0 entries — they're handled deterministically
# by PRIMITIVE_CONCEPTS + smart inference helpers below.
# ============================================================================

TOPIC_LIBRARY: list[dict] = [
    # ── Thế chiến II ────────────────────────────────────────────────────
    {
        "keywords": [
            "thế chiến", "the chien", "world war", "ww1", "ww2", "wwii",
            "thế chiến thứ 2", "the chien thu 2", "đại chiến", "dai chien",
        ],
        "spec": {
            "primitive": PRIMITIVE_TIMELINE,
            "palette": "historical_dark",
            "title": "Thế chiến II",
            "slider_label": "Năm",
            "events": [
                {"year": 1939, "title": "Mở màn", "text": "Đức xâm lược Ba Lan ngày 1/9/1939, châm ngòi Thế chiến II."},
                {"year": 1940, "title": "Tây Âu thất thủ", "text": "Pháp đầu hàng trong 6 tuần; Anh chiến đấu trong Trận không chiến Britain."},
                {"year": 1941, "title": "Mở rộng mặt trận", "text": "Đức tấn công Liên Xô (Barbarossa); Nhật bất ngờ đánh Trân Châu Cảng."},
                {"year": 1942, "title": "Bước ngoặt", "text": "Stalingrad bắt đầu; Midway xoay chiều mặt trận Thái Bình Dương."},
                {"year": 1943, "title": "Phản công", "text": "Liên Xô phản công sau Kursk; Đồng minh đổ bộ Sicily."},
                {"year": 1944, "title": "Giải phóng", "text": "Đổ bộ Normandie ngày 6/6/1944; Paris được giải phóng."},
                {"year": 1945, "title": "Kết thúc", "text": "Đức đầu hàng tháng 5; Nhật đầu hàng tháng 8 sau Hiroshima/Nagasaki."},
            ],
            "hint": (
                "Dòng thời gian Thế chiến II — kéo thanh trượt qua các mốc "
                "lớn 1939-1945. Cho Wiii biết bạn quan tâm tới mặt trận "
                "(châu Âu / Thái Bình Dương / Bắc Phi) hoặc chiến dịch cụ "
                "thể để mở rộng thành mô phỏng đầy đủ."
            ),
        },
    },
    # ── Khởi nghĩa Lam Sơn (Lê Lợi) ─────────────────────────────────────
    {
        "keywords": [
            "lê lợi", "le loi", "lam sơn", "lam son",
            "kháng chiến chống minh", "khang chien chong minh",
        ],
        "spec": {
            "primitive": PRIMITIVE_TIMELINE,
            "palette": "historical_dark",
            "title": "Khởi nghĩa Lam Sơn",
            "slider_label": "Năm",
            "events": [
                {"year": 1418, "title": "Khởi nghĩa Lam Sơn", "text": "Lê Lợi tụ binh tại Lam Sơn (Thanh Hóa) chống quân Minh."},
                {"year": 1424, "title": "Chiến dịch Nghệ An", "text": "Mở rộng vùng kiểm soát ra Nghệ Tĩnh."},
                {"year": 1426, "title": "Chiến thắng Tốt Động – Chúc Động", "text": "Đại phá quân Minh ở Tốt Động – Chúc Động."},
                {"year": 1427, "title": "Chi Lăng – Xương Giang", "text": "Tiêu diệt 10 vạn viện binh do Liễu Thăng dẫn đầu."},
                {"year": 1428, "title": "Lập triều Lê", "text": "Lê Lợi lên ngôi, nhà Hậu Lê khởi đầu, ban Bình Ngô đại cáo."},
            ],
            "hint": (
                "Dòng thời gian khởi nghĩa Lam Sơn — kéo thanh trượt qua các "
                "mốc 1418-1428. Cho Wiii biết bạn muốn đào sâu trận đánh nào "
                "hay nhân vật nào để mình mở rộng."
            ),
        },
    },
    # ── Kháng chiến chống Nguyên Mông (Trần Hưng Đạo, Bạch Đằng) ────────
    {
        "keywords": [
            "trần hưng đạo", "tran hung dao", "bạch đằng", "bach dang",
            "kháng chiến chống nguyên", "chong nguyen mong",
        ],
        "spec": {
            "primitive": PRIMITIVE_TIMELINE,
            "palette": "historical_dark",
            "title": "Kháng chiến chống Nguyên Mông",
            "slider_label": "Năm",
            "events": [
                {"year": 1257, "title": "Lần 1", "text": "Quân Mông Cổ (Ngột Lương Hợp Thai) tấn công Đại Việt; thua trận Đông Bộ Đầu."},
                {"year": 1284, "title": "Lần 2 — chuẩn bị", "text": "Trần Hưng Đạo soạn Hịch tướng sĩ; Hội nghị Diên Hồng."},
                {"year": 1285, "title": "Lần 2 — phản công", "text": "Chiến thắng Hàm Tử, Chương Dương, Tây Kết — đuổi quân Nguyên về."},
                {"year": 1287, "title": "Lần 3 — chuẩn bị", "text": "Quân Nguyên do Thoát Hoan dẫn đầu chuẩn bị xâm lược lần 3."},
                {"year": 1288, "title": "Bạch Đằng đại thắng", "text": "Trần Hưng Đạo đóng cọc nhọn dưới sông Bạch Đằng, tiêu diệt thuỷ quân Ô Mã Nhi."},
            ],
            "hint": (
                "Dòng thời gian 3 lần kháng chiến chống Nguyên Mông — kéo "
                "thanh trượt qua các mốc 1257-1288. Cho Wiii biết bạn muốn "
                "tập trung vào trận Bạch Đằng, Hịch tướng sĩ, hay Hội nghị "
                "Diên Hồng để mở rộng."
            ),
        },
    },
    # ── Truyện Kiều — Thúy Kiều ở lầu Ngưng Bích ────────────────────────
    {
        "keywords": [
            "thúy kiều", "thuy kieu",
            "truyện kiều", "truyen kieu",
            "ngưng bích", "ngung bich",
            "đoạn trường", "doan truong",
            "nguyễn du", "nguyen du",
        ],
        "spec": {
            "primitive": PRIMITIVE_SCENE,
            "palette": "warm_dusk",
            "title": "Thúy Kiều ở lầu Ngưng Bích",
            "scene_figure": "tower",
            "slider_label": "Thời gian trôi",
            "moments": [
                {"key": "Hoàng hôn", "quote": "Buồn trông cửa bể chiều hôm,",
                 "sky_blend": 0.0},
                {"key": "Trăng lên", "quote": "Trông vời cánh buồm xa xa.",
                 "sky_blend": 0.33},
                {"key": "Đêm sâu", "quote": "Sóng nước chân mây đáy bể,",
                 "sky_blend": 0.66},
                {"key": "Bình minh", "quote": "Một mình ai biết, ai hay…",
                 "sky_blend": 1.0},
            ],
            "hint": (
                "Khung scene Thúy Kiều ở lầu Ngưng Bích — kéo thanh trượt "
                "qua bốn khoảnh khắc trong ngày, mỗi cảnh kèm một câu thơ "
                "trong đoạn trích. Cho Wiii biết bạn muốn nhấn vào điều gì "
                "(tâm trạng, đoạn thơ chi tiết, phong cách vẽ) để mở rộng."
            ),
        },
    },
    # ── Vietnamese literature — character-driven ────────────────────────
    {
        "keywords": [
            "tấm cám", "tam cam", "lục vân tiên", "luc van tien",
            "chí phèo", "chi pheo", "lão hạc", "lao hac",
            "tắt đèn", "tat den", "vợ chồng a phủ", "vo chong a phu",
            "rừng xà nu", "rung xa nu", "số đỏ", "so do",
            "chiếc thuyền ngoài xa", "chiec thuyen ngoai xa",
            "hai đứa trẻ", "hai dua tre",
            "vĩnh biệt cửu trùng đài", "vinh biet cuu trung dai",
            "nguyễn trãi", "nguyen trai",
            "nam cao", "nguyễn tuân", "nguyen tuan",
            "vũ trọng phụng", "vu trong phung",
            "thạch lam", "thach lam",
            "xuân diệu", "xuan dieu", "huy cận", "huy can",
        ],
        "spec": {
            "primitive": PRIMITIVE_SCENE,
            "palette": "warm_dusk",
            "scene_figure": "character",
            "slider_label": "Thời gian trôi",
            "moments": [
                {"key": "Mở đầu", "quote": "Bối cảnh quen thuộc của tác phẩm.",
                 "sky_blend": 0.0},
                {"key": "Phát triển", "quote": "Mâu thuẫn và biến cố.",
                 "sky_blend": 0.5},
                {"key": "Cao trào", "quote": "Đỉnh điểm của câu chuyện.",
                 "sky_blend": 0.8},
                {"key": "Kết", "quote": "Hậu quả và dư vị.",
                 "sky_blend": 1.0},
            ],
            "hint": (
                "Khung scene tác phẩm văn học Việt Nam — kéo thanh trượt qua "
                "các giai đoạn của câu chuyện. Cho Wiii biết bạn muốn tập "
                "trung vào nhân vật, đoạn trích, hay phong cách hình ảnh nào."
            ),
        },
    },
]


# ============================================================================
# Primitive concepts — concept-level pattern matching.
#
# Each concept maps a small set of MOTION/STRUCTURE/ATMOSPHERE signals to
# a primitive + base parameters. Crucially these are NOT topic-specific:
# "rụng/rơi" matches falling autumn leaves, snow, rain, ash, petals, tears
# — anything that falls. "lịch sử/năm/triều đại" matches WW2, Lê Lợi,
# Roman empire, Genghis Khan — any historical sequence.
#
# Adding a new primitive concept = +1 entry. Adding a new TOPIC that fits
# an existing concept (i.e. 99% of new topics) = +0 entries.
# ============================================================================

PRIMITIVE_CONCEPTS: list[dict] = [
    # ── 1. Drift-down particles (autumn leaves, snow, rain, ash, petals) ─
    # Diacritic-stripped "rụng" → "rung" collides with "rừng" (forest);
    # diacritic-stripped "rơi" → "roi" collides with "rồi" (already). Use
    # compound forms + raw-diacritic forms only.
    {
        "keywords": [
            # Raw diacritic forms (unambiguous when user types diacritics)
            "rụng", "rơi",
            # Compound stripped forms (require object + verb together)
            "la rung", "la roi", "tan rung", "tan roi",
            "tuyet roi", "mua roi", "hoa roi",
            "rui rung", "rung xuong", "roi xuong",
            # Heavy/fast falling
            "đổ xuống", "do xuong",
            "tuôn", "tuon",
            "tàn rơi", "lả tả", "la ta",
        ],
        "spec": {
            "primitive": PRIMITIVE_PARTICLE_FIELD,
            "drift_direction": "down",
        },
    },
    # ── 2. Floating particles (fireflies, butterflies, dust, plankton) ──
    # Short signals are space-padded to enforce word boundaries — prevents
    # "luon" (lượn) from matching "luong" (lương = salary).
    {
        "keywords": [
            " bay ", " lơ lửng ", " lo lung ", " trôi ", " troi ",
            "phất phơ", "phat pho", " lượn ", " luon ", " vẫy ", " vay ",
            "đom đóm", "dom dom", "firefly", "butterfly", "bướm", "buom",
        ],
        "spec": {
            "primitive": PRIMITIVE_PARTICLE_FIELD,
            "drift_direction": "float",
        },
    },
    # ── 3. Twinkling field (stars, distant lights, plankton glow) ───────
    {
        "keywords": [
            "sao", "starry", "stars", "ngân hà", "ngan ha", "galaxy",
            "vũ trụ", "vu tru", "universe", "cosmos",
            "tinh tú", "tinh tu", "thiên hà", "thien ha",
            "lung linh", "lấp lánh", "lap lanh", "lóng lánh", "long lanh",
            "đốm sáng", "dom sang", "twinkle", "huyền ảo", "huyen ao",
            "ánh sáng", "anh sang", "rực rỡ", "ruc ro",
            "chòm sao", "chom sao", "constellation",
            "vầng trăng", "vang trang", "ánh trăng", "anh trang",
            "đêm trăng", "dem trang", "bầu trời", "bau troi",
            "thiên văn", "thien van", "astronomy",
            "hành tinh", "hanh tinh", "planet",
            "sao chổi", "sao choi", "comet",
            "northern lights", "aurora", "cực quang", "cuc quang",
        ],
        "spec": {
            "primitive": PRIMITIVE_PARTICLE_FIELD,
            "drift_direction": "twinkle",
            "extra_layers": ["moon"],
        },
    },
    # ── 4. Oscillation (pendulum, spring, wave, projectile, vibration) ──
    # Note: projectile/quỹ đạo land here because parabolic trajectory under
    # gravity is a physics phenomenon (not a math abstract curve). Order
    # matters — this concept is checked BEFORE function_plot so "viên đạn
    # parabol" routes to physics, not math.
    {
        "keywords": [
            "con lắc", "con lac", "pendulum",
            "dao động", "dao dong", "oscillation", "oscillator",
            "lò xo", "lo xo", "spring",
            "rung động", "rung dong", "vibration",
            "tần số", "tan so", "frequency",
            "biên độ", "bien do", "amplitude",
            "sóng", "song ", " song", "wave",
            "harmonic", "điều hoà", "dieu hoa",
            "quỹ đạo", "quy dao", "trajectory",
            "viên đạn", "vien dan", "projectile",
        ],
        "spec": {
            "primitive": PRIMITIVE_OSCILLATION,
            "palette": "physics_warm",
            "slider_label": "Góc lệch ban đầu",
            "slider_min": 5,
            "slider_max": 60,
            "slider_default": 30,
            "slider_unit": "°",
        },
    },
    # ── 5. Function plot (math curves, equations, vectors, coordinates) ─
    # Math function names are bound to math syntax compounds (sin(x),
    # ham sin, tan x) to avoid colliding with "tan" (scatter), "sin"
    # (rare ambiguity), "log" inside other words.
    {
        "keywords": [
            "hàm số", "ham so", "function",
            "đồ thị", "do thi", " graph ",
            "đạo hàm", "dao ham", "derivative",
            "tích phân", "tich phan", "integral",
            "phương trình", "phuong trinh", "equation",
            "lượng giác", "luong giac", "trigonometry",
            "parabol", "hyperbol", "elip", "ellipse",
            "sin(", "cos(", "tan(", "log(", "ln(",
            "ham sin", "ham cos", "ham tan", "ham log", "ham ln",
            "sin x", "cos x", "tan x",
            "vector", "vecto", "véc tơ", "vec to",
            "toạ độ", "toa do", "tọa độ",
            "oxy ", " oxy", " trục ", " truc ",
        ],
        "spec": {
            "primitive": PRIMITIVE_FUNCTION_PLOT,
            "palette": "math_cream",
            "slider_label": "Vị trí điểm x",
            "slider_min": -50,
            "slider_max": 50,
            "slider_default": 10,
            "function_expression": "x*x",
            "function_label_vi": "y = x²",
        },
    },
    # ── 6. Timeline (history, sequences, dynasties, wars, eras) ─────────
    {
        "keywords": [
            "lịch sử", "lich su", "history",
            "thế kỷ", "the ky", "century",
            "triều đại", "trieu dai", "dynasty",
            "chiến tranh", "chien tranh", "war",
            "trận đánh", "tran danh", "battle",
            "khởi nghĩa", "khoi nghia",
            "cách mạng", "cach mang", "revolution",
            "đế chế", "de che", "empire",
            "vương triều", "vuong trieu",
            "phong kiến", "phong kien",
            "1945", "1954", "1968", "1975",
            "ngô quyền", "ngo quyen", "quang trung",
            "điện biên phủ", "dien bien phu",
            "hai bà trưng", "hai ba trung",
            "thánh gióng", "thanh giong",
            "vua hùng", "vua hung", "an dương vương", "an duong vuong",
        ],
        "spec": {
            "primitive": PRIMITIVE_TIMELINE,
            "palette": "historical_dark",
            "slider_label": "Mốc thời gian",
            "events": [
                {"year": 0, "title": "Khởi đầu", "text": "Bối cảnh hình thành sự kiện."},
                {"year": 1, "title": "Diễn biến", "text": "Các bước phát triển chính."},
                {"year": 2, "title": "Cao trào", "text": "Thời điểm quyết định."},
                {"year": 3, "title": "Hệ quả", "text": "Hậu quả và ý nghĩa lịch sử."},
            ],
        },
    },
    # ── 7. Scene (literary scenes, characters, atmospheric stories) ─────
    {
        "keywords": [
            "cảnh", "canh", "khung cảnh", "khung canh", "bối cảnh", "boi canh",
            "tác phẩm", "tac pham",
            "đoạn trích", "doan trich",
            "nhân vật", "nhan vat",
            "truyện", "truyen",
            "bài thơ", "bai tho", "thơ", "tho ", "poem", "poetry",
            "literature", "scene", "câu chuyện", "cau chuyen",
        ],
        "spec": {
            "primitive": PRIMITIVE_SCENE,
            "palette": "warm_dusk",
            "scene_figure": "character",
            "slider_label": "Thời gian",
            "moments": [
                {"key": "Sáng sớm", "quote": "Cảnh sớm mai vắng lặng.", "sky_blend": 0.0},
                {"key": "Giữa trưa", "quote": "Ánh nắng chói chang.", "sky_blend": 0.4},
                {"key": "Hoàng hôn", "quote": "Bóng chiều buông xuống.", "sky_blend": 0.7},
                {"key": "Đêm khuya", "quote": "Tĩnh mịch của đêm sâu.", "sky_blend": 1.0},
            ],
        },
    },
]


# ============================================================================
# Backward-compat alias — TOPIC_LIBRARY + PRIMITIVE_CONCEPTS unified view.
# Existing tests import INTENT_PATTERNS expecting this structure.
# ============================================================================

INTENT_PATTERNS: list[dict] = TOPIC_LIBRARY + PRIMITIVE_CONCEPTS


# ============================================================================
# Inference dictionaries — pure data, no per-topic patterns.
#
# These map UNIVERSAL signals (atmosphere/object/motion/density words) to
# spec parameters. They cover any Vietnamese or English query without
# enumerating topics.
# ============================================================================

# (signal_keywords, palette_name) — first match wins. Diacritic-stripped
# variants included so "đêm" and "dem" both hit. Order matters: more
# specific signals come first.
_PALETTE_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("đêm", "dem ", " dem", "khuya", "trăng", "trang ", " trang",
      "tinh tú", "tinh tu", "vũ trụ", "vu tru",
      "ngân hà", "ngan ha", "thiên hà", "thien ha",
      "ngôi sao", "ngoi sao", "trời sao", "troi sao",
      "đầy sao", "day sao", "chòm sao", "chom sao",
      "starry", "galaxy", "cosmos", "universe", "night sky",
      "bầu trời đêm", "bau troi dem"), "night_sky"),
    (("vũ trụ sâu", "vu tru sau", "deep space", "tinh vân", "tinh van",
      "nebula"), "deep_space"),
    (("hoàng hôn", "hoang hon", "chiều tà", "chieu ta", "tà dương",
      "ta duong", "dusk", "sunset", "chiều buông", "chieu buong"), "warm_dusk"),
    (("mùa thu", "mua thu", "autumn", "lá vàng", "la vang", "vàng úa",
      "vang ua", "lá rụng", "la rung", "lá rơi", "la roi"), "autumn"),
    (("mùa đông", "mua dong", "tuyết", "tuyet", "lạnh giá", "lanh gia",
      "winter", "băng tuyết", "bang tuyet", "snowflake"), "winter"),
    (("mùa xuân", "mua xuan", "hoa anh đào", "hoa anh dao", "sakura",
      "spring", "đào nở", "dao no"), "spring"),
    (("biển", "bien", "đại dương", "dai duong", "ocean", "sea",
      "sóng biển", "song bien", "mưa rơi", "mua roi", "cơn mưa",
      "con mua", "rain", "rainfall", "bão", "bao ", " bao"), "ocean"),
    (("rừng", "rung ", " rung", "khu rừng", "khu rung", "forest",
      "jungle", "tán cây", "tan cay", "rừng già", "rung gia",
      "đom đóm", "dom dom", "firefly", "fireflies"), "forest"),
    (("vật lý", "vat ly", "physics", "cơ học", "co hoc",
      "động lực học", "dong luc hoc"), "physics_warm"),
    (("toán", "toan", "math", "đại số", "dai so",
      "hình học", "hinh hoc", "calculus"), "math_cream"),
    (("lịch sử", "lich su", "chiến tranh", "chien tranh",
      "history", "war", "battle", "đế chế", "de che",
      "triều đại", "trieu dai"), "historical_dark"),
    (("phòng thí nghiệm", "phong thi nghiem", "lab", "laboratory",
      "thí nghiệm", "thi nghiem"), "lab_bright"),
]


# (signal_keywords, particle_label_vi) — falling/floating/twinkling object
# names extracted from query. Used to humanise the slider readout.
# Object hints — order matters; matched against query padded with spaces so
# substrings like "tro" don't greedily match "troi". Use leading/trailing
# spaces in keys to enforce word-ish boundaries on short signals.
_OBJECT_HINTS: list[tuple[tuple[str, ...], str]] = [
    # Compound nouns first (most specific)
    (("lá rụng", "la rung", "lá rơi", "la roi", "tán lá", "tan la",
      " lá ", " la "), "chiếc lá"),
    (("bông tuyết", "bong tuyet", "tuyết rơi", "tuyet roi",
      "snowflake", "snowfall"), "bông tuyết"),
    (("giọt mưa", "giot mua", "mưa rơi", "mua roi",
      "raindrop", "rainfall", " mưa ", " mua "), "giọt mưa"),
    (("hoa anh đào", "hoa anh dao", "sakura petals", "cánh hoa",
      "canh hoa", "hoa rơi", "hoa roi"), "cánh hoa"),
    (("ngôi sao", "ngoi sao", "starlight", "star "), "ngôi sao"),
    (("đom đóm", "dom dom", "firefly", "fireflies"), "đom đóm"),
    (("cánh bướm", "canh buom", "bướm bay", "buom bay",
      "butterfly"), "cánh bướm"),
    (("chuồn chuồn", "chuon chuon", "dragonfly"), "chuồn chuồn"),
    (("cánh ong", "canh ong", " ong "), "cánh ong"),
    (("hạt bụi", "hat bui", "dust mote", " bụi ", " bui "), "hạt bụi"),
    (("đốm sáng", "dom sang", " đốm ", " dom ", "spark "), "đốm sáng"),
    (("hạt phấn", "hat phan", "pollen", " phấn ", " phan "), "hạt phấn"),
    (("hạt tro", "hat tro", " tro ", "ash particle", " ash "), "hạt tro"),
    (("tia sáng", "tia sang", " tia ", "ray of light"), "tia sáng"),
    (("hạt mưa đá", "hat mua da", "hailstone"), "hạt mưa đá"),
]


# Command words to strip from the head of the query so the title focuses on
# the noun phrase the user actually wants visualised.
_TITLE_PREFIXES: tuple[str, ...] = (
    "mô phỏng cảnh", "mo phong canh",
    "mô phỏng việc", "mo phong viec",
    "mô phỏng quá trình", "mo phong qua trinh",
    "mô phỏng", "mo phong",
    "mô tả", "mo ta",
    "vẽ cảnh", "ve canh",
    "vẽ", "ve",
    "tạo cảnh", "tao canh",
    "tạo ra", "tao ra",
    "tạo", "tao",
    "dựng cảnh", "dung canh",
    "dựng ra", "dung ra",
    "dựng", "dung",
    "hiển thị", "hien thi",
    "hãy", "hay",
    "render", "show", "display", "visualize", "visualise",
    "build", "create", "make", "simulate",
    "draw", "plot",
)


# Sensible default palette per primitive (used when query has no atmospheric
# hint to drive _infer_palette).
_DEFAULT_PALETTE_BY_PRIMITIVE: dict[str, str] = {
    PRIMITIVE_PARTICLE_FIELD: "night_sky",
    PRIMITIVE_OSCILLATION: "physics_warm",
    PRIMITIVE_TIMELINE: "historical_dark",
    PRIMITIVE_FUNCTION_PLOT: "math_cream",
    PRIMITIVE_SCENE: "warm_dusk",
    PRIMITIVE_DATA_BAND: "lab_bright",
}


# ============================================================================
# Helpers
# ============================================================================


def _normalize(text: str) -> str:
    if not text:
        return ""
    lowered = " ".join(text.lower().split())
    nfkd = unicodedata.normalize("NFD", lowered)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


def _short_title(query: str, max_len: int = 60) -> str:
    title = (query or "").strip()
    if len(title) > max_len:
        title = title[:max_len].rstrip() + "…"
    return title or "Khung dựng cảnh"


def _legacy_kind_for(spec: dict) -> str:
    primitive = spec.get("primitive", PRIMITIVE_DATA_BAND)
    return legacy_kind_for_primitive(primitive)


def _aria_label(spec: dict, title: str) -> str:
    legacy = _legacy_kind_for(spec)
    descriptor = {
        "literary": "Khung mô phỏng văn học",
        "physics": "Khung mô phỏng vật lý",
        "math": "Khung dựng đồ thị",
        "history": "Khung mô phỏng lịch sử",
        "celestial": "Khung mô phỏng bầu trời",
        "default": "Khung mô phỏng",
    }.get(legacy, "Khung mô phỏng")
    return (
        f"{descriptor} cho {title} — màn hình tạm, "
        "Wiii sẽ mở rộng khi bạn mô tả thêm chi tiết"
    )


# ─── Smart inference helpers (deterministic, microsecond) ──────────────────


def _extract_visual_title(query: str, max_len: int = 60) -> str:
    """Strip command words ("mô phỏng", "vẽ", "tạo") iteratively.

    Works for any topic — uses prefix-matching only, no topic enumeration.
    Iterates so chained prefixes ("hãy mô phỏng X" → "X") all get stripped.
    """
    title = (query or "").strip()
    if not title:
        return "Khung dựng cảnh"
    # Iterate until no prefix matches (handles "hãy mô phỏng cảnh ...").
    for _ in range(6):  # cap iterations to avoid pathological cases
        lower_title = title.lower()
        norm_title = _normalize(title)
        best_strip = 0
        for prefix in _TITLE_PREFIXES:
            if lower_title.startswith(prefix) and len(prefix) > best_strip:
                best_strip = len(prefix)
            elif norm_title.startswith(prefix) and len(prefix) > best_strip:
                # Diacritic strip is 1:1 in char count — same offset works.
                best_strip = len(prefix)
        if not best_strip:
            break
        title = title[best_strip:].lstrip(" :,.-—-")
        if not title:
            break
    if len(title) > max_len:
        title = title[:max_len].rstrip() + "…"
    return title or "Khung dựng cảnh"


def _infer_palette(query: str, fallback: str = "lab_bright") -> str:
    """Pick palette from atmospheric/seasonal/subject keywords in query."""
    if not query:
        return fallback
    raw = query.lower()
    norm = _normalize(query)
    bag = f"{raw}\n{norm}"
    for keys, palette_name in _PALETTE_HINTS:
        if any(k in bag for k in keys):
            return palette_name
    return fallback


def _infer_object_name(query: str, default: str = "hạt") -> str:
    """Detect object noun from query (lá/tuyết/giọt/cánh/ngôi sao/...).

    Bag is padded with spaces so word-boundary keys (`" tro "`, `" mua "`)
    work correctly — prevents "tro" matching inside "troi".
    """
    if not query:
        return default
    raw = query.lower()
    norm = _normalize(query)
    bag = f" {raw} \n {norm} "
    for keys, name in _OBJECT_HINTS:
        if any(k in bag for k in keys):
            return name
    return default


def _infer_drift_direction(query: str, fallback: str = "twinkle") -> str:
    """Detect motion verb in query → drift direction for particle field.

    Bag is space-padded so word-bound short signals (" roi ", " bay ")
    work without matching substrings of unrelated words ("rồi", "bay" in
    "bayarea"). Bare "rung" is NOT used because "rụng" → "rung" collides
    with "rừng" — instead use compound "la rung", "tan rung" forms below.
    """
    if not query:
        return fallback
    raw = query.lower()
    norm = _normalize(query)
    bag = f" {raw} \n {norm} "
    if any(k in bag for k in (" ào ào ", " ao ao ", "đổ xuống", "do xuong",
                               " tuôn ", " tuon ", "xối xả", "xoi xa",
                               " trút ", " trut ")):
        return "down_fast"
    if any(k in bag for k in (" rơi ", " roi ", " rụng ", "tàn rơi",
                               "tan roi", "lả tả", "la ta",
                               "la rung", "tan rung", "rung xuong",
                               "roi xuong", "tuyet roi", "mua roi",
                               "hoa roi", "la roi",
                               "tro tan", "tan tro", "tan ra",
                               "phun trao", "phut")):
        return "down"
    if any(k in bag for k in (" bay ", " lơ lửng ", " lo lung ",
                               " trôi ", " troi ",
                               "phất phơ", "phat pho", " lượn ", " luon ",
                               " vẫy ", " vay ", " float ", " drift ")):
        return "float"
    if any(k in bag for k in ("lung linh", "lấp lánh", "lap lanh",
                               "lóng lánh", "long lanh", " twinkle ",
                               "rực rỡ", "ruc ro", "huyền ảo", "huyen ao")):
        return "twinkle"
    return fallback


def _infer_count_range(query: str) -> tuple[int, int, int]:
    """Detect quantity hints in query → (min, max, default) particle counts."""
    if not query:
        return (30, 250, 120)
    raw = query.lower()
    norm = _normalize(query)
    bag = f"{raw}\n{norm}"
    if any(k in bag for k in ("dày đặc", "day dac", "kín trời", "kin troi",
                               "đông đúc", "dong duc", "ngập tràn", "ngap tran",
                               "rợp trời", "rop troi", "rất nhiều", "rat nhieu")):
        return (60, 400, 250)
    if any(k in bag for k in ("vài", "vai ", "thưa thớt", "thua thot",
                               "lác đác", "lac dac", " ít ", " it ",
                               "hiếm hoi", "hiem hoi", "lẻ loi", "le loi")):
        return (5, 60, 25)
    return (30, 250, 120)


def _enrich_spec(spec: dict, query: str) -> dict:
    """Fill missing fields by inference from query.

    Works for ANY query — TOPIC_LIBRARY/PRIMITIVE_CONCEPTS provide the
    primitive type + any hand-curated overrides; this helper fills the
    remaining fields so even novel topics produce relevant scaffolds.
    """
    title = _extract_visual_title(query)
    spec.setdefault("title", title)
    primitive = spec.get("primitive", PRIMITIVE_DATA_BAND)

    # Palette: use atmospheric inference if not explicitly set.
    if "palette" not in spec:
        spec["palette"] = _infer_palette(
            query, _DEFAULT_PALETTE_BY_PRIMITIVE.get(primitive, "lab_bright")
        )

    if primitive == PRIMITIVE_PARTICLE_FIELD:
        if "particle_label" not in spec:
            spec["particle_label"] = _infer_object_name(query)
        if "slider_label" not in spec:
            spec["slider_label"] = f"Số {spec['particle_label']}"
        if "drift_direction" not in spec:
            spec["drift_direction"] = _infer_drift_direction(query)
        if "particle_count_min" not in spec or "particle_count_max" not in spec:
            cmin, cmax, cdef = _infer_count_range(query)
            spec.setdefault("particle_count_min", cmin)
            spec.setdefault("particle_count_max", cmax)
            spec.setdefault("particle_count_default", cdef)
        if "readout_lead" not in spec:
            spec["readout_lead"] = title[:40]
        if "readout_phrase" not in spec:
            phrase_by_drift = {
                "down": "đang trôi xuôi theo cơn gió",
                "down_fast": "đang đổ xuống dồn dập",
                "float": "đang lơ lửng trên không",
                "twinkle": "đang lung linh trên canvas",
            }
            spec["readout_phrase"] = phrase_by_drift.get(
                spec.get("drift_direction", "twinkle"),
                "đang vận động trên canvas",
            )

    if "hint" not in spec:
        spec["hint"] = (
            f"Đây là khung tương tác cho '{title}' — kéo thanh trượt để thấy "
            "hệ thống phản hồi. Cho Wiii biết bạn muốn mở rộng theo hướng nào "
            "(nhân vật, tham số, dữ liệu cụ thể…) để mình thay phần lõi bằng "
            "nội dung đúng chủ đề."
        )

    return spec


def _build_default_spec(query: str) -> dict:
    """Smart default for queries with no concept match.

    First runs ``_infer_drift_direction`` — if the query contains any
    motion verb that didn't match a compound keyword above ("hoa anh dao
    roi", "tuyet bay", "anh sang lung linh"), still route to a
    particle_field with the inferred drift. Otherwise falls back to
    DATA_BAND (abstract sine wave) — credible "preparing canvas"
    placeholder that works for anything from Pythagore theorem to
    blockchain consensus. Title and palette still derived from query.
    """
    inferred_drift = _infer_drift_direction(query, fallback="")
    if inferred_drift in ("down", "down_fast", "float", "twinkle"):
        return _enrich_spec({
            "primitive": PRIMITIVE_PARTICLE_FIELD,
            "drift_direction": inferred_drift,
        }, query)
    return apply_scaffold_quality_gate(query, _enrich_spec({
        "primitive": PRIMITIVE_DATA_BAND,
        "slider_label": "Tham số chính",
        "slider_min": 10,
        "slider_max": 100,
        "slider_default": 50,
    }, query))


def extract_scaffold_spec(query: str) -> dict:
    """Resolve query to a scaffold spec via 3-tier matching.

    Tier 1 (TOPIC_LIBRARY): rich hand-curated content for famous topics
        (WW2 events, Truyện Kiều moments). Highest priority — when matched,
        scaffold ships concrete data instead of placeholder structure.

    Tier 2 (PRIMITIVE_CONCEPTS): concept-level signals (motion verbs,
        domain keywords). Maps "rơi" / "bay" / "lung linh" / "đồ thị" /
        "lịch sử" to the right primitive without enumerating topics.

    Tier 3 (smart default): DATA_BAND with all fields filled by inference
        helpers from the query alone. Works for unbounded novel topics.

    All tiers run through ``_enrich_spec`` so every returned spec has the
    full set of fields the renderers need (palette, title, particle_label,
    drift_direction, etc.).
    """
    if not query:
        return _build_default_spec("")
    raw = query.lower()
    norm = _normalize(query)
    # Pad bag with leading/trailing spaces so short keywords like " luon "
    # work as word-boundary matches (prevents "luon" → "lượn" matching
    # "luong" → "lương").
    bag = f" {raw} \n {norm} "
    for entry in INTENT_PATTERNS:
        if any(kw in bag for kw in entry["keywords"]):
            return _enrich_spec({**entry["spec"]}, query)
    return _build_default_spec(query)


def detect_scaffold_kind(query: str) -> str:
    """Backward-compatible legacy kind name from query.

    Walks the new INTENT_PATTERNS/spec extraction path internally then maps
    the resulting primitive back to the historical kind label so existing
    tests + callers (e.g. metrics labels) keep working.
    """
    if not query:
        return "default"
    spec = extract_scaffold_spec(query)
    return _legacy_kind_for(spec)


# ============================================================================
# Common HTML/JS helpers shared by every primitive renderer
# ============================================================================


# Kind-specific CSS variable hooks — host theme overrides land via these.
# Each entry maps legacy_kind → list of var declarations the stage CSS
# emits so the iframe can inherit ``--wiii-{kind}-*`` from the host.
# Variable names match Sprint 35e SKILL VISUAL_CODE_GEN.md v6.2.0 §12.
_KIND_VAR_HOOKS: dict[str, list[tuple[str, str]]] = {
    "literary": [
        ("scene-sky-deep", "sky_top"),
        ("scene-sky-mid", "sky_mid"),
        ("scene-fg", "fg"),
    ],
    "physics": [
        ("phys-bg-light", "sky_top"),
        ("phys-fg", "fg"),
    ],
    "math": [
        ("math-bg-light", "sky_top"),
        ("math-fg", "fg"),
        ("math-grid", "fg_muted"),
    ],
    "history": [
        ("history-bg-deep", "sky_top"),
        ("history-fg", "fg"),
    ],
    "celestial": [
        ("celestial-bg-deep", "sky_top"),
        ("celestial-fg", "fg"),
    ],
    "default": [
        ("default-bg-light", "sky_top"),
        ("default-fg", "fg"),
    ],
}


def _common_styles(prefix: str, palette: dict, kind: str = "default") -> str:
    """Shared stage/controls/slider/readout CSS for any primitive.

    ``prefix`` is the unique CSS class prefix (e.g. ``"wiii-cel"`` for
    celestial) so each primitive has its own scope. Hardcoded fallbacks
    pull from ``palette`` so the iframe renders correctly even without
    host theme overrides.

    ``kind`` is the legacy kind label (literary/physics/math/history/
    celestial/default) — used to emit kind-specific CSS variable hooks
    (``var(--wiii-scene-sky-deep, ...)``) so the host theme can override
    via ``InlineVisualFrame.readHostThemeOverrides``.
    """
    sky_top = palette["sky_top"]
    sky_bottom = palette["sky_bottom"]
    accent = palette["accent"]
    fg = palette["fg"]
    fg_muted = palette["fg_muted"]
    # Build kind-specific var hook declarations as `--_local: var(--wiii-{kind}-{slot}, fallback);`
    hooks = _KIND_VAR_HOOKS.get(kind, _KIND_VAR_HOOKS["default"])
    hook_lines = []
    slot_to_value = {
        "sky_top": sky_top, "sky_mid": palette.get("sky_mid", sky_top),
        "sky_bottom": sky_bottom, "fg": fg, "fg_muted": fg_muted, "accent": accent,
    }
    for var_name, slot in hooks:
        hook_lines.append(
            f"  --wiii-_kind-{var_name}: var(--wiii-{var_name}, {slot_to_value.get(slot, sky_top)});"
        )
    hook_block = "\n".join(hook_lines)
    return f"""
.{prefix}-stage{{
{hook_block}
  position:relative;width:100%;max-width:100%;border-radius:18px;overflow:hidden;
  background:{sky_top};
  box-shadow:0 12px 30px rgba(20,24,38,.25);
  font-family:var(--wiii-font-sans,"Inter",system-ui,sans-serif);
  color:{fg};
}}
.{prefix}-canvas{{display:block;width:100%;aspect-ratio:16/9;min-height:240px;}}
.{prefix}-controls{{
  display:flex;flex-direction:column;gap:10px;padding:14px 18px 16px;
  background:linear-gradient(180deg,
    rgba(0,0,0,0) 0%,
    {sky_bottom} 80%);
}}
.{prefix}-row{{display:flex;align-items:center;gap:12px;font-size:12.5px;color:{fg_muted};}}
.{prefix}-row label{{flex:0 0 auto;letter-spacing:.04em;}}
.{prefix}-slider{{
  flex:1;height:4px;-webkit-appearance:none;appearance:none;
  background:rgba(232,225,208,.18);border-radius:2px;outline:none;
}}
.{prefix}-slider::-webkit-slider-thumb{{
  -webkit-appearance:none;appearance:none;width:14px;height:14px;border-radius:50%;
  background:var(--wiii-accent,{accent});border:1px solid rgba(255,255,255,.85);cursor:pointer;
}}
.{prefix}-slider::-moz-range-thumb{{
  width:14px;height:14px;border-radius:50%;background:var(--wiii-accent,{accent});
  border:1px solid rgba(255,255,255,.85);cursor:pointer;
}}
.{prefix}-readout{{font-size:12px;color:{fg};letter-spacing:.02em;line-height:1.5;}}
.{prefix}-readout strong{{color:var(--wiii-accent,{accent});}}
.{prefix}-hint{{
  margin-top:12px;font-size:13px;line-height:1.55;
  color:var(--wiii-text-secondary,#5b4a4a);
  font-family:var(--wiii-font-sans,"Inter",system-ui,sans-serif);
}}
@media (max-width:480px){{
  .{prefix}-stage{{border-radius:14px;}}
  .{prefix}-canvas{{aspect-ratio:4/3;}}
  .{prefix}-controls{{padding:10px 14px 12px;}}
  .{prefix}-hint{{font-size:12px;line-height:1.45;}}
}}
@media (prefers-reduced-motion:reduce){{
  .{prefix}-canvas{{animation:none !important;}}
}}
""".strip()


def _common_script_wrapper(
    canvas_id: str,
    slider_id: str,
    readout_id: str,
    setup_body: str,
    render_body: str,
    slider_handler_body: str,
) -> str:
    """Shared RAF/slider/reduced-motion JS wrapper for every primitive.

    ``setup_body`` runs once before the loop; ``render_body`` runs every
    frame; ``slider_handler_body`` runs on slider input. All run inside
    an IIFE so iframe globals stay clean.
    """
    return f"""
<script>
(function(){{
  var canvas = document.getElementById('{canvas_id}');
  var slider = document.getElementById('{slider_id}');
  var readout = document.getElementById('{readout_id}');
  if (!canvas || !slider || !readout) return;
  var ctx = canvas.getContext('2d');
  var dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
  var raf = 0;
  var startedAt = performance.now();

  function ensureCanvasSize(){{
    var w = canvas.clientWidth || 640;
    var h = canvas.clientHeight || 360;
    if (canvas.width !== w * dpr) canvas.width = w * dpr;
    if (canvas.height !== h * dpr) canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return {{w: w, h: h}};
  }}

  {setup_body}

  function frame(){{
    var sz = ensureCanvasSize();
    var w = sz.w, h = sz.h;
    var elapsed = (performance.now() - startedAt) / 1000;
    {render_body}
    raf = requestAnimationFrame(frame);
  }}

  function reportProgress(payload, summary){{
    if (window.WiiiVisualBridge && typeof window.WiiiVisualBridge.reportResult === 'function'){{
      try {{
        window.WiiiVisualBridge.reportResult('scaffold_progress', payload || {{}}, summary || '', 'in_progress');
      }} catch (err) {{}}
    }}
  }}

  slider.addEventListener('input', function(){{
    {slider_handler_body}
  }});
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion:reduce)').matches){{
    frame(); cancelAnimationFrame(raf);
  }} else {{
    raf = requestAnimationFrame(frame);
  }}
}})();
</script>
""".strip()


# Legacy kind → second class prefix (Sprint 35e tests expect these stable
# names for tooling/CSS hooks).
_LEGACY_KIND_TO_CLASS_PREFIX: dict[str, str] = {
    "literary": "scene",
    "physics": "phys",
    "math": "math",
    "history": "hist",
    "celestial": "cel",
    "default": "default",
}


_FALLBACK_HINT = (
    "Đây là khung canvas khởi đầu — kéo thanh trượt để thấy hệ thống "
    "phản hồi theo tham số. Cho Wiii biết hiện tượng/dữ liệu/tương tác "
    "cụ thể bạn muốn dựng và mình sẽ thay phần lõi bằng nội dung "
    "đúng chủ đề."
)


def _build_shell(
    *,
    prefix: str,
    spec: dict,
    canvas_html: str,
    controls_html: str,
    script_html: str,
) -> str:
    """Compose stage + canvas + controls + hint + script into final HTML.

    Emits two stage classes: ``wiii-{primitive}-stage`` (for primitive-
    specific styling) AND ``wiii-{kind}-stage`` (for legacy kind-keyed
    tooling/tests). Both reference the same shared CSS rules.
    """
    palette = _PALETTES.get(spec.get("palette", "lab_bright"), _PALETTES["lab_bright"])
    aria = html.escape(_aria_label(spec, _short_title(spec.get("title", ""))))
    legacy_kind = _legacy_kind_for(spec)
    kind_class_prefix = _LEGACY_KIND_TO_CLASS_PREFIX.get(legacy_kind, "default")
    hint_text = spec.get("hint") or _FALLBACK_HINT
    hint_html_escaped = html.escape(hint_text)
    common_css = _common_styles(prefix, palette, kind=legacy_kind)
    # Append a kind-aliased CSS rule so `.wiii-{kind}-stage` selector
    # resolves to the same shared styles. Tests look for the substring
    # `wiii-{kind}-stage` and tooling can hook on either class.
    kind_alias_css = (
        f".wiii-{kind_class_prefix}-stage{{display:contents;}}"
    )
    return f"""
<style>
{common_css}
{kind_alias_css}
</style>
<div class="{prefix}-stage wiii-{kind_class_prefix}-stage" data-scaffold-kind="{legacy_kind}" data-scaffold-primitive="{spec.get('primitive')}" role="region" aria-label="{aria}">
  {canvas_html}
  <div class="{prefix}-controls">
    {controls_html}
  </div>
</div>
<div class="{prefix}-hint">{hint_html_escaped}</div>
{script_html}
""".strip()


# ============================================================================
# Primitive renderers (parameterized by spec)
# ============================================================================


# Extraction boundary: user-visible fallback HTML parity is the risk; rollback
# is a straight revert of the renderer-split commit if core primitives drift.
def _render_particle_field(spec: dict) -> str:
    return render_particle_field_scaffold(
        spec,
        build_shell=_build_shell,
        common_script_wrapper=_common_script_wrapper,
        short_title=_short_title,
        palettes=_PALETTES,
    )


def _render_oscillation(spec: dict) -> str:
    return render_oscillation_scaffold(
        spec,
        build_shell=_build_shell,
        common_script_wrapper=_common_script_wrapper,
        short_title=_short_title,
        palettes=_PALETTES,
    )


def _render_function_plot(spec: dict) -> str:
    return render_function_plot_scaffold(
        spec,
        build_shell=_build_shell,
        common_script_wrapper=_common_script_wrapper,
        short_title=_short_title,
        palettes=_PALETTES,
    )


def _render_timeline(spec: dict) -> str:
    return render_timeline_scaffold(
        spec,
        build_shell=_build_shell,
        common_script_wrapper=_common_script_wrapper,
        short_title=_short_title,
        palettes=_PALETTES,
    )


# Extraction boundary: user-visible fallback HTML parity is the risk; rollback
# is a straight revert of the renderer-split commit if scene/data-band drifts.
def _render_scene(spec: dict) -> str:
    return render_scene_scaffold(
        spec,
        build_shell=_build_shell,
        common_script_wrapper=_common_script_wrapper,
        short_title=_short_title,
    )


def _render_data_band(spec: dict) -> str:
    return render_data_band_scaffold(
        spec,
        build_shell=_build_shell,
        common_script_wrapper=_common_script_wrapper,
        short_title=_short_title,
    )

# ============================================================================
# Public API
# ============================================================================


_PRIMITIVE_RENDERERS = {
    PRIMITIVE_PARTICLE_FIELD: _render_particle_field,
    PRIMITIVE_OSCILLATION: _render_oscillation,
    PRIMITIVE_TIMELINE: _render_timeline,
    PRIMITIVE_FUNCTION_PLOT: _render_function_plot,
    PRIMITIVE_SCENE: _render_scene,
    PRIMITIVE_DATA_BAND: _render_data_band,
}

_RENDERER_REGISTRY = ScaffoldRendererRegistry(
    renderers=_PRIMITIVE_RENDERERS,
    fallback_renderer=_render_data_band,
)


def build_code_studio_scaffold(query: str, *, kind: str | None = None) -> str:
    """Return Canvas-first HTML scaffold satisfying tool_create_visual_code.

    The output is generated by selecting one of six universal canvas
    primitives (``particle_field``, ``oscillation``, ``timeline``,
    ``function_plot``, ``scene``, ``data_band``) and parameterising it
    with a spec extracted from the query via ``INTENT_PATTERNS``. Every
    primitive ships ``<canvas>``, ``<input type="range">``, ``aria-live``,
    ``requestAnimationFrame``, and ``WiiiVisualBridge.reportResult`` so it
    passes ``validate_code_studio_output`` for premium simulations.

    Args:
        query: User's original simulation/visualisation request.
        kind: Optional legacy kind override (``literary``, ``physics``,
            ``math``, ``history``, ``celestial``, ``default``). When set,
            forces the matching primitive even if intent extraction picks
            something else.
    """
    spec = extract_scaffold_spec(query)
    if kind:
        forced_primitive = primitive_for_legacy_kind(kind)
        if forced_primitive:
            spec = {**spec, "primitive": forced_primitive}
    return _RENDERER_REGISTRY.render(spec)


def build_scaffold_visible_caption(query: str, *, kind: str | None = None) -> str:
    """Short Vietnamese caption shown above the canvas in the chat thread."""
    spec = extract_scaffold_spec(query)
    if kind:
        forced_primitive = primitive_for_legacy_kind(kind)
        if forced_primitive:
            spec["primitive"] = forced_primitive
    primitive = spec.get("primitive", PRIMITIVE_DATA_BAND)
    return caption_for_scaffold_primitive(primitive)
