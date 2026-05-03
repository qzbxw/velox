from __future__ import annotations

from bot.agent.context import FinalAgentReport
from bot.database import db


class RunStore:
    async def save(self, report: FinalAgentReport, user_id=None, started_at=None, input_hash: str | None = None) -> None:
        doc = report.to_dict()
        doc["user_id"] = user_id
        doc["started_at"] = started_at
        doc["input_hash"] = input_hash
        await db.save_agent_run(doc)
