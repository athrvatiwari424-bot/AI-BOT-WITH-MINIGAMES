import asyncio
import os
import threading
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask

# --- FLASK BACKGROUND THREAD FOR RENDER ---
app = Flask(__name__)


@app.route("/")
def home():
  return "NOTTYAMERICA Bot is alive and running 24/7!"


def run_flask():
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)


# --- BOT INITIALIZATION ---
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix=".", intents=intents)


@bot.event
async def on_ready():
  print(f"✅ Logged in as {bot.user.name} ({bot.user.id})")
  try:
    synced = await bot.tree.sync()
    print(f"⚡ Successfully synced {len(synced)} slash command(s) globally!")
  except Exception as e:
    print(f"❌ Failed to sync slash commands: {e}")
  print("🚀 NOTTYAMERICA Bot is online!")


async def main():
  # Start Flask port binding thread for Render
  flask_thread = threading.Thread(target=run_flask)
  flask_thread.daemon = True
  flask_thread.start()
  print("🌐 Flask server launched on port 10000 for Render.")

  async with bot:
    # Load Cogs
    cogs = ["minigames", "moderation"]
    for cog in cogs:
      try:
        await bot.load_extension(cog)
        print(f"🎮 Loaded Extension: {cog}")
      except Exception as e:
        print(f"❌ Failed to load extension {cog}: {e}")

    token = os.getenv("DISCORD_TOKEN")
    if not token:
      raise ValueError("DISCORD_TOKEN environment variable is missing!")

    await bot.start(token)


if __name__ == "__main__":
  asyncio.run(main())
