import logging
import shlex
from typing import cast
from dateutil import parser as dateparser
from peewee import IntegrityError, DoesNotExist
from peewee import fn
from db.models import Tag, Transaction, TransactionTag, TransactionType, Wallet
from db.database import (
    SYNTAX_CHANNELS,
    get_channel_id,
    get_setting,
    set_channel_id,
    set_setting,
)
from bot.money import format_cents, parse_cents

logger = logging.getLogger("entt.commands")


class CommandError(Exception):
    """User-facing command error (bad args, not found, etc.)."""


def _split(content: str) -> list[str]:
    try:
        return shlex.split(content)
    except ValueError as e:
        raise CommandError(f"Couldn't parse that command: {e}")


def _crud_handler(model, label: str):
    """Factory for the repeated add/remove/list pattern (tag, type, wallet)."""

    async def handler(args: list[str]) -> str:
        if not args:
            raise CommandError(f"Usage: `!{label} add|remove|list <name>`")
        action, *rest = args

        if action == "list":
            names = [row.name for row in model.select()]
            return f"{label.capitalize()}s: " + (", ".join(names) if names else "(none yet)")

        if action == "add":
            if not rest:
                raise CommandError(f"Usage: `!{label} add <name>`")
            try:
                model.create(name=rest[0])
            except IntegrityError:
                raise CommandError(f"{label.capitalize()} `{rest[0]}` already exists.")
            return f"{label.capitalize()} `{rest[0]}` created."

        if action == "remove":
            if not rest:
                raise CommandError(f"Usage: `!{label} remove <name>`")
            try:
                model.get(model.name == rest[0]).delete_instance(recursive=True)
            except DoesNotExist:
                raise CommandError(f"No {label} named `{rest[0]}`.")
            return f"{label.capitalize()} `{rest[0]}` removed."

        raise CommandError("Unknown action. Use add, remove, or list.")

    return handler


async def cmd_ping(args: list[str]) -> str:
    return "pong!"


async def cmd_config(args: list[str]) -> str:
    if not args:
        raise CommandError("Usage: `!config get <key>` or `!config set <key> <value>`")
    action = args[0]

    if action == "get":
        if len(args) < 2:
            raise CommandError("Usage: `!config get <key>`")
        value = get_setting(args[1])
        return f"`{args[1]}` = `{value}`" if value else f"`{args[1]}` is not set."

    if action == "set":
        if len(args) < 3:
            raise CommandError("Usage: `!config set <key> <value>`")
        key, value = args[1], " ".join(args[2:])
        set_setting(key, value)
        return f"`{key}` set."

    raise CommandError("Unknown action. Use get or set.")


async def cmd_channel(args: list[str]) -> str:
    if not args:
        raise CommandError("Usage: `!channel list` or `!channel set <finance|notes|tasks> <#channel>`")
    action = args[0]

    if action == "list":
        lines = [
            f"{name}: {'<#%d>' % cid if (cid := get_channel_id(name)) else '(not set)'}"
            for name in SYNTAX_CHANNELS
        ]
        return "\n".join(lines)

    if action == "set":
        if len(args) < 3:
            raise CommandError("Usage: `!channel set <finance|notes|tasks> <#channel or id>`")
        name, raw_id = args[1], args[2].strip("<#>")
        if name not in SYNTAX_CHANNELS:
            raise CommandError(f"Channel type must be one of: {', '.join(SYNTAX_CHANNELS)}.")
        try:
            channel_id = int(raw_id)
        except ValueError:
            raise CommandError("Channel must be a mention like #finance or a numeric id.")
        set_channel_id(name, channel_id)
        return f"Channel `{name}` set to <#{channel_id}>."

    raise CommandError("Unknown action. Use set or list.")


def _wallet_balance(wallet: Wallet) -> int:
    total = (
        Transaction.select(fn.COALESCE(fn.SUM(Transaction.value_cents), 0))
        .where(Transaction.wallet == wallet)
        .scalar()
    )
    return int(total or 0)


def _wallet_summary(wallet: Wallet) -> str:
    balance = _wallet_balance(wallet)
    tx_count = Transaction.select().where(Transaction.wallet == wallet).count()
    return f"- {wallet.name}: {format_cents(balance)} ({tx_count} tx)"


