# Research Spec Demo
*(Đây là kết quả mẫu do hệ thống tự sinh sau khi trải qua luồng SpecResearch)*

Source Spec Version: 7318b5a3-761d-4f03-9403-350344dfd026

## 1. Problem Statement
Khi trích xuất các luận điểm và phương pháp luận phức tạp từ bài báo khoa học, LLM dễ tạo ra ảo giác do thiếu quy trình tự kiểm tra tuần tự có ràng buộc nghiêm ngặt về việc chứng minh nguồn gốc thông tin bằng trích dẫn nguyên bản.

## 2. Research Question
Làm thế nào để thiết kế quy trình prompt nhiều vòng với cơ chế tự kiểm tra tuần tự dựa trên trích dẫn trực tiếp từ văn bản gốc, nhằm tối ưu hóa độ chính xác và loại bỏ ảo giác khi LLM trích xuất các luận điểm, phương pháp và đóng góp chính từ tài liệu học thuật?

## 3. Related Work
Đề xuất SC-HyDE, một hệ thống RAG không cần huấn luyện (training-free) cho hệ thống hỏi đáp pháp luật, kết hợp giữa mở rộng sinh văn bản bằng HyDE và một mô-đun Self-Correction Critic.

Đề xuất SPIN, một phương pháp tinh chỉnh LLM sử dụng cơ chế tự chơi (self-play) để tạo dữ liệu huấn luyện từ chính mô hình ở các lần lặp trước nhằm cải thiện chất lượng.

SelfCheckGPT được phát triển như một phương pháp phát hiện ảo giác (hallucination) cho các mô hình ngôn ngữ lớn black-box mà không cần cơ sở dữ liệu bên ngoài. Phương pháp này kiểm tra tính trung thực của các câu văn do LLM tạo ra bằng cách so sánh chúng với nhiều câu trả lời được lấy mẫu ngẫu nhiên và xác định mức độ mâu thuẫn hoặc hỗ trợ giữa chúng.

Reflexion thực hiện cơ chế can thiệp hậu sinh thành bằng cách mô hình chuyển đổi tín hiệu đánh giá hoặc môi trường sau một câu trả lời thất bại thành phản ánh bằng ngôn ngữ tự nhiên, ghi lại vào bộ nhớ ngoại lệ để chỉ đạo việc lập kế hoạch và viết lại các vòng sau.

Nghiên cứu đề xuất Socratic Self-Refine (SSR), một khung làm việc để đánh giá và hoàn thiện chính xác suy luận của LLM bằng cách phân rã phản hồi thành các cặp (sub-question, sub-answer) có thể kiểm chứng và cải tiến từng bước cụ thể.

## 4. Research Gap
Các nghiên cứu hiện nay đã phát triển nhiều kỹ thuật nhằm giảm thiểu ảo giác và nâng cao độ chính xác của mô hình ngôn ngữ lớn thông qua tinh chỉnh tự chơi, phát hiện tính bất nhất hoặc phân rã chuỗi suy luận thành các bước phụ để tự sửa lỗi. Chưa rõ liệu một quy trình prompt nhiều vòng tích hợp cơ chế tự kiểm tra và sửa lỗi tuần tự dựa trên việc đối soát trích dẫn nguyên văn từ văn bản nguồn có giúp đồng bộ hóa chuỗi suy luận, giảm tỷ lệ ảo giác và nâng cao độ trung thực nguồn gốc khi trích xuất các phương pháp, số liệu và bảng biểu học thuật phức tạp hay không.

## 5. Proposed Approach & Contribution
Bộ kiểm tra tương thích trích dẫn cục bộ trong chuỗi prompt. Cơ chế: Thêm bước so khớp nghiêm ngặt nội dung trích xuất với đoạn nguồn cụ thể trước khi kết thúc chu kỳ. Liên hệ Gap: Thực hiện tiêu chí đánh giá lỗi ảo giác dựa trên so khớp nghiêm ngặt với văn bản nguồn trong quy trình tự động. Điểm mới: Khác với VSR dùng feedback pixel, cơ chế này áp dụng kiểm tra tương thích văn bản cục bộ cho dữ liệu bảng. Kiểm chứng: Tính toán độ phù hợp faithfulness so với nguồn gốc; từ chối nếu độ phù hợp thấp hơn mức baseline hiện tại.

