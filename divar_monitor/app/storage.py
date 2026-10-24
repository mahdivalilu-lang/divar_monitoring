from __future__ import annotations

import time
from pathlib import Path

import aiosqlite


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def __aenter__(self) -> "Storage":
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS seen_posts (
                token       TEXT PRIMARY KEY,
                title       TEXT,
                status      TEXT NOT NULL,      -- 'notified' | 'skipped' | 'seeded'
                first_seen  INTEGER NOT NULL
            )""")
        await self._db.commit()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._db:
            await self._db.close()

    async def is_seen(self, token: str) -> bool:
        async with self._db.execute(
                "SELECT 1 FROM seen_posts WHERE token = ?", (token,)) as cur:
            return await cur.fetchone() is not None

    async def mark(self, token: str, title: str, status: str) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO seen_posts (token, title, status, first_seen) "
            "VALUES (?, ?, ?, ?)", (token, title, status, int(time.time())))
        await self._db.commit()

    async def count(self) -> int:
        async with self._db.execute("SELECT COUNT(*) FROM seen_posts") as cur:
            return (await cur.fetchone())[0]

    async def prune(self, older_than_days: int = 90) -> None:
        cutoff = int(time.time()) - older_than_days * 86400
        await self._db.execute("DELETE FROM seen_posts WHERE first_seen < ?", (cutoff,))
        await self._db.commit()
