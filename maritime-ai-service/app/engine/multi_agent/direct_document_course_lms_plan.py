"""LMS-manual uploaded-document course plan builders."""

from __future__ import annotations

from typing import Any

from app.engine.multi_agent.direct_document_source_refs import _match_doc_refs


def _lms_manual_lesson(
    *,
    title: str,
    summary: str,
    activity: str,
    quick_check: str,
    refs: list[dict[str, Any]],
    duration_minutes: int = 18,
) -> dict[str, Any]:
    return {
        "title": title,
        "summary": summary,
        "activity": activity,
        "quick_check": quick_check,
        "duration_minutes": duration_minutes,
        "source_references": refs,
    }


def _build_lms_manual_course_plan(
    *,
    title_source: str,
    refs: list[dict[str, Any]],
) -> dict[str, Any]:
    chapter_specs = [
        {
            "title": "Khởi động: truy cập, đăng nhập và định hướng vai trò",
            "summary": "Giúp người học hiểu bản đồ hệ thống HoLiLiHu LMS trước khi đi vào từng vai trò.",
            "markers": ("dang nhap", "vai tro", "trang chu", "tong quan", "lms"),
            "objectives": [
                "Phân biệt luồng công khai, học viên, giảng viên và quản lý.",
                "Đăng nhập đúng tài khoản và nhận diện workspace theo vai trò.",
                "Biết nơi cần kiểm tra khi không thấy khóa học hoặc chức năng.",
            ],
            "lessons": [
                (
                    "Bản đồ HoLiLiHu LMS và các vai trò chính",
                    "Đọc hệ thống như một bản đồ: trang công khai, khu học viên, khu giảng viên và khu quản lý.",
                    "Cho học viên nối từng vai trò với 3 tác vụ thường gặp.",
                    "Khi một người dùng không thấy nút tạo khóa, cần kiểm tra điều gì trước?",
                    ("vai tro", "tong quan", "lms"),
                ),
                (
                    "Đăng nhập, xác thực và xử lý lỗi truy cập",
                    "Chuẩn hóa thao tác đăng nhập, xác minh tài khoản và nhận biết lỗi phiên đăng nhập.",
                    "Thực hành checklist: email, mật khẩu, trạng thái tài khoản, tổ chức.",
                    "Cần thu thập bằng chứng nào trước khi báo lỗi đăng nhập?",
                    ("dang nhap", "xac thuc", "tai khoan"),
                ),
                (
                    "Điều hướng theo vai trò sau khi vào hệ thống",
                    "Nhận diện đúng menu, sidebar, khóa học hiện tại và các điểm vào nhanh.",
                    "Mỗi nhóm chụp lại một đường đi đến khóa học và giải thích vì sao chọn đường đó.",
                    "Dấu hiệu nào cho thấy người dùng đang ở sai vai trò?",
                    ("menu", "sidebar", "vai tro", "dieu huong"),
                ),
            ],
        },
        {
            "title": "Hành trình học viên: học bài, video tương tác và tiến độ",
            "summary": "Biến phần hướng dẫn học viên thành kịch bản học thật: vào khóa, học bài, làm quiz và theo dõi tiến độ.",
            "markers": ("hoc vien", "video", "quiz", "tien do", "offline"),
            "objectives": [
                "Mở khóa học và đi qua một bài học có nhiều loại nội dung.",
                "Sử dụng video tương tác, tài liệu, quiz và ghi chú đúng ngữ cảnh.",
                "Tự kiểm tra tiến độ, lỗi thường gặp và chế độ học trên thiết bị di động.",
            ],
            "lessons": [
                (
                    "Từ danh sách khóa học đến bài học đầu tiên",
                    "Học viên tìm khóa học, đọc mô tả, vào chương và chọn bài học cần học.",
                    "Mô phỏng một học viên mới nhận lớp và cần tìm bài đầu tiên trong 2 phút.",
                    "Nếu học viên đã ghi danh nhưng không thấy khóa, cần kiểm tra những điểm nào?",
                    ("hoc vien", "khoa hoc", "ghi danh"),
                ),
                (
                    "Học với video, tài liệu và nội dung tương tác",
                    "Khai thác video tương tác, tài liệu đính kèm và các khối nội dung trong một bài học.",
                    "Đánh dấu các điểm cần dừng video để hỏi hoặc kiểm tra nhanh.",
                    "Video tương tác khác video thường ở điểm nào trong trải nghiệm học?",
                    ("video", "tuong tac", "tai lieu"),
                ),
                (
                    "Quiz, bài tập và phản hồi sau khi học",
                    "Hoàn thành kiểm tra, đọc phản hồi và dùng kết quả để quay lại đúng bài học.",
                    "Thiết kế một câu hỏi kiểm tra nhanh cho cuối bài.",
                    "Khi kết quả quiz thấp, học viên nên quay lại thông tin nào?",
                    ("quiz", "bai tap", "kiem tra"),
                ),
                (
                    "Theo dõi tiến độ, học offline và xử lý sự cố học tập",
                    "Đọc thanh tiến độ, trạng thái hoàn thành và các vấn đề thường gặp trên mobile/offline.",
                    "Lập checklist tự xử lý trước khi gửi hỗ trợ.",
                    "Cần gửi ảnh chụp màn hình nào để hỗ trợ kiểm tra nhanh hơn?",
                    ("tien do", "offline", "mobile", "su co"),
                ),
            ],
        },
        {
            "title": "Tác nghiệp giảng viên: thiết kế và soạn khóa học",
            "summary": "Đây là trục trọng tâm cho giáo viên: từ ý tưởng khóa học đến chương, bài, tài liệu, video và quiz.",
            "markers": ("giang vien", "tao khoa", "chuong", "bai hoc", "xuat ban"),
            "objectives": [
                "Tạo khóa học có tiêu đề, mô tả và mục tiêu đủ rõ để duyệt.",
                "Chia nội dung thành chương/bài theo logic học tập thay vì chỉ chép mục lục.",
                "Thêm video, tài liệu và quiz với checklist kiểm tra trước khi gửi duyệt.",
            ],
            "lessons": [
                (
                    "Tạo khóa học mới và viết thông tin khóa học",
                    "Giảng viên nhập tiêu đề, mô tả, mục tiêu, đối tượng và thông tin cần thiết trước khi soạn bài.",
                    "Biến một mô tả mơ hồ thành mô tả khóa học có kết quả học tập đo được.",
                    "Một mô tả khóa học đủ duyệt cần trả lời những câu hỏi nào?",
                    ("tao khoa", "thong tin khoa", "muc tieu"),
                ),
                (
                    "Chia chương/bài theo năng lực cần đạt",
                    "Sắp xếp chương và bài theo hành trình học, tránh bê nguyên mục lục nếu không tạo được tiến trình.",
                    "Từ một tài liệu dài, nhóm thành 4-6 chương có nhịp học rõ.",
                    "Dấu hiệu nào cho thấy một chương đang quá rộng?",
                    ("chuong", "bai hoc", "cau truc"),
                ),
                (
                    "Thêm video, tài liệu và nội dung tương tác",
                    "Gắn đúng loại tài nguyên vào bài học, đặt tên rõ và kiểm tra khả năng xem lại của học viên.",
                    "Soạn checklist trước khi upload video/tài liệu vào bài.",
                    "Tài liệu đính kèm cần có tên và mô tả như thế nào để học viên không bị lạc?",
                    ("video", "tai lieu", "upload", "tuong tac"),
                ),
                (
                    "Soạn quiz và kiểm tra chất lượng trước khi gửi duyệt",
                    "Thiết kế kiểm tra nhanh, câu hỏi tổng kết và kiểm tra trạng thái xuất bản một cách an toàn.",
                    "Viết 3 câu hỏi đo đúng mục tiêu học tập của bài.",
                    "Vì sao quiz không nên được publish trực tiếp khi chưa xem preview?",
                    ("quiz", "kiem tra", "xuat ban", "duyet"),
                ),
            ],
        },
        {
            "title": "Quản lý và vận hành: duyệt khóa, người dùng và chất lượng",
            "summary": "Dành cho người quản lý hoặc tổ chuyên trách vận hành LMS để đảm bảo khóa học lên production an toàn.",
            "markers": ("quan ly", "admin", "duyet", "nguoi dung", "bao cao"),
            "objectives": [
                "Hiểu trách nhiệm duyệt khóa và kiểm tra trước khi mở cho học viên.",
                "Theo dõi người dùng, vai trò, tiến độ và báo cáo vận hành.",
                "Biết khi nào cần trả khóa về cho giảng viên chỉnh sửa.",
            ],
            "lessons": [
                (
                    "Duyệt khóa học theo checklist chất lượng",
                    "Quản lý kiểm tra mục tiêu, chương/bài, nội dung, quiz, tài liệu và khả năng học thật.",
                    "Chấm một khóa mẫu theo checklist duyệt.",
                    "Ba lỗi nào nên trả về cho giảng viên thay vì duyệt ngay?",
                    ("duyet", "chat luong", "xuat ban"),
                ),
                (
                    "Quản lý người dùng, vai trò và quyền truy cập",
                    "Xác minh vai trò, lớp/khóa, tổ chức và phạm vi truy cập để tránh nhầm quyền.",
                    "Vẽ ma trận vai trò - quyền cho một lớp học mẫu.",
                    "Vì sao đổi vai trò cần kiểm tra lại ngay trên phiên kế tiếp?",
                    ("nguoi dung", "vai tro", "quyen"),
                ),
                (
                    "Theo dõi tiến độ, báo cáo và tín hiệu rủi ro",
                    "Đọc tiến độ học tập, phát hiện bài bị bỏ qua, quiz bất thường hoặc lớp ít tương tác.",
                    "Tạo 3 tín hiệu cần theo dõi hằng tuần cho một khóa mới.",
                    "Tín hiệu nào cho thấy nội dung cần được chỉnh lại chứ không phải chỉ nhắc học viên?",
                    ("tien do", "bao cao", "analytics"),
                ),
            ],
        },
        {
            "title": "Triển khai lớp học thật và xử lý sự cố",
            "summary": "Khóa lại bằng checklist vận hành: chuẩn bị trước lớp, hỗ trợ trong lớp và cải tiến sau lớp.",
            "markers": ("troubleshooting", "su co", "checklist", "ho tro", "offline"),
            "objectives": [
                "Chuẩn bị khóa học trước ngày mở lớp bằng checklist có thể kiểm chứng.",
                "Xử lý các lỗi phổ biến: đăng nhập, không thấy khóa, video/tài liệu, quiz và tiến độ.",
                "Thu thập bằng chứng hỗ trợ và cải tiến khóa sau khi chạy thật.",
            ],
            "lessons": [
                (
                    "Checklist trước khi mở lớp",
                    "Kiểm tra người học, nội dung, tài liệu, quiz, quyền truy cập và kênh hỗ trợ trước ngày học.",
                    "Chạy thử một học viên mẫu từ đăng nhập đến hoàn thành bài đầu tiên.",
                    "Điểm nào phải kiểm tra trên tài khoản học viên thật, không chỉ trên tài khoản giảng viên?",
                    ("checklist", "mo lop", "hoc vien"),
                ),
                (
                    "Xử lý lỗi đăng nhập, video, tài liệu và quiz",
                    "Chuẩn hóa cách thu thập thông tin lỗi để hỗ trợ nhanh và không đoán mò.",
                    "Viết mẫu ticket hỗ trợ có đủ bằng chứng.",
                    "Một ticket thiếu ảnh/video lỗi sẽ làm chậm hỗ trợ ở bước nào?",
                    ("su co", "dang nhap", "video", "quiz"),
                ),
                (
                    "Đánh giá sau lớp và cải tiến khóa học",
                    "Dùng phản hồi, tiến độ và lỗi phát sinh để cập nhật tài liệu, quiz và hướng dẫn.",
                    "Chọn 3 cải tiến sau buổi học đầu tiên và gắn với bằng chứng.",
                    "Khi nào nên sửa nội dung bài học thay vì chỉ thêm thông báo?",
                    ("phan hoi", "cai tien", "bao cao"),
                ),
            ],
        },
    ]

    chapters: list[dict[str, Any]] = []
    for chapter_index, chapter in enumerate(chapter_specs, start=1):
        chapter_refs = _match_doc_refs(
            refs,
            chapter["markers"],
            fallback_title=title_source,
            chapter_index=chapter_index,
        )
        lessons = []
        for lesson_index, (title, summary, activity, quick_check, markers) in enumerate(
            chapter["lessons"],
            start=1,
        ):
            lessons.append(
                _lms_manual_lesson(
                    title=title,
                    summary=summary,
                    activity=activity,
                    quick_check=quick_check,
                    refs=_match_doc_refs(
                        refs,
                        markers,
                        fallback_title=title_source,
                        chapter_index=chapter_index,
                        lesson_index=lesson_index,
                    ),
                )
            )
        chapters.append(
            {
                "title": chapter["title"],
                "summary": chapter["summary"],
                "learning_objectives": chapter["objectives"],
                "lessons": lessons,
                "source_references": chapter_refs,
            }
        )

    lesson_count = sum(len(chapter.get("lessons", [])) for chapter in chapters)

    return {
        "title": "Khai thác HoLiLiHu LMS từ tài liệu hướng dẫn",
        "description": (
            "Khóa học chuyển tài liệu hướng dẫn HoLiLiHu LMS thành lộ trình thực hành "
            "cho học viên, giảng viên và quản lý. Cấu trúc ưu tiên thao tác thật, "
            "kiểm tra chất lượng và nguồn trích dẫn để giáo viên xác minh trước khi áp dụng."
        ),
        "audience": "Giảng viên, trợ giảng, quản lý đào tạo và học viên cần sử dụng HoLiLiHu LMS.",
        "duration": f"{len(chapters)} chương, {lesson_count} bài, triển khai trong 3-5 buổi thực hành.",
        "chapters": chapters,
        "assessment_plan": [
            "Mỗi chương có câu hỏi kiểm tra nhanh gắn với thao tác thật.",
            "Cuối khóa yêu cầu người học hoàn thành một kịch bản: tạo/hoặc tham gia một khóa mẫu, học bài, kiểm tra tiến độ và xử lý một lỗi giả lập.",
            "Giảng viên dùng nguồn trích dẫn trong bản xem trước để đối chiếu từng chương trước khi áp dụng vào LMS.",
        ],
        "implementation_checklist": [
            "Xác minh tên khóa, mô tả, mục tiêu và đối tượng trước khi tạo dữ liệu LMS.",
            "Giữ mọi thay đổi ở trạng thái draft; không publish tự động.",
            "Sau khi apply, giáo viên rà lại từng chapter/lesson, thêm tài nguyên thật và gửi duyệt theo quy trình LMS.",
        ],
        "source_document_title": title_source,
    }


__all__ = ["_build_lms_manual_course_plan", "_lms_manual_lesson"]
