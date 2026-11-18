"""Runtime checks that require neither documents nor a model."""

import sqlite3
import sys


def check_python() -> None:
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11 is required")


def check_sqlite() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("SELECT 1").fetchone()
    finally:
        connection.close()
