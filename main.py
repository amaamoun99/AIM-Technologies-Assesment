import os
import sys
import argparse
import logging
import csv
from typing import List, Dict, Any
from dotenv import load_dotenv

from src.api_client import YouTubeAPIClient
from src.storage import Database
from src.ingest import IngestionPipeline
from src.config import CHANNELS, CACHE_FILE_PATH

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def print_table(title: str, rows: list):
    if not rows:
        print(f"\n--- {title} ---")
        print("No results returned.")
        return

    columns = list(rows[0].keys())
    
    # Compute max width of each column
    col_widths = {col: len(col) for col in columns}
    for row in rows:
        for col in columns:
            val_str = str(row[col]) if row[col] is not None else "NULL"
            if len(val_str) > col_widths[col]:
                col_widths[col] = len(val_str)
                
    # Print table header
    print(f"\n--- {title} ---")
    header_border = "+" + "+".join("-" * (col_widths[col] + 2) for col in columns) + "+"
    print(header_border)
    header_row = "|" + "|".join(f" {col.ljust(col_widths[col])} " for col in columns) + "|"
    print(header_row)
    print(header_border)
    
    # Print data rows
    for row in rows:
        row_str = "|" + "|".join(
            f" {str(row[col] if row[col] is not None else 'NULL').ljust(col_widths[col])} "
            for col in columns
        ) + "|"
        print(row_str)
    print(header_border)

def save_to_csv(name: str, results: List[Dict[str, Any]], output_dir: str = "data/analytics query results"):
    if not results:
        return
    os.makedirs(output_dir, exist_ok=True)
    csv_file_path = os.path.join(output_dir, f"{name}.csv")
    try:
        keys = results[0].keys()
        with open(csv_file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(results)
        logger.info(f"Saved analytics output to CSV: {csv_file_path}")
    except Exception as e:
        logger.error(f"Failed to save analytics CSV for query {name}: {e}")

def run_analysis(db: Database):
    """Execute analytical queries from queries/analysis.sql, print tables, and export to CSV."""
    print("\n==============================================")
    print("Executing Database Analytics Reports")
    print("==============================================")
    
    sql_file_path = "/app/queries/analysis.sql"
    if not os.path.exists(sql_file_path):
        # Fallback for local run
        sql_file_path = os.path.join(os.path.dirname(__file__), "queries", "analysis.sql")
        
    if not os.path.exists(sql_file_path):
        logger.error(f"Analysis SQL file not found at: {sql_file_path}")
        return
 
    try:
        with open(sql_file_path, "r", encoding="utf-8") as f:
            sql_content = f.read()
    except Exception as e:
        logger.error(f"Failed to read analysis SQL file: {e}")
        return

    # Split queries by semicolon
    raw_queries = sql_content.split(";")
    query_index = 1

    for raw_query in raw_queries:
        query = raw_query.strip()
        if not query:
            continue

        # Extract title and name from the query comments
        lines = query.split("\n")
        title = f"Report Query {query_index}"
        name = f"query_{query_index}"
        for line in lines:
            if line.strip().startswith("--"):
                comment = line.strip().lstrip("-").strip()
                if comment.lower().startswith("query"):
                    title = comment
                elif comment.lower().startswith("name:"):
                    name = comment.split(":", 1)[1].strip()

        try:
            results = db.run_query(query)
            print_table(title, results)
            save_to_csv(name, results)
            query_index += 1
        except Exception as e:
            logger.error(f"Failed to run analysis query: {title}. Error: {e}")

def main():
    parser = argparse.ArgumentParser(description="YouTube Data Ingestion & Analysis Pipeline")
    parser.add_argument(
        "--limit-videos",
        type=int,
        default=10,
        help="Maximum videos to fetch per channel (default: 10)"
    )
    parser.add_argument(
        "--limit-comments",
        type=int,
        default=5,
        help="Maximum comments to fetch per video (default: 5)"
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Execute database analysis queries and exit"
    )
    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    # Database configuration
    db_host = os.getenv("POSTGRES_HOST", "postgres")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    db_user = os.getenv("POSTGRES_USER", "pipeline")
    db_password = os.getenv("POSTGRES_PASSWORD", "pipeline")
    db_name = os.getenv("POSTGRES_DB", "youtube")

    db = Database(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_password,
        dbname=db_name
    )

    try:
        db.connect()
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        sys.exit(1)

    if args.analyze:
        run_analysis(db)
        db.close()
        return

    # Ingestion Pipeline Mode
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        logger.error("YOUTUBE_API_KEY is not defined in .env file.")
        db.close()
        sys.exit(1)

    # Make sure database tables are initialized
    try:
        db.create_schema()
    except Exception as e:
        logger.error(f"Failed to apply database schema: {e}")
        db.close()
        sys.exit(1)

    # Initialize client and pipeline
    client = YouTubeAPIClient(api_key=api_key)
    pipeline = IngestionPipeline(api_client=client, db=db, cache_path=CACHE_FILE_PATH)

    # Tracking statistics for landing task
    landing_totals = {
        "videos_landed": 0,
        "comments_landed": 0
    }

    print("\n==============================================")
    print(f"Task 1: youtube_to_landing (Extraction Phase)")
    print(f"Limits: {args.limit_videos} videos/channel, {args.limit_comments} comments/video")
    print("==============================================\n")

    for channel_handle in CHANNELS:
        print(f"--- Landing Channel: {channel_handle} ---")
        try:
            summary = pipeline.youtube_to_landing(
                channel_id_or_handle=channel_handle,
                max_videos=args.limit_videos,
                max_comments_per_video=args.limit_comments
            )
            print(f"  Videos Landed: {summary['videos_staged']}")
            print(f"  Comments Landed: {summary['comments_staged']}\n")

            landing_totals["videos_landed"] += summary["videos_staged"]
            landing_totals["comments_landed"] += summary["comments_staged"]

        except Exception as e:
            logger.error(f"Failed to land channel {channel_handle}: {e}")

    print("==============================================")
    print("Landing Extraction Summary:")
    print(f"  Total Videos Landed: {landing_totals['videos_landed']}")
    print(f"  Total Comments Landed: {landing_totals['comments_landed']}")
    print("==============================================\n")

    # Task 2: landing_to_postgres (Transformation & Loading Phase)
    db_totals = {
        "videos_loaded": 0,
        "comments_loaded": 0
    }

    print("==============================================")
    print("Task 2: landing_to_postgres (Loading Phase)")
    print("==============================================\n")
    try:
        db_summary = pipeline.landing_to_postgres()
        print(f"  Videos Loaded to Postgres DB: {db_summary['videos_loaded']}")
        print(f"  Comments Loaded to Postgres DB: {db_summary['comments_loaded']}\n")
        db_totals["videos_loaded"] = db_summary["videos_loaded"]
        db_totals["comments_loaded"] = db_summary["comments_loaded"]
    except Exception as e:
        logger.error(f"Failed to load landing data to PostgreSQL: {e}")

    db.close()

if __name__ == "__main__":
    main()
