from __future__ import annotations

import asyncio
import logging

from bot.agent.config import tool_timeout
from bot.agent.context import AgentRunContext, SourceItem
from bot.agent.tools.base import BaseAgentTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: list[BaseAgentTool] = []
        self.used_tools: list[str] = []

    def register(self, tool: BaseAgentTool) -> None:
        self._tools.append(tool)

    def enabled_tools(self, context: AgentRunContext) -> list[BaseAgentTool]:
        return [tool for tool in self._tools if tool.enabled(context)]

    async def run_collectors(self, context: AgentRunContext, queries: list[str] | None = None) -> list[SourceItem]:
        sources: list[SourceItem] = []

        async def run_tool(tool: BaseAgentTool) -> None:
            try:
                result = await asyncio.wait_for(tool.collect(context, queries=queries), timeout=tool_timeout())
                self.used_tools.append(tool.name)
                context.used_tools.append(tool.name)
                sources.extend(result.sources)
                for message in result.errors:
                    context.add_error("collect_sources", message, tool=tool.name)
            except Exception as exc:
                logger.debug("Agent tool failed: %s", tool.name, exc_info=True)
                context.add_error("collect_sources", exc, tool=tool.name)

        await asyncio.gather(*(run_tool(tool) for tool in self.enabled_tools(context)))
        return sources
