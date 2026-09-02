# Kết quả thí nghiệm: Gemini và SpecResearch Loop

> Trạng thái: Đã hoàn thành đánh giá từ các artifact hiện có  
> Ngày thực hiện: `01/09/2026`  

## 1. Ý tưởng dùng chung

Hai phương pháp sử dụng cùng một gói ý tưởng đã được xác nhận sau Grilling.

| Trường | Nội dung |
|---|---|
| Intent | Xây dựng hệ thống tự động tối ưu hóa prompt qua nhiều vòng lặp, dùng LLM làm trọng tài có đối chiếu ground truth hoặc mẫu ví dụ để giảm bịa đặt khái niệm và quan hệ nhân quả khi trích xuất từ bài báo khoa học có cấu trúc. |
| Problem | LLM bịa đặt thông tin (Fabrication) khi trích xuất dữ liệu từ bài báo khoa học, làm giảm độ tin cậy. |
| Research question | Thiết kế quy trình tự động, nhiều vòng lặp, sử dụng LLM-as-a-Judge để đánh giá và tinh chỉnh cục bộ prompt, với tiêu chí dừng dựa trên tỷ lệ lỗi Fabrication so với ground truth, nhằm tối đa hóa độ chính xác trích xuất. |
| Constraints | Dùng LLM-as-a-Judge; dừng theo ngưỡng Fabrication; cập nhật prompt bằng ví dụ/cảnh báo lỗi; dùng dataset có ground truth; chạy được trên RTX 3090. |
| Open questions | Nên tối ưu một prompt hay toàn bộ pipeline? |

## 2. Cấu hình thực nghiệm

| Phương pháp | Model/chế độ | Output |
|---|---|---|
| Gemini | Gemini Flash | `gemini-spec-research.md` |
| SpecResearch Loop | Qwen3.6-27B |`proposed-spec-research.md`|

Quy ước chạy:

- Gemini nhận prompt, không chỉnh sửa output sau lần sinh đầu tiên.
- SpecResearch Loop bắt đầu từ gói ý tưởng sau Grilling và tiếp tục từ Related work.
- Independent Judges chưa được chạy.

## 3. Điểm đánh giá

Thang điểm: 1 là rất yếu, 5 là rất tốt. Đây là audit nội dung hiện có, chưa phải điểm chấm mù bởi chuyên gia độc lập.

| Tiêu chí | Gemini | SpecResearch Loop | Nhận xét |
|---|---:|---:|---|
| Problem và research question | 4 | 4 | Cả hai đều rõ và bám gói ý tưởng; SpecResearch Loop bổ sung câu hỏi về độ tin cậy của Judge nhưng làm phạm vi rộng hơn baseline chung. |
| Gap và contribution | 3 | 2 | Gemini có chuỗi gap–contribution tương đối rõ nhưng một số phát biểu novelty còn rộng. Gap của SpecResearch Loop lấy lỗi chấm mã nguồn làm trung tâm nên lệch khỏi bài toán trích xuất khoa học; hai contribution chưa nối chặt với gap này. |
| Claims và evidence | 4 | 3 | Cả hai có nguồn hợp lệ theo kiểm tra thủ công. Gemini có claim, baseline, metric và ngưỡng thành công rõ hơn; SpecResearch Loop có rejection condition nhưng phần “Evidence” diễn đạt kết quả chưa chạy như đã quan sát và Claim 2 đặt điều kiện so sánh chưa công bằng. |
| Experiment plan | 3 | 2 | Gemini nêu dataset, split, model, baseline, metric, năm seed và số vòng lặp, nhưng PubMedQA là QA chứ không phải relation extraction. SpecResearch Loop chưa chỉ định dataset, split, seed, ngưỡng FER hoặc protocol held-out rõ ràng. |
| Feasibility | 3 | 3 | Cả hai đề cập RTX 3090, quantization và rủi ro OOM, nhưng các ước lượng VRAM/thời gian mới ở mức dự kiến và chưa có benchmark thực thi. |
| **Trung bình** | **3.4** | **2.8** | **Gemini cao hơn 0.6 điểm trong audit tài liệu này.** |

### Điểm tổng hợp

`Quality score = trung bình 5 tiêu chí`

| Phương pháp | Quality score /5 | Chênh lệch so với Gemini |
|---|---:|---:|
| Gemini | 3.4 | 0.0 |
| SpecResearch Loop | 2.8 | -0.6 |

