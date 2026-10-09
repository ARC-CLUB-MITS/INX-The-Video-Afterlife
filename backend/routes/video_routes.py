import json

from flask import Blueprint, jsonify, request

from db import get_db_connection
from services.youtube_service import (
    YouTubeBlockedError,
    YouTubeProcessingError,
    extract_video_id,
    get_transcript,
)
from services.transcript_import_service import (
    TranscriptImportError,
    parse_manual_transcript,
)
from services.chunk_service import build_chunks
from services.llm_service import LLMProcessingError, extract_knowledge, extract_knowledge_extractive
from services.embedding_service import (
    EmbeddingProcessingError,
    build_index,
    delete_index,
    get_index_status,
)
from services.retrieval_service import hybrid_search
from services.qa_service import answer_question

video_bp = Blueprint(
    "video_bp",
    __name__,
    url_prefix="/api/videos",
)


def _save_knowledge(cursor, video_db_id, knowledge, chunks):
    """Persist generated knowledge together with its exact source evidence.

    The LLM never supplies timestamps. It only supplies chunk IDs. This
    function resolves those IDs against the actual stored chunks and stores
    the resulting timestamp range + source excerpt.
    """
    cursor.execute("DELETE FROM video_topics WHERE video_id = %s", (video_db_id,))
    cursor.execute("DELETE FROM video_concepts WHERE video_id = %s", (video_db_id,))
    cursor.execute("DELETE FROM video_key_points WHERE video_id = %s", (video_db_id,))
    cursor.execute("DELETE FROM video_structure WHERE video_id = %s", (video_db_id,))

    chunk_map = {int(chunk["chunk_index"]): chunk for chunk in chunks}

    def evidence(item):
        raw = item.get("evidence_chunk_indices", [])
        if not isinstance(raw, list):
            raise LLMProcessingError("Knowledge item has invalid evidence metadata.")

        indices = []
        for value in raw:
            try:
                index = int(value)
            except (TypeError, ValueError) as exc:
                raise LLMProcessingError("Knowledge item contains a non-numeric evidence chunk.") from exc
            if index not in chunk_map:
                raise LLMProcessingError(
                    f"Gemini referenced missing transcript chunk {index}. The item was rejected for safety."
                )
            if index not in indices:
                indices.append(index)

        if not indices:
            raise LLMProcessingError("A generated knowledge item has no source evidence.")

        selected = [chunk_map[index] for index in indices]
        start_time = min(float(chunk["start_time"]) for chunk in selected)
        end_time = max(float(chunk["end_time"]) for chunk in selected)
        excerpt = " ".join(str(chunk["text"]).strip() for chunk in selected).strip()
        # Keep DB rows compact while retaining enough source text to verify.
        if len(excerpt) > 720:
            excerpt = excerpt[:717].rstrip() + "..."

        return indices, start_time, end_time, excerpt

    topic_rows = []
    for item in knowledge["topics"]:
        title = str(item.get("title", "")).strip()
        description = str(item.get("description", "")).strip()
        indices, start_time, end_time, excerpt = evidence(item)
        if title and description:
            topic_rows.append(
                (video_db_id, title, description, start_time, end_time,
                 json.dumps(indices), excerpt)
            )

    concept_rows = []
    for item in knowledge["concepts"]:
        name = str(item.get("name", "")).strip()
        definition = str(item.get("definition", "")).strip()
        indices, start_time, end_time, excerpt = evidence(item)
        if name and definition:
            concept_rows.append(
                (video_db_id, name, definition, start_time, end_time,
                 json.dumps(indices), excerpt)
            )

    point_rows = []
    for item in knowledge["key_points"]:
        point = str(item.get("point", "")).strip()
        indices, start_time, end_time, excerpt = evidence(item)
        if point:
            point_rows.append(
                (video_db_id, point, start_time, end_time,
                 json.dumps(indices), excerpt)
            )

    structure_rows = []
    for index, item in enumerate(knowledge["structure"]):
        title = str(item.get("title", "")).strip()
        summary = str(item.get("summary", "")).strip()
        indices, start_time, end_time, excerpt = evidence(item)
        if title and summary:
            structure_rows.append(
                (video_db_id, index, title, summary, start_time, end_time,
                 json.dumps(indices), excerpt)
            )

    if topic_rows:
        cursor.executemany(
            """
            INSERT INTO video_topics
                (video_id, title, description, start_time, end_time,
                 evidence_chunk_indices, evidence_excerpt)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            topic_rows,
        )
    if concept_rows:
        cursor.executemany(
            """
            INSERT INTO video_concepts
                (video_id, name, definition, start_time, end_time,
                 evidence_chunk_indices, evidence_excerpt)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            concept_rows,
        )
    if point_rows:
        cursor.executemany(
            """
            INSERT INTO video_key_points
                (video_id, point, start_time, end_time,
                 evidence_chunk_indices, evidence_excerpt)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            point_rows,
        )
    if structure_rows:
        cursor.executemany(
            """
            INSERT INTO video_structure
                (video_id, section_index, title, summary, start_time, end_time,
                 evidence_chunk_indices, evidence_excerpt)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            structure_rows,
        )


