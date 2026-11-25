import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta


SAFE_CHANNEL_PERMISSIONS = {
    "view_channel": "view_channel",
    "send_messages": "send_messages",
    "read_message_history": "read_message_history",
    "attach_files": "attach_files",
    "embed_links": "embed_links",
    "connect": "connect",
    "speak": "speak",
}


class ModerationExtras(commands.Cog):
    """Explicit, permission-checked moderation commands and deleted-message snipe."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.deleted_messages: dict[int, tuple[int, str, str, list[str]]] = {}
        self.edited_messages: dict[int, tuple[int, str, str, str]] = {}

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild and not message.author.bot:
            attachments = [attachment.url for attachment in message.attachments]
            self.deleted_messages[message.channel.id] = (
                message.author.id,
                message.author.display_name,
                message.content or "[no text content]",
                attachments,
            )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.guild and not before.author.bot and before.content != after.content:
            self.edited_messages[before.channel.id] = (
                before.author.id,
                before.author.display_name,
                before.content or "[no text content]",
                after.content or "[no text content]",
            )

    @staticmethod
    def _can_moderate(interaction: discord.Interaction, member: discord.Member) -> bool:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            return False
        bot_member = guild.me
        if member.id == guild.owner_id or member.id == interaction.user.id:
            return False
        if member.top_role >= interaction.user.top_role and interaction.user.id != guild.owner_id:
            return False
        if bot_member is None or member.top_role >= bot_member.top_role:
            return False
        return True

    @app_commands.command(name="snipe", description="Show the most recently deleted message in this channel.")
    async def snipe(self, interaction: discord.Interaction):
        item = self.deleted_messages.get(interaction.channel_id)
        if not item:
            return await interaction.response.send_message("No recently deleted message is cached for this channel.", ephemeral=True)
        user_id, display_name, content, attachments = item
        embed = discord.Embed(title="Recently deleted message", description=content[:4000], color=discord.Color.orange())
        embed.set_author(name=display_name, icon_url=(interaction.guild.get_member(user_id).display_avatar.url if interaction.guild and interaction.guild.get_member(user_id) else None))
        if attachments:
            embed.add_field(name="Attachments", value="\n".join(attachments)[:1024], inline=False)
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="editsnipe", description="Show the most recently edited message before its edit.")
    async def editsnipe(self, interaction: discord.Interaction):
        item = self.edited_messages.get(interaction.channel_id)
        if not item:
            return await interaction.response.send_message("No recently edited message is cached for this channel.", ephemeral=True)
        user_id, display_name, before, after = item
        embed = discord.Embed(title="Recently edited message", color=discord.Color.blurple())
        embed.add_field(name="Before", value=before[:1024], inline=False)
        embed.add_field(name="After", value=after[:1024], inline=False)
        embed.set_author(name=f"{display_name} ({user_id})")
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="unban", description="Unban a user by their Discord user ID.")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        try:
            numeric_id = int(user_id)
            if numeric_id <= 0:
                raise ValueError
            entry = await interaction.guild.fetch_ban(discord.Object(id=numeric_id))
            await interaction.guild.unban(entry.user, reason=f"Unbanned by {interaction.user}")
            await interaction.response.send_message(f"✅ Unbanned **{entry.user}** (`{numeric_id}`).")
        except ValueError:
            await interaction.response.send_message("Enter a valid numeric Discord user ID.", ephemeral=True)
        except discord.NotFound:
            await interaction.response.send_message("That user is not currently banned.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I need the **Ban Members** permission to unban users.", ephemeral=True)
        except discord.HTTPException as error:
            await interaction.response.send_message(f"Unban failed: `{error}`", ephemeral=True)

    @app_commands.command(name="timeout", description="Timeout a member for a number of minutes.")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout_member(self, interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "No reason provided"):
        if not self._can_moderate(interaction, member):
            return await interaction.response.send_message("Cannot timeout yourself, the server owner, or a member at/above your or the bot's role.", ephemeral=True)
        try:
            await member.timeout(timedelta(minutes=minutes), reason=f"{reason[:400]} | By: {interaction.user}")
            await interaction.response.send_message(f"⏳ Timed out **{member.display_name}** for {minutes} minute(s).")
        except discord.Forbidden:
            await interaction.response.send_message("I lack permission or role hierarchy to timeout that member.", ephemeral=True)

    @app_commands.command(name="untimeout", description="Remove a member's timeout.")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    async def untimeout_member(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if not self._can_moderate(interaction, member):
            return await interaction.response.send_message("Cannot remove timeout for yourself, the server owner, or a member at/above your or the bot's role.", ephemeral=True)
        try:
            await member.timeout(None, reason=f"{reason[:400]} | By: {interaction.user}")
            await interaction.response.send_message(f"✅ Removed timeout for **{member.display_name}**.")
        except discord.Forbidden:
            await interaction.response.send_message("I lack permission or role hierarchy to modify that member.", ephemeral=True)

    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick_member(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if not self._can_moderate(interaction, member):
            return await interaction.response.send_message("Cannot kick yourself, the server owner, or a member at/above your or the bot's role.", ephemeral=True)
        try:
            await member.kick(reason=f"{reason[:400]} | By: {interaction.user}")
            await interaction.response.send_message(f"👢 Kicked **{member.display_name}**.")
        except discord.Forbidden:
            await interaction.response.send_message("I lack permission or role hierarchy to kick that member.", ephemeral=True)

    @app_commands.command(name="ban", description="Ban a member from the server.")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_member(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if not self._can_moderate(interaction, member):
            return await interaction.response.send_message("Cannot ban yourself, the server owner, or a member at/above your or the bot's role.", ephemeral=True)
        try:
            await member.ban(reason=f"{reason[:400]} | By: {interaction.user}")
            await interaction.response.send_message(f"🔨 Banned **{member.display_name}**.")
        except discord.Forbidden:
            await interaction.response.send_message("I lack permission or role hierarchy to ban that member.", ephemeral=True)

    @app_commands.command(name="purge", description="Delete up to 100 recent messages in this channel.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("Use this in a server text channel.", ephemeral=True)
        try:
            deleted = await channel.purge(limit=amount)
            await interaction.response.send_message(f"🧹 Deleted {len(deleted)} message(s).", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I need **Manage Messages** and **Read Message History** permissions.", ephemeral=True)

    async def _set_channel_lock(self, interaction: discord.Interaction, lock: bool):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("Use this in a server text channel.", ephemeral=True)
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = not lock
        try:
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"{'Locked' if lock else 'Unlocked'} by {interaction.user}")
            await interaction.response.send_message(f"{'🔒 Locked' if lock else '🔓 Unlocked'} **#{channel.name}**.")
        except discord.Forbidden:
            await interaction.response.send_message("I need **Manage Channels** permission to change channel permissions.", ephemeral=True)

    @app_commands.command(name="lock", description="Prevent the @everyone role from sending messages here.")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock_channel(self, interaction: discord.Interaction):
        await self._set_channel_lock(interaction, True)

    @app_commands.command(name="unlock", description="Allow the @everyone role to send messages here.")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock_channel(self, interaction: discord.Interaction):
        await self._set_channel_lock(interaction, False)

    @app_commands.command(name="role_create", description="Create a non-administrator role.")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_create(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 100]):
        try:
            role = await interaction.guild.create_role(name=name, reason=f"Created by {interaction.user}")
            await interaction.response.send_message(f"✅ Created role {role.mention} (no elevated permissions granted).", allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            await interaction.response.send_message("I need **Manage Roles** and a sufficiently high role to create roles.", ephemeral=True)

    @app_commands.command(name="role_add", description="Assign a role below your and the bot's top role to a member.")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if role.is_default() or role.managed or role >= interaction.guild.me.top_role or (interaction.user.id != interaction.guild.owner_id and role >= interaction.user.top_role):
            return await interaction.response.send_message("That role is managed or is not below your and the bot's top roles.", ephemeral=True)
        try:
            await member.add_roles(role, reason=f"Assigned by {interaction.user}")
            await interaction.response.send_message(f"✅ Added **{role.name}** to **{member.display_name}**.")
        except discord.Forbidden:
            await interaction.response.send_message("I need **Manage Roles** permission.", ephemeral=True)

    @app_commands.command(name="role_remove", description="Remove a role below your and the bot's top role from a member.")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_remove(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if role.is_default() or role.managed or role >= interaction.guild.me.top_role or (interaction.user.id != interaction.guild.owner_id and role >= interaction.user.top_role):
            return await interaction.response.send_message("That role is managed or is not below your and the bot's top roles.", ephemeral=True)
        try:
            await member.remove_roles(role, reason=f"Removed by {interaction.user}")
            await interaction.response.send_message(f"✅ Removed **{role.name}** from **{member.display_name}**.")
        except discord.Forbidden:
            await interaction.response.send_message("I need **Manage Roles** permission.", ephemeral=True)

    @app_commands.command(name="role_channel_permission", description="Set a limited, non-admin channel permission for a role.")
    @app_commands.default_permissions(manage_roles=True, manage_channels=True)
    @app_commands.checks.has_permissions(manage_roles=True, manage_channels=True)
    @app_commands.choices(permission=[app_commands.Choice(name=name.replace("_", " "), value=value) for name, value in SAFE_CHANNEL_PERMISSIONS.items()])
    async def role_channel_permission(self, interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role, permission: str, enabled: bool):
        if role.is_default() or role.managed or role >= interaction.guild.me.top_role or (interaction.user.id != interaction.guild.owner_id and role >= interaction.user.top_role):
            return await interaction.response.send_message("That role is managed or is not below your and the bot's top roles.", ephemeral=True)
        if permission not in SAFE_CHANNEL_PERMISSIONS.values():
            return await interaction.response.send_message("That permission cannot be changed with this command.", ephemeral=True)
        overwrite = channel.overwrites_for(role)
        setattr(overwrite, permission, enabled)
        try:
            await channel.set_permissions(role, overwrite=overwrite, reason=f"Channel permission changed by {interaction.user}")
            await interaction.response.send_message(f"✅ Set `{permission}` to **{enabled}** for **{role.name}** in {channel.mention}.")
        except discord.Forbidden:
            await interaction.response.send_message("I need **Manage Roles** and **Manage Channels** permissions.", ephemeral=True)

    @app_commands.command(name="audit_recent", description="Show recent server moderation audit-log entries.")
    @app_commands.default_permissions(view_audit_log=True)
    @app_commands.checks.has_permissions(view_audit_log=True)
    async def audit_recent(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 10] = 5):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        try:
            lines = []
            async for entry in interaction.guild.audit_logs(limit=amount):
                target = str(entry.target) if entry.target else "unknown target"
                actor = str(entry.user) if entry.user else "unknown actor"
                lines.append(f"• `{entry.action.name}` — {actor} → {target}")
            await interaction.response.send_message("\n".join(lines) or "No recent audit entries.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            await interaction.response.send_message("I need **View Audit Log** permission.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationExtras(bot))
