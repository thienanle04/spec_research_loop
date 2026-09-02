# Idea Interpretation

## Intent
Xây dựng một hệ thống tự động tối ưu hóa prompt qua nhiều vòng lặp, sử dụng LLM làm trọng tài có đối chiếu với ground truth hoặc mẫu ví dụ, nhằm giảm thiểu việc bịa đặt các khái niệm và quan hệ nhân quả khi trích xuất từ các bài báo khoa học có cấu trúc.

## Problem
Việc trích xuất các khái niệm trừu tượng và quan hệ nhân quả từ paper khoa học bằng LLM dễ gây ra lỗi bịa đặt. Việc dùng LLM làm trọng tài đặt ra rủi ro lớn về độ tin cậy vì thiếu các tiêu chí định lượng rõ ràng để đánh giá tính 'đúng sai' của các mối liên hệ ngữ nghĩa trừu tượng, đặc biệt khi không có ground truth toàn diện.

## Research Questions
1. Làm thế nào để thiết kế một cơ chế phản hồi dựa trên LLM-as-a-judge (có tham chiếu ground truth) đủ tin cậy để đánh giá các khái niệm và quan hệ nhân quả trừu tượng, nhằm hướng dẫn quá trình tối ưu prompt tự động trong việc giảm lỗi bịa đặt?
2. Thiết kế quy trình tự động, nhiều vòng lặp, sử dụng LLM-as-a-Judge để đánh giá và tinh chỉnh cục bộ prompt, với tiêu chí dừng dựa trên tỷ lệ lỗi Fabrication so với ground truth, nhằm tối đa hóa độ chính xác trích xuất.

## Idea Decomposition

### Constraints
- **Tiêu chí dừng vòng lặp**: Đạt ngưỡng yêu cầu về tỷ lệ lỗi Fabrication (so với ground truth).
- **Cơ chế đánh giá**: Sử dụng vòng lặp phản hồi của LLM (LLM-as-a-Judge) để đánh giá trực tiếp chất lượng.
- **Chiến lược cập nhật prompt**: Tinh chỉnh cục bộ (chèn thêm ví dụ hoặc cảnh báo cụ thể cho lỗi đã gặp).
- **Phần cứng**: Chạy được trên RTX 3090.
- **Dữ liệu**: Sử dụng bộ dữ liệu có sẵn với ground truth rõ ràng.

### Open Questions
- Tối ưu một prompt hay cả pipeline?

---

## Related Work

### 1. Large Language Models as Optimizers (2023) (https://arxiv.org/abs/2309.03409)
- **What was done**: Ứng dụng OPRO để tự động tối ưu hóa prompt (instruction) nhằm tối đa hóa độ chính xác trên các bài toán trích xuất và suy luận, thay thế cho prompt thiết kế thủ công.
- **Method / Feedback**: Sử dụng LLM như một bộ tối ưu (optimizer) trong vòng lặp nhiều bước, trong đó meta-prompt chứa lịch sử các prompt trước đó và điểm đánh giá tương ứng để tạo ra prompt mới.
- **Remaining Limitation**: LLM tối ưu không khai thác hiệu quả các trường hợp lỗi trong tập huấn luyện để suy luận hướng cải thiện, khiến quá trình tối ưu bị hạn chế khi dựa vào chính xác tổng hợp thay vì phản hồi chi tiết về lỗi.

### 2. Automatic Prompt Optimization with “Gradient Descent” and Beam Search (2023) (https://arxiv.org/abs/2305.03495)
- **What was done**: Ứng dụng khung ProTeGi để tối ưu tự động prompt cho các tác vụ NLP, sử dụng dữ liệu huấn luyện và phản hồi ngôn ngữ tự nhiên từ LLM.
- **Method / Feedback**: Sử dụng gradient văn bản (textual gradients) để chỉ trích prompt hiện tại và biên tập prompt theo hướng ngữ nghĩa ngược, kết hợp tìm kiếm chùm (beam search) và lựa chọn bandit.
- **Remaining Limitation**: Hiệu quả của khung ProTeGi bị hạn chế thực tế bởi giới hạn tỷ lệ (rate limiting) trên API LLM, dẫn đến hiệu suất giảm.

