from datetime import UTC, datetime

from .models import Task
from .store import TaskStore


class TaskService:
    def __init__(self, store: TaskStore) -> None:
        self.store = store

    def create(self, task_id: int, title: str) -> Task:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("task title is required")
        task = Task(task_id, clean_title, False, datetime.now(UTC))
        self.store.save(task)
        return task
