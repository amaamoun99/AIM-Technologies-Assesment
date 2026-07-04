# YouTube Data Pipeline

A Docker-native, production-ready, quota-efficient data pipeline written in Python that ingests videos and comments from target YouTube channels into a relational PostgreSQL database and generates analytics reports.

---

## Architecture Diagram

The system architecture is summarized in the diagram below:

![Architecture Diagram](diagrams/ELT%20Pipeline.jpg)

Read our detailed architectural reasoning, database decisions, and scaling thoughts in the [Design Notes](design_notes.md).

---

## Features

* **Cheap & Scalable Handle Resolution:** Resolves channel handles dynamically. To optimize cost, it caches resolved `UC...` IDs inside `data/channel_cache.json`. On subsequent runs, it reads the mapping from the local cache costing **0 quota units**!
* **Batch Ingestion:** Batches requests for video details up to 50 items at a time to optimize network and API limits.
* **Robust Error Handling:** Detects videos with disabled comments and records them gracefully without crashing the pipeline execution.
* **Idempotency:** Implements SQL UPSERT logic (`ON CONFLICT DO UPDATE`) to ensure double runs do not corrupt data or fail.
* **Local Landing Zone:** Saves raw API responses under `data/raw/{channel_id}/{video_id}.json` as an immutable record before parsing.
* **Database Analytics:** Runs optimized PostgreSQL aggregation queries to generate reports like viewer engagement rates and top commenters.

---

## Target Channels

The pipeline is preconfigured in [src/config.py](src/config.py) to ingest data using the following handles:
1. **@AJpluskibreet**
2. **@Saba7oKorah**
3. **@SharkTankEgypt**
4. **@PeaceCake**
5. **@kareemelsayedvlogs**

---

## Getting Started

### Prerequisites

* [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/) installed on your machine.
* A YouTube Data API v3 API Key.

### 1. Environment Configuration

Copy the environment template file:
```bash
cp .env.example .env
```

Open `.env` and fill in your YouTube API Key:
```env
YOUTUBE_API_KEY=your_actual_youtube_api_key_here
POSTGRES_USER=pipeline
POSTGRES_PASSWORD=pipeline
POSTGRES_DB=youtube
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
```

### 2. Build and Start Services

Launch the Postgres database container and the App runner:
```bash
docker compose up --build -d
```
*The database has a healthcheck block. The app container waits for the database to accept connections before running.*

### 3. Run Ingestion (Decoupled ELT Flow)

To run the data ingestion pipeline tasks:
```bash
docker compose run --rm app python main.py
```

This executes two decoupled tasks matching Airflow DAG design patterns:
1. **Task 1: `youtube_to_landing`:** Connects to the YouTube Data API, resolves channel handles (using the cache), and extracts raw JSON payloads to the **landing layer** (`data/raw/{channel_id}/{video_id}.json`).
2. **Task 2: `landing_to_postgres`:** Reads the JSON files from the landing layer, transforms them into structured data, and loads/bulk-upserts them to the **PostgreSQL staging layer**.

**Options & Limits:**
* `--limit-videos N`: Max videos to pull per channel (default: `10`, pulls `50` total).
* `--limit-comments N`: Max comments to pull per video (default: `5`).

> [!NOTE]
> **Handle Resolution Caching:**
> The cache file `data/channel_cache.json` is gitignored to avoid checking private maps into Git. On the **first run**, the pipeline queries the cheap `channels` endpoint of the YouTube API (1 quota unit per channel) to resolve the configured handles and writes them to `data/channel_cache.json`. Subsequent pipeline runs read mappings directly from this file, ensuring **0 resolution quota units** are consumed!

### 4. Run Analytics Reports

To run the SQL analytics queries on the ingested data and print tables:
```bash
docker compose run --rm app python main.py --analyze
```

This generates 4 analytical reports:
* **Report 1:** Top 10 videos by view count.
* **Report 2:** Average comment count per video per channel.
* **Report 3:** Top 10 most active comment authors.
* **Report 4:** Channel-level engagement rate: `SUM(likes + comments) / SUM(views) * 100`.

The execution output of each report query is automatically printed to stdout and saved as a CSV file inside the `data/analytics query results/` directory for Excel/Google Sheets review.


### 5. Run Automated Tests

To execute the unit test suite (19 tests covering models, API clients, transformers, database repositories, and pipelines):
```bash
docker compose run --rm -e ALLOW_TEST_TRUNCATE=1 app pytest
```

> [!IMPORTANT]
> **Production Database Safeguard:**
> To prevent accidental data loss, the test suite includes a safety check that blocks test database truncation on database names matching the production name (`youtube`). To run the tests, you must explicitly pass `-e ALLOW_TEST_TRUNCATE=1` to allow the test suite to clear and seed its mock data tables.