### 3. Reflection-Enhanced Meta-Optimization Integrating TextGrad-style Prompt Optimization with Memory-Driven Self-Evolution (2025) (https://arxiv.org/abs/2508.18749)
- **What was done**: Đề xuất khung REMO tích hợp TextGrad, sử dụng cơ chế LLM-driven meta-controller và Reflection RAG để tối ưu hóa prompt một cách lặp đi lặp lại, với đánh giá hiệu quả trên bộ dữ liệu GSM8K.
- **Method / Feedback**: Phản hồi từ LLM (LLM-as-a-Judge/meta-controller) tổng hợp nhận thức phản ánh ở cấp epoch và sử dụng TextGrad để tinh chỉnh cục bộ prompt.
- **Remaining Limitation**: Gây ra sự gia tăng chi phí tính toán, cụ thể là thời gian huấn luyện tăng 3–5 lần so với baseline TextGrad.

### 4. Is It Time To Treat Prompts As Code? A Multi-Use Case Study For Prompt Optimization Using DSPy (2025) (https://arxiv.org/abs/2507.03620)
- **What was done**: Nghiên cứu ứng dụng khung tối ưu hóa DSPy (Declarative Self-improving Python) để tự động tạo và tinh chỉnh prompt cho năm trường hợp sử dụng, bao gồm phát hiện hallucination trong code và đánh giá prompt, nhằm cải thiện hiệu suất của LLM.
- **Method / Feedback**: Sử dụng thuật toán tối ưu hóa MIPROv2 và InferRules trong DSPy để tinh chỉnh prompt, kết hợp cơ chế đánh giá chất lượng đầu ra bằng LLM-as-a-Judge (mô hình Panel of Experts) với các tiêu chí định lượng cụ thể.
- **Remaining Limitation**: Việc cung cấp mã tham chiếu (ground truth) cho LLM trong quá trình đánh giá dẫn đến hiện tượng overfit, khiến hệ thống đánh giá sai (cho điểm 0) đối với các đoạn mã có sự khác biệt nhỏ nhưng vẫn chính xác.

---

## Gap Analysis

### Potential Gap — further validation needed
Nghiên cứu trước đây đã khám phá việc sử dụng khung DSPy để tự động tạo và tinh chỉnh prompt cho các tác vụ như phát hiện hallucination trong mã lập trình và đánh giá prompt, kết hợp cơ chế LLM-as-a-Judge để đánh giá chất lượng đầu ra bằng các tiêu chí định lượng. Chưa rõ liệu một cách tiếp cận có thể khắc phục hạn chế *“Khi mã được tạo ra khác đi đôi chút nhưng vẫn đúng, hệ thống đánh giá đã chấm sai thành số 0”* trong một đánh giá có kiểm soát hay không.

#### Supporting Sources
- **is-it-time-to-treat-2025**: *"When the generated code was slightly different but still correct, it was incorrectly evaluated as zero."* — Page 11

#### Counter-evidence Assessment
No counter-evidence source met the relevance and source-support checks. The limitations below remain plausible, but unconfirmed.

#### Gap Claims
Khi mã được tạo ra khác đi đôi chút nhưng vẫn đúng, hệ thống đánh giá đã chấm sai thành số 0.  
*Counter-evidence review: Not enough evidence to decide.*

---

## Contributions

### Contribution 1: Resource-Aware Error-Prioritized Scheduling
**Thuật toán điều phối ngân sách truy vấn ưu tiên lỗi cao.**
- **Cơ chế**: Điều phối động các bước vòng lặp để ưu tiên xử lý các phần tử có tỷ lệ lỗi fabrication cao nhất, giảm thiểu số lần gọi LLM.
- **Liên hệ Gap**: Chuyển ràng buộc phần cứng RTX 3090 thành biến tối ưu hóa, đảm bảo quy trình hội tụ trong tài nguyên giới hạn khi khắc phục lỗi đánh giá sai.
- **Điểm mới**: Khác với OPRO và ProTeGi giả định API không giới hạn, cơ chế này tích hợp trực tiếp giới hạn tài nguyên GPU vào logic chọn mẫu lỗi và dừng.
- **Kiểm chứng**: So sánh với OPRO và ProTeGi; quan sát thời gian chạy và VRAM; từ chối nếu gây lỗi OOM, không hội tụ kịp thời, hoặc tăng tỷ lệ lỗi fabrication.

