from datetime import datetime, timezone
from types import SimpleNamespace
import asyncio
from types import SimpleNamespace

import pytest

from core.analytics import (
    ANALYTICS_MODELS,
    Event,
    Group,
    Guild,
    MessageMetric,
    VoiceSession,
    close_voice_session,
    db,
    get_open_voice_sessions,
    open_voice_session,
    record_message,
)
from core.analytics_services import (
    AnalyticsService,
    GroupService,
    MessageMetricService,
    PermissionService,
    VoiceSessionService,
)
from bot import client as bot_client
from bot.commands import CommandContext, dispatch


@pytest.fixture(autouse=True)
def setup_analytics_db():
    db.init(":memory:")
    db.connect(reuse_if_open=True)
    db.create_tables(ANALYTICS_MODELS)
    yield
    db.drop_tables(ANALYTICS_MODELS)
    db.close()


def test_message_metrics_are_idempotent_and_do_not_store_content(caplog):
    caplog.set_level("INFO", logger="entt.analytics")
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    metric = record_message(
        guild_id=1,
        guild_name="Test",
        discord_user_id=2,
        display_name="User",
        message_id=3,
        channel_id=4,
        content="olá   mundo",
        created_at=created_at,
    )

    duplicate = record_message(
        guild_id=1,
        guild_name="Test",
        discord_user_id=2,
        display_name="User",
        message_id=3,
        channel_id=4,
        content="conteúdo diferente",
        created_at=created_at,
    )

    assert metric is not None
    assert duplicate is None
    assert metric.character_count == len("olá   mundo")
    assert metric.word_count == 2
    assert not hasattr(metric, "content")
    assert MessageMetric.select().count() == 1
    assert "model=message_metric operation=insert" in caplog.text


def test_voice_session_closes_with_duration():
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 12, 5, 30, tzinfo=timezone.utc)
    session = open_voice_session(1, "Test", 2, "User", 4, started_at=start)

    closed = close_voice_session(1, 2, ended_at=end)

    assert closed is not None
    assert closed.id == session.id
    assert closed.duration_seconds == 330
    assert VoiceSession.get_by_id(session.id).ended_at == end
    assert get_open_voice_sessions() == []


def test_voice_session_writes_are_logged(caplog):
    caplog.set_level("INFO", logger="entt.analytics")
    session = open_voice_session(1, "Test", 2, "User", 4)
    close_voice_session(1, 2)

    assert f"model=voice_session operation=insert id={session.id}" in caplog.text
    assert f"model=voice_session operation=update id={session.id}" in caplog.text


def test_groups_and_events_are_scoped_to_guilds():
    assert Group._meta.table_name == "group"
    assert Event._meta.table_name == "event"


def test_service_summaries_and_single_group_membership():
    record_message(1, "Test", 2, "User", 3, 4, "one two")
    record_message(1, "Test", 2, "User", 5, 4, "three")
    guild = Guild.get(Guild.discord_id == 1)
    account = guild.accounts.get()
    group_a = GroupService.create(guild, "Alpha", [10])
    group_b = GroupService.create(guild, "Beta")

    membership = GroupService.add_member(group_a, account)
    assert membership.group_id == group_a.id
    with pytest.raises(ValueError, match="another group"):
        GroupService.add_member(group_b, account)

    assert MessageMetricService.summary(guild, account)["words"] == 3
    assert VoiceSessionService.summary(guild, account)["sessions"] == 0
    assert PermissionService.allowed(guild, "manage_groups", {10}) is False


def test_voice_sessions_are_reconciled_on_ready(monkeypatch):
    open_voice_session(1, "Test", 99, "Old User", 100)
    member = SimpleNamespace(id=2, display_name="Current User", bot=False)
    channel = SimpleNamespace(id=200, members=[member])
    guild = SimpleNamespace(id=1, name="Test", voice_channels=[channel])
    monkeypatch.setattr(bot_client, "client", SimpleNamespace(guilds=[guild]))

    asyncio.run(bot_client.synchronize_voice_sessions())

    sessions = list(VoiceSession.select().order_by(VoiceSession.id))
    assert len(sessions) == 2
    assert sessions[0].ended_at is not None
    assert sessions[1].account.discord_id == 2
    assert sessions[1].channel_id == 200


def test_analytics_commands_cover_stats_groups_and_events():
    member = SimpleNamespace(
        id=2,
        display_name="User",
        roles=[],
        guild_permissions=SimpleNamespace(administrator=True, manage_guild=True),
    )
    guild = SimpleNamespace(
        id=1,
        name="Test",
        get_member=lambda user_id: member if user_id == 2 else None,
    )
    context = CommandContext(guild=guild, member=member, display_name="Display Name")
    record_message(1, "Test", 2, "User", 3, 4, "one two")

    stats = asyncio.run(dispatch("!stats", "!", context))
    assert "Messages: `1`" in stats

    created = asyncio.run(dispatch("!group create Alpha", "!", context))
    assert "created" in created
    groups = asyncio.run(dispatch("!group list", "!", context))
    assert "Alpha" in groups
    added = asyncio.run(dispatch("!group add Alpha <@2>", "!", context))
    assert "Alpha" in added

    created_event = asyncio.run(
        dispatch("!event create 2026-01-01T12:00 Launch", "!", context)
    )
    assert "Launch" in created_event
    joined = asyncio.run(dispatch("!event join 1", "!", context))
    assert "joined" in joined


def test_info_uses_command_members_display_name_without_guild_cache():
    member = SimpleNamespace(
        id=2,
        display_name="Display Name",
        roles=[],
        guild_permissions=SimpleNamespace(administrator=False, manage_guild=False),
    )
    guild = SimpleNamespace(id=1, name="Test", get_member=lambda _: None)
    context = CommandContext(guild=guild, member=member)

    info = asyncio.run(dispatch("!info", "!", context))

    assert "**Display Name** (`2`)" in info


def test_missing_display_name_does_not_overwrite_persisted_name():
    guild = AnalyticsService.guild(1, "Test")
    first = AnalyticsService.account(guild, 2, "Stored Name")
    second = AnalyticsService.account(guild, 2, "")

    assert second.id == first.id
    assert second.display_name == "Stored Name"


def test_command_name_repairs_account_that_was_saved_with_id():
    guild = AnalyticsService.guild(1, "Test")
    account = AnalyticsService.account(guild, 2, "")
    assert account.display_name == "2"

    member = SimpleNamespace(
        id=2,
        display_name="Real Display Name",
        roles=[],
        guild_permissions=SimpleNamespace(administrator=False, manage_guild=False),
    )
    context = CommandContext(
        guild=SimpleNamespace(id=1, name="Test", get_member=lambda _: member),
        member=member,
        display_name="Real Display Name",
    )

    info = asyncio.run(dispatch("!info", "!", context))

    assert "**Real Display Name** (`2`)" in info


def test_info_fetches_mentioned_member_when_not_cached():
    author = SimpleNamespace(
        id=2,
        display_name="Author",
        roles=[],
        guild_permissions=SimpleNamespace(administrator=False, manage_guild=False),
    )
    mentioned = SimpleNamespace(id=7, display_name="ErikG")
    guild = SimpleNamespace(
        id=1,
        name="Test",
        get_member=lambda _: None,
        fetch_member=lambda _: asyncio.sleep(0, result=mentioned),
    )
    context = CommandContext(guild=guild, member=author)

    info = asyncio.run(dispatch("!info <@7>", "!", context))

    assert "**ErikG** (`7`)" in info