def _get_wallet(name: str) -> Wallet:
    try:
        return Wallet.get(Wallet.name == name)
    except DoesNotExist:
        raise CommandError(f"No wallet named `{name}`.")


def _parse_amount(raw_amount: str) -> int:
    try:
        amount_cents = parse_cents(raw_amount)
    except ValueError:
        raise CommandError(f"Couldn't parse value `{raw_amount}`.")
    return amount_cents


async def cmd_wallet(args: list[str]) -> str:
    if not args or args[0] == "list":
        wallets = list(Wallet.select().order_by(Wallet.name))
        if not wallets:
            return "Wallets: (none yet)"
        return "Wallets:\n" + "\n".join(_wallet_summary(wallet) for wallet in wallets)

    action = args[0].lower()

    if action == "add":
        if len(args) < 2:
            raise CommandError("Usage: `!wallet add <name>`")
        name = args[1]
        try:
            Wallet.create(name=name)
        except IntegrityError:
            raise CommandError(f"Wallet `{name}` already exists.")
        return f"Wallet `{name}` created."

    if action == "remove":
        if len(args) < 2:
            raise CommandError("Usage: `!wallet remove <name>`")
        name = args[1]
        wallet = _get_wallet(name)
        wallet.delete_instance(recursive=True)
        return f"Wallet `{name}` removed."

    if action in {"show", "balance"}:
        if len(args) < 2:
            raise CommandError("Usage: `!wallet show <name>`")
        name = args[1]
        wallet = _get_wallet(name)
        return _wallet_summary(wallet)

    if action == "adjust":
        if len(args) < 3:
            raise CommandError("Usage: `!wallet adjust <name> <amount> [reason]`")
        name, raw_amount = args[1], args[2]
        reason = " ".join(args[3:]).strip() or None
        amount_cents = _parse_amount(raw_amount)
        if amount_cents == 0:
            raise CommandError("Adjustment amount can't be zero.")
        wallet, _ = Wallet.get_or_create(name=name)
        adjustment_type, _ = TransactionType.get_or_create(name="adjustment")
        Transaction.create(
            title=f"Wallet adjustment: {wallet.name}",
            description=reason,
            value_cents=amount_cents,
            wallet=wallet,
            ts_type=adjustment_type,
        )
        return f"Wallet `{wallet.name}` adjusted by {format_cents(amount_cents)}."

    if action == "transfer":
        if len(args) < 4:
            raise CommandError("Usage: `!wallet transfer <from> <to> <amount> [reason]`")
        from_name, to_name, raw_amount = args[1], args[2], args[3]
        reason = " ".join(args[4:]).strip() or None
        if from_name == to_name:
            raise CommandError("Transfer wallets must be different.")
        amount_cents = _parse_amount(raw_amount)
        if amount_cents <= 0:
            raise CommandError("Transfer amount must be positive.")

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
        return (
            f"Transferred {format_cents(amount_cents)} from `{source_wallet.name}` to `{target_wallet.name}`."
        )

    raise CommandError(
        "Unknown action. Use list, add, remove, show, balance, adjust, or transfer."
    )


def _parse_date(raw: str):
    try:
        return dateparser.parse(raw, fuzzy=True, dayfirst=True)
    except (ValueError, OverflowError):
        raise CommandError(f"Couldn't understand date `{raw}`.")


def _parse_expense_filters(args: list[str]) -> tuple[str, dict[str, list[str]]]:
    if args and args[0].lower() in {"list", "summary"}:
        action = args[0].lower()
        args = args[1:]
    else:
        action = "list"

    filters: dict[str, list[str]] = {}
    for raw in args:
        if "=" not in raw:
            raise CommandError(
                "Expense filters must look like `wallet=main tag=food contains=groceries`.")
        key, value = raw.split("=", 1)
        key = key.lower().strip()
        value = value.strip()
        if not key or not value:
            raise CommandError(
                "Expense filters must look like `wallet=main tag=food contains=groceries`.")
        filters.setdefault(key, []).append(value)

    return action, filters


