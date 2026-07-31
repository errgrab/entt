import logging
import os

from peewee import SqliteDatabase

from config import config
from db.services import get_config, set_config

logger = logging.getLogger("entt.db")

db = SqliteDatabase(
    config.db_file,
    pragmas={
        "journal_mode": "wal",
        "foreign_keys": 1,
    },
)


def _bootstrap_models():
    from db.models import (
        Note,
        NoteTag,
        Setting,
        Tag,
        Task,
        Transaction,
        TransactionTag,
        TransactionType,
        Wallet,
    )

    return [
        Setting,
        Wallet,
        Tag,
        TransactionType,
        Transaction,
        Task,
        Note,
        TransactionTag,
        NoteTag,
    ]


def _seed_default_settings() -> None:
    defaults = {
        "finance_channel_id": str(config.finance_channel_id or ""),
        "task_channel_id": str(config.task_channel_id or ""),
        "note_channel_id": str(config.note_channel_id or ""),
    }

    for key, value in defaults.items():
        if not get_config(key):
            set_config(key, value)
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
