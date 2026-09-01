# Cơ chế kiểm tra Citation và Evidence (Citation Audit Mechanism)

## 1. Vấn đề (Problem)
Khi LLM tổng hợp các nghiên cứu liên quan hoặc sinh các bằng chứng cho Research Spec, hệ thống rất dễ gặp tình trạng "hallucination" (ảo giác) - nơi LLM tạo ra các "Unsupported Claims" (nhận định không có bằng chứng từ tài liệu).

## 2. Điểm sáng tạo của hệ thống
Thay vì chỉ dựa vào LLM để tự chấm điểm văn bản (Textual Feedback), SPECRESEARCH LOOP thiết kế một cơ chế kiểm tra tính xác thực ở mức độ đoạn văn (Passage-level Grounding).

### Thuật toán Grounding
Được hiện thực hóa trong module `research/service.py` thông qua hàm `_grounding_status` và `_evidence_grounding_status`:
1. **Trích xuất (Extraction):** Hệ thống yêu cầu LLM trích xuất chính xác chuỗi `passage` từ `source_text`.
2. **Đối chiếu (Matching):** Backend dùng thuật toán `casefold()` để kiểm tra xem `passage` có thực sự nằm trong `source_text` gốc hay không.
3. **Phân loại trạng thái (Categorization):**
   - `GROUNDED`: Đoạn trích xuất hoàn toàn khớp với văn bản gốc.
   - `WARNING`: Có dấu hiệu được paraphrase, cần user hoặc LLM xem xét lại.
   - `REJECTED`: Đoạn văn hoàn toàn không tồn tại trong source, đánh dấu đây là Hallucination.

### Node Evidence Judge
Khi bản Spec chuyển sang module `judgement`, `WorkflowNode.EVIDENCE_JUDGE` (trong `judgement/service.py`) sẽ quét qua toàn bộ Claim-Evidence Matrix:
- Nó gọi bộ verifier `unsupported_citation(view)`.
- Nếu có một evidence ở trạng thái `REJECTED` hoặc không trỏ tới tài liệu có thật, Judge này sẽ throw ra một `JudgeIssueResponse` với severity `MAJOR`.
- Người dùng bị block không được xuất bản Spec cho đến khi họ chọn `HandlingOption` để sửa lỗi này (VD: Xóa claim, hoặc tìm citation khác).

> **📝 BẠN CẦN LÀM THÊM Ở FILE NÀY:**
> - Bạn có thể copy một đoạn code nhỏ từ `_passage_location` hoặc `_grounding_status` trong code của bạn để minh họa vào đây.
> - Cung cấp 1 screenshot giao diện khi hệ thống "bắt quả tang" một claim thiếu evidence.
