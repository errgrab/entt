"""Persistence and application services for Discord activity metrics."""

from __future__ import annotations

import re
import logging
from datetime import datetime, timezone

from peewee import (
    AutoField,
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    Model,
    TextField,
)

from core.db import db

logger = logging.getLogger("entt.analytics")


class AnalyticsModel(Model):
    class Meta:
        database = db


class Guild(AnalyticsModel):
    id = AutoField()
    discord_id = IntegerField(unique=True)
    name = CharField(max_length=256)
    enabled = BooleanField(default=True)


class DiscordAccount(AnalyticsModel):
    id = AutoField()
    guild = ForeignKeyField(Guild, backref="accounts", on_delete="CASCADE")
    discord_id = IntegerField()
    display_name = CharField(max_length=256)
    active = BooleanField(default=True)

    class Meta:
        indexes = ((("guild", "discord_id"), True),)


class MessageMetric(AnalyticsModel):
    id = AutoField()
    guild = ForeignKeyField(Guild, backref="messages", on_delete="CASCADE")
    account = ForeignKeyField(DiscordAccount, backref="messages", on_delete="CASCADE")
    discord_message_id = IntegerField()
    channel_id = IntegerField()
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))
    character_count = IntegerField()
    word_count = IntegerField()

    class Meta:
        indexes = ((("guild", "discord_message_id"), True),)


class VoiceSession(AnalyticsModel):
    id = AutoField()
    guild = ForeignKeyField(Guild, backref="voice_sessions", on_delete="CASCADE")
    account = ForeignKeyField(
        DiscordAccount, backref="voice_sessions", on_delete="CASCADE"
    )
    channel_id = IntegerField()
    started_at = DateTimeField()
    ended_at = DateTimeField(null=True)
    duration_seconds = IntegerField(null=True)


class Group(AnalyticsModel):
    id = AutoField()
    guild = ForeignKeyField(Guild, backref="groups", on_delete="CASCADE")
    name = CharField(max_length=128)
    admin_role_ids = TextField(default="")
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    class Meta:
        indexes = ((("guild", "name"), True),)


class GroupMembership(AnalyticsModel):
    id = AutoField()
    group = ForeignKeyField(Group, backref="memberships", on_delete="CASCADE")
    account = ForeignKeyField(
        DiscordAccount, backref="group_memberships", on_delete="CASCADE"
    )
    joined_at = DateTimeField(default=lambda: datetime.now(timezone.utc))
    active = BooleanField(default=True)


class Event(AnalyticsModel):
    id = AutoField()
    guild = ForeignKeyField(Guild, backref="events", on_delete="CASCADE")
    name = CharField(max_length=256)
    starts_at = DateTimeField()
    ends_at = DateTimeField(null=True)
    created_by = IntegerField()
    active = BooleanField(default=True)


class EventParticipation(AnalyticsModel):
    id = AutoField()
    event = ForeignKeyField(Event, backref="participants", on_delete="CASCADE")
    account = ForeignKeyField(
        DiscordAccount, backref="event_participations", on_delete="CASCADE"
    )
    joined_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    class Meta:
        indexes = ((("event", "account"), True),)


class GuildPermission(AnalyticsModel):
    id = AutoField()
    guild = ForeignKeyField(Guild, backref="permissions", on_delete="CASCADE")
    action = CharField(max_length=64)
    role_id = IntegerField()

    class Meta:
        indexes = ((("guild", "action", "role_id"), True),)


