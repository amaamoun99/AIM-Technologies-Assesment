-- Query 1: Top 10 videos by view count

SELECT 
    video_id, 
    channel_name, 
    title, 
    view_count, 
    published_at 
FROM videos 
ORDER BY view_count DESC 
LIMIT 10;

--  Average comments per video, grouped by channel

SELECT 
    channel_name, 
    ROUND(AVG(comment_count), 2) as avg_comments
FROM videos 
GROUP BY channel_name 
ORDER BY avg_comments DESC;

-- Top 10 most active commenters 

SELECT 
    author, 
    COUNT(*) as comment_count 
FROM comments 
GROUP BY author 
ORDER BY comment_count DESC 
LIMIT 10;

-- Engagement rate per channel

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
