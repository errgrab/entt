import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Self

from peewee import (
    AutoField,
    CharField,
    DoesNotExist,
    ForeignKeyField,
    IntegerField,
    ManyToManyField,
    Model,
    SqliteDatabase,
    TextField,
    TimestampField,
    fn,
)

from config import config

logger = logging.getLogger("entt.core")


db = SqliteDatabase(
    config.db_file,
    pragmas={
        "journal_mode": "wal",
        "foreign_keys": 1,
    },
)


class BaseModel(Model):
    class Meta:
        database = db


class Setting(BaseModel):
    key = CharField(primary_key=True)
    value = TextField()

    @classmethod
    def get_val(cls, key: str, default: str | None = None) -> str:
        """Fetch a setting value by key, returning default if not found."""
        setting = cls.get_or_none(cls.key == key)
        return setting.value if setting else default if default else ""

    @classmethod
    def set_val(cls, key: str, value: str) -> None:
        """Create or update a setting key-value pair."""
        cls.insert(key=key, value=str(value)).on_conflict_replace().execute()


class Tag(BaseModel):
    id = AutoField(primary_key=True)
    name = CharField(max_length=256, unique=True)

    @classmethod
    def get_or_create_clean(cls, name: str) -> Self:
        """Normalize tag names (lowercase & stripped) before fetching/creating."""
        clean_name = name.strip().lower()
        tag, _ = cls.get_or_create(name=clean_name)
        return tag


class Wallet(BaseModel):
    id = AutoField(primary_key=True)
    name = CharField(max_length=256, unique=True)
    desc = TextField(null=True)
    balance_cents = IntegerField()

    @property
    def balance(self) -> Decimal:
        """Get balance formated as Decimal (e.g., 15000 -> 150.00)."""
        return Decimal(self.balance_cents) / Decimal(100)

    @balance.setter
    def balance(self, amount: float | Decimal | str) -> None:
        """Set balance directly with monetary value."""
        self.balance_cents = round(Decimal(str(amount)) * 100)

    def sync_balance(self) -> Decimal:
        """Recalculate balance directly from transactions ('income' minus 'outcome')."""
        income = (
            Transaction.select(fn.COALESCE(fn.SUM(Transaction.value_cents), 0))
            .where((Transaction.wallet == self) & (Transaction.tx_type == "income"))
            .scalar()
        )
        outcome = (
            Transaction.select(fn.COALESCE(fn.SUM(Transaction.value_cents), 0))
            .where((Transaction.wallet == self) & (Transaction.tx_type == "outcome"))
            .scalar()
        )
        self.balance_cents = income - outcome
        self.save()
        return self.balance


class Transaction(BaseModel):
    id = AutoField(primary_key=True)
    name = CharField(max_length=256)
    desc = TextField(null=True)
    value_cents = IntegerField()
    wallet = ForeignKeyField(Wallet, backref="transactions", on_delete="CASCADE")
    tx_type = CharField(max_length=64, default="outcome")
    method = CharField(max_length=64, default="money")
    tags = ManyToManyField(Tag, backref="transactions")
    created_at = TimestampField(default=datetime.now, utc=True)
    updated_at = TimestampField(default=datetime.now, utc=True)

    @property
    def value(self) -> Decimal:
        """Monetary value formatted as a Decimal."""
        return Decimal(self.value_cents) / Decimal(100)

    @value.setter
    def value(self, amount: float | Decimal | str) -> None:
        """Allows setting tx.value direclty as a Decimal."""
        self.value_cents = round(Decimal(str(amount)) * 100)

    def save(self, *args, **kwargs):
        self.updated_at = datetime.now(tz=timezone.utc)
        return super().save(*args, **kwargs)

    @property
    def tag_names(self) -> list[str]:
        """Returns a list of string tag names for this transaction."""
        return [tag.name for tag in self.tags]

    def add_tag(self, tag_name: str):
        """Attach a tag by string name."""
        tag = Tag.get_or_create_clean(tag_name)
        self.tags.add(tag)

    def remove_tag(self, tag_name: str):
        """Detach a tag by string name."""
        clean_name = tag_name.strip().lower()
        try:
            tag = Tag.get(Tag.name == clean_name)
            self.tags.remove(tag)
        except DoesNotExist:
            pass

    @classmethod
    def filter_by_tag(cls, tag_name: str, wallet_id: int | None = None):
        """Get transactions linked to a specific tag."""
        clean_name = tag_name.strip().lower()
        query = (
            cls.select().join(TransactionTag).join(Tag).where(Tag.name == clean_name)
        )
        if wallet_id:
            query = query.where(cls.wallet == wallet_id)
        return query.order_by(cls.created_at.desc())

    @classmethod
    def get_summary(
        cls,
        wallet_id: int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, Decimal]:
        """Calculates total income, outcome, and net balance over a date range."""
        query = cls.select()
        if wallet_id:
            query = query.where(cls.wallet == wallet_id)
        if start_date:
            query = query.where(cls.created_at >= start_date)
        if end_date:
            query = query.where(cls.created_at <= end_date)

        income = (
            query.select(fn.COALESCE(fn.SUM(cls.value_cents), 0))
            .where(cls.tx_type == "income")
            .scalar()
        )
        outcome = (
            query.select(fn.COALESCE(fn.SUM(cls.value_cents), 0))
            .where(cls.tx_type == "outcome")
            .scalar()
        )

        return {
            "income": Decimal(income) / Decimal(100),
            "outcome": Decimal(outcome) / Decimal(100),
            "net": Decimal(income - outcome) / Decimal(100),
        }


TransactionTag = Transaction.tags.get_through_model()


def bootstrap() -> None:
    if os.path.exists(config.db_file):
        return

    logger.info("Bootstrapping...")

    bootstrap_models = [Setting, Tag, Wallet, Transaction, TransactionTag]

    with db:
        db.create_tables(bootstrap_models, safe=True)
        logger.info("Database ready at %s", config.db_file)

    defaults = {
        "finance_channel_id": str(config.finance_channel_id or ""),
        "task_channel_id": str(config.task_channel_id or ""),
        "note_channel_id": str(config.note_channel_id or ""),
        "default_method": str(config.default_method or "credit"),
    }

    for key, value in defaults.items():
        if not Setting.get_val(key):
            Setting.set_val(key, value)
            logger.info("Set default setting %s from environment", key)
