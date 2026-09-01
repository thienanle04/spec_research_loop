"""Spec module dependency bindings."""

import json
from collections.abc import AsyncIterator

from pydantic import TypeAdapter

from app.adapters.llm import (
    FitWebUiLlmPort,
    TracingLlm,
    configure_llm_trace_logger,
)
from app.core.config import get_settings
from app.ports.llm import LlmPort


class FakeSpecLlmPort:
    async def stream(
        self,
        *,
        system: str,
        prompt: str,
        model: str | None = None,
    ) -> AsyncIterator[str]:
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
                {"directions": [
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
                ]},
                ensure_ascii=False,
            )
        return json.dumps(
            {"directions": [
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
            ]}
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
                            "action": "Compare claim-level and aggregate verification on held-out sources.",
                            "objective": "Measure the unsupported claim rate for both methods.",
                            "significance": "Tests whether localized verification improves evidence support.",
                        }
                    ]
                },
            },
            "FeasibilityReport": {
                "is_feasible": True,
                "conclusion": "The evaluation can start with a bounded held-out set.",
                "required_resources": ["Held-out scholarly sources"],
                "potential_bottlenecks": ["Evidence annotation time"],
                "mitigation_strategies": ["Start with a smaller evaluation set"],
            },
        }
        return TypeAdapter(schema).validate_python(payloads.get(schema.__name__, {}))


def get_spec_llm() -> LlmPort:
    settings = get_settings()
    provider = settings.research_llm_provider.casefold()
    if provider == "fake":
        return FakeSpecLlmPort()
    if provider != "fit_webui":
        raise RuntimeError(f"Unsupported Spec LLM provider: {provider}")
    if not settings.fit_webui_api_key:
        raise RuntimeError(
            "FIT_WEBUI_API_KEY is required when RESEARCH_LLM_PROVIDER=fit_webui"
        )
    llm: LlmPort = FitWebUiLlmPort(
        api_key=settings.fit_webui_api_key,
        default_model=settings.research_llm_model,
        base_url=settings.fit_webui_base_url,
        timeout_seconds=settings.fit_webui_timeout_seconds,
        max_tokens=settings.fit_webui_max_tokens,
    )
    if settings.llm_trace:
        configure_llm_trace_logger()
        return TracingLlm(llm, node="spec")
    return llm
