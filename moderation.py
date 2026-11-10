import discord
from discord import app_commands
from discord.ext import commands


class Moderation(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  @app_commands.command(
      name='purge', description='Clear a specific number of messages'
  )
  @app_commands.checks.has_permissions(manage_messages=True)
  async def purge(self, interaction: discord.Interaction, amount: int):
    if amount < 1:
      return await interaction.response.send_message(
          '❌ Specify a number greater than 0!', ephemeral=True
      )
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(
        f'🧹 Deleted `{len(deleted)}` messages.', ephemeral=True
    )

  @app_commands.command(
      name='kick', description='Kick a member from the server'
  )
  @app_commands.checks.has_permissions(kick_members=True)
  async def kick(
      self,
      interaction: discord.Interaction,
      member: discord.Member,
      reason: str = 'No reason provided',
  ):
    await member.kick(reason=reason)
    await interaction.response.send_message(
        f'👢 **{member.display_name}** has been kicked. Reason: {reason}'
    )

  @app_commands.command(name='ban', description='Ban a member from the server')
  @app_commands.checks.has_permissions(ban_members=True)
  async def ban(
      self,
      interaction: discord.Interaction,
      member: discord.Member,
      reason: str = 'No reason provided',
  ):
    await member.ban(reason=reason)
    await interaction.response.send_message(
        f'🔨 **{member.display_name}** has been banned. Reason: {reason}'
    )


async def setup(bot):
  await bot.add_cog(Moderation(bot))
