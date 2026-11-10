import asyncio
import os
import discord
from discord.ext import commands

# Initialize Bot with required intents
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

# Supports both '.' prefix and slash commands
bot = commands.Bot(command_prefix=".", intents=intents)


@bot.event
async def on_ready():
  print(f"✅ Logged in as {bot.user.name} ({bot.user.id})")

  # Synchronize global slash commands tree with Discord
  try:
    synced = await bot.tree.sync()
    print(f"⚡ Successfully synced {len(synced)} slash command(s) globally!")
  except Exception as e:
    print(f"❌ Failed to sync slash commands: {e}")

  print("🚀 NOTTYAMERICA Bot is online and fully operational 24/7!")


async def main():
  async with bot:
    # Load your minigames cog
    try:
      await bot.load_extension("minigames")
      print("🎮 Loaded Extension: minigames")
    except Exception as e:
      print(f"❌ Failed to load minigames extension: {e}")

    # Start the bot using environment variable DISCORD_TOKEN
    token = os.getenv("DISCORD_TOKEN")
    if not token:
      raise ValueError(
          "DISCORD_TOKEN environment variable is missing! Make sure it is set"
          " on Render."
      )

    await bot.start(token)


if __name__ == "__main__":
  asyncio.run(main())
