import logging
import discord
from config import config
from bot.commands import dispatch, CommandError
from bot.parsers import PARSERS
from db.database import get_channel_map, get_setting

logger = logging.getLogger("entt.bot")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


async def _send_result(msg: discord.Message, source: str, content: str, handler):
    try:
        reply = await handler(content)
        await msg.channel.send(reply)
    except CommandError as e:
        await msg.channel.send(f"⚠️ {e}")
    except Exception:
        logger.exception("Unhandled error processing %s: %s", source, content)
        await msg.channel.send(f"⚠️ Something went wrong processing that {source}.")

@client.event
async def on_ready():
    logger.info("Discord bot logged in as %s", client.user)


@client.event
async def on_message(msg: discord.Message):
    if msg.author == client.user:
        return

    content = msg.content.strip()

    if content.startswith(config.command_prefix):
        await _send_result(msg, "command", content, lambda raw: dispatch(raw, config.command_prefix))
        return

    channel_type = get_channel_map().get(msg.channel.id)
    if channel_type is None:
        return

    parser = PARSERS.get(channel_type)
    if parser is None:
        logger.warning("No parser registered for channel type %s", channel_type)
        return

    await _send_result(msg, f"{channel_type} message", content, parser)

async def start_bot():
    token = get_setting("discord_token")
    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN is not set. Add it to your .env file or environment."
        )
    async with client:
        await client.start(token)
