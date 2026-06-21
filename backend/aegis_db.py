"""
AutoHeal.ai - Audit Log (SQLite Database Module)
Tracks all API failures, agent remediation steps, code diffs, and PR history.
"""
import sqlite3
import json
import os
import sys
from datetime import datetime, timezone

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = os.path.join(os.path.dirname(__file__), "aegis_audit.db")


def get_connection():
    """Returns a connection to the SQLite database, creating tables if needed."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection):
    """Creates the audit log tables if they do not exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS incidents (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            target_url      TEXT    NOT NULL,
            original_payload TEXT   NOT NULL,
            error_message   TEXT    NOT NULL,
            source_file     TEXT,
            status          TEXT    NOT NULL DEFAULT 'open'
        );

        CREATE TABLE IF NOT EXISTS agent_steps (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id     INTEGER NOT NULL REFERENCES incidents(id),
            created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            step_name       TEXT    NOT NULL,
            attempt         INTEGER NOT NULL DEFAULT 1,
            reasoning       TEXT,
            old_schema      TEXT,
            new_schema      TEXT,
            old_code        TEXT,
            new_code        TEXT,
            healed_payload  TEXT,
            verification    TEXT,
            error_detail    TEXT
        );

        CREATE TABLE IF NOT EXISTS pr_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id     INTEGER NOT NULL REFERENCES incidents(id),
            created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            branch_name     TEXT,
            target_file     TEXT,
            pr_url          TEXT,
            status          TEXT    NOT NULL DEFAULT 'pending'
        );
    """)
    conn.commit()


# ------------------------------------------------------------------
# Incident CRUD
# ------------------------------------------------------------------
def create_incident(target_url: str, original_payload: dict, error_message: str, source_file: str = None) -> int:
    """Creates a new incident row and returns its ID."""
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO incidents (target_url, original_payload, error_message, source_file) VALUES (?, ?, ?, ?)",
        (target_url, json.dumps(original_payload), error_message, source_file)
    )
    conn.commit()
    incident_id = cur.lastrowid
    conn.close()
    print(f"[AegisDB] Incident #{incident_id} created.")
    return incident_id


def update_incident_status(incident_id: int, status: str):
    """Updates the status of an incident (open / healed / failed)."""
    conn = get_connection()
    conn.execute("UPDATE incidents SET status = ? WHERE id = ?", (status, incident_id))
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# Agent Step Logging
# ------------------------------------------------------------------
def log_agent_step(
    incident_id: int,
    step_name: str,
    attempt: int = 1,
    reasoning: str = None,
    old_schema: dict = None,
    new_schema: dict = None,
    old_code: str = None,
    new_code: str = None,
    healed_payload: dict = None,
    verification: str = None,
    error_detail: str = None
):
    """Logs a single agent step (diagnose, sandbox, verify) against an incident."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO agent_steps
           (incident_id, step_name, attempt, reasoning, old_schema, new_schema,
            old_code, new_code, healed_payload, verification, error_detail)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            incident_id, step_name, attempt, reasoning,
            json.dumps(old_schema) if old_schema else None,
            json.dumps(new_schema) if new_schema else None,
            old_code, new_code,
            json.dumps(healed_payload) if healed_payload else None,
            verification, error_detail
        )
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# PR History Logging
# ------------------------------------------------------------------
def log_pr(incident_id: int, branch_name: str, target_file: str, pr_url: str = None, status: str = "pending"):
    """Logs a Pull Request creation event against an incident."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO pr_history (incident_id, branch_name, target_file, pr_url, status) VALUES (?, ?, ?, ?, ?)",
        (incident_id, branch_name, target_file, pr_url, status)
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# Query helpers (for the dashboard API)
# ------------------------------------------------------------------
def get_all_incidents(limit: int = 50) -> list[dict]:
    """Returns the most recent incidents."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM incidents ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_incident_detail(incident_id: int) -> dict:
    """Returns a full incident with its agent steps and PR history."""
    conn = get_connection()
    incident = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    if not incident:
        conn.close()
        return None

    steps = conn.execute(
        "SELECT * FROM agent_steps WHERE incident_id = ? ORDER BY created_at ASC", (incident_id,)
    ).fetchall()

    prs = conn.execute(
        "SELECT * FROM pr_history WHERE incident_id = ? ORDER BY created_at ASC", (incident_id,)
    ).fetchall()

    conn.close()
    return {
        "incident": dict(incident),
        "steps": [dict(s) for s in steps],
        "prs": [dict(p) for p in prs],
    }
