# Design Notes & Architectural Reflections

This document reflects on the architecture, technical choices, scaling capabilities, and tradeoffs made in implementing the YouTube Data Pipeline.

---

## 1. Component Responsibility Mapping

To maintain clean, maintainable, and testable code, we followed the Single Responsibility Principle (SRP) to segregate components:

| Class / Module | File | Role & Primary Responsibility |
| :--- | :--- | :--- |
| `YouTubeAPIClient` | `src/api_client.py` | **Data Fetching (API Gateway):** Exposes clean methods for querying YouTube's API (channels, playlists, details, comments). Implements connection retry, timeout handling, rate limit backoffs, and error checking. Banned from performing filesystem or database interactions. |
| `VideoTransformer` | `src/transform.py` | **Data Transformation (CPU-bound):** Standardizes raw API JSON arrays into strongly-typed `Video` and `Comment` dataclasses. Implements defensive defaults (e.g. converting missing counts to 0, parsing ISO datetimes, checking disabled comment threads). Banned from making API or DB calls. |
| `Database` | `src/storage.py` | **Data Persistence (Repository):** Manages PostgreSQL connections, transactions, and applies schema definitions. Performs high-performance batch updates via `execute_batch` and resolves conflicts gracefully via SQL `UPSERT` (`ON CONFLICT DO UPDATE`). Banned from API/business logic. |
| `IngestionPipeline` | `src/ingest.py` | **Orchestrator:** Ties components together. Controls flow: resolves IDs, checks current constraints, retrieves data via Client, dumps raw inputs to disk (`data/raw/` landing zone), passes them to Transformer, and persists outputs to the Database. |
| `main.py` | `main.py` | **Entry Point:** Handles environment bootstrapping, command-line argument parsing, logging setup, and starts either the ingestion cycle or SQL analytics reporter. |

---

## 2. Storage Justification

We chose **PostgreSQL** in a dockerized container as the primary data store over alternatives like SQLite or MongoDB:

### Why PostgreSQL over SQLite?
* **Concurrent Writing:** SQLite locks the entire database file during writes, making it prone to "database is locked" errors under parallel runs or heavy batch writing. Postgres supports fine-grained row-level locking, enabling highly concurrent reads/writes.
* **Production Parity:** PostgreSQL is the industry standard for production-grade transactional pipelines. Using it dockerized ensures that local development matches cloud execution patterns.
* **Rich Datatypes & Indexing:** Postgres supports robust timezone-aware timestamps (`TIMESTAMPTZ`) and flexible text search fields which are ideal for comment storage.

### Why PostgreSQL over MongoDB (NoSQL)?
* **Relational Integrity:** The connection between `videos` and `comments` is strictly 1-to-many. Relational keys with `FOREIGN KEY` constraints and `ON DELETE CASCADE` prevent orphaned comments, maintaining absolute referential integrity.
* **Structured Analytics:** Analytical aggregations (e.g. calculating engagement percentages or commenter counts) are much simpler, highly optimized, and faster in SQL than in Mongo's Aggregation Framework.

---

## 3. Scaling to 50k+ Videos: Cloud Migration & Orchestration Strategy

If we were to scale this pipeline from 5 channels and 50 videos to thousands of channels and 50,000+ videos with comments, we would transition from plain Python to **Apache Airflow** and cloud object storage:

### A. Pipeline Orchestration (Apache Airflow)
We would define a **DAG-per-channel** pattern or a dynamic DAG generator. Airflow provides several key advantages at scale:
* **Task-Level Retries & Monitoring:** If an API call fails due to quota exhaustion or a transient network outage, Airflow will automatically retry only the failed task (e.g. `fetch_comments`) rather than restarting the entire channel loop.
* **Rate-Limit Aware Pool Management:** We can set up an Airflow "pool" with a concurrency limit (e.g., maximum 5 concurrent workers querying the YouTube API) to stay within YouTube's rate limits and avoid `429 Too Many Requests` errors.

### B. Storage & Partitioning
* **Raw Landing Zone in S3/GCS:** Writing raw files locally on container mounts wouldn't scale. We would stream raw JSON directly to cloud object storage (AWS S3 or Google Cloud Storage) partitioned by date and channel ID: `s3://youtube-raw-landing/year=2026/month=07/channel_id=UC.../`.
* **Database Partitioning:** Storing 50,000 videos and their associated comments (which could easily exceed 5,000,000 rows) would slow down index searches. We would **partition the `comments` table by range of `published_at`** (monthly partitions), keeping index lookups extremely fast.
* **Incremental Loads:** Instead of listing the entire uploads playlist, we would implement incremental syncing—checking the latest `published_at` date stored in our database for that channel and stopping the API ingestion loop as soon as we hit a video we have already stored.

---

## 4. Plain Python Orchestration vs. Heavy Frameworks

For this specific project scope (5 channels, ~50 videos, dockerized deployment), using **plain Python** instead of Airflow/NiFi was the correct, pragmatic engineering decision:

1. **Infrastructure Simplicity:** Setting up Airflow requires running a scheduler, a webserver, a database backend (metadata db), and a message broker (like Redis). This infrastructure overhead consumes significant CPU/RAM and complicates local Docker setups, adding zero value for a lightweight batch job.
2. **Deterministic execution:** Since our pipeline runs sequentially in under 45 seconds, the overhead of Airflow task scheduling (which is usually a few seconds per task) would take longer than the code execution itself.
3. **Container footprint:** A plain Python container image is minimal (~150MB slim base), whereas an Airflow docker footprint often exceeds 1.2GB and requires complex configuration, slowing down CI/CD pipelines and deployment times.

---

## 5. Handle Configuration & Local Caching Mechanism

To achieve the best balance of scalability, readability, and cost optimization, the pipeline implements a dynamic **Handle Caching System**:

* **Handles Configuration:** Instead of obfuscated `UC...` channel IDs, developers and administrators configure readable `@handles` in `src/config.py` (e.g. `@Saba7oKorah`, `@PeaceCake`).
* **Local ID Cache (`data/channel_cache.json`):** 
  * When a channel is processed, the pipeline checks a local JSON mapping file.
  * If the handle is found, it uses the cached `UC...` channel ID, avoiding a YouTube API request (**0 API quota units consumed**).
  * If the handle is new, the pipeline calls the cheap `channels.list(forHandle=...)` API endpoint (**1 quota unit**), retrieves the `UC...` ID, and writes it to the local cache.
* **Volume Mount Integration:** By mounting the host's `data/` directory to the container (`./data:/app/data`), the cache remains persistent across container recreations and runs, while being gitignored (`data/channel_cache.json` in `.gitignore`) to prevent bloating the source repository on Github.

