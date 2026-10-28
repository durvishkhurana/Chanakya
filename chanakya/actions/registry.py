"""Tool registry with a membership check: unknown tools and bad arguments are rejected, never improvised."""

from __future__ import annotations

from pydantic import ValidationError

from chanakya.actions.systems.db import MockDB, MockSystemError
from chanakya.actions.systems.tools import TOOLS, Tool
from chanakya.core.interfaces import UnknownToolError
from chanakya.core.schemas import ToolCall, ToolInfo, ToolResult


class InvalidArgumentsError(ValueError):
    """Tool arguments that do not match the tool's schema."""


class MockToolRegistry:
    """Registry over the mock systems in ``chanakya.actions.systems``."""

    def __init__(self, db: MockDB, tools: list[Tool] | None = None):
        self.db = db
        self._tools = {tool.name: tool for tool in (tools or TOOLS)}

    def tools(self) -> list[ToolInfo]:
        """Descriptions of every registered tool."""
        return [self._info(tool) for tool in self._tools.values()]

    def get(self, name: str) -> ToolInfo | None:
        """The tool's description, or None for an unknown name."""
        tool = self._tools.get(name)
        return self._info(tool) if tool else None

    def validate(self, call: ToolCall) -> ToolCall:
        """Return the call with schema-validated arguments."""
        tool = self._tools.get(call.tool)
        if tool is None:
            raise UnknownToolError(call.tool)
        try:
            args = tool.args.model_validate(call.args)
        except ValidationError as error:
            raise InvalidArgumentsError(f"{call.tool}: {error.errors(include_url=False)}") from error
        return call.model_copy(update={"args": args.model_dump()})

    def execute(self, call: ToolCall) -> ToolResult:
        """Run a call against its mock system. Failures come back as ``ok=False``, never as exceptions."""
        call = self.validate(call)
        tool = self._tools[call.tool]
        try:
            self.db.maybe_fail(tool.system)
            data = tool.handler(self.db, tool.args.model_validate(call.args), call)
        except (MockSystemError, LookupError) as error:
            return ToolResult(call_id=call.id, tool=call.tool, ok=False, error=str(error))
        return ToolResult(call_id=call.id, tool=call.tool, ok=True, data=data)

    @staticmethod
    def _info(tool: Tool) -> ToolInfo:
        return ToolInfo(name=tool.name, system=tool.system, kind=tool.kind, description=tool.description,
                        args_schema=tool.args.model_json_schema(), irreversible=tool.irreversible)
