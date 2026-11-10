import asyncio
from datetime import datetime
import json
import logging
from json import loads
import os
import traceback

import aiosqlite
import discord
from discord.ext import commands

from utils import *

logging.basicConfig(level=logging.INFO)

# --- CONFIGURATION SETUP (Reads from Render Environment Variables) ---
token = os.environ.get('DISCORD_TOKEN')
default_prefix = os.environ.get('BOT_PREFIX', '!')

if isinstance(default_prefix, str):
  default_prefix = [default_prefix, default_prefix]

# Optional fallback for local testing if config.json is present
if not token and os.path.exists('config.json'):
  try:
    with open('config.json') as f:
      config = json.load(f)
      if config.get('stage') == 'Prod':
        default_prefix = config['default_prefix']
        token = config['token']
      else:
        default_prefix = config['beta_prefix']
        token = config['beta_token']
  except Exception as e:
    logging.warning(f'Could not load config.json: {e}')

if not token:
  raise ValueError(
      '❌ No Discord token found! Ensure DISCORD_TOKEN is set in Render'
      ' Environment Variables.'
  )

os.environ['JISHAKU_NO_UNDERSCORE'] = 'True'

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class NottyBot(commands.Bot):

  def __init__(self):
    super().__init__(command_prefix=self.get_prefix_custom, intents=intents)
    self.db = None
    self.games = {}  # Active games tracker for minigames & cricket

  async def get_prefix_custom(self, message):
    if not message.guild:
      return default_prefix
    try:
      async with self.db.execute(
          'SELECT prefix FROM prefixes WHERE guild_id = ?;', (message.guild.id,)
      ) as cursor:
        row = await cursor.fetchone()
        if row and row[0]:
          return [row[0], row[0]]
    except Exception:
      pass
    return default_prefix

  async def setup_hook(self):
    # Initialize SQLite database and required tables
    self.db = await aiosqlite.connect('database.db')
    await self.db.execute('''
            CREATE TABLE IF NOT EXISTS prefixes (
                guild_id INTEGER PRIMARY KEY,
                prefix TEXT
            );
        ''')
    await self.db.execute('''
            CREATE TABLE IF NOT EXISTS economy (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER,
                inventory TEXT
            );
        ''')
    await self.db.commit()
    logging.info('Connected to SQLite Database and tables verified.')

    # Load all modular Cogs
    extensions = ['moderation', 'minigames', 'cricket']
    for ext in extensions:
      try:
        await self.load_extension(ext)
        logging.info(f'Loaded extension: {ext}')
      except Exception as e:
        logging.error(f'Failed to load extension {ext}: {e}')
        traceback.print_exc()

    # Sync slash commands globally
    try:
      synced = await self.tree.sync()
      logging.info(f'Synced {len(synced)} slash commands globally.')
    except Exception as e:
      logging.error(f'Failed to sync slash commands: {e}')

  async def on_ready(self):
    logging.info(f'Logged in as {self.user} (ID: {self.user.id})')
    logging.info('Bot is fully active and operational!')

  async def on_command_error(self, ctx, error):
    if isinstance(error, commands.CommandNotFound):
      return
    elif isinstance(error, commands.MissingRequiredArgument):
      await ctx.send(f'❌ Missing required argument! Check `{ctx.prefix}help`.')
    elif isinstance(error, commands.CommandOnCooldown):
      await ctx.send(f'⏳ Cooldown active. Try again in {error.retry_after:.1f}s.')
    else:
      logging.error(f'Unhandled command error: {error}')
      traceback.print_exception(
          type(error), error, error.__traceback__, chain=False
      )

  async def close(self):
    if self.db:
      await self.db.close()
    await super().close()


bot = NottyBot()


# --- UTILITY COMMANDS (Prefix / Bot Management) ---
@bot.command(name='setprefix', help='Change the server prefix')
@commands.has_permissions(administrator=True)
async def setprefix(ctx, new_prefix: str):
  await bot.db.execute(
      'INSERT OR REPLACE INTO prefixes (guild_id, prefix) VALUES (?, ?);',
      (ctx.guild.id, new_prefix),
  )
  await bot.db.commit()
  await ctx.send(f'✅ Server prefix successfully updated to `{new_prefix}`!')


@setprefix.error
async def setprefix_error(ctx, error):
  if isinstance(error, commands.MissingPermissions):
    await ctx.send('❌ You need Administrator permissions to change the prefix!')


@bot.command(name='ping', help='Check bot latency')
async def ping(ctx):
  latency = round(bot.latency * 1000)
  embed = discord.Embed(
      title='Pong! 🏓',
      description=f'Bot Latency: `{latency}ms`',
      color=discord.Color.blue(),
  )
  await ctx.send(embed=embed)


if __name__ == '__main__':
  bot.run(token)
import http.server
import socketserver
import threading

# --- RENDER PORT BINDING FIX ---
PORT = int(os.environ.get('PORT', 10000))


class HealthCheckHandler(http.server.SimpleHTTPRequestHandler):

  def do_GET(self):
    self.send_response(200)
    self.end_headers()
    self.wfile.write(b'Bot is active and running!')


def run_web_server():
  with socketserver.TCPServer(('', PORT), HealthCheckHandler) as httpd:
    logging.info(f'Health check web server running on port {PORT}')
    httpd.serve_forever()


# Start the web server in a background thread so it satisfies Render's port scanner
threading.Thread(target=run_web_server, daemon=True).start()
