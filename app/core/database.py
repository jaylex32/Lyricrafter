from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from app.core.config import data_dir
from app.core.jobs import JobResult, LyricJob


class AppDatabase:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "lyricrafter.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                create table if not exists settings (
                    key text primary key,
                    value text not null
                );

                create table if not exists job_history (
                    id text primary key,
                    source_path text not null,
                    status text not null,
                    message text,
                    lrc_path text,
                    txt_path text,
                    created_at text not null default current_timestamp,
                    updated_at text not null default current_timestamp
                );

                create table if not exists recent_folders (
                    path text primary key,
                    updated_at text not null default current_timestamp
                );
                """
            )

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.connection() as conn:
            row = conn.execute("select value from settings where key = ?", (key,)).fetchone()
        return default if row is None else str(row["value"])

    def set_setting(self, key: str, value: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                insert into settings(key, value) values(?, ?)
                on conflict(key) do update set value = excluded.value
                """,
                (key, value),
            )

    def save_job(self, job: LyricJob) -> None:
        result: JobResult | None = job.result
        with self.connection() as conn:
            conn.execute(
                """
                insert into job_history(id, source_path, status, message, lrc_path, txt_path)
                values(?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    status = excluded.status,
                    message = excluded.message,
                    lrc_path = excluded.lrc_path,
                    txt_path = excluded.txt_path,
                    updated_at = current_timestamp
                """,
                (
                    job.id,
                    str(job.source_path),
                    job.status.value,
                    job.message,
                    str(result.lrc_path) if result else None,
                    str(result.txt_path) if result else None,
                ),
            )

    def add_recent_folder(self, path: Path) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                insert into recent_folders(path) values(?)
                on conflict(path) do update set updated_at = current_timestamp
                """,
                (str(path),),
            )

    def list_history(self, limit: int = 200) -> list[sqlite3.Row]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                select * from job_history
                order by updated_at desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return list(rows)

    def clear_history(self) -> None:
        with self.connection() as conn:
            conn.execute("delete from job_history")

    def list_recent_folders(self) -> Iterable[Path]:
        with self.connection() as conn:
            rows = conn.execute("select path from recent_folders order by updated_at desc").fetchall()
        return [Path(row["path"]) for row in rows]
