-- Create tables for YouTube Data Pipeline
CREATE TABLE IF NOT EXISTS videos (
    video_id VARCHAR(50) PRIMARY KEY,
    channel_id VARCHAR(50) NOT NULL,
    channel_name VARCHAR(255) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    published_at TIMESTAMPTZ NOT NULL,
    view_count BIGINT DEFAULT 0,
    like_count BIGINT DEFAULT 0,
    comment_count BIGINT DEFAULT 0,
    duration VARCHAR(50),
    fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS comments (
    comment_id VARCHAR(50) PRIMARY KEY,
    video_id VARCHAR(50) REFERENCES videos(video_id) ON DELETE CASCADE,
    author VARCHAR(255) NOT NULL,
    text TEXT,
    like_count BIGINT DEFAULT 0,
    published_at TIMESTAMPTZ NOT NULL
);

-- Create indexes for performance optimization
CREATE INDEX IF NOT EXISTS idx_videos_channel_id ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_comments_video_id ON comments(video_id);
