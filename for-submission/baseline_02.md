# Baseline 2: OPRO-style Optimizer (Optimization by PROmpting)

Baseline 2 đại diện cho các phương pháp tự động tối ưu prompt hiện trạng.

- **Mô tả:** Sử dụng chính LLM làm optimizer để sinh ra các prompt mới dựa trên điểm số (overall score) của các prompt cũ ở vòng trước.
- **Cách thức hoạt động:** Hệ thống ghép prompt cũ và điểm số thành một meta-prompt, yêu cầu LLM "Hãy sinh ra một prompt mới có khả năng đạt điểm cao hơn".
- **Nhược điểm:** OPRO chủ yếu dựa vào phản hồi dạng điểm tổng (Scalar Feedback) hoặc phản hồi văn bản chung chung (Textual Feedback). Nó không phân tích sâu vào từng claim hay từng evidence để tìm ra nguyên nhân gây hallucination.
- **So sánh với phương pháp đề xuất:** Phương pháp của chúng tôi (Claim-level evidence feedback) khắc phục nhược điểm của OPRO bằng cách tối ưu trực tiếp dựa trên trạng thái `GROUNDED` / `REJECTED` của từng mệnh đề.

*(Nội dung này phục vụ việc chứng minh Research Gap trong bản Spec cuối cùng).*
