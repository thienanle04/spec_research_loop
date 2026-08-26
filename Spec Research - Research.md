Trong đồ án **SpecResearch Loop**, việc chọn nguồn dữ liệu và bóc tách tài liệu khoa học đóng vai trò quyết định đến độ chính xác của **Related Work (Bước 3\)**, tính chân thực của **Research Gap (Bước 4\)**, và khả năng xác thực bằng chứng của **Evidence Judge (Bước 5 & 9\)**.  
Dưới đây là các **nguồn API/Repository uy tín** và **chiến lược bóc tách tài liệu** phù hợp nhất để xây dựng hệ sinh thái RAG/Retrieval cho ứng dụng:

### **1\. Các nguồn dữ liệu & API học thuật uy tín hàng đầu**

| Nguồn / API | Mục đích chính trong SpecResearch Loop | Điểm mạnh kỹ thuật |
| :---- | :---- | :---- |
| **Semantic Scholar API** *(Khuyên dùng làm nguồn chính)* | Tra cứu bài báo, tìm bài liên quan, bóc tách tóm tắt (TL;DR), trích xuất đồ thị trích dẫn (Citation Graph). | • API miễn phí, dễ tích hợp. • Có sẵn citationCount, influentialCitationCount, tldr, fieldsOfStudy. • Cung cấp sẵn Citation Graph để tìm bài báo liên quan (Forward & Backward Citations). |
| **arXiv API** | Tìm kiếm các nghiên cứu mới nhất (State-of-the-art) trong lĩnh vực AI, NLP, CV, ML. | • Cập nhật nhanh nhất các công trình vừa công bố. • Hỗ trợ tải PDF/full-text miễn phí trực tiếp qua URL. • Phù hợp với các bài toán tối ưu LLM, Prompting, Multi-agent. |
| **OpenAlex API** | Tìm kiếm đa ngành, lập chỉ mục liên kết tác giả, tổ chức, concepts, và venues. | • Dữ liệu mở hoàn toàn (Open-source), giới hạn rate limit rất thoáng. • Phân loại cây khái niệm (Concept hierarchy) rất tốt để mở rộng truy vấn (Query Expansion). |
| **DBLP API** | Kiểm tra và xác thực độ uy tín của nguồn (Peer-reviewed status). | • Tập trung vào ngành Khoa học Máy tính (CS). • Giúp hệ thống phân biệt bài báo đã được chấp nhận tại các hội nghị Top-tier (NeurIPS, ICML, ICLR, ACL, AAAI...) với các bài preprint chưa qua bình duyệt. |
| **Papers With Code / Hugging Face Daily Papers** | Hỗ trợ **Bước 6 & 7 (Baselines & Experiment Metrics)**. | • Tra cứu leaderboard, dataset chuẩn, baseline implementations và SOTA metrics để đưa vào kế hoạch thí nghiệm. |

### **2\. Nên retrieve những phần nào trong một bài báo? (Document Chunking Strategy)**

Đề bài nêu rõ quy tắc: *“Relevant Paper $\\neq$ Supporting Evidence”*. Một bài báo tương tự về chủ đề chưa chắc đã hỗ trợ cho claim cụ thể. Do đó, thay vì chỉ retrieve toàn bộ file PDF hoặc chỉ đọc mỗi Abstract, bạn nên chia nhỏ tài liệu theo **cấu trúc section chuyên biệt**:

                         TÀI LIỆU KHOA HỌC (PAPER)  
                                    │  
    ┌──────────────────────┬────────┴─────────────┬─────────────────────┐  
    ▼                      ▼                      ▼                     ▼  
\[Abstract & Intro\]   \[Related Work\]         \[Methodology\]        \[Results & Tables\]  
(Tìm bài liên quan)  (Tìm Citation Graph)   (So sánh Baselines)   (Làm Evidence cho Claim)

> 1. Phần *Limitations & Future Work* (Để tìm Research Gap \- Bước 4):  
   * Các tác giả thường nêu rõ nhược điểm hoặc hướng chưa giải quyết được ở cuối bài báo.  
   * RAG trích xuất các câu từ phần này là bằng chứng xác thực nhất để chứng minh *“Gap này thực sự tồn tại trong y văn”* thay vì do LLM tự suy diễn.  
> 2. Phần *Results / Experiments & Tables* (Để làm Supporting Evidence \- Bước 5 & 9):  
   * Chứa các số liệu thực nghiệm, bảng so sánh baseline và ablation study.  
   * Retrieve đúng đoạn này giúp **Evidence Judge** kiểm tra xem claim (ví dụ: *“giảm 30% hallucination”*) có được bảng số liệu hỗ trợ hay không.  
> 3. Phần *Related Work & References* (Để vẽ đồ thị trích dẫn \- Bước 3):  
   * Dùng để tìm các baseline kinh điển và xây dựng bảng đối sánh tính năng (như OPRO, TextGrad, DSPy...).

### **3\. Phân cấp độ tin cậy của tài liệu (Source Credibility Scoring)**

Để hỗ trợ tính năng sáng tạo *“Cơ chế chấm độ tin cậy của nguồn”* và *“Cảnh báo nguồn quá cũ/chưa kiểm chứng”* ở Bước 3:

* **Tier 1 (High Credibility \- Ưu tiên hàng đầu):**  
  * Các bài báo đã được chấp nhận tại hội nghị/tập san uy tín (A\* / Core A venues: NeurIPS, ICML, ICLR, ACL, EMNLP, CVPR, AAAI, IEEE TPAMI, ACM Trans).  
  * Metadata nhận diện qua DBLP hoặc trường venue trong Semantic Scholar.  
* **Tier 2 (Medium Credibility \- Chấp nhận có điều kiện):**  
  * Các bài báo trên arXiv có lượt trích dẫn cao hoặc đến từ các tác giả/lab nghiên cứu uy tín.  
  * Các bài Survey / Benchmark đã được cộng đồng công nhận rộng rãi.  
* **Tier 3 (Unverified / Pre-print \- Cần gắn cờ cảnh báo):**  
  * Các bài preprint arXiv mới xuất bản chưa có phản biện và lượt trích dẫn thấp.  
  * Hệ thống vẫn cho phép đưa vào RAG nhưng gắn cờ trạng thái STATUS: PROPOSED\_UNREVIEWED để cảnh báo người dùng và Judge.

### **4\. Kiến trúc pipeline tìm kiếm và nạp tài liệu khuyến nghị**

> 1. **Khởi tạo (Seed Ingestion):**  
   * Khi người dùng nhập ý tưởng ban đầu, gọi **Semantic Scholar API** với từ khóa mở rộng (Query Expansion) để lấy 10–20 papers liên quan nhất (Abstract \+ Chunks quan trọng).  
> 2. **Lưu trữ vào CSDL:**  
   * Lưu metadata (Title, Authors, Year, Venue, Citation Count, DOI/ArXiv ID) và vector embedding của các chunks vào **PostgreSQL (pgvector)**.  
> 3. **Truy xuất theo tác vụ (Context-specific Retrieval):**  
   * Khi chạy **Gap Judge**: Chỉ lọc các chunks thuộc phần Limitations, Future Work, Abstract.  
   * Khi chạy **Evidence Judge**: Chỉ lọc các chunks thuộc phần Experiments, Results, Ablation Studies của các bài báo liên quan đến claim cần xác minh.