import asyncio
from datetime import datetime
import json
import logging
from json import loads
from os import environ
import traceback

import aiosqlite
import discord
from discord.ext import commands

from utils import *

# --- CONFIGURATION SETUP ---
with open('config.json') as f:
  logging.basicConfig(level=logging.INFO)
  config = json.load(f)

  if config.get('stage') == 'Prod':
    default_prefix = config['default_prefix']
    token = config['token']
  else:
    default_prefix = config['beta_prefix']
    token = config['beta_token']


# --- DYNAMIC PREFIX RETRIEVAL ---
async def get_prefix(bot: commands.Bot, message: discord.Message):
  bot_id = bot.user.id

  if message.guild is None:
    server_prefix = (
        default_prefix[0] if isinstance(default_prefix, list) else default_prefix
    )
  else:
    try:
      server_prefix = bot.guild_settings_cache[message.guild.id]['prefix']
    except Exception as e:
      server_prefix = (
          default_prefix[0]
          if isinstance(default_prefix, list)
          else default_prefix
      )
      if bot.db is not None:
        try:
          cursor = await bot.db.execute_fetchall(
              'SELECT guild_id, prefix FROM prefixes WHERE guild_id == (?);',
              (message.guild.id,),
          )
          if len(cursor) == 0:
            to_enter = (message.guild.id, server_prefix)
            await bot.db.execute_insert(
                'INSERT INTO prefixes(guild_id, prefix) VALUES (?,?);', to_enter
            )
            await bot.db.commit()
          else:
            server_prefix = cursor[0][1]
            bot.guild_settings_cache[message.guild.id] = {
                'prefix': server_prefix
            }
        except Exception:
          traceback.print_exc()

  p1 = default_prefix[0] if isinstance(default_prefix, list) else default_prefix
  p2 = (
      default_prefix[1]
      if isinstance(default_prefix, list) and len(default_prefix) > 1
      else p1
  )

  return [f'<@{bot_id}> ', f'<@!{bot_id}> ', p1, p2, server_prefix]


# --- INTENTS SETUP ---
ClientIntents = discord.Intents.default()
ClientIntents.guilds = True
ClientIntents.members = True
ClientIntents.emojis = True
ClientIntents.messages = True
ClientIntents.message_content = True  # Required for d.py v2.x prefix commands
ClientIntents.reactions = True