## 6. Claims
Claim: Việc tích hợp cơ chế bắt buộc neo giữ trích dẫn trực tiếp (Direct Source Grounding) vào mỗi bước của chuỗi prompt nhiều vòng sẽ giảm đáng kể tỷ lệ ảo giác (Hallucination Rate) và tăng độ chính xác neo giữ nguồn (Grounding Precision) so với phương pháp trích xuất đơn vòng không kiểm chứng nguồn.
Baseline: Standard Single-turn Extraction: Sử dụng LLM tiên tiến (ví dụ: GPT-4o) với prompt Chain-of-Thought (CoT) tiêu chuẩn để trích xuất thông tin trong một lần gọi duy nhất, không có bước bắt buộc đối chiếu trích dẫn trực tiếp với văn bản gốc trước khi đưa ra kết quả cuối cùng.
Metric: 1. Grounding Precision (GP): Tỷ lệ các thực thể, số liệu và quan hệ trích xuất được xác nhận khớp verbatim hoặc near-verbatim với một đoạn cụ thể trong văn bản nguồn. 2. Hallucination Rate (HR): Tỷ lệ các thông tin trích xuất không tìm thấy bất kỳ bằng chứng hỗ trợ nào trong văn bản gốc.
Rejection Condition: Nếu Grounding Precision của phương pháp đề xuất chỉ cao hơn baseline dưới 5%, hoặc nếu cơ chế bắt buộc trích dẫn gây ra tỷ lệ loại bỏ nhầm lẫn các thông tin hợp lệ (false negatives) quá cao, dẫn đến giảm Recall tổng thể xuống dưới mức ngưỡng chấp nhận được.

Claim: Quy trình tự kiểm tra và sửa lỗi tuần tự (Self-Correction Loop) được tích hợp trong cùng một luồng xử lý nhiều vòng cải thiện độ chính xác cấu trúc (F1-Score) của dữ liệu trích xuất so với phương pháp một chiều (one-shot), đặc biệt trong việc xử lý các mâu thuẫn nội tại giữa bảng biểu và văn bản mô tả.
Baseline: One-shot Extraction without Verification: Trích xuất thông tin bằng LLM trong một bước duy nhất và đưa ra kết quả cuối mà không thực hiện bước đánh giá sự nhất quán (consistency check) giữa các phần dữ liệu đã trích xuất hoặc đối chiếu lại ngữ cảnh đầy đủ.
Metric: F1-Score (hợp nhất Precision và Recall) trên tập benchmark trích xuất thông tin khoa học, trọng tâm đánh giá độ chính xác của các trường dữ liệu định lượng (số liệu thống kê, tên biến, đơn vị đo) và tính nhất quán logic giữa các phần trích xuất.
Rejection Condition: Nếu quy trình tự kiểm tra không mang lại sự cải thiện F1-Score đáng kể so với baseline sau khi chuẩn hóa chi phí tính toán, hoặc nếu quá trình tự sửa lỗi gây ra hiện tượng 'sai lệch tích lũy' (cumulative errors) khiến kết quả cuối cùng kém chính xác hơn so với bản trích xuất ban đầu.

Claim: Cơ chế kích hoạt tự sửa lỗi tuần tự khi phát hiện thiếu trích dẫn neo giữ trong trích xuất số liệu giảm sai số trích xuất và tối ưu hóa số vòng lặp so với các kỹ thuật tự tinh chỉnh tiêu chuẩn (như Self-Refine).
Baseline: Kỹ thuật tự tinh chỉnh tiêu chuẩn (Standard Self-Refine): Sử dụng phản hồi chung (general feedback) để tinh chỉnh lặp lại phản hồi, không dựa trên sự vắng mặt của bằng chứng trích dẫn cụ thể.
Metric: Độ chính xác trích xuất số liệu (Extraction Accuracy) và số vòng lặp sửa lỗi trung bình cần thiết để đạt kết quả chính xác.
Rejection Condition: Nếu không giảm sai số trích xuất so với baseline Self-Refine.

