# Báo cáo Đánh giá Hệ thống (System Evaluation)

## 1. Mục tiêu đánh giá
Báo cáo này đánh giá mức độ hiệu quả của hệ thống SPECRESEARCH LOOP trong việc chuyển đổi một ý tưởng nghiên cứu mơ hồ thành một Research Spec vững chắc, đồng thời chứng minh các "điểm sáng tạo" của đồ án.

## 2. Điểm sáng tạo được kiểm nghiệm
1. **Multi-Agent Judgement (Hệ thống 5 Judge độc lập):** Giảm thiên kiến (bias) so với việc dùng 1 LLM duy nhất để duyệt toàn bộ Spec.
2. **Claim-level Evidence Feedback:** Cơ chế Grounding tự động bắt lỗi các Unsupported Claims.

## 3. Cấu hình thực nghiệm (Experimental Setup)
- **Tác vụ:** Tối ưu một ý tưởng về "Giảm hallucination bằng tối ưu prompt nhiều vòng".
- **Baseline so sánh:** 
  1. Quy trình sinh Spec dùng LLM 1 shot (Zero-shot LLM generator).
  2. Quy trình sinh Spec dùng 1 LLM Judge đóng vai trò reviewer tổng hợp.
- **Metric đánh giá:** 
  - Tỷ lệ Claim thiếu bằng chứng (Unsupported Claim Rate).
  - Tỷ lệ mâu thuẫn (Contradiction Rate).
  - Thời gian để user đưa ra quyết định duyệt Spec.

## 4. Kết quả (Results)
*(Kết quả giả định từ tập test cases)*

| Phương pháp | Unsupported Claim Rate | Contradiction Rate | Judge Bias Detected |
|-------------|-------------------------|--------------------|---------------------|
| LLM 1-shot | 35% | 15% | Cao |
| 1 LLM Judge | 18% | 8% | Trung bình |
| **Hệ thống của chúng tôi (5 Judges + Grounding)** | **< 2%** | **< 1%** | **Thấp** |

## 5. Kết luận
- Việc phân rã thành **Claim-Evidence Matrix** giúp việc audit citation cực kỳ dễ dàng bằng code thuần (string matching).
- Việc chia thành 5 Judge (`GAP_JUDGE`, `CONTRIBUTION_JUDGE`, `EXPERIMENT_JUDGE`, `CONFERENCE_JUDGE`, `EVIDENCE_JUDGE`) ngăn việc một LLM dễ dàng "cho qua" các lỗi thí nghiệm do quá tập trung vào phần ý tưởng.

> **📝 BẠN CẦN LÀM THÊM Ở FILE NÀY:**
> - Nếu bạn có script để chạy test tự động, hãy đưa output log của bạn vào mục Kết quả thay cho bảng giả định trên.
> - Thêm 1 biểu đồ so sánh (ví dụ Pareto frontier giữa thời gian và chất lượng sinh Spec).
