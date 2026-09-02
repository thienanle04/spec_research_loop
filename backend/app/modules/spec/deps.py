"""Spec module dependency bindings."""

import json
from collections.abc import AsyncGenerator

from pydantic import TypeAdapter

from app.adapters.llm import get_llm_port
from app.modules.loop.catalog import WorkflowNode
from app.ports.llm import LlmPort


class FakeSpecLlmPort:
    """Domain fake for tests; not selected by runtime profiles (ADR 0034)."""

    async def stream(
        self,
        *,
        system: str,
        prompt: str,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        yield await self.complete(system=system, prompt=prompt, model=model)

    async def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str | None = None,
    ) -> str:
        del system, model
        request = json.loads(prompt)
        if "input" in request:
            request = request["input"]
        vietnamese = request.get("required_output_language") == "Vietnamese"
        if vietnamese:
            return json.dumps(
                {
                    "directions": [
                        {
                            "title": "Đối chiếu từng luận điểm với nguồn học thuật",
                            "mechanism": "Tách kết quả thành từng luận điểm và truy xuất bằng chứng học thuật tương ứng cho từng luận điểm.",
                            "gap_link": "Cơ chế xử lý trực tiếp tình trạng các phương pháp hiện tại chưa kiểm chứng ở cấp từng luận điểm.",
                            "novelty": "Khác với kiểm tra toàn bộ kết quả bằng một điểm tổng hợp, hướng này định vị chính xác luận điểm thiếu hỗ trợ.",
                            "validation": "So sánh với kiểm tra tổng hợp, đo tỷ lệ luận điểm không được nguồn hỗ trợ và bác bỏ nếu không giảm tỷ lệ này.",
                        },
                        {
                            "title": "Bản đồ liên kết luận điểm–bằng chứng có thể truy vết",
                            "mechanism": "Tạo một cấu trúc liên kết mỗi luận điểm với đoạn bằng chứng, nguồn và trạng thái hỗ trợ hoặc phản bác.",
                            "gap_link": "Cấu trúc làm cho bằng chứng của từng luận điểm trong Gap đã xác nhận trở nên quan sát và kiểm tra được.",
                            "novelty": "Khác với danh sách tài liệu tham khảo không gắn kết, bản đồ biểu diễn quan hệ hỗ trợ ở cấp luận điểm.",
                            "validation": "So sánh với danh sách nguồn thông thường, đo độ chính xác truy vết và bác bỏ nếu người đánh giá không xác minh nhanh hoặc đúng hơn.",
                        },
                        {
                            "title": "Cổng xác nhận cho luận điểm thiếu bằng chứng",
                            "mechanism": "Chặn xác nhận kết quả khi một luận điểm quan trọng chưa có bằng chứng phù hợp và cho phép Account sửa liên kết.",
                            "gap_link": "Cổng xác nhận ngăn các luận điểm chưa được kiểm chứng như mô tả trong Gap đi tiếp vào Research Spec.",
                            "novelty": "Khác với cảnh báo thụ động, hướng này biến trạng thái bằng chứng thành điều kiện kiểm soát có thể chỉnh sửa.",
                            "validation": "So sánh với chỉ cảnh báo, đo số luận điểm thiếu hỗ trợ còn sót lại và bác bỏ nếu cổng không cải thiện kết quả.",
                        },
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "directions": [
                    {
                        "title": "Evidence-localized search and selection",
                        "mechanism": "Rank candidate changes using localized evidence failures instead of one aggregate score.",
                        "gap_link": "The mechanism targets the confirmed inability to locate which claim or component caused a failed result.",
                        "novelty": "Unlike aggregate-score selection, it feeds claim-level failure locations back into the next search decision.",
                        "validation": "Compare with aggregate-score selection, measure unsupported-claim rate, and reject if it yields no reduction.",
                    },
                    {
                        "title": "Traceable claim–evidence verification map",
                        "mechanism": "Represent every claim with its supporting passage, source, and support or contradiction status.",
                        "gap_link": "The map makes the evidence for each claim independently observable and auditable.",
                        "novelty": "Unlike an unlinked bibliography, it records the support relationship at claim granularity.",
                        "validation": "Compare with source-list verification, measure localization accuracy, and reject if auditing is not more accurate.",
                    },
                    {
                        "title": "Human confirmation gate for unsupported claims",
                        "mechanism": "Block confirmation when a material claim lacks suitable evidence and let the Account repair the link.",
                        "gap_link": "The gate prevents the unsupported claims identified by the confirmed Gap from entering the Research Spec.",
                        "novelty": "Unlike a passive warning, it makes evidence status an editable control condition.",
                        "validation": "Compare with warnings alone, measure residual unsupported claims, and reject if the gate does not reduce them.",
                    },
                ]
            }
        )

    async def complete_structured[T](
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        model: str | None = None,
    ) -> T:
        del system, prompt, model
        payloads: dict[str, object] = {
            "GenerateClaimsResponse": {
                "version": 1,
                "cards": [
                    {
                        "id": "claim-1",
                        "claim": "Claim-level verification reduces unsupported claims.",
                        "baseline": "Aggregate-score feedback",
                        "metric": "Unsupported claim rate",
                        "evidence": "Evaluation on held-out scholarly sources",
                        "rejection_condition": "No statistically significant reduction",
                    }
                ],
            },
            "GenerateExperimentResponse": {
                "version": 1,
                "plan": {
                    "experiments": [
                        {
                            "claim": "Claim-level verification reduces unsupported claims.",
                            "action": "Compare claim-level feedback against aggregate scores.",
                            "objective": "Measure unsupported-claim rate on held-out sources.",
                            "significance": "Shows whether localized feedback improves reliability.",
                        }
                    ]
                },
            },
            "FeasibilityReport": {
                "is_feasible": True,
                "conclusion": "The plan is feasible on a single GPU workstation.",
                "required_resources": ["24 GB VRAM", "8 hours compute"],
                "potential_bottlenecks": ["Full-text download rate limits"],
                "mitigation_strategies": ["Start with a smaller held-out evaluation set"],
            },
        }
        return TypeAdapter(schema).validate_python(payloads.get(schema.__name__, {}))


def get_contribution_llm() -> LlmPort:
    return get_llm_port(WorkflowNode.CONTRIBUTION.value)


def get_claims_llm() -> LlmPort:
    return get_llm_port(WorkflowNode.CLAIMS.value)


def get_experiment_llm() -> LlmPort:
    return get_llm_port(WorkflowNode.EXPERIMENT_PLAN.value)


def get_feasibility_llm() -> LlmPort:
    return get_llm_port(WorkflowNode.FEASIBILITY.value)
