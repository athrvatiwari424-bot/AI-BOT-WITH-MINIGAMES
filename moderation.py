import random
import string
from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands


# --- MODAL FOR CUSTOM TIMEOUT ---
class TimeoutModal(discord.ui.Modal, title="Timeout Configuration"):
  duration_minutes = discord.ui.TextInput(
      label="Duration (in minutes)",
      placeholder="e.g., 10, 60, 1440",
      default="10",
      required=True,
  )
  reason = discord.ui.TextInput(
      label="Reason",
      placeholder="Enter reason for timeout...",
      default="No reason provided",
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
          delta, reason=f"{self.reason.value} (By: {interaction.user})"
      )
      await interaction.response.send_message(
          f"⏳ **{self.target_member.display_name}** has been timed out for"
          f" `{mins} minutes`. Reason: *{self.reason.value}*"
      )
    except Exception as e:
      await interaction.response.send_message(
          f"❌ Failed to timeout: {e}", ephemeral=True
      )


# --- MODAL FOR REASON-BASED ACTIONS (Kick/Ban) ---
class ReasonModal(discord.ui.Modal):
  reason = discord.ui.TextInput(
      label="Reason",
      placeholder="Enter reason...",
      default="No reason provided",
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
      if self.action_type == "kick":
        await self.target_member.kick(
            reason=f"{self.reason.value} (By: {interaction.user})"
        )
        await interaction.response.send_message(
            f"👢 **{self.target_member.display_name}** has been kicked. Reason:"
            f" *{self.reason.value}*"
        )
      elif self.action_type == "ban":
        await self.target_member.ban(
            reason=f"{self.reason.value} (By: {interaction.user})"
        )
        await interaction.response.send_message(
            f"🔨 **{self.target_member.display_name}** has been banned. Reason:"
            f" *{self.reason.value}*"
        )
    except Exception as e:
      await interaction.response.send_message(
          f"❌ Failed to execute {self.action_type}: {e}", ephemeral=True
      )


# --- MODAL FOR CUSTOM PURGE ---
class PurgeModal(discord.ui.Modal, title="Custom Purge"):
  amount = discord.ui.TextInput(
      label="Number of messages to delete",
      placeholder="e.g., 25, 50, 100",
      default="10",
      required=True,
  )

  async def on_submit(self, interaction: discord.Interaction):
    try:
      limit = int(self.amount.value)
      if limit < 1:
        await interaction.response.send_message(
            "❌ Please specify a number greater than 0.", ephemeral=True
        )
        return

      deleted = await interaction.channel.purge(limit=limit)
      await interaction.response.send_message(
          f"🧹 Cleared `{len(deleted)}` messages by {interaction.user.mention}.",
          ephemeral=False,
      )
    except Exception as e:
      await interaction.response.send_message(
          f"❌ Failed to purge messages: {e}", ephemeral=True
      )


# --- MODAL FOR BLACK BUTTON PASSCODE CONFIRMATION ---
class BlackButtonModal(discord.ui.Modal, title="NUCLEAR PROTOCOL CONFIRMATION"):
  passcode_input = discord.ui.TextInput(
      label="Enter Passcode Shown in Embed",
      placeholder="Type the exact passcode...",
      required=True,
  )

  def __init__(self, correct_code: str):
    super().__init__()
    self.correct_code = correct_code

  async def on_submit(self, interaction: discord.Interaction):
    if self.passcode_input.value.strip() != self.correct_code:
      await interaction.response.send_message(
          "❌ **Incorrect Passcode!** Nuclear protocol aborted.", ephemeral=True
      )
      return

    await interaction.response.send_message(
        "💣 **PASSCODE ACCEPTED. INITIATING ABSOLUTE SERVER ANNIHILATION...**",
        ephemeral=False,
    )
    guild = interaction.guild

    # 1. Delete all roles except @everyone and managed/bot roles
    for role in guild.roles:
      if not role.is_default() and not role.managed and role < guild.me.top_role:
        try:
          await role.delete(reason=f"Black Button triggered by {interaction.user}")
        except Exception:
          pass

    # 2. Nuke/Clone every text channel
    for channel in list(guild.text_channels):
      try:
        new_channel = await channel.clone(
            reason=f"Black Button nuke by {interaction.user}"
        )
        await new_channel.edit(position=channel.position)
        await channel.delete()
        if channel.id == interaction.channel.id:
          await new_channel.send(
              "⚫ **THE BLACK BUTTON HAS BEEN EXECUTED.** All roles have been"
              f" purged and channels nuked by {interaction.user.mention}."
          )
      except Exception:
        pass


# --- BUTTON VIEWS ---
class PunishmentView(discord.ui.View):

  def __init__(self, target_member: discord.Member):
    super().__init__(timeout=120)
    self.target_member = target_member

  @discord.ui.button(
      label="Timeout", style=discord.ButtonStyle.blurple, emoji="⏳"
  )
  async def timeout_btn(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(TimeoutModal(self.target_member))

  @discord.ui.button(
      label="Remove Timeout", style=discord.ButtonStyle.green, emoji="🔊"
  )
  async def untimeout_btn(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await self.target_member.timeout(
        None, reason=f"Timeout removed by {interaction.user}"
    )
    await interaction.response.send_message(
        f"🔊 Timeout removed for **{self.target_member.display_name}** by"
        f" {interaction.user.mention}."
    )

  @discord.ui.button(
      label="Kick", style=discord.ButtonStyle.gray, emoji="👢"
  )
  async def kick_btn(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(
        ReasonModal(self.target_member, "kick")
    )

  @discord.ui.button(label="Ban", style=discord.ButtonStyle.red, emoji="🔨")
  async def ban_btn(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(
        ReasonModal(self.target_member, "ban")
    )


class ManageView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=120)

  @discord.ui.button(
      label="Lock Channel", style=discord.ButtonStyle.red, emoji="🔒"
  )
  async def lock_btn(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.channel.set_permissions(
        interaction.guild.default_role,
        send_messages=False,
        reason=f"Locked by {interaction.user}",
    )
    await interaction.response.send_message(
        f"🔒 **{interaction.channel.name}** has been locked down by"
        f" {interaction.user.mention}."
    )

  @discord.ui.button(
      label="Unlock Channel", style=discord.ButtonStyle.green, emoji="🔓"
  )
  async def unlock_btn(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.channel.set_permissions(
        interaction.guild.default_role,
        send_messages=True,
        reason=f"Unlocked by {interaction.user}",
    )
    await interaction.response.send_message(
        f"🔓 **{interaction.channel.name}** has been unlocked by"
        f" {interaction.user.mention}."
    )

  @discord.ui.button(
      label="Custom Purge", style=discord.ButtonStyle.gray, emoji="🧹"
  )
  async def purge_btn(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(PurgeModal())


class BlackButtonView(discord.ui.View):

  def __init__(self, passcode: str):
    super().__init__(timeout=120)
    self.passcode = passcode

  @discord.ui.button(
      label="PRESS BLACK BUTTON", style=discord.ButtonStyle.danger, emoji="🏴"
  )
  async def black_btn(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_modal(BlackButtonModal(self.passcode))


# --- MODERATION COG ---
class Moderation(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  @app_commands.command(
      name="punishment",
      description="Open interactive punishment panel for a user",
  )
  @app_commands.checks.has_permissions(moderate_members=True)
  async def punishment(
      self, interaction: discord.Interaction, member: discord.Member
  ):
    embed = discord.Embed(
        title="🛡️ Punishment Control Panel",
        description=(
            f"Target User: **{member.mention}** (`{member.id}`)\nClick a button"
            " below to execute custom actions."
        ),
        color=discord.Color.red(),
    )
    view = PunishmentView(member)
    await interaction.response.send_message(
        embed=embed, view=view, ephemeral=False
    )

  @app_commands.command(
      name="manage", description="Open channel and server management panel"
  )
  @app_commands.checks.has_permissions(manage_channels=True)
  async def manage(self, interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚙️ Server & Channel Management",
        description="Click a management action for this channel below.",
        color=discord.Color.blue(),
    )
    view = ManageView()
    await interaction.response.send_message(
        embed=embed, view=view, ephemeral=False
    )

  @app_commands.command(
      name="nuke",
      description="Clone and delete the current channel to completely wipe messages",
  )
  @app_commands.checks.has_permissions(manage_channels=True)
  async def nuke(self, interaction: discord.Interaction):
    await interaction.response.send_message(
        "💣 Nuking channel...", ephemeral=True
    )
    channel = interaction.channel
    new_channel = await channel.clone(reason=f"Nuked by {interaction.user}")
    await new_channel.edit(position=channel.position)
    await channel.delete(reason=f"Nuked by {interaction.user}")
    await new_channel.send(
        f"💥 **Channel has been successfully nuked!** Action executed by"
        f" {interaction.user.mention}."
    )

  @app_commands.command(
      name="button", description="Access emergency server control buttons"
  )
  @app_commands.describe(
      choice="Choose which emergency button to deploy: red, green, or black"
  )
  @app_commands.choices(
      choice=[
          app_commands.Choice(
              name="Red Button (Nightmare Mode Lockdown)", value="red"
          ),
          app_commands.Choice(
              name="Green Button (Restore Normal Permissions)", value="green"
          ),
          app_commands.Choice(
              name="Black Button (Ultimate Nuclear Protocol)", value="black"
          ),
      ]
  )
  @app_commands.checks.has_permissions(administrator=True)
  async def button(self, interaction: discord.Interaction, choice: str):
    if choice == "red":
      await interaction.response.send_message(
          "🚨 **NIGHTMARE MODE ACTIVATED!** Stripping server channel"
          " permissions...",
          ephemeral=False,
      )
      guild = interaction.guild
      for channel in guild.channels:
        try:
          overwrite = channel.overwrites_for(guild.default_role)
          overwrite.send_messages = False
          overwrite.connect = False
          overwrite.speak = False
          await channel.set_permissions(
              guild.default_role,
              overwrite=overwrite,
              reason=f"Nightmare Mode Red Button pressed by {interaction.user}",
          )
        except Exception:
          pass
      await interaction.followup.send(
          "🔴 **The Red Button has been pulled.** All standard channels have"
          " been completely locked down. Only administrators can speak or write."
      )

    elif choice == "green":
      await interaction.response.send_message(
          "🟢 **REVERTING NIGHTMARE MODE...** Restoring standard channel"
          " permissions...",
          ephemeral=False,
      )
      guild = interaction.guild
      for channel in guild.channels:
        try:
          overwrite = channel.overwrites_for(guild.default_role)
          overwrite.send_messages = None
          overwrite.connect = None
          overwrite.speak = None
          await channel.set_permissions(
              guild.default_role,
              overwrite=overwrite,
              reason=f"Green Button pressed by {interaction.user}",
          )
        except Exception:
          pass
      await interaction.followup.send(
          "🟢 **The Green Button has been pressed.** All channels have been"
          " restored to their normal permissions!"
      )

    elif choice == "black":
      passcode = "".join(
          random.choices(string.ascii_uppercase + string.digits, k=6)
      )
      embed = discord.Embed(
          title="🏴‍☠️ BLACK BUTTON - NUCLEAR PROTOCOL WARNING",
          description=(
              "**WARNING:** Pressing this button and entering the correct"
              " passcode will **permanently delete all server roles** and"
              " **nuke all channels**!\n\n"
              f"🔐 **REQUIRED PASSCODE:** ```{passcode}```\n\n"
              "Click the button below and type this passcode to confirm."
          ),
          color=discord.Color.dark_embed(),
      )
      view = BlackButtonView(passcode)
      await interaction.response.send_message(
          embed=embed, view=view, ephemeral=False
      )


async def setup(bot):
  await bot.add_cog(Moderation(bot))
