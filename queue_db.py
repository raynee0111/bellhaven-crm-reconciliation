"""Persist proposed/approved/rejected items to prevent rerun re-proposals."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
DB = Path(__file__).with_name("review.sqlite3")


def connect():
    cn = sqlite3.connect(DB)
    cn.row_factory = sqlite3.Row
    cn.execute("""CREATE TABLE IF NOT EXISTS proposals (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      dedupe_key TEXT UNIQUE NOT NULL,
      kind TEXT NOT NULL,
      facility TEXT NOT NULL,
      payload TEXT NOT NULL,
      evidence TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'pending',
      result TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    cn.commit()
    return cn


def add(proposals):
    count = 0
    with connect() as cn:
        for p in proposals:
            c = cn.execute("INSERT OR IGNORE INTO proposals (dedupe_key,kind,facility,payload,evidence) VALUES (?,?,?,?,?)", (
                p["dedupe_key"], p["kind"], p["facility"], json.dumps(p["payload"]), json.dumps(p["evidence"])))
            count += c.rowcount
    return count


def list_items(states=("pending", "error")):
    with connect() as cn:
        query = ",".join("?" for _ in states)
        return [dict(row) for row in cn.execute(f"SELECT * FROM proposals WHERE state IN ({query}) ORDER BY id", tuple(states))]


def update(item_id, state, result=None):
    with connect() as cn:
        if result is None:
            cn.execute("UPDATE proposals SET state=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (state, item_id))
        else:
            cn.execute("UPDATE proposals SET state=?,result=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (state, json.dumps(result), item_id))


def by_id(item_id):
    with connect() as cn:
        row = cn.execute("SELECT * FROM proposals WHERE id=?", (item_id,)).fetchone()
    return dict(row) if row else None
