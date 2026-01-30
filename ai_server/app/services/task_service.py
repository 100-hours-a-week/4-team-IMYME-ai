import uuid
from app.services.task_store import task_store
from typing import Optional, Dict, Any


class TaskService:
    """
    Service for managing Task lifecycle (Creation, Retrieval).
    """

    def create_task(self, attempt_id: int) -> int:
        """
        Creates a new task with PENDING status using client-provided attempt_id.
        """
        task_key = str(attempt_id)
        task_store.save_task(task_key, "PENDING")
        return attempt_id

    def get_task_status(self, attempt_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieves the task status/result using attempt_id.
        """
        task_key = str(attempt_id)
        return task_store.get_task(task_key)


task_service = TaskService()
