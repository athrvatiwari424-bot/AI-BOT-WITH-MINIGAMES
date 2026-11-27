from datetime import timedelta
import aiosqlite
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
        guild = interaction.guild
        actor = interaction.user
        bot_member = guild.me if guild else None
        if not guild or not isinstance(actor, discord.Member) or not actor.guild_permissions.moderate_members:
            return await interaction.response.send_message("Missing Moderate Members permission.", ephemeral=True)
        if self.target_member.guild.id != guild.id or self.target_member.id in (actor.id, guild.owner_id):
            return await interaction.response.send_message("You cannot timeout yourself or the server owner.", ephemeral=True)
        if actor.id != guild.owner_id and self.target_member.top_role >= actor.top_role:
            return await interaction.response.send_message("Your highest role must be above the target's role.", ephemeral=True)
        if not bot_member or not bot_member.guild_permissions.moderate_members or self.target_member.top_role >= bot_member.top_role:
            return await interaction.response.send_message("The bot lacks permission or role hierarchy to timeout that member.", ephemeral=True)
        try:
            mins = int(self.duration_minutes.value)
            if not 1 <= mins <= 40320:
                return await interaction.response.send_message("Duration must be between 1 minute and 28 days.", ephemeral=True)
            await self.target_member.timeout(timedelta(minutes=mins), reason=f"{self.reason.value or 'No reason provided'} (By: {actor})")
            await interaction.response.send_message(f"⏳ **{self.target_member.display_name}** timed out for `{mins} minutes`.")
        except ValueError:
            await interaction.response.send_message("Enter a whole number of minutes.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Discord denied the timeout. Check bot permissions and role hierarchy.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("The timeout failed due to a Discord API error.", ephemeral=True)


class ReasonModal(discord.ui.Modal):
    reason = discord.ui.TextInput(label="Reason", placeholder="Enter reason...", default="No reason provided", required=False)

    def __init__(self, target_member: discord.Member, action_type: str):
        super().__init__(title=f"{action_type.capitalize()} {target_member.display_name}")
        self.target_member = target_member
        self.action_type = action_type

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        actor = interaction.user
        bot_member = guild.me if guild else None
        permission = "kick_members" if self.action_type == "kick" else "ban_members"
        if not guild or not isinstance(actor, discord.Member) or not getattr(actor.guild_permissions, permission):
            return await interaction.response.send_message(f"Missing {permission.replace('_', ' ').title()} permission.", ephemeral=True)
        if self.target_member.guild.id != guild.id or self.target_member.id in (actor.id, guild.owner_id):
            return await interaction.response.send_message("You cannot punish yourself or the server owner.", ephemeral=True)
        if actor.id != guild.owner_id and self.target_member.top_role >= actor.top_role:
            return await interaction.response.send_message("Your highest role must be above the target's role.", ephemeral=True)
        if not bot_member or not getattr(bot_member.guild_permissions, permission) or self.target_member.top_role >= bot_member.top_role:
            return await interaction.response.send_message("The bot lacks permission or role hierarchy to perform that action.", ephemeral=True)
        reason = (self.reason.value or "No reason provided")[:400]
        try:
            if self.action_type == "kick":
                await self.target_member.kick(reason=f"{reason} (By: {actor})")
                response = f"👢 **{self.target_member.display_name}** has been kicked."
            else:
                await self.target_member.ban(reason=f"{reason} (By: {actor})")
                response = f"🔨 **{self.target_member.display_name}** has been banned."
            await interaction.response.send_message(response)
        except discord.Forbidden:
            await interaction.response.send_message("Discord denied the action. Check bot permissions and role hierarchy.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("The action failed due to a Discord API error.", ephemeral=True)


class PurgeModal(discord.ui.Modal, title="Custom Purge"):
    amount = discord.ui.TextInput(label="Number of messages to delete", placeholder="e.g., 25, 50, 100", default="10", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.channel
        guild = interaction.guild
        actor = interaction.user
        bot_member = guild.me if guild else None
        if not isinstance(actor, discord.Member) or not actor.guild_permissions.manage_messages:
            return await interaction.response.send_message("Manage Messages permission is required.", ephemeral=True)
        if not isinstance(channel, discord.TextChannel) or not bot_member or not channel.permissions_for(bot_member).manage_messages or not channel.permissions_for(bot_member).read_message_history:
            return await interaction.response.send_message("The bot needs Manage Messages and Read Message History in this channel.", ephemeral=True)
        try:
            limit = int(self.amount.value)
            if not 1 <= limit <= 100:
                return await interaction.response.send_message("Specify a number from 1 to 100.", ephemeral=True)
            deleted = await channel.purge(limit=limit)
            await interaction.response.send_message(f"🧹 Cleared `{len(deleted)}` messages by {actor.mention}.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Enter a whole number from 1 to 100.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Discord denied the purge. Check channel permissions.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("The purge failed due to a Discord API error.", ephemeral=True)


class PunishmentView(discord.ui.View):
    def __init__(self, target_member: discord.Member):
        super().__init__(timeout=120)
        self.target_member = target_member

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        actor = interaction.user
        bot_member = guild.me if guild else None
        if not guild or not isinstance(actor, discord.Member) or not actor.guild_permissions.moderate_members:
            await interaction.response.send_message("🚫 Moderate Members permission is required.", ephemeral=True)
            return False
        target = self.target_member
        if target.id in (actor.id, guild.owner_id) or (actor.id != guild.owner_id and target.top_role >= actor.top_role):
            await interaction.response.send_message("🚫 You cannot moderate yourself, the server owner, or a member at/above your role.", ephemeral=True)
            return False
        if not bot_member or target.top_role >= bot_member.top_role:
            await interaction.response.send_message("🚫 The bot's highest role must be above the target's role.", ephemeral=True)
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

    async def cog_load(self):
        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("""CREATE TABLE IF NOT EXISTS emergency_lockdown (
                guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
                send_messages INTEGER NOT NULL, connect INTEGER NOT NULL, speak INTEGER NOT NULL,
                PRIMARY KEY (guild_id, channel_id))""")
            await db.commit()

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

    @app_commands.guild_only()
    @app_commands.command(name="button", description="Access emergency server lockdown and restore controls")
    @app_commands.describe(choice="Choose emergency button: red or green")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Red Button (Nightmare Mode Lockdown)", value="red"),
        app_commands.Choice(name="Green Button (Restore Saved Permissions)", value="green"),
    ])
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def button(self, interaction: discord.Interaction, choice: str):
        guild = interaction.guild
        bot_member = guild.me if guild else None
        if not guild or not bot_member:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        if not bot_member.guild_permissions.manage_channels:
            return await interaction.response.send_message("I need Manage Channels permission to use emergency controls.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        changed = 0
        failed = 0
        async with aiosqlite.connect("bot_data.db") as db:
            if choice == "red":
                for channel in guild.channels:
                    try:
                        overwrite = channel.overwrites_for(guild.default_role)
                        encode = lambda value: -1 if value is None else int(value)
                        await db.execute(
                            "INSERT OR IGNORE INTO emergency_lockdown(guild_id,channel_id,send_messages,connect,speak) VALUES(?,?,?,?,?)",
                            (guild.id, channel.id, encode(overwrite.send_messages), encode(overwrite.connect), encode(overwrite.speak)),
                        )
                        overwrite.send_messages = False
                        overwrite.connect = False
                        overwrite.speak = False
                        await channel.set_permissions(guild.default_role, overwrite=overwrite, reason=f"Emergency lockdown by {interaction.user}")
                        changed += 1
                    except (discord.Forbidden, discord.HTTPException):
                        failed += 1
                await db.commit()
                await interaction.followup.send(f"🚨 Emergency lockdown applied to **{changed}** channels. {failed} could not be changed. Original @everyone permission values have been saved for restoration.", ephemeral=True)
                return

            async with db.execute(
                "SELECT channel_id,send_messages,connect,speak FROM emergency_lockdown WHERE guild_id=?",
                (guild.id,),
            ) as cursor:
                saved = await cursor.fetchall()
            if not saved:
                return await interaction.followup.send("No saved emergency lockdown exists for this server, so I did not change any permissions.", ephemeral=True)
            for channel_id, send_value, connect_value, speak_value in saved:
                channel = guild.get_channel(channel_id)
                if channel is None:
                    continue
                try:
                    overwrite = channel.overwrites_for(guild.default_role)
                    decode = lambda value: None if value == -1 else bool(value)
                    overwrite.send_messages = decode(send_value)
                    overwrite.connect = decode(connect_value)
                    overwrite.speak = decode(speak_value)
                    await channel.set_permissions(guild.default_role, overwrite=overwrite, reason=f"Emergency lockdown restored by {interaction.user}")
                    changed += 1
                    await db.execute("DELETE FROM emergency_lockdown WHERE guild_id=? AND channel_id=?", (guild.id, channel_id))
                except (discord.Forbidden, discord.HTTPException):
                    failed += 1
            await db.commit()
        await interaction.followup.send(f"🟢 Restored saved @everyone permissions in **{changed}** channels. {failed} could not be restored; their snapshots remain saved so you can retry.", ephemeral=True)



async def setup(bot):
    await bot.add_cog(Moderation(bot))
