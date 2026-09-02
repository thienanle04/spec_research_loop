# Thí nghiệm đánh giá hệ thống: Single Judge (Baseline) vs Multi-Judge (Đề xuất)

Tài liệu này trình bày phương pháp **"Proof of Concept" (Chứng minh khái niệm)** thông qua một Case Study định tính. Thí nghiệm sử dụng **đúng 1 bản Research Spec được thiết kế có chủ ý ("cài bẫy")** để chứng minh sự vượt trội của kiến trúc Multi-Judge (Đồ án đề xuất) so với phương pháp Single Judge (Baseline phổ thông).

---

## 1. Mục tiêu thí nghiệm
Chứng minh rằng một LLM duy nhất (Single Judge) khi đánh giá toàn bộ Spec sẽ bị "quá tải ngữ cảnh" (context stuffing) dẫn đến nhận xét hời hợt hoặc bỏ sót lỗi. Ngược lại, hệ thống Multi-Judge với các prompt chuyên biệt (Agentic workflow) sẽ soi chiếu sâu sắc và chỉ ra chính xác các "lỗ hổng logic" ngầm.

## 2. Kịch bản "Cài bẫy" (The Crafted Spec)
Chúng tôi chuẩn bị 1 bản Research Spec có bề ngoài hàn lâm, câu chữ mạch lạc nhưng được **cố tình cài cắm 2 lỗi logic nghiêm trọng**:

*   **Bẫy 1 (Lỗi Over-claiming ở phần Contribution):** Problem đưa ra là "Các mô hình ngôn ngữ nhỏ (SLM) hay bị lỗi suy luận toán học cơ bản". Nhưng phần Contribution lại chém gió: *"Đề xuất một framework mới giải quyết triệt để và hoàn toàn vấn đề ảo giác (hallucination) trên TẤT CẢ các mô hình ngôn ngữ"*. (Mở rộng phạm vi vô lý).
*   **Bẫy 2 (Lỗi thiếu Baseline ở phần Experiment):** Đề xuất một thuật toán mới nhưng phần kế hoạch thí nghiệm chỉ ghi: *"Sẽ đo Accuracy và F1-score trên tập dữ liệu GSM8K"*. (Hoàn toàn không ghi rõ sẽ so sánh với phương pháp Baseline nào đang có sẵn).

## 3. Thực thi Baseline (Single Judge)
*   **Cách thiết lập:** Đưa toàn bộ bản Spec "cài bẫy" trên vào một LLM tiêu chuẩn (ví dụ gpt-4o hoặc claude-3.5-sonnet) với một prompt chung chung: *"Bạn là một chuyên gia đánh giá nghiên cứu. Hãy đọc và nhận xét bản Research Spec sau, chỉ ra các lỗi nếu có."*
*   **Kết quả thu được:**
    *   Single Judge bị ấn tượng bởi văn phong học thuật, đưa ra nhận xét chung chung: *"Bài viết trình bày có cấu trúc tốt, ý tưởng đột phá."*
    *   Góp ý rất huề vốn: *"Phần thí nghiệm cần mô tả chi tiết hơn về cấu hình phần cứng chạy mô hình."*
    *   **Thất bại:** Hoàn toàn KHÔNG phát hiện ra sự phi logic của Contribution và lỗi ngớ ngẩn (thiếu Baseline) trong kế hoạch thí nghiệm.

## 4. Thực thi Proposed (Multi-Judge Pipeline trong đồ án)
*   **Cách thiết lập:** Chạy bản Spec qua luồng hệ thống của SpecResearch Loop. Hệ thống tự động cắt ngữ cảnh phù hợp (Context Projection) và đưa cho các Judge độc lập đánh giá.
*   **Kết quả thu được:**
    *   **Contribution Judge báo lỗi:** *"Từ chối (REJECTED). Vấn đề của bạn chỉ tập trung vào Toán học trên SLM, nhưng Contribution lại claim là 'giải quyết hoàn toàn ảo giác trên tất cả LLM'. Đây là lỗi Over-claiming nghiêm trọng. Vui lòng thu hẹp phạm vi Contribution."*
    *   **Experiment Judge báo lỗi:** *"Từ chối (REJECTED). Kế hoạch thí nghiệm của bạn KHÔNG có Baseline. Đo Accuracy độc lập là vô nghĩa. Bạn cần chỉ định ít nhất 2 phương pháp kinh điển (ví dụ: Chain-of-Thought tiêu chuẩn) để làm đối chứng."*

---

## 5. Bảng so sánh và Kết luận

| Tiêu chí đối sánh | Single Judge (Baseline) | Multi-Judge (Hệ thống Đồ án) | Giải thích nguyên nhân |
| :--- | :--- | :--- | :--- |
| **1. Khả năng phát hiện lỗi ngầm (Deep Reasoning)** | Kém. Chỉ đánh giá bề nổi (câu chữ, cấu trúc). | **Xuất sắc.** Bắt được chính xác các lỗi phi logic giữa các chương. | Single Judge bị "quá tải ngữ cảnh". Multi-Judge có prompt ép AI tập trung vào đúng một nhiệm vụ. |
| **2. Độ cụ thể của giải pháp (Actionability)** | Thấp. Lời khuyên chung chung ("cần chi tiết hơn"). | **Rất cao.** Chỉ đích danh lỗi ("Over-claiming", "Thiếu baseline"). | Người dùng biết ngay mình phải sửa cái gì, dòng nào, thay vì phải đoán mò. |
| **3. Giảm thiểu Ảo giác (Hallucination)** | Cao (Dễ bịa lỗi không có do đọc đoạn text quá dài). | **Thấp.** | Mỗi Judge chỉ nhận đúng phần Context (Context Projection) cần thiết, không bị nhiễu. |

**=> Kết luận:** Thông qua Case Study định tính này, đồ án chứng minh được rằng việc thiết kế hệ thống **Multi-Judge** là bắt buộc và mang lại giá trị học thuật vượt trội so với việc phụ thuộc vào một luồng hỏi-đáp LLM thông thường. Cải tiến này giải quyết triệt để vấn đề "đánh giá hời hợt", giúp sinh viên nhận được phản hồi sắc bén như từ một hội đồng thực sự.
