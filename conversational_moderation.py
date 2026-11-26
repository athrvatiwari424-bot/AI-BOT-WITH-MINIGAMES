"""Permission-checked conversational moderation commands.

Commands can be written directly, prefixed with ``Liebe,`` or preceded by a
mention of the bot. Only explicit command phrases are executed.
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import aiosqlite
import discord
from discord.ext import commands

logger = logging.getLogger("conversational_moderation")
DB_PATH = "bot_data.db"
BOT_OWNER_ID = 1170682591414861896
COMMANDS = (
    "unlockdown", "lockdown", "muterole", "removewarn", "clearwarn", "warnings", "infractions",
    "tempban", "softban", "massban", "unban", "unmute", "removerole", "addrole", "rolecolor",
    "createrole", "delrole", "modrole", "modlog", "slowmode", "userinfo", "serverinfo",
    "cleanup", "purge", "warn", "kick", "ban", "mute", "role", "help", "reason", "whois",
    "modonly", "unmodonly",
)
DURATION_RE = re.compile(r"(?<!\w)(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\b", re.I)


def duration_seconds(value: str) -> int | None:
    match = DURATION_RE.search(value)
    if not match:
        return None
    n, unit = int(match.group(1)), match.group(2).lower()
    return n * (1 if unit.startswith("s") else 60 if unit.startswith("m") else 3600 if unit.startswith("h") else 86400)


def duration_label(seconds: int) -> str:
    for unit, factor in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds and seconds % factor == 0:
            return f"{seconds // factor}{unit}"
    return f"{seconds}s"


class ConversationalModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.mod_roles: dict[int, int] = {}
        self.modlog_channels: dict[int, int] = {}
        self.mute_roles: dict[int, int] = {}
        self.scheduled_tasks: set[asyncio.Task] = set()

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("CREATE TABLE IF NOT EXISTS mod_config (guild_id INTEGER PRIMARY KEY, mute_role_id INTEGER, mod_role_id INTEGER, modlog_channel_id INTEGER)")
            await db.execute("CREATE TABLE IF NOT EXISTS mod_cases (case_id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, action TEXT NOT NULL, target_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL, reason TEXT NOT NULL, duration TEXT, created_at TEXT NOT NULL, log_channel_id INTEGER, log_message_id INTEGER)")
            await db.commit()
            async with db.execute("SELECT guild_id,mute_role_id,mod_role_id,modlog_channel_id FROM mod_config") as cur:
                for gid, mute_role, mod_role, log_channel in await cur.fetchall():
                    if mute_role:
                        self.mute_roles[gid] = mute_role
                    if mod_role:
                        self.mod_roles[gid] = mod_role
                    if log_channel:
                        self.modlog_channels[gid] = log_channel

    def _normalize(self, message: discord.Message) -> str:
        raw = message.content.strip()
        if self.bot.user:
            raw = re.sub(rf"^<@!?{self.bot.user.id}>\s*[,]?\s*", "", raw, flags=re.I).strip()
        raw = re.sub(r"^Liebe\s*[,：:]\s*", "", raw, flags=re.I).strip()
        raw = re.sub(r"^Liebe\s+", "", raw, flags=re.I).strip()
        return raw

    def _has_mod_role(self, member: discord.Member, guild: discord.Guild) -> bool:
        role_id = self.mod_roles.get(guild.id)
        return bool(role_id and any(role.id == role_id for role in member.roles))

    def _actor_has_any_moderation_permission(self, member: discord.Member) -> bool:
        perms = member.guild_permissions
        return any(getattr(perms, name, False) for name in (
            "administrator", "manage_guild", "moderate_members", "kick_members", "ban_members",
            "manage_messages", "manage_roles", "manage_channels",
        ))

    async def _has(self, message: discord.Message, permission: str) -> bool:
        actor, bot_member = message.author, message.guild.me
        if not isinstance(actor, discord.Member) or bot_member is None:
            return False
        actor_perms = actor.guild_permissions
        bot_perms = bot_member.guild_permissions
        return bool((getattr(actor_perms, permission, False) or actor_perms.administrator) and
                    (getattr(bot_perms, permission, False) or bot_perms.administrator))

    async def _reply(self, message: discord.Message, text: str):
        try:
            return await message.reply(text[:1900], mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            try:
                return await message.channel.send(text[:1900], allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                logger.exception("Could not send moderation response")
                return None

    async def _send_embed(self, message: discord.Message, embed: discord.Embed, *, target_id: int | None = None):
        allowed = discord.AllowedMentions(users=[discord.Object(id=target_id)] if target_id else [], roles=False, everyone=False, replied_user=False)
        try:
            return await message.reply(embed=embed, mention_author=False, allowed_mentions=allowed)
        except discord.HTTPException:
            try:
                return await message.channel.send(embed=embed, allowed_mentions=allowed)
            except discord.HTTPException:
                logger.exception("Could not send moderation embed")
                return None

    def _targets(self, message: discord.Message, text: str) -> list[discord.Member]:
        found = {member.id: member for member in message.mentions if member.id != getattr(self.bot.user, "id", None)}
        for raw_id in re.findall(r"(?<!\d)(\d{15,22})(?!\d)", text):
            member = message.guild.get_member(int(raw_id))
            if member and member.id != getattr(self.bot.user, "id", None):
                found[member.id] = member
        return list(found.values())

    def _reason(self, args: str, *, remove_duration: bool = False) -> str:
        reason = re.sub(r"<@!?\d+>|\b\d{15,22}\b", "", args)
        if remove_duration:
            reason = DURATION_RE.sub("", reason)
        return reason.strip(" ,|-") or "No reason provided"

    def _hierarchy_ok(self, message: discord.Message, target: discord.Member) -> bool:
        actor, bot_member = message.author, message.guild.me
        if not isinstance(actor, discord.Member) or bot_member is None:
            return False
        if target.id in (actor.id, message.guild.owner_id) or target.top_role >= bot_member.top_role:
            return False
        return actor.id == message.guild.owner_id or target.top_role < actor.top_role

    async def _case(self, message: discord.Message, action: str, target: discord.Member | discord.User, reason: str, duration: str | None = None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "INSERT INTO mod_cases (guild_id,action,target_id,moderator_id,reason,duration,created_at) VALUES (?,?,?,?,?,?,?)",
                (message.guild.id, action, target.id, message.author.id, reason, duration, now),
            )
            await db.commit()
            case_id = cur.lastrowid
        channel = message.guild.get_channel(self.modlog_channels.get(message.guild.id, 0))
        if isinstance(channel, discord.TextChannel):
            embed = discord.Embed(title=f"Moderation Case #{case_id} · {action.title()}", color=discord.Color.orange(), timestamp=datetime.now(timezone.utc))
            embed.add_field(name="Target", value=f"{target} (`{target.id}`)", inline=False)
            embed.add_field(name="Moderator", value=f"{message.author} (`{message.author.id}`)", inline=False)
            embed.add_field(name="Reason", value=reason[:1024], inline=False)
            if duration:
                embed.add_field(name="Duration", value=duration, inline=True)
            try:
                log_message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("UPDATE mod_cases SET log_channel_id=?,log_message_id=? WHERE case_id=?", (channel.id, log_message.id, case_id))
                    await db.commit()
            except discord.HTTPException:
                logger.exception("Could not send moderation log case %s", case_id)
        return case_id

    async def _punishment_embed(self, message: discord.Message, target: discord.Member | discord.User, action: str, reason: str, duration: str | None, case_id: int):
        titles = {"warn":"Warning Issued", "mute":"Timeout Issued", "ban":"Member Banned", "tempban":"Temporary Ban Issued", "softban":"Member Softbanned", "kick":"Member Kicked", "unmute":"Member Unmuted", "unban":"Member Unbanned"}
        colors = {"warn":discord.Color.gold(), "mute":discord.Color.orange(), "ban":discord.Color.red(), "tempban":discord.Color.orange(), "softban":discord.Color.orange(), "kick":discord.Color.dark_orange(), "unmute":discord.Color.green(), "unban":discord.Color.green()}
        embed = discord.Embed(title=titles.get(action, action.title()), color=colors.get(action, discord.Color.orange()), timestamp=datetime.now(timezone.utc))
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="User", value=f"{target.mention} (`{target.id}`)", inline=False)
        if action == "warn":
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT COUNT(*) FROM mod_cases WHERE guild_id=? AND target_id=? AND action='warn'", (message.guild.id, target.id)) as cur:
                    warnings = (await cur.fetchone())[0]
            embed.add_field(name="Warnings", value=f"{warnings}/3", inline=True)
        if duration:
            embed.add_field(name="Duration", value=duration, inline=True)
        embed.add_field(name="Reason", value=reason[:1024], inline=False)
        embed.add_field(name="Case", value=f"#{case_id}", inline=True)
        embed.add_field(name="Moderator", value=f"{message.author.mention} (`{message.author.id}`)", inline=False)
        embed.set_footer(text=f"{message.guild.name} Moderation")
        await self._send_embed(message, embed, target_id=target.id)

    async def _dm(self, target: discord.abc.User, guild: discord.Guild, action: str, reason: str, duration: str | None = None):
        text = f"Server: **{guild.name}**\nAction: **{action}**\nReason: {reason}"
        if duration:
            text += f"\nDuration: **{duration}**"
        try:
            await target.send(text)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _punishment(self, message: discord.Message, action: str, args: str):
        guild = message.guild
        target = next(iter(self._targets(message, args)), None)
        if not target:
            return await self._reply(message, f"Mention a current member: `{action} @user [reason]`.")
        if not self._hierarchy_ok(message, target):
            return await self._reply(message, "I cannot act on that member because of ownership or role hierarchy.")

        permission = {"ban":"ban_members", "tempban":"ban_members", "softban":"ban_members", "kick":"kick_members", "mute":"moderate_members", "unmute":"moderate_members", "warn":"moderate_members"}[action]
        if not await self._has(message, permission):
            return await self._reply(message, f"You and I both need {permission.replace('_', ' ').title()} permission.")

        seconds = duration_seconds(args) if action in ("tempban", "mute") else None
        if action == "tempban" and (seconds is None or seconds < 60 or seconds > 365 * 86400):
            return await self._reply(message, "Use a tempban duration from 1 minute to 365 days, e.g. `tempban @user 7d reason`.")
        if action == "mute" and (seconds is None or seconds > 28 * 86400):
            return await self._reply(message, "Use `mute @user 10m reason` (maximum timeout is 28 days).")
        duration = duration_label(seconds) if seconds else None
        reason = self._reason(args, remove_duration=action in ("tempban", "mute"))
        try:
            if action in ("ban", "tempban", "softban"):
                await guild.ban(target, reason=reason[:450], delete_message_seconds=86400 if action == "softban" else 0)
                if action == "softban":
                    await guild.unban(discord.Object(id=target.id), reason=f"Softban by {message.author}")
                if action == "tempban":
                    task = asyncio.create_task(self._expire_ban(guild.id, target.id, seconds))
                    self.scheduled_tasks.add(task)
                    task.add_done_callback(self.scheduled_tasks.discard)
            elif action == "kick":
                await target.kick(reason=reason[:450])
            elif action == "warn":
                pass
            elif action == "mute":
                await target.timeout(discord.utils.utcnow() + timedelta(seconds=seconds), reason=reason[:450])
            elif action == "unmute":
                await target.timeout(None, reason=reason[:450])
                mute_role = guild.get_role(self.mute_roles.get(guild.id, 0))
                if mute_role and mute_role in target.roles:
                    await target.remove_roles(mute_role, reason=reason[:450])

            case_id = await self._case(message, action, target, reason, duration)
            await self._dm(target, guild, action, reason, duration)
            await self._punishment_embed(message, target, action, reason, duration, case_id)
        except discord.Forbidden:
            await self._reply(message, "Discord denied the action. Check bot permissions and role hierarchy.")
        except discord.HTTPException:
            logger.exception("Moderation action %s failed", action)
            await self._reply(message, f"{action.title()} failed due to a Discord API error.")
        except Exception:
            logger.exception("Unexpected moderation error for action %s", action)
            await self._reply(message, "The moderation action failed unexpectedly. Check the service logs.")

    async def _expire_ban(self, guild_id: int, user_id: int, seconds: int):
        await asyncio.sleep(seconds)
        guild = self.bot.get_guild(guild_id)
        if guild:
            try:
                await guild.unban(discord.Object(id=user_id), reason="Temporary ban expired")
            except discord.HTTPException:
                logger.exception("Temporary ban expiration failed for %s", user_id)

    async def _case_command(self, message: discord.Message, action: str, args: str):
        if not (await self._has(message, "moderate_members") or await self._has(message, "manage_messages") or self._has_mod_role(message.author, message.guild)):
            return await self._reply(message, "You need Moderate Members or Manage Messages permission (or the configured moderator role) for warning management.")
        if action in ("warnings", "infractions", "clearwarn"):
            target = next(iter(self._targets(message, args)), None)
            if not target:
                return await self._reply(message, "Mention a member.")
            if action == "clearwarn":
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute("DELETE FROM mod_cases WHERE guild_id=? AND target_id=? AND action='warn'", (message.guild.id, target.id))
                    await db.commit()
                return await self._reply(message, f"Cleared **{cur.rowcount}** warnings for {target.mention}.")
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT case_id,reason,created_at,moderator_id FROM mod_cases WHERE guild_id=? AND target_id=? AND action='warn' ORDER BY case_id DESC", (message.guild.id, target.id)) as cur:
                    rows = await cur.fetchall()
            embed = discord.Embed(title=f"Warnings for {target} ({len(rows)} total)", color=discord.Color.orange())
            for case_id, reason, created, moderator_id in rows[:20]:
                embed.add_field(name=f"Case #{case_id} · {created[:10]}", value=f"{reason}\nModerator: <@{moderator_id}>", inline=False)
            return await self._send_embed(message, embed)

        match = re.search(r"\b(\d+)\b", args)
        if not match:
            return await self._reply(message, "Provide a case ID.")
        case_id = int(match.group(1))
        if action == "removewarn":
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("DELETE FROM mod_cases WHERE guild_id=? AND case_id=? AND action='warn'", (message.guild.id, case_id))
                await db.commit()
            return await self._reply(message, f"Removed warning Case #{case_id}." if cur.rowcount else "Warning case not found.")
        new_reason = re.sub(r"^\s*\d+\s*", "", args).strip()
        if not new_reason:
            return await self._reply(message, "Provide the new reason after the case ID.")
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("UPDATE mod_cases SET reason=? WHERE guild_id=? AND case_id=?", (new_reason, message.guild.id, case_id))
            await db.commit()
        return await self._reply(message, f"Updated reason for Case #{case_id}." if cur.rowcount else "Case not found.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return
        raw = self._normalize(message)
        match = re.match(r"^(" + "|".join(sorted(COMMANDS, key=len, reverse=True)) + r")\b\s*(.*)$", raw, re.I)
        if not match:
            return
        action, args = match.group(1).lower(), match.group(2).strip()
        if action == "help":
            return
        try:
            if action in ("warn", "ban", "tempban", "softban", "kick", "mute", "unmute"):
                return await self._punishment(message, action, args)
            if action in ("warnings", "infractions", "clearwarn", "removewarn", "reason"):
                return await self._case_command(message, action, args)
            if action == "unban":
                if not (await self._has(message, "ban_members") or self._has_mod_role(message.author, message.guild)):
                    return await self._reply(message, "You and I both need Ban Members permission.")
                id_match = re.search(r"\b(\d{15,22})\b", args)
                if not id_match:
                    return await self._reply(message, "Use `unban USER_ID [reason]`.")
                user_id = int(id_match.group(1))
                reason = re.sub(r"\b\d{15,22}\b", "", args).strip() or "No reason provided"
                entry = await message.guild.fetch_ban(discord.Object(id=user_id))
                await message.guild.unban(entry.user, reason=reason[:450])
                case_id = await self._case(message, "unban", entry.user, reason)
                return await self._punishment_embed(message, entry.user, "unban", reason, None, case_id)
            # Commands not implemented in this cog are intentionally not swallowed.
        except discord.NotFound:
            await self._reply(message, "That member or case could not be found.")
        except discord.Forbidden:
            await self._reply(message, "Discord denied the action. Check the relevant permissions and role hierarchy.")
        except discord.HTTPException:
            logger.exception("Moderation command %s failed", action)
            await self._reply(message, "The moderation command failed due to a Discord API error.")
        except Exception:
            logger.exception("Unexpected error handling moderation command %s", action)
            await self._reply(message, "The moderation command failed unexpectedly. Check the service logs.")

    async def setup(self):
        pass

    def _normalize(self, message: discord.Message) -> str:
        raw = message.content.strip()
        if self.bot.user:
            raw = re.sub(rf"^<@!?{self.bot.user.id}>\s*[,]?\s*", "", raw, flags=re.I).strip()
        raw = re.sub(r"^Liebe\s*[,：:]\s*", "", raw, flags=re.I).strip()
        raw = re.sub(r"^Liebe\s+", "", raw, flags=re.I).strip()
        return raw

    def _has_mod_role(self, member: discord.Member, guild: discord.Guild) -> bool:
        role_id = self.mod_roles.get(guild.id)
        return bool(role_id and any(role.id == role_id for role in member.roles))


async def setup(bot: commands.Bot):
    await bot.add_cog(ConversationalModerationCog(bot))
