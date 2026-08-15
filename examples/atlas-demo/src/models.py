from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    completed: bool
    created_at: datetime
