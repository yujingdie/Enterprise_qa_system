# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Enterprise Knowledge QA system: upload documents, retrieve relevant chunks via Milvus vector search, generate answers via LLM with SSE streaming. Backend is FastAPI, frontend is React+Vite+TypeScript+Tailwind.

## Commands

### Docker (all services)
```bash
cd G:\ai_study\Enterprise_qa_system
docker-compose up -d          # postgres, etcd, minio, milvus, backend, frontend
docker-compose logs -f backend  # tail backend logs
```
Frontend: http://localhost:3000, Backend API docs: http://localhost:8000/docs

### Backend (local dev, outside Docker)
```bash
cd backend
pip install -r requirements.txt   # needs Python 3.11+
uvicorn app.main:app --reload --port 8000
```
Note: local dev still needs Milvus + PostgreSQL running. Start infra-only via `docker-compose up -d postgres milvus etcd minio`.

### Tests
```bash
cd backend
pytest tests/                    # all tests
pytest tests/test_chunker.py     # single test file
pytest tests/test_parser.py::test_parse_txt  # single test
```
Tests are unit-level (chunker, parser, embedder mock). Milvus searcher tests require a running Milvus instance.

### Eval (retrieval quality)
```bash
cd backend
python -m eval.run_eval                        # default eval (Recall@k, MRR)
python -m eval.run_eval --experiment rerank    # rerank on/off comparison
python -m eval.run_eval --experiment search    # dense vs hybrid
python -m eval.run_eval --experiment chunk     # chunk size comparison (256/512/1024)
python -m eval.run_eval --experiment embedding # embedding model comparison
python -m eval.run_eval --experiment all       # all experiments
```
Reports saved to `backend/eval/reports/`. Dataset: `backend/eval/test_dataset.json` (10 QA pairs with difficulty levels).

### Frontend
```bash
cd frontend
npm install && npm run dev     # dev server
npm run build                  # tsc + vite build
```

## Architecture

### Query Pipeline (`backend/app/pipeline/query.py`)
`run_retrieval(question)` → returns `{candidates, sources, context, rewrite_queries}`
1. **Query rewrite**: LLM generates 3 search variants (JSON output, fallback to original on failure)
2. **Embedding**: Qianwen text-embedding-v3 API (OpenAI SDK compatible)
3. **Milvus dense search**: HNSW index, COSINE metric, top_k=20
4. **Rerank**: BGE-reranker-v2-m3 cross-encoder (optional, graceful fallback if sentence-transformers not installed)
5. **Score threshold filter**: score >= 0.3

`qa.py` endpoint calls `run_retrieval` then streams LLM answer via SSE (`chat_stream`). SSE uses three event types:
- `event: sources` — sent first with retrieval results as JSON
- `event: answer` — streamed LLM output chunks
- `event: done` — signals completion with session_id

### Ingest Pipeline (`backend/app/pipeline/ingest.py`)
Upload → parse by file type → chunk (recursive, 512 chars, 64 overlap) → embed in batches of 10 → insert_batch to Milvus → update PostgreSQL document status.

### Milvus Layer (`backend/app/milvus/`)
- **schema.py**: Collection with fields: id(VARCHAR PK), chunk_text, dense_vector(FLOAT_VECTOR 1024d), doc_id, source, page, chunk_index
- **index.py**: HNSW (M=16, ef_construction=256, ef_search=128), supports IVF_FLAT/IVF_SQ8 as alternatives
- **searcher.py**: `search_dense`, `search_sparse`, `search_hybrid` (RRF fusion). Currently only `search_dense` is used by the query pipeline
- **writer.py**: `insert_batch`, `delete_by_doc_id`

### LLM & Embedding Clients
- **LLM** (`app/llm/client.py`): Anthropic SDK calling MiMo 2.5 Pro (Anthropic-compatible API). `chat()` for single-turn, `chat_stream()` for streaming
- **Embedding** (`app/embed/client.py`): OpenAI SDK calling Qianwen text-embedding-v3. Supports local BGE model via `embedding_provider=local` in .env

### Data Models (SQLAlchemy + PostgreSQL)
- `User`: auth credentials
- `Session`: conversation grouping (title, timestamps)
- `Conversation`: individual QA pairs (question, answer, sources as JSONB)
- `Document`: upload metadata (file_path, status, chunk_count)

### Configuration
- `backend/.env`: API keys, model names, DB credentials, JWT secret (required, no defaults for secrets)
- `backend/config/pipeline.yml`: chunk strategy/size, embedding params, Milvus index params, retrieval top_k/threshold, reranker toggle
- `backend/config/prompts.yml`: query rewrite and answer generation system prompts
- `backend/app/core/config.py`: Singleton `config` object. Loads `.env` into `config.env` (Pydantic Settings) and YAML into `config.pipeline` / `config.prompts` dicts

### Frontend
- SSE streaming via `fetch()` + `ReadableStream` (not EventSource API) — `src/api/stream.ts`
- Routes: Login, Register, Chat (multi-session sidebar), Documents (upload/list/delete)
- API client: Axios with JWT interceptor, Vite proxies `/api/` to backend

## Known Issues & Constraints
- **LLM API key may be expired**: MiniMax keys expire. When LLM returns 401, query rewrite falls back to original question, answer generation falls back to showing retrieved chunks
- **Sparse vector removed**: pymilvus 2.4 `SPARSE_FLOAT_VECTOR` doesn't support `nullable=True`. Schema has no sparse_vector field. `search_sparse`/`search_hybrid` exist in code but aren't wired into the query pipeline
- **Reranker is optional**: requires `sentence-transformers` which pulls PyTorch (~2GB). Docker image doesn't install it by default. `reranker.py` gracefully degrades
- **Document upload is synchronous**: `ingest_file` is awaited in the request handler. Large files block the response. No background task queue yet
- **eval/run_eval.py**: search experiment monkey-patches `run_retrieval` at module level. Chunk/embedding experiments require re-ingestion with different configs for accurate comparison
