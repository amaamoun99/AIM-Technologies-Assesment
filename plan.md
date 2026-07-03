# YouTube Data Pipeline — Agent Implementation Plan

**Audience:** an autonomous coding agent implementing this end-to-end.
**Rule for every phase below: implement, then run the listed test(s) before moving to the next phase. Do not proceed on a failing test — fix it first.**

Locked decisions (do not deviate without a strong reason):
- Source: YouTube Data API v3
- Channels (5): AJ+ كبريت, Saba7o Korah (صباحو كورة), Shark Tank Egypt, Peace Cake, Kareem Elsayed كريم السيد
- Storage: PostgreSQL, dockerized, relational (`videos` 1→many `comments`)
- Orchestration: plain Python only — no Airflow/NiFi in the actual implementation (Airflow is discussed only as a written answer in `design_notes.md`, never installed or run)
- DB driver: psycopg2 (raw SQL, not an ORM)
- Containerization: Docker Compose (`app` + `postgres`)
- Target volume: ≥50 videos total across the 5 channels, with their comments

---

## Phase 0 — Scaffolding

**Implement:**
1. `git init` in a new `youtube-pipeline/` directory.
2. Create the full folder tree up front (empty placeholder files where needed):
   ```
   youtube-pipeline/
   ├── docker-compose.yml
   ├── Dockerfile
   ├── .env.example
   ├── .gitignore
   ├── requirements.txt
   ├── README.md
   ├── design_notes.md
   ├── data/landing/.gitkeep
   ├── src/__init__.py
   ├── src/api_client.py
   ├── src/ingest.py
   ├── src/transform.py
   ├── src/storage.py
   ├── src/models.py
   ├── queries/schema.sql
   ├── queries/analysis.sql
   ├── diagrams/architecture.png (placeholder, added in Phase 7)
   ├── tests/__init__.py
   └── main.py
   ```
3. `.gitignore`: `.env`, `data/raw/*` (keep `.gitkeep`), `__pycache__/`, `*.pyc`, `.venv/`, `diagrams/*.drawio`.
4. `.env.example`:
   ```
   YOUTUBE_API_KEY=
   POSTGRES_USER=pipeline
   POSTGRES_PASSWORD=pipeline
   POSTGRES_DB=youtube
   POSTGRES_HOST=postgres
   POSTGRES_PORT=5432
   ```
5. Copy `.env.example` to `.env`. The human will fill in `YOUTUBE_API_KEY`; agent should stop and ask for it if not already provided, rather than fabricating one.

**Test:**
- `git status` shows the expected tree tracked (minus `.env`, `data/raw/*`).
- `ls -R` matches the structure above.

---

## Phase 1 — Docker & Environment

**Implement:**
1. `requirements.txt`:
   ```
   requests
   psycopg2-binary
   python-dotenv
   pytest
   ```
2. `Dockerfile`: `python:3.11-slim` base → copy `requirements.txt` → `pip install --no-cache-dir -r requirements.txt` → copy source → `CMD ["python", "main.py"]`.
3. `docker-compose.yml`:
   - `postgres`: image `postgres:16`, env from `.env`, named volume for `/var/lib/postgresql/data`, healthcheck via `pg_isready`.
   - `app`: build from `Dockerfile`, `depends_on: postgres: condition: service_healthy`, mounts `./data/raw:/app/data/raw`, `env_file: .env`.

**Test:**
1. `docker compose up --build -d`.
2. `docker compose ps` — both services show `running`/`healthy`.
3. `docker compose exec postgres pg_isready -U pipeline` returns `accepting connections`.
4. `docker compose logs app` shows no crash loop (expected to exit/error at this stage since `main.py` is still a stub — acceptable, but it must be a clean Python error, not a container-level failure).
5. `docker compose down` cleans up without errors.

---

## Phase 2 — Database Schema

**Implement:**
1. `queries/schema.sql`:
   - `videos(video_id PK, channel_id, channel_name, title, description, published_at, view_count, like_count, comment_count, duration, fetched_at)`
   - `comments(comment_id PK, video_id FK -> videos.video_id, author, text, like_count, published_at)`
   - Indexes: `idx_comments_video_id`, `idx_videos_channel_id`.
   - All `CREATE TABLE IF NOT EXISTS` (idempotent).

