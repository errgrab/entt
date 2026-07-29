import re
from dateutil import parser as dateparser
from db.models import Transaction, TransactionTag, Tag, Wallet, TransactionType, Note, Task
from bot.commands import CommandError
from bot.money import format_cents, parse_cents

VALUE_RE = re.compile(r"R\$\s*(-?[\d.]+(?:,\d{1,2})?)")
WALLET_RE = re.compile(r"@([\w-]+)")
TAG_RE = re.compile(r"#(\w+)")
DEADLINE_RE = re.compile(r"\?(.+?)\?")


def _parse_cents(raw: str) -> int:
    try:
        return parse_cents(raw)
    except ValueError:
        raise CommandError(f"Couldn't parse value `{raw}`.")


async def parse_finance(content: str) -> str:
    """Title: R$Value @wallet #tag1 #tag2 Description text"""
    if ":" not in content:
        raise CommandError(
            "Finance syntax: `Title: R$Value @wallet #tag1 #tag2 Description`\n"
            "Example: `Groceries: R$-150,00 @main #food Weekly shopping`"
        )

    title, rest = content.split(":", 1)
    title = title.strip()
    if not title:
        raise CommandError("A title is required before the `:`.")

    value_match = VALUE_RE.search(rest)
    if not value_match:
        raise CommandError("A value is required, e.g. `R$150,00` or `R$-50,00`.")
    value_cents = _parse_cents(value_match.group(1))
    rest = rest[:value_match.start()] + rest[value_match.end():]

    wallet_names = WALLET_RE.findall(rest)
    if len(set(wallet_names)) > 1:
        raise CommandError("Only one wallet can be specified per finance entry.")
    wallet_name = wallet_names[0] if wallet_names else "main"
    rest = WALLET_RE.sub("", rest)

    tag_names = TAG_RE.findall(rest)
    rest = TAG_RE.sub("", rest)
    description = rest.strip() or None

    wallet, _ = Wallet.get_or_create(name=wallet_name)
    type_name = "income" if value_cents >= 0 else "expense"
    ts_type, _ = TransactionType.get_or_create(name=type_name)

    tx = Transaction.create(
        title=title, description=description, value_cents=value_cents,
        wallet=wallet, ts_type=ts_type,
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
        raise CommandError("Note syntax: first line must be `# Title`, followed by content.")

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
        raise CommandError("Task syntax: `Task description ?deadline?` (deadline optional).")

    deadline = None
    match = DEADLINE_RE.search(content)
    description = content
    if match:
        description = (content[:match.start()] + content[match.end():]).strip()
        raw_deadline = match.group(1).strip()
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