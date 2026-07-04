from __future__ import annotations

import time
import logging
import contextvars
import ipaddress
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, TypeVar
import functools
import inspect

F = TypeVar("F", bound=Callable[..., Any])

from pricing_config import calculate_message_cost

logger = logging.getLogger(__name__)

# ContextVars to store turn-level observability metrics
tool_metrics_var: contextvars.ContextVar[list[dict[str, Any]]] = contextvars.ContextVar(
    "tool_metrics", default=[]
)
request_metadata_var: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "request_metadata", default={}
)

def init_observability_context() -> None:
    """Initialize the ContextVar values for a fresh request turn."""
    tool_metrics_var.set([])
    request_metadata_var.set({
        "started_at": datetime.now(timezone.utc),
        "t_start": time.perf_counter(),
        "t_llm_start": None,
        "t_first_token": None,
        "model_name": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
    })

def timed_tool_execution(func: F) -> F:
    """Decorator to time tool execution, capture status, and record metrics in ContextVar."""
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        started_at = datetime.now(timezone.utc).isoformat()
        t_start = time.perf_counter()
        status = "SUCCESS"
        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            status = "FAILURE"
            result = {"not_found": True, "reason": "internal_error", "error_detail": str(exc)}
            logger.error("Error executing tool %s: %s", func.__name__, exc, exc_info=True)
            
        duration_ms = int((time.perf_counter() - t_start) * 1000)
        completed_at = datetime.now(timezone.utc).isoformat()
        
        # Record metrics in context list
        metric = {
            "name": func.__name__,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "status": status
        }
        
        current_metrics = tool_metrics_var.get()
        # Create a new list to prevent shared state issues across branches
        tool_metrics_var.set(current_metrics + [metric])
        
        return result
    
    wrapper.__signature__ = inspect.signature(func)  # type: ignore
    return wrapper  # type: ignore

def record_llm_call(response_metadata: dict[str, Any]) -> None:
    """Extract model name, token usage and update cumulative request stats."""
    metadata = request_metadata_var.get()
    
    # 1. Extract model name
    model = response_metadata.get("model_name")
    if model:
        metadata["model_name"] = model
        
    # 2. Extract token usage
    usage = response_metadata.get("token_usage") or {}
    
    # Standard format: input/output/total
    input_t = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    output_t = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    total_t = usage.get("total_tokens") or (input_t + output_t)
    
    metadata["input_tokens"] += input_t
    metadata["output_tokens"] += output_t
    metadata["total_tokens"] += total_t
    
    # 3. Calculate cost
    cost = calculate_message_cost(metadata["model_name"], input_t, output_t) or 0.0
    metadata["estimated_cost_usd"] += cost
    
    request_metadata_var.set(metadata)

def mark_llm_start() -> None:
    """Record the timestamp of the first LLM invocation start."""
    metadata = request_metadata_var.get()
    if metadata.get("t_llm_start") is None:
        metadata["t_llm_start"] = time.perf_counter()
        request_metadata_var.set(metadata)

def mark_first_token() -> None:
    """Record the timestamp when the first chunk/token is received/streamed."""
    metadata = request_metadata_var.get()
    if metadata.get("t_first_token") is None:
        metadata["t_first_token"] = time.perf_counter()
        request_metadata_var.set(metadata)