# --- MAIN BOT CLIENT ---
class Client(commands.Bot):

  def __init__(self):
    super().__init__(
        command_prefix=get_prefix,
        case_insensitive=True,
        description='I host single and multiplayer games for Hand Cricket!',
        intents=ClientIntents,
        owner_id=278094147901194242,
        allowed_mentions=discord.AllowedMentions(
            everyone=False, users=True, roles=True
        ),
    )

    self.version = '5.0a'
    self.log = logging.getLogger()
    self.games = {}
    self.db = None
    self.debug_channel = 753194446710898698
    self.bot_extensions = [
        'defaultcog',
        'ownercog',
        'multiplayer',
        'eventloops',
        'misccog',
        'runrace',
        'general',
        'helpcommand',
        'social',
        'minigames',
        'cricket',
        'moderation',
    ]
    self.launched_at = None
    self.guild_settings_cache = {}
    self.last_message_cache = {}
    self.user_profile_cache = {}

    self.invite_link = 'https://discord.com/api/oauth2/authorize?client_id=753191385296928808&permissions=1144388672&scope=bot'
    self.support_server = 'https://discord.gg/Mb9s5sVkSz'

  # --- ASYNC SETUP HOOK (d.py v2.x Standard) ---
  async def setup_hook(self):
    # 1. Connect to SQLite Database
    self.db = await aiosqlite.connect('data.db')
    print('✅ Successfully established connection with SQLite database.')

    # 2. Cache Guild Prefixes
    prefix_data = await self.db.execute_fetchall(
        'SELECT guild_id, prefix FROM prefixes;'
    )
    for row in prefix_data:
      self.guild_settings_cache[row[0]] = {'prefix': row[1]}
    print('✅ Guild settings successfully cached.')

    # 3. Cache User Profiles
    try:
      user_data = await self.db.execute_fetchall('SELECT * FROM profiles;')
      for row in user_data:
        self.user_profile_cache[row[0]] = {
            'name': row[1],
            'description': row[2],
            'matches_played': row[3],
            'matches_won': row[4],
            'matches_lost': row[5],
            'runs': row[6],
            'balls': row[7],
            'wickets': row[8],
            'wickets_lost': row[9],
            'highest_score': row[10],
            'hattricks': row[11],
            'ducks': row[12],
            'batting_average': row[13],
            'match_log': loads(row[14]) if row[14] else [],
            'status': row[15],
            'created_at': row[16],
        }
      print('✅ User profiles successfully cached.')
    except Exception as e:
      print(f'⚠️ Warning loading profiles: {e}')

    # 4. Async Load Extensions / Cogs
    ext_count = 0
    for extension in self.bot_extensions:
      try:
        await self.load_extension(extension)
        print(f'⚙️ Loaded cog: {extension}')
        ext_count += 1
      except Exception as e:
        print(f'❌ Cog {extension} could not be loaded: {e}')

    try:
      await self.load_extension('globalevents')
      print('⚙️ Loaded globalevents cog.')
    except Exception as e:
      print(f'❌ Global events failed to load: {e}')

    # 5. Sync Slash Commands Globally
    try:
      synced = await self.tree.sync()
      print(f'⚡ Synced {len(synced)} Slash Command(s) globally!')
    except Exception as e:
      print(f'❌ Failed to sync slash commands: {e}')

  async def on_ready(self):
    print(
        f'\n🚀 Logged in as {self.user}\n'
        f'📦 discord.py Version: {discord.__version__}\n'
    )
    await self.change_presence(
      activity=discord.Activity(
          type=discord.ActivityType.listening, name='Hand Cricket | /cricket'
      )
    )

  @property
  def send_invite_link(self):
    return self.invite_link

  @property
  def send_support_server(self):
    return self.support_server

  @property
  def prefix(self):
    return (
        default_prefix[0]
        if isinstance(default_prefix, list)
        else default_prefix
    )

  def run(self, *args, **kwargs):
    self.launched_at = datetime.now()
    super().run(*args, **kwargs)

  async def on_message(self, message):
    if message.author.bot:
      return
    if message.content.replace('!', '').strip() == self.user.mention:
      await message.channel.send(f'My default prefix is `{self.prefix}`')
    await self.process_commands(message)

  async def on_disconnect(self):
    print(f'🔌 Bot disconnected @ {datetime.now()}')

  # --- ERROR HANDLING ---
  async def on_command_error(self, context, exception):
    if isinstance(exception, commands.CommandNotFound):
      return

    elif isinstance(exception, commands.CheckFailure):
      return await context.send(str(exception))

    elif isinstance(exception, commands.CommandOnCooldown):
      return await context.send(
          embed=discord.Embed(
              color=BASICRED,
              description=(
                  ':x: Command on cooldown, try after'
                  f' {round(exception.retry_after)} seconds.'
              ),
          )
      )

    elif isinstance(exception, commands.MissingRequiredArgument):
      return await context.send(
          embed=discord.Embed(
              color=BASICRED,
              description=(
                  f':x: Missing required argument.\n\nUsage:\n```'
                  f'{context.command.usage or context.command.name}```'
              ),
          )
      )

    elif isinstance(exception, commands.MissingPermissions):
      return await context.send(
          embed=discord.Embed(
              color=BASICRED,
              description=(
                  ':x: Missing permissions!'
                  f' {", ".join(exception.missing_permissions)}'
              ),
          )
      )

    else:
      print(f'❌ Error in command {context.command}: {exception}')
      traceback.print_exception(
          type(exception), exception, exception.__traceback__
      )

  # --- REACTION JOIN LISTENER ---
  async def on_reaction_add(self, reaction, user):
    if user.bot:
      return
    if str(reaction.emoji) != misc_emojis.get('rtj'):
      return
    if reaction.message.channel.id not in self.games:
      return

    game = self.games[reaction.message.channel.id]
    if game.type not in (GameType.MULTI, GameType.RUNRACE):
      return
    if check_for_other_games(self, user):
      return

    if not game.debounce:
      game.debounce = True
      game.players_queue.append(user)
      await asyncio.sleep(3)

      joined = ''
      for q_user in game.players_queue:
        if game.type == GameType.MULTI and len(game.players) >= 20:
          break
        elif game.type == GameType.RUNRACE and len(game.players) >= 10:
          break

        if q_user not in game.players:
          game.players.append(q_user)
          if game.type == GameType.MULTI and game.shuffled:
            if len(game.TeamA) < len(game.TeamB):
              game.TeamA.append(q_user)
            else:
              game.TeamB.append(q_user)
          joined += f'{q_user.name}, '

      game.debounce = False
      game.players_queue = []
      if joined:
        return await game.channel.send(
            f'**{joined[:-2]} has joined the game. ✅**'
        )

  # --- GUILD EVENT HANDLERS ---
  async def on_guild_join(self, guild: discord.Guild):
    p = default_prefix[0] if isinstance(default_prefix, list) else default_prefix
    if self.db:
      await self.db.execute_insert(
          'INSERT INTO prefixes(guild_id, prefix) VALUES (?,?);', (guild.id, p)
      )
      await self.db.commit()
    self.guild_settings_cache[guild.id] = {'prefix': p}

  async def on_guild_remove(self, guild: discord.Guild):
    for channel in guild.channels:
      if channel.id in self.games:
        self.games.pop(channel.id)

    if self.db:
      await self.db.execute(
          'DELETE FROM prefixes WHERE guild_id == (?);', (guild.id,)
      )
      await self.db.commit()
    self.guild_settings_cache.pop(guild.id, None)

  # --- CLEAN SHUTDOWN ---
  async def close(self):
    for game in list(self.games.values()):
      try:
        await game.channel.send(
            '⚠️ All ongoing matches have been abandoned due to bot shutdown!'
        )
      except Exception:
        pass
    self.games.clear()

    if self.db:
      await self.db.commit()
      await self.db.close()
      print('🔒 SQLite connection closed.')

    await super().close()


# --- STARTUP ENTRY POINT ---
if __name__ == '__main__':
  environ['JISHAKU_NO_UNDERSCORE'] = 'True'
  environ['JISHAKU_NO_DM_TRACEBACK'] = 'True'
  Client().run(token, reconnect=True)
