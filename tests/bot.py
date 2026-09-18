import pytest

from bot.commands import COMMANDS, CommandError, dispatch


def test_only_analytics_commands_are_exposed():
    assert set(COMMANDS) == {
        "ping",
        "help",
        "info",
        "stats",
        "voice",
        "group",
        "groups",
        "event",
        "events",
    }


def test_removed_legacy_commands_are_not_available():
    with pytest.raises(CommandError, match="Unknown command"):
        import asyncio

        asyncio.run(dispatch("!removed", "!"))
