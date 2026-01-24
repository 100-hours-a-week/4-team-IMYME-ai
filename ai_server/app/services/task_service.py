import uuid
from app.services.task_store import task_store
from typing import Optional, Dict, Any


class TaskService:
    """
    Service for managing Task lifecycle (Creation, Retrieval).
    """

    def create_task(self) -> str:
        """
        Creates a new task with PENDING status and returns the ID.
        """
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        task_store.save_task(task_id, "PENDING")
        return task_id

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves the task status/result.
        """
        return task_store.get_task(task_id)


task_service = TaskService()
