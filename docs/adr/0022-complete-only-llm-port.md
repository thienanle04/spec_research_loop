# Complete-only LlmPort; LangChain in the adapter

We considered a second RAG/retrieval port beside `LlmPort.complete`. Retrieval is not a shared port this increment: Context Projection already assembles Stage Revisions, and citation search belongs in `research` once Citations exist. Modules keep depending on one complete-only port (ADR 0006). LangChain LCEL (`ChatPromptTemplate | ChatOpenAI`) lives in `app/adapters/llm`; ports stay Protocols plus plain types. `create_app` binds one adapter instance to every Workflow Node for later per-node overrides; adapters do not import `loop.catalog`.

**Considered options:** a `RagPort` (retrieve or retrieve-and-generate); LangChain types on the port; per-node prompt chains in adapters; `loop` owning LLM bind like StagePort.

**Why:** A second completer duplicates `LlmPort`. Vectorizing Stage Revisions fights Context Projection (ADR 0011). Loop must not call the LLM (ADR 0018). LCEL without a retriever matches `complete(system, prompt)` without stealing prompts from modules.
