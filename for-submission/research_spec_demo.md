# Research Spec Demo
*(Đây là kết quả mẫu do hệ thống tự sinh sau khi trải qua luồng SpecResearch)*

> **📝 BẠN CẦN LÀM THÊM Ở FILE NÀY:**
> Sau khi bạn hoàn thành việc quay video demo ở bước trên, hãy bấm nút "Export Spec" hoặc copy toàn bộ văn bản Markdown do ứng dụng web của bạn sinh ra (ở tab Spec/Revision) và dán đè lên nội dung bên dưới.
>
> --- (Mẫu tham khảo) ---

## 1. Problem Statement
Prompt thủ công khi dùng LLM để trích xuất thông tin (Extraction tasks) thường không ổn định và dễ bị hallucination (sinh ra thông tin ảo).

## 2. Research Question
Việc tối ưu prompt qua nhiều vòng (multi-turn optimization) kết hợp cơ chế kiểm chứng claim-level có giúp giảm tỷ lệ "unsupported claims" trong ngân sách token giới hạn hay không?

## 3. Related Work
- **OPRO:** Tối ưu prompt dùng điểm tổng. (Nhược điểm: Chưa phân tích lỗi theo từng claim).
- **DSPy:** Tối ưu pipeline tự động. (Nhược điểm: Đòi hỏi định nghĩa metric phức tạp cho downstream task).

## 4. Research Gap
Các framework tối ưu prompt hiện tại sử dụng phản hồi chung chung (textual/scalar feedback). Chưa có hệ thống nào tách output thành từng claim, kiểm tra evidence độc lập và đưa lỗi cấp độ claim làm feedback cho LLM optimizer.

## 5. Proposed Approach & Contribution
Một Framework tối ưu prompt dựa trên "Claim-level Evidence Feedback".
- Điểm mới 1: Bộ Verifier phân biệt claim được chứng minh (GROUNDED), thiếu (WARNING) và mâu thuẫn (REJECTED).
- Điểm mới 2: Cơ chế feedback trực tiếp vào mutation phase để chỉnh sửa prompt ban đầu.

## 6. Experiment Plan
- **Thí nghiệm 1 - So sánh Baseline:** So sánh với Human-written prompt và OPRO-style. (Điều kiện: Cùng budget 10 vòng, cùng Model 8B).
- **Thí nghiệm 2 - Chất lượng:** Đo đạc Claim precision/recall, Unsupported Claim rate.
- **Thí nghiệm 3 - Generalization:** Thử nghiệm chéo prompt tốt nhất lên domain chưa từng gặp (Tài chính).

## 7. Resource Constraints
- Model yêu cầu: 7B-8B parameters, lượng VRAM <= 24GB (Chạy vừa trên 1 GPU RTX 3090).