def _hydrate_knowledge_row(row, chunks=None):
    """Decode evidence metadata. Backfill legacy rows from their stored source range."""
    row = dict(row)
    raw = row.get("evidence_chunk_indices")
    try:
        indices = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        indices = []

    # Existing Step-4 rows may have been generated before evidence metadata was
    # added. Their backend-generated start/end range is still enough to recover
    # the exact transcript chunks that overlap that range.
    if (not isinstance(indices, list) or not indices) and chunks:
        try:
            start = float(row.get("start_time") or 0)
            end = float(row.get("end_time") or start)
            recovered = [
                c["chunk_index"] for c in chunks
                if float(c["end_time"]) >= start and float(c["start_time"]) <= end
            ]
            indices = recovered
            if recovered and not row.get("evidence_excerpt"):
                selected = [c for c in chunks if c["chunk_index"] in recovered]
                excerpt = " ".join(str(c["text"]).strip() for c in selected).strip()
                row["evidence_excerpt"] = excerpt[:717].rstrip() + "..." if len(excerpt) > 720 else excerpt
        except (TypeError, ValueError):
            indices = []

    row["evidence_chunk_indices"] = indices if isinstance(indices, list) else []
    row["evidence_excerpt"] = row.get("evidence_excerpt") or ""
    return row


def _load_video_payload(cursor, video_db_id):
    """Load everything the Step 4 UI needs from the database."""
    cursor.execute(
        """
        SELECT id, youtube_video_id, url, status, error_message
        FROM videos
        WHERE id = %s
        """,
        (video_db_id,),
    )
    video = cursor.fetchone()
    if not video:
        return None

    cursor.execute(
        """
        SELECT segment_index, start_time, duration, text
        FROM transcript_segments
        WHERE video_id = %s
        ORDER BY segment_index
        """,
        (video_db_id,),
    )
    transcript_rows = cursor.fetchall()
    transcript = [
        {
            "start": float(row["start_time"]),
            "duration": float(row["duration"] or 0),
            "text": row["text"],
        }
        for row in transcript_rows
    ]

    cursor.execute(
        """
        SELECT chunk_index, start_time, end_time, text, word_count, segment_count
        FROM transcript_chunks
        WHERE video_id = %s
        ORDER BY chunk_index
        """,
        (video_db_id,),
    )
    chunk_rows = cursor.fetchall()
    chunks = [
        {
            "chunk_index": row["chunk_index"],
            "start_time": float(row["start_time"]),
            "end_time": float(row["end_time"]),
            "text": row["text"],
            "word_count": row["word_count"],
            "segment_count": row["segment_count"],
        }
        for row in chunk_rows
    ]

    cursor.execute(
        """
        SELECT title, description, start_time, end_time, evidence_chunk_indices, evidence_excerpt
        FROM video_topics
        WHERE video_id = %s
        ORDER BY start_time
        """,
        (video_db_id,),
    )
    topics = cursor.fetchall()
    topics = [_hydrate_knowledge_row(row, chunks) for row in topics]

    cursor.execute(
        """
        SELECT name, definition, start_time, end_time, evidence_chunk_indices, evidence_excerpt
        FROM video_concepts
        WHERE video_id = %s
        ORDER BY start_time
        """,
        (video_db_id,),
    )
    concepts = cursor.fetchall()
    concepts = [_hydrate_knowledge_row(row, chunks) for row in concepts]

    cursor.execute(
        """
        SELECT point, start_time, end_time, evidence_chunk_indices, evidence_excerpt
        FROM video_key_points
        WHERE video_id = %s
        ORDER BY start_time
        """,
        (video_db_id,),
    )
    key_points = cursor.fetchall()
    key_points = [_hydrate_knowledge_row(row, chunks) for row in key_points]

    cursor.execute(
        """
        SELECT section_index, title, summary, start_time, end_time, evidence_chunk_indices, evidence_excerpt
        FROM video_structure
        WHERE video_id = %s
        ORDER BY section_index
        """,
        (video_db_id,),
    )
    structure = cursor.fetchall()
    structure = [_hydrate_knowledge_row(row, chunks) for row in structure]

    knowledge = {
        "topics": topics,
        "concepts": concepts,
        "key_points": key_points,
        "structure": structure,
    }

    return {
        "video": video,
        "transcript": transcript,
        "chunks": chunks,
        "knowledge": knowledge,
    }


