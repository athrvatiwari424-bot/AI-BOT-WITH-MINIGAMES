"""Permission-checked conversational moderation for Discord text chat."""

import asyncio
import logging
import re
import time
from datetime import datetime, timezone

import aiosqlite
import discord
from discord.ext import commands

logger = logging.getLogger("conversational_moderation")
DB_PATH = "bot_data.db"
MAX_PURGE = 100
MAX_MASSBAN = 10
BOT_OWNER_ID = 1170682591414861896
COMMANDS = (
    "unlockdown", "lockdown", "muterole", "removewarn", "clearwarn", "tempban",
    "softban", "massban", "cleanup", "unmute", "unmodonly", "modonly", "modrole",
    "purge", "warn", "kick", "ban", "mute",
)


class ConversationalModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.mute_roles: dict[int, int] = {}
        self.mod_roles: dict[int, int] = {}
        self.mod_only_channels: set[int] = set()
        self.tempban_tasks: set[asyncio.Task] = set()

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("CREATE TABLE IF NOT EXISTS mod_config (guild_id INTEGER PRIMARY KEY, mute_role_id INTEGER, mod_role_id INTEGER)")
            await db.execute("CREATE TABLE IF NOT EXISTS mod_warnings (case_id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            await db.execute("CREATE TABLE IF NOT EXISTS mod_only_channels (channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL)")
            await db.execute("CREATE TABLE IF NOT EXISTS lockdown_overwrites (channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, send_messages INTEGER)")
            await db.execute("CREATE TABLE IF NOT EXISTS temp_bans (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, expires_at REAL NOT NULL, PRIMARY KEY (guild_id, user_id))")
            await db.commit()
            async with db.execute("SELECT guild_id, mute_role_id, mod_role_id FROM mod_config") as cur:
                for guild_id, mute_id, mod_id in await cur.fetchall():
                    if mute_id:
                        self.mute_roles[guild_id] = mute_id
                    if mod_id:
                        self.mod_roles[guild_id] = mod_id
            async with db.execute("SELECT channel_id FROM mod_only_channels") as cur:
                self.mod_only_channels.update(row[0] for row in await cur.fetchall())
            async with db.execute("SELECT guild_id, user_id, expires_at FROM temp_bans") as cur:
                for guild_id, user_id, expires_at in await cur.fetchall():
                    task = asyncio.create_task(self._schedule_unban(guild_id, user_id, max(0, expires_at - time.time())))
                    self.tempban_tasks.add(task)
                    task.add_done_callback(self.tempban_tasks.discard)

    @staticmethod
    def _member(message: discord.Message) -> discord.Member | None:
        return message.author if isinstance(message.author, discord.Member) else None

    def _is_mod(self, member: discord.Member, guild: discord.Guild) -> bool:
        role_id = self.mod_roles.get(guild.id)
        return (
            member.id in (guild.owner_id, BOT_OWNER_ID)
            or member.guild_permissions.administrator
            or member.guild_permissions.manage_guild
            or bool(role_id and any(role.id == role_id for role in member.roles))
        )

    async def _send(self, message: discord.Message, text: str):
        try:
            await message.reply(text[:1900], mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            try:
                await message.channel.send(text[:1900], allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                logger.exception("Could not send moderation response")

    async def _has(self, message: discord.Message, permission: str) -> bool:
        member = self._member(message)
        bot_member = message.guild.me if message.guild else None
        return bool(
            member and bot_member
            and getattr(member.guild_permissions, permission, False)
            and getattr(bot_member.guild_permissions, permission, False)
        )

    @staticmethod
    def _targets(message: discord.Message, text: str) -> list[discord.Member]:
        guild = message.guild
        if not guild or not guild.me:
            return []
        targets = {member.id: member for member in message.mentions if member.id != guild.me.id}
        for raw in re.findall(r"(?<!\d)(\d{15,22})(?!\d)", text):
            member = guild.get_member(int(raw))
            if member and member.id != guild.me.id:
                targets[member.id] = member
        return list(targets.values())

    def _hierarchy_ok(self, message: discord.Message, target: discord.Member) -> bool:
        actor = self._member(message)
        bot_member = message.guild.me
        if not actor or not bot_member or target.id in (actor.id, message.guild.owner_id):
            return False
        return target.top_role < bot_member.top_role and (
            actor.id == message.guild.owner_id or target.top_role < actor.top_role
        )

    async def _config_save(self, guild_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO mod_config (guild_id, mute_role_id, mod_role_id) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET mute_role_id=excluded.mute_role_id, mod_role_id=excluded.mod_role_id",
                (guild_id, self.mute_roles.get(guild_id), self.mod_roles.get(guild_id)),
            )
            await db.commit()

    async def _warn(self, message: discord.Message, target: discord.Member, reason: str):
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "INSERT INTO mod_warnings (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
                (message.guild.id, target.id, message.author.id, reason[:500] or "No reason provided"),
            )
            await db.commit()
            case_id = cursor.lastrowid
        await self._send(message, f"⚠️ Warned **{target.display_name}** (case `{case_id}`).")

    async def _purge(self, message: discord.Message, mode: str, argument: str):
        if not await self._has(message, "manage_messages"):
            return await self._send(message, "You and I both need Manage Messages permission.")
        if not isinstance(message.channel, discord.TextChannel):
            return await self._send(message, "This cleanup is supported only in server text channels.")
        count_match = re.search(r"\b(\d{1,3})\b", argument)
        amount = min(MAX_PURGE, int(count_match.group(1))) if count_match else 25
        phrase = ""
        if mode == "contains":
            raw_phrase = re.sub(r"\s+\d{1,3}\s*$", "", argument).strip()
            phrase = raw_phrase.strip(' \t\r\n\"“”\'')
            if not phrase:
                return await self._send(message, 'Use `purge contains "phrase" 25`.')
        user = next(iter(message.mentions), None)
        if mode == "user" and user is None:
            return await self._send(message, "Use `purge user @member 25`.")
        custom_emoji = re.compile(r"<a?:\w+:\d+>")
        link = re.compile(r"(?:https?://|www\.)\S+", re.I)

        def check(item: discord.Message) -> bool:
            if item.id == message.id:
                return True
            if mode == "user":
                return bool(user and item.author.id == user.id)
            if mode == "bot":
                return item.author.bot
            if mode == "contains":
                return phrase.casefold() in item.content.casefold()
            if mode == "links":
                return bool(link.search(item.content))
            if mode == "images":
                return bool(item.embeds or any(a.content_type and a.content_type.startswith("image/") for a in item.attachments))
            if mode == "files":
                return bool(item.attachments)
            if mode == "embeds":
                return bool(item.embeds)
            if mode == "emoji":
                return bool(custom_emoji.search(item.content))
            if mode == "cleanup":
                carl_message = item.author.bot and "carl" in item.author.name.casefold()
                command_trigger = item.content.startswith("!")
                return carl_message or command_trigger
            return True

        try:
            deleted = await message.channel.purge(limit=amount + 1, check=check, bulk=False)
            count = len(deleted) - (1 if any(item.id == message.id for item in deleted) else 0)
            await self._send(message, f"🧹 Deleted {count} message(s).")
        except discord.Forbidden:
            await self._send(message, "Discord denied cleanup; check Manage Messages and Read Message History.")
        except discord.HTTPException:
            logger.exception("Purge failed")
            await self._send(message, "Cleanup failed because of a Discord API error.")

    async def _lock_channel(self, channel: discord.TextChannel, locked: bool, reason: str):
        everyone = channel.guild.default_role
        overwrite = channel.overwrites_for(everyone)
        async with aiosqlite.connect(DB_PATH) as db:
            if locked:
                await db.execute(
                    "INSERT OR IGNORE INTO lockdown_overwrites (channel_id, guild_id, send_messages) VALUES (?, ?, ?)",
                    (channel.id, channel.guild.id, None if overwrite.send_messages is None else int(overwrite.send_messages)),
                )
            else:
                async with db.execute("SELECT send_messages FROM lockdown_overwrites WHERE channel_id=?", (channel.id,)) as cur:
                    row = await cur.fetchone()
                await db.execute("DELETE FROM lockdown_overwrites WHERE channel_id=?", (channel.id,))
            await db.commit()
        if locked:
            overwrite.send_messages = False
        else:
            overwrite.send_messages = None if not row or row[0] is None else bool(row[0])
        await channel.set_permissions(everyone, overwrite=overwrite, reason=reason)

    async def _schedule_unban(self, guild_id: int, user_id: int, seconds: float):
        await asyncio.sleep(seconds)
        guild = self.bot.get_guild(guild_id)
        try:
            if guild:
                await guild.unban(discord.Object(id=user_id), reason="Temporary ban expired")
        except discord.NotFound:
            pass
        except discord.HTTPException:
            logger.exception("Could not expire temporary ban for %s", user_id)
        finally:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM temp_bans WHERE guild_id=? AND user_id=?", (guild_id, user_id))
                await db.commit()

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        role_id = self.mute_roles.get(channel.guild.id)
        role = channel.guild.get_role(role_id) if role_id else None
        if role and isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
            try:
                overwrite = channel.overwrites_for(role)
                overwrite.send_messages = False
                overwrite.speak = False
                await channel.set_permissions(role, overwrite=overwrite, reason="Apply configured mute-role restrictions")
            except discord.HTTPException:
                logger.exception("Could not configure mute role on channel %s", channel.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return
        member = message.author
        content = message.content.strip()
        # Enforce modonly on prefix commands and conversational moderation phrases.
        if message.channel.id in self.mod_only_channels and not self._is_mod(member, message.guild):
            if content.startswith("!") or re.match(r"^(?:liebe[\s,]+)?(?:" + "|".join(COMMANDS) + r")\b", content, re.I):
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
                await self._send(message, "Commands are restricted to moderators in this channel.")
                return
        raw = re.sub(r"^(?:liebe[\s,]+)", "", content, flags=re.I).strip()
        if self.bot.user:
            raw = re.sub(rf"^<@!?{self.bot.user.id}>\s*", "", raw).strip()
        if re.fullmatch(r"help", raw, re.I):
            return
        match = re.match(r"^(" + "|".join(COMMANDS) + r")\b\s*(.*)$", raw, re.I)
        if not match:
            return
        action, args = match.group(1).lower(), match.group(2).strip()
        if not self._is_mod(member, message.guild):
            await self._send(message, "Only server moderators can use conversational moderation.")
            return
        await self._dispatch(message, action, args)

    async def _dispatch(self, message: discord.Message, action: str, args: str):
        guild, actor = message.guild, message.author
        if action in ("ban", "kick", "softban", "tempban", "massban"):
            permission = "kick_members" if action == "kick" else "ban_members"
            if not await self._has(message, permission):
                return await self._send(message, f"You and I both need {permission.replace('_', ' ').title()} permission.")
            targets = self._targets(message, args)
            if not targets:
                return await self._send(message, f"Mention target member(s): `{action} @member [reason/duration]`.")
            if action != "massban" and len(targets) != 1:
                return await self._send(message, "Use one target for this action.")
            if action == "massban" and len(targets) > MAX_MASSBAN:
                return await self._send(message, f"Massban is limited to {MAX_MASSBAN} members per request.")
            if any(not self._hierarchy_ok(message, target) for target in targets):
                return await self._send(message, "I cannot act on one or more targets because of self-targeting, ownership, or role hierarchy.")
            target = targets[0]
            reason = re.sub(r"<@!?\d+>|\b\d{15,22}\b", "", args).strip() or f"Requested by {actor}"
            try:
                if action == "kick":
                    await target.kick(reason=reason[:450])
                    return await self._send(message, f"👢 Kicked **{target.display_name}**.")
                if action == "softban":
                    await target.ban(reason=reason[:450], delete_message_seconds=86400)
                    await guild.unban(target, reason=f"Softban by {actor}")
                    return await self._send(message, f"✅ Softbanned **{target.display_name}** (removed recent messages and kicked them).")
                if action == "tempban":
                    duration = re.search(r"\b(\d+)(s|m|h|d)\b", args, re.I)
                    if not duration:
                        return await self._send(message, "Use `tempban @member 1d [reason]` (s/m/h/d supported).")
                    amount, unit = int(duration.group(1)), duration.group(2).lower()
                    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
                    if seconds < 60 or seconds > 365 * 86400:
                        return await self._send(message, "Temporary bans must be between 1 minute and 365 days.")
                    expires_at = time.time() + seconds
                    await target.ban(reason=reason[:450])
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute("INSERT INTO temp_bans (guild_id, user_id, expires_at) VALUES (?, ?, ?) ON CONFLICT(guild_id, user_id) DO UPDATE SET expires_at=excluded.expires_at", (guild.id, target.id, expires_at))
                        await db.commit()
                    task = asyncio.create_task(self._schedule_unban(guild.id, target.id, seconds))
                    self.tempban_tasks.add(task)
                    task.add_done_callback(self.tempban_tasks.discard)
                    return await self._send(message, f"🔨 Temporarily banned **{target.display_name}** for `{amount}{unit}`.")
                if action == "massban":
                    succeeded = 0
                    for current in targets:
                        try:
                            await current.ban(reason=f"Massban by {actor}: {reason[:350]}")
                            succeeded += 1
                        except discord.HTTPException:
                            logger.exception("Massban failed for member %s", current.id)
                    return await self._send(message, f"🔨 Massban completed: {succeeded}/{len(targets)} banned.")
                await target.ban(reason=reason[:450])
                return await self._send(message, f"🔨 Banned **{target.display_name}**.")
            except discord.Forbidden:
                return await self._send(message, "Discord denied the action; check my permissions and role hierarchy.")
            except discord.HTTPException:
                logger.exception("%s failed", action)
                return await self._send(message, f"{action.title()} failed due to a Discord API error.")

        if action == "warn":
            target = next(iter(self._targets(message, args)), None)
            if not target:
                return await self._send(message, "Use `warn @member [reason]`.")
            if not self._hierarchy_ok(message, target):
                return await self._send(message, "The target must be below your and the bot's role positions.")
            return await self._warn(message, target, re.sub(r"<@!?\d+>", "", args).strip())

        if action == "removewarn":
            if not self._is_mod(actor, guild):
                return await self._send(message, "Only moderators can remove warnings.")
            case = re.search(r"\b(\d+)\b", args)
            if not case:
                return await self._send(message, "Use `removewarn CASE_ID`.")
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("DELETE FROM mod_warnings WHERE guild_id=? AND case_id=?", (guild.id, int(case.group(1))))
                await db.commit()
            return await self._send(message, "✅ Warning removed." if cursor.rowcount else "No warning found with that case ID in this server.")

        if action == "clearwarn":
            if not self._is_mod(actor, guild):
                return await self._send(message, "Only moderators can clear warnings.")
            target = next(iter(self._targets(message, args)), None)
            if not target:
                return await self._send(message, "Use `clearwarn @member`.")
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("DELETE FROM mod_warnings WHERE guild_id=? AND user_id=?", (guild.id, target.id))
                await db.commit()
            return await self._send(message, f"✅ Removed {cursor.rowcount} warning(s) for **{target.display_name}**.")

        if action == "purge":
            mode_match = re.match(r"(user|bot|contains|links|images|files|embeds|emoji|reactions)\b\s*(.*)$", args, re.I)
            mode, rest = (mode_match.group(1).lower(), mode_match.group(2).strip()) if mode_match else ("all", args)
            if mode == "reactions":
                if not await self._has(message, "manage_messages"):
                    return await self._send(message, "You and I both need Manage Messages permission.")
                if not isinstance(message.channel, discord.TextChannel):
                    return await self._send(message, "Use this in a text channel.")
                number = re.search(r"\b(\d{1,3})\b", rest)
                amount = min(MAX_PURGE, int(number.group(1))) if number else 25
                try:
                    async for item in message.channel.history(limit=amount):
                        if item.reactions:
                            await item.clear_reactions()
                    return await self._send(message, f"✅ Cleared reactions from the latest {amount} messages.")
                except discord.HTTPException:
                    return await self._send(message, "Could not clear reactions; check Manage Messages permission.")
            if mode == "all" and not re.search(r"\d", args):
                return await self._send(message, "Use `purge 25`, or `purge user @member 25`, `purge contains phrase 25`, etc.")
            return await self._purge(message, mode, rest if mode_match else args)

        if action == "cleanup":
            return await self._purge(message, "cleanup", args)

        if action in ("lockdown", "unlockdown"):
            locked = action == "lockdown"
            server = args.casefold().startswith("server")
            if not await self._has(message, "manage_channels"):
                return await self._send(message, "You and I both need Manage Channels permission.")
            if server:
                channels = [ch for ch in guild.text_channels if guild.me and ch.permissions_for(guild.me).manage_channels]
            elif isinstance(message.channel, discord.TextChannel):
                channels = [message.channel]
            else:
                return await self._send(message, "Lockdown is available in text channels only.")
            changed = 0
            for channel in channels:
                try:
                    await self._lock_channel(channel, locked, f"{action} requested by {actor}")
                    changed += 1
                except discord.HTTPException:
                    logger.exception("Could not change lockdown for channel %s", channel.id)
            return await self._send(message, f"{'🔒 Locked' if locked else '🔓 Restored'} {changed} text channel(s).")

        if action in ("mute", "unmute"):
            target = next(iter(self._targets(message, args)), None)
            if not target:
                return await self._send(message, f"Use `{action} @member`.")
            if not self._hierarchy_ok(message, target):
                return await self._send(message, "Cannot act on that member due to role hierarchy.")
            role_id = self.mute_roles.get(guild.id)
            role = guild.get_role(role_id) if role_id else None
            if not role:
                return await self._send(message, "Set the mute role first: `muterole @role` or `muterole create`.")
            if not await self._has(message, "manage_roles") or not guild.me or role >= guild.me.top_role:
                return await self._send(message, "You and I need Manage Roles, and the mute role must be below the bot's top role.")
            try:
                if action == "mute":
                    await target.add_roles(role, reason=f"Muted by {actor}")
                else:
                    await target.remove_roles(role, reason=f"Unmuted by {actor}")
                return await self._send(message, f"✅ {'Muted' if action == 'mute' else 'Unmuted'} **{target.display_name}**.")
            except discord.HTTPException:
                return await self._send(message, "Discord denied that role change.")

        if action == "muterole":
            if not await self._has(message, "manage_roles"):
                return await self._send(message, "You and I both need Manage Roles permission.")
            sub = args.casefold()
            if sub.startswith("create"):
                if not await self._has(message, "manage_channels"):
                    return await self._send(message, "You and I both need Manage Channels to configure the new mute role.")
                try:
                    role = await guild.create_role(name="Muted", reason=f"Mute role created by {actor}")
                    self.mute_roles[guild.id] = role.id
                    await self._config_save(guild.id)
                    for channel in guild.channels:
                        if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
                            overwrite = channel.overwrites_for(role)
                            overwrite.send_messages = False
                            overwrite.speak = False
                            await channel.set_permissions(role, overwrite=overwrite, reason="Configure mute role restrictions")
                    return await self._send(message, f"✅ Created and configured mute role **{role.name}**.")
                except discord.HTTPException:
                    return await self._send(message, "Could not create/configure the mute role; check Manage Roles and Manage Channels.")
            if sub.startswith("update"):
                role_id = self.mute_roles.get(guild.id)
                role = guild.get_role(role_id) if role_id else None
                if not role:
                    return await self._send(message, "No mute role is configured.")
                for channel in guild.channels:
                    if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
                        try:
                            overwrite = channel.overwrites_for(role)
                            overwrite.send_messages = False
                            overwrite.speak = False
                            await channel.set_permissions(role, overwrite=overwrite, reason="Refresh mute role restrictions")
                        except discord.HTTPException:
                            logger.exception("Could not update mute role in channel %s", channel.id)
                return await self._send(message, "✅ Updated mute-role restrictions on current channels; future channels are handled automatically.")
            role = next((role for role in guild.roles if f"<@&{role.id}>" in args), None)
            if not role:
                role = discord.utils.find(lambda item: item.name.casefold() == args.strip().strip('"“”').casefold(), guild.roles)
            if not role or role.is_default() or role.managed or not guild.me or role >= guild.me.top_role:
                return await self._send(message, "Mention or name an eligible role below my top role: `muterole @role`.")
            self.mute_roles[guild.id] = role.id
            await self._config_save(guild.id)
            return await self._send(message, f"✅ **{role.name}** is now the mute role. Use `muterole update` to configure restrictions.")

        if action == "modrole":
            if not await self._has(message, "manage_guild"):
                return await self._send(message, "You and I both need Manage Server permission.")
            role = next((role for role in guild.roles if f"<@&{role.id}>" in args), None)
            if not role:
                role = discord.utils.find(lambda item: item.name.casefold() == args.strip().strip('"“”').casefold(), guild.roles)
            if not role or role.is_default() or role.managed:
                return await self._send(message, "Mention or name a valid moderator role: `modrole @role`.")
            self.mod_roles[guild.id] = role.id
            await self._config_save(guild.id)
            return await self._send(message, f"✅ **{role.name}** is recognized as the moderator role.")

        if action in ("modonly", "unmodonly"):
            if not await self._has(message, "manage_channels"):
                return await self._send(message, "You and I both need Manage Channels permission.")
            enabled = action == "modonly"
            if enabled:
                self.mod_only_channels.add(message.channel.id)
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("INSERT OR IGNORE INTO mod_only_channels (channel_id, guild_id) VALUES (?, ?)", (message.channel.id, guild.id))
                    await db.commit()
            else:
                self.mod_only_channels.discard(message.channel.id)
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("DELETE FROM mod_only_channels WHERE channel_id=?", (message.channel.id,))
                    await db.commit()
            return await self._send(message, f"✅ Bot commands are {'moderator-only' if enabled else 'available to everyone'} in this channel.")


async def setup(bot: commands.Bot):
    await bot.add_cog(ConversationalModerationCog(bot))
