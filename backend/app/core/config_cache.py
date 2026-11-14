"""In-memory cache for configuration snapshots (published forms, workflows, options).

Invalidated immediately on publish or modification (prompt P4-05 PERFORMANCE §3).
Thread-safe with thread lock.
"""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()

_published_forms: dict[str, dict[str, Any]] = {}
_published_workflows: dict[str, dict[str, Any]] = {}
_option_sets: dict[str, dict[str, Any]] = {}


# --- Forms Cache -------------------------------------------------------------------------------
def get_cached_published_form(form_code: str) -> dict[str, Any] | None:
    with _lock:
        return _published_forms.get(form_code)


def set_cached_published_form(form_code: str, snapshot: dict[str, Any]) -> None:
    with _lock:
        _published_forms[form_code] = snapshot


def invalidate_form_cache(form_code: str | None = None) -> None:
    with _lock:
        if form_code is not None:
            _published_forms.pop(form_code, None)
        else:
            _published_forms.clear()


# --- Workflow Cache ----------------------------------------------------------------------------
def get_cached_published_workflow(workflow_code: str) -> dict[str, Any] | None:
    with _lock:
        return _published_workflows.get(workflow_code)


def set_cached_published_workflow(workflow_code: str, snapshot: dict[str, Any]) -> None:
    with _lock:
        _published_workflows[workflow_code] = snapshot


def invalidate_workflow_cache(workflow_code: str | None = None) -> None:
    with _lock:
        if workflow_code is not None:
            _published_workflows.pop(workflow_code, None)
        else:
            _published_workflows.clear()


# --- Option Sets Cache -------------------------------------------------------------------------
def get_cached_option_set(code: str) -> dict[str, Any] | None:
    with _lock:
        return _option_sets.get(code)


def set_cached_option_set(code: str, data: dict[str, Any]) -> None:
    with _lock:
        _option_sets[code] = data


def invalidate_option_cache(code: str | None = None) -> None:
    with _lock:
        if code is not None:
            _option_sets.pop(code, None)
        else:
            _option_sets.clear()


# --- Global Invalidation -----------------------------------------------------------------------
def clear_all_config_cache() -> None:
    with _lock:
        _published_forms.clear()
        _published_workflows.clear()
        _option_sets.clear()
