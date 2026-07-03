import os
import pytest
import psycopg2
from datetime import datetime, timezone
from src.storage import Database
from src.models import Video, Comment

@pytest.fixture(scope="module")
def db():
    # Use environment variables passed by docker-compose or defaults for container testing
    database = Database(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        user=os.getenv("POSTGRES_USER", "pipeline"),
        password=os.getenv("POSTGRES_PASSWORD", "pipeline"),
        dbname=os.getenv("POSTGRES_DB", "youtube")
    )
    database.connect()
    yield database
    database.close()

def test_create_schema_and_inserts(db):
    # Initialize the schema
    db.create_schema()

    # Clear tables to ensure clean state
    if db.dbname == "youtube" and os.getenv("ALLOW_TEST_TRUNCATE") != "1":
        pytest.fail("Safety Block: Attempting to truncate production database 'youtube' during unit tests. Set environment variable ALLOW_TEST_TRUNCATE=1 to bypass.")

    with db.conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE comments, videos CASCADE;")
    db.conn.commit()

    now = datetime.now(timezone.utc)
    
    # 1. Insert 2 fixture videos
    video1 = Video(
        video_id="vid_1",
        channel_id="chan_1",
        channel_name="Channel One",
        title="Video One",
        description="First Description",
        published_at=now,
        view_count=100,
        like_count=10,
        comment_count=1,
        duration="PT1M",
        fetched_at=now
    )
    video2 = Video(
        video_id="vid_2",
        channel_id="chan_1",
        channel_name="Channel One",
        title="Video Two",
        description="Second Description",
        published_at=now,
        view_count=200,
        like_count=20,
        comment_count=2,
        duration="PT2M",
        fetched_at=now
    )
    db.insert_videos([video1, video2])

    # Insert 3 fixture comments (referenced correctly)
    comment1 = Comment(
        comment_id="c_1",
        video_id="vid_1",
        author="Alice",
        text="Loved this!",
        like_count=2,
        published_at=now
    )
    comment2 = Comment(
        comment_id="c_2",
        video_id="vid_1",
        author="Bob",
        text="Interesting",
        like_count=0,
        published_at=now
    )
    comment3 = Comment(
        comment_id="c_3",
        video_id="vid_2",
        author="Charlie",
        text="Great job!",
        like_count=5,
        published_at=now
    )
    db.insert_comments([comment1, comment2, comment3])

    # Verify counts
    res_videos = db.run_query("SELECT COUNT(*) as cnt FROM videos;")
    assert res_videos[0]["cnt"] == 2

    res_comments = db.run_query("SELECT COUNT(*) as cnt FROM comments;")
    assert res_comments[0]["cnt"] == 3

def test_upsert_conflict_handling(db):
    now = datetime.now(timezone.utc)
    
    # 2. Re-insert the same video (conflict path) - modify views
    updated_video1 = Video(
        video_id="vid_1",
        channel_id="chan_1",
        channel_name="Channel One",
        title="Video One Updated",
        description="First Description Updated",
        published_at=now,
        view_count=999, # changed
        like_count=10,
        comment_count=1,
        duration="PT1M",
        fetched_at=now
    )
    
    db.insert_videos([updated_video1])
    
    # Assert no duplicate row, but values updated
    res = db.run_query("SELECT title, view_count FROM videos WHERE video_id = 'vid_1';")
    assert len(res) == 1
    assert res[0]["title"] == "Video One Updated"
    assert res[0]["view_count"] == 999

def test_foreign_key_constraint(db):
    now = datetime.now(timezone.utc)
    
    # 4. Insert a comment referencing a non-existent video_id - assert FK rejects it
    invalid_comment = Comment(
        comment_id="c_invalid",
        video_id="non_existent_video_id", # invalid
        author="Deadpool",
        text="Where am I?",
        like_count=0,
        published_at=now
    )
    
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        db.insert_comments([invalid_comment])
    
    # Clean up transaction state since constraint error aborts transaction
    db.conn.rollback()
