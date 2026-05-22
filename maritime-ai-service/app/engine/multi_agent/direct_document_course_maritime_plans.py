"""Maritime uploaded-document course plan builders."""

from __future__ import annotations

from typing import Any

from app.engine.multi_agent.direct_document_course_lms_plan import _lms_manual_lesson
from app.engine.multi_agent.direct_document_source_refs import _match_doc_refs


def _build_maritime_vessel_management_course_plan(
    *,
    title_source: str,
    refs: list[dict[str, Any]],
) -> dict[str, Any]:
    chapter_specs = [
        {
            "title": "Bối cảnh số hóa vận hành và hồ sơ tàu thủy",
            "summary": "Đặt vấn đề quản lý vận hành và hồ sơ tàu trong doanh nghiệp vận tải biển.",
            "markers": ("gioi thieu", "bai toan", "qpec", "van tai bien", "ho so tau"),
            "objectives": [
                "Giải thích được vì sao doanh nghiệp vận tải biển cần số hóa hồ sơ tàu.",
                "Nhận diện các nhóm người dùng và điểm đau trong quản lý vận hành.",
                "Xác định phạm vi khóa học dựa trên tài liệu nghiên cứu.",
            ],
            "lessons": [
                (
                    "Bài toán quản lý vận hành trong doanh nghiệp vận tải biển",
                    "Tổng hợp bối cảnh, mục tiêu nghiên cứu và nhu cầu quản lý đội tàu.",
                    "Người học lập bản đồ vấn đề: ai dùng hệ thống, dùng để giải quyết việc gì.",
                    "Nếu không số hóa hồ sơ tàu, rủi ro vận hành lớn nhất là gì?",
                ),
                (
                    "Phạm vi hồ sơ tàu và luồng thông tin cần quản lý",
                    "Nhận diện hồ sơ, giấy tờ, chứng chỉ, nhật ký và dữ liệu vận hành liên quan đến tàu.",
                    "Tạo checklist 10 loại thông tin cần có trong hồ sơ tàu.",
                    "Một hồ sơ tàu đủ tốt cần trả lời được những câu hỏi nào?",
                ),
                (
                    "Các bên liên quan: doanh nghiệp, tàu, bờ và người khai thác",
                    "Phân tích vai trò của bộ phận bờ, tàu, quản lý và người vận hành hệ thống.",
                    "Vẽ sơ đồ stakeholder và quyền truy cập dữ liệu tối thiểu.",
                    "Vai trò nào cần được phân quyền chặt nhất, vì sao?",
                ),
            ],
        },
        {
            "title": "Khảo sát nghiệp vụ và yêu cầu hệ thống",
            "summary": "Chuyển khảo sát hiện trạng thành yêu cầu chức năng và phi chức năng.",
            "markers": ("khao sat", "yeu cau", "nghiep vu", "bieu mau", "co cau to chuc"),
            "objectives": [
                "Tách được yêu cầu nghiệp vụ khỏi mô tả hiện trạng.",
                "Mô hình hóa các quy trình chính trong vận hành và hồ sơ tàu.",
                "Viết được yêu cầu kiểm chứng được cho hệ thống.",
            ],
            "lessons": [
                (
                    "Đọc khảo sát hiện trạng như một bản yêu cầu nghiệp vụ",
                    "Rút ra quy trình, biểu mẫu và vấn đề đang tồn tại từ phần khảo sát.",
                    "Đánh dấu các câu trong tài liệu có thể chuyển thành requirement.",
                    "Một yêu cầu tốt khác một mô tả hiện trạng ở điểm nào?",
                ),
                (
                    "Quy trình nghiệp vụ quản lý vận hành và hồ sơ tàu",
                    "Mô tả các bước nghiệp vụ từ cập nhật hồ sơ đến theo dõi tình trạng vận hành.",
                    "Dựng flow ngắn cho một nghiệp vụ: thêm hồ sơ tàu hoặc cập nhật chứng chỉ.",
                    "Bước nào trong quy trình cần kiểm soát/audit rõ nhất?",
                ),
                (
                    "Từ biểu mẫu giấy sang dữ liệu có cấu trúc",
                    "Chuyển các giấy tờ và biểu mẫu thành trường dữ liệu, ràng buộc và trạng thái.",
                    "Chọn một biểu mẫu trong tài liệu và thiết kế schema tối thiểu.",
                    "Trường dữ liệu nào bắt buộc phải chuẩn hóa để tìm kiếm/báo cáo?",
                ),
            ],
        },
        {
            "title": "Phân tích chức năng và luồng dữ liệu",
            "summary": "Biến nghiệp vụ thành chức năng hệ thống, sơ đồ phân rã và luồng dữ liệu.",
            "markers": ("phan tich chuc nang", "so do phan ra", "luong du lieu", "muc ngu canh", "muc dinh"),
            "objectives": [
                "Đọc được sơ đồ phân rã chức năng và sơ đồ luồng dữ liệu.",
                "Liên kết chức năng với tác nhân và dữ liệu đầu vào/đầu ra.",
                "Phát hiện điểm thiếu trong luồng dữ liệu trước khi thiết kế giao diện.",
            ],
            "lessons": [
                (
                    "Sơ đồ phân rã chức năng cho hệ thống quản lý tàu",
                    "Tổ chức các chức năng lớn thành nhóm dễ triển khai và kiểm thử.",
                    "So sánh cây chức năng trong tài liệu với một backlog sản phẩm.",
                    "Chức năng nào là lõi vận hành, chức năng nào là hỗ trợ?",
                ),
                (
                    "Sơ đồ luồng dữ liệu mức ngữ cảnh và mức đỉnh",
                    "Giải thích dữ liệu đi qua hệ thống giữa người dùng, kho dữ liệu và báo cáo.",
                    "Vẽ lại một luồng dữ liệu bằng ngôn ngữ người dùng cuối.",
                    "Một luồng dữ liệu thiếu kho lưu trữ sẽ gây lỗi thiết kế nào?",
                ),
                (
                    "Kiểm tra nhất quán giữa nghiệp vụ và chức năng",
                    "Đối chiếu yêu cầu, chức năng, dữ liệu và báo cáo để tránh bỏ sót.",
                    "Tạo ma trận traceability từ yêu cầu sang chức năng.",
                    "Khi nào cần tách một chức năng thành hai module riêng?",
                ),
            ],
        },
        {
            "title": "Thiết kế dữ liệu và hồ sơ tàu",
            "summary": "Thiết kế thực thể, thuộc tính, quan hệ và bảng dữ liệu cho hồ sơ tàu.",
            "markers": ("thiet ke co so du lieu", "thuc the", "thuoc tinh", "lien ket thuc the", "bang du lieu"),
            "objectives": [
                "Nhận diện được các thực thể cốt lõi trong hồ sơ tàu.",
                "Thiết kế quan hệ dữ liệu phục vụ vận hành và truy xuất hồ sơ.",
                "Kiểm tra dữ liệu theo tiêu chí toàn vẹn, tìm kiếm và báo cáo.",
            ],
            "lessons": [
                (
                    "Thực thể cốt lõi: tàu, hồ sơ, chứng chỉ, thiết bị và chuyến biển",
                    "Tách các khái niệm nghiệp vụ thành thực thể dữ liệu có quan hệ rõ ràng.",
                    "Lập danh sách entity và thuộc tính bắt buộc cho một tàu.",
                    "Entity nào nên là trung tâm của mô hình dữ liệu, vì sao?",
                ),
                (
                    "Sơ đồ liên kết thực thể và ràng buộc dữ liệu",
                    "Đọc ERD và xác định quan hệ một-nhiều, nhiều-nhiều, bắt buộc/tùy chọn.",
                    "Kiểm tra một quan hệ dữ liệu bằng ví dụ tàu có nhiều chứng chỉ.",
                    "Ràng buộc nào giúp ngăn nhập hồ sơ tàu sai?",
                ),
                (
                    "Bảng dữ liệu và khả năng báo cáo vận hành",
                    "Đánh giá bảng dữ liệu theo nhu cầu lọc, cảnh báo, thống kê và truy xuất.",
                    "Thiết kế một truy vấn báo cáo hết hạn giấy tờ/chứng chỉ.",
                    "Nếu muốn cảnh báo tự động, bảng nào cần trường ngày hiệu lực?",
                ),
            ],
        },
        {
            "title": "Thiết kế hệ thống tàu, hệ thống bờ và trải nghiệm người dùng",
            "summary": "Kết nối dữ liệu, chức năng, phân quyền và giao diện theo bối cảnh tàu/bờ.",
            "markers": ("he thong tau", "he thong bo", "giao dien", "phan quyen", "quan tri"),
            "objectives": [
                "Phân biệt nhu cầu sử dụng trên tàu và trên bờ.",
                "Thiết kế giao diện theo vai trò và quy trình nghiệp vụ.",
                "Đặt nguyên tắc phân quyền, audit và an toàn dữ liệu.",
            ],
            "lessons": [
                (
                    "Luồng làm việc giữa hệ thống tàu và hệ thống bờ",
                    "Mô tả cách dữ liệu vận hành được nhập, đồng bộ, kiểm tra và khai thác.",
                    "Phác thảo một workflow từ tàu gửi cập nhật đến bờ xác nhận.",
                    "Điểm nào trong workflow cần xử lý offline hoặc chậm mạng?",
                ),
                (
                    "Giao diện theo vai trò và tác vụ",
                    "Biến chức năng thành màn hình, menu, form và trạng thái dễ dùng.",
                    "Thiết kế wireframe nhanh cho màn hình hồ sơ tàu.",
                    "Giao diện nào cần ưu tiên giảm lỗi nhập liệu?",
                ),
                (
                    "Phân quyền, audit và bảo vệ hồ sơ tàu",
                    "Xác định quyền xem/sửa/xóa/xuất báo cáo theo vai trò.",
                    "Tạo bảng phân quyền tối thiểu cho quản lý, nhân viên bờ và người trên tàu.",
                    "Vì sao xóa hồ sơ tàu cần cơ chế audit hoặc soft delete?",
                ),
            ],
        },
        {
            "title": "Triển khai, kiểm thử và đánh giá hiệu quả",
            "summary": "Đưa thiết kế vào môi trường doanh nghiệp, kiểm thử và đo giá trị vận hành.",
            "markers": ("trien khai", "kiem thu", "danh gia", "ket qua", "ket luan", "huong phat trien"),
            "objectives": [
                "Lập kế hoạch triển khai hệ thống theo giai đoạn an toàn.",
                "Thiết kế kiểm thử dựa trên nghiệp vụ và dữ liệu thật.",
                "Đánh giá hiệu quả bằng chỉ số vận hành và chất lượng hồ sơ.",
            ],
            "lessons": [
                (
                    "Kế hoạch triển khai trong doanh nghiệp vận tải biển",
                    "Chia triển khai thành các bước: chuẩn hóa dữ liệu, đào tạo, chạy thử và chuyển đổi.",
                    "Lập checklist trước khi đưa hệ thống vào dùng thật.",
                    "Rủi ro chuyển đổi dữ liệu nào cần kiểm soát đầu tiên?",
                ),
                (
                    "Kiểm thử nghiệp vụ và dữ liệu hồ sơ tàu",
                    "Xây dựng test case từ quy trình, biểu mẫu, phân quyền và báo cáo.",
                    "Viết 3 test case cho nhập hồ sơ tàu, cập nhật chứng chỉ và xuất báo cáo.",
                    "Test nào chứng minh hệ thống không chỉ đúng giao diện mà đúng nghiệp vụ?",
                ),
                (
                    "Đánh giá hiệu quả và hướng phát triển",
                    "Đo thời gian xử lý, mức đầy đủ hồ sơ, khả năng truy xuất và chất lượng báo cáo.",
                    "Đề xuất 3 KPI để so sánh trước/sau khi số hóa.",
                    "Một hệ thống quản lý hồ sơ tàu tốt nên cải tiến tiếp theo hướng nào?",
                ),
            ],
        },
    ]

    chapters: list[dict[str, Any]] = []
    for chapter_index, spec in enumerate(chapter_specs, start=1):
        chapter_refs = _match_doc_refs(
            refs,
            tuple(spec["markers"]),
            fallback_title=title_source,
            chapter_index=chapter_index,
        )
        lessons = []
        for lesson_index, (title, summary, activity, quick_check) in enumerate(
            spec["lessons"],
            start=1,
        ):
            lesson_refs = _match_doc_refs(
                refs,
                tuple(spec["markers"]) + tuple(title.lower().split()[:4]),
                fallback_title=title_source,
                chapter_index=chapter_index,
                lesson_index=lesson_index,
            )
            lessons.append(
                _lms_manual_lesson(
                    title=title,
                    summary=summary,
                    activity=activity,
                    quick_check=quick_check,
                    refs=lesson_refs,
                    duration_minutes=22,
                )
            )
        chapters.append(
            {
                "title": spec["title"],
                "summary": spec["summary"],
                "learning_objectives": spec["objectives"],
                "lessons": lessons,
                "source_references": chapter_refs,
            }
        )

    lesson_count = sum(len(chapter["lessons"]) for chapter in chapters)
    return {
        "title": "Quản lý vận hành và hồ sơ tàu thủy cho doanh nghiệp vận tải biển",
        "description": (
            "Khóa học chuyển tài liệu nghiên cứu về hệ thống quản lý vận hành và hồ sơ "
            "tàu thủy thành lộ trình học thực hành cho doanh nghiệp vận tải biển."
        ),
        "audience": (
            "Cán bộ quản lý vận hành, nhân sự phụ trách hồ sơ tàu, nhóm triển khai phần "
            "mềm và người học ngành vận tải biển."
        ),
        "duration": f"{len(chapters)} chương, {lesson_count} bài, triển khai trong 4-6 buổi workshop.",
        "chapters": chapters,
        "assessment_plan": [
            "Mỗi chương có bài kiểm tra nhanh dựa trên nguồn trích dẫn từ tài liệu nghiên cứu.",
            "Cuối khóa làm case study: thiết kế module hồ sơ tàu và quy trình vận hành cho một doanh nghiệp mẫu.",
            "Đánh giá bằng rubric gồm: đúng nghiệp vụ, đúng dữ liệu, an toàn phân quyền và khả năng triển khai.",
        ],
        "implementation_checklist": [
            "Giáo viên kiểm tra nguồn trích dẫn trước khi áp dụng vào LMS.",
            "Các chương/bài được tạo ở trạng thái draft; không publish tự động.",
            "Nên bổ sung tài liệu mẫu hoặc biểu mẫu thật của doanh nghiệp trước buổi thực hành.",
        ],
        "source_document_title": title_source,
    }


