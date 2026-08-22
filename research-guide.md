# Lập kế hoạch module research

## 1. Chốt boundary trước khi code

Research Workflow gồm đúng 3 Workflow Node:

| Workflow Node | Dữ liệu/chức năng chính | Nơi xác nhận |
|---|---|---|
| `research_inputs` | Keywords, preferred sources | `loop.confirm` |
| `related_work` | Tìm kiếm, đọc, phân tích, verify Citation, related-work matrix | `loop.confirm` |
| `gap` | Đề xuất Gap, giải thích, dẫn nguồn, lựa chọn/Edit/Other | `loop.confirm` |

Theo kiến trúc hiện tại:

- `research` sở hữu generate/SSE, Citation và logic phân tích related work.
- `loop` tiếp tục sở hữu Loop Session, Working Draft, Card, Decision, prepare, confirm và stale invalidation.
- Gap được lưu dưới dạng `CardKind.GAP`, không tạo bảng Gap riêng.
- Không tạo endpoint confirm trong `research`; frontend gọi `/api/loop/.../confirm`.

Luồng này đã được mô tả tại [workflow.mmd](/D:/spec_research_loop/docs/for-human/workflow.mmd:22) và [backend.mmd](/D:/spec_research_loop/docs/for-human/backend.mmd:103).

## 2. Sửa integration seam trước

Có ba điểm trong hạ tầng hiện tại cần xử lý trước khi Citation thực sự tham gia versioning:

1. Tất cả Workflow Node hiện đang được bind vào cùng một `NoOpStagePort` tại [loop/deps.py](/D:/spec_research_loop/backend/app/modules/loop/deps.py:9).

2. Hash khi confirm hiện chỉ gồm narrative và Card snapshot; thay đổi Citation nhưng không đổi narrative có thể không tạo Stage Revision mới ([loop/service.py](/D:/spec_research_loop/backend/app/modules/loop/service.py:305)).

3. Context Projection hiện chỉ gọi projector của node đích, chưa gọi projector của từng upstream node. Vì thế module `spec` hoặc `judgement` chưa thể nhận Citation đã confirm ([loop/service.py](/D:/spec_research_loop/backend/app/modules/loop/service.py:445)).

Nên mở rộng [StagePort](/D:/spec_research_loop/backend/app/ports/stage.py:8) theo hướng:

- Port được tạo với cùng `AsyncSession` mà `LoopService` đang dùng để `freeze` nằm trong cùng transaction.
- Thêm `fingerprint()` để typed rows như Citation tham gia freeze hash.
- `project()` nhận thêm `revision_id`; `None` nghĩa là working rows.
- `LoopService.project_context()` gọi port tương ứng của từng upstream Node Head đang `current`.
- Bind `ResearchStagePort` cho `research_inputs`, `related_work`, `gap`.

Đây là prerequisite quan trọng nhất để module vừa độc lập vừa tích hợp đúng.

## 3. Thiết kế contract và dữ liệu backend

Nên thêm `backend/app/modules/research/schemas.py` và định nghĩa trước các schema sau.

### Research inputs

Lưu trong `working_draft_narrative`:

```json
{
  "keywords": ["claim verification", "prompt optimization"],
  "preferred_sources": {
    "peer_reviewed_papers": true,
    "official_proceedings": true,
    "author_materials": true,
    "sourced_surveys": true
  }
}
```

### Citation

Tối thiểu nên có:

- `id`, `citation_key` ổn định qua các revision.
- `session_id`.
- `stage_revision_id`: `NULL` là working set.
- `title`, `authors`, `year`, `venue`.
- `doi`, `url`, `provider`, `provider_source_id`.
- `abstract`, `retrieved_at`.
- `verification_status`: pending/verified/warning/rejected.
- Metadata gốc từ nguồn.

Không chỉ lưu Citation trong narrative JSON vì yêu cầu cần tìm kiếm, quản lý, verify và liên kết nguồn.

### Related-work finding

Nên có bảng riêng hoặc ít nhất typed structure chứa:

- Citation liên quan.
- “Đã làm gì?”
- Phương pháp/feedback sử dụng.
- Hạn chế.
- Mức liên quan tới Research Question.
- Đoạn nguồn hỗ trợ.
- Confidence và trạng thái verify.

