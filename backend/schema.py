from db import get_db_connection


def initialize_database():
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS videos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            youtube_video_id VARCHAR(32) NOT NULL UNIQUE,
            url VARCHAR(500) NOT NULL,
            title VARCHAR(500) NULL,
            duration_seconds INT NULL,
            status ENUM('processing', 'ready', 'failed') NOT NULL DEFAULT 'processing',
            error_message TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transcript_segments (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            video_id INT NOT NULL,
            segment_index INT NOT NULL,
            start_time DECIMAL(12,3) NOT NULL,
            duration DECIMAL(12,3) NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_video_segment(video_id, segment_index),
            INDEX idx_transcript_video_start(video_id, start_time),
            CONSTRAINT fk_transcript_video
                FOREIGN KEY (video_id) REFERENCES videos(id)
                ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transcript_chunks (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            video_id INT NOT NULL,
            chunk_index INT NOT NULL,
            start_time DECIMAL(12,3) NOT NULL,
            end_time DECIMAL(12,3) NOT NULL,
            text LONGTEXT NOT NULL,
            word_count INT NOT NULL DEFAULT 0,
            segment_count INT NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_video_chunk(video_id, chunk_index),
            INDEX idx_chunks_video_time(video_id, start_time, end_time),
            CONSTRAINT fk_chunk_video
                FOREIGN KEY (video_id) REFERENCES videos(id)
                ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS video_topics (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            video_id INT NOT NULL,
            title VARCHAR(255) NOT NULL,
            description TEXT NOT NULL,
            start_time DECIMAL(12,3) NOT NULL,
            end_time DECIMAL(12,3) NOT NULL,
            evidence_chunk_indices TEXT NULL,
            evidence_excerpt TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_topics_video(video_id),
            CONSTRAINT fk_topic_video
                FOREIGN KEY (video_id) REFERENCES videos(id)
                ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS video_concepts (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            video_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            definition TEXT NOT NULL,
            start_time DECIMAL(12,3) NOT NULL,
            end_time DECIMAL(12,3) NOT NULL,
            evidence_chunk_indices TEXT NULL,
            evidence_excerpt TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_concepts_video(video_id),
            CONSTRAINT fk_concept_video
                FOREIGN KEY (video_id) REFERENCES videos(id)
                ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS video_key_points (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            video_id INT NOT NULL,
            point TEXT NOT NULL,
            start_time DECIMAL(12,3) NOT NULL,
            end_time DECIMAL(12,3) NOT NULL,
            evidence_chunk_indices TEXT NULL,
            evidence_excerpt TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_key_points_video(video_id),
            CONSTRAINT fk_key_point_video
                FOREIGN KEY (video_id) REFERENCES videos(id)
                ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS video_structure (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            video_id INT NOT NULL,
            section_index INT NOT NULL,
            title VARCHAR(255) NOT NULL,
            summary TEXT NOT NULL,
            start_time DECIMAL(12,3) NOT NULL,
            end_time DECIMAL(12,3) NOT NULL,
            evidence_chunk_indices TEXT NULL,
            evidence_excerpt TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_video_structure(video_id, section_index),
            INDEX idx_structure_video(video_id),
            CONSTRAINT fk_structure_video
                FOREIGN KEY (video_id) REFERENCES videos(id)
                ON DELETE CASCADE
        )
        """
    )

    # Existing Step 4 databases may have been initialized before traceability
    # columns existed. Add them without requiring the user to drop data.
    for table in ("video_topics", "video_concepts", "video_key_points", "video_structure"):
        for column, definition in (
            ("evidence_chunk_indices", "TEXT NULL"),
            ("evidence_excerpt", "TEXT NULL"),
        ):
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = %s
                  AND column_name = %s
                """,
                (table, column),
            )
            exists = cursor.fetchone()[0]
            if not exists:
                cursor.execute(
                    f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}"
                )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS embedding_indexes (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            video_id INT NOT NULL UNIQUE,
            model_name VARCHAR(255) NOT NULL,
            dimension INT NOT NULL,
            chunk_count INT NOT NULL,
            index_version INT NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP,
            CONSTRAINT fk_embedding_index_video
                FOREIGN KEY (video_id) REFERENCES videos(id)
                ON DELETE CASCADE
        )
        """
    )

    connection.commit()
    cursor.close()
    connection.close()
