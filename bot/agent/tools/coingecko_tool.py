from __future__ import annotations

from bot.agent.context import AgentRunContext
from bot.agent.tools.base import BaseAgentTool, ToolResult


class CoinGeckoTool(BaseAgentTool):
    name = "coingecko"
    source_type = "api"

    def enabled(self, context: AgentRunContext) -> bool:
        return False

    async def collect(self, context: AgentRunContext, queries: list[str] | None = None) -> ToolResult:
        return ToolResult(self.name)