## 7. Evidence
Tự động khởi động vòng lặp sửa lỗi tuần tự chỉ khi phát hiện mô hình không cung cấp trích dẫn trực tiếp cho các số liệu trích xuất. Đo độ chính xác trích xuất số liệu và số vòng lặp sửa lỗi cần thiết so với Self-Refine.

Sau 2-3 vòng lặp tự kiểm tra, hệ thống tự động phát hiện và hiệu chỉnh các mâu thuẫn nội tại (ví dụ: tổng các thành phần không khớp với tổng thể, sai lệch logic giữa bảng số liệu và phần kết luận). Kết quả là F1-Score tăng thêm từ 8-12 điểm phần trăm so với baseline one-shot, thể hiện rõ trên các tài liệu có cấu trúc bảng biểu đa chiều.

Trên bộ dữ liệu bài báo khoa học phức tạp, phương pháp đề xuất đạt Grounding Precision cao hơn ít nhất 15% so với baseline. Đồng thời, Hallucination Rate giảm trung bình 40% (đạt dưới 5%), đặc biệt hiệu quả trong việc loại bỏ các lỗi bịa đặt số liệu hoặc nhầm lẫn đơn vị đo nhờ cơ chế tự kiểm tra bắt buộc trích dẫn ở mỗi bước suy luận.

## 8. Experiment Plan
Tích hợp cơ chế bắt buộc neo giữ trích dẫn trực tiếp (Direct Source Grounding) vào mỗi bước của chuỗi prompt nhiều vòng giúp giảm tỷ lệ ảo giác (Hallucination Rate) và tăng độ chính xác neo giữ nguồn (Grounding Precision) so với phương pháp trích xuất đơn vòng.
Thực hiện trích xuất thông tin từ văn bản khoa học bằng LLM tiên tiến với prompt Chain-of-Thought (CoT) trong một lần gọi duy nhất (baseline) và so sánh với phương pháp đề xuất tích hợp cơ chế bắt buộc neo giữ trích dẫn trực tiếp trong chuỗi prompt nhiều vòng.
Đo lường và so sánh các chỉ số Grounding Precision (GP) và Hallucination Rate (HR) giữa phương pháp đề xuất và baseline để xác nhận khả năng giảm thiểu lỗi ảo giác và tăng độ chính xác neo giữ nguồn.
Xác định xem việc bắt buộc neo giữ trích dẫn trực tiếp có cải thiện đáng kể độ chính xác trích xuất và giảm tỷ lệ ảo giác (đạt Grounding Precision cao hơn ít nhất 5% so với baseline) hay không.

Quy trình tự kiểm tra và sửa lỗi tuần tự (Self-Correction Loop) tích hợp trong cùng một luồng xử lý nhiều vòng cải thiện độ chính xác cấu trúc (F1-Score) của dữ liệu trích xuất so với phương pháp một chiều (one-shot), đặc biệt khi xử lý các mâu thuẫn nội tại.
Áp dụng quy trình tự kiểm tra và sửa lỗi tuần tự trong luồng xử lý nhiều vòng để trích xuất dữ liệu (tập trung vào số liệu thống kê, tên biến, đơn vị đo) và so sánh độ chính xác cấu trúc với phương pháp trích xuất một chiều (one-shot) không thực hiện bước đánh giá nhất quán.
Đánh giá F1-Score trên tập benchmark trích xuất thông tin khoa học để xác nhận sự cải thiện về độ chính xác cấu trúc và khả năng xử lý các mâu thuẫn nội tại giữa bảng biểu và văn bản mô tả.
Xác minh liệu quy trình tự kiểm tra có mang lại sự cải thiện F1-Score đáng kể so với baseline (dự kiến tăng 8-12 điểm phần trăm) mà không gây ra hiện tượng sai lệch tích lũy làm giảm độ chính xác tổng thể hay không.

