import discord
from discord import app_commands
from discord.ext import commands
from game import DoubleGame, MultiplayerGame, RunRaceGame, SingleGame


class Cricket(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  @app_commands.command(
      name='cricket', description='Start or play a game of Hand Cricket!'
  )
  @app_commands.describe(
      mode='Choose the game mode: single, multi, double, or runrace'
  )
  @app_commands.choices(
      mode=[
          app_commands.Choice(name='Singleplayer vs Bot', value='single'),
          app_commands.Choice(name='Multiplayer Team Match', value='multi'),
          app_commands.Choice(name='Double 1v1 Match', value='double'),
          app_commands.Choice(name='Run Race Battle', value='runrace'),
      ]
  )
  async def cricket(self, interaction: discord.Interaction, mode: str = 'single'):
    if not hasattr(self.bot, 'games'):
      self.bot.games = {}

    channel_id = interaction.channel.id
    if channel_id in self.bot.games:
      await interaction.response.send_message(
          '❌ A cricket game is already active in this channel!', ephemeral=True
      )
      return

    if mode == 'single':
      game = SingleGame.create(interaction, self.bot)
      self.bot.games[channel_id] = game
      embed = discord.Embed(
          title='🏏 Hand Cricket - Singleplayer',
          description=(
              f'Match started by {interaction.user.mention} against the Bot!\nType'
              ' your runs in chat.'
          ),
          color=discord.Color.blue(),
      )
      await interaction.response.send_message(embed=embed)

    elif mode == 'multi':
      game = MultiplayerGame.create(interaction, self.bot)
      self.bot.games[channel_id] = game
      embed = discord.Embed(
          title='🏏 Hand Cricket - Multiplayer Match',
          description=(
              f'Lobby created by {interaction.user.mention}!'
          ),
          color=discord.Color.green(),
      )
      await interaction.response.send_message(embed=embed)

    elif mode == 'double':
      await interaction.response.send_message(
          '⚔️ Double 1v1 mode initialized! Mention your opponent to begin.',
          ephemeral=True,
      )

    elif mode == 'runrace':
      game = RunRaceGame.create(interaction, self.bot)
      self.bot.games[channel_id] = game
      embed = discord.Embed(
          title='🏃 Hand Cricket - Run Race',
          description=(
              f'Run Race lobby created by {interaction.user.mention}!'
          ),
          color=discord.Color.orange(),
      )
      await interaction.response.send_message(embed=embed)


async def setup(bot):
  await bot.add_cog(Cricket(bot))
