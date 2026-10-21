"""Runs the graph for one case at a time and reports its state.

A per-case lock serialises start/resume so two quick clicks cannot interleave on one thread.
Failures become a typed event plus a 'failed' status; the checkpoint is kept, so retry() continues
from the last completed node instead of starting over."""
import threading
from datetime import date
from typing import Any

from langgraph.types import Command

from app import db
from app.agents.checkpoint import get_checkpointer
from app.agents.graph import build_graph
from app.agents.nodes import WorkflowCancelled
from app.repositories.cases import TenantRepo

_graph = None
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph(get_checkpointer())
    return _graph


def reset_graph() -> None:
    """Tests only."""
    global _graph
    _graph = None


def _lock(case_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(case_id, threading.Lock())


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}


def _run(tenant_id: str, case_id: str, thread_id: str, graph_input: Any) -> None:
    with _lock(case_id):
        try:
            get_graph().invoke(graph_input, _config(thread_id))
        except WorkflowCancelled:
            pass
        except Exception as exc:  # noqa: BLE001 - the user needs a clear failure, not a hung screen
            with db.SessionLocal() as session:
                repo = TenantRepo(session, tenant_id)
                case = repo.get_case(case_id)
                repo.update_case(case, status="failed")
                repo.emit(case_id, "workflow_error", "Something went wrong. Your answers are saved. Retry to continue.",
                          error=exc.__class__.__name__)
                repo.audit("workflow_failed", case_id, error=exc.__class__.__name__)


def start(tenant_id: str, case_id: str, thread_id: str, user_id: str, workspace: str, transcript: str) -> None:
    initial = {"tenant_id": tenant_id, "case_id": case_id, "user_id": user_id, "workspace": workspace,
               "transcript": transcript, "today": date.today().isoformat()}
    _run(tenant_id, case_id, thread_id, initial)


def resume(tenant_id: str, case_id: str, thread_id: str, payload: dict[str, Any]) -> None:
    _run(tenant_id, case_id, thread_id, Command(resume=payload))


def retry(tenant_id: str, case_id: str, thread_id: str) -> None:
    """Continue a failed run from its last checkpoint."""
    _run(tenant_id, case_id, thread_id, None)


def pending_interrupt(thread_id: str) -> dict | None:
    """What the graph is currently waiting for, or None if it is not paused."""
    snap = get_graph().get_state(_config(thread_id))
    for task in snap.tasks:
        for it in getattr(task, "interrupts", ()):
            return dict(it.value)
    return None


def graph_values(thread_id: str) -> dict:
    return dict(get_graph().get_state(_config(thread_id)).values or {})
