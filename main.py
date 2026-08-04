import asyncio
import logging

from watchfiles import run_process

from bot.client import start_bot
from core.db import bootstrap

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("entt.main")


async def main() -> None:
    bootstrap()
    await start_bot()


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run_process("core", "bot", "main.py", target=run)
