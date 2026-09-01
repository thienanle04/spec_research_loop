# Tập Use Case Thử Nghiệm

Hệ thống được thử nghiệm với các Use case mang tính mơ hồ cao để kiểm chứng khả năng phân rã và hoàn thiện của luồng SpecResearch.

## Use case 1 (Use case chính): Tối ưu prompt LLM
**Input của người dùng:** 
> "Tôi muốn xây dựng phương pháp tự động tối ưu prompt nhiều vòng để giảm hallucination khi LLM trích xuất thông tin từ paper."

**Phân rã mong đợi từ hệ thống:**
- **Problem:** Prompt thủ công có thể không ổn định.
- **RQ:** Tối ưu nhiều vòng có giảm unsupported claims không?
- **Gap:** Các phương pháp hiện tại chưa tối ưu trực tiếp ở mức claim-evidence.
- **Contribution:** Framework tối ưu prompt dựa trên evidence feedback.

*(Hãy chạy hệ thống của bạn với input trên, sau đó sao chép kết quả output JSON/Markdown mà web bạn sinh ra và dán vào đây để chứng minh hệ thống hoạt động đúng).*

## Use case 2: Áp dụng RAG cho y khoa
**Input của người dùng:**
> "Làm sao để dùng RAG (Retrieval-Augmented Generation) trả lời các câu hỏi về y tế chuẩn xác hơn mà không bị sai phác đồ điều trị."

**Phân rã mong đợi từ hệ thống:**
- **Problem:** LLM thường sinh ra các phác đồ y tế sai lệch (hallucinate) gây nguy hiểm.
- **RQ:** Làm sao tích hợp Clinical Guidelines vào hệ thống RAG để hạn chế sinh văn bản nằm ngoài phác đồ?
- **Gap:** Các hệ thống RAG hiện tại tra cứu theo semantic similarity nhưng không có logic loại trừ các tài liệu mâu thuẫn phác đồ.

*(Tương tự, dán kết quả hệ thống của bạn sinh ra vào đây)*

> **📝 BẠN CẦN LÀM THÊM Ở FILE NÀY:**
> - Chạy giao diện frontend của bạn (`pnpm dev`).
> - Nhập các Use case này vào ô "Vague Idea".
> - Copy kết quả trên màn hình và paste vào đây.
