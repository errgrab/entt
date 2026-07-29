import asyncio
import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path
from db.database import bootstrap
from bot.client import start_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger=logging.getLogger("entt.main")

ROOT = Path(__file__).resolve().parent


def _watched_paths() -> list[Path]:
    paths = [ROOT / "main.py", ROOT / "config.py", ROOT / ".env"]
    for name in ("api", "bot", "db"):
        folder = ROOT / name
        if folder.exists():
            paths.extend(folder.rglob("*.py"))
    return paths


def _snapshot() -> dict[str, float]:
    snapshot: dict[str, float] = {}
    for path in _watched_paths():
        if path.exists():
            snapshot[str(path)] = path.stat().st_mtime
    return snapshot

async def main():
    bootstrap()
    await start_bot()


def run_once() -> int:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down.")
    return 0


def run_with_reload() -> int:
    while True:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"], cwd=str(ROOT))
        previous_snapshot = _snapshot()

        try:
            while True:
                exit_code = process.poll()
                if exit_code is not None:
                    return exit_code

                time.sleep(0.5)
                current_snapshot = _snapshot()
                if current_snapshot != previous_snapshot:
                    logger.info("Change detected, restarting...")
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    break
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            logger.info("Shutting down.")
            return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reload", action="store_true", help="Restart the bot when source files change.")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.reload:
        raise SystemExit(run_with_reload())

    raise SystemExit(run_once())
