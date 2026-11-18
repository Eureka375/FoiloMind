"""Per-user settings and application database schema."""

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


SCHEMA_VERSION = 1


class StartupPage(StrEnum):
    WORKSPACE = "workspace"
    TASKS = "tasks"


@dataclass(frozen=True)
class Settings:
    startup_page: StartupPage = StartupPage.WORKSPACE
    revision: int = 0


class SettingsError(Exception):
    """A settings failure that can be shown without exposing paths or payloads."""


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_current_user(cls) -> "SettingsStore":
        local_data = os.environ.get("LOCALAPPDATA")
        if not local_data or not Path(local_data).is_absolute():
            raise SettingsError("找不到当前用户的 Windows 本地应用数据目录。")
        return cls(Path(local_data) / "FolioMind" / "foliomind.sqlite3")

    def load(self) -> Settings:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=0.25)) as connection, connection:
                self._ensure_schema(connection)
                row = connection.execute(
                    "SELECT startup_page, revision FROM settings WHERE singleton = 1"
                ).fetchone()
                if row is None:
                    raise SettingsError("本地设置记录缺失，请检查应用数据库。")
                return Settings(StartupPage(row[0]), row[1])
        except (OSError, sqlite3.Error, ValueError) as error:
            raise SettingsError("无法读取本地设置。请检查应用数据目录或数据库。") from error

    def save(self, page: StartupPage, expected_revision: int) -> Settings:
        try:
            uri = f"{self.path.absolute().as_uri()}?mode=rw"
            with closing(sqlite3.connect(uri, uri=True, timeout=0.25)) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                if self._schema_version(connection) != SCHEMA_VERSION:
                    raise SettingsError("本地数据库版本已变化，请重新启动应用。")
                updated = connection.execute(
                    """UPDATE settings SET startup_page = ?, revision = revision + 1
                       WHERE singleton = 1 AND revision = ?""",
                    (page.value, expected_revision),
                )
                if updated.rowcount != 1:
                    raise SettingsError("设置记录已变化，请重新打开应用后再保存。")
                return Settings(page, expected_revision + 1)
        except (OSError, sqlite3.Error) as error:
            raise SettingsError("无法保存本地设置。请检查应用数据目录的写入权限或稍后重试。") from error

    @staticmethod
    def _schema_version(connection: sqlite3.Connection) -> int:
        return connection.execute("PRAGMA user_version").fetchone()[0]

    @classmethod
    def _ensure_schema(cls, connection: sqlite3.Connection) -> None:
        version = cls._schema_version(connection)
        if version == 0:
            # Start at version zero only for a new database. Recheck after taking the lock.
            connection.execute("BEGIN IMMEDIATE")
            version = cls._schema_version(connection)
            if version == 0:
                existing_objects = connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*' LIMIT 1"
                ).fetchone()
                if existing_objects:
                    raise SettingsError("应用数据库包含无法识别的旧版结构。")
                connection.execute("""
                    CREATE TABLE settings (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        startup_page TEXT NOT NULL CHECK (startup_page IN ('workspace', 'tasks')),
                        revision INTEGER NOT NULL CHECK (revision >= 0)
                    )
                    """)
                connection.execute(
                    "INSERT INTO settings VALUES (1, ?, 0)", (StartupPage.WORKSPACE.value,)
                )
                connection.execute("PRAGMA user_version = 1")
                version = 1
        if version != SCHEMA_VERSION:
            raise SettingsError("应用数据库版本与当前程序不兼容。请使用对应版本打开。")
