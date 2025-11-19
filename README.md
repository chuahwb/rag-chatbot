# RAG Chatbot (FastAPI + React)

End-to-end RAG chatbot for the Mindhive assessment. A FastAPI backend with a LangGraph planner orchestrates tools (calculator, products RAG, outlets Text2SQL), and a React/Vite chat UI visualizes planner and tool activity.

## Quick Start: Setup & Run

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker (optional, recommended for quickest full-stack bring-up)

### Option 1: Docker Compose (API + UI)

1. Create your environment file from the template:
   ```bash
   cp env.example .env
   ```
2. Build and start both services:
   ```bash
   docker compose up --build
   # or
   make dev-docker
   ```
   - API: `http://localhost:8000`
   - Web UI: `http://localhost:5173`
   - Data: FAISS and SQLite persisted under `./data/`
3. Stop with `Ctrl+C`.

### Option 2: Native Development (separate processes)

1. Backend (FastAPI):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r server/requirements/dev.txt
   cp env.example .env  # adjust providers/keys as needed
   ```
2. (Optional) ingest real data:
   ```bash
   make ingest  # builds FAISS index under ./data/faiss/products
   make seed    # seeds SQLite outlets DB under ./data/sqlite/outlets.db
   ```
3. Run the API:
   ```bash
   make dev
   ```
   The API listens on `http://0.0.0.0:8000`.
4. Frontend (React/Vite):
   ```bash
   cd web
   npm install
   cp env.example .env.local   # adjust API base URL / SSE flags if needed
   npm run dev                 # http://localhost:5173
   ```

#### Single-shell convenience

```bash
make dev-all
```

Starts FastAPI and Vite together (Python 3.11+ and Node 20+ recommended).

## Architecture Overview

- **Backend (FastAPI, `server/`)**
  - `app/main.py` exposes:
    - `GET /health` – health probe
    - `GET /calc` – calculator tool
    - `GET /products` – products RAG endpoint
    - `GET /outlets` – outlets Text2SQL endpoint
    - `POST /chat` – main conversational endpoint (planner turn)
    - `GET /events` – SSE stream of planner node events (`sessionId`-scoped)
  - `app/agents/planner.py`:
    - LangGraph state machine for classifying intent, extracting slots, choosing tools vs follow-ups vs answering.
  - `app/services/products.py`:
    - RAG over FAISS index (`data/faiss/products`), with optional LLM summarization.
  - `app/services/outlets.py`:
    - Text2SQL pipeline over SQLite (`data/sqlite/outlets.db`), with strong SQL safety checks.
  - `app/services/calculator.py` / `app/services/calculator_http.py`:
    - Local vs HTTP-based calculator tools.

- **Frontend (React/Vite, `web/`)**
  - `useChat`:
    - Owns chat state and session lifecycle.
    - Handles quick commands `/calc`, `/products`, `/outlets`, `/reset` by calling REST tools directly.
    - Persists messages, tool actions, and `sessionId` into `localStorage` (`mh.chat.state`).
  - `useEvents`:
    - Subscribes to `/events?sessionId=...` via SSE and maintains a rolling window of planner events.
  - Components:
    - `ChatWindow` – main surface combining messages, composer, planner timeline, and tool activity.
    - `PlannerTimeline` – human-readable view of planner node transitions (with optional raw-event debug).
    - `ToolActivity` – latest tool calls and outcomes for the current user turn.

Planner and tool activity are streamed back to the UI over SSE and presented alongside the conversation.

![Chat and planner flow](docs/chat-flow.svg)

## Key Trade-offs

- **LLM provider modes vs determinism/cost**
  - `PLANNER_LLM_PROVIDER`, `TEXT2SQL_PROVIDER`, `EMBEDDINGS_PROVIDER`, and `PRODUCT_SUMMARY_PROVIDER` can be:
    - `fake` – fully offline, deterministic behavior for tests and demos.
    - `openai` – realistic quality at the cost of API usage.
    - `local` – uses Ollama for Text2SQL when available.
  - Default templates favor offline/fake for development; switch to OpenAI for more realistic behavior.

- **Calculator tool: local vs HTTP**
  - `CALC_TOOL_MODE=local` keeps the calculator in-process (simpler, faster, no extra deployment).
  - `CALC_TOOL_MODE=http` allows swapping in an external calculator microservice at `CALC_HTTP_BASE_URL`.

- **RAG vs Text2SQL separation**
  - Products are retrieved via embeddings + FAISS (vector similarity) and optional LLM summaries.
  - Outlets are stored in SQLite and queried via an NL→SQL chain with strict safety filters.
  - This separation mirrors common production patterns: unstructured product copy vs highly structured outlet data.

- **Planner observability**
  - SSE (`ENABLE_SSE=true`) streams per-node planner events to the UI for debugging and demos.
  - Optional Langfuse integration (`LANGFUSE_*`) gives production-grade tracing when keys are set; otherwise it’s inert.

- **Frontend state management**
  - Single-page React app with localStorage persistence for sessions (simple, robust for single-user/local usage).
  - Quick commands bypass `/chat` and hit tools directly, making unhappy flows (missing args, 5xx, network errors) easy to test and reason about.

## Configuration

Backend configuration is driven by the root `.env` (see `env.example` for a documented template). Key groups:

- **Planner & LLMs**
  - `OPENAI_API_KEY`
  - `PLANNER_LLM_PROVIDER`, `PLANNER_MODEL`, `PLANNER_TEMPERATURE`, `PLANNER_MAX_CALLS_PER_TURN`
- **Calculator**
  - `CALC_TOOL_MODE`, `CALC_HTTP_BASE_URL`, `CALC_HTTP_TIMEOUT_SEC`
- **Products RAG**
  - `EMBEDDINGS_PROVIDER`, `VECTOR_STORE_PATH`
  - `PRODUCT_SUMMARY_PROVIDER`, `PRODUCT_SUMMARY_MODEL`, `PRODUCT_SUMMARY_TIMEOUT_SEC`
- **Outlets Text2SQL**
  - `TEXT2SQL_PROVIDER`, `TEXT2SQL_MODEL`, `TEXT2SQL_TIMEOUT_SEC`
  - `SQLITE_URL` pointing at the outlets DB
  - `OLLAMA_HOST` when using `TEXT2SQL_PROVIDER=local`
- **Runtime behavior & observability**
  - `ENABLE_SSE`, `CORS_ORIGINS`
  - `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `LANGFUSE_RELEASE`

For fully offline development, a typical configuration is:

```bash
PLANNER_LLM_PROVIDER=fake
EMBEDDINGS_PROVIDER=fake
TEXT2SQL_PROVIDER=fake
PRODUCT_SUMMARY_PROVIDER=fake
```

## Testing & Quality

- **Backend**
  - `make test` – run pytest (unit + integration).
  - `make lint` – Ruff lint checks.
  - `make format` – Ruff formatter.
- **Frontend**
  - `cd web && npm run test` – Vitest + Testing Library (hooks, components, storage, API client).
  - `cd web && npm run test:e2e` – Playwright E2E (requires `npx playwright install chromium` once).

