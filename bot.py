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
    initial_extensions = [
        'minigames',
        'moderation',
        'game',
        'cricket',
        'music'
    ]
    
    for extension in initial_extensions:
        try:
            await bot.load_extension(extension)
            logger.info(f"Loaded extension: {extension}")
        except Exception as e:
            logger.error(f"Failed to load extension {extension}: {e}")

# Simple web server handler to satisfy Render's port binding requirement if deployed as a Web Service
async def handle_ping(request):
    return web.Response(text="Bot is active and running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render assigns a dynamic port via environment variable PORT (defaults to 10000)
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server started on port {port}")

async def main():
    async with bot:
        await load_extensions()
        
        # Start the health check web server for Render in the background
        await start_web_server()
        
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            logger.error("DISCORD_TOKEN environment variable is missing!")
            return
            
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
