/**
 * Shared label mappings for the reasoning rail components.
 * Extracted from ThinkingBlock + ToolExecutionStrip + ActionText
 * to eliminate duplication (WAVE-004).
 * Sprint 231: Fixed Vietnamese diacritics (was ASCII Vietnamese).
 */

/** Vietnamese labels for tool names used across reasoning UI. */
export const TOOL_LABELS: Record<string, string> = {
  tool_knowledge_search: "Tra cứu kiến thức",
  tool_maritime_search: "Tra cứu hàng hải",
  tool_web_search: "Tìm kiếm web",
  tool_search_news: "Tìm tin tức",
  tool_search_legal: "Tra cứu pháp luật",
  tool_search_maritime: "Tìm kiếm hàng hải",
  tool_fetch_url: "Đọc chi tiết URL",
  tool_current_weather: "Tra thời tiết",
  current_weather: "Tra thời tiết",
  tool_current_datetime: "Thời gian hiện tại",
  tool_calculator: "Máy tính",
  tool_think: "Suy nghĩ",
  tool_report_progress: "Báo tiến độ",
  tool_save_user_info: "Lưu thông tin",
  tool_get_user_info: "Truy xuất thông tin",
  tool_execute_python: "Chạy mã Python",
  tool_browser_snapshot_url: "Mở trang và chụp nhanh",
  tool_generate_html_file: "Tạo HTML",
  tool_generate_excel_file: "Tạo Excel",
  tool_generate_word_document: "Tạo Word",
  tool_generate_visual: "Dựng visual giải thích",
  tool_generate_rich_visual: "Dựng visual giải thích",
  tool_create_visual_code: "Tạo visual code",
  tool_search_products: "Tìm sản phẩm",
  tool_search_shopping: "Tìm mua sắm",
};

/** Vietnamese labels for agent node names. */
export const NODE_LABELS: Record<string, string> = {
  supervisor: "Điều hướng",
  rag: "Tra cứu",
  rag_agent: "Tra cứu",
  tutor: "Giải thích",
  tutor_agent: "Giải thích",
  memory: "Trí nhớ",
  direct: "Trực tiếp",
  grader: "Đánh giá",
  guardian: "Kiểm duyệt",
  synthesizer: "Tổng hợp",
  search: "Đối chiếu",
  product_search: "Tìm sản phẩm",
  product_search_agent: "Đối chiếu",
  web_search: "Tìm web",
  aggregator: "Hợp nhất",
  parallel_dispatch: "Song song",
  code_studio_agent: "Xưởng mã",
};

/** Vietnamese labels for reasoning phases. */
export const PHASE_LABELS: Record<string, string> = {
  attune: "Bắt nhịp",
  clarify: "Làm rõ",
  ground: "Kiểm dữ liệu",
  verify: "Kiểm chéo",
  counterpoint: "Phản biện",
  decision: "Chọn hướng",
  synthesis: "Chốt lại",
  act: "Thực hiện",
  synthesize: "Tổng hợp",
};
