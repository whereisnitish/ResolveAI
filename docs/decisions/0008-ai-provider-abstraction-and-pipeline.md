# ADR-0008: AI provider abstraction, LangGraph pipeline and RAG on pgvector

* Status: Accepted · Date: 2026-11-09

## Context
AI agents must answer from each workspace's own knowledge, hand off safely to humans, and never be tied to one LLM vendor. The platform must also run fully offline in development and tests.

## Decision
**Providers** (`apps/ai_agents/providers.py`). Application code depends only on `LLMProvider.complete(LLMRequest) -> LLMResponse`.
* `AnthropicProvider` uses the official SDK: `beta.messages.create` with `output_config` (`effort` plus a JSON-schema `format`) for structured answers. On models that support it, the server-side refusal fallback is enabled (`fallbacks: "default"`). A `stop_reason == "refusal"` result is treated as a handoff. Errors are mapped from a typed exception chain, with `retryable` set for 429, 5xx and connection failures. The default model is `claude-opus-5-5`, configurable per agent.
* `OpenAIProvider` uses the official SDK's Chat Completions with a strict `json_schema` and `reasoning_effort` for reasoning models. The default is `gpt-5.5`.
* `MockProvider` is deterministic and offline: it answers from the top retrieved passage and hands off when nothing relevant is found. In development and tests, a missing key falls back to it (`AI_ALLOW_MOCK_FALLBACK`). Production settings disable this, so a missing key produces a handoff, never a fake answer.
* Adding a provider means one class plus one registry branch.

**Pipeline** (`apps/ai_agents/pipeline.py`, LangGraph `StateGraph`): `check_request → retrieve → generate (≤2 safe tool rounds) → validate → decide`.
* The pipeline is pure computation. `services.py` persists `AIExecution`/`ToolExecution` and delivers the reply **inside a row lock that re-checks `Conversation.ai_state`**, so a human taking over mid-generation always wins (brief test #7).
* **Tools** are a registry of read-only, workspace-scoped functions (`search_knowledge`, `get_customer_profile`) with argument validation. There is no code execution. Unknown tools return an error result to the model rather than raising.
* **Safety:** internal notes never enter the model history; retrieved text is delimited and declared to be data; answers sharing any 8-word shingle with the agent's private instructions are blocked; empty, refused or low-confidence answers and provider errors all lead to a handoff.
* **Handoff triggers:** a human-request keyword (checked before any model call), reaching the reply cap, no relevant knowledge under strict grounding, the model setting `needs_human`, confidence below the threshold, a refusal or provider failure, or exhausted quota.

**RAG** (`apps/knowledge`): Celery ingestion (extract → normalize → chunk at ~1,200 characters with overlap, one chunk per FAQ entry → embed → store) into `KnowledgeChunk.embedding vector(1536)` with an HNSW cosine index. Retrieval always filters by workspace and by the current `embedding_model`, so vectors from different models are never compared. Embeddings come from OpenAI `text-embedding-3-small`, or from a local feature-hashing embedder when no key is set.

## Consequences
* \+ Provider swaps are configuration; the whole AI path is testable offline (26 AI tests, including fake-SDK request-shape tests for both providers).
* \+ Every AI decision is auditable: retrieved chunks, scores, steps, tokens, latency and the reason for any handoff.
* − Structured JSON output (instead of native tool calling) keeps providers interchangeable at the cost of some tool-use expressiveness. Native tool calling can be added per provider later behind the same interface.
* − Hashing embeddings are lexical. Production should set `OPENAI_API_KEY` (or add a Voyage/Cohere embedder) and re-index.
