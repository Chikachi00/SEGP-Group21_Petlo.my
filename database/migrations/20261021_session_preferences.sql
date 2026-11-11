-- Additive metadata only. Existing sessions, videos, jobs and events are preserved.
CREATE TABLE IF NOT EXISTS analysis_session_preferences (
    session_id VARCHAR(64) NOT NULL,
    display_name VARCHAR(120) NULL,
    deleted_at VARCHAR(40) NULL,
    PRIMARY KEY (session_id),
    FOREIGN KEY (session_id) REFERENCES analysis_sessions (session_id)
);
