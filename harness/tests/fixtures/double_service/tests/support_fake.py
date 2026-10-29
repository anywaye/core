
from __future__ import annotations

from typing import Any, Mapping


class FakePool:

    def __init__(self) -> None:
        self.rows: dict[str, Mapping[str, Any]] = {}

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        if "delete from" in sql:
            self.rows.pop(str(params[0]), None)
        elif "insert into" in sql:
            self.rows[str(params[0])] = {"id": params[0]}