**Test:**
1. Bring up `postgres` only: `docker compose up -d postgres`.
2. `docker compose exec -T postgres psql -U pipeline -d youtube -f /dev/stdin < queries/schema.sql` (or copy file in and run it).
3. `docker compose exec postgres psql -U pipeline -d youtube -c "\dt"` — confirms `videos` and `comments` exist.
4. Re-run the same schema script a second time — must succeed with no errors (idempotency check).

---

## Phase 3 — Core Classes

Implement in this order. Write a matching test file for each before moving to the next class, and run it immediately.

### 3a. `src/models.py`
- `@dataclass Video` and `@dataclass Comment` matching the schema columns exactly (types included).

**Test (`tests/test_models.py`):** instantiate each dataclass with sample values, assert field access and types.

### 3b. `src/api_client.py` — `YouTubeAPIClient`
- `__init__(api_key)`.
- `search_channel_videos(channel_id, max_results)`.
- `resolve_channel_id(handle_or_name)` — supports `forHandle`/search fallback for `@handle`-style channels.
- `get_video_details(video_ids)`.
- `get_comments(video_id, max_results)`.
- Shared private `_request(...)` with retry/backoff on 429/5xx and timeout; raises a clear exception on repeated failure.
- No file I/O, no DB calls in this class.

**Test (`tests/test_api_client.py`):**
- Unit tests with `requests` mocked (`responses` lib or `unittest.mock`) covering: happy path parsing, a 429 triggering retry, a malformed response raising a clear error.
- One manual/live smoke test (not part of automated suite) hitting the real API for a single known channel to confirm the API key works and quota isn't exhausted — run once, log the result, don't leave it in CI.

### 3c. `src/transform.py` — `VideoTransformer`
- `transform_videos(raw_json) -> list[Video]`
- `transform_comments(video_id, raw_json) -> list[Comment]`
- Defensive handling: missing stats, disabled comments, null descriptions.

**Test (`tests/test_transform.py`):** feed fixture JSON (including an edge case with comments disabled / missing fields) and assert correct `Video`/`Comment` objects, no exceptions on missing fields.

### 3d. `src/storage.py` — `Database`
- `connect()`, `close()`, context-manager support.
- `create_schema()` — executes `queries/schema.sql`.
- `insert_videos(videos)`, `insert_comments(comments)` — batched, `ON CONFLICT (id) DO UPDATE/NOTHING`.
- `run_query(sql, params=None) -> list[dict]`.

**Test (`tests/test_storage.py`, requires `postgres` running):**
- `create_schema()` then insert 2 fixture videos + 3 fixture comments.
- Re-insert the same video (conflict path) — assert no duplicate row, no crash.
- `run_query("SELECT COUNT(*) FROM videos")` returns expected count.
- Insert a comment referencing a non-existent `video_id` — assert FK constraint rejects it.

### 3e. `src/ingest.py` — `IngestionPipeline`
- `run_for_channel(channel_id_or_handle)`:
  resolve channel → list video IDs → fetch details → dump raw JSON to `data/raw/{channel}/{video_id}.json` → fetch comments per video → transform → load via `Database`.
- Structured logging per channel/video (counts, failures).

**Test (`tests/test_ingest.py`):**
- Mock `YouTubeAPIClient` and `Database`; run `run_for_channel` on a fake channel with 2 fake videos; assert the pipeline calls resolve → details → comments → transform → insert in the right order, and that raw JSON files are written to `data/raw/`.

---

## Phase 4 — Channel Resolution & Config

**Implement:**
1. `src/config.py` (or a constant block in `main.py`) listing the 5 channels by handle/name:
   ```python
   CHANNELS = [
       "AJ+ كبريت",
       "@Saba7oKorah",
       "Shark Tank Egypt",
       "Peace Cake",
       "Kareem Elsayed كريم السيد",
   ]
   ```
2. A one-off resolution run that calls `resolve_channel_id` for each and prints the resolved channel IDs.
3. Hardcode the resolved IDs back into config once confirmed, to avoid re-resolving on every run.

