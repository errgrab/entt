"""Prefix commands for analytics and community management."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import discord

from core.analytics import Group, GroupMembership
from core.analytics_services import (
    AnalyticsService,
    EventService,
    GroupService,
    MessageMetricService,
    PermissionService,
    VoiceSessionService,
)


class CommandError(Exception):
    """User-facing command error."""


@dataclass(frozen=True)
class CommandContext:
    guild: Any
    member: Any
    display_name: str = ""


def _split(content: str) -> list[str]:
    try:
        return shlex.split(content)
    except ValueError as error:
        raise CommandError(f"Couldn't parse that command: {error}") from error


def _require_context(context: CommandContext | None) -> CommandContext:
    if context is None or context.guild is None:
        raise CommandError("This command can only be used inside a server.")
    return context


def _guild(context: CommandContext):
    return AnalyticsService.guild(context.guild.id, context.guild.name)


async def _account(context: CommandContext, user_id: int | None = None):
    target_id = user_id or context.member.id
    member = (
        context.member
        if target_id == context.member.id
        else context.guild.get_member(target_id)
    )
    if member is None and target_id != context.member.id:
        try:
            member = await context.guild.fetch_member(target_id)
        except discord.NotFound:
            member = None
        except discord.HTTPException as error:
            raise CommandError("Discord could not resolve that user.") from error

    display_name = context.display_name if target_id == context.member.id else ""
    if member is not None:
        display_name = (
            display_name
            or getattr(member, "display_name", None)
            or getattr(member, "global_name", None)
            or getattr(member, "name", None)
            or ""
        )
    return AnalyticsService.account(_guild(context), target_id, display_name)


def _user_id(value: str | None) -> int | None:
    if value is None:
        return None
    raw = value.strip().strip("<@!>")
    try:
        return int(raw)
    except ValueError as error:
        raise CommandError("User must be a Discord ID or mention.") from error


def _duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"


def _resolve_group(guild: Any, name: str) -> Group:
    clean_name = name.strip()
    group = next(
        (
            candidate
            for candidate in Group.select().where(Group.guild == guild)
            if candidate.name.casefold() == clean_name.casefold()
        ),
        None,
    )
    if group is None:
        raise CommandError(f"Group `{clean_name}` not found.")
    return group


def _can_manage(context: CommandContext, action: str) -> bool:
    member = context.member
    permissions = getattr(member, "guild_permissions", None)
    if permissions and (
        getattr(permissions, "administrator", False)
        or getattr(permissions, "manage_guild", False)
    ):
        return True
    role_ids = {role.id for role in getattr(member, "roles", [])}
    return PermissionService.allowed(_guild(context), action, role_ids)


def _require_manage(context: CommandContext, action: str) -> None:
    if not _can_manage(context, action):
        raise CommandError("You do not have permission for this action.")


async def cmd_ping(args: list[str], context: CommandContext | None = None) -> str:
    return "pong!"


async def cmd_info(args: list[str], context: CommandContext | None = None) -> str:
    ctx = _require_context(context)
    user_id = _user_id(args[0]) if args else None
    account = await _account(ctx, user_id)
    membership = (
        GroupMembership.select()
        .where((GroupMembership.account == account) & GroupMembership.active)
        .first()
    )
    group_name = membership.group.name if membership else "none"
    return (
        f"**{account.display_name}** (`{account.discord_id}`)\n"
        f"Group: **{group_name}**\n"
        f"Tracked: {'yes' if account.active else 'no'}"
    )


async def cmd_stats(args: list[str], context: CommandContext | None = None) -> str:
    ctx = _require_context(context)
    account = await _account(ctx, _user_id(args[0]) if args else None)
    summary = MessageMetricService.summary(_guild(ctx), account)
    return (
        f"**Message statistics — {account.display_name}**\n"
        f"Messages: `{summary['messages']}`\n"
        f"Words: `{summary['words']}`\n"
        f"Characters: `{summary['characters']}`"
    )


async def cmd_voice(args: list[str], context: CommandContext | None = None) -> str:
    ctx = _require_context(context)
    account = await _account(ctx, _user_id(args[0]) if args else None)
    summary = VoiceSessionService.summary(_guild(ctx), account)
    return (
        f"**Voice statistics — {account.display_name}**\n"
        f"Sessions: `{summary['sessions']}`\n"
        f"Completed: `{summary['completed_sessions']}`\n"
        f"Total time: `{_duration(summary['duration_seconds'])}`"
    )


async def cmd_group(args: list[str], context: CommandContext | None = None) -> str:
    ctx = _require_context(context)
    guild = _guild(ctx)
    action = args[0].lower() if args else "list"
    if action == "list":
        groups = list(Group.select().where(Group.guild == guild).order_by(Group.name))
        if not groups:
            return "No groups have been created."
        return "\n".join(
            f"`{group.id}` **{group.name}** — {group.memberships.where(GroupMembership.active).count()} members"
            for group in groups
        )
    if action == "create":
        _require_manage(ctx, "manage_groups")
        if len(args) < 2:
            raise CommandError("Usage: `!group create <name>`")
        group = GroupService.create(guild, " ".join(args[1:]))
        return f"Group **{group.name}** created (`{group.id}`)."
    if action == "members":
        if len(args) < 2:
            raise CommandError("Usage: `!group members <group-id>`")
        try:
            group_id = int(args[1])
        except ValueError as error:
            raise CommandError("Group ID must be numeric.") from error
        group = Group.get_or_none((Group.guild == guild) & (Group.id == group_id))
        if group is None:
            raise CommandError("Group not found.")
        members = (
            GroupMembership.select()
            .where((GroupMembership.group == group) & GroupMembership.active)
            .order_by(GroupMembership.joined_at)
        )
        return (
            "\n".join(f"- {membership.account.display_name}" for membership in members)
            or "This group has no members."
        )
    if action in {"join", "add"}:
        if action == "add":
            if len(args) < 3:
                raise CommandError("Usage: `!group add <group-name> <user>`")
            group = _resolve_group(guild, " ".join(args[1:-1]))
            target_user = _user_id(args[-1])
        else:
            if len(args) < 2:
                raise CommandError("Usage: `!group join <group-name>`")
            group = _resolve_group(guild, " ".join(args[1:]))
            target_user = None
        if action == "add":
            _require_manage(ctx, "manage_group_members")
        account = await _account(ctx, target_user)
        GroupService.add_member(group, account)
        return f"{account.display_name} joined **{group.name}**."
    if action == "remove":
        _require_manage(ctx, "manage_group_members")
        if len(args) < 2:
            raise CommandError("Usage: `!group remove <group-id> <user>`")
        group = Group.get_or_none((Group.guild == guild) & (Group.id == int(args[1])))
        if group is None:
            raise CommandError("Group not found.")
        account = await _account(ctx, _user_id(args[2]) if len(args) > 2 else None)
        return (
            f"{account.display_name} removed from **{group.name}**."
            if GroupService.remove_member(group, account)
            else "That user is not in the group."
        )
    raise CommandError("Usage: `!group list|members|create|join|add|remove ...`")


async def cmd_event(args: list[str], context: CommandContext | None = None) -> str:
    ctx = _require_context(context)
    guild = _guild(ctx)
    action = args[0].lower() if args else "list"
    if action == "list":
        events = EventService.list(guild)
        return (
            "\n".join(
                f"`{event.id}` **{event.name}** — {event.starts_at:%Y-%m-%d %H:%M} UTC "
                f"({len(EventService.participants(event))} participants)"
                for event in events
            )
            or "No active events."
        )
    if action == "create":
        _require_manage(ctx, "manage_events")
        if len(args) < 3:
            raise CommandError("Usage: `!event create <YYYY-MM-DDTHH:MM> <name>`")
        try:
            starts_at = datetime.fromisoformat(args[1])
        except ValueError as error:
            raise CommandError("Invalid date. Use YYYY-MM-DDTHH:MM.") from error
        event = EventService.create(guild, " ".join(args[2:]), starts_at, ctx.member.id)
        return f"Event **{event.name}** created (`{event.id}`)."
    if action in {"join", "leave"}:
        if len(args) < 2:
            raise CommandError(f"Usage: `!event {action} <event-id>`")
        try:
            event_id = int(args[1])
        except ValueError as error:
            raise CommandError("Event ID must be numeric.") from error
        event = EventService.get(guild, event_id)
        if event is None:
            raise CommandError("Event not found.")
        account = await _account(ctx)
        if action == "join":
            EventService.join(event, account)
            return f"{account.display_name} joined **{event.name}**."
        return (
            f"{account.display_name} left **{event.name}**."
            if EventService.leave(event, account)
            else "You are not registered for that event."
        )
    if action == "participants":
        if len(args) < 2:
            raise CommandError("Usage: `!event participants <event-id>`")
        try:
            event_id = int(args[1])
        except ValueError as error:
            raise CommandError("Event ID must be numeric.") from error
        event = EventService.get(guild, event_id)
        if event is None:
            raise CommandError("Event not found.")
        return (
            "\n".join(f"- {account.display_name}" for account in EventService.participants(event))
            or "This event has no participants."
        )
    raise CommandError("Usage: `!event list|create|join|leave|participants ...`")


async def cmd_help(args: list[str], context: CommandContext | None = None) -> str:
    return (
        "**Analytics commands**\n"
        "`!info [user]` — account and group\n"
        "`!stats [user]` — messages, words, characters\n"
        "`!voice [user]` — voice sessions and duration\n"
        "`!group list|members|create|join|add|remove ...`\n"
        "Use `!group add <group-name> <user>` for member management.\n"
        "`!event list|create|join|leave|participants ...`\n"
        "`!ping`"
    )


COMMANDS = {
    "ping": cmd_ping,
    "help": cmd_help,
    "info": cmd_info,
    "stats": cmd_stats,
    "voice": cmd_voice,
    "group": cmd_group,
    "groups": cmd_group,
    "event": cmd_event,
    "events": cmd_event,
}


async def dispatch(
    content: str, prefix: str, context: CommandContext | None = None
) -> str:
    raw = content[len(prefix) :].strip()
    if not raw:
        raise CommandError("Empty command. Try `!help`.")
    parts = _split(raw)
    handler = COMMANDS.get(parts[0].lower())
    if handler is None:
        raise CommandError(f"Unknown command `{parts[0]}`. Try `!help`.")
    return await handler(parts[1:], context)
