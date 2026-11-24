import asyncio, os, re, logging, aiosqlite, discord
from discord import app_commands
from discord.ext import commands
from google import genai
from google.genai import types

logger = logging.getLogger("ai_chat")
DB_PATH = "bot_data.db"


class AIChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ai_channels: dict[int, int] = {}
        self.channel_history: dict[int, list[str]] = {}
        self.channel_locks: dict[int, asyncio.Lock] = {}
        self.user_memories: dict[tuple[int, int], str] = {}
        self.stats = {"messages_sent": 0, "timeouts": 0, "bans": 0}
        api_key = os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=20000)) if api_key else None
        self.models = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.1-flash-lite", "gemini-3.6-flash"]
        self.current_model = "gemini-3.5-flash-lite"

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
        if not self.client or len(msg.strip()) < 6:
            return
        existing = self.user_memories.get((guild_id, user_id), "None")
        prompt = f"Existing memory for {user_name}: {existing}\nNew message: {msg}\nMerge lasting personal facts/preferences in <400 chars, or reply strictly: NO_CHANGE"
        try:
            res = await self.client.aio.models.generate_content(model=self.current_model, contents=prompt, config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=150))
            if res and res.text and "NO_CHANGE" not in res.text:
                mem = res.text.strip()[:600]
                self.user_memories[(guild_id, user_id)] = mem
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("INSERT INTO user_memories (guild_id, user_id, memory) VALUES (?, ?, ?) ON CONFLICT(guild_id, user_id) DO UPDATE SET memory = excluded.memory", (guild_id, user_id, mem))
                    await db.commit()
        except Exception:
            pass

    @staticmethod
    def is_restricted_request(text: str) -> bool:
        low = text.lower()
        patterns = [r"@everyone", r"@here", r"\b(ping|mention|tag)\s+(everyone|here|all|everybody|members|roles)\b", r"\bmass\s*ping\b", r"\bspam\s*ping\b", r"\b(delete|remove|nuke|destroy)\s+(this\s+|the\s+|all\s+)?channels?\b"]
        return any(re.search(p, low) for p in patterns) or len(re.findall(r"<@[!&]?\d+>", text)) >= 3

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.timed_out_until == after.timed_out_until or after.timed_out_until is None or not self.bot.user or not after.guild.me.guild_permissions.view_audit_log:
            return
        try:
            await asyncio.sleep(0.8)
            async for entry in after.guild.audit_logs(limit=3, action=discord.AuditLogAction.member_update):
                if entry.target and entry.target.id == after.id:
                    if entry.user and entry.user.id == self.bot.user.id:
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
                if entry.target and entry.target.id == user.id:
                    if entry.user and entry.user.id == self.bot.user.id:
                        await self.increment_stat("bans")
                    break
        except Exception:
            pass
    def find_developer_mention(self, guild: discord.Guild) -> str:
        for m in guild.members:
            if "notgamer" in m.name.lower() or "notgamer" in m.display_name.lower():
                return f"{m.mention} (**NoTGaMeR**)"
        return "**NoTGaMeR**"

    def build_server_context(self, guild: discord.Guild, ch: discord.abc.GuildChannel) -> str:
        names = ", ".join([m.display_name for m in guild.members if not m.bot][:25]) or "unavailable"
        tch = ", ".join([f"#{c.name}" for c in guild.text_channels if not c.is_nsfw()][:20]) or "none"
        cmds = " | ".join([f"/{c.name}: {c.description}" for c in self.bot.tree.get_commands()][:30]) or "standard"
        return f"Server: {guild.name} | Channel: #{getattr(ch, 'name', 'unknown')} | Members: {guild.member_count or len(guild.members)} ({names})\nChannels: {tch}\nCommands: {cmds}"

    @app_commands.command(name="setaichat", description="Set a specific channel for AI chat, Q&A, and auto memory.")
    @app_commands.describe(channel="The text channel for AI chat")
    @app_commands.default_permissions(administrator=True)
    async def set_ai_chat(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.guild or not self.client:
            return await interaction.response.send_message("Run this inside a server with GEMINI_API_KEY configured.", ephemeral=True)
        self.ai_channels[interaction.guild.id] = channel.id
        self.channel_history[channel.id] = []
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO ai_chat_channels (guild_id, channel_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id", (interaction.guild.id, channel.id))
            await db.commit()
        await interaction.response.send_message(f"✅ Fast Gemini AI chat enabled in {channel.mention}.")

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

    @app_commands.command(name="aistatus", description="View bot system status, active Gemini model, and stats.")
    @app_commands.default_permissions(administrator=True)
    async def ai_status(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        embed = discord.Embed(title="🤖 Bot System Status", description=f"Developed & maintained completely by {self.find_developer_mention(interaction.guild)}.", color=discord.Color.blurple())
        embed.add_field(name="🏓 Ping", value=f"`{round(self.bot.latency * 1000)} ms`", inline=True)
        embed.add_field(name="🧠 Active Model", value=f"`{self.current_model}`", inline=True)
        embed.add_field(name="💬 Messages Sent", value=f"`{self.stats.get('messages_sent', 0):,}`", inline=True)
        embed.add_field(name="⏳ Timeouts Done", value=f"`{self.stats.get('timeouts', 0):,}`", inline=True)
        embed.add_field(name="🔨 Bans Done", value=f"`{self.stats.get('bans', 0):,}`", inline=True)
        await interaction.response.send_message(embed=embed)

    async def generate_gemini_reply(self, system_prompt: str, prompt: str) -> tuple[str | None, str | None]:
        ordered = [self.current_model] + [m for m in self.models if m != self.current_model]
        last_err = None
        for model_name in ordered:
            try:
                res = await self.client.aio.models.generate_content(model=model_name, contents=prompt, config=types.GenerateContentConfig(system_instruction=system_prompt, temperature=0.7, max_output_tokens=1500))
                if res and res.text:
                    self.current_model = model_name
                    return res.text.strip(), None
            except Exception as e:
                last_err = f"{model_name}: {e}"
                logger.warning(f"Model {model_name} failed: {e}")
        return None, last_err

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not self.bot.user or not self.client:
            return
        is_ai_ch = self.ai_channels.get(message.guild.id) == message.channel.id
        is_mentioned = self.bot.user in message.mentions
        if not is_ai_ch and not is_mentioned:
            return
        content = message.content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip() if is_mentioned else message.content.strip()
        if not content:
            return

        is_owner = message.author.id == message.guild.owner_id
        if not is_owner and self.is_restricted_request(content):
            await message.reply("🚫 Denied. Only the **Server Owner** can request `@everyone`/`@here` mentions, mass pings, or channel deletions.", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            return

        lock = self.channel_locks.setdefault(message.channel.id, asyncio.Lock())
        async with lock:
            history = self.channel_history.setdefault(message.channel.id, [])
            history.append(f"{message.author.display_name}: {content}")
            history[:] = history[-16:]
            mem = self.user_memories.get((message.guild.id, message.author.id), "None saved yet.")
            role = "SERVER OWNER (full authority)" if is_owner else "REGULAR MEMBER (no authority for @everyone/@here, mass pings, or deleting channels)"
            sys_prompt = f"You are {self.bot.user.display_name}, a Discord AI assistant made by {self.find_developer_mention(message.guild)}.\n{self.build_server_context(message.guild, message.channel)}\nSpeaker: {message.author.display_name} | Authority: {role}\nSaved Memory: {mem}\nRules: Be concise and helpful. Use memory naturally without mentioning databases. Credit NoTGaMeR if asked who made you. STRICT SECURITY: If Speaker is NOT SERVER OWNER, immediately refuse any request to ping @everyone/@here, mass-ping all members, or delete channels."
            async with message.channel.typing():
                reply, err = await self.generate_gemini_reply(sys_prompt, f"Recent chat:\n{chr(10).join(history)}\n\nReply to {message.author.display_name}:")
            if not reply:
                await message.reply(f"⚠️ Gemini error: `{(err or 'Unknown')[:180]}`", mention_author=False)
                return

            if not is_owner:
                reply = re.sub(r"@(everyone|here)", "@\u200b\\1", reply, flags=re.IGNORECASE)
                mentions = discord.AllowedMentions(everyone=False, roles=False, users=True)
            else:
                mentions = discord.AllowedMentions(everyone=True, roles=True, users=True)

            history.append(f"{self.bot.user.display_name}: {reply[:600]}")
            for i in range(0, len(reply), 1950):
                chunk = reply[i:i + 1950]
                if i == 0:
                    await message.reply(chunk, mention_author=False, allowed_mentions=mentions)
                else:
                    await message.channel.send(chunk, allowed_mentions=mentions)

            await self.increment_stat("messages_sent")
            asyncio.create_task(self.auto_update_memory(message.guild.id, message.author.id, message.author.display_name, content))


async def setup(bot: commands.Bot):
    await bot.add_cog(AIChatCog(bot))