Điều này đáp ứng yêu cầu “mỗi nhận định phải liên kết với nguồn cụ thể” tại [TOPIC.md](/D:/spec_research_loop/TOPIC.md:175).

### Gap Card

Body của Gap Card nên có:

```json
{
  "statement": "...",
  "prior_work": "...",
  "limitation": "...",
  "importance": "...",
  "testability": "...",
  "supporting_citation_keys": ["..."],
  "status": "proposed"
}
```

Bốn trường `prior_work`, `limitation`, `importance`, `testability` giúp tránh kiểu Gap “không tìm thấy paper giống hệt nên coi là Gap”.

## 4. Tách external provider để test không cần mạng

Tạo module-local port, ví dụ:

```text
backend/app/modules/research/
├── ports.py
├── adapters/
│   ├── fake_source.py
│   └── openalex.py hoặc semantic_scholar.py
```

Các interface chính:

- `ScholarlySourcePort.search()`
- `ScholarlySourcePort.get_source()`
- `CitationVerifier.verify()`
- Dùng `LlmPort` hiện có cho tạo query, phân tích và đề xuất Gap.

Trong automated test luôn dùng:

- `FakeScholarlySourcePort`.
- `FakeLlmPort`.
- Fixture JSON cố định trong `backend/tests/fixtures/research/`.

Live API chỉ dùng cho smoke test có marker riêng, không chạy mặc định. Như vậy không cần API key, internet hoặc module khác.

## 5. API đề xuất

REST cho thao tác ngắn:

```text
GET    /api/research/sessions/{id}/citations
POST   /api/research/sessions/{id}/citations
PATCH  /api/research/sessions/{id}/citations/{citation_id}
DELETE /api/research/sessions/{id}/citations/{citation_id}
POST   /api/research/sessions/{id}/citations/{citation_id}/verify
```

SSE cho công việc dài:

```text
POST /api/research/sessions/{id}/nodes/{node}/generate
```

Chỉ chấp nhận ba node của research. Request nên có `expected_version`; service phải kiểm tra:

- Account sở hữu Loop Session.
- Node đúng là Working Draft hiện tại.
- Version không conflict.
- Upstream Node Heads đều current.

Event SSE nên ổn định ngay từ đầu:

```text
progress
citation_upsert
draft_patch
warning
done
error
```

Frontend SSE hiện chỉ hỗ trợ GET tại [sse.ts](/D:/spec_research_loop/frontend/lib/api/sse.ts:1), nên mở rộng helper để nhận `method`, `body` và `AbortSignal`.

Đồng thời cập nhật [orval.config.ts](/D:/spec_research_loop/frontend/orval.config.ts:4) để loại route streaming của research khỏi codegen; các REST route còn lại vẫn sinh TanStack Query hooks bình thường.

## 6. Implement backend theo thứ tự

1. Thêm SQLAlchemy models và import vào `app/db/models.py`.
2. Tạo Alembic migration, review constraint/index thủ công.
3. Viết schemas request/response/SSE event.
4. Viết fake source và fake LLM trước.
5. Implement Citation CRUD, normalization và deduplication theo DOI/provider ID.
6. Implement search → analyze → verify → related-work matrix.
7. Implement Gap generation với citation support.
8. Implement `ResearchStagePort`:
   - `fingerprint`: hash working Citation/finding.
   - `freeze`: clone working rows sang Stage Revision.
   - `reset_working`: restore từ revision hoặc xóa working set.
   - `project`: trả Citation/finding của đúng revision.
9. Bind port vào composition root.
10. Thêm API và auth/ownership/version checks.

## 7. Frontend nên chia component như sau

```text
frontend/features/research/
├── ResearchStagePanel.tsx
├── ResearchInputsEditor.tsx
├── CitationSearchPanel.tsx
├── CitationList.tsx
├── RelatedWorkMatrix.tsx
├── GapCandidatePicker.tsx
├── useResearchStream.ts
└── *.test.tsx
```

Hành vi theo Working Draft:

- `research_inputs`: keyword chips và bốn nhóm preferred sources.
- `related_work`: search progress, citation list, matrix, verify badge, edit/remove.
- `gap`: các Gap candidate kèm giải thích và nguồn; hỗ trợ Pick, Edit, Other.
- Nút Confirm vẫn do `LoopSessionWorkbench` quản lý.

