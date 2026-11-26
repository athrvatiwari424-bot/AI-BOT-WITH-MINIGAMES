"""Permission-checked conversational moderation commands.
Commands can be written directly, prefixed with ``Liebe,`` or preceded by a
mention of the bot. Only explicit command phrases are executed.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import aiosqlite
import discord
from discord.ext import commands

logger = logging.getLogger("conversational_moderation")

DB_PATH = "bot_data.db"
BOT_OWNER_ID = 1170682591414861896

COMMANDS = (
    "unlockdown", "lockdown", "muterole", "removewarn", "clearwarn", "warnings", "infractions",
    "tempban", "softban", "massban", "unban", "unmute", "removetimeout", "removerole", "addrole",
    "rolecolor", "createrole", "rolecreate", "delrole", "roledelete", "createchannel",
    "channelcreate", "delchannel", "channeldelete", "nuke", "modrole", "modlog", "slowmode",
    "userinfo", "serverinfo", "cleanup", "purge", "warn", "kick", "ban", "mute", "timeout",
    "role", "help", "reason", "whois", "modonly", "unmodonly",
)

DURATION_RE = re.compile(
    r"(?<!\w)(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\b",
    re.I,
)


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
        self.modonly_channels: set[int] = set()
        self.scheduled_tasks: set[asyncio.Task] = set()

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS mod_config ("
                "guild_id INTEGER PRIMARY KEY, mute_role_id INTEGER, mod_role_id INTEGER, modlog_channel_id INTEGER)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS mod_cases ("
                "case_id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, action TEXT NOT NULL, "
                "target_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL, reason TEXT NOT NULL, "
                "duration TEXT, created_at TEXT NOT NULL, log_channel_id INTEGER, log_message_id INTEGER)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS modonly_channels (channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL)"
            )
            await db.commit()

            async with db.execute("SELECT guild_id, mute_role_id, mod_role_id, modlog_channel_id FROM mod_config") as cur:
                for gid, mute_role, mod_role, log_channel in await cur.fetchall():
                    if mute_role:
                        self.mute_roles[gid] = mute_role
                    if mod_role:
                        self.mod_roles[gid] = mod_role
                    if log_channel:
                        self.modlog_channels[gid] = log_channel

            async with db.execute("SELECT channel_id FROM modonly_channels") as cur:
                for (cid,) in await cur.fetchall():
                    self.modonly_channels.add(cid)

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

    def _is_mod(self, member: discord.Member) -> bool:
        if member.id == BOT_OWNER_ID or member.id == member.guild.owner_id:
            return True
        if self._has_mod_role(member, member.guild):
            return True
        perms = member.guild_permissions
        return any(
            getattr(perms, name, False)
            for name in (
                "administrator", "manage_guild", "moderate_members", "kick_members",
                "ban_members", "manage_messages", "manage_roles", "manage_channels",
            )
        )

    async def _has(self, message: discord.Message, permission: str, *, allow_mod_role: bool = False) -> bool:
        actor, bot_member = message.author, message.guild.me
        if not isinstance(actor, discord.Member) or bot_member is None:
            return False
        actor_perms = actor.guild_permissions
        bot_perms = bot_member.guild_permissions
        bot_ok = bool(getattr(bot_perms, permission, False) or bot_perms.administrator)
        actor_ok = bool(
            actor.id == BOT_OWNER_ID
            or getattr(actor_perms, permission, False)
            or actor_perms.administrator
            or (allow_mod_role and self._has_mod_role(actor, message.guild))
        )
        return actor_ok and bot_ok

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
        allowed = discord.AllowedMentions(
            users=[discord.Object(id=target_id)] if target_id else [],
            roles=False,
            everyone=False,
            replied_user=False,
        )
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

    def _find_role(self, guild: discord.Guild, query: str) -> discord.Role | None:
        query = query.strip()
        if not query:
            return None
        mention_match = re.search(r"<@&(\d+)>", query)
        if mention_match:
            return guild.get_role(int(mention_match.group(1)))
        if re.fullmatch(r"\d{15,22}", query):
            return guild.get_role(int(query))
        lower = query.lower()
        return discord.utils.find(lambda r: r.name.lower() == lower, guild.roles) or discord.utils.find(
            lambda r: lower in r.name.lower(), guild.roles
        )

    def _find_channel(self, guild: discord.Guild, query: str) -> discord.abc.GuildChannel | None:
        query = query.strip()
        if not query:
            return None
        mention_match = re.search(r"<#(\d+)>", query)
        if mention_match:
            return guild.get_channel(int(mention_match.group(1)))
        if re.fullmatch(r"\d{15,22}", query):
            return guild.get_channel(int(query))
        lower = query.lstrip("#").lower()
        return discord.utils.find(lambda c: c.name.lower() == lower, guild.channels)

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
        return actor.id in (message.guild.owner_id, BOT_OWNER_ID) or target.top_role < actor.top_role

    async def _case(
        self,
        message: discord.Message,
        action: str,
        target: discord.Member | discord.User | discord.Object,
        reason: str,
        duration: str | None = None,
    ) -> int:
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

        channel = message.guild.get_channel(self.modlog_channels.get(message.guild.id, 0))
        if isinstance(channel, discord.TextChannel):
            embed = discord.Embed(
                title=f"Moderation Case #{case_id} · {action.title()}",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Target", value=f"{target} (`{target.id}`)", inline=False)
            embed.add_field(name="Moderator", value=f"{message.author} (`{message.author.id}`)", inline=False)
            embed.add_field(name="Reason", value=reason[:1024], inline=False)
            if duration:
                embed.add_field(name="Duration", value=duration, inline=True)
            try:
                log_message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE mod_cases SET log_channel_id=?,log_message_id=? WHERE case_id=?",
                        (channel.id, log_message.id, case_id),
                    )
                    await db.commit()
            except discord.HTTPException:
                logger.exception("Could not send moderation log case %s", case_id)
        return case_id

    async def _punishment_embed(
        self,
        message: discord.Message,
        target: discord.Member | discord.User,
        action: str,
        reason: str,
        duration: str | None,
        case_id: int,
    ):
        titles = {
            "warn": "Warning Issued",
            "mute": "Timeout Issued",
            "timeout": "Timeout Issued",
            "ban": "Member Banned",
            "tempban": "Temporary Ban Issued",
            "softban": "Member Softbanned",
            "kick": "Member Kicked",
            "unmute": "Member Unmuted",
            "removetimeout": "Timeout Removed",
            "unban": "Member Unbanned",
        }
        colors = {
            "warn": discord.Color.gold(),
            "mute": discord.Color.orange(),
            "timeout": discord.Color.orange(),
            "ban": discord.Color.red(),
            "tempban": discord.Color.orange(),
            "softban": discord.Color.orange(),
            "kick": discord.Color.dark_orange(),
            "unmute": discord.Color.green(),
            "removetimeout": discord.Color.green(),
            "unban": discord.Color.green(),
        }
        embed = discord.Embed(
            title=titles.get(action, action.title()),
            color=colors.get(action, discord.Color.orange()),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="User", value=f"{target.mention} (`{target.id}`)", inline=False)
        if action == "warn":
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM mod_cases WHERE guild_id=? AND target_id=? AND action='warn'",
                    (message.guild.id, target.id),
                ) as cur:
                    row = await cur.fetchone()
                    warnings = row[0] if row else 0
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
        canonical = "mute" if action == "timeout" else "unmute" if action == "removetimeout" else action

        if canonical == "massban":
            if not await self._has(message, "ban_members"):
                return await self._reply(message, "You and I both need Ban Members permission.")
            targets = self._targets(message, args)
            if not targets:
                return await self._reply(message, "Mention or provide IDs of members to massban.")
            reason = self._reason(args)
            banned = 0
            for t in targets:
                if self._hierarchy_ok(message, t):
                    await guild.ban(t, reason=reason[:450])
                    await self._case(message, "massban", t, reason)
                    banned += 1
            return await self._reply(message, f"Massbanned **{banned}/{len(targets)}** members.")

        target = next(iter(self._targets(message, args)), None)
        if not target:
            return await self._reply(message, f"Mention a current member: `{action} @user [reason]`.")
        if not self._hierarchy_ok(message, target):
            return await self._reply(message, "I cannot act on that member because of ownership or role hierarchy.")

        permission = {
            "ban": "ban_members",
            "tempban": "ban_members",
            "softban": "ban_members",
            "kick": "kick_members",
            "mute": "moderate_members",
            "unmute": "moderate_members",
            "warn": "moderate_members",
        }[canonical]
        if not await self._has(message, permission, allow_mod_role=(canonical == "warn")):
            return await self._reply(message, f"You and I both need {permission.replace('_', ' ').title()} permission.")

        seconds = duration_seconds(args) if canonical in ("tempban", "mute") else None
        if canonical == "tempban" and (seconds is None or seconds < 60 or seconds > 365 * 86400):
            return await self._reply(message, "Use a tempban duration from 1 minute to 365 days, e.g. `tempban @user 7d reason`.")
        if canonical == "mute" and (seconds is None or seconds > 28 * 86400):
            return await self._reply(message, f"Use `{action} @user 10m reason` (maximum timeout is 28 days).")

        duration = duration_label(seconds) if seconds else None
        reason = self._reason(args, remove_duration=canonical in ("tempban", "mute"))

        try:
            if canonical in ("ban", "tempban", "softban"):
                await guild.ban(target, reason=reason[:450], delete_message_seconds=86400 if canonical == "softban" else 0)
                if canonical == "softban":
                    await guild.unban(discord.Object(id=target.id), reason=f"Softban by {message.author}")
                if canonical == "tempban":
                    task = asyncio.create_task(self._expire_ban(guild.id, target.id, seconds))
                    self.scheduled_tasks.add(task)
                    task.add_done_callback(self.scheduled_tasks.discard)
            elif canonical == "kick":
                await target.kick(reason=reason[:450])
            elif canonical == "warn":
                pass
            elif canonical == "mute":
                await target.timeout(discord.utils.utcnow() + timedelta(seconds=seconds), reason=reason[:450])
                mute_role = guild.get_role(self.mute_roles.get(guild.id, 0))
                if mute_role and mute_role not in target.roles:
                    await target.add_roles(mute_role, reason=reason[:450])
            elif canonical == "unmute":
                await target.timeout(None, reason=reason[:450])
                mute_role = guild.get_role(self.mute_roles.get(guild.id, 0))
                if mute_role and mute_role in target.roles:
                    await target.remove_roles(mute_role, reason=reason[:450])

            case_id = await self._case(message, canonical, target, reason, duration)
            await self._dm(target, guild, canonical, reason, duration)
            await self._punishment_embed(message, target, action, reason, duration, case_id)
        except discord.Forbidden:
            await self._reply(message, "Discord denied the action. Check bot permissions and role hierarchy.")
        except discord.HTTPException:
            logger.exception("Moderation action %s failed", action)
            await self._reply(message, f"{action.title()} failed due to a Discord API error.")

    async def _expire_ban(self, guild_id: int, user_id: int, seconds: int):
        await asyncio.sleep(seconds)
        guild = self.bot.get_guild(guild_id)
        if guild:
            try:
                await guild.unban(discord.Object(id=user_id), reason="Temporary ban expired")
            except discord.HTTPException:
                logger.exception("Temporary ban expiration failed for %s", user_id)

    async def _case_command(self, message: discord.Message, action: str, args: str):
        if not (
            await self._has(message, "moderate_members", allow_mod_role=True)
            or await self._has(message, "manage_messages", allow_mod_role=True)
        ):
            return await self._reply(
                message, "You need Moderate Members or Manage Messages permission (or the configured moderator role)."
            )
        if action in ("warnings", "infractions", "clearwarn"):
            target = next(iter(self._targets(message, args)), None)
            if not target:
                return await self._reply(message, "Mention a member.")
            if action == "clearwarn":
            if action == "clearwarn":
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        "DELETE FROM mod_cases WHERE guild_id=? AND target_id=? AND action='warn'",
                        (message.guild.id, target.id),
                    )
                    await db.commit()
                return await self._reply(message, f"Cleared **{cur.rowcount}** warnings for {target.mention}.")

            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT case_id,reason,created_at,moderator_id FROM mod_cases WHERE guild_id=? AND target_id=? AND action='warn' ORDER BY case_id DESC",
                    (message.guild.id, target.id),
                ) as cur:
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
                cur = await db.execute(
                    "DELETE FROM mod_cases WHERE guild_id=? AND case_id=? AND action='warn'", (message.guild.id, case_id)
                )
                await db.commit()
            return await self._reply(message, f"Removed warning Case #{case_id}." if cur.rowcount else "Warning case not found.")

        new_reason = re.sub(r"^\s*\d+\s*", "", args).strip()
        if not new_reason:
            return await self._reply(message, "Provide the new reason after the case ID.")
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "UPDATE mod_cases SET reason=? WHERE guild_id=? AND case_id=?", (new_reason, message.guild.id, case_id)
            )
            await db.commit()
        return await self._reply(message, f"Updated reason for Case #{case_id}." if cur.rowcount else "Case not found.")
    async def _channel_command(self, message: discord.Message, action: str, args: str):
        guild = message.guild
        channel = message.channel

        if action in ("purge", "cleanup"):
            if not await self._has(message, "manage_messages", allow_mod_role=True):
                return await self._reply(message, "You and I both need Manage Messages permission.")
            num_match = re.search(r"\b(\d+)\b", args)
            limit = min(max(int(num_match.group(1)), 1), 100) if num_match else 10
            targets = self._targets(message, args)

            def check(msg: discord.Message) -> bool:
                if msg.id == message.id:
                    return False
                if action == "cleanup":
                    return msg.author.bot
                if targets:
                    return msg.author.id in {t.id for t in targets}
                return True

            try:
                await message.delete()
            except discord.HTTPException:
                pass
            deleted = await channel.purge(limit=limit + (10 if targets or action == "cleanup" else 0), check=check)
            return await channel.send(f"Deleted **{len(deleted)}** messages.", delete_after=4)

        if not await self._has(message, "manage_channels"):
            return await self._reply(message, "You and I both need Manage Channels permission.")

        if action in ("lockdown", "unlockdown"):
            target_ch = self._find_channel(guild, args) or channel
            if not isinstance(target_ch, discord.TextChannel):
                return await self._reply(message, "Specify a valid text channel.")
            overwrite = target_ch.overwrites_for(guild.default_role)
            overwrite.send_messages = False if action == "lockdown" else None
            await target_ch.set_permissions(guild.default_role, overwrite=overwrite, reason=f"{action} by {message.author}")
            state = "locked" if action == "lockdown" else "unlocked"
            return await self._reply(message, f"{target_ch.mention} has been **{state}**.")

        if action == "slowmode":
            if not isinstance(channel, discord.TextChannel):
                return
            if args.lower() in ("off", "disable", "0", "none"):
                sec = 0
            else:
                sec = duration_seconds(args)
                if sec is None and args.isdigit():
                    sec = int(args)
            if sec is None or sec < 0 or sec > 21600:
                return await self._reply(
                    message, "Provide a slowmode duration between `0s` and `6h` (e.g. `slowmode 10s` or `slowmode off`)."
                )
            await channel.edit(slowmode_delay=sec, reason=f"Slowmode by {message.author}")
            return await self._reply(message, f"Slowmode set to **{duration_label(sec) if sec else 'off'}** in {channel.mention}.")

        if action in ("createchannel", "channelcreate"):
            parts = args.split()
            if not parts:
                return await self._reply(message, "Usage: `createchannel [text|voice|category] <name>`.")
            ch_type = "text"
            if parts[0].lower() in ("text", "voice", "vc", "category"):
                ch_type = parts.pop(0).lower()
            name = "-".join(parts) if ch_type == "text" else " ".join(parts)
            if not name:
                return await self._reply(message, "Provide a channel name.")
            category = channel.category if isinstance(channel, discord.abc.GuildChannel) else None
            if ch_type in ("voice", "vc"):
                created = await guild.create_voice_channel(name=name[:100], category=category, reason=f"Created by {message.author}")
            elif ch_type == "category":
                created = await guild.create_category(name=name[:100], reason=f"Created by {message.author}")
            else:
                created = await guild.create_text_channel(name=name[:100], category=category, reason=f"Created by {message.author}")
            return await self._reply(message, f"Created **{ch_type}** channel {created.mention} (`{created.name}`).")

        if action in ("delchannel", "channeldelete"):
            target_ch = self._find_channel(guild, args) or (channel if not args else None)
            if not target_ch:
                return await self._reply(message, "Mention or name a valid channel to delete.")
            ch_name = target_ch.name
            await target_ch.delete(reason=f"Deleted by {message.author}")
            if target_ch.id != channel.id:
                return await self._reply(message, f"Deleted channel **#{ch_name}**.")
            return None

        if action == "nuke":
            target_ch = self._find_channel(guild, args) or channel
            if not isinstance(target_ch, discord.TextChannel):
                return await self._reply(message, "Only text channels can be nuked.")
            pos = target_ch.position
            cloned = await target_ch.clone(reason=f"Channel nuked by {message.author}")
            await cloned.edit(position=pos)
            await target_ch.delete(reason=f"Channel nuked by {message.author}")
            return await cloned.send(f"Channel nuked by {message.author.mention}.")
    async def _role_command(self, message: discord.Message, action: str, args: str):
        guild = message.guild
        bot_member = guild.me
        if not await self._has(message, "manage_roles"):
            return await self._reply(message, "You and I both need Manage Roles permission.")

        if action in ("createrole", "rolecreate"):
            color_match = re.search(r"#?([0-9a-fA-F]{6})\b", args)
            color = discord.Color(int(color_match.group(1), 16)) if color_match else discord.Color.default()
            name = re.sub(r"#?[0-9a-fA-F]{6}\b", "", args).strip()
            if not name:
                return await self._reply(message, "Usage: `createrole <name> [#hexcolor]`.")
            role = await guild.create_role(name=name[:100], color=color, reason=f"Created by {message.author}")
            return await self._reply(message, f"Created role {role.mention} (`{role.id}`).")

        if action in ("delrole", "roledelete"):
            role = self._find_role(guild, args)
            if not role:
                return await self._reply(message, "Mention or name the role to delete.")
            if role.managed or role >= bot_member.top_role or (
                message.author.id not in (guild.owner_id, BOT_OWNER_ID) and role >= message.author.top_role
            ):
                return await self._reply(message, "Cannot delete that role due to role hierarchy or integration.")
            rname = role.name
            await role.delete(reason=f"Deleted by {message.author}")
            return await self._reply(message, f"Deleted role **{rname}**.")

        if action == "rolecolor":
            color_match = re.search(r"#?([0-9a-fA-F]{6})\b", args)
            if not color_match:
                return await self._reply(message, "Usage: `rolecolor <role> <#hexcolor>`.")
            role_query = re.sub(r"#?[0-9a-fA-F]{6}\b", "", args).strip()
            role = self._find_role(guild, role_query)
            if not role:
                return await self._reply(message, "Role not found.")
            if role >= bot_member.top_role or (
                message.author.id not in (guild.owner_id, BOT_OWNER_ID) and role >= message.author.top_role
            ):
                return await self._reply(message, "Cannot edit that role due to role hierarchy.")
            color = discord.Color(int(color_match.group(1), 16))
            await role.edit(color=color, reason=f"Role color updated by {message.author}")
            return await self._reply(message, f"Updated color for {role.mention} to `#{color_match.group(1).upper()}`.")

        targets = self._targets(message, args)
        if not targets:
            return await self._reply(message, f"Usage: `{action} @user <role>`.")
        target = targets[0]
        role_query = re.sub(r"<@!?\d+>|\b\d{15,22}\b", "", args).strip()
        role = self._find_role(guild, role_query)
        if not role:
            return await self._reply(message, "Specify a valid role name, mention, or ID.")
        if role.managed or role >= bot_member.top_role or (
            message.author.id not in (guild.owner_id, BOT_OWNER_ID) and role >= message.author.top_role
        ):
            return await self._reply(message, "Cannot assign/remove that role due to role hierarchy.")

        if action == "addrole" or (action == "role" and role not in target.roles):
            await target.add_roles(role, reason=f"Added by {message.author}")
            return await self._reply(message, f"Added {role.mention} to {target.mention}.")
        else:
            await target.remove_roles(role, reason=f"Removed by {message.author}")
            return await self._reply(message, f"Removed {role.mention} from {target.mention}.")
    async def _config_or_info_command(self, message: discord.Message, action: str, args: str):
        guild = message.guild

        if action in ("userinfo", "whois"):
            target = next(iter(self._targets(message, args)), message.author)
            roles = [r.mention for r in reversed(target.roles[1:])]
            embed = discord.Embed(title=f"User Info · {target}", color=target.color or discord.Color.blurple())
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.add_field(name="ID", value=f"`{target.id}`", inline=True)
            embed.add_field(name="Created", value=discord.utils.format_dt(target.created_at, "R"), inline=True)
            if target.joined_at:
                embed.add_field(name="Joined", value=discord.utils.format_dt(target.joined_at, "R"), inline=True)
            embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles[:15]) or "None", inline=False)
            return await self._send_embed(message, embed)

        if action == "serverinfo":
            embed = discord.Embed(title=guild.name, color=discord.Color.blurple())
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            embed.add_field(name="Owner", value=f"<@{guild.owner_id}>", inline=True)
            embed.add_field(name="Members", value=str(guild.member_count), inline=True)
            embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
            embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
            embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, "R"), inline=True)
            return await self._send_embed(message, embed)

        if not (
            message.author.id in (guild.owner_id, BOT_OWNER_ID)
            or message.author.guild_permissions.administrator
            or message.author.guild_permissions.manage_guild
        ):
            return await self._reply(message, "You need Administrator or Manage Server permission to change bot settings.")

        if action == "modrole":
            role = self._find_role(guild, args)
            if not role:
                return await self._reply(message, "Mention or name the role to set as Moderator role.")
            self.mod_roles[guild.id] = role.id
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO mod_config (guild_id, mod_role_id) VALUES (?, ?) "
                    "ON CONFLICT(guild_id) DO UPDATE SET mod_role_id=excluded.mod_role_id",
                    (guild.id, role.id),
                )
                await db.commit()
            return await self._reply(message, f"Moderator role set to {role.mention}.")

        if action == "muterole":
            role = self._find_role(guild, args)
            if not role:
                return await self._reply(message, "Mention or name the role to set as Mute role.")
            self.mute_roles[guild.id] = role.id
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO mod_config (guild_id, mute_role_id) VALUES (?, ?) "
                    "ON CONFLICT(guild_id) DO UPDATE SET mute_role_id=excluded.mute_role_id",
                    (guild.id, role.id),
                )
                await db.commit()
            return await self._reply(message, f"Mute role set to {role.mention}.")

        if action == "modlog":
            target_ch = self._find_channel(guild, args) or message.channel
            if not isinstance(target_ch, discord.TextChannel):
                return await self._reply(message, "Mention or name a valid text channel.")
            self.modlog_channels[guild.id] = target_ch.id
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO mod_config (guild_id, modlog_channel_id) VALUES (?, ?) "
                    "ON CONFLICT(guild_id) DO UPDATE SET modlog_channel_id=excluded.modlog_channel_id",
                    (guild.id, target_ch.id),
                )
                await db.commit()
            return await self._reply(message, f"Moderation log channel set to {target_ch.mention}.")

        if action in ("modonly", "unmodonly"):
            target_ch = self._find_channel(guild, args) or message.channel
            async with aiosqlite.connect(DB_PATH) as db:
                if action == "modonly":
                    self.modonly_channels.add(target_ch.id)
                    await db.execute(
                        "INSERT OR IGNORE INTO modonly_channels (channel_id, guild_id) VALUES (?, ?)",
                        (target_ch.id, guild.id),
                    )
                else:
                    self.modonly_channels.discard(target_ch.id)
                    await db.execute("DELETE FROM modonly_channels WHERE channel_id=?", (target_ch.id,))
                await db.commit()
            state = "restricted to moderators only" if action == "modonly" else "opened to all members"
            return await self._reply(message, f"{target_ch.mention} is now **{state}**.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return

        if message.channel.id in self.modonly_channels and not self._is_mod(message.author):
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return

        raw = self._normalize(message)
        match = re.match(r"^(" + "|".join(sorted(COMMANDS, key=len, reverse=True)) + r")\b\s*(.*)$", raw, re.I)
        if not match:
            return

        action, args = match.group(1).lower(), match.group(2).strip()
        if action == "help":
            return

        try:
            if action in ("warn", "ban", "tempban", "softban", "massban", "kick", "mute", "timeout", "unmute", "removetimeout"):
                return await self._punishment(message, action, args)

            if action in ("warnings", "infractions", "clearwarn", "removewarn", "reason"):
                return await self._case_command(message, action, args)

            if action in ("purge", "cleanup", "lockdown", "unlockdown", "slowmode", "createchannel", "channelcreate", "delchannel", "channeldelete", "nuke"):
                return await self._channel_command(message, action, args)

            if action in ("createrole", "rolecreate", "delrole", "roledelete", "rolecolor", "addrole", "removerole", "role"):
                return await self._role_command(message, action, args)

            if action in ("userinfo", "whois", "serverinfo", "modrole", "muterole", "modlog", "modonly", "unmodonly"):
                return await self._config_or_info_command(message, action, args)

            if action == "unban":
                if not await self._has(message, "ban_members", allow_mod_role=True):
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

        except discord.NotFound:
            await self._reply(message, "That member, channel, role, or case could not be found.")
        except discord.Forbidden:
            await self._reply(message, "Discord denied the action. Check the bot's permissions and role hierarchy.")
        except discord.HTTPException:
            logger.exception("Moderation command %s failed", action)
            await self._reply(message, "The moderation command failed due to a Discord API error.")
        except Exception:
            logger.exception("Unexpected error handling moderation command %s", action)
            await self._reply(message, "The moderation command failed unexpectedly. Check the service logs.")


async def setup(bot: commands.Bot):
    await bot.add_cog(ConversationalModerationCog(bot))
