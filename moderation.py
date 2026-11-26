from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands


class TimeoutModal(discord.ui.Modal, title="Timeout Configuration"):
    duration_minutes = discord.ui.TextInput(label="Duration (in minutes)", placeholder="e.g., 10, 60, 1440", default="10", required=True)
    reason = discord.ui.TextInput(label="Reason", placeholder="Enter reason for timeout...", default="No reason provided", required=False)

    def __init__(self, target_member: discord.Member):
        super().__init__()
        self.target_member = target_member

    async def on_submit(self, interaction: discord.Interaction):
        try:
            mins = int(self.duration_minutes.value)
            await self.target_member.timeout(timedelta(minutes=mins), reason=f"{self.reason.value} (By: {interaction.user})")
            await interaction.response.send_message(f"⏳ **{self.target_member.display_name}** timed out for `{mins} minutes`. Reason: *{self.reason.value}*")
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to timeout: {e}", ephemeral=True)


class ReasonModal(discord.ui.Modal):
    reason = discord.ui.TextInput(label="Reason", placeholder="Enter reason...", default="No reason provided", required=False)

    def __init__(self, target_member: discord.Member, action_type: str):
        super().__init__(title=f"{action_type.capitalize()} {target_member.display_name}")
        self.target_member = target_member
        self.action_type = action_type

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if self.action_type == "kick":
                await self.target_member.kick(reason=f"{self.reason.value} (By: {interaction.user})")
                await interaction.response.send_message(f"👢 **{self.target_member.display_name}** has been kicked. Reason: *{self.reason.value}*")
            elif self.action_type == "ban":
                await self.target_member.ban(reason=f"{self.reason.value} (By: {interaction.user})")
                await interaction.response.send_message(f"🔨 **{self.target_member.display_name}** has been banned. Reason: *{self.reason.value}*")
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to execute {self.action_type}: {e}", ephemeral=True)


class PurgeModal(discord.ui.Modal, title="Custom Purge"):
    amount = discord.ui.TextInput(label="Number of messages to delete", placeholder="e.g., 25, 50, 100", default="10", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = int(self.amount.value)
            if limit < 1:
                return await interaction.response.send_message("❌ Specify a number greater than 0.", ephemeral=True)
            deleted = await interaction.channel.purge(limit=limit)
            await interaction.response.send_message(f"🧹 Cleared `{len(deleted)}` messages by {interaction.user.mention}.")
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to purge: {e}", ephemeral=True)


class PunishmentView(discord.ui.View):
    def __init__(self, target_member: discord.Member):
        super().__init__(timeout=120)
        self.target_member = target_member

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.response.send_message("🚫 Staff only.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Timeout", style=discord.ButtonStyle.blurple, emoji="⏳")
    async def timeout_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TimeoutModal(self.target_member))

    @discord.ui.button(label="Remove Timeout", style=discord.ButtonStyle.green, emoji="🔊")
    async def untimeout_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.target_member.timeout(None, reason=f"Timeout removed by {interaction.user}")
        await interaction.response.send_message(f"🔊 Timeout removed for **{self.target_member.display_name}** by {interaction.user.mention}.")

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.gray, emoji="👢")
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.kick_members:
            return await interaction.response.send_message("🚫 Missing Kick Members permission.", ephemeral=True)
        await interaction.response.send_modal(ReasonModal(self.target_member, "kick"))

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.red, emoji="🔨")
    async def ban_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message("🚫 Missing Ban Members permission.", ephemeral=True)
        await interaction.response.send_modal(ReasonModal(self.target_member, "ban"))


class ManageView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("🚫 Staff only.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Lock Channel", style=discord.ButtonStyle.red, emoji="🔒")
    async def lock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False, reason=f"Locked by {interaction.user}")
        await interaction.response.send_message(f"🔒 **{interaction.channel.name}** locked down by {interaction.user.mention}.")

    @discord.ui.button(label="Unlock Channel", style=discord.ButtonStyle.green, emoji="🔓")
    async def unlock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True, reason=f"Unlocked by {interaction.user}")
        await interaction.response.send_message(f"🔓 **{interaction.channel.name}** unlocked by {interaction.user.mention}.")

    @discord.ui.button(label="Custom Purge", style=discord.ButtonStyle.gray, emoji="🧹")
    async def purge_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("🚫 Missing Manage Messages permission.", ephemeral=True)
        await interaction.response.send_modal(PurgeModal())


class BlackButtonView(discord.ui.View):
    def __init__(self, passcode: str):
        super().__init__(timeout=120)
        self.passcode = passcode

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("🚫 Administrators only.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="PRESS BLACK BUTTON", style=discord.ButtonStyle.danger, emoji="🏴")
    async def black_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BlackButtonModal(self.passcode))


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = "🚫 You don't have permission to use this command." if isinstance(error, app_commands.MissingPermissions) else f"❌ Error: {error}"
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="punishment", description="Open interactive punishment panel for a user")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    async def punishment(self, interaction: discord.Interaction, member: discord.Member):
        embed = discord.Embed(title="🛡️ Punishment Control Panel", description=f"Target: **{member.mention}** (`{member.id}`)", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, view=PunishmentView(member))

    @app_commands.command(name="manage", description="Open channel and server management panel")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def manage(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⚙️ Server & Channel Management", description="Select an action below.", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, view=ManageView())

    @app_commands.command(name="nuke", description="Clone and delete the current channel to wipe messages")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def nuke(self, interaction: discord.Interaction):
        from conversational_server_actions import NukeConfirmationView
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Only text channels can be reset.", ephemeral=True)
        view = NukeConfirmationView(interaction.channel, interaction.user.id)
        await interaction.response.send_message("⚠️ This will replace this channel and permanently remove its message history. Confirm below.", view=view, ephemeral=True)
        view.prompt = await interaction.original_response()

    @app_commands.command(name="button", description="Access emergency server control buttons")
    @app_commands.describe(choice="Choose emergency button: red or green")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Red Button (Nightmare Mode Lockdown)", value="red"),
        app_commands.Choice(name="Green Button (Restore Normal Permissions)", value="green"),
    ])
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def button(self, interaction: discord.Interaction, choice: str):
        guild = interaction.guild
        if choice == "red":
            await interaction.response.send_message("🚨 **NIGHTMARE MODE ACTIVATED!** Locking all channels...")
            for ch in guild.channels:
                try:
                    ow = ch.overwrites_for(guild.default_role)
                    ow.send_messages = ow.connect = ow.speak = False
                    await ch.set_permissions(guild.default_role, overwrite=ow, reason=f"Red Button by {interaction.user}")
                except Exception:
                    pass
            await interaction.followup.send("🔴 **Red Button pulled.** All standard channels locked down.")
        elif choice == "green":
            await interaction.response.send_message("🟢 **REVERTING NIGHTMARE MODE...** Restoring permissions...")
            for ch in guild.channels:
                try:
                    ow = ch.overwrites_for(guild.default_role)
                    ow.send_messages = ow.connect = ow.speak = None
                    await ch.set_permissions(guild.default_role, overwrite=ow, reason=f"Green Button by {interaction.user}")
                except Exception:
                    pass
            await interaction.followup.send("🟢 **Green Button pressed.** All channels restored!")


async def setup(bot):
    await bot.add_cog(Moderation(bot))