def _build_maritime_training_lms_course_plan(
    *,
    title_source: str,
    refs: list[dict[str, Any]],
) -> dict[str, Any]:
    chapter_specs = [
        {
            "title": "Bối cảnh đào tạo nghiệp vụ hàng hải bằng LMS",
            "summary": "Đặt vấn đề chuyển hoạt động bồi dưỡng nghiệp vụ thủy thủ sang môi trường học tập số.",
            "markers": ("gioi thieu", "lms", "thuy thu", "nghiep vu chuyen mon", "dao tao"),
            "objectives": [
                "Giải thích được nhu cầu đào tạo nghiệp vụ chuyên môn cho thủy thủ bằng LMS.",
                "Nhận diện người học, giáo viên và đơn vị quản lý trong bối cảnh hàng hải.",
                "Phân biệt tài liệu nghiên cứu hệ thống LMS với tài liệu hướng dẫn sử dụng một sản phẩm cụ thể.",
            ],
            "lessons": [
                (
                    "Nhu cầu số hóa đào tạo nghiệp vụ cho thủy thủ",
                    "Tổng hợp bối cảnh, mục tiêu và vấn đề đào tạo nghiệp vụ chuyên môn trong ngành hàng hải.",
                    "Người học lập bản đồ vấn đề: thủy thủ cần học gì, học ở đâu và vì sao cần LMS.",
                    "Yếu tố nào khiến đào tạo nghiệp vụ hàng hải khó quản lý nếu chỉ dùng tài liệu rời?",
                ),
                (
                    "Vai trò người học, giảng viên và quản lý đào tạo",
                    "Phân tích các vai trò tham gia hệ thống LMS và trách nhiệm của từng nhóm.",
                    "Tạo bảng vai trò/quyền hạn tối thiểu cho người học, giảng viên và quản trị đào tạo.",
                    "Vai trò nào cần được hỗ trợ nhiều nhất để khóa học vận hành ổn định?",
                ),
                (
                    "Mục tiêu năng lực và chuẩn đầu ra của khóa học",
                    "Chuyển mục tiêu nghiên cứu thành năng lực có thể dạy, luyện tập và đánh giá.",
                    "Viết 3 chuẩn đầu ra theo dạng: hành động, điều kiện, tiêu chí đánh giá.",
                    "Một chuẩn đầu ra tốt khác một mô tả nội dung ở điểm nào?",
                ),
            ],
        },
        {
            "title": "Phân tích yêu cầu hệ thống LMS cho đào tạo thủy thủ",
            "summary": "Biến nhu cầu đào tạo thành yêu cầu chức năng, dữ liệu và quy trình học tập.",
            "markers": ("phan tich", "yeu cau", "chuc nang", "nguoi hoc", "khoa hoc", "bai giang"),
            "objectives": [
                "Tách được yêu cầu nghiệp vụ đào tạo khỏi mô tả giải pháp kỹ thuật.",
                "Liên kết chức năng LMS với quy trình học, kiểm tra và theo dõi tiến độ.",
                "Ưu tiên yêu cầu theo giá trị vận hành và khả năng kiểm chứng.",
            ],
            "lessons": [
                (
                    "Từ nhu cầu đào tạo sang yêu cầu chức năng",
                    "Đọc tài liệu để rút ra các chức năng như khóa học, bài giảng, kiểm tra và theo dõi học viên.",
                    "Đánh dấu các câu có thể chuyển thành user story cho hệ thống LMS.",
                    "Yêu cầu nào là lõi của đào tạo thủy thủ, yêu cầu nào chỉ là tiện ích?",
                ),
                (
                    "Luồng học tập: đăng ký, học, kiểm tra và phản hồi",
                    "Mô tả hành trình người học từ lúc vào khóa đến khi hoàn thành đánh giá.",
                    "Vẽ flow ngắn cho một thủy thủ học bài, làm quiz và nhận phản hồi.",
                    "Điểm nào trong luồng cần lưu vết để giáo viên theo dõi tiến bộ?",
                ),
                (
                    "Yêu cầu dữ liệu và báo cáo đào tạo",
                    "Xác định dữ liệu cần cho hồ sơ học tập, tiến độ, điểm số và báo cáo năng lực.",
                    "Thiết kế một bảng thông tin tối thiểu cho tiến độ học của học viên.",
                    "Báo cáo nào giúp quản lý biết khóa học có hiệu quả hay không?",
                ),
            ],
        },
        {
            "title": "Thiết kế học liệu, hoạt động và kiểm tra trên LMS",
            "summary": "Chuyển nội dung chuyên môn thành bài học số có tương tác, bài tập và đánh giá.",
            "markers": ("hoc lieu", "bai giang", "video", "quiz", "danh gia", "tuong tac"),
            "objectives": [
                "Thiết kế bài học số bám sát mục tiêu năng lực.",
                "Chọn dạng học liệu phù hợp cho kiến thức, quy trình và tình huống hàng hải.",
                "Xây dựng kiểm tra nhanh có nguồn trích dẫn để giáo viên xác minh.",
            ],
            "lessons": [
                (
                    "Cấu trúc một bài học nghiệp vụ trên LMS",
                    "Tổ chức bài học thành mục tiêu, nội dung cốt lõi, ví dụ, hoạt động và kiểm tra.",
                    "Biến một phần tài liệu thành khung bài học 20 phút cho thủy thủ.",
                    "Bài học cần có thành phần nào để người học không chỉ đọc mà còn luyện tập?",
                ),
                (
                    "Học liệu đa phương tiện và tình huống thực hành",
                    "Xác định khi nào dùng văn bản, hình ảnh, video, mô phỏng hoặc checklist nghiệp vụ.",
                    "Đề xuất một tình huống hàng hải và loại học liệu phù hợp để dạy tình huống đó.",
                    "Loại học liệu nào dễ tạo cảm giác hiểu nhầm nếu thiếu bối cảnh?",
                ),
                (
                    "Quiz, rubric và phản hồi năng lực",
                    "Thiết kế câu hỏi kiểm tra, rubric và phản hồi giúp đo năng lực chuyên môn.",
                    "Viết 3 câu hỏi: nhận biết, áp dụng và xử lý tình huống.",
                    "Một quiz tốt cần đo điều gì ngoài việc nhớ lại nội dung?",
                ),
            ],
        },
        {
            "title": "Thiết kế vận hành, phân quyền và theo dõi chất lượng",
            "summary": "Đưa khóa học vào quy trình quản lý có phân quyền, dữ liệu tiến độ và kiểm soát chất lượng.",
            "markers": ("phan quyen", "quan ly", "tien do", "bao cao", "chat luong", "du lieu"),
            "objectives": [
                "Thiết kế phân quyền an toàn cho người học, giảng viên và quản trị.",
                "Theo dõi tiến độ học tập bằng dữ liệu có thể kiểm chứng.",
                "Xây dựng vòng phản hồi để cải tiến khóa học sau mỗi đợt triển khai.",
            ],
            "lessons": [
                (
                    "Phân quyền và an toàn dữ liệu đào tạo",
                    "Xác định quyền xem, sửa, chấm, xuất báo cáo và quản trị nội dung trong LMS.",
                    "Lập ma trận quyền hạn cho giáo viên, học viên và quản lý đào tạo.",
                    "Quyền nào nếu cấp sai sẽ ảnh hưởng lớn nhất tới độ tin cậy của khóa học?",
                ),
                (
                    "Theo dõi tiến độ và cảnh báo học tập",
                    "Thiết kế chỉ số theo dõi tiến độ, mức hoàn thành và điểm cần hỗ trợ.",
                    "Đề xuất 5 chỉ số dashboard giúp giáo viên biết lớp đang học ra sao.",
                    "Chỉ số nào dễ gây hiểu nhầm nếu không kèm ngữ cảnh?",
                ),
                (
                    "Quy trình cải tiến nội dung sau triển khai",
                    "Dùng dữ liệu học tập, phản hồi và kết quả kiểm tra để chỉnh bài học.",
                    "Viết checklist rà soát khóa học sau một vòng chạy thử.",
                    "Khi nào nên sửa nội dung, khi nào nên sửa hoạt động học?",
                ),
            ],
        },
        {
            "title": "Triển khai thử nghiệm và đánh giá hiệu quả đào tạo",
            "summary": "Lập kế hoạch pilot, kiểm thử và đo hiệu quả của hệ thống LMS trong đào tạo hàng hải.",
            "markers": ("trien khai", "thu nghiem", "kiem thu", "danh gia", "ket qua", "huong phat trien"),
            "objectives": [
                "Lập kế hoạch triển khai thử nghiệm LMS theo giai đoạn an toàn.",
                "Thiết kế kiểm thử theo nghiệp vụ đào tạo thay vì chỉ kiểm tra giao diện.",
                "Đánh giá hiệu quả bằng dữ liệu học tập và phản hồi từ người dùng.",
            ],
            "lessons": [
                (
                    "Kế hoạch pilot cho khóa học nghiệp vụ thủy thủ",
                    "Chia triển khai thành các bước: chuẩn hóa học liệu, tạo lớp, chạy thử và thu phản hồi.",
                    "Lập checklist trước khi mở khóa học cho nhóm học viên đầu tiên.",
                    "Rủi ro nào cần kiểm soát trước khi pilot trên người học thật?",
                ),
                (
                    "Kiểm thử chức năng và kiểm thử trải nghiệm học",
                    "Xây dựng test case cho học liệu, quiz, tiến độ, phân quyền và báo cáo.",
                    "Viết 3 test case chứng minh khóa học vừa đúng hệ thống vừa đúng nghiệp vụ.",
                    "Một test UI thành công có đủ để kết luận khóa học tốt chưa?",
                ),
                (
                    "Đánh giá hiệu quả và hướng phát triển",
                    "Đo mức hoàn thành, chất lượng câu trả lời, phản hồi người học và khả năng mở rộng.",
                    "Đề xuất 3 KPI so sánh trước/sau khi áp dụng LMS vào đào tạo thủy thủ.",
                    "Nếu mở rộng hệ thống, ưu tiên cải tiến nội dung, dữ liệu hay trải nghiệm trước?",
                ),
            ],
        },
    ]

    chapters: list[dict[str, Any]] = []
    for chapter_index, spec in enumerate(chapter_specs, start=1):
        chapter_refs = _match_doc_refs(
            refs,
            tuple(spec["markers"]),
            fallback_title=title_source,
            chapter_index=chapter_index,
        )
        lessons = []
        for lesson_index, (title, summary, activity, quick_check) in enumerate(
            spec["lessons"],
            start=1,
        ):
            lesson_refs = _match_doc_refs(
                refs,
                tuple(spec["markers"]) + tuple(title.lower().split()[:4]),
                fallback_title=title_source,
                chapter_index=chapter_index,
                lesson_index=lesson_index,
            )
            lessons.append(
                _lms_manual_lesson(
                    title=title,
                    summary=summary,
                    activity=activity,
                    quick_check=quick_check,
                    refs=lesson_refs,
                    duration_minutes=22,
                )
            )
        chapters.append(
            {
                "title": spec["title"],
                "summary": spec["summary"],
                "learning_objectives": spec["objectives"],
                "lessons": lessons,
                "source_references": chapter_refs,
            }
        )

    lesson_count = sum(len(chapter["lessons"]) for chapter in chapters)
    return {
        "title": "LMS nâng cao nghiệp vụ chuyên môn cho thủy thủ",
        "description": (
            "Khóa học chuyển tài liệu nghiên cứu về hệ thống LMS phục vụ đào tạo "
            "nghiệp vụ hàng hải thành cây chương/bài có hoạt động, đánh giá và nguồn trích dẫn."
        ),
        "audience": (
            "Giảng viên hàng hải, người quản lý đào tạo, thủy thủ/học viên và nhóm triển khai LMS."
        ),
        "duration": f"{len(chapters)} chương, {lesson_count} bài, triển khai trong 4-6 buổi học/workshop.",
        "chapters": chapters,
        "assessment_plan": [
            "Mỗi chương có kiểm tra nhanh gắn với nguồn trích dẫn từ tài liệu nghiên cứu.",
            "Cuối khóa làm project nhỏ: thiết kế một module/bài học LMS cho nghiệp vụ hàng hải cụ thể.",
            "Đánh giá bằng rubric gồm: đúng mục tiêu năng lực, phù hợp người học, có dữ liệu theo dõi và khả năng triển khai.",
        ],
        "implementation_checklist": [
            "Giáo viên kiểm tra title, chương/bài và citation trước khi áp dụng vào LMS.",
            "Các chương/bài được tạo ở trạng thái draft; không publish tự động.",
            "Nên bổ sung tài liệu nghiệp vụ, rubric hoặc ví dụ tình huống thật trước buổi thực hành.",
        ],
        "source_document_title": title_source,
    }


__all__ = [
    "_build_maritime_training_lms_course_plan",
    "_build_maritime_vessel_management_course_plan",
]
