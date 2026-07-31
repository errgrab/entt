from dateutil import parser as dateparser

from bot.commands import CommandError, format_cents, parse_cents
from db.models import (
    Note,
    Tag,
    Task,
    Transaction,
    TransactionTag,
    TransactionType,
    Wallet,
)


def _parse_cents(raw: str) -> int:
    try:
        return parse_cents(raw)
    except ValueError:
        raise CommandError(f"Couldn't parse value `{raw}`.")


def _scan_finance_prefix(s: str):
    i = 0
    while i < len(s) and s[i].isspace():
        i += 1
    if i >= len(s):
        return None

    type_name = None
    type_start = i

    if s[i] == "$":
        j = i + 1
        while j < len(s) and (s[j].isalnum() or s[j] == "_"):
            j += 1
        if j > i + 1:
            type_name = s[i + 1 : j]
            k = j
            while k < len(s) and s[k].isspace():
                k += 1
            i = k
        else:
            return None
    elif s[i] in "+-":
        type_name = "income" if s[i] == "+" else "outcome"
        i += 1
        while i < len(s) and s[i].isspace():
            i += 1
    else:
        return None

    return type_name, i, type_start


def _parse_amount_at(s: str, start: int):
    i = start
    while i < len(s) and s[i].isspace():
        i += 1
    if i >= len(s):
        return None
    if s[i] in "+-":
        i += 1
    if i >= len(s) or (not s[i].isdigit() and s[i] != "."):
        return None
    val_start = i
    while i < len(s) and (s[i].isdigit() or s[i] == "."):
        i += 1
    if i < len(s) and s[i] == ",":
        i += 1
        dec_start = i
        while i < len(s) and s[i].isdigit():
            i += 1
        if i - dec_start > 2:
            i = dec_start + 2
    raw = s[val_start:i]
    return raw, i


def _find_wallets(s: str):
    names = []
    i = 0
    while i < len(s):
        if s[i] == "@":
            j = i + 1
            while j < len(s) and (s[j].isalnum() or s[j] == "_" or s[j] == "-"):
                j += 1
            if j > i + 1:
                names.append(s[i + 1 : j])
            i = j
        else:
            i += 1
    return names


def _remove_wallets(s: str) -> str:
    result = []
    i = 0
    while i < len(s):
        if s[i] == "@":
            j = i + 1
            while j < len(s) and (s[j].isalnum() or s[j] == "_" or s[j] == "-"):
                j += 1
            if j > i + 1:
                i = j
                continue
        result.append(s[i])
        i += 1
    return "".join(result)


def _find_tags(s: str):
    names = []
    i = 0
    while i < len(s):
        if s[i] == "#":
            j = i + 1
            while j < len(s) and (s[j].isalnum() or s[j] == "_"):
                j += 1
            if j > i + 1:
                names.append(s[i + 1 : j])
            i = j
        else:
            i += 1
    return names


def _remove_tags(s: str) -> str:
    result = []
    i = 0
    while i < len(s):
        if s[i] == "#":
            j = i + 1
            while j < len(s) and (s[j].isalnum() or s[j] == "_"):
                j += 1
            if j > i + 1:
                i = j
                continue
        result.append(s[i])
        i += 1
    return "".join(result)


async def parse_finance(content: str) -> str:
    """Title: +Amount | -Amount | $type Amount @wallet #tag1 #tag2 Description"""
    if ":" not in content:
        raise CommandError(
            "Finance syntax: `Title: +Amount | -Amount | $type Amount @wallet #tag1 #tag2 Description`\n"
            "Example: `Groceries: -150,00 @main #food Weekly shopping`"
        )

    title, rest = content.split(":", 1)
    title = title.strip()
    if not title:
        raise CommandError("A title is required before the `:`.")

    prefix = _scan_finance_prefix(rest)
    if not prefix:
        raise CommandError(
            "A value is required, e.g. `+150,00`, `-50,00`, `$pix 30,00`."
        )
    type_label, amount_start, type_start = prefix

    amount_result = _parse_amount_at(rest, amount_start)
    if not amount_result:
        raise CommandError(
            "A value is required, e.g. `+150,00`, `-50,00`, `$pix 30,00`."
        )
    raw_amount, amount_end = amount_result
    value_cents = _parse_cents(raw_amount)

    rest = rest[:type_start] + rest[amount_end:]

    wallet_names = _find_wallets(rest)
    if len(set(wallet_names)) > 1:
        raise CommandError("Only one wallet can be specified per finance entry.")
    wallet_name = wallet_names[0] if wallet_names else "main"
    rest = _remove_wallets(rest)

    tag_names = _find_tags(rest)
    rest = _remove_tags(rest)
    description = rest.strip() or None

    wallet, _ = Wallet.get_or_create(name=wallet_name)

    if type_label in ("income", "outcome"):
        type_name = type_label
    else:
        ts_type = TransactionType.get_or_none(name=type_label)
        if ts_type is None:
            ts_type, _ = TransactionType.get_or_create(name="credit")
        type_name = ts_type.name

    ts_type, _ = TransactionType.get_or_create(name=type_name)

    tx = Transaction.create(
        title=title,
        description=description,
        value_cents=value_cents,
        wallet=wallet,
        ts_type=ts_type,
    )
    for name in tag_names:
        tag, _ = Tag.get_or_create(name=name)
        TransactionTag.create(transaction=tx, tag=tag)

    tag_str = f" — tags: {', '.join(tag_names)}" if tag_names else ""
    wallet_str = f" — wallet: {wallet.name}" if wallet.name != "main" else ""
    return f"💰 Logged **{title}** (`{type_name}`, {format_cents(value_cents)}){wallet_str}{tag_str}"


async def parse_note(content: str) -> str:
    """# Title
    Content, can span multiple lines."""
    lines = content.strip().splitlines()
    if not lines or not lines[0].strip().startswith("#"):
        raise CommandError(
            "Note syntax: first line must be `# Title`, followed by content."
        )

    title = lines[0].lstrip("#").strip()
    if not title:
        raise CommandError("A title is required after `#`.")

    body = "\n".join(lines[1:]).strip()
    if not body:
        raise CommandError("Note content can't be empty.")

    note = Note.create(title=title, content=body)
    return f"📝 Note **{note.title}** saved (id `{note.id}`)."


async def parse_task(content: str) -> str:
    """Task description ?deadline?"""
    content = content.strip()
    if not content:
        raise CommandError(
            "Task syntax: `Task description ?deadline?` (deadline [optional])."
        )

    deadline = None
    start = content.find("?")
    description = content
    if start != -1:
        end = content.find("?", start + 1)
        if end != -1 and end > start + 1:
            raw_deadline = content[start + 1 : end].strip()
            description = (content[:start] + content[end + 1 :]).strip()
            try:
                deadline = dateparser.parse(raw_deadline, fuzzy=True, dayfirst=True)
            except (ValueError, OverflowError):
                raise CommandError(f"Couldn't understand deadline `{raw_deadline}`.")

    if not description:
        raise CommandError("A task description is required.")

    task = Task.create(title=description, deadline=deadline)
    when = f" — due {deadline.strftime('%Y-%m-%d %H:%M')}" if deadline else ""
    return f"✅ Task **{task.title}** created (id `{task.id}`){when}."


PARSERS = {
    "finance": parse_finance,
    "notes": parse_note,
    "tasks": parse_task,
}
