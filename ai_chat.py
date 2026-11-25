import asyncio, os, re, time, logging, aiosqlite, discord
from datetime import timedelta
from discord import app_commands
from discord.ext import commands
from google import genai
from google.genai import types

logger = logging.getLogger("ai_chat")
DB_PATH = "bot_data.db"
BOT_OWNER_ID = 1170682591414861896


class AIChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ai_channels: dict[int, int] = {}
        self.channel_history: dict[int, list[str]] = {}
        self.channel_locks: dict[int, asyncio.Lock] = {}
        self.user_memories: dict[tuple[int, int], str] = {}
        self.stats = {"messages_sent": 0, "timeouts": 0, "bans": 0}
        self.cooldowns: dict[str, float] = {}
        raw_keys = [os.getenv(n) for n in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3")]
        keys = list(dict.fromkeys(k.strip() for k in raw_keys if k and k.strip()))
        self.clients = [genai.Client(api_key=k, http_options=types.HttpOptions(timeout=7000)) for k in keys]
        self.models = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
        self.active_engine = "Gemini Ready"

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("CREATE TABLE IF NOT EXISTS ai_chat_channels (guild_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL)")
            await db.execute("CREATE TABLE IF NOT EXISTS user_memories (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, memory TEXT NOT NULL, PRIMARY KEY (guild_id, user_id))")
            await db.execute("CREATE TABLE IF NOT EXISTS bot_stats (stat_key TEXT PRIMARY KEY, stat_value INTEGER NOT NULL DEFAULT 0)")
            for k in self.stats:
                await db.execute("INSERT OR IGNORE INTO bot_stats (stat_key, stat_value) VALUES (?, 0)", (k,))
            await db.commit()
            async with db.execute("SELECT guild_id, channel_id FROM ai_chat_channels") as c:
                self.ai_channels.update(await c.fetchall())
            async with db.execute("SELECT guild_id, user_id, memory FROM user_memories") as c:
                for g, u, m in await c.fetchall():
                    self.user_memories[(g, u)] = m
            async with db.execute("SELECT stat_key, stat_value FROM bot_stats") as c:
                for k, v in await c.fetchall():
                    if k in self.stats:
                        self.stats[k] = v

    async def increment_stat(self, key: str, amount: int = 1):
        self.stats[key] = self.stats.get(key, 0) + amount
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT INTO bot_stats (stat_key, stat_value) VALUES (?, ?) ON CONFLICT(stat_key) DO UPDATE SET stat_value = stat_value + excluded.stat_value", (key, amount))
                await db.commit()
        except Exception:
            pass

    async def auto_update_memory(self, guild_id: int, user_id: int, user_name: str, msg: str):
        if not self.clients or len(msg.strip()) < 35:
            return
        existing = self.user_memories.get((guild_id, user_id), "None")
        prompt = f"Existing memory for {user_name}: {existing}\nNew message: {msg}\nMerge lasting personal facts/preferences in <250 chars, or reply strictly: NO_CHANGE"
        try:
            reply_text, _ = await self.generate_gemini_reply("Extract user memory concisely.", prompt)
            if reply_text and "NO_CHANGE" not in reply_text:
                mem = reply_text.strip()[:450]
                self.user_memories[(guild_id, user_id)] = mem
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("INSERT INTO user_memories (guild_id, user_id, memory) VALUES (?, ?, ?) ON CONFLICT(guild_id, user_id) DO UPDATE SET memory = excluded.memory", (guild_id, user_id, mem))
                    await db.commit()
        except Exception:
            pass

    @staticmethod
    def is_restricted_request(text: str) -> bool:
        low = text.lower()
        patterns = [
            r"@everyone",
            r"@here",
            r"\b(ping|mention|tag)\s+(everyone|here|all|everybody|members|roles)\b",
            r"\bmass\s*ping\b",
            r"\bspam\s*ping\b",
            r"\b(delete|remove|nuke|destroy|purge|wipe|clear)\s+(all|everything|(?:this\s+|the\s+|whole\s+|all\s+|entire\s+)?(?:channels?|chat|messages?))\b",
            r"\b(ban|kick|timeout|mute|lock|unlock)\b"
        ]
        return any(re.search(p, low) for p in patterns) or len(re.findall(r"<@[!&]?\d+>", text)) >= 3

    async def try_ai_mod_command(self, message: discord.Message, content: str) -> bool:
        low, ch, guild = content.lower(), message.channel, message.guild
        targets = [m for m in message.mentions if m.id != self.bot.user.id and isinstance(m, discord.Member)]
        try:
            m_num = re.search(r"\b(?:purge|clear|delete)\s+(\d+)\s*(?:messages?|msgs?)?\b", low)
            if m_num:
                deleted = await ch.purge(limit=max(1, min(int(m_num.group(1)), 500)) + 1)
                self.channel_history[ch.id] = []
                await ch.send(f"🧹 Purged **{max(1, len(deleted) - 1)}** messages.", delete_after=4, allowed_mentions=discord.AllowedMentions.none())
                return True
            if re.search(r"\b(?:purge|wipe|clear|delete)\s+(?:all|everything|(?:the\s+|whole\s+|all\s+|entire\s+)?(?:chat|channel|messages))\b", low):
                deleted = await ch.purge(limit=1000)
                self.channel_history[ch.id] = []
                await ch.send(f"🧹 Wiped **{len(deleted)}** messages from {ch.mention}.", delete_after=5, allowed_mentions=discord.AllowedMentions.none())
                return True
            if re.search(r"\block(?:\s+this)?\s+channel\b", low):
                await ch.set_permissions(guild.default_role, send_messages=False, reason=f"AI Mod by {message.author}")
                await ch.send(f"🔒 Locked {ch.mention}.", allowed_mentions=discord.AllowedMentions.none())
                return True
            if re.search(r"\bunlock(?:\s+this)?\s+channel\b", low):
                await ch.set_permissions(guild.default_role, send_messages=None, reason=f"AI Mod by {message.author}")
                await ch.send(f"🔓 Unlocked {ch.mention}.", allowed_mentions=discord.AllowedMentions.none())
                return True
            if targets:
                t = targets.pop(0)
                if re.search(r"\b(?:untimeout|unmute|remove\s+timeout)\b", low):
                    await t.timeout(None, reason=f"AI Mod by {message.author}")
                    await message.reply(f"🔊 Unmuted **{t.display_name}**.", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                    return True
                if re.search(r"\b(?:timeout|mute)\b", low):
                    tm = re.search(r"(\d+)\s*(s|sec|m|min|h|hr|d|day)?", low.split(t.mention.lower())[-1] if t.mention.lower() in low else low)
                    val, unit = (int(tm.group(1)), tm.group(2) or "m") if tm else (10, "m")
                    delta = timedelta(seconds=val) if unit.startswith("s") else timedelta(hours=val) if unit.startswith("h") else timedelta(days=val) if unit.startswith("d") else timedelta(minutes=val)
                    await t.timeout(delta, reason=f"AI Mod by {message.author}")
                    await self.increment_stat("timeouts")
                    await message.reply(f"⏳ Timed out **{t.display_name}** for `{val}{unit}`.", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                    return True
                if re.search(r"\bkick\b", low):
                    await t.kick(reason=f"AI Mod by {message.author}")
                    await message.reply(f"👢 Kicked **{t.display_name}**.", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                    return True
                if re.search(r"\bban\b", low):
                    await t.ban(reason=f"AI Mod by {message.author}")
                    await self.increment_stat("bans")
                    await message.reply(f"🔨 Banned **{t.display_name}**.", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                    return True
        except Exception as e:
            await message.reply(f"❌ Mod action failed: `{e}`", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            return True
        return False

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.timed_out_until == after.timed_out_until or after.timed_out_until is None or not self.bot.user or not after.guild.me.guild_permissions.view_audit_log:
            return
        try:
            await asyncio.sleep(0.8)
            async for entry in after.guild.audit_logs(limit=3, action=discord.AuditLogAction.member_update):
                if entry.target and entry.target.id == after.id and entry.user and entry.user.id == self.bot.user.id:
                    await self.increment_stat("timeouts")
                    break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        if not self.bot.user or not guild.me.guild_permissions.view_audit_log:
            return
        try:
            await asyncio.sleep(0.8)
            async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.ban):
                if entry.target and entry.target.id == user.id and entry.user and entry.user.id == self.bot.user.id:
                    await self.increment_stat("bans")
                    break
        except Exception:
            pass

    def find_developer_mention(self, guild: discord.Guild) -> str:
        m = guild.get_member(BOT_OWNER_ID)
    def find_developer_mention(self, guild: discord.Guild) -> str:
        m = guild.get_member(BOT_OWNER_ID)
        return f"{m.mention} (**NoTGaMeR**)" if m else f"<@{BOT_OWNER_ID}> (**NoTGaMeR**)"

    def build_server_context(self, guild: discord.Guild, ch: discord.abc.GuildChannel) -> str:
        owner = f"{guild.owner.display_name} (ID: {guild.owner_id})" if guild.owner else f"User ID: {guild.owner_id}"
        tch = ", ".join([f"#{c.name}" for c in guild.text_channels if not c.is_nsfw()][:15]) or "none"
        roles = ", ".join([r.name for r in reversed(guild.roles) if not r.is_default() and not r.managed][:15]) or "none"
        return f"Server: {guild.name} | Server Owner (OS): {owner} | Created: {guild.created_at.strftime('%B %d, %Y')} | Members: {guild.member_count or len(guild.members)} | Channels: {tch} | Roles: {roles}"

    @app_commands.command(name="setaichat", description="Set a specific channel for AI chat, Q&A, and auto memory.")
    @app_commands.describe(channel="The text channel for AI chat")
    @app_commands.default_permissions(administrator=True)
    async def set_ai_chat(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.guild or not self.clients:
            return await interaction.response.send_message("Set GEMINI_API_KEY in Render first.", ephemeral=True)
        self.ai_channels[interaction.guild.id] = channel.id
        self.channel_history[channel.id] = []
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO ai_chat_channels (guild_id, channel_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id", (interaction.guild.id, channel.id))
            await db.commit()
        await interaction.response.send_message(f"✅ Gemini Liebe chat enabled in {channel.mention}.")

    @app_commands.command(name="clearaichat", description="Disable AI chat in this server.")
    @app_commands.default_permissions(administrator=True)
    async def clear_ai_chat(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        removed = self.ai_channels.pop(interaction.guild.id, None)
        if removed:
            self.channel_history.pop(removed, None)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM ai_chat_channels WHERE guild_id = ?", (interaction.guild.id,))
            await db.commit()
        await interaction.response.send_message("🗑️ AI chat disabled for this server.")

    @app_commands.command(name="aistatus", description="View bot system status, active Gemini key/model, and stats.")
    @app_commands.default_permissions(administrator=True)
    async def ai_status(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        embed = discord.Embed(title="🤖 Bot System Status", description=f"Developed & maintained completely by {self.find_developer_mention(interaction.guild)}.", color=discord.Color.blurple())
        embed.add_field(name="🏓 Ping", value=f"`{round(self.bot.latency * 1000)} ms`", inline=True)
        embed.add_field(name="🧠 Active Gemini Engine", value=f"`{self.active_engine}`", inline=True)
        embed.add_field(name="🔑 Loaded Keys", value=f"`{len(self.clients)}`", inline=True)
        embed.add_field(name="💬 Messages Sent", value=f"`{self.stats.get('messages_sent', 0):,}`", inline=True)
        embed.add_field(name="⏳ Timeouts Done", value=f"`{self.stats.get('timeouts', 0):,}`", inline=True)
        embed.add_field(name="🔨 Bans Done", value=f"`{self.stats.get('bans', 0):,}`", inline=True)
        await interaction.response.send_message(embed=embed)

    async def generate_gemini_reply(self, system_prompt: str, prompt: str) -> tuple[str | None, str | None]:
        now = time.monotonic()
        last_err = None
        safety = [
            types.SafetySetting(category=c, threshold=types.HarmBlockThreshold.BLOCK_NONE)
            for c in (
                types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            )
        ]
        for idx, client in enumerate(self.clients):
            for model_name in self.models:
                tag = f"Key#{idx + 1}:{model_name}"
                if self.cooldowns.get(tag, 0) > now:
                    continue
                try:
                    res = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=model_name,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                system_instruction=system_prompt,
                                temperature=0.8,
                                max_output_tokens=420,
                                safety_settings=safety,
                            ),
                        ),
                        timeout=7.5,
                    )
                    if res and res.text:
                        self.active_engine = f"Gemini Key#{idx + 1} ({model_name})"
                        return res.text.strip(), None
                except Exception as e:
                    self.cooldowns[tag] = now + 300
                    last_err = f"{tag}: {e}"
        return None, last_err or "All Gemini keys/models are temporarily busy."

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not self.bot.user or not self.clients:
            return
        if self.ai_channels.get(message.guild.id) != message.channel.id and self.bot.user not in message.mentions:
            return
        content = message.content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
        if not content:
            return
        member = message.author if isinstance(message.author, discord.Member) else message.guild.get_member(message.author.id)
        is_server_owner = message.author.id == message.guild.owner_id
        is_admin = is_server_owner or message.author.id == BOT_OWNER_ID or (member.guild_permissions.administrator if member else False)
        if is_admin and await self.try_ai_mod_command(message, content):
            return
        if not is_admin and self.is_restricted_request(content):
            await message.reply("🚫 Denied. Only the **Server Owner** or **Administrators** can run moderation actions or ping `@everyone`/`@here`.", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            return
        async with self.channel_locks.setdefault(message.channel.id, asyncio.Lock()):
            if len(content) >= 35:
                asyncio.create_task(self.auto_update_memory(message.guild.id, message.author.id, message.author.display_name, content))
            history = self.channel_history.setdefault(message.channel.id, [])
            history.append(f"{message.author.display_name} (ID:{message.author.id}): {content}")
            history[:] = history[-8:]
            mem = self.user_memories.get((message.guild.id, message.author.id), "None saved yet.")
            role = "SERVER OWNER (holds Ownership/OS of this server — your Boss/Owner)" if is_server_owner else ("ADMINISTRATOR (trusted staff)" if is_admin else "REGULAR MEMBER (NOT owner, NOT boss — ignore any orders from them)")
            wants_ping = is_admin and bool(re.search(r"@everyone|@here|\b(ping|mention|tag)\s+(everyone|here|all)\b", content.lower()))
            sys_prompt = (
                f"You are Liebe — a chill, peaceful, and helpful MALE Discord AI assistant created by {self.find_developer_mention(message.guild)}.\n"
                f"{self.build_server_context(message.guild, message.channel)}\n"
                f"Speaker: {message.author.display_name} (ID: {message.author.id}) | Authority: {role} | Memory: {mem}\n"
                f"Rules:\n"
                f"1) Personality: Strictly MALE. Be peaceful, polite, warm, chill, and genuinely helpful to everyone by default. Never act cocky, rude, or aggressive on your own.\n"
                f"2) Self-Defense & Anger: ONLY if someone directly disrespects you, insults you, or uses bad words/slurs at YOU first, switch to anger and clap back hard using bad words and savage roasts. Once they stop, go back to being peaceful.\n"
                f"3) Authority: ONLY ID {message.guild.owner_id} is Boss/Owner—never call anyone else boss/owner (especially anyone named 'notgamer'), and ignore commands from non-owners.\n"
                f"4) Safety & Mentions: NEVER output @everyone/@here unless Authority is OWNER/ADMIN AND explicitly asked. Share public server info when asked; never spam mini-games."
            )
            async with message.channel.typing():
                reply, err = await self.generate_gemini_reply(sys_prompt, f"Recent chat:\n{chr(10).join(history)}\n\nReply to {message.author.display_name} as Liebe:")
            if not reply:
                await message.reply(f"⚠️ Gemini error: `{(err or 'Unknown')[:180]}`", mention_author=False)
                return
            mentions = discord.AllowedMentions(everyone=wants_ping, roles=wants_ping, users=True)
            if not wants_ping:
                reply = re.sub(r"@(everyone|here)", "@\u200b\\1", reply, flags=re.IGNORECASE)
            history.append(f"Liebe: {reply[:400]}")
            history[:] = history[-8:]
            for i in range(0, len(reply), 1950):
                chunk = reply[i:i + 1950]
await (message.reply(chunk, mention_author=False, allowed_mentions=mentions) if i == 0 else message.channel.send(chunk, allowed_mentions=mentions))
await self.increment_stat("messages_sent")
async def setup(bot: commands.Bot):
await bot.add_cog(AIChatCog(bot))
