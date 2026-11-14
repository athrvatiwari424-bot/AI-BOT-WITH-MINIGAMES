import os
import asyncio
import logging
from aiohttp import web
import discord
from discord.ext import commands
from database import init_db

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await init_db()
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")

async def load_extensions():
    # Removed 'game' since it lacked a setup function; kept active cogs
    initial_extensions = [
        'minigames',
        'moderation',
        'cricket',
        'music'
    ]
    
    for extension in initial_extensions:
        try:
            await bot.load_extension(extension)
            logger.info(f"Loaded extension: {extension}")
        except Exception as e:
            logger.error(f"Failed to load extension {extension}: {e}")

# Simple web server handler to satisfy Render's port binding requirement
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
        logger.info(f"Health check web server running on port {port}")
    except OSError as e:
        if e.errno == 98:
            logger.warning(f"Port {port} is already in use, skipping web server bind.")
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
