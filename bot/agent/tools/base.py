from __future__ import annotations

from dataclasses import dataclass, field

from bot.agent.context import AgentRunContext, SourceItem


@dataclass
class ToolResult:
    tool_name: str
    sources: list[SourceItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class BaseAgentTool:
    name = "base"
    source_type = "generic"

    def enabled(self, context: AgentRunContext) -> bool:
        return True

    async def collect(self, context: AgentRunContext, queries: list[str] | None = None) -> ToolResult:
        return ToolResult(tool_name=self.name)
