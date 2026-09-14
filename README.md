# Lex Bot — Backend

FastAPI service powering the RAG chatbot: PDF ingestion, hybrid retrieval, optional live web search, streaming answers, session & memory management.

## Tech Stack

- **FastAPI** + Uvicorn (ASGI)
- **Google Gemini API** — final LLM, embeddings, and reranking
- **Tavily** — live web search
- **Hybrid retrieval** — BM25 keyword + semantic FAISS, fused with **Reciprocal Rank Fusion**, then re-ranked
- **in-memory session store** with background TTL cleanup
- **slowapi** rate limiting + shared `API_KEY` auth

## Running Locally

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate   |  macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

copy .env.example .env    # then edit it (see "Environment Variables")
uvicorn app.main:app --reload
```

Interactive API docs: http://localhost:8000/docs. Health check: http://localhost:8000/health (no auth required).

## Environment Variables

| Variable | Default | Required | Notes |
| --- | --- | --- | --- |
| `GEMINI_API_KEY` | — | ✅ | Google Gemini API key |
| `TAVILY_API_KEY` | — | ✅ | Tavily web-search key |
| `API_KEY` | `""` | ✅ | Shared secret; every `/api/v1` route verifies it via `X-API-Key` header |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | — | Comma-separated CORS origins (include any deployed frontend) |
| `SESSION_BACKEND` | `memory` | — | `memory` or `redis` |
| `SESSION_TTL_SECONDS` | `21600` | — | How long a session lives before the sweep removes it |
| `SESSION_CLEANUP_INTERVAL_SECONDS` | `1800` | — | Background TTL sweep frequency |
| `MAX_UPLOAD_MB` | `15` | — | Largest allowed PDF |
| `MAX_QUERY_LENGTH` | `2000` | — | Truncation guard for chat queries |
| `RATE_LIMIT_CHAT` | `20/minute` | — | Per-IP chat/stream limit |
| `RATE_LIMIT_UPLOAD` | `10/minute` | — | Per-IP upload limit |
| `DEBUG_MODE` | `false` | — | `true` only when debugging locally; hides internal error detail when `false` |

See [`app/core/config.py`](app/core/config.py) for every tunable (chunk size, top-k, reranker, agent step limits).

## API Reference

All routes are under `/api/v1` and require the `X-API-Key` header.

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/chat` | Non-streaming chat (JSON answer + sources) |
| `POST` | `/chat/stream` | Streaming chat via Server-Sent Events (SSE) |
| `POST` | `/upload` | Upload a PDF (`multipart/form-data`: `session_id`, `file`) |
| `GET` | `/documents?session_id=` | List uploaded documents + chunk counts |
| `DELETE` | `/documents/{filename}?session_id=` | Remove a document's chunks |
| `GET` | `/sessions` | Active (non-empty) sessions |
| `GET` | `/sessions/{session_id}` | Session detail incl. chat history + documents |
| `POST` | `/sessions` | Create a session |
| `PUT` | `/sessions/{session_id}/rename` | Rename a session |
| `DELETE` | `/sessions/{session_id}` | Delete a session |
| `GET` | `/memory/{device_id}` | Cross-session memory facts |
| `PUT` | `/memory/{device_id}` | Toggle memory on/off |
| `DELETE` | `/memory/{device_id}` | Clear stored facts |

**SSE stream events** — `event:` types emitted by `/chat/stream`:

- `status` — progress line ("Searching your document…") shown before text arrives
- `sources` — retrieved document + web sources
- `token` — an answer chunk to append
- `done` / `error` — terminal signals

## Architecture

```text
app/
├── main.py            # FastAPI app: CORS, rate limiting, TTL cleanup loop, exception handlers
├── api/
│   ├── routes.py      # All endpoints; heavy work runs in a threadpool (run_in_threadpool)
│   ├── schemas.py     # Pydantic request/response models
│   └── dependencies.py# Dependency wiring (store, rag service, memory store)
├── core/
│   ├── config.py      # Pydantic-settings configuration
│   ├── auth.py        # API-key verification
│   ├── rate_limit.py  # slowapi limiter
│   └── exceptions.py  # RAG errors -> clean 400/500
└── services/
    ├── rag_service.py # RAG pipeline: ingest, hybrid retrieval, routing, generation
    ├── session_store.py # In-memory sessions with TTL
    └── memory_store.py  # Per-device memory facts
```

Design notes:

- **Threadpool isolation** — embeddings, FAISS, and LLM calls are sync/blocking; they are dispatched via `run_in_threadpool` (or Starlette's internal generator threading for SSE) so one slow request never blocks the event loop.
- **Errors are opaque in production** — `RAGBaseError` yields a generic 400, the catch-all hides stack traces (500). Real details are logged server-side.
- **`GET /documents` never 500s** — a retrieval failure returns an empty list.
- **Sessions materialize lazily** — `get_or_create` means a fresh browser session ID is valid without an explicit create call.

## Deployment

Build the Docker image from this directory and set every env var in your hosting dashboard (FastAPICloud, Render, Fly, etc.):

```bash
docker build -t lex-bot-backend .
```

Ensure `ALLOWED_ORIGINS` includes exactly the origin(s) serving the frontend. Confirm the container boots on `/health` and that `/api/v1` rejects requests without `X-API-Key`.