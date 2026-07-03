import os
import sys
import argparse
import logging
from dotenv import load_dotenv

from src.api_client import YouTubeAPIClient
from src.storage import Database
from src.ingest import IngestionPipeline
from src.config import RESOLVED_CHANNELS

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def run_analysis(db: Database):
    """Placeholder for Phase 6 analysis queries."""
    # We will implement query execution here in Phase 6.
    # For now, let's print a placeholder message.
    print("\n[Analysis mode enabled] Executing database reports...")
    
    # We can load queries from queries/analysis.sql or run them directly.
    # We'll fully implement this in Phase 6.
    print("No queries executed yet (Phase 6 implementation pending).")

def main():
    parser = argparse.ArgumentParser(description="YouTube Data Ingestion & Analysis Pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and save raw JSON files locally, but do not write to PostgreSQL"
    )
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
    if not args.dry_run:
        try:
            db.create_schema()
        except Exception as e:
            logger.error(f"Failed to apply database schema: {e}")
            db.close()
            sys.exit(1)

    # Initialize client and pipeline
    client = YouTubeAPIClient(api_key=api_key)
    pipeline = IngestionPipeline(api_client=client, db=db)

    # Tracking statistics
    totals = {
        "videos_fetched": 0,
        "comments_fetched": 0,
        "videos_loaded": 0,
        "comments_loaded": 0
    }

    print("\n==============================================")
    print(f"Starting Ingestion Run (Dry-Run: {args.dry_run})")
    print(f"Limits: {args.limit_videos} videos/channel, {args.limit_comments} comments/video")
    print("==============================================\n")

    for channel_name, channel_id in RESOLVED_CHANNELS.items():
        print(f"--- Channel: {channel_name} ({channel_id}) ---")
        try:
            summary = pipeline.run_for_channel(
                channel_id_or_handle=channel_id,
                max_videos=args.limit_videos,
                max_comments_per_video=args.limit_comments,
                dry_run=args.dry_run
            )
            print(f"  Videos Fetched: {summary['videos_fetched']}")
            print(f"  Comments Fetched: {summary['comments_fetched']}")
            print(f"  Videos Loaded to DB: {summary['videos_loaded']}")
            print(f"  Comments Loaded to DB: {summary['comments_loaded']}\n")

            for k in totals:
                totals[k] += summary[k]

        except Exception as e:
            logger.error(f"Failed to process channel {channel_name}: {e}")

    print("==============================================")
    print("Run Summary:")
    print(f"  Total Videos Fetched: {totals['videos_fetched']}")
    print(f"  Total Comments Fetched: {totals['comments_fetched']}")
    print(f"  Total Videos Loaded to DB: {totals['videos_loaded']}")
    print(f"  Total Comments Loaded to DB: {totals['comments_loaded']}")
    print("==============================================\n")

    db.close()

if __name__ == "__main__":
    main()
