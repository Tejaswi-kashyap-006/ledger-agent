"""User memory: pinned core blocks + long-term facts. Shared by the categorizer and the Q&A agent.

    core blocks  (Letta-style)   small, labeled, size-limited, ALWAYS in the prompt.
                                 'household' - who's who: landlord, family, own accounts
                                 'preferences' - how the user wants things categorized / reported
                                 'goals' - budgets and savings targets
    facts        (Generative-Agents-style) many small statements, retrieved per question by
                                 keyword relevance (BM25) + recency + importance.

Memory writes come from the agent's tools (`memory_update`, `remember`) - i.e. from things the
user SAID - never from transaction text, which is untrusted.
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone

DEFAULT_BLOCKS = [
    ("household", "Who is who: landlord, family members, own accounts, employer. Used to categorize transfers.", 1500),
    ("preferences", "How the user wants categorization and reports done.", 1000),
    ("goals", "Budgets and savings goals, with amounts and months.", 1000),
]

_STOP = set("a an the is are was were be i me my you your we our it of to in on at for and or but with this that "
            "what which who how do does did have has had not no so as by from".split())


def ensure_blocks(conn: sqlite3.Connection) -> None:
    for label, desc, limit in DEFAULT_BLOCKS:
        conn.execute("INSERT OR IGNORE INTO memory_blocks (label, description, value, char_limit) VALUES (?,?,'',?)",
                     (label, desc, limit))


def render_blocks(conn: sqlite3.Connection) -> str:
    ensure_blocks(conn)
    parts = []
    for r in conn.execute("SELECT label, description, value, char_limit FROM memory_blocks ORDER BY label"):
        parts.append(f'<{r["label"]} description="{r["description"]}" chars="{len(r["value"])}/{r["char_limit"]}">\n'
                     f'{r["value"]}\n</{r["label"]}>')
    return "\n".join(parts)


def profile_text(conn: sqlite3.Connection) -> str:
    """Compact version for the bulk categorizer: only non-empty blocks."""
    ensure_blocks(conn)
    rows = conn.execute("SELECT label, value FROM memory_blocks WHERE value != '' ORDER BY label").fetchall()
    return "\n".join(f"[{r['label']}] {r['value']}" for r in rows)


def update_block(conn: sqlite3.Connection, label: str, old: str, new: str) -> str:
    """old='' appends `new` as a line; otherwise replaces the first occurrence of `old`."""
    ensure_blocks(conn)
    row = conn.execute("SELECT value, char_limit FROM memory_blocks WHERE label = ?", (label,)).fetchone()
    if row is None:
        raise ValueError(f"no memory block {label!r}; use one of: " + ", ".join(b[0] for b in DEFAULT_BLOCKS))
    value = row["value"]
    if old:
        if old not in value:
            raise ValueError(f"{old!r} not found in block {label!r}. Current value:\n{value}")
        value = value.replace(old, new, 1).strip()
    else:
        value = (value + "\n" + new).strip()
    if len(value) > row["char_limit"]:
        raise ValueError(f"block {label!r} would be {len(value)}/{row['char_limit']} chars - condense it first "
                         "by replacing old text with a shorter summary.")
    conn.execute("UPDATE memory_blocks SET value = ? WHERE label = ?", (value, label))
    return f"updated {label} ({len(value)}/{row['char_limit']} chars)"


# ---------------------------------------------------------------------------------- facts
def _tok(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP]


def remember(conn: sqlite3.Connection, text: str, importance: float = 5) -> int:
    cur = conn.execute("INSERT INTO memory_facts (text, importance) VALUES (?, ?) RETURNING id",
                       (text.strip()[:500], float(min(max(importance, 1), 10))))
    return cur.fetchone()["id"]


def forget(conn: sqlite3.Connection, fact_id: int) -> bool:
    return conn.execute("UPDATE memory_facts SET active = 0 WHERE id = ?", (fact_id,)).rowcount == 1


def recall(conn: sqlite3.Connection, query: str, k: int = 5, now: datetime | None = None) -> list[sqlite3.Row]:
    """score = BM25(query, fact) normalized + 0.995^hours_since_access + importance/10."""
    rows = conn.execute("SELECT id, text, importance, created_at, last_accessed FROM memory_facts WHERE active = 1")\
        .fetchall()
    if not rows:
        return []
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    docs = {r["id"]: _tok(r["text"]) for r in rows}
    n = len(docs)
    avgdl = sum(len(d) for d in docs.values()) / n or 1
    df = Counter(w for d in docs.values() for w in set(d))
    q = set(_tok(query))
    bm25 = {}
    for i, d in docs.items():
        tf = Counter(d)
        bm25[i] = sum(math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5)) * tf[w] * 2.5 / (tf[w] + 1.5 * (0.25 + 0.75 * len(d) / avgdl))
                      for w in q if w in tf)
    top = max(bm25.values()) or 1.0
    scored = []
    for r in rows:
        hours = max((now - datetime.fromisoformat(r["last_accessed"])).total_seconds() / 3600, 0)
        relevance = bm25[r["id"]] / top
        score = 2.0 * relevance + 0.995 ** hours + r["importance"] / 10
        if relevance > 0 or r["importance"] >= 8:      # irrelevant low-importance facts stay out of context
            scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    hits = [r for _, r in scored[:k]]
    if hits:
        conn.execute(f"UPDATE memory_facts SET last_accessed = datetime('now') WHERE id IN ({','.join('?' * len(hits))})",
                     [h["id"] for h in hits])
    return hits