ANALYTICS_MODELS = [
    Guild,
    DiscordAccount,
    MessageMetric,
    VoiceSession,
    Group,
    GroupMembership,
    Event,
    EventParticipation,
    GuildPermission,
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create_guild(discord_id: int, name: str) -> Guild:
    guild, created = Guild.get_or_create(
        discord_id=discord_id, defaults={"name": name[:256]}
    )
    if not created and guild.name != name[:256]:
        old_name = guild.name
        guild.name = name[:256]
        guild.save(only=[Guild.name])
        logger.info(
            "sql_write model=guild operation=update id=%s discord_id=%s old_name=%r new_name=%r",
            guild.id,
            discord_id,
            old_name,
            guild.name,
        )
    elif created:
        logger.info(
            "sql_write model=guild operation=insert id=%s discord_id=%s name=%r",
            guild.id,
            discord_id,
            guild.name,
        )
    return guild


def get_or_create_account(guild: Guild, discord_id: int, display_name: str) -> DiscordAccount:
    clean_display_name = display_name.strip()[:256]
    account, created = DiscordAccount.get_or_create(
        guild=guild,
        discord_id=discord_id,
        defaults={"display_name": clean_display_name or str(discord_id)},
    )
    if (
        not created
        and clean_display_name
        and clean_display_name != str(discord_id)
        and account.display_name != clean_display_name
    ):
        account.display_name = clean_display_name
        account.save(only=[DiscordAccount.display_name])
        logger.info(
            "sql_write model=discord_account operation=update id=%s guild_id=%s discord_id=%s",
            account.id,
            guild.discord_id,
            discord_id,
        )
    elif created:
        logger.info(
            "sql_write model=discord_account operation=insert id=%s guild_id=%s discord_id=%s",
            account.id,
            guild.discord_id,
            discord_id,
        )
    return account


def record_message(
    guild_id: int,
    guild_name: str,
    discord_user_id: int,
    display_name: str,
    message_id: int,
    channel_id: int,
    content: str,
    created_at: datetime | None = None,
) -> MessageMetric | None:
    """Record only message metrics; content itself is intentionally discarded."""
    guild = get_or_create_guild(guild_id, guild_name)
    account = get_or_create_account(guild, discord_user_id, display_name)
    words = len(re.findall(r"\S+", content, flags=re.UNICODE))
    metric, created = MessageMetric.get_or_create(
        guild=guild,
        discord_message_id=message_id,
        defaults={
            "account": account,
            "channel_id": channel_id,
            "created_at": created_at or utc_now(),
            "character_count": len(content),
            "word_count": words,
        },
    )
    if created:
        logger.info(
            "sql_write model=message_metric operation=insert id=%s guild_id=%s account_id=%s message_id=%s channel_id=%s characters=%s words=%s",
            metric.id,
            guild_id,
            account.id,
            message_id,
            channel_id,
            metric.character_count,
            metric.word_count,
        )
        return metric
    logger.debug(
        "sql_write model=message_metric operation=skip_duplicate guild_id=%s message_id=%s",
        guild_id,
        message_id,
    )
    return None


def open_voice_session(
    guild_id: int,
    guild_name: str,
    discord_user_id: int,
    display_name: str,
    channel_id: int,
    started_at: datetime | None = None,
) -> VoiceSession:
    guild = get_or_create_guild(guild_id, guild_name)
    account = get_or_create_account(guild, discord_user_id, display_name)
    session = VoiceSession.create(
        guild=guild,
        account=account,
        channel_id=channel_id,
        started_at=started_at or utc_now(),
    )
    logger.info(
        "sql_write model=voice_session operation=insert id=%s guild_id=%s account_id=%s channel_id=%s started_at=%s",
        session.id,
        guild_id,
        account.id,
        channel_id,
        session.started_at,
    )
    return session


def close_voice_session(
    guild_id: int, discord_user_id: int, ended_at: datetime | None = None
) -> VoiceSession | None:
    session = (
        VoiceSession.select()
        .join(Guild)
        .join(DiscordAccount)
        .where(
            (Guild.discord_id == guild_id)
            & (DiscordAccount.discord_id == discord_user_id)
            & VoiceSession.ended_at.is_null()
        )
        .order_by(VoiceSession.started_at.desc())
        .first()
    )
    if session is None:
        return None
    end = ended_at or utc_now()
    session.ended_at = end
    session.duration_seconds = max(0, int((end - session.started_at).total_seconds()))
    session.save(only=[VoiceSession.ended_at, VoiceSession.duration_seconds])
    logger.info(
        "sql_write model=voice_session operation=update id=%s guild_id=%s account_id=%s channel_id=%s ended_at=%s duration_seconds=%s",
        session.id,
        guild_id,
        session.account_id,
        session.channel_id,
        session.ended_at,
        session.duration_seconds,
    )
    return session


def get_open_voice_sessions() -> list[VoiceSession]:
    """Return sessions that were still open when the process stopped."""
    return list(VoiceSession.select().where(VoiceSession.ended_at.is_null()))