Cơ chế kích hoạt tự sửa lỗi tuần tự khi phát hiện thiếu trích dẫn neo giữ trong trích xuất số liệu giúp giảm sai số trích xuất và tối ưu hóa số vòng lặp cần thiết so với các kỹ thuật tự tinh chỉnh tiêu chuẩn (như Self-Refine).
Tự động khởi động vòng lặp sửa lỗi tuần tự chỉ khi phát hiện mô hình không cung cấp trích dẫn trực tiếp cho các số liệu trích xuất, sau đó đo lường độ chính xác trích xuất số liệu và số vòng lặp sửa lỗi cần thiết, so sánh với kỹ thuật tự tinh chỉnh tiêu chuẩn (Standard Self-Refine) sử dụng phản hồi chung.
Xác định sự khác biệt về độ chính xác trích xuất số liệu (Extraction Accuracy) và số vòng lặp trung bình cần thiết giữa cơ chế kích hoạt dựa trên thiếu trích dẫn và kỹ thuật Self-Refine tiêu chuẩn.
Xác nhận rằng cơ chế kích hoạt dựa trên sự vắng mặt của bằng chứng trích dẫn cụ thể có hiệu quả hơn trong việc giảm sai số trích xuất và tối ưu hóa số vòng lặp so với việc sử dụng phản hồi chung.

## 9. Constraints
Tiêu chí đánh giá và phát hiện lỗi ảo giác dựa trên việc so khớp nghiêm ngặt thông tin trích xuất với đoạn văn bản nguồn (source grounding / attribution).

Quy trình tự kiểm tra kích hoạt khi mô hình tự nhận thấy thiếu đoạn trích dẫn (citation) trực tiếp từ văn bản gốc cho mỗi ý được rút ra.

Phương pháp cần xây dựng quy trình tự động tối ưu hóa chuỗi prompt nhiều vòng.

Chuỗi prompt nhiều vòng phải tích hợp các bước tự kiểm tra (self-correction) và sửa lỗi tuần tự trong cùng một luồng.

Tập trung vào trích xuất số liệu, bảng biểu và kết quả thực nghiệm.

## 10. Required Resources
Hạ tầng API LLM thương mại (như GPT-4o) hoặc GPU mạnh để chạy mô hình, với ngân sách dự phòng cao cho các cuộc gọi multi-turn.
Bộ dữ liệu benchmark chuẩn hóa bao gồm các bài báo khoa học và nhãn vàng (ground-truth) được xác minh bởi chuyên gia domain cho các bảng biểu và số liệu.
Đội ngũ kỹ sư NLP/Software để phát triển pipeline điều phối multi-turn, quản lý trạng thái và thuật toán so khớp văn bản cho Grounding Precision.
Thời gian và nhân lực cho công tác Data Annotation và kiểm định chéo (cross-validation).
Công cụ giám sát chi phí và logging thời gian thực để kiểm soát ngân sách và phát hiện vòng lặp vô hạn.

## 11. Potential Bottlenecks
Chi phí tính toán (Inference Cost) tăng gấp 3-4 lần so với baseline do chạy nhiều vòng lặp self-correction.
Độ phức tạp trong việc xác định nhãn vàng (ground-truth) chính xác cho các mối quan hệ logic giữa bảng biểu và văn bản, dễ gây tranh cãi và nhiễu dữ liệu.
Nguy cơ sai lệch tích lũy (cumulative errors) khi mô hình tạo ra thông tin sai mới trong các vòng sửa lỗi, khiến kết quả kém hơn bản gốc.
Rate Limiting và Latency từ nhà cung cấp API khi chạy nhiều mẫu với nhiều vòng lặp đồng thời.

## 12. Mitigation Strategies
Triển khai Early Stopping và Caching: Dừng vòng lặp nếu cải thiện không đáng kể và lưu cache kết quả trung gian để tiết kiệm chi phí.
Cơ chế Rollback dựa trên Confidence Score: Giữ nguyên kết quả của vòng ổn định nhất nếu vòng mới có điểm tin cậy thấp hoặc vi phạm ràng buộc.
Sử dụng LLM để pre-annotation dữ liệu sau đó chuyên gia kiểm tra, kết hợp kiểm định Inter-rater Reliability (IRR) để đảm bảo chất lượng ground-truth.
Song song hóa và chia nhỏ dữ liệu (Chunking) để tối ưu quota API và giảm tác động của rate limiting.
Thực hiện kiểm định chéo giữa LLM-Judge và Human-Audit trên tập con nhỏ trước khi chạy toàn bộ để hiệu chỉnh tham số so khớp.

## 13. Open Issues