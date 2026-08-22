"""Vector search backed by SQLite instead of a JSON file.

The JSON index holds every embedding as a list of numbers, so answering one query
means parsing the whole file and scoring every chunk in Python. At a few thousand
chunks that is already seconds per search and hundreds of megabytes of memory.

sqlite-vec keeps the vectors in a database and does the nearest-neighbour search
itself, which is what a vector database is for. It is an extension to the SQLite
that is already here rather than another service to run, so nothing new has to be
installed, started, or kept alive.

The index is derived data. If this file is missing or unreadable the archive still
works; rebuilding it costs only the time to re-embed.
"""

from __future__ import annotations

import re
import sqlite3
import struct
from pathlib import Path
from typing import Any, Iterable, Sequence

DEFAULT_VECTOR_DB_FILE = "semantic_index.sqlite3"
BUSY_TIMEOUT_SECONDS = 15.0


def default_vector_db_path() -> Path:
    """Where the vector index lives.

    Deliberately not under the bind-mounted data directory. A nearest-neighbour
    search reads tens of megabytes of vectors, and Docker Desktop's Windows file
    sharing makes that two orders of magnitude slower: the same query measured
    1039ms through the mount and 7ms on container-local storage. The index is
    derived data, so keeping it in a volume costs nothing but a rebuild if lost,
    while the transcripts stay on the host where they can be backed up.
    """
    import os

    configured = os.getenv("YT_TRANSCRIPTS_VECTOR_DB", "").strip()
    if configured:
        return Path(configured).expanduser()

    vector_dir = os.getenv("YT_TRANSCRIPTS_VECTOR_DIR", "").strip()
    if vector_dir:
        return Path(vector_dir) / DEFAULT_VECTOR_DB_FILE

    data_dir = os.getenv("YT_TRANSCRIPTS_DATA_DIR", "").strip() or "."
    return Path(data_dir) / DEFAULT_VECTOR_DB_FILE


class VectorStoreUnavailable(RuntimeError):
    """Raised when sqlite-vec cannot be loaded, so callers can fall back."""


def extension_available() -> bool:
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        return False
    return True


def _connect(db_path: str | Path) -> sqlite3.Connection:
    try:
        import sqlite_vec
    except ImportError as exc:
        raise VectorStoreUnavailable("sqlite-vec is not installed") from exc

    connection = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_SECONDS)
    connection.row_factory = sqlite3.Row
    try:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
    except (AttributeError, sqlite3.OperationalError) as exc:
        connection.close()
        raise VectorStoreUnavailable(f"Could not load sqlite-vec: {exc}") from exc
    return connection


def _pack(vector: Sequence[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *(float(v) for v in vector))


def stored_dimensions(db_path: str | Path) -> int:
    """The width the index was built with, or 0 if there is no usable index.

    Needed because changing embedding model changes the vector width, and a query
    of the wrong width must fall back rather than raise from inside SQLite.
    """
    path = Path(db_path)
    if not path.exists():
        return 0
    try:
        with _connect(path) as connection:
            row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'chunk_vectors'"
            ).fetchone()
    except (VectorStoreUnavailable, sqlite3.Error):
        return 0

    if not row or not row["sql"]:
        return 0
    match = re.search(r"float\[(\d+)\]", row["sql"])
    return int(match.group(1)) if match else 0


