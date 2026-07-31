"""Bot command handlers - uses db.services for all database operations."""

import logging
import shlex

from dateutil import parser as dateparser

from db import services
from db.services import SYNTAX_CHANNELS

logger = logging.getLogger("entt.commands")


def parse_cents(raw: str) -> int:
    normalized = raw.strip().replace("R$", "").replace(" ", "")
    if not normalized:
        raise ValueError("Empty money value.")

    sign = 1
    if normalized[0] in "+-":
        sign = -1 if normalized[0] == "-" else 1
        normalized = normalized[1:]

    if not normalized:
        raise ValueError("Empty money value.")

    if "," in normalized:
        whole, fraction = normalized.split(",", 1)
        if not whole or not fraction or not fraction.isdigit() or len(fraction) > 2:
            raise ValueError(f"Couldn't parse value `{raw}`.")
        if not whole.replace(".", "").isdigit():
            raise ValueError(f"Couldn't parse value `{raw}`.")

        whole_value = int(whole.replace(".", ""))
        cents = int(fraction.ljust(2, "0"))
        return sign * (whole_value * 100 + cents)

    if not normalized.replace(".", "").isdigit():
        raise ValueError(f"Couldn't parse value `{raw}`.")

    whole_value = int(normalized.replace(".", ""))
    return sign * whole_value * 100


def format_cents(value_cents: int) -> str:
    sign = "-" if value_cents < 0 else ""
    absolute = abs(value_cents)
    whole, fraction = divmod(absolute, 100)
    whole_str = f"{whole:,}".replace(",", ".")
    return f"R${sign}{whole_str},{fraction:02d}"


class CommandError(Exception):
    """User-facing command error (bad args, not found, etc.)."""


def _split(content: str) -> list[str]:
    try:
        return shlex.split(content)
    except ValueError as e:
        raise CommandError(f"Couldn't parse that command: {e}")


async def cmd_ping(args: list[str]) -> str:
    return "pong!"


async def cmd_config(args: list[str]) -> str:
    if not args:
        raise CommandError("Usage: `!config get <key>` or `!config set <key> <value>`")
    action = args[0]

    if action == "get":
        if len(args) < 2:
            raise CommandError("Usage: `!config get <key>`")
        value = services.get_config(args[1])
        return f"`{args[1]}` = `{value}`" if value else f"`{args[1]}` is not set."

    if action == "set":
        if len(args) < 3:
            raise CommandError("Usage: `!config set <key> <value>`")
        key, value = args[1], " ".join(args[2:])
        services.set_config(key, value)
        return f"`{key}` set."

    raise CommandError("Unknown action. Use get or set.")


async def cmd_channel(args: list[str]) -> str:
    if not args:
        raise CommandError(
            "Usage: `!channel list` or `!channel set <finance|notes|tasks> <#channel>`"
        )
    action = args[0]

    if action == "list":
        lines = [
            f"{name}: {f'{cid}' if (cid := services.get_channel(name)) else '(not set)'}"
            for name in SYNTAX_CHANNELS
        ]
        return "\n".join(lines)

    if action == "set":
        if len(args) < 3:
            raise CommandError(
                "Usage: `!channel set <finance|notes|tasks> <#channel or id>`"
            )
        name, raw_id = args[1], args[2].strip("<#>")
        if name not in SYNTAX_CHANNELS:
            raise CommandError(
                f"Channel type must be one of: {', '.join(SYNTAX_CHANNELS)}."
            )
        try:
            channel_id = int(raw_id)
        except ValueError:
            raise CommandError(
                "Channel must be a mention like #finance or a numeric id."
            )
        services.set_channel(name, channel_id)
        return f"Channel `{name}` set to <#{channel_id}>."

    raise CommandError("Unknown action. Use set or list.")


def _format_wallet(wallet: services.WalletInfo) -> str:
    return f"- {wallet.name}: {format_cents(wallet.balance_cents)} ({wallet.transaction_count} tx)"


