# Baseline 1: Human-written Prompt

Baseline 1 là một phương pháp tiêu chuẩn hiện nay dùng để làm đường cơ sở so sánh cho thực nghiệm trong Research Spec.

- **Mô tả:** Sử dụng các prompt được kỹ sư (human expert) thiết kế thủ công, kết hợp với các kỹ thuật như Zero-shot hoặc Few-shot prompting.
- **Cách thức hoạt động:** Kỹ sư viết một đoạn prompt mô tả tác vụ trích xuất (Ví dụ: "Extract claims from this abstract").
- **Nhược điểm:** Phụ thuộc vào kỹ năng của người viết prompt. Khó tổng quát hóa trên nhiều loại paper khác nhau (Y tế, Máy tính, Sinh học). Rất dễ bị Hallucination.
- **Metric đánh giá tương ứng:** Mức độ Coverage (độ bao phủ thông tin) và Unsupported Claim Rate.

*(Nội dung này là cấu hình thí nghiệm được định nghĩa trong bước Experiment Plan của SpecResearch Loop).*
