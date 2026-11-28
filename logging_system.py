"""Carl-bot-style message, command, moderation and update logging for Liebe."""
from datetime import datetime, timezone
import re
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

DB = "bot_data.db"
BOT_VERSION = "Beta v1.031"
BOT_UPDATE_SUMMARY = "Added selectable normal-message/embed echo, mention-triggered AI replies in any channel, message/mod/bot logging, persistent update announcements, multi-category tickets, and confirmed create-only server template imports."
GAME_COMMANDS = {
    "games", "moregames", "tictactoe", "connect4", "highlow", "profile", "achievements", "serverstats",
    "rockpaperscissors", "hangman", "wordscramble", "trivia", "emojidecode", "chess", "checkers",
    "battleship", "wordle", "2048", "minesweeper", "ludo", "snakesandladders", "memorymatch",
    "whowas", "wouldyourather", "reactionspeed", "typingrace", "numberrace", "mathbattle", "wordchain",
    "sentencebuilding", "geographyquiz", "moviequiz", "animequiz", "flagguess", "riddlebattle",
    "quizbattle", "mafia", "werewolf", "uno", "blackjack", "dotsandboxes", "guessnumber",
}


def admin_only():
    async def predicate(interaction: discord.Interaction):
        return bool(interaction.guild and isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator)
    return app_commands.check(predicate)


def timestamp_text():
    return datetime.now(timezone.utc).strftime("%d %B %Y • %H:%M UTC")


class LoggingSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.message_cache: dict[int, dict] = {}

    async def cog_load(self):
        async with aiosqlite.connect(DB) as db:
            await db.execute("""CREATE TABLE IF NOT EXISTS liebe_log_settings (
                guild_id INTEGER PRIMARY KEY, message_log INTEGER, mod_log INTEGER, bot_log INTEGER,
                update_enabled INTEGER NOT NULL DEFAULT 0, last_version TEXT
            )""")
            await db.commit()

    async def _settings(self, guild_id):
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT message_log,mod_log,bot_log,update_enabled,last_version FROM liebe_log_settings WHERE guild_id=?", (guild_id,))
            return await cur.fetchone()

    async def _save(self, guild_id, column, value):
        if column not in {"message_log", "mod_log", "bot_log", "update_enabled"}:
            raise ValueError("Invalid log setting")
        async with aiosqlite.connect(DB) as db:
            await db.execute("INSERT OR IGNORE INTO liebe_log_settings(guild_id) VALUES(?)", (guild_id,))
            await db.execute(f"UPDATE liebe_log_settings SET {column}=? WHERE guild_id=?", (value, guild_id))
            await db.commit()

    def _channel(self, guild, channel_id):
        channel = guild.get_channel(channel_id) if channel_id else None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _send_log(self, guild, channel_id, embed):
        channel = self._channel(guild, channel_id)
        if not channel:
            return False
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            return True
        except discord.HTTPException:
            return False

    def _base_embed(self, title, color=discord.Color.blurple()):
        embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
        embed.set_footer(text=f"Liebe Logs • {timestamp_text()}")
        return embed

    def _message_snapshot(self, message: discord.Message):
        attachments = [f"{a.filename} ({a.url})" for a in getattr(message, "attachments", [])]
        embeds = []
        for item in getattr(message, "embeds", [])[:5]:
            if item.url:
                embeds.append(item.url)
            if item.title:
                embeds.append(item.title[:150])
        forwarded = []
        for snap in getattr(message, "message_snapshots", []) or []:
            content = getattr(snap, "content", "") or ""
            if content:
                forwarded.append(content[:700])
            for attachment in getattr(snap, "attachments", []) or []:
                forwarded.append(f"Forwarded attachment: {getattr(attachment, 'filename', 'file')} ({getattr(attachment, 'url', '')})")
        return {
            "guild_id": message.guild.id if message.guild else None,
            "channel_id": message.channel.id,
            "author_id": message.author.id,
            "author": str(message.author),
            "content": message.content or "[No text content]",
            "attachments": attachments,
            "embeds": embeds,
            "forwarded": forwarded,
            "created_at": message.created_at,
            "jump_url": message.jump_url,
        }

    def _cache(self, message):
        if not message.guild:
            return
        self.message_cache[message.id] = self._message_snapshot(message)
        if len(self.message_cache) > 3000:
            for key in list(self.message_cache)[:500]:
                self.message_cache.pop(key, None)

    async def _log_message(self, guild, snap, title, color):
        settings = await self._settings(guild.id)
        if not settings or not settings[0]:
            return
        embed = self._base_embed(title, color)
        embed.add_field(name="Author", value=f"{snap.get('author','Unknown')} (`{snap.get('author_id','?')}`)", inline=False)
        channel = guild.get_channel(snap.get("channel_id"))
        embed.add_field(name="Channel", value=channel.mention if channel else f"`{snap.get('channel_id')}`", inline=True)
        embed.add_field(name="Message created", value=f"<t:{int(snap['created_at'].timestamp())}:F>" if snap.get("created_at") else "Unknown", inline=True)
        content = (snap.get("content") or "[No text content]")
        embed.add_field(name="Content", value=content[:1000], inline=False)
        for field, title in (("attachments", "Attachments / photos / files"), ("embeds", "Links / embeds"), ("forwarded", "Forwarded content")):
            values = snap.get(field) or []
            if values:
                embed.add_field(name=title, value="\\n".join(values)[:1000], inline=False)
        if snap.get("jump_url"):
            embed.add_field(name="Original message", value=snap["jump_url"], inline=False)
        await self._send_log(guild, settings[0], embed)

    async def _command_log(self, interaction=None, ctx=None, error=None):
        if interaction:
            guild = interaction.guild
            user = interaction.user
            command = interaction.command.qualified_name if interaction.command else "unknown"
            channel = interaction.channel
        else:
            guild = ctx.guild
            user = ctx.author
            command = ctx.command.qualified_name if ctx.command else "unknown"
            channel = ctx.channel
        if not guild or command.split()[0].lower() in GAME_COMMANDS:
            return
        settings = await self._settings(guild.id)
        if not settings:
            return
        embed = self._base_embed("⚙️ Command Error" if error else "⚙️ Command Used", discord.Color.red() if error else discord.Color.orange())
        embed.add_field(name="Command", value=f"`{command}`", inline=True)
        embed.add_field(name="Used by", value=f"{user} (`{user.id}`)", inline=True)
        embed.add_field(name="Channel", value=getattr(channel, "mention", "Unknown"), inline=True)
        if error:
            safe_error = re.sub(r"(?i)(token|api[_ -]?key|authorization)\\s*[:=]\\s*\\S+", r"\\1=[redacted]", str(error))
            embed.add_field(name="Error", value=safe_error[:900], inline=False)
        await self._send_log(guild, settings[1], embed)
        if command.split()[0].lower() == "echo" and settings[2]:
            bot_embed = self._base_embed("📢 Echo Command Used", discord.Color.blurple())
            bot_embed.add_field(name="Used by", value=f"{user} (`{user.id}`)", inline=True)
            bot_embed.add_field(name="Channel", value=getattr(channel, "mention", "Unknown"), inline=True)
            await self._send_log(guild, settings[2], bot_embed)

    @app_commands.guild_only()
    @app_commands.command(name="message-log", description="Set the channel for deleted and edited message logs")
    @admin_only()
    async def message_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not channel.permissions_for(interaction.guild.me).send_messages or not channel.permissions_for(interaction.guild.me).embed_links:
            return await interaction.response.send_message("I need Send Messages and Embed Links in that channel.", ephemeral=True)
        await self._save(interaction.guild_id, "message_log", channel.id)
        await interaction.response.send_message(f"✅ Message logs will be sent to {channel.mention}.", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="mod-log", description="Set the channel for command and moderation logs")
    @admin_only()
    async def mod_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not channel.permissions_for(interaction.guild.me).send_messages or not channel.permissions_for(interaction.guild.me).embed_links:
            return await interaction.response.send_message("I need Send Messages and Embed Links in that channel.", ephemeral=True)
        await self._save(interaction.guild_id, "mod_log", channel.id)
        await interaction.response.send_message(f"✅ Command and moderation logs will be sent to {channel.mention}.", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="bot-log", description="Set the channel for bot-specific activity such as echo usage")
    @admin_only()
    async def configure_bot_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not channel.permissions_for(interaction.guild.me).send_messages or not channel.permissions_for(interaction.guild.me).embed_links:
            return await interaction.response.send_message("I need Send Messages and Embed Links in that channel.", ephemeral=True)
        await self._save(interaction.guild_id, "bot_log", channel.id)
        await interaction.response.send_message(f"✅ Bot activity logs will be sent to {channel.mention}.", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="bot-update-log", description="Enable or disable automatic Liebe update posts in this mod-log channel")
    @app_commands.describe(enabled="Whether automatic bot update announcements should be enabled")
    @admin_only()
    async def configure_bot_update_log(self, interaction: discord.Interaction, enabled: bool = True):
        settings = await self._settings(interaction.guild_id)
        if not settings or not settings[1] or settings[1] != interaction.channel_id:
            return await interaction.response.send_message("Run `/bot-update-log` inside the channel configured with `/mod-log`.", ephemeral=True)
        await self._save(interaction.guild_id, "update_enabled", int(enabled))
        state = "enabled" if enabled else "disabled"
        await interaction.response.send_message(f"✅ Automatic Liebe update announcements are now **{state}** in this mod-log channel.", ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            settings = await self._settings(guild.id)
            if not settings or not settings[3] or not settings[1] or settings[4] == BOT_VERSION:
                continue
            embed = self._base_embed("🚀 Liebe Bot Updated", discord.Color.green())
            embed.description = f"Liebe is now running **{BOT_VERSION}**.\\n\\n**What changed:** {BOT_UPDATE_SUMMARY}"
            sent = await self._send_log(guild, settings[1], embed)
            if not sent:
                continue
            async with aiosqlite.connect(DB) as db:
                await db.execute("UPDATE liebe_log_settings SET last_version=? WHERE guild_id=?", (BOT_VERSION, guild.id))
                await db.commit()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        self._cache(message)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        before = self.message_cache.get(payload.message_id)
        data = payload.data or {}
        if before:
            snap = dict(before)
        else:
            snap = {"guild_id": payload.guild_id, "channel_id": payload.channel_id, "author_id": "unknown", "author": "Unknown (message was not cached)", "content": "[Previous content unavailable]", "attachments": [], "embeds": [], "forwarded": [], "created_at": None, "jump_url": ""}
        if "content" in data:
            snap["content"] = f"**Before:**\\n{snap.get('content', '[Previous content unavailable]')}\\n\\n**After:**\\n{data.get('content') or '[No text content]'}"
        raw_attachments = data.get("attachments") or []
        if raw_attachments:
            snap["attachments"] = [f"{item.get('filename', 'file')} ({item.get('url', '')})" for item in raw_attachments]
        raw_embeds = data.get("embeds") or []
        if raw_embeds:
            snap["embeds"] = [str(item.get('url') or item.get('title') or 'Embedded content')[:200] for item in raw_embeds]
        raw_snapshots = data.get("message_snapshots") or []
        if raw_snapshots:
            forwarded = []
            for item in raw_snapshots[:5]:
                forwarded.append((item.get("content") or "[Forwarded attachment]")[:700])
                for attachment in item.get("attachments", [])[:5]:
                    forwarded.append(f"{attachment.get('filename', 'file')} ({attachment.get('url', '')})")
            snap["forwarded"] = forwarded
        await self._log_message(guild, snap, "✏️ Message Edited", discord.Color.orange())
        cached = payload.cached_message
        if cached:
            self._cache(cached)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        cached = payload.cached_message
        snap = self._message_snapshot(cached) if cached else self.message_cache.get(payload.message_id)
        self.message_cache.pop(payload.message_id, None)
        if snap:
            await self._log_message(guild, snap, "🗑️ Message Deleted", discord.Color.red())
        else:
            settings = await self._settings(guild.id)
            if settings and settings[0]:
                embed = self._base_embed("🗑️ Message Deleted", discord.Color.red())
                embed.description = "The message was deleted, but its content was not cached before deletion. Discord does not provide deleted content after the fact."
                channel = guild.get_channel(payload.channel_id)
                embed.add_field(name="Channel", value=channel.mention if channel else str(payload.channel_id))
                await self._send_log(guild, settings[0], embed)

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction, command: app_commands.Command):
        await self._command_log(interaction=interaction)

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._command_log(interaction=interaction, error=error)

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        await self._command_log(ctx=ctx)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        await self._command_log(ctx=ctx, error=error)


async def setup(bot: commands.Bot):
    await bot.add_cog(LoggingSystem(bot))
