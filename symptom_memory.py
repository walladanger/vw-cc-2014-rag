"""
Symptom memory: every question asked is a clue about what is wrong with the car.

Each query is stored in a small SQLite file next to the index (out/symptoms.db)
with its timestamp and the manual pages it pulled up. When a new question comes
in, earlier questions that share meaningful words are passed to the model as
background, so it can connect today's symptom to last week's.

Past symptoms are owner observations, never a spec source: they go into the
prompt in their own section and are never cited or used to verify numbers.
"""
import os
import re
import sqlite3
from datetime import datetime

_STOP = set("""
a an the and or but if of to in on at for with from by is are was were be been
it its this that these those my me i we you your our do does did have has had
how what when where why which who can could should would will not no yes there
car vw cc 2014 engine check please help need want get got when then than so
""".split())

_WORD = re.compile(r"[a-z0-9]+")


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP}


class SymptomMemory:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS symptoms (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    asked_at    TEXT NOT NULL,
                    question    TEXT NOT NULL,
                    pages       TEXT,
                    refused     INTEGER DEFAULT 0,
                    note        TEXT
                )""")

    def _conn(self):
        return sqlite3.connect(self.path)

    def record(self, question: str, citations: list | None = None, refused: bool = False) -> int:
        pages = "; ".join(f"{c['manual_id']} p{c['page_physical']}" for c in (citations or [])[:5])
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO symptoms (asked_at, question, pages, refused) VALUES (?, ?, ?, ?)",
                (datetime.now().isoformat(timespec="seconds"), question, pages, int(refused)),
            )
            return cur.lastrowid

    def related(self, question: str, limit: int = 5) -> list[dict]:
        """Earlier questions sharing at least one meaningful word, best overlap first."""
        q = _terms(question)
        if not q:
            return []
        scored = []
        for row in self.all():
            overlap = len(q & _terms(row["question"]))
            if overlap:
                scored.append((overlap, row["id"], row))
        scored.sort(key=lambda t: (-t[0], -t[1]))
        return [r for _, _, r in scored[:limit]]

    def all(self) -> list[dict]:
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("SELECT * FROM symptoms ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

    def set_note(self, symptom_id: int, note: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE symptoms SET note = ? WHERE id = ?", (note, symptom_id))


def format_for_prompt(rows: list[dict]) -> str:
    if not rows:
        return ""
    lines = [f"- {r['asked_at'][:10]}: \"{r['question']}\"" + (f" (owner note: {r['note']})" if r.get("note") else "")
             for r in rows]
    return "\n".join(lines)
