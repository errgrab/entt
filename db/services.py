"""Database service layer - clean interface for bot to interact with database.

This module provides a high-level API that abstracts the underlying ORM (Peewee)
and database operations. The bot should use these services instead of directly
importing models or database functions.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from peewee import DoesNotExist, fn

from db.models import (
    Note,
    NoteTag,
    Tag,
    Task,
    Transaction,
    TransactionTag,
    TransactionType,
    Wallet,
)

SYNTAX_CHANNELS = ("finance", "notes", "tasks")

logger = logging.getLogger("entt.db.services")


# Data Transfer Objects


@dataclass(frozen=True)
class WalletInfo:
    name: str
    balance_cents: int
    transaction_count: int


@dataclass(frozen=True)
class TransactionInfo:
    id: int
    timestamp: datetime
    wallet_name: str
    type_name: str
    value_cents: int
    title: str
    description: str | None
    tags: list[str]


@dataclass(frozen=True)
class NoteInfo:
    id: int
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
    tags: list[str]


@dataclass(frozen=True)
class TaskInfo:
    id: int
    title: str
    description: str | None
    completed: bool
    deadline: datetime | None
    created_at: datetime
    completed_at: datetime | None


# Settings / Configuration


def get_channel_id(channel_type: str) -> int | None:
    channel_id = get_config(f"{channel_type}_channel_id")
    return int(channel_id) if channel_id is not None else None


def set_channel_id(channel_type: str, channel_id: int) -> None:
    set_config(f"{channel_type}_channel_id", f"{channel_id}")


def get_channel_map() -> dict[int, str]:
    """{channel_id: channel_type} for every configured syntax channel."""
    result = {}
    for channel_type in SYNTAX_CHANNELS:
        channel_id = get_channel_id(channel_type)
        if channel_id is not None:
            result[channel_id] = channel_type
    return result


def get_channel(channel_type: str) -> int | None:
    """Get channel ID for a channel type."""
    if channel_type not in SYNTAX_CHANNELS:
        raise ValueError(f"Unknown channel type: {channel_type}")
    return get_channel_id(channel_type)


def set_channel(channel_type: str, channel_id: int) -> None:
    """Set channel ID for a channel type."""
    if channel_type not in SYNTAX_CHANNELS:
        raise ValueError(f"Unknown channel type: {channel_type}")
    set_channel_id(channel_type, channel_id)


def list_channels() -> list[tuple[str, int | None]]:
    """List all channel types and their configured IDs."""
    return [(name, get_channel_id(name)) for name in SYNTAX_CHANNELS]


def get_config(key: str, default: str | None = None) -> str | None:
    from db.models import Setting

    row = Setting.get_or_none(Setting.key == key)
    return row.value if row else default


def set_config(key: str, value: str) -> None:
    from db.models import Setting

    Setting.insert(key=key, value=value).on_conflict(
        conflict_target=[Setting.key],
        update={Setting.value: value},
    ).execute()


# Wallet Operations


def list_wallets() -> list[WalletInfo]:
    """List all wallets with balances."""
    wallets = list(Wallet.select().order_by(Wallet.name))
    result = []
    for wallet in wallets:
        balance = (
            Transaction.select(fn.COALESCE(fn.SUM(Transaction.value_cents), 0))
            .where(Transaction.wallet == wallet)
            .scalar()
        )
        balance = int(balance or 0)
        tx_count = Transaction.select().where(Transaction.wallet == wallet).count()
        result.append(WalletInfo(wallet.name, balance, tx_count))
    return result


def get_wallet(name: str) -> Wallet | None:
    """Get wallet by name."""
    try:
        return Wallet.get(Wallet.name == name)
    except DoesNotExist:
        return None


def create_wallet(name: str) -> Wallet:
    """Create a new wallet."""
    return Wallet.create(name=name)


def delete_wallet(name: str) -> bool:
    """Delete a wallet by name."""
    wallet = get_wallet(name)
    if wallet is None:
        return False
    wallet.delete_instance(recursive=True)
    return True


def wallet_balance(wallet: Wallet) -> int:
    """Get wallet balance in cents."""
    total = (
        Transaction.select(fn.COALESCE(fn.SUM(Transaction.value_cents), 0))
        .where(Transaction.wallet == wallet)
        .scalar()
    )
    return int(total or 0)


def wallet_tx_count(wallet: Wallet) -> int:
    """Get wallet transaction count."""
    return Transaction.select().where(Transaction.wallet == wallet).count()


def adjust_wallet(name: str, amount_cents: int, reason: str | None = None) -> Wallet:
    """Adjust wallet balance by creating an adjustment transaction."""
    wallet, _ = Wallet.get_or_create(name=name)
    adjustment_type, _ = TransactionType.get_or_create(name="adjustment")
    Transaction.create(
        title=f"Wallet adjustment: {wallet.name}",
        description=reason,
        value_cents=amount_cents,
        wallet=wallet,
        ts_type=adjustment_type,
    )
    return wallet


def transfer_between_wallets(
    from_name: str, to_name: str, amount_cents: int, reason: str | None = None
) -> tuple[Wallet, Wallet]:
    """Transfer amount between wallets."""
    if from_name == to_name:
        raise ValueError("Transfer wallets must be different.")
    if amount_cents <= 0:
        raise ValueError("Transfer amount must be positive.")

    source_wallet, _ = Wallet.get_or_create(name=from_name)
    target_wallet, _ = Wallet.get_or_create(name=to_name)
    out_type, _ = TransactionType.get_or_create(name="transfer_out")
    in_type, _ = TransactionType.get_or_create(name="transfer_in")

    Transaction.create(
        title=f"Transfer to {target_wallet.name}",
        description=reason,
        value_cents=-amount_cents,
        wallet=source_wallet,
        ts_type=out_type,
    )
    Transaction.create(
        title=f"Transfer from {source_wallet.name}",
        description=reason,
        value_cents=amount_cents,
        wallet=target_wallet,
        ts_type=in_type,
    )
    return source_wallet, target_wallet


def _wallet_balance(wallet: Wallet) -> int:
    """Get wallet balance in cents."""
    total = (
        Transaction.select(fn.COALESCE(fn.SUM(Transaction.value_cents), 0))
        .where(Transaction.wallet == wallet)
        .scalar()
    )
    return int(total or 0)


def _wallet_tx_count(wallet: Wallet) -> int:
    """Get wallet transaction count."""
    return Transaction.select().where(Transaction.wallet == wallet).count()


# Transaction Operations


def list_transactions(
    wallet: str | None = None,
    tags: list[str] | None = None,
    contains: str | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
    limit: int = 10,
    expense_only: bool = False,
) -> list[TransactionInfo]:
    """List transactions with filters."""
    query = (
        Transaction.select(Transaction, Wallet, TransactionType)
        .join(Wallet)
        .switch(Transaction)
        .join(TransactionType)
    )

    if wallet:
        query = query.where(Wallet.name == wallet)

    if contains:
        query = query.where(
            (Transaction.title.contains(contains))
            | (Transaction.description.contains(contains))
        )

    if after:
        query = query.where(Transaction.timestamp >= after)

    if before:
        query = query.where(Transaction.timestamp <= before)

    if tags:
        query = (
            query.switch(Transaction)
            .join(TransactionTag)
            .join(Tag)
            .where(Tag.name.in_(tags))
            .distinct()
        )

    if expense_only:
        query = query.where(
            (TransactionType.name == "expense") | (Transaction.value_cents < 0)
        )

    rows = list(query.order_by(Transaction.timestamp.desc()).limit(limit))

    result = []
    for tx in rows:
        tag_names = [
            row.tag.name
            for row in TransactionTag.select(TransactionTag, Tag)
            .join(Tag)
            .where(TransactionTag.transaction == tx)
        ]
        result.append(
            TransactionInfo(
                id=tx.id,
                timestamp=tx.timestamp,
                wallet_name=tx.wallet.name,
                type_name=tx.ts_type.name,
                value_cents=tx.value_cents,
                title=tx.title,
                description=tx.description,
                tags=tag_names,
            )
        )
    return result


def create_transaction(
    title: str,
    value_cents: int,
    wallet_name: str,
    type_name: str | None = None,
    description: str | None = None,
    tag_names: list[str] | None = None,
) -> Transaction:
    """Create a new transaction."""
    wallet, _ = Wallet.get_or_create(name=wallet_name)
    if type_name is None:
        type_name = "income" if value_cents >= 0 else "expense"
    ts_type, _ = TransactionType.get_or_create(name=type_name)

    tx = Transaction.create(
        title=title,
        description=description,
        value_cents=value_cents,
        wallet=wallet,
        ts_type=ts_type,
    )

    if tag_names:
        for name in tag_names:
            tag, _ = Tag.get_or_create(name=name)
            TransactionTag.create(transaction=tx, tag=tag)

    return tx


def get_expense_summary(
    wallet: str | None = None,
    tags: list[str] | None = None,
    contains: str | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
) -> tuple[int, int]:
    """Get expense summary (count and total spent in cents)."""
    query = (
        Transaction.select(fn.COALESCE(fn.SUM(Transaction.value_cents), 0))
        .join(Wallet)
        .switch(Transaction)
        .join(TransactionType)
        .where((TransactionType.name == "expense") | (Transaction.value_cents < 0))
    )

    if wallet:
        query = query.where(Wallet.name == wallet)

    if contains:
        query = query.where(
            (Transaction.title.contains(contains))
            | (Transaction.description.contains(contains))
        )

    if after:
        query = query.where(Transaction.timestamp >= after)

    if before:
        query = query.where(Transaction.timestamp <= before)

    if tags:
        query = (
            query.switch(Transaction)
            .join(TransactionTag)
            .join(Tag)
            .where(Tag.name.in_(tags))
            .distinct()
        )

    total = int(query.scalar() or 0)
    count = query.count()
    return count, abs(total)


# Tag Operations


def list_tags() -> list[str]:
    """List all tag names."""
    return [row.name for row in Tag.select().order_by(Tag.name)]


def create_tag(name: str) -> Tag:
    """Create a new tag."""
    return Tag.create(name=name)


def delete_tag(name: str) -> bool:
    """Delete a tag by name."""
    try:
        Tag.get(Tag.name == name).delete_instance(recursive=True)
        return True
    except DoesNotExist:
        return False


# Transaction Type Operations


def list_types() -> list[str]:
    """List all transaction type names."""
    return [row.name for row in TransactionType.select().order_by(TransactionType.name)]


def create_type(name: str) -> TransactionType:
    """Create a new transaction type."""
    return TransactionType.create(name=name)


def delete_type(name: str) -> bool:
    """Delete a transaction type by name."""
    try:
        TransactionType.get(TransactionType.name == name).delete_instance(
            recursive=True
        )
        return True
    except DoesNotExist:
        return False


# Note Operations


def list_notes(limit: int = 10) -> list[NoteInfo]:
    """List recent notes."""
    notes = list(Note.select().order_by(Note.created_at.desc()).limit(limit))
    note_tags = (
        NoteTag.select(NoteTag, Tag, Note)
        .join(Note)
        .join(Tag)
        .where(NoteTag.note.in_(notes))
    )
    tags_by_note: dict[int, list[str]] = defaultdict(list)
    for note_tag in note_tags:
        tags_by_note[note_tag.note.id].append(note_tag.tag.name)

    return [
        NoteInfo(
            id=note.id,
            title=note.title,
            content=note.content,
            created_at=note.created_at,
            updated_at=note.updated_at,
            tags=tags_by_note.get(note.id, []),
        )
        for note in notes
    ]


def create_note(title: str, content: str) -> Note:
    """Create a new note."""
    return Note.create(title=title, content=content)


# Task Operations


def list_tasks(
    completed: bool | None = None,
    limit: int = 10,
) -> list[TaskInfo]:
    """List tasks."""
    query = Task.select()
    if completed is not None:
        query = query.where(Task.completed == completed)
    rows = list(query.order_by(Task.created_at.desc()).limit(limit))
    return [
        TaskInfo(
            id=task.id,
            title=task.title,
            description=task.description,
            completed=task.completed,
            deadline=task.deadline,
            created_at=task.created_at,
            completed_at=task.completed_at,
        )
        for task in rows
    ]


def create_task(title: str, deadline: datetime | None = None) -> Task:
    """Create a new task."""
    return Task.create(title=title, deadline=deadline)
