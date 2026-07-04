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
| `IngestionPipeline` | `src/ingest.py` | **Orchestrator (ELT Tasks):** Exposes two decoupled orchestration tasks matching Airflow DAG designs: `youtube_to_landing` (queries API and writes raw JSON files to the landing layer) and `landing_to_postgres` (reads landed files, transforms them, and bulk upserts them to the PostgreSQL staging layer). |
| `main.py` | `main.py` | **Entry Point:** Handles environment bootstrapping, command-line argument parsing, logging setup, and sequentially fires the pipeline tasks (`youtube_to_landing` followed by `landing_to_postgres`). |

---

## 2. Storage Justification

We chose **PostgreSQL** in a dockerized container as the primary data store over alternatives like SQLite or MongoDB:


### Why PostgreSQL over MongoDB (NoSQL)?
* **Relational Integrity:** The connection between `videos` and `comments` is strictly 1-to-many. Relational keys with `FOREIGN KEY` constraints and `ON DELETE CASCADE` prevent orphaned comments, maintaining absolute referential integrity.
* **Structured Analytics:** Analytical aggregations (e.g. calculating engagement percentages or commenter counts) are much simpler, highly optimized, and faster in SQL than in Mongo's Aggregation Framework.
* **Horizontal Scaling Limitations on Relational Data:** While MongoDB is designed to scale horizontally across clusters using document collections, highly relational datasets (like videos and comments) do not scale horizontally well in a NoSQL document model. If comment documents are distributed across different nodes in a cluster, running aggregates and lookups (like joining video and comment collections) to calculate video or channel engagement metrics becomes a massive performance bottleneck. PostgreSQL handles these structured relations and aggregations natively and efficiently.

---

## 3. Scaling to 50k+ Videos: Cloud Migration & Orchestration Strategy

If we were to scale this pipeline from 5 channels and 50 videos to thousands of channels and 50,000+ videos with comments, we would transition from plain Python to a distributed cloud architecture:

### A. Pipeline Orchestration & Scheduling (Apache Airflow)
We would transition our batch pipeline runs to **Apache Airflow**, scheduled to run as daily cron batches. At scale, Airflow provides several key advantages:
* **Task-Level Retries & Monitoring:** If an API call fails due to quota exhaustion or a transient network outage, Airflow will automatically retry only the failed task (e.g. `fetch_comments`) rather than restarting the entire channel loop.
* **Rate-Limit Aware Pool Management:** We can set up an Airflow "pool" with a concurrency limit (e.g., maximum 5 concurrent workers querying the YouTube API) to stay within YouTube's rate limits and avoid `429 Too Many Requests` errors.

### B. Storage & Partitioning (Cloud Landing Layer)
* **Raw Landing Zone in S3/GCS:** Writing raw files locally on container mounts wouldn't scale. We would stream raw JSON directly to cloud object storage (AWS S3 or Google Cloud Storage) partitioned by date and channel ID: `s3://youtube-raw-landing/year=2026/month=07/channel_id=UC.../`.
* **Incremental Loads:** Instead of listing the entire uploads playlist, we would implement incremental syncing—checking the latest `published_at` date stored in our database for that channel and stopping the API ingestion loop as soon as we hit a video we have already stored.

### C. Data Quality & Alerting (Great Expectations)
To protect downstream dashboard reports and tables from corrupt raw inputs, we would integrate **Great Expectations** as our validation gatekeeper:
* **Data Assertions:** Run automatic checks on schema validation, null thresholds (e.g., ensuring comment text or author display names are not null), and timestamp sanity bounds.
* **Automated Alerting System:** Connect Great Expectations validation runs to Slack, Microsoft Teams, or PagerDuty. If a validation check fails due to schema drift (e.g., YouTube changing their API payload format) or anomalous null counts, an alert is dispatched automatically to the engineering team for triage.

### D. Enterprise Data Warehousing (Clustering & Partitioning)
Instead of PostgreSQL, we would load the staging data into a dedicated Cloud Data Warehouse like **Snowflake**, **Google BigQuery**, or **Amazon Redshift**:
* **Partitioning:** We would partition our database tables by date (`published_at`) to isolate daily query scans.
* **Clustering:** We would cluster the tables by `channel_id` or `video_id`. This ensures that when analysts look up comments for a specific channel or video, the query scans only the relevant micro-partitions, dramatically reducing query run times and database scan costs.

### E. Analytics Team Collaboration & Data Modeling
To optimize the dashboard experiences, we would work closely with the analytics and BI teams to design optimized data models within the Data Warehouse:
* **dbt (data build tool):** Use `dbt` to build modular SQL transformations on top of our staging tables, transforming normalized tables into dimensional models (Star Schemas with rich dimension and fact tables).
* **Pre-Aggregated Summary Tables:** Build pre-aggregated summary tables (e.g., daily engagement metrics per channel) to speed up queries and ensure their Power BI, Tableau, or Looker Studio dashboards render in under 1 second.

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

---

