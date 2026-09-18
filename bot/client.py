import logging

import discord

from bot.commands import CommandContext, CommandError, dispatch
from config import config
from core.analytics import (
    close_voice_session,
    get_open_voice_sessions,
    open_voice_session,
    record_message,
)

logger = logging.getLogger("entt.bot")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


async def _send_result(
    msg: discord.Message, source: str, content: str, handler
) -> None:
    try:
        reply = await handler(content)
        await msg.channel.send(reply)
    except CommandError as e:
        await msg.channel.send(f"⚠️ {e}")
    except Exception:
        logger.exception("Unhandled error processing %s: %s", source, content)
        await msg.channel.send(f"⚠️ Something went wrong processing that {source}.")


@client.event
async def on_ready() -> None:
    await synchronize_voice_sessions()
    logger.info("Discord bot logged in as %s", client.user)


async def synchronize_voice_sessions() -> None:
    """Reconcile persisted sessions with members currently connected to voice."""
    for session in get_open_voice_sessions():
        close_voice_session(session.guild.discord_id, session.account.discord_id)

    active_users: set[tuple[int, int]] = set()
    for guild in client.guilds:
        for channel in guild.voice_channels:
            for member in channel.members:
                if member.bot:
                    continue
                key = (guild.id, member.id)
                if key in active_users:
                    continue
                active_users.add(key)
                open_voice_session(
                    guild_id=guild.id,
                    guild_name=guild.name,
                    discord_user_id=member.id,
                    display_name=member.display_name,
                    channel_id=channel.id,
                )


@client.event
async def on_message(msg: discord.Message) -> None:
    if msg.author == client.user:
        return
    if msg.guild is None:
        return

    record_message(
        guild_id=msg.guild.id,
        guild_name=msg.guild.name,
        discord_user_id=msg.author.id,
        display_name=msg.author.display_name,
        message_id=msg.id,
        channel_id=msg.channel.id,
        content=msg.content,
        created_at=msg.created_at,
    )

    content = msg.content.strip()
    if content.startswith(config.command_prefix):
        await _send_result(
            msg,
            "command",
            content,
            lambda raw: dispatch(
                raw,
                config.command_prefix,
                CommandContext(
                    guild=msg.guild,
                    member=msg.author,
                    display_name=(
                        getattr(msg.author, "display_name", None)
                        or getattr(msg.author, "global_name", None)
                        or getattr(msg.author, "name", None)
                        or ""
                    ),
                ),
            ),
        )
        return


@client.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    if member.bot or before.channel == after.channel:
        return

    if before.channel is not None:
        close_voice_session(member.guild.id, member.id)

    if after.channel is not None:
        open_voice_session(
            guild_id=member.guild.id,
            guild_name=member.guild.name,
            discord_user_id=member.id,
            display_name=member.display_name,
            channel_id=after.channel.id,
        )


async def start_bot() -> None:
    token = config.discord_token
    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN is not set. Add it to your .env file or environment."
        )
    async with client:
        await client.start(token)
