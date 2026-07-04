from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from core.research import search_entries as rank_search_entries
from core.research import words

DEFAULT_DB_FILE = "transcripts_store.sqlite3"
UNKNOWN_CHANNEL = "Unknown Channel"


class SQLiteTranscriptStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_FILE):
        self.db_path = Path(db_path)
        if self.db_path.parent != Path("."):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.fts_enabled = self._initialize_schema()
        if self.fts_enabled:
            self.rebuild_fts()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize_schema(self) -> bool:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    saved_at TEXT NOT NULL DEFAULT '',
                    transcript TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (channel_id) REFERENCES channels(id)
                );

                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT NOT NULL,
                    segment_index INTEGER NOT NULL,
                    text TEXT NOT NULL DEFAULT '',
                    start REAL NOT NULL DEFAULT 0,
                    duration REAL NOT NULL DEFAULT 0,
                    FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE,
                    UNIQUE (video_id, segment_index)
                );

                CREATE INDEX IF NOT EXISTS idx_videos_channel_id
                    ON videos(channel_id);

                CREATE INDEX IF NOT EXISTS idx_segments_video_id_index
                    ON segments(video_id, segment_index);

                CREATE TABLE IF NOT EXISTS fetch_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT,
                    status TEXT
                );
                """
            )

        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS video_search_fts
                    USING fts5(
                        video_id UNINDEXED,
                        title,
                        channel,
                        transcript
                    )
                    """
                )
        except sqlite3.OperationalError as exc:
            if "fts5" in str(exc).lower() or "no such module" in str(exc).lower():
                return False
            raise

        return True

    def add_entry(self, entry: dict[str, Any]) -> None:
        video_id = str(entry["video_id"])
        title = str(entry.get("title") or "")
        channel = str(entry.get("channel") or UNKNOWN_CHANNEL)
        saved_at = str(entry.get("saved_at") or "")
        transcript = str(entry.get("transcript") or "")
        segments = list(entry.get("segments") or [])

        with self._connection() as connection:
            channel_id = self._upsert_channel(connection, channel)
            sort_order = self._next_sort_order(connection)

            connection.execute(
                """
                INSERT INTO videos (
                    video_id, channel_id, title, saved_at, transcript, sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    title = excluded.title,
                    saved_at = excluded.saved_at,
                    transcript = excluded.transcript,
                    sort_order = excluded.sort_order,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (video_id, channel_id, title, saved_at, transcript, sort_order),
            )

            connection.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))
            connection.executemany(
                """
                INSERT INTO segments (
                    video_id, segment_index, text, start, duration
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        video_id,
                        index,
                        str(segment.get("text") or ""),
                        _as_float(segment.get("start")),
                        _as_float(segment.get("duration")),
                    )
                    for index, segment in enumerate(segments)
                    if isinstance(segment, dict)
                ],
            )
            self._refresh_fts_entry(connection, video_id, title, channel, transcript)

    def delete_entry(self, video_id: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM videos WHERE video_id = ?", (video_id,))
            self._delete_fts_entry(connection, video_id)

    def all_entries(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            video_rows = connection.execute(
                """
                SELECT
                    videos.video_id,
                    videos.title,
                    channels.name AS channel,
                    videos.saved_at,
                    videos.transcript
                FROM videos
                JOIN channels ON channels.id = videos.channel_id
                ORDER BY videos.sort_order ASC, videos.created_at ASC
                """
            ).fetchall()

            return self._entries_from_rows(connection, video_rows)

    def search_entries(
        self,
        query: str,
        channel: str | None = None,
        limit: int = 50,
        matches_per_entry: int = 4,
        sort: str = "relevance",
    ) -> list[dict[str, Any]]:
        fts_query = _fts_query(query)
        if not fts_query:
            return []

        if not self.fts_enabled:
            return rank_search_entries(
                self.all_entries(),
                query=query,
                channel=channel,
                limit=limit,
                matches_per_entry=matches_per_entry,
                sort=sort,
            )

        channel_filter = (channel or "").strip().lower()
        candidate_limit = max(100, min(1000, limit * 20))

        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT
                        videos.video_id,
                        videos.title,
                        channels.name AS channel,
                        videos.saved_at,
                        videos.transcript
                    FROM video_search_fts
                    JOIN videos ON videos.video_id = video_search_fts.video_id
                    JOIN channels ON channels.id = videos.channel_id
                    WHERE video_search_fts MATCH ?
                        AND (? = '' OR lower(channels.name) = ?)
                    ORDER BY bm25(video_search_fts), videos.saved_at DESC
                    LIMIT ?
                    """,
                    (fts_query, channel_filter, channel_filter, candidate_limit),
                ).fetchall()

                candidates = self._entries_from_rows(connection, rows)
        except sqlite3.OperationalError:
            candidates = self.all_entries()

        return rank_search_entries(
            candidates,
            query=query,
            channel=channel,
            limit=limit,
            matches_per_entry=matches_per_entry,
            sort=sort,
        )

    def export_json(self, export_path: str | Path) -> Path:
        return export_entries_to_json(self.all_entries(), export_path)

    def import_entries(self, entries: Iterable[dict[str, Any]]) -> None:
        for entry in entries:
            self.add_entry(entry)

    def rebuild_fts(self) -> None:
        if not self.fts_enabled:
            return

        with self._connection() as connection:
            connection.execute("DELETE FROM video_search_fts")
            connection.execute(
                """
                INSERT INTO video_search_fts (video_id, title, channel, transcript)
                SELECT videos.video_id, videos.title, channels.name, videos.transcript
                FROM videos
                JOIN channels ON channels.id = videos.channel_id
                """
            )

    def _entries_from_rows(
        self,
        connection: sqlite3.Connection,
        video_rows: Iterable[sqlite3.Row],
    ) -> list[dict[str, Any]]:
        rows = list(video_rows)
        if not rows:
            return []

        video_ids = [row["video_id"] for row in rows]
        placeholders = ", ".join("?" for _ in video_ids)
        segment_rows = connection.execute(
            f"""
            SELECT video_id, text, start, duration
            FROM segments
            WHERE video_id IN ({placeholders})
            ORDER BY video_id ASC, segment_index ASC
            """,
            video_ids,
        ).fetchall()

        segments_by_video: dict[str, list[dict[str, Any]]] = {}
        for row in segment_rows:
            segments_by_video.setdefault(row["video_id"], []).append(
                {
                    "text": row["text"],
                    "start": row["start"],
                    "duration": row["duration"],
                }
            )

        return [
            {
                "video_id": row["video_id"],
                "title": row["title"],
                "channel": row["channel"],
                "saved_at": row["saved_at"],
                "transcript": row["transcript"],
                "segments": segments_by_video.get(row["video_id"], []),
            }
            for row in rows
        ]

    def _upsert_channel(self, connection: sqlite3.Connection, name: str) -> int:
        connection.execute(
            "INSERT OR IGNORE INTO channels (name) VALUES (?)",
            (name or UNKNOWN_CHANNEL,),
        )
        row = connection.execute(
            "SELECT id FROM channels WHERE name = ?",
            (name or UNKNOWN_CHANNEL,),
        ).fetchone()
        return int(row["id"])

    def _next_sort_order(self, connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM videos"
        ).fetchone()
        return int(row["next_order"])

    def _refresh_fts_entry(
        self,
        connection: sqlite3.Connection,
        video_id: str,
        title: str,
        channel: str,
        transcript: str,
    ) -> None:
        if not self.fts_enabled:
            return

        self._delete_fts_entry(connection, video_id)
        connection.execute(
            """
            INSERT INTO video_search_fts (video_id, title, channel, transcript)
            VALUES (?, ?, ?, ?)
            """,
            (video_id, title, channel, transcript),
        )

    def _delete_fts_entry(self, connection: sqlite3.Connection, video_id: str) -> None:
        if not self.fts_enabled:
            return

        connection.execute(
            "DELETE FROM video_search_fts WHERE video_id = ?",
            (video_id,),
        )


def migrate_json_to_sqlite(json_path: str | Path, db_path: str | Path) -> SQLiteTranscriptStore:
    with Path(json_path).open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("Expected transcript JSON data to be a list of entries")

    store = SQLiteTranscriptStore(db_path)
    with store._connection() as connection:
        if store.fts_enabled:
            connection.execute("DELETE FROM video_search_fts")
        connection.execute("DELETE FROM segments")
        connection.execute("DELETE FROM videos")
        connection.execute("DELETE FROM channels")
    store.import_entries(entry for entry in data if isinstance(entry, dict))
    return store


def export_entries_to_json(entries: Iterable[dict[str, Any]], export_path: str | Path) -> Path:
    path = Path(export_path)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(list(entries), file, indent=2, ensure_ascii=False)

    return path


def _fts_query(query: str) -> str:
    terms = words(query)
    return " ".join(f"{term}*" for term in terms if len(term) > 1)


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
