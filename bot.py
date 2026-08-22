"""
Overworld Event Bot — Raid-Helper-style signup bot.

Commands:
    /event create title description date time   -> posts an event embed with Accept/Leave buttons
    /event list                                  -> lists this server's active events
    /event close event_id                        -> stops the countdown / freezes signups (creator or admin)
    /event delete event_id                       -> deletes the event entirely (creator or admin)

Run:
    python bot.py
Requires DISCORD_TOKEN in the environment (see .env.example).
"""

import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import database as db
import utils
from views import SignupView

load_dotenv()

TOKEN = os.environ.get("DISCORD_TOKEN")
TZ_NAME = os.environ.get("TIMEZONE", "Europe/Stockholm")
TZ = ZoneInfo(TZ_NAME)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("eventbot")

intents = discord.Intents.default()


class EventBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await db.init_db()
        self.add_view(SignupView())  # persistent view, survives restarts
        await self.tree.sync()
        refresh_countdowns.start()


bot = EventBot()
event_group = app_commands.Group(name="event", description="Manage Overworld group events")


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} ({bot.user.id})")


def parse_start_datetime(date_str: str, time_str: str) -> int:
    """
    date_str: 'YYYY-MM-DD'
    time_str: 'HH:MM' (24h)
    Interpreted in TZ_NAME, returned as a unix timestamp (UTC).
    Raises ValueError on bad input.
    """
    naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    localized = naive.replace(tzinfo=TZ)
    return int(localized.timestamp())


@event_group.command(name="create", description="Create a new signup event")
@app_commands.describe(
    title="Event title",
    description="Event description",
    date="Start date, format YYYY-MM-DD",
    time="Start time (24h), format HH:MM",
)
async def event_create(interaction: discord.Interaction, title: str, description: str, date: str, time: str):
    try:
        start_ts = parse_start_datetime(date, time)
    except ValueError:
        await interaction.response.send_message(
            "Couldn't parse that date/time. Use `YYYY-MM-DD` for date and `HH:MM` (24h) for time, "
            f"e.g. `2026-08-25` and `19:30`. Times are interpreted as {TZ_NAME}.",
            ephemeral=True,
        )
        return

    event_id = await db.create_event(
        guild_id=interaction.guild_id,
        channel_id=interaction.channel_id,
        title=title,
        description=description,
        start_ts=start_ts,
        creator_id=interaction.user.id,
    )

    event = await db.get_event(event_id)
    accepted = await db.get_signups(event_id, db.ACCEPTED)
    priority = await db.get_signups(event_id, db.PRIORITY)
    embed = utils.build_event_embed(event, accepted, priority)
    view = SignupView()

    await interaction.response.send_message(embed=embed, view=view)
    sent_message = await interaction.original_response()
    await db.set_message_id(event_id, sent_message.id)


@event_group.command(name="list", description="List active events in this server")
async def event_list(interaction: discord.Interaction):
    events = await db.get_events_by_guild(interaction.guild_id)
    if not events:
        await interaction.response.send_message("No active events.", ephemeral=True)
        return

    lines = []
    for e in events:
        lines.append(f"**#{e['id']}** {e['title']} — <t:{e['start_ts']}:R>")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


def _can_manage(interaction: discord.Interaction, event) -> bool:
    if interaction.user.id == event["creator_id"]:
        return True
    perms = interaction.user.guild_permissions
    return perms.manage_guild or perms.administrator


@event_group.command(name="close", description="Freeze an event (stops the countdown, keeps the message)")
@app_commands.describe(event_id="The event ID shown in the embed footer or /event list")
async def event_close(interaction: discord.Interaction, event_id: int):
    event = await db.get_event(event_id)
    if event is None or event["guild_id"] != interaction.guild_id:
        await interaction.response.send_message("Event not found.", ephemeral=True)
        return
    if not _can_manage(interaction, event):
        await interaction.response.send_message("Only the creator or a server manager can do that.", ephemeral=True)
        return

    await db.close_event(event_id)
    event = await db.get_event(event_id)
    accepted = await db.get_signups(event_id, db.ACCEPTED)
    priority = await db.get_signups(event_id, db.PRIORITY)
    embed = utils.build_event_embed(event, accepted, priority)

    channel = bot.get_channel(event["channel_id"])
    if channel is not None and event["message_id"]:
        try:
            msg = await channel.fetch_message(event["message_id"])
            await msg.edit(embed=embed)
        except discord.NotFound:
            pass

    await interaction.response.send_message(f"Event #{event_id} closed.", ephemeral=True)


@event_group.command(name="delete", description="Delete an event entirely")
@app_commands.describe(event_id="The event ID shown in the embed footer or /event list")
async def event_delete(interaction: discord.Interaction, event_id: int):
    event = await db.get_event(event_id)
    if event is None or event["guild_id"] != interaction.guild_id:
        await interaction.response.send_message("Event not found.", ephemeral=True)
        return
    if not _can_manage(interaction, event):
        await interaction.response.send_message("Only the creator or a server manager can do that.", ephemeral=True)
        return

    channel = bot.get_channel(event["channel_id"])
    if channel is not None and event["message_id"]:
        try:
            msg = await channel.fetch_message(event["message_id"])
            await msg.delete()
        except discord.NotFound:
            pass

    await db.delete_event(event_id)
    await interaction.response.send_message(f"Event #{event_id} deleted.", ephemeral=True)


