# Cơ chế kiểm tra Citation và Evidence (Citation Audit Mechanism)

## 1. Tổng quan

Mục tiêu của cơ chế này là kiểm tra một Claim có thực sự được Citation hỗ trợ hay không. Hệ thống không xem việc “có tài liệu tham khảo” là đủ, mà phải truy vết được chuỗi:

```text
Claim → citation_key → passage → Citation → nội dung nguồn
```

Quá trình kiểm tra gồm hai lớp: **Research Grounding** xác minh nguồn và passage; **Evidence Judge** kiểm tra quan hệ giữa Claim và passage.

## 2. Research Grounding

Khi tìm được một tài liệu, module `research` thực hiện:

1. Lưu metadata như tiêu đề, tác giả, DOI, URL và scholarly provider.
2. Resolve lại DOI/provider ID và so sánh tiêu đề để xác minh danh tính Citation.
3. Tải nội dung nguồn và lưu kèm checksum, loại nội dung và vị trí object storage.
4. Yêu cầu LLM trích một passage nguyên văn cho mỗi nhận định trong Related Work.
5. Kiểm tra passage có thật trong source text trước khi đánh dấu `grounded`.

Nếu không xác minh được nguồn hoặc passage, Citation/finding được giữ ở trạng thái `warning`, `rejected` hoặc không đủ điều kiện làm bằng chứng. Hệ thống không tự coi output của LLM là bằng chứng hợp lệ.

## 3. Evidence Judge

Evidence Judge chỉ chạy trên **Valid Spec Version**. Hệ thống tạo các bộ ba:

```json
{
  "claim_id": "<Card UUID>",
  "claim": "Nội dung Claim",
  "citation_key": "paper-2024",
  "passage": "Đoạn trích từ nguồn"
}
```

Với mỗi Claim, verifier lấy các token chữ/số dài hơn ba ký tự và kiểm tra chúng có cùng xuất hiện trong ít nhất một passage hay không. Claim không có Citation hoặc không có passage sẽ không vượt qua kiểm tra.

Nếu không có passage phù hợp, hệ thống tạo Judge Issue:

```text
finding_kind: unsupported_citation
severity: CRITICAL
target_card_id: <claim_id>
```

Evidence Judge LLM chạy thêm một lượt đánh giá theo ngữ cảnh. Tuy nhiên, LLM không thể xóa hoặc hạ mức lỗi do verifier tạo. Finding Kind ngoài catalog bị loại và `unsupported_citation` luôn có Severity tối thiểu là `CRITICAL`.

## 4. Kết quả và vòng sửa

Sau khi năm Judge hoàn tất, Aggregator đưa các lỗi vào Aggregator Report. Chỉ cần còn một lỗi `CRITICAL`, Readiness sẽ fail.

Account có thể chọn Handling Option để mở lại Workflow Node liên quan, sửa Claim hoặc Citation, Confirm lại và chạy lại Judge. Handling Option chỉ đưa ra gợi ý; hệ thống không tự sửa nội dung hoặc tự xóa lỗi.

CRITICAL không xóa Spec Version và không chặn hoàn toàn việc export. Tuy nhiên, mỗi lần export khi còn CRITICAL đều phải ghi nhận một **Critical Export Confirmation**.