`ResearchStagePanel` nên nhận DTO và callbacks qua props; phần gọi generated hooks nằm ở container. Nhờ vậy component test độc lập mà không cần backend.

## 8. Test backend độc lập

Tạo ít nhất:

```text
backend/tests/
├── test_research_service.py
├── test_research_api.py
├── test_research_stream.py
├── test_research_stage_port.py
└── test_research_loop_integration.py
```

Các case quan trọng:

- Normalize và deduplicate DOI/URL.
- Mỗi related-work finding có Citation.
- Provider/LLM timeout hoặc trả dữ liệu lỗi.
- Không cho sửa Citation khi Working Draft không phải `related_work`.
- Account khác không truy cập được.
- Version conflict trả 409.
- SSE đúng thứ tự event và kết thúc bằng `done`.
- Freeze clone rows, không sửa history.
- Reset khôi phục đúng revision.
- Đổi Citation làm freeze hash thay đổi và descendants trở thành Stale.
- Context Projection của Gap chứa Citation đã confirm.
- Context Projection của downstream module không chứa revision Stale.

Không cần `idea` hoạt động: trong fixture chỉ cần tạo Loop Session, confirm rỗng `idea_interpretation`, confirm `idea_decomposition`, rồi prepare Loop Stage `related_work`.

## 9. Test frontend độc lập

Mock generated hooks và SSE client tương tự các test hiện có của `LoopSessionWorkbench`.

Cần test:

- Render form theo đúng Workflow Node.
- Search progress và partial Citation results.
- Abort/retry SSE.
- Citation warning/rejected state.
- Related-work matrix hiển thị source link.
- Chọn Gap candidate, sửa candidate và nhập Other.
- Disable Confirm khi search/generate đang chạy hoặc dữ liệu chưa hợp lệ.
- Xử lý 401, 409 version conflict và lỗi provider.
- Refresh query sau khi mutation/SSE hoàn tất.

## 10. Tạo luồng demo độc lập

Thêm một script local như:

```text
backend/scripts/bootstrap_research_demo.py
```

Script dùng HTTP API để:

1. Register/login Account demo.
2. Tạo Loop Session.
3. Confirm hai node của Grilling bằng fixture narrative/Card.
4. Prepare `related_work`.
5. In ra URL:

```text
http://localhost:3000/sessions/{id}?stage=related_work
```

Chạy module độc lập:

```powershell
docker compose up -d postgres

cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

cd ../frontend
pnpm codegen
pnpm dev
```

Automated checks:

```powershell
cd backend
uv run pytest tests/test_research_service.py tests/test_research_api.py tests/test_research_stream.py tests/test_research_stage_port.py -q
uv run ruff check app/modules/research tests

cd ../frontend
pnpm test -- features/research
pnpm typecheck
pnpm build
```

Ngoài `create_all` trong pytest hiện tại, nên chạy thêm `alembic upgrade head` trong CI để chắc migration thật không hỏng.

## 11. Contract để ghép luồng hoàn chỉnh

Research chỉ cần công bố một output projection ổn định:

```json
{
  "research_inputs": {},
  "citations": [],
  "related_work": [],
  "gap": {
    "card": {},
    "supporting_citations": []
  }
}
```

- Input từ `idea`: Problem, Research Questions, Constraints và Open Questions của `idea_decomposition`.
- Output cho `spec`: Related-work matrix, Gap đã confirm, Citation.
- Output cho `judgement`: Citation metadata, passages, verification status và Gap-support mapping.
- `loop` chịu trách nhiệm chọn revision current và loại bỏ dữ liệu Stale.

## Definition of Done

Module được xem là hoàn thành khi:

- Search và quản lý Citation hoạt động.
- Related-work matrix có liên kết nguồn cụ thể.
- Gap có đủ prior work, limitation, importance, testability và Citation support.
- Có Pick/Edit/Other.
- Freeze/reset/project hoạt động qua StagePort.
- Thay đổi Citation gây invalidation đúng.
- Frontend dùng OpenAPI-generated client cho REST và helper riêng cho SSE.
- Toàn bộ test mặc định chạy bằng fake provider, không cần internet/LLM/module khác.
- Có bootstrap demo cho manual test.
- `spec` và `judgement` có thể nhận dữ liệu qua Context Projection mà không truy cập trực tiếp bảng của `research`.
