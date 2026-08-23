from app.modules.spec.schemas import SpecConstructionContext

async def get_mock_spec_context() -> SpecConstructionContext:
    """
    Mock data context dựa theo ví dụ trong đồ án.
    Sau này sẽ đổi thành truy vấn từ DB: lấy Problem, RQ, Research Gap đã confirm.
    """
    return SpecConstructionContext(
        problem_statement="Prompt thủ công có thể không ổn định khi LLM trích xuất thông tin từ paper.",
        research_questions=[
            "Tối ưu nhiều vòng có giảm unsupported claims không?"
        ],
        research_gap="Các phương pháp hiện tại (OPRO, PromptBreeder) chưa tối ưu trực tiếp ở mức claim–evidence.",
        related_works_summary="OPRO dùng điểm tổng, PromptBreeder tiến hóa prompt nhưng tốn resource, TextGrad dùng textual feedback nhưng judge có thể bias.",
        hardware_constraint="Chạy được trên RTX 3090"
    )
