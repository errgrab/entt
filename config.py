import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    db_file: str = os.getenv("DB_FILE", "entt.db")
    discord_token: str | None = os.getenv("DISCORD_TOKEN")
    finance_channel_id: int | None = int(os.getenv("FINANCE_CHANNEL", "0"))
    note_channel_id: int | None = int(os.getenv("NOTE_CHANNEL", "0"))
    task_channel_id: int | None = int(os.getenv("TASK_CHANNEL", "0"))
    api_host: str = os.getenv("API_HOST", "127.0.0.1")
    api_port: int = int(os.getenv("API_PORT", "8000"))
    command_prefix: str = os.getenv("ENTT_PREFIX", "!")

config = Config()