### Contribution 2: Error-Pair Insertion Mechanism
**Cơ chế chèn cặp ví dụ lỗi (Error-Pair) đối chiếu ground truth.**
- **Cơ chế**: Tự động trích xuất và chèn các cặp (lỗi fabrication, ground truth) cụ thể vào prompt để tinh chỉnh cục bộ thay vì dùng phản hồi tổng quát.
- **Liên hệ Gap**: Giải quyết hạn chế đánh giá 'chấm 0 sai' bằng cách biến lỗi cụ thể thành ràng buộc cứng, giúp hệ thống nhận diện sự sai lệch dù khác biệt nhẹ.
- **Điểm mới**: Khác với OPRO và TextGrad chỉ dùng lịch sử điểm số hoặc gradient văn bản tổng quát, cơ chế này đưa bằng chứng phản ví dụ cụ thể vào lệnh.
- **Kiểm chứng**: So sánh với prompt tĩnh và OPRO; quan sát tỷ lệ lỗi fabrication trên tập kiểm tra; từ chối nếu không giảm lỗi hoặc vượt ngân sách token RTX 3090.

---

## Claims & Evidence

### Claim 1: Error-Pair Mechanism Reduces Fabrication Error Rate
> **Claim:** Cơ chế chèn cặp ví dụ lỗi (Error-Pair) dựa trên ground truth giảm tỷ lệ lỗi Fabrication cao hơn so với phương pháp tinh chỉnh prompt tổng quát (như OPRO) và prompt tĩnh.

- **Baseline:**
  1. Prompt tĩnh (cơ sở ban đầu).
  2. Thuật toán OPRO (Optimization by PROmpting) sử dụng lịch sử điểm số để tinh chỉnh prompt.
- **Metric:**
  - Tỷ lệ lỗi Fabrication (Fabrication Error Rate) trên tập kiểm tra.
  - Số lượng token trung bình trong prompt.
- **Evidence:** Trên bộ dữ liệu trích xuất từ bài báo khoa học, prompt được tinh chỉnh bằng cơ chế Error-Pair cho thấy tỷ lệ lỗi Fabrication giảm đáng kể so với baseline. Cụ thể, các trường hợp mà LLM bịa đặt thông tin do sự mơ hồ hoặc khác biệt nhẹ so với ground truth được giảm thiểu do sự chèn cặp (lỗi, ground truth) cụ thể vào prompt.
- **Rejection Condition:** Tỷ lệ lỗi Fabrication không giảm hoặc tăng so với baseline OPRO; hoặc số lượng token trong prompt vượt quá giới hạn ngữ cảnh của mô hình chạy trên RTX 3090 dẫn đến lỗi OOM hoặc suy giảm hiệu suất.

---

### Claim 2: Resource-Aware Scheduling Enables Convergence within RTX 3090 Constraints
> **Claim:** Thuật toán điều phối ngân sách truy vấn ưu tiên lỗi cao (Resource-Aware Error-Prioritized Scheduling) cho phép quy trình hội tụ về ngưỡng lỗi Fabrication mục tiêu trong giới hạn tài nguyên VRAM và thời gian của RTX 3090, vượt trội hơn so với các phương pháp giả định API không giới hạn.

- **Baseline:**
  1. OPRO chạy đầy đủ các vòng lặp cho đến khi hội tụ (giả định tài nguyên vô hạn).
  2. ProTeGi chạy đầy đủ các vòng lặp.
- **Metric:**
  - Thời gian chạy tổng (end-to-end time).
  - Đỉnh VRAM sử dụng (Peak VRAM Usage).
  - Tỷ lệ hội tụ (số vòng lặp cần để đạt ngưỡng lỗi mục tiêu).
