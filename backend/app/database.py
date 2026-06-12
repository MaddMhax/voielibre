"""Couche d'accès aux données : SQLite via la lib standard (aucune dépendance lourde).

Un "trajet" = une gare de départ + une gare d'arrivée + une période (matin/soir).
"""
import os
import sqlite3
from contextlib import contextmanager
from typing import Optional

from .config import settings


@contextmanager
def get_conn():
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def init_db() -> None:
    """Crée la table des trajets ; migre l'ancien schéma (gare unique) si besoin."""
    os.makedirs(os.path.dirname(settings.DB_PATH) or ".", exist_ok=True)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='lines'"
        ).fetchone()

        # Ancien modèle (gare de départ seule) -> on repart proprement sur le
        # nouveau modèle "trajet". Les anciennes lignes sont à recréer via l'admin.
        if existing and not _has_column(conn, "lines", "from_id"):
            conn.execute("DROP TABLE lines")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lines (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                label       TEXT    NOT NULL,
                from_id     TEXT    NOT NULL,
                from_name   TEXT    NOT NULL,
                to_id       TEXT    NOT NULL,
                to_name     TEXT    NOT NULL,
                period      TEXT    NOT NULL DEFAULT 'both',
                position    INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # Migration douce : heure de notification ntfy (vide = désactivée).
        if not _has_column(conn, "lines", "notify_time"):
            conn.execute(
                "ALTER TABLE lines ADD COLUMN notify_time TEXT NOT NULL DEFAULT ''"
            )

        # Compteur local d'appels à l'API SNCF. La clé `month` reçoit aussi
        # bien un mois ("2026-06") qu'un jour ("2026-06-12") : un appel
        # incrémente les deux périodes.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_usage (
                month TEXT PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 0
            )
            """
        )


def list_lines(period: Optional[str] = None) -> list[dict]:
    with get_conn() as conn:
        if period:
            rows = conn.execute(
                "SELECT * FROM lines WHERE period IN (?, 'both') ORDER BY position, id",
                (period,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM lines ORDER BY position, id"
            ).fetchall()
        return [dict(r) for r in rows]


def get_line(line_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM lines WHERE id = ?", (line_id,)).fetchone()
        return dict(row) if row else None


def add_line(
    label: str,
    from_id: str,
    from_name: str,
    to_id: str,
    to_name: str,
    period: str,
    notify_time: str = "",
) -> int:
    with get_conn() as conn:
        # En fin de liste par défaut.
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM lines").fetchone()[0]
        cur = conn.execute(
            """INSERT INTO lines
               (label, from_id, from_name, to_id, to_name, period, position, notify_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (label, from_id, from_name, to_id, to_name, period, pos, notify_time),
        )
        return cur.lastrowid


def delete_line(line_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM lines WHERE id = ?", (line_id,))


def move_line(line_id: int, direction: str) -> bool:
    """Monte ou descend un trajet dans l'ordre d'affichage."""
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM lines ORDER BY position, id").fetchall()
        ids = [r["id"] for r in rows]
        if line_id not in ids:
            return False
        i = ids.index(line_id)
        j = i - 1 if direction == "up" else i + 1
        if not (0 <= j < len(ids)):
            return False
        ids[i], ids[j] = ids[j], ids[i]
        # Réécrit des positions séquentielles propres.
        for pos, lid in enumerate(ids):
            conn.execute("UPDATE lines SET position = ? WHERE id = ?", (pos, lid))
        return True


def replace_lines(lines: list[dict]) -> int:
    """Restauration d'un export : remplace l'intégralité des trajets."""
    with get_conn() as conn:
        conn.execute("DELETE FROM lines")
        for pos, ln in enumerate(lines):
            conn.execute(
                """INSERT INTO lines
                   (label, from_id, from_name, to_id, to_name, period, position, notify_time)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ln["label"], ln["from_id"], ln["from_name"],
                    ln["to_id"], ln["to_name"], ln["period"],
                    pos, ln.get("notify_time", ""),
                ),
            )
        return len(lines)


def bump_api_usage(month: str, n: int = 1) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO api_usage (month, count) VALUES (?, ?)
               ON CONFLICT(month) DO UPDATE SET count = count + excluded.count""",
            (month, n),
        )


def get_api_usage(month: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT count FROM api_usage WHERE month = ?", (month,)
        ).fetchone()
        return row["count"] if row else 0