class SQLiteVectorStore:
    """Chunk embeddings and their metadata, searchable by meaning."""

    def __init__(self, db_path: str | Path, dimensions: int):
        self.db_path = Path(db_path)
        self.dimensions = int(dimensions)
        if self.db_path.parent != Path("."):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        with _connect(self.db_path) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors "
                f"USING vec0(embedding float[{self.dimensions}])"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chunk_metadata (
                    rowid INTEGER PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    channel TEXT NOT NULL DEFAULT '',
                    start REAL NOT NULL DEFAULT 0,
                    end REAL NOT NULL DEFAULT 0,
                    text TEXT NOT NULL DEFAULT '',
                    chunk_index INTEGER NOT NULL DEFAULT 0,
                    embedding_model TEXT NOT NULL DEFAULT '',
                    transcript_hash TEXT NOT NULL DEFAULT '',
                    indexed_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunk_metadata_video ON chunk_metadata(video_id)"
            )

    def replace_all(self, items: Iterable[dict[str, Any]]) -> int:
        """Swap in a freshly built index. The old contents go entirely."""
        written = 0
        with _connect(self.db_path) as connection:
            connection.execute("DELETE FROM chunk_vectors")
            connection.execute("DELETE FROM chunk_metadata")

            for rowid, item in enumerate(items, start=1):
                vector = item.get("vector")
                if not vector or len(vector) != self.dimensions:
                    continue
                connection.execute(
                    "INSERT INTO chunk_vectors(rowid, embedding) VALUES (?, ?)",
                    (rowid, _pack(vector)),
                )
                connection.execute(
                    """
                    INSERT INTO chunk_metadata (
                        rowid, video_id, title, channel, start, end, text,
                        chunk_index, embedding_model, transcript_hash, indexed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rowid,
                        str(item.get("video_id") or ""),
                        str(item.get("title") or ""),
                        str(item.get("channel") or ""),
                        float(item.get("start") or 0),
                        float(item.get("end") or 0),
                        str(item.get("text") or ""),
                        int(item.get("chunk_index") or 0),
                        str(item.get("embedding_model") or ""),
                        str(item.get("transcript_hash") or ""),
                        str(item.get("indexed_at") or ""),
                    ),
                )
                written += 1
        return written

    def search(self, vector: Sequence[float], limit: int = 20) -> list[dict[str, Any]]:
        """Chunks closest in meaning to the query, nearest first."""
        if not vector or len(vector) != self.dimensions:
            return []

        bounded = max(1, min(int(limit), 500))
        with _connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    m.video_id, m.title, m.channel, m.start, m.end, m.text,
                    m.chunk_index, m.embedding_model, v.distance
                FROM chunk_vectors AS v
                JOIN chunk_metadata AS m ON m.rowid = v.rowid
                WHERE v.embedding MATCH ? AND k = ?
                ORDER BY v.distance
                """,
                (_pack(vector), bounded),
            ).fetchall()

        results = []
        for row in rows:
            distance = float(row["distance"])
            results.append({
                "video_id": row["video_id"],
                "title": row["title"],
                "channel": row["channel"],
                "start": row["start"],
                "end": row["end"],
                "text": row["text"],
                "chunk_index": row["chunk_index"],
                "embedding_model": row["embedding_model"],
                # These vectors are normalised, so L2 distance maps back to cosine
                # similarity. Callers already speak in scores where higher is better.
                "score": max(0.0, 1.0 - (distance * distance) / 2.0),
                "distance": distance,
            })
        return results

    def stats(self) -> dict[str, Any]:
        try:
            with _connect(self.db_path) as connection:
                row = connection.execute(
                    "SELECT COUNT(*) AS chunks, COUNT(DISTINCT video_id) AS videos FROM chunk_metadata"
                ).fetchone()
                model_row = connection.execute(
                    "SELECT embedding_model FROM chunk_metadata LIMIT 1"
                ).fetchone()
        except (VectorStoreUnavailable, sqlite3.Error):
            return {"available": False, "chunk_count": 0, "video_count": 0}

        size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "available": True,
            "path": str(self.db_path),
            "chunk_count": int(row["chunks"] or 0),
            "video_count": int(row["videos"] or 0),
            "embedding_model": model_row["embedding_model"] if model_row else "",
            # What the table was actually built with, which is not necessarily what
            # this object was constructed with.
            "dimensions": stored_dimensions(self.db_path) or self.dimensions,
            "size_bytes": size,
        }

    def clear(self) -> None:
        with _connect(self.db_path) as connection:
            connection.execute("DELETE FROM chunk_vectors")
            connection.execute("DELETE FROM chunk_metadata")


def migrate_json_index(
    index: dict[str, Any],
    db_path: str | Path,
) -> dict[str, Any]:
    """Move an existing JSON index into SQLite, keeping the JSON as a backup."""
    items = [item for item in (index.get("items") or []) if isinstance(item, dict)]
    if not items:
        return {"migrated": 0, "dimensions": 0}

    dimensions = len(items[0].get("vector") or [])
    if not dimensions:
        return {"migrated": 0, "dimensions": 0}

    store = SQLiteVectorStore(db_path, dimensions)
    migrated = store.replace_all(items)
    return {"migrated": migrated, "dimensions": dimensions, **store.stats()}