def _expense_query(filters: dict[str, list[str]]):
    query = (
        Transaction.select(Transaction, Wallet, TransactionType)
        .join(Wallet)
        .switch(Transaction)
        .join(TransactionType)
        .where(
            (TransactionType.name == "expense")
            | (Transaction.value_cents < 0)
        )
    )

    wallet_name = filters.get("wallet", [None])[0]
    if wallet_name:
        query = query.where(Wallet.name == wallet_name)

    contains_terms = filters.get("contains", [])
    if contains_terms:
        search_text = " ".join(contains_terms)
        query = query.where(
            (Transaction.title.contains(search_text))
            | (Transaction.description.contains(search_text))
        )

    after_terms = filters.get("after", [])
    if after_terms:
        query = query.where(Transaction.timestamp >= _parse_date(after_terms[0]))

    before_terms = filters.get("before", [])
    if before_terms:
        query = query.where(Transaction.timestamp <= _parse_date(before_terms[0]))

    tag_names = filters.get("tag", [])
    if tag_names:
        query = (
            query.switch(Transaction)
            .join(TransactionTag)
            .join(Tag)
            .where(Tag.name.in_(tag_names))
            .distinct()
        )

    return query


def _format_transaction(tx: Transaction) -> str:
    tags = [
        row.tag.name
        for row in TransactionTag.select(TransactionTag, Tag)
        .join(Tag)
        .where(TransactionTag.transaction == tx)
    ]
    tag_str = f" {' '.join(f'#{tag}' for tag in tags)}" if tags else ""
    description = f" - {tx.description}" if tx.description else ""
    return (
        f"- {tx.timestamp:%Y-%m-%d %H:%M} | {tx.wallet.name} | "
        f"{format_cents(cast(int, tx.value_cents))} | {tx.title}{description}{tag_str}"
    )


async def cmd_expense(args: list[str]) -> str:
    action, filters = _parse_expense_filters(args)
    query = _expense_query(filters)

    if action == "summary":
        total = query.select(fn.COALESCE(fn.SUM(Transaction.value_cents), 0)).scalar() or 0
        count = query.count()
        spent = abs(int(total))
        return f"Expenses: {count} transaction(s), total {format_cents(spent)}."

    limit_values = filters.get("limit", ["10"])
    try:
        limit = int(limit_values[0])
    except ValueError:
        raise CommandError("`limit` must be a number.")
    if limit <= 0:
        raise CommandError("`limit` must be greater than zero.")

    rows = list(query.order_by(Transaction.timestamp.desc()).limit(limit))
    if not rows:
        return "No matching expenses found."

    header_bits = []
    if filters.get("wallet"):
        header_bits.append(f"wallet={filters['wallet'][0]}")
    if filters.get("tag"):
        header_bits.append(f"tag={', '.join(filters['tag'])}")
    if filters.get("contains"):
        header_bits.append(f"contains={ ' '.join(filters['contains']) }")
    header = f"Expenses ({', '.join(header_bits)})" if header_bits else "Expenses"
    return header + "\n" + "\n".join(_format_transaction(tx) for tx in rows)


async def cmd_help(args: list[str]) -> str:
    return (
        "**Prefix commands (work anywhere)**\n"
        "`!ping`\n"
        "`!tag add|remove|list <name>`\n"
        "`!type add|remove|list <name>`\n"
        "`!wallet list|show|add|remove|adjust|transfer ...`\n"
        "`!expense [list|summary] wallet=<name> tag=<tag> contains=<text> after=<date> before=<date> limit=<n>`\n"
        "`!channel list` / `!channel set <finance|notes|tasks> <#channel>`\n"
        "`!config get|set <key> [value]`\n\n"
        "**Channel syntax (no prefix, in the configured channel)**\n"
        "`finance`: `Title: R$Value @wallet #tag1 #tag2 Description`\n"
        "`notes`: `# Title` then content on following lines\n"
        "`tasks`: `Task description ?deadline?`"
    )


COMMANDS = {
    "ping": cmd_ping,
    "tag": _crud_handler(Tag, "tag"),
    "type": _crud_handler(TransactionType, "type"),
    "wallet": cmd_wallet,
    "expense": cmd_expense,
    "transactions": cmd_expense,
    "tx": cmd_expense,
    "config": cmd_config,
    "channel": cmd_channel,
    "help": cmd_help,
}


async def dispatch(content: str, prefix: str) -> str:
    raw = content[len(prefix):].strip()
    if not raw:
        raise CommandError("Empty command. Try `!help`.")

    parts = _split(raw)
    name, args = parts[0].lower(), parts[1:]

    handler = COMMANDS.get(name)
    if handler is None:
        raise CommandError(f"Unknown command `{name}`. Try `!help`.")

    return await handler(args)