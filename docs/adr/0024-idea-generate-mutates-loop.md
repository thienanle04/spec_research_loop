# idea generate mutates loop in-process

`POST /api/idea/sessions/{id}/generate` streams, then `idea` applies the parsed result through `LoopService` in one aggregate version bump (Working Draft narrative, and decomposition Card upserts). The SPA does not PATCH generate output. `loop.confirm` still does not call `idea` or the LLM (ADR 0012, ADR 0018). `idea` may import `loop`; `loop` still does not import `idea` tables.

**Considered options:** stream-only generate with the SPA persisting afterward; a private `idea` working set copied on confirm.

**Why:** Confirm freezes whatever `loop` holds. If generate were advisory, tests and the workbench would fake the write that matters, and autosave could confirm a different slice than the model just produced. A second working set duplicates Working Draft. One transactional apply matches ADR 0021.
