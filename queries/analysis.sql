-- Query 1: Top 10 videos by view count
-- NAME: top_videos_by_views
SELECT 
    video_id, 
    channel_name, 
    title, 
    view_count, 
    published_at 
FROM videos 
ORDER BY view_count DESC 
LIMIT 10;

-- Query 2: Average comments per video, grouped by channel
-- NAME: avg_comments_per_channel
SELECT 
    channel_name, 
    ROUND(AVG(comment_count), 2) as avg_comments
FROM videos 
GROUP BY channel_name 
ORDER BY avg_comments DESC;

-- Query 3: Top 10 most active commenters (by comment count)
-- NAME: top_active_commenters
SELECT 
    author, 
    COUNT(*) as comment_count 
FROM comments 
GROUP BY author 
ORDER BY comment_count DESC 
LIMIT 10;

-- Query 4: Engagement rate per channel, ranked (Option A: Sum-Ratio)
-- NAME: channel_engagement_rate
SELECT 
    channel_name,
    SUM(like_count) as total_likes,
    SUM(comment_count) as total_comments,
    SUM(view_count) as total_views,
    ROUND(
        (SUM(like_count + comment_count)::numeric / NULLIF(SUM(view_count), 0)) * 100, 
        4
    ) as engagement_rate_percentage
FROM videos 
GROUP BY channel_name 
ORDER BY engagement_rate_percentage DESC;
