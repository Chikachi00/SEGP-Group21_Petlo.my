-- Additive Petlo API extension. Import petlo.sql first; no legacy table is altered.


CREATE TABLE IF NOT EXISTS analysis_sessions (
	session_id VARCHAR(64) NOT NULL, 
	dog_id INTEGER NOT NULL, 
	trainer_id INTEGER NOT NULL, 
	recorded_at VARCHAR(40) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	current_job_id VARCHAR(64), 
	PRIMARY KEY (session_id), 
	FOREIGN KEY(dog_id) REFERENCES dogs (dog_id), 
	FOREIGN KEY(trainer_id) REFERENCES user_login (user_id)
)

;


CREATE TABLE IF NOT EXISTS analysis_jobs (
	job_id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	stage VARCHAR(64), 
	mode VARCHAR(16) NOT NULL, 
	video_ids JSON NOT NULL, 
	result_json JSON, 
	error_json JSON, 
	created_at VARCHAR(40) NOT NULL, 
	finished_at VARCHAR(40), 
	PRIMARY KEY (job_id), 
	FOREIGN KEY(session_id) REFERENCES analysis_sessions (session_id)
)

;


CREATE TABLE IF NOT EXISTS analysis_videos (
	video_id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	legacy_video_id INTEGER NOT NULL, 
	camera_perspective VARCHAR(16) NOT NULL, 
	storage_key VARCHAR(1023) NOT NULL, 
	preview_key VARCHAR(1023), 
	source_sha256 VARCHAR(64) NOT NULL, 
	metadata_json JSON NOT NULL, 
	PRIMARY KEY (video_id), 
	UNIQUE (session_id, camera_perspective), 
	FOREIGN KEY(session_id) REFERENCES analysis_sessions (session_id), 
	FOREIGN KEY(legacy_video_id) REFERENCES video (video_id)
)

;


CREATE TABLE IF NOT EXISTS analysis_events (
	event_id VARCHAR(128) NOT NULL, 
	job_id VARCHAR(64) NOT NULL, 
	category VARCHAR(40) NOT NULL, 
	conflict BOOL NOT NULL, 
	source_intervals JSON NOT NULL, 
	PRIMARY KEY (event_id), 
	FOREIGN KEY(job_id) REFERENCES analysis_jobs (job_id)
)

;

