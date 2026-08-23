from app.ports.llm import LlmPort
from app.modules.spec.schemas import (
    SpecConstructionContext,
    GenerateContributionResponse,
    GenerateClaimsResponse,
    GenerateExperimentResponse,
    FeasibilityReport
)

async def generate_contribution_options(context: SpecConstructionContext, llm: LlmPort) -> GenerateContributionResponse:
    system = "Bạn là một AI hỗ trợ thiết kế Đặc tả Nghiên cứu (Research Spec)."
    prompt = f"""
    Người dùng đang muốn phát triển một nghiên cứu.
    Vấn đề (Problem): {context.problem_statement}
    Research Gap: {context.research_gap}
    Các nghiên cứu liên quan: {context.related_works_summary}
    
    Hãy đề xuất 3-4 hướng đóng góp (Contribution Options).
    Bao gồm các hướng tập trung vào Thuật toán, Verifier, Human-in-the-loop, và một lựa chọn kết hợp.
    Mỗi hướng đóng góp nên có tiêu đề (title), mã option (id) và mô tả chi tiết (description).
    """
    return await llm.complete_structured(
        system=system,
        prompt=prompt,
        schema=GenerateContributionResponse
    )

async def generate_claims_evidence(contribution_desc: str, context: SpecConstructionContext, llm: LlmPort) -> GenerateClaimsResponse:
    system = "Bạn là một AI hỗ trợ thiết kế Đặc tả Nghiên cứu (Research Spec)."
    prompt = f"""
    Với hướng đóng góp sau: {contribution_desc}
    (Vấn đề gốc: {context.problem_statement})
    
    Hãy xây dựng danh sách các Claim-Evidence Card. 
    Mỗi thẻ cần có Claim, Baseline để so sánh, Metric đo lường, Evidence kỳ vọng, và điều kiện bác bỏ.
    """
    return await llm.complete_structured(
        system=system,
        prompt=prompt,
        schema=GenerateClaimsResponse
    )

async def generate_experiment_plan(claims: list[dict], context: SpecConstructionContext, llm: LlmPort) -> GenerateExperimentResponse:
    system = "Bạn là một AI hỗ trợ thiết kế Đặc tả Nghiên cứu (Research Spec)."
    prompt = f"""
    Dựa trên các Claim sau: {claims}
    
    Hãy lên kế hoạch thí nghiệm chi tiết gồm: Baselines, Metrics, Giao thức đánh giá (evaluation_protocol), Ablation Study, và Generalization.
    """
    return await llm.complete_structured(
        system=system,
        prompt=prompt,
        schema=GenerateExperimentResponse
    )

async def check_feasibility(plan_desc: str, context: SpecConstructionContext, llm: LlmPort) -> FeasibilityReport:
    system = "Bạn là một AI hỗ trợ thiết kế Đặc tả Nghiên cứu (Research Spec)."
    prompt = f"""
    Kế hoạch thí nghiệm: {plan_desc}
    Ràng buộc tài nguyên: {context.hardware_constraint}
    
    Hãy đánh giá tính khả thi (Feasibility). Đưa ra ước lượng VRAM (estimated_vram), thời gian chạy (estimated_time), và các gợi ý điều chỉnh nếu cần (suggestions). Trả về boolean is_feasible.
    """
    return await llm.complete_structured(
        system=system,
        prompt=prompt,
        schema=FeasibilityReport
    )
