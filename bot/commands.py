import logging
import shlex

from core.services import SettingService

logger = logging.getLogger("entt.commands")


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
        value = SettingService.get(args[1])
        return f"`{args[1]}` = `{value}`" if value else f"`{args[1]}` is not set."

    if action == "set":
        if len(args) < 3:
            raise CommandError("Usage: `!config set <key> <value>`")
        key, value = args[1], " ".join(args[2:])
        SettingService.set(key, value)
        return f"`{key}` set."

    raise CommandError("Unknown action. Use get or set.")


async def cmd_channel(args: list[str]) -> str:
    raise NotImplementedError("This is not implemented yet.")


async def cmd_wallet(args: list[str]) -> str:
    raise NotImplementedError("This is not implemented yet.")


async def cmd_help(args: list[str]) -> str:
    return (
        "**Prefix commands (work anywhere)**\n"
        "`!ping`\n"
        "`!config get|set <key> [value]`\n\n"
        "`!channel list` / `!channel set <finance|notes|tasks> <#channel>`\n"
        "`!wallet list|show|add|remove`\n"
        "**Channel syntax (no prefix, in the configured channel)**\n"
        "`finance`: `Title: $type Amount #tag1 #tag2 Description`\n"
        "`notes`: `# Title` then content on following lines\n"
        "`tasks`: `Task description ?deadline?`"
    )


COMMANDS = {
    "ping": cmd_ping,
    "config": cmd_config,
    "channel": cmd_channel,
    "wallet": cmd_wallet,
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
