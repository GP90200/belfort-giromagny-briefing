"""Point d'entrée du worker : enregistre le workflow et démarre le polling."""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import mistralai.workflows as workflows

from src.workflows.briefing import BelfortBriefingWorkflow


async def main() -> None:
    await workflows.run_worker([BelfortBriefingWorkflow])


if __name__ == "__main__":
    asyncio.run(main())
