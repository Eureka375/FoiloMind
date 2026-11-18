import os
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from foliomind.settings import SCHEMA_VERSION, Settings, SettingsError, SettingsStore, StartupPage


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.store = SettingsStore(self.directory / "profile" / "foliomind.sqlite3")

    def test_initial_schema_and_revision(self) -> None:
        first = self.store.load()
        self.assertEqual(first, Settings())
        self.store.save(StartupPage.TASKS, first.revision)
        with self.assertRaisesRegex(SettingsError, "设置记录已变化"):
            self.store.save(StartupPage.WORKSPACE, first.revision)
        self.assertEqual(self.store.load(), Settings(StartupPage.TASKS, 1))

    def test_unknown_schema_version_is_preserved(self) -> None:
        self.store.load()
        self.store.save(StartupPage.TASKS, 0)
        future_version = SCHEMA_VERSION + 1
        with closing(sqlite3.connect(self.store.path)) as connection, connection:
            connection.execute(f"PRAGMA user_version = {future_version}")
        with self.assertRaisesRegex(SettingsError, "不兼容"):
            self.store.load()
        with closing(sqlite3.connect(self.store.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], future_version)
            self.assertEqual(connection.execute("SELECT startup_page FROM settings").fetchone()[0], "tasks")

    def test_unrecognized_version_zero_is_preserved(self) -> None:
        self.store.path.parent.mkdir()
        with closing(sqlite3.connect(self.store.path)) as connection, connection:
            connection.execute("CREATE TABLE legacy (value TEXT)")
            connection.execute("INSERT INTO legacy VALUES ('saved')")
        with self.assertRaisesRegex(SettingsError, "无法识别"):
            self.store.load()
        with closing(sqlite3.connect(self.store.path)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM legacy").fetchone()[0], "saved")

    def test_missing_database_is_not_created_by_save(self) -> None:
        self.store.path.parent.mkdir()
        with self.assertRaisesRegex(SettingsError, "无法保存"):
            self.store.save(StartupPage.TASKS, 0)
        self.assertFalse(self.store.path.exists())

    def test_startup_page_survives_two_windows_processes(self) -> None:
        project = Path(__file__).resolve().parents[1]
        profile = self.directory / "windows profile"
        env = {**os.environ, "LOCALAPPDATA": str(profile), "PYTHONPATH": str(project)}
        process_code = """
import sys
import tkinter as tk
from foliomind.desktop import DesktopApp
from foliomind.settings import StartupPage

root = tk.Tk()
app = DesktopApp(root)
root.update()
assert root.winfo_viewable()
if sys.argv[1] == 'save':
    assert app.tabs.select() == str(app.workspace)
    app.startup_page.set(StartupPage.TASKS.value)
    app.save_button.invoke()
    assert app.settings_status.get() == '已保存。下次启动时生效。', app.settings_status.get()
else:
    assert app.tabs.select() == str(app.tasks), app.settings_status.get()
    assert app.startup_page.get() == StartupPage.TASKS.value
app.close()
root.wait_window()
"""
        for mode in ("save", "reload"):
            result = subprocess.run(
                [sys.executable, "-B", "-c", process_code, mode],
                cwd=self.directory,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((profile / "FolioMind" / "foliomind.sqlite3").is_file())