**Test:**
- Run the resolution script live; assert all 5 return a valid `UC...` channel ID (fail loudly and list which handle failed if any don't resolve — Arabic-name channels especially need the search fallback verified).

---

## Phase 5 — Entry Point

**Implement:**
1. `main.py`: load `.env` → instantiate client/db/pipeline → `db.create_schema()` → loop over `CHANNELS`, pulling enough videos per channel that the total across all 5 is ≥50 → print a per-channel and total summary (videos loaded, comments loaded, failures).
2. Support a `--dry-run` flag that does the fetch/transform but skips DB writes (useful for repeated testing without burning quota/re-inserting).

**Test:**
1. `docker compose up --build` (full stack).
2. `docker compose exec app python main.py` — completes without unhandled exceptions.
3. `docker compose exec postgres psql -U pipeline -d youtube -c "SELECT COUNT(*) FROM videos;"` — count is ≥50.
4. `docker compose exec postgres psql -U pipeline -d youtube -c "SELECT COUNT(*) FROM comments;"` — count is > 0.
5. `docker compose exec postgres psql -U pipeline -d youtube -c "SELECT DISTINCT channel_name FROM videos;"` — all 5 channels present.
6. Run `main.py` a second time (no wipe) — assert no duplicate-key crashes (conflict handling from Phase 3d holds under a real run).

---

## Phase 6 — Analysis Queries

**Implement:**
1. `queries/analysis.sql` — at minimum:
   - Top 10 videos by view count.
   - Average comments per video, grouped by channel.
   - Top 10 most active commenters (by comment count).
   - Engagement rate `(like_count + comment_count) / NULLIF(view_count,0)` per channel, ranked.
2. `main.py --analyze` (or a separate `analyze.py`) that runs each query via `Database.run_query()` and pretty-prints results as tables to stdout.

**Test:**
- `docker compose exec app python main.py --analyze` — runs without error, prints non-empty, sane-looking results for every query (spot check: top video view count is plausible, no `NULL`/divide-by-zero crashes on the engagement query).

---

## Phase 7 — Architecture Diagram

**Implement:**
1. Diagram (draw.io/Excalidraw, exported PNG): `YouTubeAPIClient → IngestionPipeline → data/raw (JSON landing zone) → VideoTransformer → Database (Postgres) → analysis.sql`, with a boundary box around the Docker Compose services.
2. Save as `diagrams/architecture.png`, referenced from `README.md`.

**Test:**
- File exists, opens as a valid PNG, and every class/component named in `src/` appears somewhere on the diagram (manual visual check against the file tree).

---

## Phase 8 — Design Notes (Reflection)

**Implement:** `design_notes.md` covering:
1. Class responsibility table (client / pipeline / transformer / repository).
2. Storage justification: relational shape, Postgres over Mongo/SQLite given dockerized + concurrent-write context.
3. Scaling to 50k videos: this is the one place Airflow is discussed — DAG-per-channel, task-level retries, rate-limit-aware pooling, incremental/idempotent loads, partitioning `comments`, raw landing zone moved to object storage.
4. Why plain Python orchestration (not Airflow/NiFi) was the right call for this scope.

**Test:**
- Read-through check: every claim in the doc must match what was actually implemented (e.g., don't claim retry logic exists if Phase 3b's retry test isn't passing).

---

## Phase 9 — README & Full-Stack Verification

**Implement:**
1. `README.md`: prerequisites, `.env` setup, `docker compose up --build`, how to run ingestion and analysis, env var reference, embedded diagram, link to `design_notes.md`.
2. Confirm `.env` is gitignored; only `.env.example` is committed.

**Final test — full clean-machine simulation:**
1. `docker compose down -v` (wipe volumes).
2. `docker compose up --build -d`.
3. `docker compose exec app python main.py` → succeeds, loads ≥50 videos + comments across all 5 channels.
4. `docker compose exec app python main.py --analyze` → all queries return sane results.
5. `docker compose exec app pytest` → full unit test suite (Phases 3a–3e) passes.
6. `docker compose down` → clean shutdown, no orphaned containers.
7. Manually diff `README.md` steps against what was actually run — a grader following the README verbatim must reproduce the same result with zero manual fixes.

---

## Definition of Done

- [ ] `docker compose up --build` works from a clean clone with only `.env` filled in.
- [ ] `pytest` passes (all unit tests from Phase 3).
- [ ] ≥50 videos and >0 comments loaded across exactly the 5 named channels.
- [ ] Re-running `main.py` is idempotent (no crashes, no duplicate rows).
- [ ] `main.py --analyze` produces correct, non-crashing results for every required query.
- [ ] `diagrams/architecture.png` exists and accurately reflects the implemented classes.
- [ ] `design_notes.md` answers match the real implementation (no aspirational claims).
- [ ] `README.md` is followable end-to-end by someone who has never seen the repo.
- [ ] No Airflow/NiFi installed or referenced anywhere except as a written answer in `design_notes.md`.