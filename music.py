import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'default_search': 'ytsearch',
    'quiet': True,
    'no_warnings': True,
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}


class MusicPanelView(discord.ui.View):
    def __init__(self, cog, guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(emoji="⏯️", label="Play/Pause", style=discord.ButtonStyle.primary, row=0)
    async def play_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("Bot is not connected to a voice channel.", ephemeral=True)
        
        if vc.is_playing():
            vc.pause()
            await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction.guild), view=self)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction.guild), view=self)
        else:
            await interaction.response.send_message("Nothing is currently playing.", ephemeral=True)

    @discord.ui.button(emoji="⏭️", label="Skip", style=discord.ButtonStyle.secondary, row=0)
    async def skip_song(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc or (not vc.is_playing() and not vc.is_paused()):
            return await interaction.response.send_message("Nothing to skip.", ephemeral=True)
        
        vc.stop()  # Triggers the after_playing callback to play the next song
        await asyncio.sleep(0.5)
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction.guild), view=self)

    @discord.ui.button(emoji="⏹️", label="Stop", style=discord.ButtonStyle.danger, row=0)
    async def stop_music(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        state = self.cog.get_guild_state(self.guild_id)
        state["queue"].clear()
        state["current"] = None
        state["loop"] = False
        if vc:
            vc.stop()
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction.guild), view=self)

    @discord.ui.button(emoji="🔁", label="Loop", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.get_guild_state(self.guild_id)
        state["loop"] = not state["loop"]
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction.guild), view=self)

    @discord.ui.button(emoji="🔉", label="-10%", style=discord.ButtonStyle.secondary, row=1)
    async def vol_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        state = self.cog.get_guild_state(self.guild_id)
        state["volume"] = max(0.0, round(state["volume"] - 0.1, 1))
        if vc and vc.source:
            vc.source.volume = state["volume"]
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction.guild), view=self)

    @discord.ui.button(emoji="🔊", label="+10%", style=discord.ButtonStyle.secondary, row=1)
    async def vol_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        state = self.cog.get_guild_state(self.guild_id)
        state["volume"] = min(2.0, round(state["volume"] + 0.1, 1))
        if vc and vc.source:
            vc.source.volume = state["volume"]
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction.guild), view=self)

    @discord.ui.button(emoji="📜", label="Queue", style=discord.ButtonStyle.success, row=1)
    async def show_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.get_guild_state(self.guild_id)
        queue = state["queue"]
        if not queue:
            return await interaction.response.send_message("The queue is currently empty.", ephemeral=True)
        
        q_text = "\n".join([f"**{idx + 1}.** {song['title']}" for idx, song in enumerate(queue[:15])])
        if len(queue) > 15:
            q_text += f"\n*...and {len(queue) - 15} more*"
            
        embed = discord.Embed(title="🎶 Upcoming Song Queue", description=q_text, color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.guild_states = {}

    def get_guild_state(self, guild_id: int):
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = {
                "queue": [],
                "current": None,
                "volume": 0.5,  # Default 50%
                "loop": False,
            }
        return self.guild_states[guild_id]

    def build_panel_embed(self, guild: discord.Guild) -> discord.Embed:
        state = self.get_guild_state(guild.id)
        vc = guild.voice_client
        current = state["current"]

        if current and vc and (vc.is_playing() or vc.is_paused()):
            status = "⏸️ Paused" if vc.is_paused() else "▶️ Playing"
            now_playing = f"**[{current['title']}]({current['webpage_url']})**"
            duration = current.get("duration_str", "Unknown")
        else:
            status = "⏹️ Idle"
            now_playing = "Nothing playing right now."
            duration = "0:00"

        vol_percent = int(state["volume"] * 100)
        loop_status = "✅ On" if state["loop"] else "❌ Off"
        queue_count = len(state["queue"])

        embed = discord.Embed(title="🎛️ Live Music Control Panel", color=discord.Color.dark_theme())
        embed.add_field(name="Now Playing", value=now_playing, inline=False)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Duration", value=duration, inline=True)
        embed.add_field(name="Volume", value=f"{vol_percent}%", inline=True)
        embed.add_field(name="Loop", value=loop_status, inline=True)
        embed.add_field(name="Songs in Queue", value=str(queue_count), inline=True)

        if current and current.get("thumbnail"):
            embed.set_thumbnail(url=current["thumbnail"])

        return embed

    def play_next(self, guild: discord.Guild):
        state = self.get_guild_state(guild.id)
        vc = guild.voice_client

        if not vc or not vc.is_connected():
            state["current"] = None
            return

        if state["loop"] and state["current"]:
            next_song = state["current"]
        elif state["queue"]:
            next_song = state["queue"].pop(0)
            state["current"] = next_song
        else:
            state["current"] = None
            return

        raw_source = discord.FFmpegPCMAudio(next_song["stream_url"], **FFMPEG_OPTIONS)
        transformed_source = discord.PCMVolumeTransformer(raw_source, volume=state["volume"])

        def after_playing(error):
            if error:
                print(f"Audio playback error: {error}")
            self.bot.loop.call_soon_threadsafe(self.play_next, guild)

        vc.play(transformed_source, after=after_playing)

    @app_commands.command(name="joinmusic", description="Make the bot join your current voice channel.")
    async def join_music(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                "❌ You must be inside a voice channel first!", ephemeral=True
            )

        channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client

        if vc:
            if vc.channel.id == channel.id:
                return await interaction.response.send_message("I am already in your voice channel!", ephemeral=True)
            await vc.move_to(channel)
        else:
            await channel.connect()

        await interaction.response.send_message(f"🔊 Joined **{channel.name}**!")

    @app_commands.command(name="playmusic", description="Search a song by name or URL and play/queue it.")
    @app_commands.describe(song="Song name or YouTube URL")
    async def play_music(self, interaction: discord.Interaction, song: str):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                "❌ Join a voice channel first to play music!", ephemeral=True
            )

        await interaction.response.defer(thinking=True)

        vc = interaction.guild.voice_client
        if not vc:
            vc = await interaction.user.voice.channel.connect()
        elif vc.channel != interaction.user.voice.channel:
            await vc.move_to(interaction.user.voice.channel)

        # Fetch track metadata & audio stream via yt-dlp in a non-blocking executor
        loop = asyncio.get_event_loop()
        try:
            def extract():
                with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                    info = ydl.extract_info(song, download=False)
                    if 'entries' in info:
                        info = info['entries'][0]
                    return info

            info = await loop.run_in_executor(None, extract)
        except Exception as e:
            return await interaction.followup.send(f"❌ Could not find or load that song: `{e}`")

        duration_sec = info.get("duration", 0)
        mins, secs = divmod(int(duration_sec), 60)
        
        track_data = {
            "title": info.get("title", "Unknown Track"),
            "stream_url": info["url"],
            "webpage_url": info.get("webpage_url", ""),
            "thumbnail": info.get("thumbnail", None),
            "duration_str": f"{mins}:{secs:02d}" if duration_sec else "Live",
        }

        state = self.get_guild_state(interaction.guild.id)
        state["queue"].append(track_data)

        if not vc.is_playing() and not vc.is_paused():
            self.play_next(interaction.guild)
            await interaction.followup.send(f"🎶 Now playing: **{track_data['title']}** (`{track_data['duration_str']}`)")
        else:
            await interaction.followup.send(f"➕ Added to queue (#{len(state['queue'])}): **{track_data['title']}** (`{track_data['duration_str']}`)")

    @app_commands.command(name="musicpanel", description="Open the interactive music controller panel.")
    async def music_panel(self, interaction: discord.Interaction):
        embed = self.build_panel_embed(interaction.guild)
        view = MusicPanelView(self, interaction.guild.id)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
