"""Safe, create-only server structure importer for Liebe.

Supports a source guild Liebe is in and official Discord template links. It never
removes or overwrites existing target-server content.
"""
import re
from urllib.parse import urlparse
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

DISCORD_TEMPLATE_RE = re.compile(r"(?:discord\.new/|discord(?:app)?\.com/templates?/)([A-Za-z0-9-]+)", re.I)


def admin_only():
    async def predicate(interaction: discord.Interaction):
        return bool(interaction.guild and isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator)
    return app_commands.check(predicate)


class TemplateConfirmView(discord.ui.View):
    def __init__(self, cog, source_data, source_name):
        super().__init__(timeout=120)
        self.cog = cog
        self.source_data = source_data
        self.source_name = source_name

    @discord.ui.button(label="Create server structure", style=discord.ButtonStyle.success, emoji="📦")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Only a server administrator can confirm this import.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        result = await self.cog.apply_template(interaction.guild, self.source_data)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass
        await interaction.followup.send(result, ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Template import cancelled.", view=self, embed=None)


class ServerTemplates(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _fetch_discord_template(self, url: str):
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        allowed = {"discord.new", "www.discord.new", "discord.com", "www.discord.com", "discordapp.com", "www.discordapp.com", "discordtemplates.me", "www.discordtemplates.me"}
        if host not in allowed:
            raise ValueError("For safety, I can only import official Discord template links or discordtemplates.me pages. Other template websites use incompatible formats.")
        match = DISCORD_TEMPLATE_RE.search(url)
        if not match and host.endswith("discordtemplates.me"):
            timeout = aiohttp.ClientTimeout(total=12)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status != 200:
                        raise ValueError("I could not open that template page.")
                    html = await response.text()
                    match = DISCORD_TEMPLATE_RE.search(html)
        if not match:
            raise ValueError("That page does not expose an official Discord template link. Paste a Discord template URL instead.")
        code = match.group(1)
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"https://discord.com/api/v10/guilds/templates/{code}") as response:
                if response.status != 200:
                    raise ValueError(f"Discord template could not be loaded (HTTP {response.status}).")
                data = await response.json()
        source = data.get("serialized_source_guild") or {}
        if not source.get("channels"):
            raise ValueError("This Discord template does not contain a readable channel structure.")
        return source, data.get("name") or source.get("name") or "Discord template"

    def _guild_to_data(self, guild: discord.Guild):
        roles = []
        for role in sorted(guild.roles, key=lambda item: item.position):
            if role.is_default() or role.managed:
                continue
            roles.append({"id": role.id, "name": role.name, "permissions": role.permissions.value, "color": role.colour.value, "hoist": role.hoist, "mentionable": role.mentionable})
        channels = []
        for channel in guild.channels:
            if isinstance(channel, discord.CategoryChannel):
                kind = 4
            elif isinstance(channel, discord.TextChannel):
                kind = 0
            elif isinstance(channel, discord.VoiceChannel):
                kind = 2
            else:
                continue
            overwrites = []
            for target, overwrite in channel.overwrites.items():
                if isinstance(target, discord.Role):
                    allow, deny = overwrite.pair()
                    overwrites.append({"id": target.id, "type": 0, "allow": allow.value, "deny": deny.value})
            channels.append({"id": channel.id, "name": channel.name, "type": kind, "parent_id": channel.category_id, "position": channel.position, "topic": getattr(channel, "topic", None), "nsfw": getattr(channel, "nsfw", False), "slowmode": getattr(channel, "slowmode_delay", 0), "bitrate": getattr(channel, "bitrate", None), "user_limit": getattr(channel, "user_limit", 0), "overwrites": overwrites})
        return {"roles": roles, "channels": channels}

    async def apply_template(self, target: discord.Guild, data: dict) -> str:
        me = target.me
        if not me or not me.guild_permissions.manage_channels or not me.guild_permissions.manage_roles:
            return "I need Manage Channels and Manage Roles permissions in this server."
        roles = data.get("roles") or []
        channels = data.get("channels") or []
        if len(roles) > 50 or len(channels) > 100:
            return "This template is too large for one safe import (limit: 50 roles and 100 channels)."
        role_map = {}
        created_roles = 0
        # Create roles without Administrator. The command is admin-only and create-only.
        for role_data in sorted(roles, key=lambda r: int(r.get("position", 0))):
            name = str(role_data.get("name") or "Imported Role")[:100]
            permissions = discord.Permissions(int(role_data.get("permissions", 0)))
            permissions.administrator = False
            try:
                role = await target.create_role(name=name, permissions=permissions, colour=discord.Colour(int(role_data.get("color", 0))), hoist=bool(role_data.get("hoist", False)), mentionable=bool(role_data.get("mentionable", False)), reason="Liebe template import")
                role_map[int(role_data.get("id", 0))] = role
                created_roles += 1
            except discord.HTTPException:
                continue

        def make_overwrites(raw):
            result = {target.default_role: discord.PermissionOverwrite()}
            for item in raw or []:
                if int(item.get("type", 0)) != 0:
                    continue
                source_id = int(item.get("id", 0))
                dest = target.default_role if source_id == 0 else role_map.get(source_id)
                if dest is None:
                    continue
                allow = discord.Permissions(int(item.get("allow", 0)))
                deny = discord.Permissions(int(item.get("deny", 0)))
                result[dest] = discord.PermissionOverwrite.from_pair(allow, deny)
            return result

        source_channels = channels
        categories = [c for c in source_channels if int(c.get("type", -1)) == 4]
        other_channels = [c for c in source_channels if int(c.get("type", -1)) in (0, 2, 5)]
        channel_map = {}
        created_channels = 0
        for item in sorted(categories, key=lambda c: int(c.get("position", 0))):
            try:
                created = await target.create_category(str(item.get("name") or "Imported Category")[:100], overwrites=make_overwrites(item.get("permission_overwrites") or item.get("overwrites")), reason="Liebe template import")
                channel_map[int(item.get("id", 0))] = created
                created_channels += 1
            except discord.HTTPException:
                continue
        for item in sorted(other_channels, key=lambda c: int(c.get("position", 0))):
            parent = channel_map.get(int(item.get("parent_id") or 0))
            name = str(item.get("name") or "imported-channel")[:100]
            overwrites = make_overwrites(item.get("permission_overwrites") or item.get("overwrites"))
            try:
                kind = int(item.get("type", 0))
                if kind in (0, 5):
                    created = await target.create_text_channel(name, category=parent, topic=(item.get("topic") or None), nsfw=bool(item.get("nsfw", False)), slowmode_delay=min(int(item.get("rate_limit_per_user", item.get("slowmode", 0)) or 0), 21600), overwrites=overwrites, reason="Liebe template import")
                else:
                    bitrate = item.get("bitrate")
                    kwargs = {"category": parent, "overwrites": overwrites, "reason": "Liebe template import"}
                    if bitrate:
                        kwargs["bitrate"] = min(int(bitrate), target.bitrate_limit)
                    kwargs["user_limit"] = min(int(item.get("user_limit", 0) or 0), 99)
                    created = await target.create_voice_channel(name, **kwargs)
                channel_map[int(item.get("id", 0))] = created
                created_channels += 1
            except discord.HTTPException:
                continue
        return f"✅ Template structure imported. Created **{created_roles} roles** and **{created_channels} channels/categories**. Existing channels and roles were not deleted or overwritten. Administrator permission was removed from imported roles."

    @app_commands.guild_only()
    @app_commands.command(name="template-copy", description="Import a server structure from another Liebe server or Discord template link")
    @app_commands.describe(source="Source server ID or official Discord template URL")
    @admin_only()
    async def template_copy(self, interaction: discord.Interaction, source: app_commands.Range[str, 1, 500]):
        target = interaction.guild
        me = target.me
        if not me or not me.guild_permissions.manage_channels or not me.guild_permissions.manage_roles:
            return await interaction.response.send_message("I need Manage Channels and Manage Roles permissions in this server.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        source_data = None
        source_name = ""
        if source.strip().isdigit():
            source_guild = self.bot.get_guild(int(source.strip()))
            if not source_guild:
                return await interaction.followup.send("I am not in that source server, or the server ID is invalid.", ephemeral=True)
            source_data = self._guild_to_data(source_guild)
            source_name = source_guild.name
        else:
            try:
                source_data, source_name = await self._fetch_discord_template(source.strip())
            except (ValueError, aiohttp.ClientError, TimeoutError) as error:
                return await interaction.followup.send(f"Could not load template: {str(error)[:350]}", ephemeral=True)
        roles = len(source_data.get("roles", []))
        channels = len(source_data.get("channels", []))
        embed = discord.Embed(title="📦 Confirm Server Template Import", description=f"**Source:** {source_name}\n**Roles:** {roles}\n**Channels/categories:** {channels}\n\nThis adds new roles and channels to **{target.name}**. It will not delete or overwrite existing items. Imported roles will not receive Administrator permission.", color=discord.Color.blurple())
        await interaction.followup.send(embed=embed, view=TemplateConfirmView(self, source_data, source_name), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerTemplates(bot))