- **Evidence:** Khi áp đặt giới hạn tài nguyên (ví dụ: tối đa 20GB VRAM, 2 giờ chạy), thuật toán điều phối mới ưu tiên xử lý các phần tử có tỷ lệ lỗi cao nhất, dẫn đến sự giảm lỗi toàn cục nhanh hơn trong số lần gọi LLM giới hạn. Ngược lại, OPRO/ProTeGi bị dừng sớm do OOM hoặc không kịp thời gian, để lại tỷ lệ lỗi cao hơn.
- **Rejection Condition:** Thuật toán gây ra lỗi OOM trên RTX 3090; hoặc không thể đạt được ngưỡng lỗi Fabrication mục tiêu trong ngân sách thời gian/tài nguyên đã quy định, trong khi baseline (nếu chạy đủ tài nguyên ảo) có thể đạt được.

---

## Experiment Planning

### Experiment 1: Error-Pair Mechanism vs. Baselines
- **Action:** Chạy quy trình tối ưu trên bộ dữ liệu trích xuất khoa học với 3 nhóm: Prompt tĩnh, OPRO và Error-Pair. Mỗi nhóm thực hiện tối đa 5 vòng lặp phản hồi, sử dụng tập kiểm tra 200 mẫu có ground truth để đánh giá sau mỗi vòng.
- **Objective:** Đo và so sánh Tỷ lệ lỗi Fabrication (FER) và độ dài trung bình của prompt token giữa 3 nhóm phương pháp.
- **Significance:** Kết quả xác nhận tính vượt trội của Error-Pair trong việc xử lý các trường hợp sai lệch nhẹ mà OPRO bỏ qua, hoặc bác bỏ claim nếu FER không cải thiện đáng kể.

### Experiment 2: Resource-Aware Scheduling vs. Baselines
- **Action:** Triển khai thuật toán mới và baseline OPRO/ProTeGi trên GPU RTX 3090 với giới hạn cứng 20GB VRAM và 2 giờ chạy. Theo dõi số vòng lặp cần thiết để đạt ngưỡng lỗi mục tiêu và đo peak VRAM trong quá trình chạy.
- **Objective:** Xác định thời gian hội tụ, mức sử dụng VRAM tối đa và tỷ lệ lỗi cuối cùng của thuật toán trong điều kiện tài nguyên giới hạn.
- **Significance:** Bằng chứng cho thấy thuật toán khả thi về mặt phần cứng và tối ưu hóa chi phí, hoặc bác bỏ nếu gây ra lỗi OOM hoặc không đạt ngưỡng lỗi khi baseline (nếu có đủ tài nguyên) có thể đạt được.

---

## Feasibility

**Experiment Plan is Feasible**

Kế hoạch thử nghiệm khả thi về mặt học thuật và kỹ thuật, với điều kiện nhóm nghiên cứu có sẵn bộ dữ liệu khoa học với ground truth chất lượng cao và mô hình LLM phù hợp (dự đoán là các mô hình mở tham số vừa phải, khoảng 7B-13B tham số, chạy được trên RTX 3090). Việc so sánh với OPRO và ProTeGi là hợp lý vì đây là các baseline tiêu chuẩn trong lĩnh vực prompt optimization. Tuy nhiên, tính khả thi cao độ phụ thuộc vào việc kiểm soát tốt độ dài prompt và chiến lược batch inference để tránh OOM khi chạy 3 phương pháp trên cùng một phần cứng giới hạn.

---

## Required Resources
- **GPU**: NVIDIA RTX 3090 (24GB VRAM) hoặc tương đương.
- **Dataset**: Bộ dữ liệu trích xuất từ bài báo khoa học với tối thiểu 200 mẫu kiểm tra (test set) và tập huấn luyện (train set) đủ lớn cho các vòng lặp tối ưu, có kèm theo ground truth chi tiết cho từng trường hợp.
- **Model**: Mô hình LLM mã mở (Open-source LLM) có kích thước phù hợp để chạy inference trên 20GB VRAM (ví dụ: LLaMA-3-8B, Mistral-7B, hoặc các phiên bản quantized của các mô hình lớn hơn), hỗ trợ cả vai trò trích xuất (Extraction) và đánh giá (Judge).
- **Software**: Môi trường phần mềm (Python, PyTorch/Transformers) và mã nguồn tham chiếu cho các thuật toán OPRO và ProTeGi để thiết lập baseline chính xác.
- **Compute Time**: Thời gian tính toán dự kiến khoảng 2-4 giờ cho mỗi phương pháp để hoàn thành 5 vòng lặp tối ưu trên tập dữ liệu thử nghiệm.

