"""
Helpers for building the event embed and formatting the countdown.
"""

import time
import discord

ACCENT_COLOR = 0x5865F2  # discord blurple; change to taste


def format_time_left(start_ts: int) -> str:
    """Return a human string like '2d 4h 12m' / 'Starting now' / 'Started 1h 5m ago'."""
    now = int(time.time())
    delta = start_ts - now

    if -60 < delta <= 60:
        return "Starting now"

    past = delta < 0
    delta = abs(delta)

    days, rem = divmod(delta, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")

    text = " ".join(parts)
    return f"Started {text} ago" if past else text


def build_event_embed(event, accepted_signups, priority_signups) -> discord.Embed:
    """
    event: aiosqlite.Row with columns id, title, description, start_ts, creator_id, closed
    accepted_signups / priority_signups: list of aiosqlite.Row with columns user_id, username
    """
    embed = discord.Embed(
        title=event["title"],
        description=event["description"],
        color=ACCENT_COLOR,
    )

    embed.add_field(name="Start Date", value=f"<t:{event['start_ts']}:F>", inline=True)

    if event["closed"]:
        time_left_value = "Event closed"
    else:
        time_left_value = format_time_left(event["start_ts"])
    embed.add_field(name="Time Left", value=time_left_value, inline=True)

    # invisible 3rd column that fills out row 1 (Discord groups inline fields 3-per-row), so
    # Accepted/Priority start a fresh 2-column row right after with no extra gap. World is
    # intentionally NOT shown here — it's private info sent only via DM to Priority members.
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    accepted_names = [s["username"] for s in accepted_signups]
    accepted_text = "\n".join(accepted_names) if accepted_names else "*No one yet*"
    embed.add_field(name=f"Accepted ({len(accepted_names)})", value=accepted_text, inline=True)

    priority_names = [s["username"] for s in priority_signups]
    priority_text = "\n".join(priority_names) if priority_names else "*None set*"
    embed.add_field(name=f"Priority ({len(priority_names)})", value=priority_text, inline=True)

    embed.set_footer(text=f"Event ID: {event['id']}")
    return embed
