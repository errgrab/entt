"""Service layer for Discord analytics, following the project's service pattern."""

from __future__ import annotations

from datetime import datetime
from collections.abc import Iterable
import logging

from peewee import IntegrityError, fn

from core.analytics import (
    DiscordAccount,
    Event,
    EventParticipation,
    Group,
    GroupMembership,
    Guild,
    GuildPermission,
    MessageMetric,
    VoiceSession,
    get_or_create_account,
    get_or_create_guild,
)
from core.db import db

logger = logging.getLogger("entt.analytics")


class AnalyticsService:
    """Shared lookups and aggregation queries for Discord activity."""

    @staticmethod
    def guild(discord_id: int, name: str = "") -> Guild:
        return get_or_create_guild(discord_id, name or str(discord_id))

    @staticmethod
    def account(
        guild: Guild, discord_id: int, display_name: str = ""
    ) -> DiscordAccount:
        return get_or_create_account(guild, discord_id, display_name)


class MessageMetricService:
    @staticmethod
    def query(
        guild: Guild | int,
        account: DiscordAccount | int | None = None,
        channel_id: int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MessageMetric]:
        guild_id = guild.id if isinstance(guild, Guild) else guild
        query = MessageMetric.select().where(MessageMetric.guild == guild_id)
        if account is not None:
            account_id = account.id if isinstance(account, DiscordAccount) else account
            query = query.where(MessageMetric.account == account_id)
        if channel_id is not None:
            query = query.where(MessageMetric.channel_id == channel_id)
        if start_date is not None:
            query = query.where(MessageMetric.created_at >= start_date)
        if end_date is not None:
            query = query.where(MessageMetric.created_at <= end_date)
        return list(
            query.order_by(MessageMetric.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

    @staticmethod
    def summary(
        guild: Guild | int,
        account: DiscordAccount | int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, int]:
        guild_id = guild.id if isinstance(guild, Guild) else guild
        query = MessageMetric.select().where(MessageMetric.guild == guild_id)
        if account is not None:
            account_id = account.id if isinstance(account, DiscordAccount) else account
            query = query.where(MessageMetric.account == account_id)
        if start_date is not None:
            query = query.where(MessageMetric.created_at >= start_date)
        if end_date is not None:
            query = query.where(MessageMetric.created_at <= end_date)
        return {
            "messages": query.count(),
            "characters": query.select(fn.COALESCE(fn.SUM(MessageMetric.character_count), 0)).scalar(),
            "words": query.select(fn.COALESCE(fn.SUM(MessageMetric.word_count), 0)).scalar(),
        }


class VoiceSessionService:
    @staticmethod
    def query(
        guild: Guild | int,
        account: DiscordAccount | int | None = None,
        channel_id: int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[VoiceSession]:
        guild_id = guild.id if isinstance(guild, Guild) else guild
        query = VoiceSession.select().where(VoiceSession.guild == guild_id)
        if account is not None:
            account_id = account.id if isinstance(account, DiscordAccount) else account
            query = query.where(VoiceSession.account == account_id)
        if channel_id is not None:
            query = query.where(VoiceSession.channel_id == channel_id)
        if start_date is not None:
            query = query.where(VoiceSession.started_at >= start_date)
        if end_date is not None:
            query = query.where(VoiceSession.started_at <= end_date)
        return list(query.order_by(VoiceSession.started_at.desc()))

    @staticmethod
    def summary(
        guild: Guild | int,
        account: DiscordAccount | int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, int]:
        sessions = VoiceSessionService.query(
            guild, account, start_date=start_date, end_date=end_date
        )
        return {
            "sessions": len(sessions),
            "completed_sessions": sum(session.ended_at is not None for session in sessions),
            "duration_seconds": sum(session.duration_seconds or 0 for session in sessions),
        }


class GroupService:
    @staticmethod
    def create(
        guild: Guild, name: str, admin_role_ids: Iterable[int] = ()
    ) -> Group:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Group name cannot be empty.")
        try:
            group = Group.create(
                guild=guild,
                name=clean_name,
                admin_role_ids=",".join(str(role_id) for role_id in admin_role_ids),
            )
            logger.info(
                "sql_write model=group operation=insert id=%s guild_id=%s name=%r",
                group.id,
                guild.discord_id,
                group.name,
            )
            return group
        except IntegrityError:
            raise ValueError(f"Group '{clean_name}' already exists.") from None

    @staticmethod
    def add_member(group: Group, account: DiscordAccount) -> GroupMembership:
        if group.guild_id != account.guild_id:
            raise ValueError("Group and account must belong to the same guild.")
        with db.atomic():
            active = GroupMembership.get_or_none(
                (GroupMembership.account == account) & GroupMembership.active
            )
            if active is not None and active.group_id != group.id:
                raise ValueError("Account already belongs to another group.")
            if active is not None:
                return active
            membership = GroupMembership.create(group=group, account=account)
            logger.info(
                "sql_write model=group_membership operation=insert id=%s group_id=%s account_id=%s",
                membership.id,
                group.id,
                account.id,
            )
            return membership

    @staticmethod
    def remove_member(group: Group, account: DiscordAccount) -> bool:
        membership = GroupMembership.get_or_none(
            (GroupMembership.group == group)
            & (GroupMembership.account == account)
            & GroupMembership.active
        )
        if membership is None:
            return False
        membership.active = False
        membership.save(only=[GroupMembership.active])
        logger.info(
            "sql_write model=group_membership operation=update id=%s group_id=%s account_id=%s active=false",
            membership.id,
            group.id,
            account.id,
        )
        return True


class PermissionService:
    @staticmethod
    def allowed(guild: Guild, action: str, role_ids: set[int]) -> bool:
        required = {
            permission.role_id
            for permission in GuildPermission.select().where(
                (GuildPermission.guild == guild) & (GuildPermission.action == action)
            )
        }
        return bool(required & role_ids)


class EventService:
    @staticmethod
    def create(
        guild: Guild,
        name: str,
        starts_at: datetime,
        created_by: int,
        ends_at: datetime | None = None,
    ) -> Event:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Event name cannot be empty.")
        event = Event.create(
            guild=guild,
            name=clean_name,
            starts_at=starts_at,
            ends_at=ends_at,
            created_by=created_by,
        )
        logger.info(
            "sql_write model=event operation=insert id=%s guild_id=%s created_by=%s starts_at=%s",
            event.id,
            guild.discord_id,
            created_by,
            starts_at,
        )
        return event

    @staticmethod
    def list(guild: Guild, active_only: bool = True) -> list[Event]:
        query = Event.select().where(Event.guild == guild)
        if active_only:
            query = query.where(Event.active)
        return list(query.order_by(Event.starts_at))

    @staticmethod
    def get(guild: Guild, event_id: int) -> Event | None:
        return Event.get_or_none((Event.guild == guild) & (Event.id == event_id))

    @staticmethod
    def join(event: Event, account: DiscordAccount) -> EventParticipation:
        if event.guild_id != account.guild_id:
            raise ValueError("Event and account must belong to the same guild.")
        participation, created = EventParticipation.get_or_create(
            event=event, account=account
        )
        if not created:
            logger.debug(
                "sql_write model=event_participation operation=skip_duplicate event_id=%s account_id=%s",
                event.id,
                account.id,
            )
        else:
            logger.info(
                "sql_write model=event_participation operation=insert id=%s event_id=%s account_id=%s",
                participation.id,
                event.id,
                account.id,
            )
        return participation

    @staticmethod
    def leave(event: Event, account: DiscordAccount) -> bool:
        deleted = (
            EventParticipation.delete()
            .where(
                (EventParticipation.event == event)
                & (EventParticipation.account == account)
            )
            .execute()
            > 0
        )
        if deleted:
            logger.info(
                "sql_write model=event_participation operation=delete event_id=%s account_id=%s",
                event.id,
                account.id,
            )
        return deleted

    @staticmethod
    def participants(event: Event) -> list[DiscordAccount]:
        return [
            participation.account
            for participation in EventParticipation.select()
            .where(EventParticipation.event == event)
            .order_by(EventParticipation.joined_at)
        ]