async def _refresh_message(event):
    """Re-fetch and re-render an event's message in-place. Used by the admin commands below."""
    channel = bot.get_channel(event["channel_id"])
    if channel is None or not event["message_id"]:
        return
    try:
        msg = await channel.fetch_message(event["message_id"])
    except discord.NotFound:
        return
    accepted = await db.get_signups(event["id"], db.ACCEPTED)
    priority = await db.get_signups(event["id"], db.PRIORITY)
    embed = utils.build_event_embed(event, accepted, priority)
    try:
        await msg.edit(embed=embed)
    except discord.HTTPException:
        pass


@event_group.command(name="remove_signup", description="[Admin] Remove someone from the Accepted list")
@app_commands.describe(event_id="The event ID", member="The member to remove")
async def event_remove_signup(interaction: discord.Interaction, event_id: int, member: discord.Member):
    event = await db.get_event(event_id)
    if event is None or event["guild_id"] != interaction.guild_id:
        await interaction.response.send_message("Event not found.", ephemeral=True)
        return
    if not _can_manage(interaction, event):
        await interaction.response.send_message("Only the creator or a server manager can do that.", ephemeral=True)
        return

    await db.remove_signup(event_id, member.id, db.ACCEPTED)
    await _refresh_message(event)
    await interaction.response.send_message(f"Removed {member.display_name} from Accepted.", ephemeral=True)


@event_group.command(name="add_priority", description="[Admin] Add someone to the Priority list")
@app_commands.describe(event_id="The event ID", member="The member to add as priority")
async def event_add_priority(interaction: discord.Interaction, event_id: int, member: discord.Member):
    event = await db.get_event(event_id)
    if event is None or event["guild_id"] != interaction.guild_id:
        await interaction.response.send_message("Event not found.", ephemeral=True)
        return
    if not _can_manage(interaction, event):
        await interaction.response.send_message("Only the creator or a server manager can do that.", ephemeral=True)
        return

    await db.add_signup(event_id, member.id, member.display_name, db.PRIORITY)
    await _refresh_message(event)
    await interaction.response.send_message(f"Added {member.display_name} to Priority.", ephemeral=True)


@event_group.command(name="remove_priority", description="[Admin] Remove someone from the Priority list")
@app_commands.describe(event_id="The event ID", member="The member to remove from priority")
async def event_remove_priority(interaction: discord.Interaction, event_id: int, member: discord.Member):
    event = await db.get_event(event_id)
    if event is None or event["guild_id"] != interaction.guild_id:
        await interaction.response.send_message("Event not found.", ephemeral=True)
        return
    if not _can_manage(interaction, event):
        await interaction.response.send_message("Only the creator or a server manager can do that.", ephemeral=True)
        return

    await db.remove_signup(event_id, member.id, db.PRIORITY)
    await _refresh_message(event)
    await interaction.response.send_message(f"Removed {member.display_name} from Priority.", ephemeral=True)


@event_group.command(name="set_world", description="[Admin] Set the raid world and notify everyone on Priority")
@app_commands.describe(event_id="The event ID", world="The world/server number or name")
async def event_set_world(interaction: discord.Interaction, event_id: int, world: str):
    event = await db.get_event(event_id)
    if event is None or event["guild_id"] != interaction.guild_id:
        await interaction.response.send_message("Event not found.", ephemeral=True)
        return
    if not _can_manage(interaction, event):
        await interaction.response.send_message("Only the creator or a server manager can do that.", ephemeral=True)
        return

    await db.set_world(event_id, world)
    event = await db.get_event(event_id)
    await _refresh_message(event)

    priority = await db.get_signups(event_id, db.PRIORITY)
    dm_blocked = []
    not_found = []
    for row in priority:
        try:
            member = await interaction.guild.fetch_member(row["user_id"])
        except discord.NotFound:
            not_found.append(row["username"])
            continue
        try:
            await member.send(f"Raid world is {world} {member.mention}")
        except discord.Forbidden:
            dm_blocked.append(row["username"])

    sent_count = len(priority) - len(dm_blocked) - len(not_found)
    summary = f"World set to **{world}**. Notified {sent_count}/{len(priority)} priority members."
    if dm_blocked:
        summary += f"\nDMs closed for: {', '.join(dm_blocked)}."
    if not_found:
        summary += f"\nNo longer in this server: {', '.join(not_found)}."
    await interaction.response.send_message(summary, ephemeral=True)


@tasks.loop(minutes=1)
async def refresh_countdowns():
    """Periodically re-render the 'Time Left' field on every active event."""
    events = await db.get_active_events()
    for event in events:
        if not event["message_id"]:
            continue
        channel = bot.get_channel(event["channel_id"])
        if channel is None:
            continue
        try:
            msg = await channel.fetch_message(event["message_id"])
        except (discord.NotFound, discord.Forbidden):
            continue

        accepted = await db.get_signups(event["id"], db.ACCEPTED)
        priority = await db.get_signups(event["id"], db.PRIORITY)
        embed = utils.build_event_embed(event, accepted, priority)
        try:
            await msg.edit(embed=embed)
        except discord.HTTPException:
            pass


@refresh_countdowns.before_loop
async def before_refresh():
    await bot.wait_until_ready()


bot.tree.add_command(event_group)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
    bot.run(TOKEN)
