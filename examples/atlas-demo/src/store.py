import sqlite3
from pathlib import Path

from .models import Task


class TaskStore:
    def __init__(self, database: Path) -> None:
        self.database = database

    def save(self, task: Task) -> None:
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO tasks (id, title, completed, created_at) VALUES (?, ?, ?, ?)",
                (task.id, task.title, task.completed, task.created_at.isoformat()),
            )
