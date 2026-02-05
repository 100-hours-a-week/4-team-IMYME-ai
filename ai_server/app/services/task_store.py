from typing import Dict, Any, Optional


class TaskStore:
    """
    [v1 Only] In-Memory Task Storage
    - Uses a simple Python dictionary to store task states.
    - Singleton pattern to ensure shared state across the application instance.
    - FUTURE (v2): Replace this class with a Redis-based implementation.
    """

    _instance = None
    _tasks: Dict[str, Dict[str, Any]] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TaskStore, cls).__new__(cls)
            cls._tasks = {}
        return cls._instance

    def save_task(
        self,
        task_id: str,
        status: str,
        result: Optional[Dict] = None,
        error: Optional[Dict] = None,
    ):
        """
        Saves or updates a task's state.
        """
        self._tasks[task_id] = {
            "taskId": task_id,
            "status": status,
            "result": result,
            "error": error,
        }

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a task by ID.
        Returns None if not found.
        """
        return self._tasks.get(task_id)

    def delete_task(self, task_id: str):
        """
        [Cleanup] Removes a task from memory.
        """
        if task_id in self._tasks:
            del self._tasks[task_id]


# Create a global instance to be imported by other services
task_store = TaskStore()
