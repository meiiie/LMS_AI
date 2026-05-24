"""Direct prompt tool-context builders.

This module owns prompt text about available tools and Code Studio capability
routing. Keeping it narrow makes prompt drift easier to audit.
"""

from __future__ import annotations

from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.visual_intent_resolver import resolve_visual_intent
from app.engine.tools.code_studio_app_intent_contract import (
    resolve_code_studio_app_intent_contract,
)


def _build_direct_tools_context(
    settings_obj,
    domain_name_vi: str,
    user_role: str = "student",
    *,
    query: str = "",
    state: AgentState | None = None,
) -> str:
    """Build tools context string for direct node from settings + knowledge limits."""
    try:
        _natural_guidance = getattr(settings_obj, "enable_natural_conversation", False) is True
    except Exception:
        _natural_guidance = False

    tool_hints = []
    if settings_obj.enable_character_tools:
        tool_hints.append(
            "- tool_character_note: Ghi chu khi user chia se thong tin ca nhan MOI."
        )

    if _natural_guidance:
        tool_hints.append(
            "- tool_current_datetime: Lay ngay gio hien tai (UTC+7). "
            "Wiii luon chinh xac - khi can biet thoi gian, Wiii dung tool de dam bao."
        )
        tool_hints.append(
            "- tool_web_search: Tim kiem TONG HOP tren web. "
            "Dung cho thoi tiet, gia vang, thong tin chung khong thuoc tin tuc hay phap luat."
        )
        tool_hints.append(
            "- tool_search_news: Tim kiem TIN TUC Viet Nam. "
            "Wiii chon tool nay khi nguoi dung quan tam tin tuc, thoi su, ban tin. "
            "Nguon: VnExpress, Tuoi Tre, Thanh Nien, Dan Tri + RSS."
        )
        tool_hints.append(
            "- tool_search_legal: Tim kiem VAN BAN PHAP LUAT VN. "
            "Wiii chon tool nay khi cau hoi lien quan luat, nghi dinh, thong tu, muc phat. "
            "Nguon: Thu vien Phap luat, Cong TTDT Chinh phu."
        )
    else:
        tool_hints.append(
            "- tool_current_datetime: Lay ngay gio hien tai (UTC+7). "
            "BAT BUOC goi khi user hoi 'hom nay ngay may', 'bay gio may gio', hoac bat ky cau hoi ve thoi gian hien tai."
        )
        tool_hints.append(
            "- tool_web_search: Tim kiem TONG HOP tren web. "
            "Dung khi cau hoi KHONG thuoc tin tuc, phap luat, hay hang hai. "
            "VD: thoi tiet, gia vang, thong tin chung."
        )
        tool_hints.append(
            "- tool_search_news: Tim kiem TIN TUC Viet Nam. "
            "BAT BUOC khi user hoi 'tin tuc', 'thoi su', 'ban tin', 'su kien hom nay'. "
            "Nguon: VnExpress, Tuoi Tre, Thanh Nien, Dan Tri + RSS."
        )
        tool_hints.append(
            "- tool_search_legal: Tim kiem VAN BAN PHAP LUAT VN. "
            "BAT BUOC khi user hoi ve luat, nghi dinh, thong tu, muc phat, bo luat. "
            "Nguon: Thu vien Phap luat, Cong TTDT Chinh phu."
        )

    tool_hints.append(
        "- tool_search_maritime: Tim kiem HANG HAI quoc te. "
        "Dung khi hoi ve IMO, quy dinh quoc te, shipping news, DNV, Cuc Hang hai."
    )

    structured_visuals_enabled = getattr(settings_obj, "enable_structured_visuals", False)
    llm_code_gen_visuals = getattr(settings_obj, "enable_llm_code_gen_visuals", False)

    if structured_visuals_enabled:
        tool_hints.append(
            "- tool_generate_visual: Tao visual co cau truc (comparison, process, chart, etc.). "
            "Day la lane mac dinh cho article figure va chart runtime. Frontend render inline ngay trong stream."
        )
        if llm_code_gen_visuals:
            tool_hints.append(
                "- tool_create_visual_code: Chi dung khi user thuc su can app/widget/artifact hoac interaction bespoke. "
                "Neu user muon sua visual truoc do, reuse visual_session_id."
            )
    elif llm_code_gen_visuals:
        tool_hints.append(
            "- tool_create_visual_code: Tao visual bang HTML/CSS/SVG/JS truc tiep khi khong co visual runtime co cau truc. "
            "Viet code HTML dep, co animation khi can, responsive, va reuse visual_session_id cho follow-up."
        )
    if structured_visuals_enabled:
        tool_hints.append(
            "- LANE POLICY: article figure va chart runtime mac dinh di qua tool_generate_visual "
            "voi inline_html/SVG-first. Chi dung tool_create_visual_code khi user thuc su can "
            "app/widget/artifact hoac interaction bespoke."
        )

    parts = []
    parts.append("## CONG CU CO SAN:\n" + "\n".join(tool_hints))

    if _natural_guidance:
        parts.append(
            "\n## GIỚI HẠN KIẾN THỨC CỦA WIII:"
            "\n- Ve kien thuc cua Wiii: day la phan noi ro cach Wiii dung tri thuc san co va khi nao can tra cuu."
            "\n- Wiii co kien thuc huan luyen den dau 2024."
            "\n- Khi can thong tin moi (tin tuc, thoi tiet, gia ca, su kien sau 2024), "
            "Wiii dung tool tim kiem de dam bao chinh xac."
            "\n- Khi can biet ngay gio, Wiii dung tool_current_datetime."
        )
        parts.append(
            "\n## CACH WIII SU DUNG TOOL:"
            "\n- Wiii chon tool phu hop nhat voi noi dung cau hoi:"
            "\n   - Tin tuc / thoi su -> tool_search_news"
            "\n   - Luat / nghi dinh / muc phat -> tool_search_legal"
            "\n   - Hang hai / IMO / shipping -> tool_search_maritime"
            "\n   - Thoi tiet, gia ca, thong tin chung -> tool_web_search"
            "\n- Wiii tra cuu truoc, tra loi sau - luon dua tren du lieu thuc."
            "\n- Co the dung nhieu tool cung luc khi can."
            "\n- Wiii trung thuc: neu tool khong tra ve ket qua, Wiii noi thang."
            "\n- Wiii tap trung tra loi dung cau hoi, khong goi y chuyen chu de."
            "\n- [QUAN TRỌNG] Nếu Wiii nghĩ cần dùng tool, Wiii PHẢI emit tool_calls JSON schema — "
            "không chỉ nghĩ về tool trong thinking rồi bỏ qua. Gọi tool hay trả lời trực tiếp, không ở giữa."
            "\n- [QUAN TRỌNG] Khi người dùng nói 'Tạo file Excel/Word/HTML', Wiii PHẢI gọi tool tạo file "
            "(tool_generate_excel_file, tool_generate_word_document, tool_generate_html_file). "
            "KHÔNG CHỈ trả nội dung Markdown — người dùng cần file thật để tải về."
            "\n- [ĐIỀU KIỆN DÙNG TOOL] Chỉ dùng tool visual/chart/generation khi user EXPLICIT yêu cầu "
            "'vẽ biểu đồ', 'tạo sơ đồ', 'minh họa', 'tạo file'. KHÔNG tự động tạo visual cho câu hỏi "
            "đơn giản, triết lý, hoặc kiến thức chung (ví dụ: 'Tại sao bầu trời xanh?'). Những câu đó "
            "trả lời trực tiếp bằng text."
        )
    else:
        parts.append(
            "\n## GIỚI HẠN KIẾN THỨC (QUAN TRỌNG):"
            "\n- Kien thuc huan luyen cua ban CU - ngat vao dau nam 2024."
            "\n- Ban KHONG CO Internet truc tiep - chi co the truy cap web QUA tool_web_search."
            "\n- Ban KHONG BIET ngay gio hien tai - chi biet qua tool_current_datetime."
            "\n- Bat ky cau hoi ve su kien, tin tuc, thoi tiet, gia ca SAU nam 2024 -> PHAI goi tool."
        )
        parts.append(
            "\n## QUY TAC BAT BUOC VE TOOL:"
            "\n1. PHAI goi tool_current_datetime khi hoi ve ngay/gio. TUYET DOI KHONG tu doan."
            "\n2. CHON DUNG TOOL tim kiem:"
            "\n   - Tin tuc / thoi su / ban tin -> tool_search_news"
            "\n   - Luat / nghi dinh / thong tu / muc phat -> tool_search_legal"
            "\n   - Hang hai quoc te / IMO / shipping -> tool_search_maritime"
            "\n   - Thoi tiet, gia ca, thong tin chung -> tool_web_search"
            "\n   - Voi phan tich gia dau / Brent / WTI / OPEC+ / thi truong nang luong hien tai -> uu tien tool_web_search; KHONG nhay sang tool_search_news chi vi co chu 'hom nay'."
            "\n   - Khi snippet tu tool_web_search KHONG du chi tiet (vi du: can bang gia chinh xac, bai phan tich dai, bai bao ky thuat) -> goi tool_fetch_url(url) tren URL hua hen nhat de doc full markdown."
            "\n3. GOI TOOL TRUOC - tra loi SAU. Khong bao gio tra loi truoc roi moi goi tool."
            "\n4. Neu khong chac thong tin co con dung khong -> goi tool tim kiem de xac minh."
            "\n5. Co the goi NHIEU tool cung luc, nhung voi turn analytical thi thuong chi nen dung 3-4 truy van co chu dich de phu cac truc chinh. KHONG spam cac query gan trung nhau."
            "\n5a. [QUAN TRONG - SEARCH BROADENING] Voi cau hoi gia ca / tin tuc / su kien hien tai, "
            "DUNG luon mot loop 2-buoc: (a) goi tool_web_search voi truy van CHINH (vi du 'gia dau Brent hom nay'), "
            "DONG THOI goi them mot tool_search_news voi truy van VE BOI CANH lam dich gia (vi du 'OPEC+ tin moi nhat', "
            "'cang thang Trung Dong dau mo', 'Iran tau dau'). KHONG dung lai sau 1 truy van vi rat de bo lo tin nong."
            "\n5b. [INLINE CITATIONS - bat buoc khi co web search] "
            "Khi mention so lieu / su kien lay tu search, PHAI cite inline bang markdown link: "
            "\"Theo [Reuters](https://reuters.com/...) Brent dat $115/thung\". "
            "URLs lay tu cac dong 'URL: https://...' trong tool result. "
            "Toi thieu 1 link/doan facts. KHONG dung footnote [1] [2] kieu so vi LLM hay tao nham reference."
            "\n6. KHONG BAO GIO tu bia tin tuc, su kien, so lieu, nhiet do, do am, toc do gio."
            "\n   Neu tool that bai hoac khong goi duoc -> noi thang 'Minh khong tra cuu duoc luc nay'."
            "\n7. KHONG goi y chuyen chu de. Tra loi dung cau hoi cua user, KHONG hoi nguoc ve chu de khac."
            "\n8. [QUAN TRỌNG] Nếu bạn nghĩ rằng cần dùng tool để trả lời câu hỏi, bạn PHẢI emit tool_calls JSON schema. "
            "KHÔNG chỉ nghĩ về tool trong thinking rồi không gọi — điều này khiến người dùng chờ đợi mà không có kết quả. "
            "Nếu bạn cần tool, gọi nó. Nếu bạn không gọi tool, phải trả lời trực tiếp bằng kiến thức của mình."
            "\n9. [ĐIỀU KIỆN DÙNG TOOL] Chỉ dùng tool visual/chart/generation khi user EXPLICIT yêu cầu "
            "'vẽ biểu đồ', 'tạo sơ đồ', 'minh họa', 'tạo file'. KHÔNG tự động tạo visual cho câu hỏi "
            "đơn giản, triết lý, hoặc kiến thức chung. Những câu đó trả lời trực tiếp bằng text."
        )

    # Phase 35 — Anthropic-format SKILL injection (progressive disclosure).
    # Triggered SKILLs get full body in system prompt; non-triggered ones get
    # only metadata block (1-2 sentences). LLM uses metadata as discovery cue.
    #
    # v2.8: Wiii Pointy `@plugin-name` mention force-injects full SKILL body
    # bất kể keyword match — user explicit invocation wins over heuristic.
    if not (query or state):
        return "\n".join(parts)

    try:
        from app.engine.skills.library_loader import (
            load_library_skills as _load_lib,
            match_skills_for_query as _match_lib,
        )
        all_skills = _load_lib()
        triggered = _match_lib(query)
        triggered_names = {s.name for s in triggered}
        # Force-include skills từ @ mentions. v3.0 F3 fix: state stores
        # force_skills under state["context"]["force_skills"], NOT top
        # level. Use shared helper from tool_collection.
        force_skills_names: set[str] = set()
        if state is not None:
            try:
                from app.engine.multi_agent.tool_collection import (
                    _force_skills_from_state,
                )
                force_skills_names = _force_skills_from_state(state)
            except Exception:  # noqa: BLE001
                force_skills_names = set()
        if all_skills:
            parts.append("\n## CÁC SKILL CÓ SẴN (Anthropic format)")
            for skill in all_skills:
                if skill.name in triggered_names or skill.name in force_skills_names:
                    parts.append(skill.full_body())
                else:
                    parts.append(skill.metadata_block())
    except Exception:  # noqa: BLE001 — skill injection is best-effort
        pass

    return "\n".join(parts)


