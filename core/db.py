import logging

from peewee import Model, SqliteDatabase

from config import config

logger = logging.getLogger("entt.core")

db = SqliteDatabase(
    config.db_file,
    pragmas={"journal_mode": "wal", "foreign_keys": 1},
)


class BaseModel(Model):
    class Meta:
        database = db


def bootstrap() -> None:
    from core.analytics import ANALYTICS_MODELS

    logger.info("Ensuring database schema is ready...")
    with db:
        db.create_tables(ANALYTICS_MODELS, safe=True)
        logger.info("Database ready at %s", config.db_file)