---

## Potential Bottlenecks
1. **Rủi ro OOM (Out of Memory)**: Khi chèn nhiều cặp ví dụ lỗi (Error-Pair) hoặc các prompt tối ưu hóa dài từ OPRO, độ dài token có thể vượt quá giới hạn ngữ cảnh hoặc bộ nhớ của mô hình, đặc biệt khi thực hiện các bước suy luận phức tạp.
2. **Chi phí thời gian cho LLM-as-a-Judge**: Việc gọi LLM để đánh giá chất lượng sau mỗi vòng lặp trên 200 mẫu có thể tốn nhiều thời gian, làm chậm tiến độ thử nghiệm và khó đạt được trong giới hạn 2 giờ nếu không tối ưu hóa kỹ thuật inference (như vLLM).
3. **Tính nhất quán của đánh giá (Evaluation Consistency)**: LLM-as-a-Judge có thể đưa ra các đánh giá không nhất quán (noise), dẫn đến tín hiệu tối ưu hóa nhiễu và khó xác định liệu sự cải thiện FER là do cơ chế Error-Pair hay do biến thiên ngẫu nhiên của bộ đánh giá.
4. **Khó khăn trong việc triển khai OPRO/ProTeGi đúng chuẩn**: Các baseline này thường được thiết kế cho các tác vụ cụ thể (như toán học hay lập trình). Việc áp dụng chúng vào task trích xuất văn bản khoa học có thể yêu cầu các điều chỉnh (fine-tuning) trong logic đánh giá để đảm bảo tính công bằng (fair comparison).
5. **Sự phụ thuộc vào chất lượng Ground Truth**: Nếu ground truth trong bộ dữ liệu khoa học không rõ ràng hoặc có nhiều ý kiến khác nhau (subjective), việc xác định lỗi Fabrication sẽ trở nên mơ hồ và khó đo lường chính xác.

---

## Mitigation Strategies
- **Quantization**: Sử dụng kỹ thuật Quantization (INT8/INT4) cho mô hình LLM để giảm thiểu sử dụng VRAM, đảm bảo dự phòng bộ nhớ cho bộ đệm (KV-cache) khi xử lý các prompt dài.
- **High-Performance Inference**: Triển khai thư viện suy luận hiệu suất cao như vLLM hoặc TGI để tăng tốc độ xử lý song song (batching) cho các bước đánh giá và trích xuất, giúp giảm thời gian chạy thực tế xuống dưới ngưỡng 2 giờ.
- **Token Budgeting**: Áp dụng chiến lược 'Early Stopping' và 'Token Budgeting': Đặt giới hạn cứng cho số lượng cặp ví dụ lỗi được chèn vào prompt và cắt bớt (truncation) thông minh các phần không quan trọng để duy trì độ dài prompt dưới ngưỡng an toàn (ví dụ: dưới 4k tokens).
- **Reduce Judge Noise**: Chạy LLM-as-a-Judge với nhiệt độ (temperature) bằng 0 (hoặc rất thấp) và sử dụng đa số hóa (majority voting) với 3-5 lần gọi cho mỗi mẫu để giảm nhiễu và tăng độ tin cậy của điểm đánh giá, từ đó cải thiện chất lượng tín hiệu tối ưu hóa.
- **Ground Truth Validation**: Tiền xử lý dữ liệu và chuẩn hóa Ground Truth: Kiểm tra thủ công một phần nhỏ (ví dụ: 20 mẫu) của bộ dữ liệu để xác nhận tính khách quan của ground truth và hiệu chỉnh tiêu chí đánh giá Fabrication để tránh các trường hợp biên (edge cases) gây tranh cãi.