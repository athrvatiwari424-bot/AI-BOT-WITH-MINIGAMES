"""Deterministic conversational moderation and server-management commands.

Messages are parsed only when they begin with an explicit command phrase (optionally
prefixed by `Liebe,`). This avoids asking a generative model to infer whether a user
intended a destructive moderation action.
"""

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
BOT_OWNER_ID = 1170682591414861896
MAX_PURGE = 100
MAX_MASSBAN = 10
MAX_ROLE_BATCH = 100

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
    factor = 1 if unit.startswith("s") else 60 if unit.startswith("m") else 3600 if unit.startswith("h") else 86400
    return n * factor


def duration_label(seconds: int) -> str:
    for unit, factor in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds and seconds % factor == 0:
            return f"{seconds // factor}{unit}"
    return f"{seconds}s"


class ConversationalModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.mute_roles: dict[int, int] = {}
        self.mod_roles: dict[int, int] = {}
        self.modlog_channels: dict[int, int] = {}
        self.mod_only_channels: set[int] = set()
        self.tempban_tasks: set[asyncio.Task] = set()
        self.lock_tasks: set[asyncio.Task] = set()

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("CREATE TABLE IF NOT EXISTS mod_config (guild_id INTEGER PRIMARY KEY, mute_role_id INTEGER, mod_role_id INTEGER, modlog_channel_id INTEGER)")
            await db.execute("CREATE TABLE IF NOT EXISTS mod_cases (case_id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, action TEXT NOT NULL, target_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL, reason TEXT NOT NULL, duration TEXT, created_at TEXT NOT NULL, log_channel_id INTEGER, log_message_id INTEGER)")
            await db.execute("CREATE TABLE IF NOT EXISTS mod_only_channels (channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL)")
            await db.execute("CREATE TABLE IF NOT EXISTS lockdown_overwrites (channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, send_messages INTEGER)")
            await db.execute("CREATE TABLE IF NOT EXISTS scheduled_actions (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, action TEXT NOT NULL, expires_at REAL NOT NULL, PRIMARY KEY (guild_id,user_id,action))")
            await db.commit()
            async with db.execute("SELECT guild_id,mute_role_id,mod_role_id,modlog_channel_id FROM mod_config") as cur:
                for gid, mute, mod, log_channel in await cur.fetchall():
                    if mute: self.mute_roles[gid] = mute
                    if mod: self.mod_roles[gid] = mod
                    if log_channel: self.modlog_channels[gid] = log_channel
            async with db.execute("SELECT channel_id FROM mod_only_channels") as cur:
                self.mod_only_channels.update(row[0] for row in await cur.fetchall())
            async with db.execute("SELECT guild_id,user_id,action,expires_at FROM scheduled_actions") as cur:
                for gid, uid, action, expiry in await cur.fetchall():
                    task = asyncio.create_task(self._schedule_action(gid, uid, action, max(0, expiry-time.time())))
                    (self.tempban_tasks if action == "unban" else self.lock_tasks).add(task)
                    task.add_done_callback((self.tempban_tasks if action == "unban" else self.lock_tasks).discard)

    def _is_mod(self, member: discord.Member, guild: discord.Guild) -> bool:
        role_id = self.mod_roles.get(guild.id)
        return member.id in (guild.owner_id, BOT_OWNER_ID) or member.guild_permissions.administrator or member.guild_permissions.manage_guild or bool(role_id and any(r.id == role_id for r in member.roles))

    async def _has(self, message: discord.Message, permission: str) -> bool:
        actor, bot_member = message.author, message.guild.me
        return bool(isinstance(actor, discord.Member) and bot_member and getattr(actor.guild_permissions, permission, False) and getattr(bot_member.guild_permissions, permission, False))

    async def _reply(self, message: discord.Message, text: str, *, delete_after: float | None = None):
        try:
            sent = await message.reply(text[:1900], mention_author=False, allowed_mentions=discord.AllowedMentions.none(), delete_after=delete_after)
        except discord.HTTPException:
            try:
                sent = await message.channel.send(text[:1900], allowed_mentions=discord.AllowedMentions.none(), delete_after=delete_after)
            except discord.HTTPException:
                logger.exception("Could not send moderation response")
                return None
        return sent

    def _targets(self, message: discord.Message, text: str) -> list[discord.Member]:
        found = {m.id: m for m in message.mentions if message.guild.me and m.id != message.guild.me.id}
        for raw in re.findall(r"(?<!\d)(\d{15,22})(?!\d)", text):
            member = message.guild.get_member(int(raw))
            if member and (not message.guild.me or member.id != message.guild.me.id):
                found[member.id] = member
        return list(found.values())

    async def _resolve_ban_user(self, message: discord.Message, text: str) -> tuple[discord.User | discord.Member | None, int | None]:
        targets = self._targets(message, text)
        if targets:
            return targets[0], targets[0].id
        match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", text)
        if not match:
            return None, None
        uid = int(match.group(1))
        try:
            return await self.bot.fetch_user(uid), uid
        except discord.HTTPException:
            return None, uid

    def _hierarchy_ok(self, message: discord.Message, target: discord.Member) -> bool:
        actor, bot_member = message.author, message.guild.me
        return bool(isinstance(actor, discord.Member) and bot_member and target.id not in (actor.id, message.guild.owner_id) and target.top_role < bot_member.top_role and (actor.id == message.guild.owner_id or target.top_role < actor.top_role))

    async def _config_save(self, guild_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO mod_config (guild_id,mute_role_id,mod_role_id,modlog_channel_id) VALUES (?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET mute_role_id=excluded.mute_role_id,mod_role_id=excluded.mod_role_id,modlog_channel_id=excluded.modlog_channel_id", (guild_id,self.mute_roles.get(guild_id),self.mod_roles.get(guild_id),self.modlog_channels.get(guild_id)))
            await db.commit()

    async def _case(self, message: discord.Message, action: str, target_id: int, reason: str, duration: str | None = None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("INSERT INTO mod_cases (guild_id,action,target_id,moderator_id,reason,duration,created_at) VALUES (?,?,?,?,?,?,?)", (message.guild.id,action,target_id,message.author.id,reason,duration,now))
            await db.commit()
            case_id = cur.lastrowid
        channel = message.guild.get_channel(self.modlog_channels.get(message.guild.id, 0))
        if isinstance(channel, discord.TextChannel):
            target = message.guild.get_member(target_id)
            user_text = f"{target} ({target_id})" if target else f"<@{target_id}> ({target_id})"
            embed = discord.Embed(title=f"Moderation Case #{case_id} · {action.title()}", timestamp=datetime.now(timezone.utc), color=discord.Color.orange())
            embed.add_field(name="Target", value=user_text, inline=False)
            embed.add_field(name="Moderator", value=f"{message.author} ({message.author.id})", inline=False)
            embed.add_field(name="Reason", value=reason[:1024], inline=False)
            if duration: embed.add_field(name="Duration", value=duration, inline=True)
            try:
                log_message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("UPDATE mod_cases SET log_channel_id=?,log_message_id=? WHERE case_id=?", (channel.id,log_message.id,case_id))
                    await db.commit()
            except discord.HTTPException:
                logger.exception("Could not send mod log case %s", case_id)
        return case_id

    async def _dm(self, user: discord.abc.User, guild: discord.Guild, action: str, reason: str, duration: str | None = None):
        text = f"Server: **{guild.name}**\nAction: **{action}**\nReason: {reason}"
        if duration: text += f"\nDuration: **{duration}**"
        try: await user.send(text)
        except discord.HTTPException: pass

    async def _schedule_action(self, guild_id: int, user_id: int, action: str, seconds: float):
        await asyncio.sleep(seconds)
        guild = self.bot.get_guild(guild_id)
        try:
            if guild and action == "unban":
                await guild.unban(discord.Object(id=user_id), reason="Temporary ban expired")
            elif guild and action == "unmute":
                member = guild.get_member(user_id)
                if member:
                    await member.timeout(None, reason="Temporary mute expired")
                    role = guild.get_role(self.mute_roles.get(guild_id, 0))
                    if role: await member.remove_roles(role, reason="Temporary mute expired")
            elif guild and action.startswith("unlock:"):
                channel_id = int(action.split(":",1)[1])
                channel = guild.get_channel(channel_id)
                if isinstance(channel, discord.TextChannel): await self._set_lock(channel, False, "Timed lockdown expired")
        except discord.HTTPException:
            logger.exception("Scheduled moderation action failed")
        finally:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM scheduled_actions WHERE guild_id=? AND user_id=? AND action=?", (guild_id,user_id,action))
                await db.commit()

    async def _schedule(self, guild_id: int, user_id: int, action: str, seconds: int):
        expiry = time.time() + seconds
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO scheduled_actions (guild_id,user_id,action,expires_at) VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,action) DO UPDATE SET expires_at=excluded.expires_at", (guild_id,user_id,action,expiry))
            await db.commit()
        task = asyncio.create_task(self._schedule_action(guild_id,user_id,action,seconds))
        collection = self.tempban_tasks if action == "unban" else self.lock_tasks
        collection.add(task)
        task.add_done_callback(collection.discard)

    async def _punishment(self, message: discord.Message, action: str, args: str):
        guild, actor = message.guild, message.author
        user, uid = await self._resolve_ban_user(message, args)
        if uid is None or user is None:
            return await self._reply(message, f"Mention a user or provide their ID: `{action} @user [reason]`.")
        target = guild.get_member(uid)
        if target and not self._hierarchy_ok(message, target):
            return await self._reply(message, "I cannot act on that member because of ownership or role hierarchy.")
        if action in ("kick", "mute", "unmute", "warn") and target is None:
            return await self._reply(message, "That action requires the user to be a current server member.")
        perm = "kick_members" if action == "kick" else "moderate_members" if action in ("mute", "unmute") else "ban_members"
        if action != "warn" and not await self._has(message, perm):
            return await self._reply(message, f"You and I both need {perm.replace('_',' ').title()} permission.")
        days = 1 if action == "softban" else 0
        day_match = re.search(r"(?<!\w)([0-7])\s*(?:days?|d)\b", args, re.I)
        if day_match and action in ("ban", "softban"):
            days = int(day_match.group(1))
        duration_s = duration_seconds(args) if action in ("tempban", "mute") else None
        duration = duration_label(duration_s) if duration_s else None
        reason = re.sub(r"<@!?\d+>|\b\d{15,22}\b", "", args)
        reason = DURATION_RE.sub("", reason)
        reason = re.sub(r"(?<!\w)[0-7]\s*(?:days?|d)\b", "", reason, flags=re.I).strip(" ,|-") or "No reason provided"
        try:
            if action in ("ban", "tempban", "softban"):
                if action == "tempban" and (not duration_s or duration_s < 60 or duration_s > 365*86400):
                    return await self._reply(message, "Use a valid tempban duration from 1 minute to 365 days, e.g. `tempban @user 7d reason`.")
                await guild.ban(user, reason=reason[:450], delete_message_seconds=days*86400)
                if action == "softban": await guild.unban(discord.Object(id=uid), reason=f"Softban by {actor}")
                if action == "tempban": await self._schedule(guild.id,uid,"unban",duration_s)
                await self._dm(user,guild,action,reason,duration)
                await self._case(message,action,uid,reason,duration)
                mention = f"<@{uid}>"
                if action == "ban": text=f"🔨 **{mention}** has been banned. | **Reason:** {reason}"
                elif action == "tempban": text=f"⏳ **{mention}** has been temporarily banned for **{duration}**. | **Reason:** {reason}"
                else: text=f"🧹 **{mention}** has been softbanned (messages cleared). | **Reason:** {reason}"
                return await self._reply(message,text)
            if action == "kick":
                await target.kick(reason=reason[:450]); await self._dm(target,guild,action,reason); await self._case(message,action,uid,reason)
                return await self._reply(message,f"👢 **<@{uid}>** has been kicked. | **Reason:** {reason}")
            if action == "warn":
                case_id=await self._case(message,"warn",uid,reason); await self._dm(target,guild,"warn",reason)
                return await self._reply(message,f"⚠️ **<@{uid}>** has been warned. Please follow the server rules. | **Reason:** {reason} (Case #{case_id})")
            if action == "mute":
                if not duration_s or duration_s > 28*86400:
                    return await self._reply(message,"Use `mute @user 10m reason` (maximum timeout is 28 days).")
                await target.timeout(discord.utils.utcnow()+discord.timedelta(seconds=duration_s), reason=reason[:450])
                await self._dm(target,guild,action,reason,duration); await self._case(message,action,uid,reason,duration)
                return await self._reply(message,f"🔇 **<@{uid}>** has been muted for **{duration}**. | **Reason:** {reason}")
            if action == "unmute":
                await target.timeout(None,reason=reason[:450]); role=guild.get_role(self.mute_roles.get(guild.id,0))
                if role and role in target.roles: await target.remove_roles(role,reason=reason[:450])
                await self._case(message,action,uid,reason)
                return await self._reply(message,f"🔊 **<@{uid}>** has been unmuted. | **Reason:** {reason}")
        except discord.Forbidden:
            return await self._reply(message,"Discord denied the action. Check bot permissions and role hierarchy.")
        except discord.HTTPException:
            logger.exception("Punishment %s failed",action)
            return await self._reply(message,f"{action.title()} failed due to a Discord API error.")

    async def _set_lock(self, channel: discord.TextChannel, locked: bool, reason: str):
        everyone=channel.guild.default_role; overwrite=channel.overwrites_for(everyone)
        async with aiosqlite.connect(DB_PATH) as db:
            if locked:
                await db.execute("INSERT OR IGNORE INTO lockdown_overwrites (channel_id,guild_id,send_messages) VALUES (?,?,?)",(channel.id,channel.guild.id,None if overwrite.send_messages is None else int(overwrite.send_messages)))
                old=None
            else:
                async with db.execute("SELECT send_messages FROM lockdown_overwrites WHERE channel_id=?",(channel.id,)) as cur: old=await cur.fetchone()
                await db.execute("DELETE FROM lockdown_overwrites WHERE channel_id=?",(channel.id,))
            await db.commit()
        overwrite.send_messages=False if locked else (None if not old or old[0] is None else bool(old[0]))
        await channel.set_permissions(everyone,overwrite=overwrite,reason=reason)

    async def _purge(self,message:discord.Message,mode:str,args:str):
        if not await self._has(message,"manage_messages"): return await self._reply(message,"You and I both need Manage Messages permission.")
        if not isinstance(message.channel,discord.TextChannel): return await self._reply(message,"Purge works in text channels only.")
        count_match=re.search(r"\b(\d{1,3})\b",args); limit=min(MAX_PURGE,int(count_match.group(1))) if count_match else MAX_PURGE
        phrase=""
        if mode=="contains":
            phrase=re.sub(r"\s+\d{1,3}\s*$","",args).strip().strip('"“”\' ')
            if not phrase: return await self._reply(message,'Use `purge contains "text" [count]`.')
        target=next(iter(message.mentions),None)
        if mode=="user" and not target: return await self._reply(message,"Use `purge user @user [count]`.")
        emoji=re.compile(r"<a?:\w+:\d+>"); links=re.compile(r"(?:https?://|www\.)\S+",re.I)
        def check(m:discord.Message)->bool:
            if m.pinned or m.id==message.id: return False
            if mode=="user": return bool(target and m.author.id==target.id)
            if mode=="bot": return m.author.bot
            if mode=="contains": return phrase.casefold() in m.content.casefold()
            if mode=="links": return bool(links.search(m.content))
            if mode=="images": return bool(m.embeds or any(a.content_type and a.content_type.startswith("image/") for a in m.attachments))
            if mode=="files": return bool(m.attachments)
            if mode=="embeds": return bool(m.embeds)
            if mode=="emoji": return bool(emoji.search(m.content))
            if mode=="cleanup": return (m.author.bot and "carl" in m.author.name.casefold()) or m.content.startswith("!")
            return True
        try:
            deleted=await message.channel.purge(limit=limit,check=check,bulk=True)
            if mode=="user": text=f"🧹 Deleted **{len(deleted)}** messages from **<@{target.id}>**."
            elif mode=="bot": text=f"🧹 Deleted **{len(deleted)}** bot messages."
            elif mode=="contains": text=f'🧹 Deleted **{len(deleted)}** messages containing "{phrase}".'
            else: text=f"🧹 Deleted **{len(deleted)}** messages."
            await self._reply(message,text,delete_after=3)
        except discord.Forbidden: await self._reply(message,"Discord denied purge; check Manage Messages and Read Message History.")
        except discord.HTTPException: logger.exception("Purge failed"); await self._reply(message,"Purge failed due to a Discord API error.")

    @commands.Cog.listener()
    async def on_guild_channel_create(self,channel:discord.abc.GuildChannel):
        role=channel.guild.get_role(self.mute_roles.get(channel.guild.id,0))
        if role and isinstance(channel,(discord.TextChannel,discord.VoiceChannel,discord.StageChannel)):
            try:
                ow=channel.overwrites_for(role); ow.send_messages=False; ow.add_reactions=False; ow.speak=False
                await channel.set_permissions(role,overwrite=ow,reason="Sync mute role restrictions")
            except discord.HTTPException: logger.exception("Mute role sync failed")

    @commands.Cog.listener()
    async def on_message(self,message:discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author,discord.Member): return
        raw=re.sub(r"^(?:liebe[\s,]+)","",message.content.strip(),flags=re.I).strip()
        if self.bot.user: raw=re.sub(rf"^<@!?{self.bot.user.id}>\s*","",raw).strip()
        if message.channel.id in self.mod_only_channels and not self._is_mod(message.author,message.guild) and (raw.startswith("!") or re.match(r"^(?:"+"|".join(COMMANDS)+r")\b",raw,re.I)):
            try: await message.delete()
            except discord.HTTPException: pass
            await self._reply(message,"Commands are restricted to moderators in this channel."); return
        match=re.match(r"^("+"|".join(COMMANDS)+r")\b\s*(.*)$",raw,re.I)
        if not match: return
        action,args=match.group(1).lower(),match.group(2).strip()
        if action=="help": return
        if not self._is_mod(message.author,message.guild): return await self._reply(message,"Only server moderators can use moderation commands.")
        await self._dispatch(message,action,args)

    async def _dispatch(self,message:discord.Message,action:str,args:str):
        guild,actor=message.guild,message.author
        if action in ("ban","tempban","softban","massban","kick","mute","unmute","warn"):
            if action=="massban":
                targets=self._targets(message,args)
                if not targets or len(targets)>MAX_MASSBAN: return await self._reply(message,f"Mention 1 to {MAX_MASSBAN} members for massban.")
                succeeded=[]
                for target in targets:
                    if not self._hierarchy_ok(message,target): continue
                    if not await self._has(message,"ban_members"): break
                    try:
                        reason=re.sub(r"<@!?\d+>|\b\d{15,22}\b","",args).strip() or "No reason provided"
                        await guild.ban(target,reason=reason[:450]); await self._dm(target,guild,"massban",reason)
                        await self._case(message,"massban",target.id,reason); succeeded.append(str(target))
                    except discord.HTTPException: logger.exception("Massban error for %s",target.id)
                return await self._reply(message,f"🔨 Banned **{len(succeeded)}** users: {', '.join(succeeded)}. | **Reason:** {reason}")
            return await self._punishment(message,action,args)

        if action in ("purge","cleanup"):
            mode="cleanup" if action=="cleanup" else "all"
            rest=args
            if action=="purge":
                mt=re.match(r"(user|bot|contains|links|images|files|embeds|emoji|reactions)\b\s*(.*)$",args,re.I)
                if mt: mode,rest=mt.group(1).lower(),mt.group(2).strip()
            if mode=="reactions":
                if not await self._has(message,"manage_messages"): return await self._reply(message,"You and I both need Manage Messages permission.")
                if not isinstance(message.channel,discord.TextChannel): return await self._reply(message,"Use this in a text channel.")
                nm=re.search(r"\b(\d{1,3})\b",rest); amount=min(MAX_PURGE,int(nm.group(1))) if nm else MAX_PURGE; count=0
                try:
                    async for item in message.channel.history(limit=amount):
                        if not item.pinned and item.reactions: await item.clear_reactions(); count+=1
                    return await self._reply(message,f"🧹 Cleared reactions from **{count}** messages.",delete_after=3)
                except discord.HTTPException: return await self._reply(message,"Could not clear reactions; check permissions.")
            return await self._purge(message,mode,rest)

        if action in ("lockdown","unlockdown"):
            if not await self._has(message,"manage_channels"): return await self._reply(message,"You and I both need Manage Channels permission.")
            locked=action=="lockdown"; server=args.casefold().startswith("server")
            cm=next(iter(message.channel_mentions),None); channel=cm or message.channel
            if server:
                channels=guild.text_channels
                for ch in channels:
                    try: await self._set_lock(ch,locked,f"{action} by {actor}")
                    except discord.HTTPException: logger.exception("Lockdown failed for %s",ch.id)
                return await self._reply(message,"🔒 Server-wide lockdown enabled." if locked else "🔓 Server-wide lockdown lifted.")
            if not isinstance(channel,discord.TextChannel): return await self._reply(message,"Lockdown requires a text channel.")
            try: await self._set_lock(channel,locked,f"{action} by {actor}")
            except discord.HTTPException: return await self._reply(message,"Could not update channel permissions.")
            dur=duration_seconds(args)
            if locked and dur: await self._schedule(guild.id,0,f"unlock:{channel.id}",dur)
            return await self._reply(message,f"{'🔒' if locked else '🔓'} **{channel.mention}** has been {'locked' if locked else 'unlocked'}"+(f" for **{duration_label(dur)}**." if locked and dur else "."))

        if action=="slowmode":
            if not await self._has(message,"manage_channels"): return await self._reply(message,"You and I both need Manage Channels permission.")
            ch=next(iter(message.channel_mentions),None) or message.channel; seconds=duration_seconds(args) or 0
            if not isinstance(ch,discord.TextChannel) or seconds<0 or seconds>21600: return await self._reply(message,"Use `slowmode 30s [#channel]` (0s to 6h).")
            await ch.edit(slowmode_delay=seconds,reason=f"Slowmode set by {actor}")
            return await self._reply(message,f"⏱️ {'Slowmode disabled' if seconds==0 else f'Slowmode set to **{duration_label(seconds)}**'} in **{ch.mention}**.")

        if action=="modlog":
            if not await self._has(message,"manage_guild"): return await self._reply(message,"You and I both need Manage Server permission.")
            ch=next(iter(message.channel_mentions),None)
            if not isinstance(ch,discord.TextChannel): return await self._reply(message,"Use `modlog #channel`.")
            self.modlog_channels[guild.id]=ch.id; await self._config_save(guild.id)
            return await self._reply(message,f"✅ Moderation logs will now be sent to **{ch.mention}**.")

        if action=="modrole":
            if not await self._has(message,"manage_guild"): return await self._reply(message,"You and I both need Manage Server permission.")
            role=next((r for r in guild.roles if f"<@&{r.id}>" in args),None) or discord.utils.find(lambda r:r.name.casefold()==args.strip().casefold(),guild.roles)
            if not role or role.is_default() or role.managed: return await self._reply(message,"Mention or name a valid moderator role.")
            self.mod_roles[guild.id]=role.id; await self._config_save(guild.id)
            return await self._reply(message,f"✅ **{role.name}** is recognized as the moderator role.")

        if action=="muterole":
            if not await self._has(message,"manage_roles") or not await self._has(message,"manage_channels"): return await self._reply(message,"You and I both need Manage Roles and Manage Channels.")
            if args.casefold().startswith("create"):
                name=args.split(maxsplit=1)[1] if len(args.split())>1 else "Muted"
                role=await guild.create_role(name=name[:100],reason=f"Mute role created by {actor}")
            else:
                role=next((r for r in guild.roles if f"<@&{r.id}>" in args),None) or discord.utils.find(lambda r:r.name.casefold()==args.strip().casefold(),guild.roles)
            if not role or role.is_default() or role.managed or not guild.me or role>=guild.me.top_role: return await self._reply(message,"Mention an eligible role, or use `muterole create [name]`.")
            self.mute_roles[guild.id]=role.id; await self._config_save(guild.id)
            for ch in guild.channels:
                if isinstance(ch,(discord.TextChannel,discord.VoiceChannel,discord.StageChannel)):
                    try:
                        ow=ch.overwrites_for(role); ow.send_messages=False; ow.add_reactions=False; ow.speak=False
                        await ch.set_permissions(role,overwrite=ow,reason="Sync mute role permissions")
                    except discord.HTTPException: logger.exception("Mute role sync failed in %s",ch.id)
            return await self._reply(message,f"✅ Mute role set to **<@&{role.id}>** and channel permissions synced.")

        if action in ("role","addrole","removerole"):
            await self._role_action(message,action,args); return
        if action in ("createrole","delrole","rolecolor"):
            await self._role_admin(message,action,args); return

        if action in ("warnings","infractions","removewarn","clearwarn","reason"):
            await self._case_action(message,action,args); return
        if action in ("whois","userinfo","serverinfo"):
            await self._info(message,action,args); return

        if action=="unban":
            if not await self._has(message,"ban_members"): return await self._reply(message,"You and I both need Ban Members permission.")
            uid_match=re.search(r"\b(\d{15,22})\b",args)
            if not uid_match: return await self._reply(message,"Use `unban USER_ID [reason]`.")
            uid=int(uid_match.group(1)); reason=re.sub(r"\b\d{15,22}\b","",args).strip() or "No reason provided"
            try:
                entry=await guild.fetch_ban(discord.Object(id=uid)); await guild.unban(entry.user,reason=reason[:450]); await self._case(message,"unban",uid,reason)
                return await self._reply(message,f"🔓 **{entry.user}** (`{uid}`) has been unbanned. | **Reason:** {reason}")
            except discord.NotFound: return await self._reply(message,"That user is not currently banned.")
            except discord.HTTPException: return await self._reply(message,"Unban failed due to a Discord API error.")

    async def _role_action(self,message:discord.Message,action:str,args:str):
        if not await self._has(message,"manage_roles"): return await self._reply(message,"You and I both need Manage Roles permission.")
        guild=message.guild; sub=re.match(r"^(all|humans|bots)\s+(.+)$",args,re.I) if action=="role" else None
        if sub:
            kind,name=sub.groups(); role=next((r for r in guild.roles if f"<@&{r.id}>" in name),None) or discord.utils.find(lambda r:r.name.casefold()==name.strip().casefold(),guild.roles)
            if not role or role.is_default() or role.managed or not guild.me or role>=guild.me.top_role: return await self._reply(message,"Choose an assignable role below my top role.")
            members=[m for m in guild.members if (kind.lower()=="all" or (kind.lower()=="bots")==m.bot) and role not in m.roles and m.top_role<guild.me.top_role]
            members=members[:MAX_ROLE_BATCH]; await self._reply(message,f"⏳ Adding **{role.name}** to **{len(members)}** members...")
            count=0
            for member in members:
                try: await member.add_roles(role,reason=f"Bulk role assigned by {message.author}"); count+=1
                except discord.HTTPException: await asyncio.sleep(0.5)
                await asyncio.sleep(0.15)
            return await self._reply(message,f"✅ Finished adding **{role.name}** to **{count}** members.")
        target=next(iter(self._targets(message,args)),None)
        if not target: return await self._reply(message,"Mention a member: `role @member @role`.")
        role=next((r for r in guild.roles if f"<@&{r.id}>" in args),None)
        if not role:
            rest=re.sub(r"<@!?\d+>|\b\d{15,22}\b","",args).strip()
            role=discord.utils.find(lambda r:r.name.casefold()==rest.casefold(),guild.roles)
        if not role or role.is_default() or role.managed or not guild.me or role>=guild.me.top_role or (message.author.id!=guild.owner_id and role>=message.author.top_role): return await self._reply(message,"Role must be assignable and below your and my top roles.")
        if not self._hierarchy_ok(message,target): return await self._reply(message,"Target is above your or my role hierarchy.")
        remove=action=="removerole" or (action=="role" and role in target.roles)
        try:
            if remove: await target.remove_roles(role,reason=f"Role change by {message.author}")
            else: await target.add_roles(role,reason=f"Role change by {message.author}")
            return await self._reply(message,f"✅ {'Removed' if remove else 'Added'} **{role.name}** {'from' if remove else 'to'} **<@{target.id}>**.")
        except discord.HTTPException: return await self._reply(message,"Discord denied the role change.")

    async def _role_admin(self,message:discord.Message,action:str,args:str):
        if not await self._has(message,"manage_roles"): return await self._reply(message,"You and I both need Manage Roles permission.")
        guild=message.guild
        if action=="createrole":
            color_match=re.search(r"#([0-9a-fA-F]{6})",args); color=discord.Color(int(color_match.group(1),16)) if color_match else discord.Color.default()
            hoist_match=re.search(r"\bhoist\s*[:=]?\s*(true|false)\b",args,re.I); hoist=bool(hoist_match and hoist_match.group(1).lower()=="true")
            name=re.sub(r"#([0-9a-fA-F]{6})|\bhoist\s*[:=]?\s*(true|false)\b","",args,flags=re.I).strip(' "')
            if not name: return await self._reply(message,"Use `createrole VIP #ff0000 hoist:true`.")
            try:
                role=await guild.create_role(name=name[:100],colour=color,hoist=hoist,reason=f"Created by {message.author}")
                return await self._reply(message,f"✅ Created role **<@&{role.id}>** (Color: `{color_match.group(0) if color_match else '#000000'}`).")
            except discord.HTTPException: return await self._reply(message,"Could not create role; check Manage Roles and role hierarchy.")
        role=next((r for r in guild.roles if f"<@&{r.id}>" in args),None)
        if not role:
            role_name=re.sub(r"#([0-9a-fA-F]{6})","",args).strip()
            role=discord.utils.find(lambda r:r.name.casefold()==role_name.casefold(),guild.roles)
        if not role or role.is_default() or role.managed or not guild.me or role>=guild.me.top_role or (message.author.id!=guild.owner_id and role>=message.author.top_role): return await self._reply(message,"Role not found or above your/bot role.")
        try:
            if action=="delrole":
                name=role.name; await role.delete(reason=f"Deleted by {message.author}"); return await self._reply(message,f"🗑️ Deleted role **{name}**.")
            color_match=re.search(r"#?([0-9a-fA-F]{6})\b",args)
            if not color_match: return await self._reply(message,"Use `rolecolor @role #ff0000`.")
            color=discord.Color(int(color_match.group(1),16)); await role.edit(colour=color,reason=f"Color changed by {message.author}")
            return await self._reply(message,f"🎨 Updated color for **<@&{role.id}>** to `#{color_match.group(1)}`.")
        except discord.HTTPException: return await self._reply(message,"Role update failed due to Discord permissions or API error.")

    async def _case_action(self,message:discord.Message,action:str,args:str):
        guild=message.guild
        if action in ("warnings","infractions","clearwarn"):
            target=next(iter(self._targets(message,args)),None)
            if not target: return await self._reply(message,"Mention a member.")
            if action=="clearwarn":
                async with aiosqlite.connect(DB_PATH) as db: cur=await db.execute("DELETE FROM mod_cases WHERE guild_id=? AND target_id=? AND action='warn'",(guild.id,target.id)); await db.commit()
                return await self._reply(message,f"✅ Cleared all **{cur.rowcount}** warnings for **<@{target.id}>**.")
            async with aiosqlite.connect(DB_PATH) as db: cur=await db.execute("SELECT case_id,reason,created_at,moderator_id FROM mod_cases WHERE guild_id=? AND target_id=? AND action='warn' ORDER BY case_id DESC",(guild.id,target.id)); rows=await cur.fetchall()
            embed=discord.Embed(title=f"Warnings for {target} ({len(rows)} total)",color=discord.Color.orange())
            for cid,reason,created,modid in rows[:20]: embed.add_field(name=f"Case #{cid} · {created[:10]}",value=f"{reason}\nModerator: <@{modid}>",inline=False)
            return await message.reply(embed=embed,mention_author=False,allowed_mentions=discord.AllowedMentions.none())
        case_match=re.search(r"\b(\d+)\b",args)
        if not case_match: return await self._reply(message,"Provide a case ID.")
        case_id=int(case_match.group(1))
        if action=="removewarn":
            async with aiosqlite.connect(DB_PATH) as db: cur=await db.execute("DELETE FROM mod_cases WHERE guild_id=? AND case_id=? AND action='warn'",(guild.id,case_id)); await db.commit()
            return await self._reply(message,f"✅ Removed warning **Case #{case_id}**." if cur.rowcount else "Warning case not found.")
        new_reason=re.sub(r"^\s*\d+\s*","",args).strip()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT reason,log_channel_id,log_message_id FROM mod_cases WHERE guild_id=? AND case_id=?",(guild.id,case_id)) as cur: row=await cur.fetchone()
            if not row: return await self._reply(message,"Case not found.")
            await db.execute("UPDATE mod_cases SET reason=? WHERE guild_id=? AND case_id=?",(new_reason,guild.id,case_id)); await db.commit()
        if row[1] and row[2]:
            ch=guild.get_channel(row[1])
            try:
                logmsg=await ch.fetch_message(row[2]); embed=logmsg.embeds[0]; embed.set_field_at(2,name="Reason",value=new_reason[:1024],inline=False); await logmsg.edit(embed=embed)
            except (discord.HTTPException,IndexError): pass
        return await self._reply(message,f"📝 Updated reason for **Case #{case_id}** to: **{new_reason}**")

    async def _info(self,message:discord.Message,action:str,args:str):
        guild=message.guild
        if action=="serverinfo":
            humans=sum(not m.bot for m in guild.members); bots=sum(m.bot for m in guild.members)
            embed=discord.Embed(title=guild.name,color=discord.Color.blurple())
            if guild.icon: embed.set_thumbnail(url=guild.icon.url)
            embed.add_field(name="Owner",value=str(guild.owner or guild.owner_id)); embed.add_field(name="Members",value=f"{guild.member_count} ({humans} humans / {bots} bots)")
            embed.add_field(name="Channels",value=str(len(guild.channels))); embed.add_field(name="Roles",value=str(len(guild.roles))); embed.add_field(name="Boost level",value=str(guild.premium_tier))
            return await message.reply(embed=embed,mention_author=False)
        target=next(iter(self._targets(message,args)),None)
        if not target: return await self._reply(message,"Mention a user for whois/userinfo.")
        async with aiosqlite.connect(DB_PATH) as db: cur=await db.execute("SELECT COUNT(*) FROM mod_cases WHERE guild_id=? AND target_id=? AND action='warn'",(guild.id,target.id)); warnings=(await cur.fetchone())[0]
        embed=discord.Embed(title=f"User info · {target}",color=discord.Color.blurple())
        embed.set_thumbnail(url=target.display_avatar.url); embed.add_field(name="User ID",value=str(target.id)); embed.add_field(name="Account created",value=discord.utils.format_dt(target.created_at,"R"))
        embed.add_field(name="Joined server",value=discord.utils.format_dt(target.joined_at,"R") if target.joined_at else "Unknown"); embed.add_field(name="Roles",value=", ".join(r.mention for r in target.roles[1:])[:1000] or "None",inline=False); embed.add_field(name="Warnings",value=str(warnings))
        return await message.reply(embed=embed,mention_author=False,allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot):
    await bot.add_cog(ConversationalModerationCog(bot))
