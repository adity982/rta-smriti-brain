from .service import TaskService


def create_task(service: TaskService, payload: dict[str, object]) -> dict[str, object]:
    task = service.create(int(payload["id"]), str(payload["title"]))
    return {"id": task.id, "title": task.title, "completed": task.completed}
