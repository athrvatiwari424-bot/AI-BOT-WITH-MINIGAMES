"""Persistent multi-category ticket panels for Liebe."""
import re
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

DB = "bot_data.db"
TICKET_TYPES = {
    "support": ("🛠️ Support", "Support Tickets", discord.ButtonStyle.primary),
    "sponsor": ("💜 Sponsorship", "Sponsorship Tickets", discord.ButtonStyle.success),
    "general": ("💬 General Help", "General Tickets", discord.ButtonStyle.secondary),
    "other": ("📩 Other", "Other Tickets", discord.ButtonStyle.danger),
}


def admin_only():
    async def predicate(interaction: discord.Interaction):
        return bool(interaction.guild and isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator)
    return app_commands.check(predicate)


class TicketCloseView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Close ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="liebe_ticket_close_v1")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.close_ticket(interaction)


class TicketPanelView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        for key, (label, _, style) in TICKET_TYPES.items():
            button = discord.ui.Button(label=label, style=style, custom_id=f"liebe_ticket_open_{key}_v1")
            button.callback = self._make_callback(key)
            self.add_item(button)

    def _make_callback(self, ticket_type):
        async def callback(interaction: discord.Interaction):
            await self.cog.create_ticket(interaction, ticket_type)
        return callback


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB) as db:
            await db.executescript("""
            CREATE TABLE IF NOT EXISTS ticket_panels (
                guild_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ticket_categories (
                guild_id INTEGER NOT NULL, ticket_type TEXT NOT NULL, category_id INTEGER NOT NULL,
                PRIMARY KEY(guild_id, ticket_type)
            );
            CREATE TABLE IF NOT EXISTS tickets (
                channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                ticket_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """)
            await db.commit()
            cur = await db.execute("SELECT guild_id,message_id FROM ticket_panels")
            panels = await cur.fetchall()
            cur = await db.execute("SELECT channel_id FROM tickets WHERE status='open'")
            open_tickets = await cur.fetchall()
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(TicketCloseView(self))

    async def _get_panel(self, guild_id):
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT channel_id,message_id,title,description FROM ticket_panels WHERE guild_id=?", (guild_id,))
            return await cur.fetchone()

    async def _get_category(self, guild_id, ticket_type):
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT category_id FROM ticket_categories WHERE guild_id=? AND ticket_type=?", (guild_id, ticket_type))
            row = await cur.fetchone()
            return row[0] if row else None

    def panel_embed(self, title, description):
        embed = discord.Embed(title=title, description=description, color=discord.Color.blurple())
        embed.set_footer(text="Choose a ticket type below. A private channel will be created for you.")
        return embed

    @app_commands.guild_only()
    @app_commands.command(name="ticket-setup", description="Create a ticket panel and default ticket categories")
    @app_commands.describe(channel="Channel where the ticket panel should be posted")
    @admin_only()
    async def ticket_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild = interaction.guild
        me = guild.me
        if not me.guild_permissions.manage_channels or not channel.permissions_for(me).send_messages or not channel.permissions_for(me).embed_links:
            return await interaction.response.send_message("I need Manage Channels, Send Messages and Embed Links permissions.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        for key, (_, category_name, _) in TICKET_TYPES.items():
            category = discord.utils.get(guild.categories, name=category_name)
            if category is None:
                try:
                    category = await guild.create_category(category_name, reason="Liebe ticket system setup")
                except discord.HTTPException:
                    return await interaction.followup.send(f"I could not create the **{category_name}** category. Check my role and channel permissions.", ephemeral=True)
            async with aiosqlite.connect(DB) as db:
                await db.execute("INSERT INTO ticket_categories(guild_id,ticket_type,category_id) VALUES(?,?,?) ON CONFLICT(guild_id,ticket_type) DO UPDATE SET category_id=excluded.category_id", (guild.id, key, category.id))
                await db.commit()
        title = "🎫 Open a Ticket"
        description = "Select the department that best matches your request. Liebe will create a private ticket channel for you."
        panel = await channel.send(embed=self.panel_embed(title, description), view=TicketPanelView(self))
        async with aiosqlite.connect(DB) as db:
            await db.execute("INSERT INTO ticket_panels(guild_id,channel_id,message_id,title,description) VALUES(?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id,message_id=excluded.message_id,title=excluded.title,description=excluded.description", (guild.id, channel.id, panel.id, title, description))
            await db.commit()
        await interaction.followup.send(f"✅ Ticket panel created in {channel.mention}. Default categories are ready: Support, Sponsorship, General Help and Other.", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="ticket-edit", description="Edit the ticket panel embed")
    @app_commands.describe(title="New panel title", description="New panel description")
    @admin_only()
    async def ticket_edit(self, interaction: discord.Interaction, title: app_commands.Range[str, 1, 200], description: app_commands.Range[str, 1, 3000]):
        row = await self._get_panel(interaction.guild_id)
        if not row:
            return await interaction.response.send_message("Run `/ticket-setup` first.", ephemeral=True)
        channel_id, message_id, _, _ = row
        channel = interaction.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("The configured ticket panel channel no longer exists. Run `/ticket-setup` again.", ephemeral=True)
        try:
            panel = await channel.fetch_message(message_id)
            await panel.edit(embed=self.panel_embed(title, description), view=TicketPanelView(self))
        except discord.HTTPException:
            return await interaction.response.send_message("I could not edit the ticket panel. Check my channel permissions.", ephemeral=True)
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE ticket_panels SET title=?,description=? WHERE guild_id=?", (title, description, interaction.guild_id))
            await db.commit()
        await interaction.response.send_message("✅ Ticket panel embed updated.", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="ticket-category", description="Assign a ticket type to an existing category")
    @app_commands.choices(ticket_type=[app_commands.Choice(name="Support", value="support"), app_commands.Choice(name="Sponsorship", value="sponsor"), app_commands.Choice(name="General Help", value="general"), app_commands.Choice(name="Other", value="other")])
    @admin_only()
    async def ticket_category(self, interaction: discord.Interaction, ticket_type: str, category: discord.CategoryChannel):
        async with aiosqlite.connect(DB) as db:
            await db.execute("INSERT INTO ticket_categories(guild_id,ticket_type,category_id) VALUES(?,?,?) ON CONFLICT(guild_id,ticket_type) DO UPDATE SET category_id=excluded.category_id", (interaction.guild_id, ticket_type, category.id))
            await db.commit()
        await interaction.response.send_message(f"✅ {TICKET_TYPES[ticket_type][0]} tickets will now be created under **{category.name}**.", ephemeral=True)

    async def create_ticket(self, interaction: discord.Interaction, ticket_type: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Tickets can only be opened inside a server.", ephemeral=True)
        guild = interaction.guild
        category_id = await self._get_category(guild.id, ticket_type)
        category = guild.get_channel(category_id) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message("This ticket category is not configured. Ask an administrator to run `/ticket-setup`.", ephemeral=True)
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT channel_id FROM tickets WHERE guild_id=? AND user_id=? AND ticket_type=? AND status='open'", (guild.id, interaction.user.id, ticket_type))
            existing = await cur.fetchone()
        if existing:
            channel = guild.get_channel(existing[0])
            if channel:
                return await interaction.response.send_message(f"You already have an open ticket of this type: {channel.mention}", ephemeral=True)
        me = guild.me
        if not me.guild_permissions.manage_channels:
            return await interaction.response.send_message("I need Manage Channels permission to create tickets.", ephemeral=True)
        safe_name = re.sub(r"[^a-z0-9-]", "-", interaction.user.name.lower()).strip("-")[:18] or "member"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True),
            me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True),
        }
        for role in guild.roles:
            if not role.is_default() and not role.managed and (role.permissions.manage_channels or role.permissions.administrator):
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        try:
            channel = await guild.create_text_channel(f"{ticket_type}-{safe_name}", category=category, overwrites=overwrites, topic=f"Liebe ticket | owner_id={interaction.user.id} | type={ticket_type}", reason=f"Ticket opened by {interaction.user.id}")
        except discord.HTTPException:
            return await interaction.response.send_message("I could not create your ticket. Please notify a server administrator.", ephemeral=True)
        async with aiosqlite.connect(DB) as db:
            await db.execute("INSERT INTO tickets(channel_id,guild_id,user_id,ticket_type,status) VALUES(?,?,?,?, 'open')", (channel.id, guild.id, interaction.user.id, ticket_type))
            await db.commit()
        label = TICKET_TYPES[ticket_type][0]
        embed = discord.Embed(title=f"{label} Ticket", description=f"Welcome {interaction.user.mention}! Please describe your request. A staff member will respond when available.", color=discord.Color.blurple())
        embed.add_field(name="Ticket owner", value=interaction.user.mention)
        await channel.send(content=interaction.user.mention, embed=embed, view=TicketCloseView(self), allowed_mentions=discord.AllowedMentions(users=[interaction.user]))
        await interaction.response.send_message(f"✅ Your ticket has been created: {channel.mention}", ephemeral=True)

    async def close_ticket(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT user_id,status FROM tickets WHERE channel_id=? AND guild_id=?", (interaction.channel.id, interaction.guild_id))
            row = await cur.fetchone()
        if not row or row[1] != "open":
            return await interaction.response.send_message("This ticket is already closed or is not registered.", ephemeral=True)
        if interaction.user.id != row[0] and not (isinstance(interaction.user, discord.Member) and (interaction.user.guild_permissions.manage_channels or interaction.user.guild_permissions.administrator)):
            return await interaction.response.send_message("Only the ticket owner or server staff can close this ticket.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.channel.set_permissions(discord.Object(id=row[0]), view_channel=True, send_messages=False, add_reactions=False)
            await interaction.channel.edit(name=f"closed-{interaction.channel.name}"[:100])
        except discord.HTTPException:
            pass
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE tickets SET status='closed' WHERE channel_id=?", (interaction.channel.id,))
            await db.commit()
        await interaction.followup.send("🔒 Ticket closed. Staff can archive or delete this channel when appropriate.", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="ticket-close", description="Close the current ticket")
    async def ticket_close(self, interaction: discord.Interaction):
        await self.close_ticket(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
