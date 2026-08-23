# Backend (FastAPI)

Modular monolith for SpecResearch Loop. See root `README.md` and `docs/adr/`.

## Layout

```
app/
  main.py                 # FastAPI app factory / router includes
  core/                   # settings, security helpers
  db/                     # engine, session
  ports/                  # LLM (and shared ports)
  adapters/
    llm/                  # concrete model providers
    storage/              # S3-compatible object store
  workers/                # reserved; SSE is in-request for now
  modules/
    identity/             # Accounts, auth (JWT)
    idea/                 # grilling / idea workflow (+ SSE demo)
    research/             # citations, related work
    spec/                 # Research Spec construction + artifacts metadata
    judgement/            # Judges + aggregator
alembic/                  # schema migrations
```

Each module: `api.py`, `service.py`, `models.py` (+ `ports/` when module-local).

## Run

```powershell
Copy-Item .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Requires `docker compose up -d` from the repo root (Postgres + MinIO). Schema is applied **only** via Alembic — the app does not `create_all`.

## OpenAlex scholarly search

Create a free API key at `https://openalex.org/settings/api`, then configure:

```dotenv
RESEARCH_SOURCE_PROVIDER=openalex
OPENALEX_API_KEY=your-openalex-api-key
OPENALEX_MAILTO=you@example.com
```

Restart the backend after changing `.env`. OpenAlex search errors are returned
as a terminal stream error when every generated query fails; partial query
failures remain warnings while successful results continue to be analyzed.

## FIT@HCMUS WebUI LLM

Personal API keys from the FIT WebUI use the OpenAI-compatible Chat Completions
endpoint. Add the following to `.env` (never commit the real key):

```dotenv
RESEARCH_LLM_PROVIDER=fit_webui
RESEARCH_LLM_MODEL=Qwen3.6-27B
FIT_WEBUI_API_KEY=sk-your-personal-key
FIT_WEBUI_BASE_URL=https://ai-fit.hcmus.edu.vn/openai
FIT_WEBUI_TIMEOUT_SECONDS=300
FIT_WEBUI_MAX_TOKENS=2000
```

## Migrations

After changing SQLAlchemy models:

```powershell
uv run alembic revision --autogenerate -m "describe the change"
# review alembic/versions/*.py
uv run alembic upgrade head
```

## Tooling

- Python ≥ 3.12 + [uv](https://github.com/astral-sh/uv)
- PostgreSQL + S3-compatible store (MinIO locally)
- OpenAPI from FastAPI is the contract source for `frontend` codegen
