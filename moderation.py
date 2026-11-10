import random
import string
from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands


# --- MODAL FOR CUSTOM TIMEOUT ---
class TimeoutModal(discord.ui.Modal, title='Timeout Configuration'):
  duration_minutes = discord.ui.TextInput(
      label='Duration (in minutes)',
      placeholder='e.g., 10, 60, 1440',
      default='10',
      required=True,
  )
  reason = discord.ui.TextInput(
      label='Reason',
      placeholder='Enter reason for timeout...',
      default='No reason provided',
      required=False,
  )

  def __init__(self, target_member: discord.Member):
    super().__init__()
    self.target_member = target_member

  async def on_submit(self, interaction: discord.Interaction):
    try:
      mins = int(self.duration_minutes.value)
      delta = timedelta(minutes=mins)
      await self.target_member.timeout(
          delta, reason=f'{self.reason.value} (By: {interaction.user})'
      )
      await interaction.response.send_message(
          f'⏳ **{self.target_member.display_name}** has been timed out for'
          f' `{mins} minutes`. Reason: *{self.reason.value}*'
      )
    except Exception as e:
      await interaction.response.send_message(
          f'❌ Failed to timeout: {e}', ephemeral=True
      )


# --- MODAL FOR REASON-BASED ACTIONS (Kick/Ban) ---
class ReasonModal(discord.ui.Modal):
  reason = discord.ui.TextInput(
      label='Reason',
      placeholder='Enter reason...',
      default='No reason provided',
      required=False,
  )

  def __init__(self, target_member: discord.Member, action_type: str):
    super().__init__(
        title=f"{action_type.capitalize()} {target_member.display_name}"
    )
    self.target_member = target_member
    self.action_type = action_type

  async def on_submit(self, interaction: discord.Interaction):
    try:
      if self.action_type == 'kick':
        await self.target_member.kick(
            reason=f'{self.reason.value} (By: {interaction.user})'
        )
        await interaction.response.send_message(
            f'👢 **{self.target_member.display_name}** has been kicked. Reason:'
            f' *{self.reason.value}*'
        )
      elif self.action_type == 'ban':
        await self.target_member.ban(
            reason=f'{self.reason.value} (By: {interaction.user})'
        )
        await interaction.response.send_message(
            f'🔨 **{self.target_member.display_name}** has been banned. Reason:'
            f' *{self.reason.value}*'
        )
    except Exception as e:
      await interaction.response.send_message(
          f'❌ Failed to execute {self.action_type}: {e}', ephemeral=True
      )


# --- MODAL FOR CUSTOM PURGE ---
class PurgeModal(discord.ui.Modal, title='Custom Purge'):
  amount = discord.ui.TextInput(
      label='Number of messages to delete',
      placeholder='e.g., 25, 50, 100',
      default='10',
      required=True,
  )

  async def on_submit(self, interaction: discord.Interaction):
    try:
      limit = int(self.amount.value)
      if limit < 1:
        await interaction.response.send_message(
            '❌ Please specify a number greater than 0.', ephemeral=True
        )
        return

      deleted = await interaction.channel.purge(limit=limit)
      await interaction.response.send_message(
          f'🧹 Cleared `{len(deleted)}` messages by {interaction.user.mention}.',
          ephemeral=False,
      )
    except Exception as e:
      await interaction.response.send_message(
          f'❌ Failed to purge messages: {e}', ephemeral=True
      )


# --- MODAL FOR BLACK BUTTON PASSCODE CONFIRMATION ---
class BlackButtonModal(discord.ui.Modal, title='NUCLEAR PROTOCOL CONFIRMATION'):
  passcode_input = discord.ui.TextInput(
      label='Enter Passcode Shown in Embed',
      placeholder='Type the exact passcode...',
      required=True,
  )

  def __init__(self, correct_code: str):
    super().__init__()
    self.correct_code = correct_code

  async def on_submit(self, interaction: discord.Interaction):
    if self.passcode_input.value.strip() != self.correct_code:
      await interaction.response.send_message(
          '❌ **Incorrect Passcode!** Nuclear protocol aborted.', ephemeral=True
      )
      return

    await interaction.response.send_message(
        '💣 **PASSCODE ACCEPTED. INITIATING ABSOLUTE SERVER ANNIHILATION...**',
        ephemeral=False,
    )
    guild = interaction.guild

    # 1. Delete all roles except @everyone and managed/bot roles
    for role in guild.roles:
      if not role.is_default() and not role.managed and role < guild.me.top_role:
        try:
          await role.delete(reason=f'Black Button triggered by {interaction.user}')
        except Exception:
          pass

    # 2. Nuke/Clone every text channel
    for channel in list(guild.text_channels):
      try:
        new_channel = await channel.clone(
            reason=f'Black Button nuke by {interaction.user}'
        )
        await new_channel.edit(position=channel.position)
        await channel.delete()
        if channel.id == interaction.channel.id:
          await new_channel.send(
              '⚫ **THE BLACK BUTTON HAS BEEN EXECUTED.** All roles have been'
              f' purged and channels nuked by {interaction.user.mention}.'
          )
      except Exception:
        pass


# --- BUTTON VIEWS ---
class PunishmentView(discord.ui.View):

  def __init__(self, target_member: discord.Member):
    super().__init__(timeout=120)
    self.target_member = target_member

  @discord.ui.button(
      label='Timeout', style=discord.ButtonStyle.blurple, emoji='⏳'
  )
  async def timeout_btn(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(TimeoutModal(self.target_member))

  @discord.ui.button(
      label='Remove Timeout', style=discord.ButtonStyle.green, emoji='🔊'
  )
  async def untimeout_btn(
      self, interaction: discord.Interaction, button: discord.ui
