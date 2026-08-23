# SpecResearch Loop

Website that turns a vague research idea into a verified **Research Spec** through a human-in-the-loop **SpecResearch Loop** (grilling → related work → claims/evidence → experiment plan → independent Judges). See `TOPIC.md` and `docs/for-human/workflow.mmd`.

Domain language lives in [`CONTEXT.md`](./CONTEXT.md). Architecture decisions live in [`docs/adr/`](./docs/adr/).

## Repository shape

| Path | Role |
|------|------|
| `backend/` | FastAPI **modular monolith** (only real API) |
| `frontend/` | Next.js **SPA client** over that API |
| `docs/` | ADRs, human diagrams |
| `CONTEXT.md` | Ubiquitous language (glossary only) |
| `docker-compose.yml` | Local Postgres + MinIO |

No shared runtime package yet. The contract is FastAPI OpenAPI → generated TypeScript types in `frontend/lib/api`.

## Quick start

```powershell
# 1) Infra (Postgres :55432, MinIO :9010 / console :9011)
docker compose up -d

# 2) Backend
cd backend
Copy-Item .env.example .env   # if needed
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 3) Frontend (other terminal)
cd frontend
Copy-Item .env.example .env.local
# set NEXT_PUBLIC_API_BASE_URL to the backend URL
pnpm install
pnpm dev

# 4) OpenAPI types (backend must be running)
pnpm codegen
```

Smoke paths: register/login at `/register` and `/login`, then `/demo` for authenticated SSE.

**Port notes:** compose maps Postgres to **55432** and MinIO to **9010/9011** so they do not collide with common local services on 5432/9000. Adjust `backend/.env` if you change compose ports.

## Backend modules

```
identity → idea → research → spec → judgement
```

- **identity** — Accounts (email/password), JWT Bearer (`/api/identity/register|login|me`)
- **idea** — grilling / idea workflow; SSE demo at `/api/idea/demo/stream`
- **research** — citations, related work, gap proposals
- **spec** — Research Spec drafts + **Spec Artifact** metadata
- **judgement** — independent Judges + aggregator

Shared: `app/core`, `app/db`, `app/ports` (LLM, object storage), `app/adapters`, `app/workers` (reserved).

## Frontend layout

- `app/` — thin App Router routes (client-heavy)
- `features/{identity,idea,research,spec,judgement}/` — UI by workflow
- `lib/api/` — Orval + TanStack Query (`pnpm codegen`); SSE stays hand-written
- `components/ui/` — shadcn/ui (Tailwind, zinc)
- `NEXT_PUBLIC_API_BASE_URL` — FastAPI origin (no Next rewrite BFF)

## Cross-cutting decisions (summary)

| Topic | Choice | ADR |
|-------|--------|-----|
| Process shape | Modular monolith, five modules | [0001](./docs/adr/0001-modular-monolith-modules.md) |
| UI ↔ API | SPA + Orval/TanStack Query; env API base URL | [0007](./docs/adr/0007-orval-tanstack-query.md) (supersedes [0002](./docs/adr/0002-spa-openapi-client.md)) |
| UI kit | shadcn/ui + Tailwind (zinc, light first) | [0008](./docs/adr/0008-shadcn-tailwind.md) |
| Data | Postgres + S3-compatible object store | [0003](./docs/adr/0003-postgres-s3-persistence.md) |
| Long work | SSE, in-request async streaming | [0004](./docs/adr/0004-sse-in-request-streaming.md) |
| Auth | Email/password Accounts, JWT Bearer | [0005](./docs/adr/0005-email-password-jwt-accounts.md) |
| LLMs | Provider port + adapters | [0006](./docs/adr/0006-llm-provider-port.md), [0022](./docs/adr/0022-complete-only-llm-port.md) |

## Tooling

- **backend:** uv, Python ≥ 3.12
- **frontend:** pnpm, Next.js App Router
