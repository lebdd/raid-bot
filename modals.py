"""
The pop-up form used by /event create.

Using a Modal instead of plain slash-command string options gives the
Description field a real multi-line textarea — Enter creates a new line,
and Discord's `#` / `##` / `###` header markdown renders correctly inside it
(embed *titles* never support markdown, no matter how they're entered —
that's a Discord-wide limitation, not something this bot controls).
"""

import discord

import database as db
import utils
from views import SignupView


class EventCreateModal(discord.ui.Modal, title="Create Raid Event"):
    event_title = discord.ui.TextInput(
        label="Title (short, plain text)",
        placeholder="e.g. Overworld Is Calling",
        max_length=256,
        style=discord.TextStyle.short,
    )
    description = discord.ui.TextInput(
        label="Description",
        placeholder="Use # for a header, ## for smaller, blank lines for paragraphs...",
        style=discord.TextStyle.paragraph,
        max_length=3900,
        required=True,
    )
    date = discord.ui.TextInput(
        label="Start Date (YYYY-MM-DD)",
        placeholder="2026-08-28",
        max_length=10,
        style=discord.TextStyle.short,
    )
    time = discord.ui.TextInput(
        label="Start Time, 24h (HH:MM)",
        placeholder="19:30",
        max_length=5,
        style=discord.TextStyle.short,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            start_ts = utils.parse_start_datetime(self.date.value, self.time.value)
        except ValueError:
            await interaction.response.send_message(
                "Couldn't parse that date/time. Use `YYYY-MM-DD` for date and `HH:MM` (24h) for time, "
                f"e.g. `2026-08-28` and `19:30`. Times are interpreted as {utils.TZ_NAME}.",
                ephemeral=True,
            )
            return

        event_id = await db.create_event(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            title=self.event_title.value,
            description=self.description.value,
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
