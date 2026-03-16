"""
Persistent memory system for Dennis.

Two-layer storage:
1. ChromaDB  – semantic vector search over past conversations & knowledge
2. SQLite    – structured storage for goals, facts, episodic logs, drafts,
               notification queue, email triage, and API call tracking
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
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
        self._chroma = chromadb.PersistentClient(path=config.CHROMA_DB_PATH)
        self._conv_col = self._chroma.get_or_create_collection(
            "conversations", embedding_function=_ef
        )
        self._know_col = self._chroma.get_or_create_collection(
            "knowledge", embedding_function=_ef
        )

        self._db = sqlite3.connect(config.MEMORY_DB_PATH, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    # ── Schema ─────────────────────────────────────────────────────────────
    def _init_schema(self):
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS api_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                model TEXT NOT NULL,
                call_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_api_calls_date ON api_calls(date);

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
                progress_notes TEXT DEFAULT '[]',
                schedule TEXT DEFAULT NULL,
                last_triggered TEXT DEFAULT NULL,
                last_completion_check TEXT DEFAULT NULL
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

            CREATE TABLE IF NOT EXISTS drafts (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );

            CREATE TABLE IF NOT EXISTS notification_queue (
                id TEXT PRIMARY KEY,
                message TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'system',
                queued_at TEXT NOT NULL,
                deliver_after TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notif_deliver ON notification_queue(deliver_after);

            CREATE TABLE IF NOT EXISTS email_triage (
                message_id TEXT PRIMARY KEY,
                subject TEXT,
                sender TEXT,
                triaged_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS webhook_events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                processed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """)
        self._db.commit()
        # Add new columns to goals if they don't exist (migration for existing DBs)
        for col, typedef in [
            ("schedule", "TEXT DEFAULT NULL"),
            ("last_triggered", "TEXT DEFAULT NULL"),
            ("last_completion_check", "TEXT DEFAULT NULL"),
        ]:
            try:
                self._db.execute(f"ALTER TABLE goals ADD COLUMN {col} {typedef}")
                self._db.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists

    # ── Conversation memory ────────────────────────────────────────────────
    def save_conversation_turn(self, role: str, content: str, metadata: dict = None):
        doc_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        meta = {"role": role, "timestamp": ts, **(metadata or {})}
        self._conv_col.add(documents=[content], metadatas=[meta], ids=[doc_id])
        return doc_id

    def recall_relevant(self, query: str, n: int = None) -> list[dict]:
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
        doc_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        meta = {"source": source, "tags": json.dumps(tags or []), "timestamp": ts}
        self._know_col.add(documents=[content], metadatas=[meta], ids=[doc_id])
        self._db.execute(
            "INSERT INTO episodes VALUES (?,?,?,?,?)",
            (doc_id, source, content[:200], content, ts),
        )
        self._db.commit()
        return doc_id

    def search_knowledge(self, query: str, n: int = 5) -> list[dict]:
        count = self._know_col.count()
        if count == 0:
            return []
        results = self._know_col.query(query_texts=[query], n_results=min(n, count))
        return [
            {"content": doc, "metadata": meta}
            for doc, meta in zip(results["documents"][0], results["metadatas"][0])
        ]

    def get_all_knowledge(self, limit: int = 200) -> list[dict]:
        """Return recent knowledge items (for export)."""
        rows = self._db.execute(
            "SELECT * FROM episodes ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Facts ──────────────────────────────────────────────────────────────
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

    def get_all_facts(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT category, key, value, updated_at FROM facts ORDER BY category, key"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Behavior config ────────────────────────────────────────────────────
    def set_behavior_config(self, key: str, value: str):
        self.set_fact("behavior", key, value)

    def get_behavior_config(self) -> dict:
        return self.get_facts_by_category("behavior")

    # ── Goals ──────────────────────────────────────────────────────────────
    def create_goal(self, title: str, description: str, priority: int = 5,
                    schedule: str = None) -> str:
        goal_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            """INSERT INTO goals (id,title,description,priority,created_at,updated_at,schedule)
               VALUES (?,?,?,?,?,?,?)""",
            (goal_id, title, description, priority, ts, ts, schedule),
        )
        self._db.commit()
        return goal_id

    def get_active_goals(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM goals WHERE status='active' ORDER BY priority DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_completed_goals(self, limit: int = 20) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM goals WHERE status='completed' ORDER BY updated_at DESC LIMIT ?",
            (limit,),
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

    def mark_goal_completion_checked(self, goal_id: str):
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "UPDATE goals SET last_completion_check=? WHERE id=?", (ts, goal_id)
        )
        self._db.commit()

    def update_goal_last_triggered(self, goal_id: str):
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "UPDATE goals SET last_triggered=? WHERE id=?", (ts, goal_id)
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
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        row = self._db.execute(
            "SELECT COUNT(*) as n FROM goal_tasks WHERE goal_id=? AND created_at > ?",
            (goal_id, cutoff),
        ).fetchone()
        return row["n"] if row else 0

    def get_recent_completed_tasks(self, days: int = 7) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self._db.execute(
            """SELECT gt.*, g.title as goal_title
               FROM goal_tasks gt JOIN goals g ON gt.goal_id=g.id
               WHERE gt.status='done' AND gt.completed_at > ?
               ORDER BY gt.completed_at DESC""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_recurring_goals(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM goals WHERE status='active' AND schedule IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Drafts ─────────────────────────────────────────────────────────────
    def save_draft(self, draft_type: str, title: str, content: str, metadata: dict = None) -> str:
        draft_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "INSERT INTO drafts VALUES (?,?,?,?,?,?,?,?)",
            (draft_id, draft_type, title, content, json.dumps(metadata or {}), "pending", ts, None),
        )
        self._db.commit()
        return draft_id

    def get_pending_drafts(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM drafts WHERE status='pending' ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_draft(self, draft_id: str) -> Optional[dict]:
        row = self._db.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
        return dict(row) if row else None

    def update_draft_content(self, draft_id: str, new_content: str):
        self._db.execute("UPDATE drafts SET content=? WHERE id=?", (new_content, draft_id))
        self._db.commit()

    def resolve_draft(self, draft_id: str, status: str):
        """status: 'approved', 'rejected'"""
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "UPDATE drafts SET status=?, resolved_at=? WHERE id=?", (status, ts, draft_id)
        )
        self._db.commit()

    # ── Notification queue (quiet hours) ───────────────────────────────────
    def queue_notification(self, message: str, deliver_after: datetime, source: str = "system"):
        notif_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "INSERT INTO notification_queue VALUES (?,?,?,?,?)",
            (notif_id, message, source, ts, deliver_after.isoformat()),
        )
        self._db.commit()

    def get_due_notifications(self) -> list[dict]:
        now = datetime.now(timezone.utc).isoformat()
        rows = self._db.execute(
            "SELECT * FROM notification_queue WHERE deliver_after <= ? ORDER BY queued_at",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_notification(self, notif_id: str):
        self._db.execute("DELETE FROM notification_queue WHERE id=?", (notif_id,))
        self._db.commit()

    def get_notification_count_this_hour(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        row = self._db.execute(
            "SELECT COUNT(*) as n FROM notification_queue WHERE queued_at > ?", (cutoff,)
        ).fetchone()
        return row["n"] if row else 0

    # ── Email triage ───────────────────────────────────────────────────────
    def mark_email_triaged(self, message_id: str, subject: str = "", sender: str = ""):
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "INSERT OR IGNORE INTO email_triage VALUES (?,?,?,?)",
            (message_id, subject, sender, ts),
        )
        self._db.commit()

    def is_email_triaged(self, message_id: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM email_triage WHERE message_id=?", (message_id,)
        ).fetchone()
        return row is not None

    # ── Webhook events ─────────────────────────────────────────────────────
    def save_webhook_event(self, source: str, event_type: str, payload: dict) -> str:
        event_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "INSERT INTO webhook_events VALUES (?,?,?,?,?,?)",
            (event_id, source, event_type, json.dumps(payload), 0, ts),
        )
        self._db.commit()
        return event_id

    def get_unprocessed_webhook_events(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM webhook_events WHERE processed=0 ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_webhook_processed(self, event_id: str):
        self._db.execute(
            "UPDATE webhook_events SET processed=1 WHERE id=?", (event_id,)
        )
        self._db.commit()

    # ── API call budget tracking ────────────────────────────────────────────
    def record_api_call(self, model: str, call_type: str = "chat"):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ts = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "INSERT INTO api_calls (date, model, call_type, created_at) VALUES (?,?,?,?)",
            (today, model, call_type, ts),
        )
        self._db.commit()

    def get_api_calls_today(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = self._db.execute(
            "SELECT COUNT(*) as n FROM api_calls WHERE date=?", (today,)
        ).fetchone()
        return row["n"] if row else 0

    def get_api_call_stats(self, days: int = 7) -> list[dict]:
        rows = self._db.execute(
            """SELECT date, COUNT(*) as calls
               FROM api_calls
               WHERE date >= date('now', ?)
               GROUP BY date ORDER BY date DESC""",
            (f"-{days} days",),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Memory pruning and export ───────────────────────────────────────────
    def get_old_conversation_ids(self, older_than_days: int) -> list[str]:
        """Return ChromaDB document IDs for conversations older than N days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        results = self._conv_col.get(where={"timestamp": {"$lt": cutoff}})
        return results.get("ids", [])

    def delete_conversation_docs(self, doc_ids: list[str]):
        if doc_ids:
            self._conv_col.delete(ids=doc_ids)

    def get_conversation_docs(self, doc_ids: list[str]) -> list[dict]:
        if not doc_ids:
            return []
        results = self._conv_col.get(ids=doc_ids, include=["documents", "metadatas"])
        return [
            {"content": doc, "metadata": meta}
            for doc, meta in zip(results["documents"], results["metadatas"])
        ]

    def get_conversation_count(self) -> int:
        return self._conv_col.count()
