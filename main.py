import logging

from watchfiles import run_process

# from bot.client import start_bot
from core.db import bootstrap

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("entt.main")


def main() -> None:
    bootstrap()


"""
def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
"""

if __name__ == "__main__":
    run_process("core", "bot", "db", "main.py", target=main)
