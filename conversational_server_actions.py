"""Conversational server actions: role creation and safely confirmed channel reset."""

import re

import discord
from discord.ext import commands


COLOR_RE = re.compile(r"#([0-9a-fA-F]{6})\b")
HOIST_RE = re.compile(r"\bhoist\s*[:=]?\s*(true|false)\b", re.I)


class NukeConfirmationView(discord.ui.View):
    """Require the command author to explicitly confirm a channel reset."""

    def __init__(self, channel: discord.TextChannel, requester_id: int):
        super().__init__(timeout=30)
        self.channel = channel
        self.requester_id = requester_id
        self.prompt: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the moderator who started this confirmation can use it.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.manage_channels and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Manage Channels permission is required.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm channel reset", style=discord.ButtonStyle.danger, emoji="💣")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        bot_member = guild.me if guild else None
        if not guild or not bot_member or not bot_member.guild_permissions.manage_channels:
            return await interaction.response.send_message("The bot needs Manage Channels permission.", ephemeral=True)
        if self.channel.guild.id != guild.id:
            return await interaction.response.send_message("This confirmation is for another server.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        try:
            replacement = await self.channel.clone(reason=f"Channel reset confirmed by {interaction.user}")
            await replacement.edit(position=self.channel.position)
            await self.channel.delete(reason=f"Channel reset confirmed by {interaction.user}")
            await replacement.send(
                f"💣 Channel reset completed by <@{interaction.user.id}>.",
                allowed_mentions=discord.AllowedMentions(users=[interaction.user]),
            )
            await interaction.followup.send("Channel reset completed.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("Discord denied the reset. Check Manage Channels and the bot's role.", ephemeral=True)
        except discord.HTTPException:
            await interaction.followup.send("Channel reset failed due to a Discord API error.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Channel reset cancelled.", view=None)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.prompt:
            try:
                await self.prompt.edit(content="Channel reset confirmation expired.", view=self)
            except discord.HTTPException:
                pass


class ConversationalServerActions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _normalize(self, message: discord.Message) -> str:
        raw = message.content.strip()
        if self.bot.user:
            raw = re.sub(rf"^<@!?{self.bot.user.id}>\s*[,]?\s*", "", raw, flags=re.I).strip()
        raw = re.sub(r"^Liebe\s*[,：:]\s*", "", raw, flags=re.I).strip()
        raw = re.sub(r"^Liebe\s+", "", raw, flags=re.I).strip()
        return raw

    async def _reply(self, message: discord.Message, text: str, *, view: discord.ui.View | None = None):
        try:
            return await message.reply(text, view=view, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            try:
                return await message.channel.send(text, view=view, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                return None

    async def _create_role(self, message: discord.Message, args: str):
        actor, guild = message.author, message.guild
        bot_member = guild.me
        if not isinstance(actor, discord.Member) or not bot_member:
            return await self._reply(message, "Could not verify the required permissions.")
        if not (actor.guild_permissions.manage_roles or actor.guild_permissions.administrator):
            return await self._reply(message, "You need Manage Roles permission to create a role.")
        if not (bot_member.guild_permissions.manage_roles or bot_member.guild_permissions.administrator):
            return await self._reply(message, "I need Manage Roles permission to create a role.")

        color_match = COLOR_RE.search(args)
        hoist_match = HOIST_RE.search(args)
        name = COLOR_RE.sub("", args)
        name = HOIST_RE.sub("", name).strip(" \t,|")
        if not name:
            return await self._reply(message, "Use `createrole VIP [#ff0000] [hoist:true]`.")
        color = discord.Color(int(color_match.group(1), 16)) if color_match else discord.Color.default()
        hoist = bool(hoist_match and hoist_match.group(1).lower() == "true")
        try:
            role = await guild.create_role(name=name[:100], colour=color, hoist=hoist, reason=f"Role created by {actor}")
        except discord.Forbidden:
            return await self._reply(message, "Discord denied role creation. Check Manage Roles and the bot's role hierarchy.")
        except discord.HTTPException:
            return await self._reply(message, "Role creation failed due to a Discord API error.")
        return await self._reply(message, f"✅ Created role **{role.name}**{f' with color `#{color_match.group(1)}`' if color_match else ''}.")

    async def _nuke(self, message: discord.Message, args: str):
        actor, guild, channel = message.author, message.guild, message.channel
        if not isinstance(actor, discord.Member) or not isinstance(channel, discord.TextChannel):
            return await self._reply(message, "Nuke is only available in a server text channel.")
        if not (actor.guild_permissions.manage_channels or actor.guild_permissions.administrator):
            return await self._reply(message, "You need Manage Channels permission to reset a channel.")
        bot_member = guild.me
        if not bot_member or not (bot_member.guild_permissions.manage_channels or bot_member.guild_permissions.administrator):
            return await self._reply(message, "I need Manage Channels permission to reset a channel.")
        if args.strip().casefold() == "cancel":
            return await self._reply(message, "No channel was changed. To reset this channel, send `nuke` and confirm the button.")
        view = NukeConfirmationView(channel, actor.id)
        prompt = await self._reply(
            message,
            f"⚠️ This will replace **#{channel.name}** with a copy and remove the current channel and its message history. Confirm only if you intend to do this.",
            view=view,
        )
        view.prompt = prompt

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return
        raw = self._normalize(message)
        match = re.match(r"^(createrole|nuke)\b\s*(.*)$", raw, re.I)
        if not match:
            return
        command, args = match.group(1).lower(), match.group(2).strip()
        if command == "createrole":
            await self._create_role(message, args)
        else:
            await self._nuke(message, args)


async def setup(bot: commands.Bot):
    await bot.add_cog(ConversationalServerActions(bot))
