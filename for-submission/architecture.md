# Tài Liệu Kiến Trúc (Architecture Document)

## 1. Tổng quan hệ thống (System Overview)
Hệ thống SPECRESEARCH LOOP được xây dựng theo kiến trúc **Modular Monolith** ở backend và **Single Page Application (SPA)** ở frontend. 
- **Backend:** FastAPI (Python) cung cấp API RESTful và Server-Sent Events (SSE) cho streaming.
- **Frontend:** Next.js (App Router) kết hợp React, Tailwind CSS và Shadcn/UI để xây dựng giao diện tương tác người dùng phong phú.
- **Database & Storage:** PostgreSQL cho dữ liệu quan hệ (người dùng, session, spec) và MinIO (S3-compatible) cho lưu trữ object/tài liệu (PDF, JSON log).

## 2. Cấu trúc Backend (5 Modules)
Backend được chia làm 5 module độc lập giúp phân tách rõ domain logic:
1. **Identity:** Xử lý xác thực (Email/Password, JWT Bearer).
2. **Idea:** Quản lý SSE streaming cho quá trình nhập và breakdown ý tưởng (Problem, RQ, Gap, Contribution).
3. **Research:** Tìm kiếm công trình liên quan, phân tích citation, tính toán `retrieval_score` dựa trên độ phủ token và trích xuất đoạn văn (passage extraction).
4. **Spec:** Sinh, lưu trữ và quản lý các phiên bản (Working Draft) của Research Spec.
5. **Judgement:** Hệ thống 5 Agent/Judge độc lập đóng vai trò kiểm định chất lượng spec.

## 3. Kiến trúc Frontend
Frontend phân rã theo `features/`:
- `features/loop`: Quản lý các Loop Session, hiển thị giao diện Workbench cho luồng làm việc.
- `features/research`: Hiển thị ma trận Related Work, Gap Candidate Picker.
- `features/spec`: Trình bày Claim-Evidence Matrix, Experiment Plan.
- `features/judgement`: Hiển thị lỗi từ các Judge và các Handling Option cho người dùng.

## 4. Luồng dữ liệu chính (SpecResearch Loop)
1. **Nhập ý tưởng:** Client gọi API qua `features/loop`, backend stream kết quả breakdown qua SSE.
2. **Nghiên cứu & Đối sánh:** `research` module parse tài liệu, trích xuất sections (Abstract, Method...).
3. **Phân rã Claim - Evidence:** User xác nhận các thẻ.
4. **Đánh giá (Judgement):** Bản draft gửi tới 5 Node. Các lỗi sẽ trả về dưới dạng `JudgeIssueResponse` kèm `HandlingOption`.
5. **Lưu Quyết Định & Sinh Spec:** Người dùng apply patch/options, `spec` module lưu bản Revision mới và xuất markdown cuối.

> **📝 BẠN CẦN LÀM THÊM Ở FILE NÀY:** 
> - Hãy chụp một bức ảnh Sơ đồ kiến trúc (bạn có thể vẽ bằng draw.io hoặc mermaid) và chèn link ảnh vào đây: `![Sơ đồ kiến trúc](./images/architecture.png)`.
