import discord
from discord import app_commands
from discord.ext import commands


# --- DROPDOWN VIEW FOR PUNISHMENTS ---
class PunishmentSelect(discord.ui.Select):

  def __init__(self, target_member: discord.Member):
    self.target_member = target_member
    options = [
        discord.SelectOption(
            label='Timeout',
            description='Timeout member for 10 minutes',
            emoji='⏳',
            value='timeout',
        ),
        discord.SelectOption(
            label='Remove Timeout',
            description='Remove timeout from member',
            emoji='🔊',
            value='untimeout',
        ),
        discord.SelectOption(
            label='Kick',
            description='Kick member from the server',
            emoji='👢',
            value='kick',
        ),
        discord.SelectOption(
            label='Ban',
            description='Ban member from the server',
            emoji='🔨',
            value='ban',
        ),
    ]
    super().__init__(
        placeholder='Choose a punishment action...',
        min_values=1,
        max_values=1,
        options=options,
    )

  async def callback(self, interaction: discord.Interaction):
    action = self.values[0]
    guild = interaction.guild

    if action == 'timeout':
      try:
        from datetime import timedelta

        await self.target_member.timeout(
            timedelta(minutes=10), reason=f'Punishment menu by {interaction.user}'
        )
        await interaction.response.send_message(
            f'⏳ **{self.target_member.display_name}** has been timed out for 10'
            ' minutes.',
            ephemeral=True,
        )
      except Exception as e:
        await interaction.response.send_message(
            f'❌ Failed to timeout: {e}', ephemeral=True
        )

    elif action == 'untimeout':
      try:
        await self.target_member.timeout(
            None, reason=f'Timeout removed by {interaction.user}'
        )
        await interaction.response.send_message(
            f'🔊 Timeout removed for **{self.target_member.display_name}**.',
            ephemeral=True,
        )
      except Exception as e:
        await interaction.response.send_message(
            f'❌ Failed to remove timeout: {e}', ephemeral=True
        )

    elif action == 'kick':
      try:
        await self.target_member.kick(
            reason=f'Punishment menu by {interaction.user}'
        )
        await interaction.response.send_message(
            f'👢 **{self.target_member.display_name}** has been kicked.',
            ephemeral=True,
        )
      except Exception as e:
        await interaction.response.send_message(
            f'❌ Failed to kick: {e}', ephemeral=True
        )

    elif action == 'ban':
      try:
        await self.target_member.ban(
            reason=f'Punishment menu by {interaction.user}'
        )
        await interaction.response.send_message(
            f'🔨 **{self.target_member.display_name}** has been banned.',
            ephemeral=True,
        )
      except Exception as e:
        await interaction.response.send_message(
            f'❌ Failed to ban: {e}', ephemeral=True
        )


class PunishmentView(discord.ui.View):

  def __init__(self, target_member: discord.Member):
    super().__init__(timeout=60)
    self.add_item(PunishmentSelect(target_member))


# --- DROPDOWN VIEW FOR SERVER MANAGEMENT ---
class ManageSelect(discord.ui.Select):

  def __init__(self):
    options = [
        discord.SelectOption(
            label='Lockdown Channel',
            description='Lock the current channel',
            emoji='🔒',
            value='lock',
        ),
        discord.SelectOption(
            label='Unlock Channel',
            description='Unlock the current channel',
            emoji='🔓',
            value='unlock',
        ),
        discord.SelectOption(
            label='Clear Messages (Purge)',
            description='Delete last 10 messages',
            emoji='🧹',
            value='purge',
        ),
    ]
    super().__init__(
        placeholder='Choose a channel management action...',
        min_values=1,
        max_values=1,
        options=options,
    )

  async def callback(self, interaction: discord.Interaction):
    action = self.values[0]
    channel = interaction.channel

    if action == 'lock':
      await channel.set_permissions(
          interaction.guild.default_role,
          send_messages=False,
          reason=f'Locked by {interaction.user}',
      )
      await interaction.response.send_message(
          f'🔒 **{channel.name}** has been locked down.', ephemeral=True
      )

    elif action == 'unlock':
      await channel.set_permissions(
          interaction.guild.default_role,
          send_messages=True,
          reason=f'Unlocked by {interaction.user}',
      )
      await interaction.response.send_message(
          f'🔓 **{channel.name}** has been unlocked.', ephemeral=True
      )

    elif action == 'purge':
      deleted = await channel.purge(limit=10)
      await interaction.response.send_message(
          f'🧹 Cleared `{len(deleted)}` messages from this channel.',
          ephemeral=True,
      )


class ManageView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=60)
    self.add_item(ManageSelect())


# --- MODERATION COG ---
class Moderation(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  @app_commands.command(
      name='punishment',
      description='Open interactive punishment panel for a user',
  )
  @app_commands.checks.has_permissions(moderate_members=True)
  async def punishment(
      self, interaction: discord.Interaction, member: discord.Member
  ):
    embed = discord.Embed(
        title='🛡️ Punishment Control Panel',
        description=(
            f'Target User: **{member.mention}** (`{member.id}`)\nSelect an'
            ' action from the dropdown menu below to execute.'
        ),
        color=discord.Color.red(),
    )
    view = PunishmentView(member)
    await interaction.response.send_message(
        embed=embed, view=view, ephemeral=True
    )

  @app_commands.command(
      name='manage', description='Open channel and server management panel'
  )
  @app_commands.checks.has_permissions(manage_channels=True)
  async def manage(self, interaction: discord.Interaction):
    embed = discord.Embed(
        title='⚙️ Server & Channel Management',
        description=(
            'Select a management action for this channel from the dropdown'
            ' below.'
        ),
        color=discord.Color.blue(),
    )
    view = ManageView()
    await interaction.response.send_message(
        embed=embed, view=view, ephemeral=True
    )


async def setup(bot):
  await bot.add_cog(Moderation(bot))
