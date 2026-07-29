import os
import logging
from peewee import SqliteDatabase
from config import config


logger = logging.getLogger("entt.db")

SYNTAX_CHANNELS = ("finance", "notes", "tasks")

_CHANNEL_SETTING_KEYS = {
    "finance": "finance_channel_id",
    "notes": "note_channel_id",
    "tasks": "task_channel_id",
}

db = SqliteDatabase(
    config.db_file,
    pragmas={
        "journal_mode": "wal",
        "foreign_keys": 1,
    },
)


def get_setting(key: str, default: str | None = None) -> str | None:
    from db.models import Setting
    row = Setting.get_or_none(Setting.key == key)
    return row.value if row else default


def set_setting(key: str, value: str) -> None:
    from db.models import Setting
    Setting.insert(key=key, value=value).on_conflict(
        conflict_target=[Setting.key],
        update={Setting.value: value},
    ).execute()


def get_channel_id(name: str) -> int | None:
    key = _CHANNEL_SETTING_KEYS.get(name)
    if key is None:
        raise KeyError(f"Unknown channel type: {name}")

    value = get_setting(key)
    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid channel id stored for %s: %r", key, value)
        return None


def set_channel_id(name: str, channel_id: int) -> None:
    key = _CHANNEL_SETTING_KEYS.get(name)
    if key is None:
        raise KeyError(f"Unknown channel type: {name}")

    set_setting(key, str(channel_id))


def get_channel_map() -> dict[int, str]:
    """{channel_id: channel_type} for every configured syntax channel."""
    result = {}
    for channel_type in SYNTAX_CHANNELS:
        channel_id = get_channel_id(channel_type)
        if channel_id is not None:
            result[channel_id] = channel_type
    return result


def _bootstrap_models():
    from db.models import (
        Setting, Wallet, Tag, TransactionType, Transaction,
        Task, Note, TransactionTag, NoteTag,
    )

    return [
        Setting, Wallet, Tag, TransactionType, Transaction,
        Task, Note, TransactionTag, NoteTag,
    ]


def _seed_default_settings() -> None:
    defaults = {
        "discord_token": config.discord_token or "",
        "finance_channel_id": str(config.finance_channel_id or ""),
        "task_channel_id": str(config.task_channel_id or ""),
        "note_channel_id": str(config.note_channel_id or ""),
    }

    for key, value in defaults.items():
        if not get_setting(key):
            set_setting(key, value)
            logger.info("Set default setting %s from environment", key)


def _create_schema() -> None:
    with db:
        db.create_tables(_bootstrap_models(), safe=True)
        logger.info("Database ready at %s", config.db_file)


def bootstrap() -> None:
    if os.path.exists(config.db_file):
        return

    logger.info("Bootstrapping...")
    _create_schema()
    _seed_default_settings()
