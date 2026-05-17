from __future__ import annotations

from typing import Any, Callable


class ExecutionModeService:
    """Decides whether Queen should answer directly, use tools, or delegate to workers."""

    def __init__(
        self,
        execution_mode: str,
        infer_file_action: Callable[[str], dict[str, Any] | None],
        extract_save_to_file_request: Callable[[str], tuple[bool, str | None]],
        looks_like_shell_task: Callable[[str], bool],
    ) -> None:
        self.execution_mode = execution_mode
        self._infer_file_action = infer_file_action
        self._extract_save_to_file_request = extract_save_to_file_request
        self._looks_like_shell_task = looks_like_shell_task

    def select_execution_path(self, payload: dict[str, Any], action_result_present: bool) -> str:
        if action_result_present and payload.get("stop_after_actions"):
            return "action_loop"
        if self.execution_mode in ("model_tools", "hybrid"):
            return "tool_loop"
        if not self.should_delegate_to_workers(payload):
            return "direct_chat"
        return "worker_delegation"

    def should_delegate_to_workers(self, payload: dict[str, Any]) -> bool:
        if payload.get("delegate_to_worker") is True:
            return True
        if payload.get("use_web_search") is True:
            return True
        if payload.get("domains"):
            return True
        if payload.get("numbers") is not None or payload.get("operation"):
            return True
        query = str(payload.get("query") or payload.get("topic") or "").strip()
        if query and self._infer_file_action(query):
            return True
        if query and self._extract_save_to_file_request(query)[0]:
            return True
        if query and self._looks_like_shell_task(query):
            return True
        return False