async def cmd_wallet(args: list[str]) -> str:
    if not args or args[0] == "list":
        wallets = services.list_wallets()
        if not wallets:
            return "Wallets: (none yet)"
        return "Wallets:\n" + "\n".join(_format_wallet(wallet) for wallet in wallets)

    action = args[0].lower()

    if action == "add":
        if len(args) < 2:
            raise CommandError("Usage: `!wallet add <name>`")
        name = args[1]
        try:
            services.create_wallet(name)
        except Exception:
            raise CommandError(f"Wallet `{name}` already exists.")
        return f"Wallet `{name}` created."

    if action == "remove":
        if len(args) < 2:
            raise CommandError("Usage: `!wallet remove <name>`")
        name = args[1]
        if not services.delete_wallet(name):
            raise CommandError(f"No wallet named `{name}`.")
        return f"Wallet `{name}` removed."

    if action in {"show", "balance"}:
        if len(args) < 2:
            raise CommandError("Usage: `!wallet show <name>`")
        name = args[1]
        wallet = services.get_wallet(name)
        if wallet is None:
            raise CommandError(f"No wallet named `{name}`.")
        # Calculate balance and tx count
        balance = services._wallet_balance(wallet)
        tx_count = services._wallet_tx_count(wallet)
        info = services.WalletInfo(
            name=wallet.name, balance_cents=balance, transaction_count=tx_count
        )
        return _format_wallet(info)

    if action == "adjust":
        if len(args) < 3:
            raise CommandError("Usage: `!wallet adjust <name> <amount> [reason]`")
        name, raw_amount = args[1], args[2]
        reason = " ".join(args[3:]).strip() or None
        amount_cents = _parse_amount(raw_amount)
        if amount_cents == 0:
            raise CommandError("Adjustment amount can't be zero.")
        services.adjust_wallet(name, amount_cents, reason)
        return f"Wallet `{name}` adjusted by {format_cents(amount_cents)}."

    if action == "transfer":
        if len(args) < 4:
            raise CommandError(
                "Usage: `!wallet transfer <from> <to> <amount> [reason]`"
            )
        from_name, to_name, raw_amount = args[1], args[2], args[3]
        reason = " ".join(args[4:]).strip() or None
        if from_name == to_name:
            raise CommandError("Transfer wallets must be different.")
        amount_cents = _parse_amount(raw_amount)
        if amount_cents <= 0:
            raise CommandError("Transfer amount must be positive.")
        services.transfer_between_wallets(from_name, to_name, amount_cents, reason)
        return f"Transferred {format_cents(amount_cents)} from `{from_name}` to `{to_name}`."

    raise CommandError(
        "Unknown action. Use list, add, remove, show, balance, adjust, or transfer."
    )


def _parse_amount(raw_amount: str) -> int:
    try:
        return parse_cents(raw_amount)
    except ValueError:
        raise CommandError(f"Couldn't parse value `{raw_amount}`.")


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
                "Expense filters must look like `wallet=main tag=food contains=groceries`."
            )
        key, value = raw.split("=", 1)
        key = key.lower().strip()
        value = value.strip()
        if not key or not value:
            raise CommandError(
                "Expense filters must look like `wallet=main tag=food contains=groceries`."
            )
        filters.setdefault(key, []).append(value)

    return action, filters