def _knowledge_counts(knowledge):
    return {
        "topic_count": len(knowledge["topics"]),
        "concept_count": len(knowledge["concepts"]),
        "key_point_count": len(knowledge["key_points"]),
        "structure_count": len(knowledge["structure"]),
    }


@video_bp.post("/process")
def process_video():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "")).strip()
    # Optional manual transcript (pasted text or uploaded .txt/.srt/.vtt content).
    manual_text = data.get("transcript_text")
    manual_text = manual_text if isinstance(manual_text, str) and manual_text.strip() else None
    import_info = None
    transcript_source = "youtube"

    connection = None
    cursor = None
    video_id = None
    database_video_id = None

    try:
        video_id = extract_video_id(url)
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Find/create the video record BEFORE contacting YouTube. This lets us
        # cache successful transcript retrieval independently from Gemini.
        cursor.execute(
            "SELECT id, status FROM videos WHERE youtube_video_id = %s",
            (video_id,),
        )
        existing = cursor.fetchone()

        if existing:
            database_video_id = existing["id"]
            status = existing["status"]
        else:
            cursor.execute(
                """
                INSERT INTO videos (youtube_video_id, url, status)
                VALUES (%s, %s, 'processing')
                """,
                (video_id, url),
            )
            database_video_id = cursor.lastrowid
            status = "processing"
            connection.commit()

        # If a previous run completed successfully, don't call YouTube or
        # Gemini again. Return the cached result immediately.
        if status == "ready" and not manual_text:
            payload = _load_video_payload(cursor, database_video_id)
            if payload and payload["transcript"] and payload["chunks"]:
                counts = _knowledge_counts(payload["knowledge"])
                return jsonify(
                    success=True,
                    knowledge_mode="stored",
                    message="Loaded the previously processed video from cache.",
                    video={
                        "id": database_video_id,
                        "youtube_video_id": video_id,
                        "url": url,
                        "status": "ready",
                        "segment_count": len(payload["transcript"]),
                        "chunk_count": len(payload["chunks"]),
                        **counts,
                    },
                    transcript=payload["transcript"],
                    chunks=payload["chunks"],
                    knowledge=payload["knowledge"],
                    cached=True,
                )

        # Reuse transcript/chunks if a previous run already fetched them but
        # failed later (normally during Gemini extraction). This prevents a
        # Gemini retry from hitting YouTube again.
        payload = _load_video_payload(cursor, database_video_id)
        segments = payload["transcript"] if payload else []
        chunks = payload["chunks"] if payload else []

        if segments and chunks and not manual_text:
            print(
                f"[INX] Reusing cached transcript for {video_id}: "
                f"{len(segments)} segments -> {len(chunks)} chunks."
            )
        else:
            if manual_text:
                print(f"[INX] Importing manual transcript for {video_id}...")
                try:
                    segments, import_info = parse_manual_transcript(manual_text)
                except TranscriptImportError as import_exc:
                    raise YouTubeProcessingError(str(import_exc)) from import_exc
                transcript_source = "manual"
            else:
                print(f"[INX] Fetching fresh transcript for {video_id}...")
                segments = get_transcript(video_id)
            chunks = build_chunks(segments)

            if not chunks:
                raise YouTubeProcessingError(
                    "The transcript was retrieved but could not be converted "
                    "into usable knowledge chunks."
                )

            # Replace only transcript/chunk data. Commit it BEFORE Gemini so
            # the successful YouTube retrieval is durable even if Gemini fails.
            cursor.execute(
                """
                UPDATE videos
                SET url = %s, status = 'processing', error_message = NULL
                WHERE id = %s
                """,
                (url, database_video_id),
            )
            cursor.execute(
                "DELETE FROM transcript_chunks WHERE video_id = %s",
                (database_video_id,),
            )
            cursor.execute(
                "DELETE FROM transcript_segments WHERE video_id = %s",
                (database_video_id,),
            )

            segment_rows = [
                (
                    database_video_id,
                    index,
                    segment["start"],
                    segment["duration"],
                    segment["text"],
                )
                for index, segment in enumerate(segments)
            ]
            cursor.executemany(
                """
                INSERT INTO transcript_segments
                    (video_id, segment_index, start_time, duration, text)
                VALUES (%s, %s, %s, %s, %s)
                """,
                segment_rows,
            )

            chunk_rows = [
                (
                    database_video_id,
                    chunk["chunk_index"],
                    chunk["start_time"],
                    chunk["end_time"],
                    chunk["text"],
                    chunk["word_count"],
                    chunk["segment_count"],
                )
                for chunk in chunks
            ]
            cursor.executemany(
                """
                INSERT INTO transcript_chunks
                    (
                        video_id, chunk_index, start_time, end_time,
                        text, word_count, segment_count
                    )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                chunk_rows,
            )
            delete_index(database_video_id)
            cursor.execute("DELETE FROM embedding_indexes WHERE video_id = %s", (database_video_id,))
            connection.commit()
            print(
                f"[INX] Transcript cached: {len(segments)} segments -> "
                f"{len(chunks)} chunks."
            )

        # Prefer Gemini's structured extraction, but keep transcript learning
        # usable when the API key/quota/provider is unavailable. The fallback
        # is explicitly labeled and only selects transcript sentences/terms.
        knowledge_mode = "gemini"
        try:
            knowledge = extract_knowledge(chunks)
        except LLMProcessingError as llm_exc:
            print(f"[INX] Gemini knowledge extraction unavailable; using extractive fallback: {llm_exc}")
            knowledge = extract_knowledge_extractive(chunks)
            knowledge_mode = "extractive_fallback"
        _save_knowledge(cursor, database_video_id, knowledge, chunks)

        cursor.execute(
            """
            UPDATE videos
            SET url = %s, status = 'ready', error_message = NULL
            WHERE id = %s
            """,
            (url, database_video_id),
        )
        connection.commit()

        counts = _knowledge_counts(knowledge)
        return jsonify(
            success=True,
            message=("Transcript processed; knowledge extracted with Gemini." if knowledge_mode == "gemini"
                     else "Transcript processed. Gemini was unavailable, so a clearly labeled extractive knowledge map was created."),
            knowledge_mode=knowledge_mode,
            transcript_source=transcript_source,
            import_info=import_info,
            video={
                "id": database_video_id,
                "youtube_video_id": video_id,
                "url": url,
                "status": "ready",
                "segment_count": len(segments),
                "chunk_count": len(chunks),
                **counts,
            },
            transcript=segments,
            chunks=chunks,
            knowledge=knowledge,
            cached=False,
        )

    except (YouTubeProcessingError, LLMProcessingError) as exc:
        if connection:
            connection.rollback()

        # Preserve any already-cached transcript/chunks. Only update the
        # status/error field so a later retry can continue from the failed step.
        if database_video_id and connection:
            try:
                cursor.execute(
                    """
                    UPDATE videos
                    SET url = %s, status = 'failed', error_message = %s
                    WHERE id = %s
                    """,
                    (url, str(exc), database_video_id),
                )
                connection.commit()
            except Exception as db_exc:
                print(f"[INX] Could not save failed state: {db_exc}")
        elif video_id:
            try:
                if connection is None:
                    connection = get_db_connection()
                if cursor is None:
                    cursor = connection.cursor(dictionary=True)
                cursor.execute(
                    """
                    INSERT INTO videos
                        (youtube_video_id, url, status, error_message)
                    VALUES (%s, %s, 'failed', %s)
                    ON DUPLICATE KEY UPDATE
                        url = VALUES(url),
                        status = 'failed',
                        error_message = VALUES(error_message)
                    """,
                    (video_id, url, str(exc)),
                )
                connection.commit()
            except Exception as db_exc:
                print(f"[INX] Could not save failed state: {db_exc}")

        if isinstance(exc, LLMProcessingError):
            code = "LLM_ERROR"
        elif isinstance(exc, YouTubeBlockedError):
            code = "TRANSCRIPT_BLOCKED"
        else:
            code = "TRANSCRIPT_ERROR"
        return jsonify(
            success=False,
            error=str(exc),
            code=code,
            manual_import_available=code in ("TRANSCRIPT_BLOCKED", "TRANSCRIPT_ERROR"),
        ), 422

    except Exception as exc:
        if connection:
            connection.rollback()
        print(f"[INX] Processing error: {type(exc).__name__}: {exc}")
        return jsonify(
            success=False,
            error="The video could not be processed because of a server or database error.",
            code="PROCESSING_ERROR",
        ), 500

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@video_bp.get("/<youtube_video_id>/index")
def get_embedding_index_status(youtube_video_id):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id FROM videos WHERE youtube_video_id = %s",
            (youtube_video_id,),
        )
        video = cursor.fetchone()
        if not video:
            return jsonify(success=False, error="Video not found."), 404

        status = get_index_status(video["id"])
        cursor.execute(
            """
            SELECT model_name, dimension, chunk_count, created_at, updated_at
            FROM embedding_indexes
            WHERE video_id = %s
            """,
            (video["id"],),
        )
        db_row = cursor.fetchone()
        if db_row and status["indexed"]:
            status.update({
                "model": db_row["model_name"],
                "dimension": db_row["dimension"],
                "chunk_count": db_row["chunk_count"],
                "created_at": db_row["created_at"].isoformat() if db_row["created_at"] else None,
            })
        return jsonify(success=True, index=status)
    except Exception as exc:
        print(f"[INX] Index status error: {type(exc).__name__}: {exc}")
        return jsonify(success=False, error="Could not retrieve semantic index status."), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@video_bp.post("/<youtube_video_id>/index")
def build_embedding_index(youtube_video_id):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, status FROM videos WHERE youtube_video_id = %s",
            (youtube_video_id,),
        )
        video = cursor.fetchone()
        if not video:
            return jsonify(success=False, error="Video not found."), 404

        cursor.execute(
            """
            SELECT chunk_index, start_time, end_time, text, word_count, segment_count
            FROM transcript_chunks
            WHERE video_id = %s
            ORDER BY chunk_index
            """,
            (video["id"],),
        )
        chunks = cursor.fetchall()
        if not chunks:
            return jsonify(success=False, error="Process the video before building its semantic index."), 422

        result = build_index(video["id"], chunks)
        cursor.execute(
            """
            INSERT INTO embedding_indexes
                (video_id, model_name, dimension, chunk_count, index_version)
            VALUES (%s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
                model_name = VALUES(model_name),
                dimension = VALUES(dimension),
                chunk_count = VALUES(chunk_count),
                index_version = index_version + 1
            """,
            (video["id"], result["model"], result["dimension"], result["chunk_count"]),
        )
        connection.commit()
        return jsonify(success=True, message="Semantic index built successfully.", index=result)
    except EmbeddingProcessingError as exc:
        if connection:
            connection.rollback()
        return jsonify(success=False, error=str(exc), code="EMBEDDING_ERROR"), 422
    except Exception as exc:
        if connection:
            connection.rollback()
        print(f"[INX] Index build error: {type(exc).__name__}: {exc}")
        return jsonify(success=False, error="Could not build the semantic index."), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@video_bp.get("/<youtube_video_id>/search")
def semantic_search(youtube_video_id):
    connection = None
    cursor = None
    try:
        query = str(request.args.get("q", "")).strip()
        top_k = int(request.args.get("top_k", 5))
        top_k = max(1, min(top_k, 10))

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id FROM videos WHERE youtube_video_id = %s",
            (youtube_video_id,),
        )
        video = cursor.fetchone()
        if not video:
            return jsonify(success=False, error="Video not found."), 404

        cursor.execute(
            """
            SELECT chunk_index, start_time, end_time, text, word_count, segment_count
            FROM transcript_chunks
            WHERE video_id = %s
            ORDER BY chunk_index
            """,
            (video["id"],),
        )
        chunks = cursor.fetchall()
        results = hybrid_search(video["id"], query, chunks, top_k=top_k)
        return jsonify(success=True, query=query, results=results)
    except ValueError:
        return jsonify(success=False, error="top_k must be a number."), 400
    except EmbeddingProcessingError as exc:
        return jsonify(success=False, error=str(exc), code="EMBEDDING_ERROR"), 422
    except Exception as exc:
        print(f"[INX] Semantic search error: {type(exc).__name__}: {exc}")
        return jsonify(success=False, error="Could not perform semantic search."), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@video_bp.post("/<youtube_video_id>/ask")
def ask_video_question(youtube_video_id):
    connection = None
    cursor = None
    try:
        data = request.get_json(silent=True) or {}
        question = str(data.get("question", "")).strip()
        if not question:
            return jsonify(success=False, error="Question cannot be empty."), 400

        top_k = int(data.get("top_k", 6))
        top_k = max(3, min(top_k, 8))

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id FROM videos WHERE youtube_video_id = %s", (youtube_video_id,))
        video = cursor.fetchone()
        if not video:
            return jsonify(success=False, error="Video not found."), 404

        cursor.execute(
            """
            SELECT chunk_index, start_time, end_time, text, word_count, segment_count
            FROM transcript_chunks
            WHERE video_id = %s
            ORDER BY chunk_index
            """,
            (video["id"],),
        )
        chunks = cursor.fetchall()
        retrieved = hybrid_search(video["id"], question, chunks, top_k=top_k)
        result = answer_question(question, retrieved)

        return jsonify(success=True, question=question, retrieval=retrieved, **result)
    except ValueError:
        return jsonify(success=False, error="top_k must be a number."), 400
    except (EmbeddingProcessingError, LLMProcessingError) as exc:
        return jsonify(success=False, error=str(exc), code="QA_ERROR"), 422
    except Exception as exc:
        print(f"[INX] Q&A error: {type(exc).__name__}: {exc}")
        return jsonify(success=False, error="Could not answer the question."), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@video_bp.get("/<youtube_video_id>/knowledge")
def get_knowledge(youtube_video_id):
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id, youtube_video_id, url, status, error_message
            FROM videos
            WHERE youtube_video_id = %s
            """,
            (youtube_video_id,),
        )
        video = cursor.fetchone()

        if not video:
            return jsonify(success=False, error="Video not found."), 404

        payload = _load_video_payload(cursor, video["id"])
        return jsonify(
            success=True,
            video=video,
            knowledge=payload["knowledge"],
        )

    except Exception as exc:
        print(f"[INX] Knowledge retrieval error: {type(exc).__name__}: {exc}")
        return jsonify(success=False, error="Could not retrieve extracted knowledge."), 500

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@video_bp.get("/<youtube_video_id>/explorer")
def get_explorer_payload(youtube_video_id):
    """Return the verified transcript, chunks, and knowledge for the explorer UI."""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, youtube_video_id, url, status, error_message FROM videos WHERE youtube_video_id = %s",
            (youtube_video_id,),
        )
        video = cursor.fetchone()
        if not video:
            return jsonify(success=False, error="Video not found."), 404
        payload = _load_video_payload(cursor, video["id"])
        return jsonify(
            success=True,
            video=payload["video"],
            transcript=payload["transcript"],
            chunks=payload["chunks"],
            knowledge=payload["knowledge"],
        )
    except Exception as exc:
        print(f"[INX] Explorer retrieval error: {type(exc).__name__}: {exc}")
        return jsonify(success=False, error="Could not load the video explorer."), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
