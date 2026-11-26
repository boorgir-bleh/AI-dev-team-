import json
from typing import Any, Callable

from pydantic import BaseModel


LLMCallObserver = Callable[[dict[str, Any]], None]


def json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return str(value)
