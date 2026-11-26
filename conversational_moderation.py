"""Deterministic conversational moderation and server-management commands.

Messages are parsed only when they begin with an explicit command phrase (optionally
prefixed by `Liebe,` or a bot mention). This avoids asking a generative model to infer
whether a user intended a destructive moderation action.
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
            await db.execute("CREATE TABLE IF NOT EXISTS mod_warnings (case_id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
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
                    collection = self.tempban_tasks if action == "unban" else self.lock_tasks
                    collection.add(task)
                    task.add_done_callback(collection.discard)

    def _normalize_command(self, message: discord.Message) -> str:
        raw = message.content.strip()
        if self.bot.user:
            raw = re.sub(rf"^<@!?{self.bot.user.id}>\s*[,]?\s*", "", raw, flags=re.I).strip()
        raw = re.sub(r"^Liebe\s*[,：:]\s*", "", raw, flags=re.I).strip()
        raw = re.sub(r"^Liebe\s+", "", raw, flags=re.I).strip()
        return raw

    def _is_mod(self, member: discord.Member, guild: discord.Guild) -> bool:
        role_id = self.mod_roles.get(guild.id)
        return member.id in (guild.owner_id, BOT_OWNER_ID) or member.guild_permissions.administrator or member.guild_permissions.manage_guild or bool(role_id and any(r.id == role_id for r in member.roles))

    async def _has(self, message: discord.Message, permission: str) -> bool:
        actor, bot_member = message.author, message.guild.me
        return bool(isinstance(actor, discord.Member) and bot_member and getattr(actor.guild_permissions, permission, False) and getattr(bot_member.guild_permissions, permission, False))

    async def _reply(self, message: discord.Message, text: str, *, delete_after: float | None = None):
        try:
            return await message.reply(text[:1900], mention_author=False, allowed_mentions=discord.AllowedMentions.none(), delete_after=delete_after)
        except discord.HTTPException:
            try:
                return await message.channel.send(text[:1900], allowed_mentions=discord.AllowedMentions.none(), delete_after=delete_after)
            except discord.HTTPException:
                logger.exception("Could not send moderation response")
                return None

    async def _punishment_embed(self, message: discord.Message, target: discord.abc.User, action: str, reason: str, duration: str | None = None, case_id: int | None = None):
        titles = {"warn":"Warning Issued","mute":"Timeout Issued","ban":"Member Banned","tempban":"Temporary Ban Issued","softban":"Member Softbanned","kick":"Member Kicked","unmute":"Member Unmuted","unban":"Member Unbanned","massban":"Members Banned"}
        colors = {"warn":discord.Color.gold(),"mute":discord.Color.orange(),"ban":discord.Color.red(),"tempban":discord.Color.orange(),"softban":discord.Color.orange(),"kick":discord.Color.dark_orange(),"unmute":discord.Color.green(),"unban":discord.Color.green(),"massban":discord.Color.red()}
        embed = discord.Embed(title=titles.get(action,action.title()), color=colors.get(action,discord.Color.orange()), timestamp=datetime.now(timezone.utc))
        if isinstance(target,(discord.Member,discord.User)):
            embed.set_thumbnail(url=target.display_avatar.url)
        warning_count = None
        if action == "warn":
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT COUNT(*) FROM mod_cases WHERE guild_id=? AND target_id=? AND action='warn'",(message.guild.id,target.id)) as cur:
                    row = await cur.fetchone()
                    warning_count = row[0] if row else 0
        embed.add_field(name="User",value=f"{target.mention if hasattr(target,'mention') else target} (`{target.id}`)",inline=False)
        if warning_count is not None:
            embed.add_field(name="Warnings",value=f"{warning_count}/3",inline=True)
        if duration:
            embed.add_field(name="Duration",value=duration,inline=True)
        embed.add_field(name="Reason",value=reason[:1024] or "No reason provided",inline=False)
        if case_id:
            embed.add_field(name="Case",value=f"#{case_id}",inline=True)
        embed.add_field(name="Moderator",value=f"{message.author.mention} (`{message.author.id}`)",inline=False)
        embed.set_footer(text=f"{message.guild.name} Moderation")
        await message.reply(embed=embed,mention_author=False,allowed_mentions=discord.AllowedMentions(users=[target.id] if hasattr(target,"id") else []))

    def _targets(self, message: discord.Message, text: str) -> list[discord.Member]:
        found = {m.id:m for m in message.mentions if message.guild.me and m.id != message.guild.me.id}
        for raw in re.findall(r"(?<!\d)(\d{15,22})(?!\d)",text):
            member = message.guild.get_member(int(raw))
            if member and (not message.guild.me or member.id != message.guild.me.id):
                found[member.id] = member
        return list(found.values())

    async def _resolve_ban_user(self, message: discord.Message, text: str):
        targets = self._targets(message,text)
        if targets:
            return targets[0],targets[0].id
        match = re.search(r"(?<!\d)(\d{15,22})(?!\d)",text)
        if not match:
            return None,None
        uid = int(match.group(1))
        try:
            return await self.bot.fetch_user(uid),uid
        except discord.HTTPException:
            return None,uid

    def _hierarchy_ok(self, message: discord.Message, target: discord.Member) -> bool:
        actor, bot_member = message.author, message.guild.me
        return bool(isinstance(actor,discord.Member) and bot_member and target.id not in (actor.id,message.guild.owner_id) and target.top_role < bot_member.top_role and (actor.id == message.guild.owner_id or target.top_role < actor.top_role))

    async def _config_save(self, guild_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO mod_config (guild_id,mute_role_id,mod_role_id,modlog_channel_id) VALUES (?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET mute_role_id=excluded.mute_role_id,mod_role_id=excluded.mod_role_id,modlog_channel_id=excluded.modlog_channel_id",(guild_id,self.mute_roles.get(guild_id),self.mod_roles.get(guild_id),self.modlog_channels.get(guild_id)))
            await db.commit()

    async def _case(self, message: discord.Message, action: str, target_id: int, reason: str, duration: str | None = None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("INSERT INTO mod_cases (guild_id,action,target_id,moderator_id,reason,duration,created_at) VALUES (?,?,?,?,?,?,?)",(message.guild.id,action,target_id,message.author.id,reason,duration,now))
            await db.commit()
            case_id = cur.lastrowid
        channel = message.guild.get_channel(self.modlog_channels.get(message.guild.id,0))
        if isinstance(channel,discord.TextChannel):
            target = message.guild.get_member(target_id)
            user_text = f"{target} ({target_id})" if target else f"<@{target_id}> ({target_id})"
            embed = discord.Embed(title=f"Moderation Case #{case_id} · {action.title()}",timestamp=datetime.now(timezone.utc),color=discord.Color.orange())
            embed.add_field(name="Target",value=user_text,inline=False)
            embed.add_field(name="Moderator",value=f"{message.author} ({message.author.id})",inline=False)
            embed.add_field(name="Reason",value=reason[:1024],inline=False)
            if duration:
                embed.add_field(name="Duration",value=duration,inline=True)
            try:
                log_message = await channel.send(embed=embed,allowed_mentions=discord.AllowedMentions.none())
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("UPDATE mod_cases SET log_channel_id=?,log_message_id=? WHERE case_id=?",(channel.id,log_message.id,case_id))
                    await db.commit()
            except discord.HTTPException:
                logger.exception("Could not send mod log case %s",case_id)
        return case_id

    async def _schedule_action(self,guild_id:int,user_id:int,action:str,seconds:float):
        await asyncio.sleep(seconds)
        guild=self.bot.get_guild(guild_id)
        try:
            if guild and action=="unban": await guild.unban(discord.Object(id=user_id),reason="Temporary ban expired")
            elif guild and action=="unmute":
                member=guild.get_member(user_id)
                if member:
                    await member.timeout(None,reason="Temporary mute expired")
                    role=guild.get_role(self.mute_roles.get(guild_id,0))
                    if role: await member.remove_roles(role,reason="Temporary mute expired")
            elif guild and action.startswith("unlock:"):
                channel=guild.get_channel(int(action.split(":",1)[1]))
                if isinstance(channel,discord.TextChannel): await self._set_lock(channel,False,"Timed lockdown expired")
        except discord.HTTPException:
            logger.exception("Scheduled moderation action failed")
        finally:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM scheduled_actions WHERE guild_id=? AND user_id=? AND action=?",(guild_id,user_id,action))
                await db.commit()

    async def _schedule(self,guild_id:int,user_id:int,action:str,seconds:int):
        expiry=time.time()+seconds
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO scheduled_actions (guild_id,user_id,action,expires_at) VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,action) DO UPDATE SET expires_at=excluded.expires_at",(guild_id,user_id,action,expiry))
            await db.commit()
        task=asyncio.create_task(self._schedule_action(guild_id,user_id,action,seconds))
        collection=self.tempban_tasks if action=="unban" else self.lock_tasks
        collection.add(task)
        task.add_done_callback(collection.discard)

    async def _dm(self,user:discord.abc.User,guild:discord.Guild,action:str,reason:str,duration:str|None=None):
        text=f"Server: **{guild.name}**\nAction: **{action}**\nReason: {reason}"
        if duration: text+=f"\nDuration: **{duration}**"
        try:
            await user.send(text)
        except (discord.Forbidden,discord.HTTPException):
            pass

    async def _punishment(self,message:discord.Message,action:str,args:str):
        guild,actor=message.guild,message.author
        user,uid=await self._resolve_ban_user(message,args)
        if uid is None or user is None:
            return await self._reply(message,f"Mention a user or provide their ID: `{action} @user [reason]`.")
        target=guild.get_member(uid)
        if target and not self._hierarchy_ok(message,target):
            return await self._reply(message,"I cannot act on that member because of ownership or role hierarchy.")
        if action in ("kick","mute","unmute","warn") and target is None:
            return await self._reply(message,"That action requires the user to be a current server member.")
        perm="kick_members" if action=="kick" else "moderate_members" if action in ("mute","unmute") else "ban_members"
        if action != "warn" and not await self._has(message,perm):
            return await self._reply(message,f"You and I both need {perm.replace('_',' ').title()} permission.")
        days=1 if action=="softban" else 0
        day_match=re.search(r"(?<!\w)([0-7])\s*(?:days?|d)\b",args,re.I)
        if day_match and action in ("ban","softban"):
            days=int(day_match.group(1))
        duration_s=duration_seconds(args) if action in ("tempban","mute") else None
        duration=duration_label(duration_s) if duration_s else None
        reason=re.sub(r"<@!?\d+>|\b\d{15,22}\b","",args)
        reason=DURATION_RE.sub("",reason)
        reason=re.sub(r"(?<!\w)[0-7]\s*(?:days?|d)\b","",reason,flags=re.I).strip(" ,|-") or "No reason provided"
        try:
            if action in ("ban","tempban","softban"):
                if action=="tempban" and (not duration_s or duration_s<60 or duration_s>365*86400):
                    return await self._reply(message,"Use a valid tempban duration from 1 minute to 365 days, e.g. `tempban @user 7d reason`.")
                await guild.ban(user,reason=reason[:450],delete_message_seconds=days*86400)
                if action=="softban": await guild.unban(discord.Object(id=uid),reason=f"Softban by {actor}")
                if action=="tempban": await self._schedule(guild.id,uid,"unban",duration_s)
                await self._dm(user,guild,action,reason,duration)
                case_id=await self._case(message,action,uid,reason,duration)
                await self._punishment_embed(message,user,action,reason,duration,case_id)
            elif action=="kick":
                await target.kick(reason=reason[:450]); await self._dm(target,guild,action,reason)
                case_id=await self._case(message,action,uid,reason)
                await self._punishment_embed(message,target,action,reason,None,case_id)
            elif action=="warn":
                case_id=await self._case(message,"warn",uid,reason); await self._dm(target,guild,"warn",reason)
                await self._punishment_embed(message,target,"warn",reason,None,case_id)
            elif action=="mute":
                if not duration_s or duration_s>28*86400:
                    return await self._reply(message,"Use `mute @user 10m reason` (maximum timeout is 28 days).")
                await target.timeout(discord.utils.utcnow()+timedelta(seconds=duration_s),reason=reason[:450])
                await self._dm(target,guild,action,reason,duration)
                case_id=await self._case(message,action,uid,reason,duration)
                await self._punishment_embed(message,target,action,reason,duration,case_id)
            elif action=="unmute":
                await target.timeout(None,reason=reason[:450])
                role=guild.get_role(self.mute_roles.get(guild.id,0))
                if role and role in target.roles: await target.remove_roles(role,reason=reason[:450])
                case_id=await self._case(message,action,uid,reason)
                await self._punishment_embed(message,target,action,reason,None,case_id)
        except discord.Forbidden:
            await self._reply(message,"Discord denied the action. Check bot permissions and role hierarchy.")
        except discord.HTTPException:
            logger.exception("Punishment %s failed",action)
            await self._reply(message,f"{action.title()} failed due to a Discord API error.")

    @commands.Cog.listener()
    async def on_message(self,message:discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author,discord.Member): return
        raw=self._normalize_command(message)
        match=re.match(r"^("+"|".join(sorted(COMMANDS,key=len,reverse=True))+r")\b\s*(.*)$",raw,re.I)
        if not match: return
        action,args=match.group(1).lower(),match.group(2).strip()
        if action=="help": return
        if not self._is_mod(message.author,message.guild):
            return await self._reply(message,"Only server moderators can use moderation commands.")
        await self._dispatch(message,action,args)

    async def _dispatch(self,message:discord.Message,action:str,args:str):
        guild,actor=message.guild,message.author
        if action in ("ban","tempban","softban","massban","kick","mute","unmute","warn"):
            if action=="massban":
                targets=self._targets(message,args)
                if not targets or len(targets)>MAX_MASSBAN:
                    return await self._reply(message,f"Mention 1 to {MAX_MASSBAN} members for massban.")
                succeeded=[]
                reason=re.sub(r"<@!?\d+>|\b\d{15,22}\b","",args).strip() or "No reason provided"
                for target in targets:
                    if not self._hierarchy_ok(message,target): continue
                    if not await self._has(message,"ban_members"): break
                    try:
                        await guild.ban(target,reason=reason[:450]); await self._dm(target,guild,"massban",reason)
                        await self._case(message,"massban",target.id,reason); succeeded.append(target)
                    except discord.HTTPException:
                        logger.exception("Massban error for %s",target.id)
                await self._reply(message,f"🔨 Banned **{len(succeeded)}** users: {', '.join(t.mention for t in succeeded)}. | **Reason:** {reason}")
                return
            return await self._punishment(message,action,args)
        if action=="unban":
            if not await self._has(message,"ban_members"): return await self._reply(message,"You and I both need Ban Members permission.")
            uid_match=re.search(r"\b(\d{15,22})\b",args)
            if not uid_match: return await self._reply(message,"Use `unban USER_ID [reason]`.")
            uid=int(uid_match.group(1)); reason=re.sub(r"\b\d{15,22}\b","",args).strip() or "No reason provided"
            try:
                entry=await guild.fetch_ban(discord.Object(id=uid)); await guild.unban(entry.user,reason=reason[:450])
                case_id=await self._case(message,"unban",uid,reason)
                await self._punishment_embed(message,entry.user,"unban",reason,None,case_id)
            except discord.NotFound:
                await self._reply(message,"That user is not currently banned.")
            except discord.HTTPException:
                await self._reply(message,"Unban failed due to a Discord API error.")

async def setup(bot:commands.Bot):
    await bot.add_cog(ConversationalModerationCog(bot))
