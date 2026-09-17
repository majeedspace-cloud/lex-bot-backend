# RAG Chatbot — Backend

FastAPI backend for a hybrid-retrieval RAG chatbot: document + live-web
question answering, streaming responses, multi-step agent reasoning,
named sessions, and cross-session memory.

## Stack

- **FastAPI** + **Gemini API** (both the LLM and the embeddings — no local
  ML models, no torch/sentence-transformers, deliberately lightweight
  enough to run on any free-tier host)
- **FAISS** for the vector index, **scikit-learn** (TF-IDF) for keyword search
- **Tavily** for live web search
- **slowapi** for rate limiting

## Getting Started

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in GEMINI_API_KEY, TAVILY_API_KEY, API_KEY, etc.
uvicorn app.main:app --reload
```
Visit `/docs` for interactive Swagger UI, `/health` for a plain liveness check.

## Architecture

```text
app/
├── main.py              # FastAPI app, CORS, rate limiting, error handling
├── core/                # Stateless building blocks
│   ├── config.py         # All settings, env-var driven
│   ├── llm.py             # Gemini wrapper (chat + streaming + multi-turn history)
│   ├── embeddings.py      # Gemini embeddings (RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY)
│   ├── retrieval.py       # Keyword + semantic search, RRF fusion
│   ├── reranker.py        # LLM-based reranking of fused candidates
│   ├── vector_store.py    # FAISS index wrapper
│   ├── document_loader.py # PDF text extraction + chunking
│   ├── auth.py            # API key verification
│   ├── rate_limit.py      # Shared slowapi limiter instance
│   └── prompts.py         # Single source of truth for system prompts
├── services/             # Stateful orchestration
│   ├── rag_service.py         # Ties everything together per request
│   ├── agent.py               # Multi-step agent (plans from intent, adapts to empty results)
│   ├── intent_router.py       # Classifies each message: casual / needs_pdf / needs_web / needs_both
│   ├── session_store.py       # In-memory session storage, owned per device_id
│   ├── user_memory_store.py   # Cross-session fact storage, per device_id
│   ├── memory_extractor.py    # Extracts durable facts from messages
│   └── web_search.py          # Tavily wrapper
└── api/
    ├── routes.py          # All endpoints
    ├── schemas.py         # Request/response models
    └── dependencies.py    # Dependency-injection wiring
```

## Key Design Decisions

- **Sessions are owned by `device_id`, not just identified by `session_id`.**
  Every session/document/memory endpoint enforces that the caller's
  `device_id` matches the session's owner — this is the actual privacy
  boundary between different users of the same deployment.
- **No local ML models.** Embeddings and reranking both go through the
  Gemini API instead of a local `sentence-transformers` model — this is
  what makes the whole thing fit in a free-tier host's memory limit.
- **The agent plans from the intent classifier's result** instead of
  re-deciding from scratch, and falls back to the other source
  (doc↔web) automatically if the planned search comes back empty.

## Environment Variables

See `.env.example` for the full list. The ones that block startup if missing:
`GEMINI_API_KEY`, `TAVILY_API_KEY`. `API_KEY` is required outside `DEBUG_MODE`.

## Deployment

Currently deployed on FastAPI Cloud. `ALLOWED_ORIGINS` (exact match list)
and `ALLOWED_ORIGIN_REGEX` (for platforms like Vercel that generate a new
preview URL per deploy) both need to be set correctly or the frontend
will be blocked by CORS — see the frontend's `ALLOWED_ORIGINS` note.
