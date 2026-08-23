# LlmPort.stream is the primitive; complete joins it

Supersedes the complete-only *contract* in [0022](./0022-complete-only-llm-port.md). The RagPort rejection stands: no shared retrieval port, ports stay Protocols plus plain types, LangChain stays in the adapter, `loop` does not own LLM bind.

`LlmPort.stream` yields completion strings (`AsyncIterator[str]`). `complete()` concatenates that stream for Judges and tests. `idea` generate SSEs those tokens (prose only; a `---json---` trailer is parsed after the stream). `FakeLlm` and `LangChainChatAdapter` (`astream`) implement both methods.

**Considered options:** keep complete-only and fake token events; replace `complete()` entirely; put SSE event objects on the port.

**Why:** Grilling needs real vendor tokens this increment. A second event vocabulary on the port would leak HTTP into adapters. Joining the stream keeps a one-shot API for later Judge runs without a second LLM method family.
