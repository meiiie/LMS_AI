"""Deterministic intent and spec extraction for Code Studio scaffolds."""

from __future__ import annotations

import unicodedata

from app.engine.multi_agent.code_studio_scaffold_contract import (
    PRIMITIVE_DATA_BAND,
    PRIMITIVE_FUNCTION_PLOT,
    PRIMITIVE_OSCILLATION,
    PRIMITIVE_PARTICLE_FIELD,
    PRIMITIVE_SCENE,
    PRIMITIVE_TIMELINE,
    legacy_kind_for_primitive,
)
from app.engine.multi_agent.code_studio_scaffold_quality import (
    apply_scaffold_quality_gate,
)

# The data below is intentionally deterministic and I/O-free. It decides
# what primitive to render; renderer modules own HTML/CSS/JS output.

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
    return legacy_kind_for_primitive(spec.get("primitive", PRIMITIVE_DATA_BAND))
