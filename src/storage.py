import os
import logging
import psycopg2
from psycopg2.extras import DictCursor, execute_batch
from typing import Any, Dict, List, Optional
from src.models import Video, Comment

logger = logging.getLogger(__name__)

class Database:
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        dbname: Optional[str] = None
    ):
        self.host = host or os.getenv("POSTGRES_HOST", "localhost")
        self.port = port or os.getenv("POSTGRES_PORT", "5432")
        self.user = user or os.getenv("POSTGRES_USER", "pipeline")
        self.password = password or os.getenv("POSTGRES_PASSWORD", "pipeline")
        self.dbname = dbname or os.getenv("POSTGRES_DB", "youtube")
        self.conn = None

    def connect(self):
        """Establish connection to PostgreSQL database."""
        if not self.conn or self.conn.closed:
            try:
                self.conn = psycopg2.connect(
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    password=self.password,
                    dbname=self.dbname
                )
                logger.info("Connected to database successfully")
            except Exception as e:
                logger.error(f"Failed to connect to database: {e}")
                raise

    def close(self):
        """Close connection to the database."""
        if self.conn and not self.conn.closed:
            self.conn.close()
            logger.info("Database connection closed")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def create_schema(self, schema_file_path: str = "/app/queries/schema.sql"):
        """Execute the queries/schema.sql script to initialize tables and indexes."""
        if not os.path.exists(schema_file_path):
            # Fallback for local vs container pathing
            schema_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "queries", "schema.sql")

        try:
            with open(schema_file_path, "r", encoding="utf-8") as f:
                schema_sql = f.read()

            with self.conn.cursor() as cursor:
                cursor.execute(schema_sql)
            self.conn.commit()
            logger.info("Schema applied successfully")
        except Exception as e:
            if self.conn:
                self.conn.rollback()
            logger.error(f"Failed to apply schema: {e}")
            raise

    def insert_videos(self, videos: List[Video]):
        """Batch insert or update videos."""
        if not videos:
            return

        sql = """
            INSERT INTO videos (
                video_id, channel_id, channel_name, title, description, 
                published_at, view_count, like_count, comment_count, duration, fetched_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (video_id) DO UPDATE SET
                channel_id = EXCLUDED.channel_id,
                channel_name = EXCLUDED.channel_name,
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                published_at = EXCLUDED.published_at,
                view_count = EXCLUDED.view_count,
                like_count = EXCLUDED.like_count,
                comment_count = EXCLUDED.comment_count,
                duration = EXCLUDED.duration,
                fetched_at = EXCLUDED.fetched_at;
        """

        params = [
            (
                v.video_id,
                v.channel_id,
                v.channel_name,
                v.title,
                v.description,
                v.published_at,
                v.view_count,
                v.like_count,
                v.comment_count,
                v.duration,
                v.fetched_at
            )
            for v in videos
        ]

        try:
            with self.conn.cursor() as cursor:
                execute_batch(cursor, sql, params, page_size=100)
            self.conn.commit()
            logger.info(f"Successfully inserted/updated {len(videos)} videos")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to insert videos: {e}")
            raise

    def insert_comments(self, comments: List[Comment]):
        """Batch insert or update comments."""
        if not comments:
            return

        sql = """
            INSERT INTO comments (
                comment_id, video_id, author, text, like_count, published_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (comment_id) DO UPDATE SET
                video_id = EXCLUDED.video_id,
                author = EXCLUDED.author,
                text = EXCLUDED.text,
                like_count = EXCLUDED.like_count,
                published_at = EXCLUDED.published_at;
        """

        params = [
            (
                c.comment_id,
                c.video_id,
                c.author,
                c.text,
                c.like_count,
                c.published_at
            )
            for c in comments
        ]

        try:
            with self.conn.cursor() as cursor:
                execute_batch(cursor, sql, params, page_size=100)
            self.conn.commit()
            logger.info(f"Successfully inserted/updated {len(comments)} comments")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to insert comments: {e}")
            raise

    def run_query(self, sql: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        """Run arbitrary SELECT queries and return results as lists of dictionaries."""
        try:
            with self.conn.cursor(cursor_factory=DictCursor) as cursor:
                cursor.execute(sql, params)
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    return [dict(zip(columns, row)) for row in cursor.fetchall()]
                return []
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            raise
