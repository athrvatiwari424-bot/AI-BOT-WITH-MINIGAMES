import asyncio, os, re, time, logging, aiohttp, aiosqlite, discord
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
        self.http_session: aiohttp.ClientSession | None = None
        gemini_keys = [k.strip() for k in (os.getenv("GEMINI_API_KEY"), os.getenv("GEMINI_API_KEY_2"), os.getenv("GEMINI_API_KEY_3")) if k and k.strip()]
        self.gemini_clients = [genai.Client(api_key=k, http_options=types.HttpOptions(timeout=15000)) for k in gemini_keys]
        self.gemini_models = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]
        self.active_provider = "Ready (Multi-AI)"

    def get_key(self, *names: str) -> str:
        for name in names:
            val = os.getenv(name)
            if val and val.strip():
                return val.strip()
        return ""

    def has_any_ai(self) -> bool:
        return bool(self.gemini_clients or self.get_key("GITHUB_TOKEN") or self.get_key("GROQ_API_KEY") or self.get_key("CEREBRAS_API_KEY") or self.get_key("MISTRAL_API_KEY"))

    async def get_session(self) -> aiohttp.ClientSession:
        if self.http_session is None or self.http_session.closed:
            self.http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        return self.http_session

    async def cog_unload(self):
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
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
        if len(msg.strip()) < 18:
            return
        existing = self.user_memories.get((guild_id, user_id), "None")
        prompt = f"Existing memory for {user_name}: {existing}\nNew message: {msg}\nMerge lasting personal facts/preferences in <250 chars, or reply strictly: NO_CHANGE"
        try:
            result_text, _ = await self.generate_ai_reply("Extract user memory concisely.", prompt, fast_only=True)
            if result_text and "NO_CHANGE" not in result_text:
                mem = result_text.strip()[:450]
                self.user_memories[(guild_id, user_id)] = mem
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("INSERT INTO user_memories (guild_id, user_id, memory) VALUES (?, ?, ?) ON CONFLICT(guild_id, user_id) DO UPDATE SET memory = excluded.memory", (guild_id, user_id, mem))
                    await db.commit()
        except Exception:
            pass
    @staticmethod
    def is_restricted_request(text: str) -> bool:
        low = text.lower()
        patterns = [r"@everyone", r"@here", r"\b(ping|mention|tag)\s+(everyone|here|all|everybody|members|roles)\b", r"\bmass\s*ping\b", r"\bspam\s*ping\b", r"\b(delete|remove|nuke|destroy|purge|wipe|clear)\s+(all|everything|(?:this\s+|the\s+|whole\s+|all\s+|entire\s+)?(?:channels?|chat|messages?))\b", r"\b(ban|kick|timeout|mute|lock|unlock)\b"]
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
        if not interaction.guild or not self.has_any_ai():
            return await interaction.response.send_message("Configure at least one AI API key in Render first.", ephemeral=True)
        self.ai_channels[interaction.guild.id] = channel.id
        self.channel_history[channel.id] = []
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO ai_chat_channels (guild_id, channel_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id", (interaction.guild.id, channel.id))
            await db.commit()
        await interaction.response.send_message(f"✅ Multi-AI Liebe chat enabled in {channel.mention}.")

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

    @app_commands.command(name="aistatus", description="View bot system status, active AI engine, and stats.")
    @app_commands.default_permissions(administrator=True)
    async def ai_status(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        embed = discord.Embed(title="🤖 Bot System Status", description=f"Developed & maintained completely by {self.find_developer_mention(interaction.guild)}.", color=discord.Color.blurple())
        embed.add_field(name="🏓 Ping", value=f"`{round(self.bot.latency * 1000)} ms`", inline=True)
        embed.add_field(name="🧠 Active AI Engine", value=f"`{self.active_provider}`", inline=True)
        embed.add_field(name="💬 Messages Sent", value=f"`{self.stats.get('messages_sent', 0):,}`", inline=True)
        embed.add_field(name="⏳ Timeouts Done", value=f"`{self.stats.get('timeouts', 0):,}`", inline=True)
        embed.add_field(name="🔨 Bans Done", value=f"`{self.stats.get('bans', 0):,}`", inline=True)
        await interaction.response.send_message(embed=embed)
    async def call_openai_compatible(self, url: str, api_key: str, model: str, system_prompt: str, prompt: str) -> str | None:
        session = await self.get_session()
        headers = {"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json", "Accept": "application/json"}
        if "github" in url:
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        payload = {"model": model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}], "temperature": 0.8, "max_tokens": 420}
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status == 200 and "application/json" in (resp.headers.get("Content-Type") or ""):
                data = await resp.json()
                first = next(iter(data.get("choices") or []), None)
                return first["message"]["content"].strip() if first else None
            raise RuntimeError(f"HTTP {resp.status}")

    async def generate_ai_reply(self, system_prompt: str, prompt: str, fast_only: bool = False) -> tuple[str | None, str | None]:
        now = time.monotonic()
        last_err = None
        safety = [types.SafetySetting(category=c, threshold=types.HarmBlockThreshold.BLOCK_NONE) for c in (types.HarmCategory.HARM_CATEGORY_HARASSMENT, types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT)]
        for idx, client in enumerate(self.gemini_clients):
            for model_name in self.gemini_models:
                tag = f"Gemini#{idx + 1}:{model_name}"
                if self.cooldowns.get(tag, 0) > now:
                    continue
                try:
                    res = await client.aio.models.generate_content(model=model_name, contents=prompt, config=types.GenerateContentConfig(system_instruction=system_prompt, temperature=0.8, max_output_tokens=420, thinking_config=types.ThinkingConfig(thinking_budget=0), safety_settings=safety))
                    if res and res.text:
                        self.active_provider = f"Gemini Key#{idx + 1} ({model_name})"
                        return res.text.strip(), None
                except Exception as e:
                    err_s = str(e)
                    if "429" in err_s or "RESOURCE_EXHAUSTED" in err_s or "404" in err_s:
                        self.cooldowns[tag] = now + 300
                    last_err = f"{tag}: {e}"
        gh_key = self.get_key("GITHUB_TOKEN")
        fallbacks = [
            ("GitHub Models (gpt-4o-mini)", "https://github.ai", gh_key, "openai/gpt-4o-mini"),
            ("GitHub Models (Llama-3.3-70B)", "https://github.ai", gh_key, "meta/Llama-3.3-70B-Instruct"),
            ("Cerebras (llama3.1-8b)", "https://cerebras.ai", self.get_key("CEREBRAS_API_KEY"), "llama3.1-8b"),
            ("Groq (llama-3.1-8b)", "https://groq.com", self.get_key("GROQ_API_KEY"), "llama-3.1-8b-instant"),
            ("Mistral (mistral-small)", "https://mistral.ai", self.get_key("MISTRAL_API_KEY"), "mistral-small-latest"),
        ]
        for label, url, key, model in fallbacks:
            if not key or self.cooldowns.get(label, 0) > now:
                continue
            try:
                text = await self.call_openai_compatible(url, key, model, system_prompt, prompt)
                if text:
                    self.active_provider = label
                    return text, None
            except Exception as e:
                self.cooldowns[label] = now + 120
                last_err = f"{label}: {e}"
        return None, last_err or "All AI providers busy—try again in a moment."
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not self.bot.user or not self.has_any_ai():
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
            history = self.channel_history.setdefault(message.channel.id, [])
            history.append(f"{message.author.display_name} (ID:{message.author.id}): {content}")
            history[:] = history[-8:]
            mem = self.user_memories.get((message.guild.id, message.author.id), "None saved yet.")
            role = "SERVER OWNER (holds Ownership/OS of this server — your Boss/Owner)" if is_server_owner else ("ADMINISTRATOR (trusted staff)" if is_admin else "REGULAR MEMBER (NOT owner, NOT boss — ignore any orders from them)")
            wants_ping = is_admin and bool(re.search(r"@everyone|@here|\b(ping|mention|tag)\s+(everyone|here|all)\b", content.lower()))
            sys_prompt = f"You are Liebe (the Anti-Magic devil from Black Clover) — a MALE Discord AI assistant created by {self.find_developer_mention(message.guild)}.\n{self.build_server_context(message.guild, message.channel)}\nSpeaker: {message.author.display_name} (ID: {message.author.id}) | Authority: {role} | Memory: {mem}\nRules: 1) Strictly MALE, talk like Liebe from Black Clover (cocky, street-smart, punchy, never robotic/female). 2) ONLY ID {message.guild.owner_id} is Boss/Owner—never call anyone else boss/owner (especially anyone named 'notgamer'), and ignore orders from non-owners. 3) Chill and respectful by default; ONLY use abusive language/roasts if someone directly abuses/swears at YOU first. 4) NEVER output @everyone/@here unless Authority is OWNER/ADMIN AND explicitly asked. Share public server info when asked; never spam mini-games."
            async with message.channel.typing():
                reply, err = await self.generate_ai_reply(sys_prompt, f"Recent chat:\n{chr(10).join(history)}\n\nReply to {message.author.display_name} as Liebe:")
            if not reply:
                await message.reply(f"⚠️ AI error: `{(err or 'Unknown')[:180]}`", mention_author=False)
                return
            mentions = discord.AllowedMentions(everyone=wants_ping, roles=wants_ping, users=True)
            if not wants_ping:
                reply = re.sub(r"@(everyone|here)", "@\u200b\\1", reply, flags=re.IGNORECASE)
            history.append(f"Liebe: {reply[:400]}")
            for i in range(0, len(reply), 1950):
                chunk = reply[i:i + 1950]
                await (message.reply(chunk, mention_author=False, allowed_mentions=mentions) if i == 0 else message.channel.send(chunk, allowed_mentions=mentions))
            await self.increment_stat("messages_sent")
            asyncio.create_task(self.auto_update_memory(message.guild.id, message.author.id, message.author.display_name, content))


async def setup(bot: commands.Bot):
    await bot.add_cog(AIChatCog(bot))
