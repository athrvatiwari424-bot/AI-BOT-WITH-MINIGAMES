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
        self.memory_cooldowns: dict[tuple[int, int], float] = {}
        raw_keys = [os.getenv(n) for n in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3")]
        keys = list(dict.fromkeys(k.strip() for k in raw_keys if k and k.strip()))
        # The GenAI client rejects manually configured deadlines shorter than 10 seconds.
        self.clients = [genai.Client(api_key=k, http_options=types.HttpOptions(timeout=15000)) for k in keys]
        self.models = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]
        self.active_engine = "Gemini Ready"

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("CREATE TABLE IF NOT EXISTS ai_chat_channels (guild_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL)")
            await db.execute("CREATE TABLE IF NOT EXISTS user_memories (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, memory TEXT NOT NULL, PRIMARY KEY (guild_id, user_id))")
            await db.execute("CREATE TABLE IF NOT EXISTS bot_stats (stat_key TEXT PRIMARY KEY, stat_value INTEGER NOT NULL DEFAULT 0)")
            for key in self.stats:
                await db.execute("INSERT OR IGNORE INTO bot_stats (stat_key, stat_value) VALUES (?, 0)", (key,))
            await db.commit()
            async with db.execute("SELECT guild_id, channel_id FROM ai_chat_channels") as cursor:
                self.ai_channels.update(await cursor.fetchall())
            async with db.execute("SELECT guild_id, user_id, memory FROM user_memories") as cursor:
                for guild_id, user_id, memory in await cursor.fetchall():
                    self.user_memories[(guild_id, user_id)] = memory
            async with db.execute("SELECT stat_key, stat_value FROM bot_stats") as cursor:
                for key, value in await cursor.fetchall():
                    if key in self.stats:
                        self.stats[key] = value

    async def increment_stat(self, key: str, amount: int = 1):
        self.stats[key] = self.stats.get(key, 0) + amount
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT INTO bot_stats (stat_key, stat_value) VALUES (?, ?) ON CONFLICT(stat_key) DO UPDATE SET stat_value = stat_value + excluded.stat_value", (key, amount))
                await db.commit()
        except Exception:
            logger.exception("Could not persist bot stat %s", key)

    async def auto_update_memory(self, guild_id: int, user_id: int, user_name: str, msg: str):
        if not self.clients or len(msg.strip()) < 35:
            return
        memory_key = (guild_id, user_id)
        now = time.monotonic()
        if self.memory_cooldowns.get(memory_key, 0) > now:
            return
        self.memory_cooldowns[memory_key] = now + 600
        existing = self.user_memories.get(memory_key, "None")
        prompt = f"Existing memory for {user_name}: {existing}\nNew message: {msg}\nMerge lasting personal facts/preferences in <250 chars, or reply strictly: NO_CHANGE"
        try:
            text, _ = await self.generate_gemini_reply("Extract user memory concisely.", prompt)
            if text:
                memory = text.strip()
                if memory.upper() != "NO_CHANGE" and len(memory) <= 450:
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute("INSERT INTO user_memories (guild_id, user_id, memory) VALUES (?, ?, ?) ON CONFLICT(guild_id, user_id) DO UPDATE SET memory = excluded.memory", (guild_id, user_id, memory))
                        await db.commit()
                    self.user_memories[memory_key] = memory
        except Exception:
            logger.exception("Failed to update memory for user %s in guild %s", user_id, guild_id)

    @staticmethod
    def is_restricted_request(text: str) -> bool:
        low = text.lower()
        patterns = [
            r"@everyone", r"@here",
            r"\b(ping|mention|tag)\s+(everyone|here|all|everybody|members|roles)\b",
            r"\bmass\s*ping\b", r"\bspam\s*ping\b",
            r"\b(delete|remove|nuke|destroy|purge|wipe|clear)\s+(all|everything|(?:this\s+|the\s+|whole\s+|all\s+|entire\s+)?(?:channels?|chat|messages?))\b",
            r"\b(ban|kick|timeout|mute|lock|unlock)\b",
        ]
        return any(re.search(pattern, low) for pattern in patterns) or len(re.findall(r"<@[!&]?\d+>", text)) >= 3

    async def try_ai_mod_command(self, message: discord.Message, content: str) -> bool:
        low, channel, guild = content.lower(), message.channel, message.guild
        targets = [m for m in message.mentions if self.bot.user and m.id != self.bot.user.id and isinstance(m, discord.Member)]
        try:
            count_match = re.search(r"\b(?:purge|clear|delete)\s+(\d+)\s*(?:messages?|msgs?)?\b", low)
            if count_match:
                deleted = await channel.purge(limit=max(1, min(int(count_match.group(1)), 500)) + 1)
                self.channel_history[channel.id] = []
                await channel.send(f"🧹 Purged **{max(1, len(deleted) - 1)}** messages.", delete_after=4, allowed_mentions=discord.AllowedMentions.none())
                return True
            if re.search(r"\b(?:purge|wipe|clear|delete)\s+(?:all|everything|(?:the\s+|whole\s+|all\s+|entire\s+)?(?:chat|channel|messages))\b", low):
                deleted = await channel.purge(limit=1000)
                self.channel_history[channel.id] = []
                await channel.send(f"🧹 Wiped **{len(deleted)}** messages from {channel.mention}.", delete_after=5, allowed_mentions=discord.AllowedMentions.none())
                return True
            if re.search(r"\block(?:\s+this)?\s+channel\b", low):
                await channel.set_permissions(guild.default_role, send_messages=False, reason=f"AI Mod by {message.author}")
                await channel.send(f"🔒 Locked {channel.mention}.", allowed_mentions=discord.AllowedMentions.none())
                return True
            if re.search(r"\bunlock(?:\s+this)?\s+channel\b", low):
                await channel.set_permissions(guild.default_role, send_messages=None, reason=f"AI Mod by {message.author}")
                await channel.send(f"🔓 Unlocked {channel.mention}.", allowed_mentions=discord.AllowedMentions.none())
                return True
            if targets:
                target = targets[0]
                if re.search(r"\b(?:untimeout|unmute|remove\s+timeout)\b", low):
                    await target.timeout(None, reason=f"AI Mod by {message.author}")
                    await message.reply(f"🔊 Unmuted **{target.display_name}**.", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                    return True
                if re.search(r"\b(?:timeout|mute)\b", low):
                    match = re.search(r"(\d+)\s*(s|sec|m|min|h|hr|d|day)?", low)
                    value, unit = (int(match.group(1)), match.group(2) or "m") if match else (10, "m")
                    duration = timedelta(seconds=value) if unit.startswith("s") else timedelta(hours=value) if unit.startswith("h") else timedelta(days=value) if unit.startswith("d") else timedelta(minutes=value)
                    await target.timeout(duration, reason=f"AI Mod by {message.author}")
                    await message.reply(f"⏳ Timed out **{target.display_name}** for `{value}{unit}`.", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                    return True
                if re.search(r"\bkick\b", low):
                    await target.kick(reason=f"AI Mod by {message.author}")
                    await message.reply(f"👢 Kicked **{target.display_name}**.", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                    return True
                if re.search(r"\bban\b", low):
                    await target.ban(reason=f"AI Mod by {message.author}")
                    await message.reply(f"🔨 Banned **{target.display_name}**.", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                    return True
        except discord.HTTPException as error:
            try:
                await message.channel.send(f"❌ Mod action failed: `{error}`", allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                logger.exception("Could not report moderation error")
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
            logger.exception("Could not inspect timeout audit log")

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
            logger.exception("Could not inspect ban audit log")

    def find_developer_mention(self, guild: discord.Guild) -> str:
        member = guild.get_member(BOT_OWNER_ID)
        return f"{member.mention} (**NoTGaMeR**)" if member else f"<@{BOT_OWNER_ID}> (**NoTGaMeR**)"

    def build_server_context(self, guild: discord.Guild, channel: discord.abc.GuildChannel) -> str:
        owner = f"{guild.owner.display_name} (ID: {guild.owner_id})" if guild.owner else f"User ID: {guild.owner_id}"
        text_channels = ", ".join(f"#{item.name}" for item in [c for c in guild.text_channels if not c.is_nsfw()][:15]) or "none"
        roles = ", ".join(role.name for role in [r for r in reversed(guild.roles) if not r.is_default() and not r.managed][:15]) or "none"
        return f"Server: {guild.name} | Server Owner: {owner} | Created: {guild.created_at.strftime('%B %d, %Y')} | Members: {guild.member_count or len(guild.members)} | Channels: {text_channels} | Roles: {roles} | Current channel: #{channel.name}"

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
        embed.add_field(name="💬 Messages Sent", value=f"`{self.stats['messages_sent']:,}`", inline=True)
        embed.add_field(name="⏳ Timeouts Done", value=f"`{self.stats['timeouts']:,}`", inline=True)
        embed.add_field(name="🔨 Bans Done", value=f"`{self.stats['bans']:,}`", inline=True)
        await interaction.response.send_message(embed=embed)

    async def generate_gemini_reply(self, system_prompt: str, prompt: str) -> tuple[str | None, str | None]:
        last_error = None
        safety = [types.SafetySetting(category=category, threshold=types.HarmBlockThreshold.BLOCK_NONE) for category in (types.HarmCategory.HARM_CATEGORY_HARASSMENT, types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT)]
        for index, client in enumerate(self.clients):
            for model_name in self.models:
                tag = f"Key#{index + 1}:{model_name}"
                if self.cooldowns.get(tag, 0) > time.monotonic():
                    continue
                try:
                    response = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=model_name,
                            contents=prompt,
                            config=types.GenerateContentConfig(system_instruction=system_prompt, temperature=0.8, max_output_tokens=420, safety_settings=safety),
                        ),
                        timeout=15.0,
                    )
                    if response and response.text and response.text.strip():
                        self.active_engine = f"Gemini Key#{index + 1} ({model_name})"
                        return response.text.strip(), None
                except Exception as error:
                    error_text = str(error)
                    self.cooldowns[tag] = time.monotonic() + (3600 if "404" in error_text else 60 if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text else 300)
                    last_error = f"{tag}: {error}"
        return None, last_error or "All Gemini keys/models are temporarily busy."

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not self.bot.user or not self.clients:
            return
        # Compare user IDs rather than relying on Discord.py object identity; regex
        # also covers raw mention markup when the mentions cache is unavailable.
        mention_pattern = rf"<@!?{self.bot.user.id}>"
        bot_mentioned = any(user.id == self.bot.user.id for user in message.mentions) or bool(re.search(mention_pattern, message.content))
        if self.ai_channels.get(message.guild.id) != message.channel.id and not bot_mentioned:
            return
        content = re.sub(mention_pattern, "", message.content).strip()
        if not content:
            return

        async def send_response(text: str, allowed_mentions: discord.AllowedMentions | None = None):
            try:
                await message.reply(text, mention_author=False, allowed_mentions=allowed_mentions)
            except discord.HTTPException:
                try:
                    await message.channel.send(text, allowed_mentions=allowed_mentions)
                except discord.HTTPException:
                    logger.warning("Could not send AI response in channel %s", message.channel.id)

        member = message.author if isinstance(message.author, discord.Member) else message.guild.get_member(message.author.id)
        is_owner = message.author.id == message.guild.owner_id
        is_admin = is_owner or message.author.id == BOT_OWNER_ID or (member.guild_permissions.administrator if member else False)
        if is_admin and await self.try_ai_mod_command(message, content):
            return
        if not is_admin and self.is_restricted_request(content):
            await send_response("🚫 Denied. Only the **Server Owner** or **Administrators** can run moderation actions or ping `@everyone`/`@here`.", discord.AllowedMentions.none())
            return

        lock = self.channel_locks.setdefault(message.channel.id, asyncio.Lock())
        async with lock:
            history = self.channel_history.setdefault(message.channel.id, [])
            history.append(f"{message.author.display_name} (ID:{message.author.id}): {content}")
            history[:] = history[-8:]
            history_snapshot = list(history)
        memory = self.user_memories.get((message.guild.id, message.author.id), "None saved yet.")
        authority = "SERVER OWNER" if is_owner else "ADMINISTRATOR" if is_admin else "REGULAR MEMBER"
        wants_ping = is_admin and bool(re.search(r"@everyone|@here|\b(ping|mention|tag)\s+(everyone|here|all)\b", content.lower()))
        system_prompt = (f"You are Liebe — a chill, peaceful, helpful male Discord AI assistant created by {self.find_developer_mention(message.guild)}.\n"
                         f"{self.build_server_context(message.guild, message.channel)}\n"
                         f"Speaker: {message.author.display_name} (ID: {message.author.id}) | Authority: {authority} | Memory: {memory}\n"
                         "Be warm and helpful. Never send @everyone/@here unless an authorized admin explicitly asks. Share public server info when asked; don't spam mini-games.")
        async with message.channel.typing():
            reply, error = await self.generate_gemini_reply(system_prompt, f"Recent chat:\n{chr(10).join(history_snapshot)}\n\nReply to {message.author.display_name} as Liebe:")
        if not reply:
            await send_response(f"⚠️ Gemini error: `{(error or 'Unknown')[:180]}`", discord.AllowedMentions.none())
            return
        allowed = discord.AllowedMentions(everyone=wants_ping, roles=wants_ping, users=True)
        if not wants_ping:
            reply = re.sub(r"@(everyone|here)", "@\u200b\\1", reply, flags=re.IGNORECASE)
            reply = re.sub(r"<@&\d+>", "@role", reply)
        async with lock:
            history = self.channel_history.setdefault(message.channel.id, [])
            history.append(f"Liebe: {reply[:400]}")
            history[:] = history[-8:]
        for index in range(0, len(reply), 1950):
            part = reply[index:index + 1950]
            if index == 0:
                await send_response(part, allowed)
            else:
                try:
                    await message.channel.send(part, allowed_mentions=allowed)
                except discord.HTTPException:
                    logger.warning("Could not send AI response chunk in channel %s", message.channel.id)
                    return
        await self.increment_stat("messages_sent")
        if len(content) >= 35:
            asyncio.create_task(self.auto_update_memory(message.guild.id, message.author.id, message.author.display_name, content))


async def setup(bot: commands.Bot):
    await bot.add_cog(AIChatCog(bot))
