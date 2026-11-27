import os
import asyncio
import logging
from aiohttp import web
import discord
from discord.ext import commands
from database import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await init_db()
    logger.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    try:
        synced = await bot.tree.sync()
        logger.info("Synced %s slash command(s).", len(synced))
    except Exception:
        logger.exception("Failed to sync slash commands")


async def load_extensions():
    initial_extensions = [
        "minigames",
        "extended_games",
        "moderation",
        "moderation_extras",
        "cricket",
        "music",
        "ai_chat",
        "conversational_moderation",
        "conversational_moderation_help",
        "community_features",
    ]
    for extension in initial_extensions:
        try:
            await bot.load_extension(extension)
            logger.info("Loaded extension: %s", extension)
        except Exception:
            logger.exception("Failed to load extension %s", extension)
            # Conversational moderation is a core feature; don't report a healthy
            # service while silently running without it.
            if extension in ("conversational_moderation", "community_features"):
                raise


async def handle_ping(request):
    return web.Response(text="Bot is active and running!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    try:
        await site.start()
        logger.info("Health check web server running on port %s", port)
    except OSError as error:
        if error.errno == 98:
            logger.warning("Port %s is already in use, skipping web server bind.", port)
        else:
            raise


async def main():
    async with bot:
        await load_extensions()
        await start_web_server()
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            logger.error("DISCORD_TOKEN environment variable is missing!")
            return
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