async def cmd_expense(args: list[str]) -> str:
    action, filters = _parse_expense_filters(args)

    if action == "summary":
        wallet_name = filters.get("wallet", [None])[0]
        tag_names = filters.get("tag", [])
        contains_terms = filters.get("contains", [])
        after = _parse_date(filters["after"][0]) if filters.get("after") else None
        before = _parse_date(filters["before"][0]) if filters.get("before") else None

        count, total = services.get_expense_summary(
            wallet=wallet_name,
            tags=tag_names if tag_names else None,
            contains=" ".join(contains_terms) if contains_terms else None,
            after=after,
            before=before,
        )
        return f"Expenses: {count} transaction(s), total {format_cents(total)}."

    limit_values = filters.get("limit", ["10"])
    try:
        limit = int(limit_values[0])
    except ValueError:
        raise CommandError("`limit` must be a number.")
    if limit <= 0:
        raise CommandError("`limit` must be greater than zero.")

    wallet_name = filters.get("wallet", [None])[0]
    tag_names = filters.get("tag", [])
    contains_terms = filters.get("contains", [])
    after = _parse_date(filters["after"][0]) if filters.get("after") else None
    before = _parse_date(filters["before"][0]) if filters.get("before") else None

    transactions = services.list_transactions(
        wallet=wallet_name,
        tags=tag_names if tag_names else None,
        contains=" ".join(contains_terms) if contains_terms else None,
        after=after,
        before=before,
        limit=limit,
        expense_only=True,
    )

    if not transactions:
        return "No matching expenses found."

    header_bits = []
    if wallet_name:
        header_bits.append(f"wallet={wallet_name}")
    if tag_names:
        header_bits.append(f"tag={', '.join(tag_names)}")
    if contains_terms:
        header_bits.append(f"contains={' '.join(contains_terms)}")
    header = f"Expenses ({', '.join(header_bits)})" if header_bits else "Expenses"

    lines = [header]
    for tx in transactions:
        tag_str = f" {' '.join(f'#{tag}' for tag in tx.tags)}" if tx.tags else ""
        desc_str = f" - {tx.description}" if tx.description else ""
        lines.append(
            f"- {tx.timestamp:%Y-%m-%d %H:%M} | {tx.wallet_name} | "
            f"{format_cents(tx.value_cents)} | {tx.title}{desc_str}{tag_str}"
        )
    return "\n".join(lines)


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
        "`finance`: `Title: +Amount | -Amount | $type Amount @wallet #tag1 #tag2 Description`\n"
        "`notes`: `# Title` then content on following lines\n"
        "`tasks`: `Task description ?deadline?`"
    )


def _crud_handler(label: str):
    """Factory for the repeated add/remove/list pattern (tag, type)."""

    async def handler(args: list[str]) -> str:
        if not args:
            raise CommandError(f"Usage: `!{label} add|remove|list <name>`")
        action, *rest = args

        if action == "list":
            if label == "tag":
                names = services.list_tags()
            elif label == "type":
                names = services.list_types()
            else:
                raise CommandError("Unknown label")
            return f"{label.capitalize()}s: " + (
                ", ".join(names) if names else "(none yet)"
            )

        if action == "add":
            if not rest:
                raise CommandError(f"Usage: `!{label} add <name>`")
            if label == "tag":
                try:
                    services.create_tag(rest[0])
                except Exception:
                    raise CommandError(
                        f"{label.capitalize()} `{rest[0]}` already exists."
                    )
            elif label == "type":
                try:
                    services.create_type(rest[0])
                except Exception:
                    raise CommandError(
                        f"{label.capitalize()} `{rest[0]}` already exists."
                    )
            return f"{label.capitalize()} `{rest[0]}` created."

        if action == "remove":
            if not rest:
                raise CommandError(f"Usage: `!{label} remove <name>`")
            if label == "tag":
                if not services.delete_tag(rest[0]):
                    raise CommandError(f"No {label} named `{rest[0]}`.")
            elif label == "type" and not services.delete_type(rest[0]):
                raise CommandError(f"No {label} named `{rest[0]}`.")
            return f"{label.capitalize()} `{rest[0]}` removed."

        raise CommandError("Unknown action. Use add, remove, or list.")

    return handler


COMMANDS = {
    "ping": cmd_ping,
    "tag": _crud_handler("tag"),
    "type": _crud_handler("type"),
    "wallet": cmd_wallet,
    "expense": cmd_expense,
    "transactions": cmd_expense,
    "tx": cmd_expense,
    "config": cmd_config,
    "channel": cmd_channel,
    "help": cmd_help,
}


async def dispatch(content: str, prefix: str) -> str:
    raw = content[len(prefix) :].strip()
    if not raw:
        raise CommandError("Empty command. Try `!help`.")

    parts = _split(raw)
    name, args = parts[0].lower(), parts[1:]

    handler = COMMANDS.get(name)
    if handler is None:
        raise CommandError(f"Unknown command `{name}`. Try `!help`.")

    return await handler(args)