## 6. Decoupled ELT Architecture (Airflow DAG Design Pattern)

To align with standard data engineering practices and ensure high robustness, the pipeline splits the execution run into two fully decoupled tasks matching the steps of an Airflow DAG:

1. **`youtube_to_landing` (Extract Task):**
   - Connects to the YouTube Data API and fetches channel details, videos, and comments.
   - Saves raw JSON payloads directly into the **landing layer** (`data/raw/{channel_id}/{video_id}.json`).
   - **DB Offline Resiliency:** This task has zero connection to the database. If PostgreSQL is temporarily offline, raw ingestion still succeeds, preventing redundant API calls.
2. **`landing_to_postgres` (Load & Transform Task):**
   - Reads files on disk from the **landing layer** (`data/raw/`).
   - Transforms JSON payloads into strongly-typed dataclasses using `VideoTransformer`.
   - Loads and bulk-upserts them to the **PostgreSQL staging layer**.
   - **API Offline Resiliency:** This task makes zero API calls. If PostgreSQL was offline or schema migrations failed, this task can be run independently to load data from the landing files without burning YouTube API quota.

---

## 7. Part 6: Design Reflection & Stress Test

This section contains formal, structured answers to the assessment's Part 6 questions:

### Q1 — Why did you structure your solution the way you did?
We split the pipeline into clear, modular components complying with the **Single Responsibility Principle (SRP)**:
1. **`YouTubeAPIClient`** manages connections, timeout backoffs, and raw queries.
2. **`VideoTransformer`** maps nested structures to clean, flat Python dataclasses.
3. **`Database`** manages schemas, connections, and high-performance transactional upserts.
4. **`IngestionPipeline`** acts as the orchestrator.

To follow best practices for staging/ELT data layers, we separated the orchestration flow into two decoupled Airflow-style tasks: `youtube_to_landing` (extracting and dumping raw JSON files to the **landing layer**) and `landing_to_postgres` (reading, transforming, and batch loading to the **PostgreSQL staging layer**). This prevents code coupling and enables reprocessing raw files without querying external APIs.

### Q2 — What would break at scale (50,000+ videos)?
Scaling the pipeline from 50 to 50,000+ videos exposes several key bottlenecks:
1. **YouTube API Quota Limits:** Listing and retrieving comments for 50,000 videos would quickly consume the 10,000 daily quota. We would address this by implementing **Incremental Ingestion** (stopping the fetching loop when hitting a video ID already present in the database) and utilizing multiple client API keys.
2. **Database Connection & Write Overhead:** Inserting items one by one would cause heavy write lock wait times. We would address this by scaling our PostgreSQL configuration, indexing search fields, partitioning the `comments` table by month (`published_at`), and using bulk upsert loads.
3. **Network Latency & Memory Footprint:** Sequentially downloading details for 50,000 videos would take hours. We would address this by running asynchronous/parallel workers under Apache Airflow pools (limiting concurrent workers to prevent API rate limiting) and streaming JSON dumps directly to cloud storage (S3/GCS) instead of local container storage.

### Q3 — What would you improve with more time?
If given an extra hour, we would implement **Incremental Syncing**:
* Currently, `youtube_to_landing` downloads the top $N$ videos from the playlist.
* With more time, we would query the database to find the latest `published_at` timestamp for each channel, and pass this timestamp to the API client. The client would then stop fetching playlist items as soon as it encounters a video older than our last sync point.
* This would dramatically reduce API quota consumption and run times for subsequent daily cron runs.

---

## 8. Analytical Output persistency & BI Visualization (Production Expansion)

For this assessment, the analytics results are printed to the console and automatically exported to CSV files inside the `data/analytics query results/` directory for manual analysis in Excel or Sheets. 

In a production setup, we would implement the following architecture to automate dashboard visualizations:

### A. Persistent PostgreSQL Views
Rather than querying raw tables, we would register the analytical queries as database views:
```sql
CREATE VIEW view_channel_engagement AS
SELECT 
    channel_name,
    ROUND((SUM(like_count + comment_count)::numeric / NULLIF(SUM(view_count), 0)) * 100, 4) as engagement_rate
FROM videos 
GROUP BY channel_name;
```

### B. Business Intelligence (BI) Dashboard Integration
By registering views inside the database, we can connect BI reporting tools to query PostgreSQL directly:
1. **Looker Studio (Google):** We can connect Looker Studio directly to our PostgreSQL database using Google's Cloud SQL or PostgreSQL connector. This allows us to create free, shareable interactive reports on YouTube video views and engagement rates.
2. **Power BI / Tableau:** We can configure Power BI or Tableau to query our relational views. This allows business stakeholders to refresh the dashboard instantly to see live updates as the pipeline pulls fresh data.
3. **Metabase:** A lightweight, dockerized BI tool that runs on the same Docker Compose stack. We can spin up a `metabase` service in `docker-compose.yml` to automatically connect to PostgreSQL and build graphs without requiring any desktop software.