`Score difference (SpecResearch Loop − Gemini) = 2.8 − 3.4 = -0.6`

## 4. Kiểm tra citation

Chọn ngẫu nhiên tối đa 10 citation trong mỗi spec. Một citation chỉ được tính là hợp lệ khi nguồn tồn tại và nội dung nguồn hỗ trợ đúng nhận định đi kèm.

| Phương pháp | Số citation kiểm tra | Nguồn tồn tại | Hỗ trợ đúng claim | Valid citation rate |
|---|---:|---:|---:|---:|
| Gemini | 10 | 10 | 10 | 100% |
| SpecResearch Loop | 4 | 4 | 4 | 100% |

`Valid citation rate = số citation tồn tại và hỗ trợ đúng claim / số citation đã kiểm tra`

Theo kết quả kiểm tra thủ công của người thực hiện, cả hai output đều có đủ URL/DOI, các nguồn được kiểm tra đều tồn tại và hỗ trợ đúng claim; không ghi nhận citation có vấn đề trong mẫu kiểm tra.

## 5. Completeness

Đánh dấu `1` nếu phần có nội dung hợp lệ và `0` nếu thiếu hoặc chỉ có placeholder.

| Phần bắt buộc | Gemini | SpecResearch Loop |
|---|---:|---:|
| Problem | 1 | 1 |
| Research question | 1 | 1 |
| Related work | 1 | 1 |
| Research gap | 1 | 1 |
| Proposed contribution | 1 | 1 |
| Claims–evidence | 1 | 1 |
| Experiment plan | 1 | 1 |
| Feasibility | 1 | 1 |
| Limitations/open questions | 1 | 1 |
| **Completeness /9** | **9/9** | **9/9** |

Completeness chỉ đo sự hiện diện của nội dung, không khẳng định nội dung đúng hoặc đủ chất lượng.

## 6. Bảng kết quả cuối

| Phương pháp | Quality /5 | Valid citations | Completeness /9 |
|---|---:|---:|---:|
| Gemini | 3.4 | 100% | 9/9 |
| SpecResearch Loop | 2.8 | 100% | 9/9 |

## 7. Phân tích định tính

### Gemini

- Điểm mạnh: cấu trúc đủ chín phần; claim có ngưỡng định lượng; experiment plan nêu rõ dataset, split, model, baseline, metric, số seed và số vòng lặp; citation có URL/DOI và đã được kiểm tra hợp lệ.
- Điểm yếu: scope chuyển mạnh sang biomedical relation extraction; PubMedQA không phù hợp trực tiếp với task trích xuất quan hệ; novelty/gap có phát biểu rộng; feasibility và throughput chưa có benchmark hỗ trợ.
- Lỗi điển hình: chọn dataset có ground truth nhưng không cùng dạng đầu ra với task mục tiêu, làm protocol khó áp dụng thống nhất giữa PubMedQA và BioRED.

### SpecResearch Loop

- Điểm mạnh: nêu rõ rủi ro Judge noise, OOM, prompt bloating và mitigation; claim có baseline, metric và rejection condition; contribution chú ý trực tiếp tới giới hạn RTX 3090; citation đã được kiểm tra hợp lệ.
- Điểm yếu: gap dựa trên lỗi đánh giá code nên không khớp chặt với trích xuất khái niệm/quan hệ nhân quả; experiment plan thiếu dataset, split, model cố định, seed và ngưỡng thành công.
- Lỗi điển hình: phần Evidence và Claim 2 diễn đạt kết quả chưa chạy như sự thật đã quan sát; baseline “tài nguyên vô hạn” không tạo phép so sánh công bằng với phương pháp bị giới hạn 20 GB/2 giờ.

## 9. Kết luận

> Trong audit dựa trên artifact hiện có, Gemini đạt Quality score `3.4/5`, cao hơn SpecResearch Loop `0.6` điểm. Cả hai đạt Valid citation rate `100%` theo kiểm tra thủ công và Completeness `9/9`. Kết quả hiện tại không cho thấy SpecResearch Loop tốt hơn baseline trong case study này.

Do dataset chỉ gồm một ý tưởng, kết quả này chỉ có giá trị cho case study đã thực hiện và không chứng minh rằng một phương pháp tốt hơn trong mọi trường hợp.
