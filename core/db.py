import logging
import os

from config import config
from core.models import (
    Setting,
    Tag,
    Transaction,
    TransactionTag,
    Wallet,
    db,
)

logger = logging.getLogger("entt.core")

bootstrap_models = [Setting, Tag, Wallet, Transaction, TransactionTag]


def bootstrap() -> None:
    if os.path.exists(config.db_file):
        return

    logger.info("Bootstrapping...")

    with db:
        db.create_tables(bootstrap_models, safe=True)
        logger.info("Database ready at %s", config.db_file)

    defaults = {
        "finance_channel_id": str(config.finance_channel_id or ""),
        "task_channel_id": str(config.task_channel_id or ""),
        "note_channel_id": str(config.note_channel_id or ""),
    }

    for key, value in defaults.items():
        if not Setting.get_val(key):
            Setting.set_val(key, value)
            logger.info("Set default setting %s from environment", key)
