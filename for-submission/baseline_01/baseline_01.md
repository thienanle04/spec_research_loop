# Thí nghiệm so sánh Single LLM và SpecResearch Loop

## Baseline

Trước khi so sánh, đưa ý tưởng ban đầu qua **Grilling** của SpecResearch Loop. Sau khi người dùng xác nhận Grilling, lưu một **gói ý tưởng dùng chung** gồm:

- intent;
- problem;
- research question;
- constraints;
- open questions.

Single LLM và SpecResearch Loop đều bắt đầu từ gói ý tưởng này. Nhờ đó, kết quả không bị ảnh hưởng bởi việc một phương pháp nhận được ý tưởng rõ hơn phương pháp còn lại.

Baseline sử dụng **một LLM cố định** để sinh toàn bộ phần còn lại của Research Spec bằng một prompt. Có thể chọn Gemini hoặc ChatGPT làm LLM thực nghiệm.

Baseline có thể dùng chức năng tìm kiếm web/nghiên cứu của LLM nếu có, nhưng:

- chỉ gửi một prompt;
- không hỏi đáp hoặc xác nhận từng giai đoạn;
- không yêu cầu LLM sửa lại output;
- không chạy Independent Judges.

Output phải gồm: problem, research question, related work, gap, contribution, claims–evidence, experiment plan, feasibility và limitations.

### Prompt mẫu cho Single LLM

```text
Bạn là một chuyên gia thiết kế nghiên cứu. Từ gói ý tưởng đã được người dùng
xác nhận dưới đây, hãy tìm kiếm tài liệu liên quan và tạo một Research Spec
rõ ràng, có căn cứ và có thể triển khai.

GÓI Ý TƯỞNG ĐÃ XÁC NHẬN

Problem:
[PROBLEM]

Research question:
[RESEARCH QUESTION]

Constraints:
[CONSTRAINTS]

Open questions:
[OPEN QUESTIONS]

YÊU CẦU

Hãy:

1. Tìm những công trình liên quan trực tiếp nhất.
2. Chỉ sử dụng citation có thể kiểm tra bằng URL hoặc DOI.
3. Xác định research gap nhưng không khẳng định novelty nếu chưa đủ bằng chứng.
4. Đề xuất contribution bám sát gap.
5. Chuyển contribution thành các claim có thể kiểm nghiệm hoặc bác bỏ.
6. Với mỗi claim, xác định baseline và metric phù hợp.
7. Thiết kế experiment plan có dataset, data split, model, baseline, metric,
   số lần chạy, tiêu chí thành công và tài nguyên cần thiết.
8. Đánh giá tính khả thi.
9. Nêu rõ limitation, rủi ro và câu hỏi chưa giải quyết.

Không hỏi lại người dùng. Hãy tự đưa ra lựa chọn hợp lý và ghi rõ assumption.

Xuất một tài liệu Markdown sạch gồm:

1. Confirmed Idea
2. Related Work
3. Research Gap
4. Proposed Contribution
5. Testable Claims
6. Experiment Plan
7. Feasibility
8. Limitations
9. References
```

## Dataset

Sử dụng **1 ý tưởng nghiên cứu ban đầu** lấy từ đề tài của sinh viên hoặc do giảng viên cung cấp.

Ý tưởng được chạy Grilling một lần để tạo gói ý tưởng đã xác nhận. Từ gói chung đó, Single LLM sinh một spec và SpecResearch Loop tiếp tục sinh một spec. Tổng cộng thu được:

```text
1 ý tưởng × 2 phương pháp = 2 Research Specs
```

Hai phương pháp phải nhận đúng cùng intent, problem, research question, constraints và open questions từ Grilling.

## Ground Truth

Mỗi spec được chấm từ 1 đến 5 theo năm tiêu chí:

1. Problem và research question có rõ ràng không?
2. Gap và contribution có hợp lý, cụ thể không?
3. Claim có evidence hoặc citation phù hợp không?
4. Experiment plan có đủ baseline, dataset, metric và protocol không?
5. Kế hoạch có khả thi với tài nguyên đã cho không?

Điểm cuối của một spec là trung bình điểm của năm tiêu chí.

## Metric

- **Quality score:** điểm chất lượng trung bình trên thang 1–5. Đây là metric chính.
- **Score difference:** chênh lệch Quality score giữa SpecResearch Loop và Single LLM.
- **Valid citation rate:** số citation tồn tại và hỗ trợ đúng nhận định chia cho tổng số citation được kiểm tra.
- **Completeness:** số phần có nội dung hợp lệ trên tổng 9 phần bắt buộc.

Để giảm công sức, chỉ cần kiểm tra tối đa 10 citation được chọn ngẫu nhiên trong mỗi spec.

## Proposed

Sử dụng **SpecResearch Loop** để tạo Research Spec từ cùng gói ý tưởng đã hoàn tất và được xác nhận ở Grilling.

Người dùng đi qua các giai đoạn:

```text
Gói ý tưởng sau Grilling
→ Related work
→ Gap
→ Contribution
→ Claims–evidence
→ Experiment planning
→ Spec Draft
```

Không chạy lại Grilling khi bắt đầu nhánh Proposed. Hệ thống tiếp tục từ Related work và lấy Produced Spec Version tại Spec Draft làm output. Chưa chạy Independent Judges để thí nghiệm chỉ đo khả năng sinh Research Spec.

Để so sánh công bằng, hai phương pháp cũng phải dùng cùng ngôn ngữ và cùng cấu trúc output.

Trong case study này, SpecResearch Loop được xem là tốt hơn baseline nếu có Quality score cao hơn, citation chính xác hơn.

Vì dataset chỉ có một ý tưởng, kết quả chỉ mô tả case study này và không được dùng để kết luận rằng SpecResearch Loop tốt hơn Single LLM trong mọi trường hợp.
