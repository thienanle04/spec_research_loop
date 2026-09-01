# Tập hợp các Prompt (Prompts Directory)

Dưới đây là các prompt chính được sử dụng trong hệ thống SPECRESEARCH LOOP, chia theo 2 nhóm: Nhóm sinh ý tưởng (Generators) và Nhóm đánh giá (Judges).

## 1. Nhóm Generator Prompts
*(Mẫu prompt dùng để breakdown ý tưởng mơ hồ thành Problem, RQ, Gap, Contribution)*

```text
[BẠN HÃY COPY NỘI DUNG TỪ FILE: backend/app/modules/idea/prompts.py]
VÍ DỤ BẠN CÓ THỂ ĐIỀN:
"You are a strict research mentor. Parse the user's vague idea and output a JSON representing Problem, RQ, Gap..."
```

## 2. Nhóm Judge Prompts (5 Independent Judges)

### 2.1 Gap Judge Prompt
```text
[BẠN HÃY COPY SYSTEM PROMPT DÙNG CHO GAP_JUDGE VÀO ĐÂY]
```

### 2.2 Contribution Judge Prompt
```text
[BẠN HÃY COPY SYSTEM PROMPT DÙNG CHO CONTRIBUTION_JUDGE VÀO ĐÂY]
```

### 2.3 Experiment Judge Prompt
```text
[BẠN HÃY COPY SYSTEM PROMPT DÙNG CHO EXPERIMENT_JUDGE VÀO ĐÂY]
```

### 2.4 Conference Readiness Judge Prompt
```text
[BẠN HÃY COPY SYSTEM PROMPT DÙNG CHO CONFERENCE_JUDGE VÀO ĐÂY]
```

### 2.5 Evidence Judge Prompt
```text
[BẠN HÃY COPY SYSTEM PROMPT DÙNG CHO EVIDENCE_JUDGE VÀO ĐÂY]
```

> **📝 BẠN CẦN LÀM THÊM Ở FILE NÀY:**
> - Hãy mở các file trong `backend/app/modules/judgement/` hoặc `backend/app/modules/idea/` để tìm các đoạn string chứa Prompt và dán vào các khối code bên trên. Nếu bạn cấu hình Prompt trên nền tảng LangSmith hoặc file config riêng, hãy dán nội dung tương ứng vào.
