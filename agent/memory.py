"""
Persistent memory system for Dennis.

Two-layer storage:
1. ChromaDB  – semantic vector search over past conversations & knowledge
2. SQLite    – structured storage for goals, facts, and episodic logs
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions

import config


# ── Embedding function (local, no API cost) ────────────────────────────────
_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)


class Memory:
    def __init__(self):
        # Vector store
        self._chroma = chromadb.PersistentClient(path=config.CHROMA_DB_PATH)
        self._conv_col = self._chroma.get_or_create_collection(
            "conversations", embedding_function=_ef
        )
        self._know_col = self._chroma.get_or_create_collection(
            "knowledge", embedding_function=_ef
        )

        # Structured store – WAL mode for better concurrency
        self._db = sqlite3.connect(config.MEMORY_DB_PATH, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    # ── Schema ─────────────────────────────────────────────────────────────
    def _init_schema(self):
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                key TEXT NOT NULL UNIQUE,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS goals (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                priority INTEGER NOT NULL DEFAULT 5,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                next_check TEXT,
                progress_notes TEXT DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS goal_tasks (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL REFERENCES goals(id),
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                result TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                summary TEXT NOT NULL,
                full_content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        self._db.commit()

    # ── Conversation memory ────────────────────────────────────────────────
    def save_conversation_turn(self, role: str, content: str, metadata: dict = None):
        """Store a conversation turn in the vector DB."""
        doc_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        meta = {"role": role, "timestamp": ts, **(metadata or {})}
        self._conv_col.add(documents=[content], metadatas=[meta], ids=[doc_id])
        return doc_id

    def recall_relevant(self, query: str, n: int = None) -> list[dict]:
        """Semantic search over past conversations."""
        n = n or config.MEMORY_MAX_RESULTS
        count = self._conv_col.count()
        if count == 0:
            return []
        results = self._conv_col.query(query_texts=[query], n_results=min(n, count))
        if not results["documents"][0]:
            return []
        return [
            {"content": doc, "metadata": meta}
            for doc, meta in zip(results["documents"][0], results["metadatas"][0])
        ]

    # ── Knowledge base ─────────────────────────────────────────────────────
    def add_knowledge(self, content: str, source: str, tags: list[str] = None):
        """Add a piece of knowledge (research finding, learned fact, etc.)."""
        doc_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        meta = {"source": source, "tags": json.dumps(tags or []), "timestamp": ts}
        self._know_col.add(documents=[content], metadatas=[meta], ids=[doc_id])
        # Also log as episode
        self._db.execute(
            "INSERT INTO episodes VALUES (?,?,?,?,?)",
            (doc_id, source, content[:200], content, ts),
        )
        self._db.commit()
        return doc_id

    def search_knowledge(self, query: str, n: int = 5) -> list[dict]:
        """Search the knowledge base semantically."""
        count = self._know_col.count()
        if count == 0:
            return []
        results = self._know_col.query(query_texts=[query], n_results=min(n, count))
        return [
            {"content": doc, "metadata": meta}
            for doc, meta in zip(results["documents"][0], results["metadatas"][0])
        ]

    # ── Facts (key-value store) ────────────────────────────────────────────
    def set_fact(self, category: str, key: str, value: str):
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            """INSERT INTO facts (category, key, value, created_at, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (category, key, value, ts, ts),
        )
        self._db.commit()

    def get_fact(self, key: str) -> Optional[str]:
        row = self._db.execute("SELECT value FROM facts WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def get_facts_by_category(self, category: str) -> dict:
        rows = self._db.execute(
            "SELECT key, value FROM facts WHERE category=?", (category,)
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    def delete_fact(self, category: str, key: str):
        self._db.execute("DELETE FROM facts WHERE category=? AND key=?", (category, key))
        self._db.commit()

    # ── Behavior config (stored in facts under category='behavior') ────────
    def set_behavior_config(self, key: str, value: str):
        """Persist a behavioral override (survives restarts)."""
        self.set_fact("behavior", key, value)

    def get_behavior_config(self) -> dict:
        """Return all behavioral overrides as a dict."""
        return self.get_facts_by_category("behavior")

    # ── Goals ──────────────────────────────────────────────────────────────
    def create_goal(self, title: str, description: str, priority: int = 5) -> str:
        goal_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            """INSERT INTO goals (id,title,description,priority,created_at,updated_at)
               VALUES (?,?,?,?,?,?)""",
            (goal_id, title, description, priority, ts, ts),
        )
        self._db.commit()
        return goal_id

    def get_active_goals(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM goals WHERE status='active' ORDER BY priority DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_goal_progress(self, goal_id: str, note: str):
        row = self._db.execute(
            "SELECT progress_notes FROM goals WHERE id=?", (goal_id,)
        ).fetchone()
        if not row:
            return
        notes = json.loads(row["progress_notes"])
        notes.append({"note": note, "timestamp": datetime.now(timezone.utc).isoformat()})
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "UPDATE goals SET progress_notes=?, updated_at=? WHERE id=?",
            (json.dumps(notes), ts, goal_id),
        )
        self._db.commit()

    def complete_goal(self, goal_id: str):
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "UPDATE goals SET status='completed', updated_at=? WHERE id=?", (ts, goal_id)
        )
        self._db.commit()

    def add_goal_task(self, goal_id: str, description: str) -> str:
        task_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "INSERT INTO goal_tasks VALUES (?,?,?,?,?,?,?)",
            (task_id, goal_id, description, "pending", None, ts, None),
        )
        self._db.commit()
        return task_id

    def complete_goal_task(self, task_id: str, result: str):
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "UPDATE goal_tasks SET status='done', result=?, completed_at=? WHERE id=?",
            (result, ts, task_id),
        )
        self._db.commit()

    def delete_goal_tasks(self, goal_id: str, status: str = "pending"):
        """Delete all tasks for a goal with the given status (e.g. to clear a stuck queue)."""
        self._db.execute(
            "DELETE FROM goal_tasks WHERE goal_id=? AND status=?", (goal_id, status)
        )
        self._db.commit()

    def get_goal_tasks(self, goal_id: str, status: str = None) -> list[dict]:
        if status:
            rows = self._db.execute(
                "SELECT * FROM goal_tasks WHERE goal_id=? AND status=?", (goal_id, status)
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM goal_tasks WHERE goal_id=?", (goal_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_task_count_today(self, goal_id: str) -> int:
        """Return number of tasks created for this goal in the last 24 hours (loop detection)."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        row = self._db.execute(
            "SELECT COUNT(*) as n FROM goal_tasks WHERE goal_id=? AND created_at > ?",
            (goal_id, cutoff),
        ).fetchone()
        return row["n"] if row else 0