def _build_code_studio_tools_context(
    settings_obj,
    user_role: str = "student",
    query: str = "",
) -> str:
    """Build focused tool guidance for the code studio capability."""
    has_execute_python = getattr(settings_obj, "enable_code_execution", False) and user_role == "admin"
    structured_visuals_enabled = getattr(settings_obj, "enable_structured_visuals", False)
    visual_decision = resolve_visual_intent(query)

    tool_hints = []

    if structured_visuals_enabled:
        tool_hints.append(
            "- POLICY MOI: tool_generate_visual la primary lane cho article figure va chart runtime, "
            "uu tien inline_html/SVG-first va chi fallback sang structured spec khi can. "
            "tool_create_visual_code chi danh cho simulation, mini tool, widget, app, hoac artifact code-centric."
        )

    if has_execute_python:
        tool_hints.append(
            "- tool_execute_python: Chay Python trong sandbox de tinh toan, phan tich, tao bieu do, va sinh artifact that. "
            "Khi lam chart/plot/visualization, UU TIEN dung tool nay voi matplotlib/seaborn de luu ra file PNG that. "
            "Day la cong cu chinh cho moi yeu cau 've bieu do', 'plot', 'chart data'."
        )

    tool_hints += [
        "- tool_generate_html_file: Tao file HTML hoan chinh khi user can landing page, microsite, email template, web preview, hoac bat ky artifact HTML nao.",
        "- tool_generate_excel_file: Tao file Excel (.xlsx) tu du lieu bang khi user can spreadsheet hoac bang tong hop de tai xuong.",
        "- tool_generate_word_document: Tao file Word (.docx) tu noi dung co cau truc khi user can memo, report, proposal, hoac handout.",
    ]

    if (
        structured_visuals_enabled
        and visual_decision.force_tool
        and visual_decision.presentation_intent == "chart_runtime"
    ):
        tool_hints.append(
            "- tool_generate_interactive_chart: KHONG phai lua chon chinh cho query hien tai. "
            "Chi dung khi user can dashboard so hoc / hover tooltip / raw numeric chart. "
            "Neu chart dung de giai thich khai niem, co che, trade-off, hoac so sanh -> dung tool_generate_visual."
        )
    else:
        tool_hints.append(
            "- tool_generate_interactive_chart: TAO BIEU DO TUONG TAC (bar, line, pie, doughnut, radar) "
            "voi Chart.js cho dashboard du lieu so hoc, hover tooltip, va metric widgets. "
            "UU TIEN tool nay khi user can data chart tuong tac don le. "
            "Tra ve ```widget code block - FE tu render."
        )

    if structured_visuals_enabled:
        llm_code_gen = getattr(settings_obj, "enable_llm_code_gen_visuals", False)
        tool_hints.append(
            "- PRIMARY POLICY: tool_generate_visual la lane mac dinh cho article_figure va chart_runtime. "
            "Dung no de sinh HTML/SVG truc tiep theo kieu LLM-first, uu tien SVG-first cho comparison, process, "
            "architecture, concept, infographic, timeline, chart benchmark, va visual giai thich."
        )
        tool_hints.append(
            "- tool_create_visual_code CHI dung cho code_studio_app hoac artifact: simulation, quiz, search/code widget, mini tool, HTML app, document, app code-centric."
        )
        tool_hints.append(
            "- CHART RUNTIME: khong tao div-bars demo thu cong cho chart thong thuong. "
            "Neu can chart widget code-centric, dung SVG/Canvas/Chart.js voi axis, legend, units, source, va takeaway."
        )
        if llm_code_gen:
            if visual_decision.presentation_intent in {"code_studio_app", "artifact"}:
                app_contract = resolve_code_studio_app_intent_contract(
                    presentation_intent=visual_decision.presentation_intent,
                    studio_lane=visual_decision.studio_lane or "",
                    artifact_kind=visual_decision.artifact_kind or "",
                    requested_visual_type=visual_decision.visual_type or "",
                    app_category=getattr(visual_decision, "app_category", ""),
                    user_query=query,
                    planning_profile=visual_decision.planning_profile,
                )
                tool_hints.append(
                    "- tool_create_visual_code: TOOL CHINH CHO QUERY NAY. "
                    "Dung no de tao app/widget/artifact code-centric voi host-owned shell, body logic ro rang, va patch cung session."
                )
                tool_hints.extend(app_contract.prompt_lines())
                tool_hints.append(
                    "- DESIGN: App/widget can su dung shell cua host, controls gon, va feedback bridge ro rang. "
                    "Khong tao dashboard/card loe loet neu bai toan la app inline trong chat."
                )
                tool_hints.append(
                    "- QUALITY: Tach ro state/data, render surface, controls, va feedback bridge. "
                    "Khong hardcode minh hoa kieu div-bars neu query la chart chuan."
                )
            else:
                tool_hints.append(
                    "- Du local co bat llm code gen, query hien tai VAN UU TIEN tool_generate_visual cho article_figure/chart_runtime. "
                    "Chi nang cap sang tool_create_visual_code neu interaction depth that su can app/widget/artifact."
                )
                tool_hints.append(
                    "- Neu can visual bespoke, van phai giu article-first, host-governed runtime, khong day query giai thich thong thuong vao Code Studio."
                )
        else:
            tool_hints.append(
                "- tool_generate_visual: TOOL CHINH - tao 2-3 inline figures cho moi giai thich. "
                "Types: comparison, process, matrix, architecture, concept, infographic, chart, timeline, map_lite. "
                "GOI NHIEU LAN (2-3 calls) de tao multi-figure explanation. "
                "Frontend render inline ngay khi stream, khong can copy payload."
            )
        tool_hints.append(
            "- Follow-up visual edits: neu user muon chinh visual vua co, reuse visual_session_id va set operation='patch'."
        )

    if has_execute_python:
        tool_hints.append(
            "- tool_generate_mermaid / tool_generate_chart: Du phong cho bieu do khi sandbox khong kha dung. "
            "Chi dung khi khong the chay tool_execute_python. Output la Mermaid syntax (SVG), khong phai PNG that."
        )
    else:
        tool_hints.append(
            "- tool_generate_mermaid / tool_generate_chart: Tao so do, bieu do cau truc (flowchart, sequence, pie chart) "
            "bang Mermaid syntax. FE se render thanh SVG. Chi dung cho so do/quy trinh, KHONG cho data visualization."
        )

    if (
        user_role == "admin"
        and getattr(settings_obj, "enable_browser_agent", False)
        and getattr(settings_obj, "enable_privileged_sandbox", False)
        and getattr(settings_obj, "sandbox_provider", "") == "opensandbox"
        and getattr(settings_obj, "sandbox_allow_browser_workloads", False)
    ):
        tool_hints.append(
            "- tool_browser_snapshot_url: Mo trang web trong browser sandbox de xem render that, chup snapshot, va xac minh artifact front-end."
        )

    priority_rules = [
        "## NGUYEN TAC UU TIEN:",
        "- Uu tien tao output THAT (file, PNG, HTML, widget) thay vi chi mo ta bang loi.",
        "- Voi yeu cau 've bieu do / chart / thong ke / so lieu': "
        + (
            (
                "neu chart dung de GIAI THICH khai niem/co che/trade-off -> goi tool_generate_visual (type=chart, comparison, process...). "
                "Chi dung tool_execute_python hoac tool_generate_interactive_chart cho data dashboard / raw numeric plots khi hover, tooltip, metric widgets la muc tieu chinh."
                if structured_visuals_enabled
                else "goi tool_execute_python neu can tinh toan phuc tap, HOAC goi tool_generate_interactive_chart neu da co san labels + data."
            )
            if has_execute_python
            else (
                "neu chart dung de GIAI THICH khai niem/co che/trade-off -> goi tool_generate_visual. "
                "Chi dung tool_generate_interactive_chart cho data dashboard / numeric chart. "
                "Chi dung tool_generate_mermaid cho so do/quy trinh (flowchart, mindmap), KHONG cho data chart."
                if structured_visuals_enabled
                else "goi tool_generate_interactive_chart (uu tien) de tao bieu do tuong tac inline. Chi dung tool_generate_mermaid cho so do/quy trinh."
            )
        ),
        "- Voi yeu cau 'tao trang web / HTML / landing page': luon goi tool_generate_html_file.",
        "- Voi yeu cau 'tao file Excel / spreadsheet': luon goi tool_generate_excel_file.",
        "- Voi yeu cau 'tao file Word / bao cao / report': luon goi tool_generate_word_document.",
        # Action-Forcing Directive: LLM must not just output markdown when user asks for file
        "\n[QUAN TRỌNG] Khi người dùng nói 'Tạo file', 'Xuất file', 'Tải về', "
        "bạn KHÔNG ĐƯỢC chỉ trả nội dung dưới dạng Markdown. "
        "Bạn PHẢI gọi tool tương ứng (tool_generate_excel_file, tool_generate_word_document, tool_generate_html_file) "
        "để tạo file thật. Nếu bạn có dữ liệu rồi, hãy gọi tool. KHÔNG chỉ mô tả dữ liệu bằng text.",
        "\n[ĐIỀU KIỆN] KHÔNG tự động tạo visual/chart cho câu hỏi đơn giản, triết lý, hoặc kiến thức chung. "
        "Chỉ tạo visual khi user EXPLICIT yêu cầu 'vẽ', 'minh họa', 'sơ đồ', 'biểu đồ'.",
        "- Voi yeu cau GIAI THICH khai niem / SO SANH / KIEN TRUC: goi "
        + ("tool_generate_visual 2-3 LAN de tao multi-figure" if structured_visuals_enabled else "tool_generate_visual")
        + ".",
        (
            "- SAU KHI goi tool_generate_interactive_chart: COPY NGUYEN VAN widget code block vao response."
            if not structured_visuals_enabled
            else "- SAU KHI goi tool_generate_visual: khong copy payload JSON vao answer. Viet bridge prose + takeaway."
        ),
        "- Khi sandbox gap loi ket noi, noi ro gioi han va KHONG gia vo da chay code.",
        "- KHONG route chart giai thich thong thuong vao Code Studio neu chart runtime/article figure da du kha nang.",
    ]

    sections = ["## CODE STUDIO TOOLKIT:", *tool_hints, "", *priority_rules]
    sections.append("")
    sections.append(
        "## WIII CHARACTER trong visual:\n"
        "Visual cua Wiii khong chi la code - ma la cong cu day hoc. "
        "Mo dau bang scene giup nguoi hoc 'cam' duoc co che truoc khi hieu ly thuyet. "
        "Readouts khong chi hien so - ma kem ghi chu ngan giup nguoi hoc doc gia tri. "
        "Controls cho phep nguoi hoc tu kham pha, khong phai chi xem. "
        "Ngon ngu Tieng Viet trong UI: labels, tooltips, readout names."
    )

    if getattr(settings_obj, "enable_llm_code_gen_visuals", False):
        sections.append("")
        sections.append(
            "## CODE FORMAT cho tool_create_visual_code:\n"
            "code_html bat dau bang `<!-- STATE MODEL: ... RENDER SURFACE: ... CONTROLS: ... READOUTS: ... -->` "
            "roi `<style>` voi CSS variables (--bg, --fg, --accent, --surface, --border), "
            "roi HTML content, roi `<script>` cuoi cung.\n"
            "KHONG dung DOCTYPE, html, head, body tags. Fragment only.\n"
            "LUON embed data truc tiep trong code. KHONG BAO GIO dung placeholder nhu 'No data provided' hay de trong.\n"
            "KHONG dung overflow:hidden voi border-radius tren text container - se cat chu. Dung overflow:clip hoac overflow:visible.\n"
            "Simulation can: Canvas + requestAnimationFrame + deltaTime + controls (sliders) + readouts (live values) + WiiiVisualBridge.reportResult().\n"
            "Chat luong se duoc cham diem tu dong. Score < 6/10 se bi tu choi va yeu cau viet lai."
        )

    return "\n".join(sections)
