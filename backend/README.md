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

## Semantic Scholar scholarly search

Configure Semantic Scholar as the only scholarly provider:

```dotenv
RESEARCH_SOURCE_PROVIDER=semantic_scholar
SEMANTIC_SCHOLAR_API_KEY=your-semantic-scholar-api-key
```

OpenAlex is optional and does not need to be present in `.env` for this mode.

Semantic Scholar requests are automatically queued at most one request per
second (with a small clock-boundary margin)
across search, source resolution, references, citations, and all adapter
instances in the backend process. Keep a single backend worker when one API key
is shared; a multi-worker deployment needs a distributed rate limiter. HTTP 429
responses are retried twice with `Retry-After`/exponential backoff.

Discovery issues each SearchPlan facet query independently through the lower-cost
paper bulk-search endpoint and requests only the metadata needed by the research
workflow. When Related Work search starts, the LLM first expands the confirmed
Research Input keywords into unverified discovery leads: named tools/frameworks,
techniques, candidate scholarly-work titles, and aliases. The SearchPlan then turns
tool names and candidate titles into exact queries while using techniques and aliases
to refine conceptual queries. Leads never become Citations until a configured
scholarly provider returns and verifies a matching record. For Ideas with known
implementations, papers that explicitly mention a named tool/framework/technique rank
ahead of otherwise comparable concept-only papers.
Results are pre-ranked locally, missing facets receive one bounded follow-up search,
and facet coverage drives the final top-eight selection. Before downloading text,
records without a known full-text URL are resolved across all configured providers so
an OpenAlex open-access URL can enrich a Semantic Scholar discovery record. With
`RESEARCH_REQUIRE_DOWNLOADABLE_FULL_TEXT=false` (the default), downloadable papers,
scholarly landing/DOI pages, and provider abstracts are all eligible when they yield
non-empty analyzable text. Their actual provenance remains recorded in
`text_source_kind`; the application does not relabel an abstract as a PDF. Set the
option to `true` to restore strict downloadable-full-text behavior, in which
abstract-only records are skipped and lower-ranked records backfill the result set.
The portfolio reserves the highest-ranked matching article for each discovered named
tool, then fills remaining slots with distinct works. A second article for the same
work/tool is excluded rather than used as backfill. The Related Work narrative records
each discovery tool as `matched_citation` or `not_found`, and the UI shows that status
next to the lead. In the Related Work matrix, Study is the work/tool/framework name
while the article title remains visible as source provenance.

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

## LLM providers and profiles (ADR 0034)

Composition root binds one `LlmPort` per Workflow Node from named **Profiles**
(`creative`, `research`, `structured`, `judge`). Each Profile aliases a
**ModelRef** (`provider_id` + model). **Providers** hold kind + `api_key_env`
(secrets stay in separate env vars).

With empty `LLM_PROVIDERS` / `LLM_PROFILES`, defaults are:

- Provider `ai-fit` (`kind=langchain`) from `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_DEFAULT_MODEL` (default model `Qwen3.6-27B`)
- Provider `fake` (opt-in via JSON or test injects)
- All four Profiles → ModelRef(`ai-fit`, `LLM_DEFAULT_MODEL`)

Migration: if `LLM_PROFILES` still uses `provider_id` `openai`, either add that Provider under `LLM_PROVIDERS` or retarget Profiles to `ai-fit`.

Optional JSON overrides (e.g. Gemini for some roles, fake for research):

```dotenv
LLM_API_KEY=sk-your-fit-key
LLM_BASE_URL=https://ai-fit.hcmus.edu.vn/openai
LLM_DEFAULT_MODEL=Qwen3.6-27B
LLM_PROVIDERS={"ai-fit":{"kind":"langchain","api_key_env":"LLM_API_KEY","base_url":"LLM_BASE_URL"},"gemini":{"kind":"langchain","api_key_env":"GEMINI_API_KEY","base_url":"GEMINI_BASE_URL"},"fake":{"kind":"fake"}}
LLM_PROFILES={"creative":{"provider_id":"gemini","model":"gemini-2.0-flash"},"research":{"provider_id":"ai-fit","model":"Qwen3.6-27B"},"structured":{"provider_id":"ai-fit","model":"Qwen3.6-27B"},"judge":{"provider_id":"gemini","model":"gemini-2.0-flash"}}
LLM_NODE_PROFILE_OVERRIDES=
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
