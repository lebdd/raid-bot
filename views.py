"""
Persistent View for the Accept / Leave buttons on event embeds.

Persistence approach: buttons use fixed custom_ids (not per-event), and the
callback looks up which event this is by the message the button lives on.
That means one view instance registered at startup covers every event
message, including ones created before a restart.

Note: only the self-serve "Accepted" list has buttons. The "Priority" list
is admin-managed via slash commands (/event add_priority, /event remove_priority)
since it's meant to be set by the raid organizers, not the players themselves.
"""

import discord
import database as db
import utils


class SignupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _refresh_embed(self, interaction: discord.Interaction, event_id: int):
        event = await db.get_event(event_id)
        accepted = await db.get_signups(event_id, db.ACCEPTED)
        priority = await db.get_signups(event_id, db.PRIORITY)
        embed = utils.build_event_embed(event, accepted, priority)
        await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="raidhelper_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        event = await db.get_event_by_message(interaction.message.id)
        if event is None or event["closed"]:
            await interaction.response.send_message("This event is no longer active.", ephemeral=True)
            return

        await db.add_signup(event["id"], interaction.user.id, interaction.user.display_name, db.ACCEPTED)
        await interaction.response.defer()
        await self._refresh_embed(interaction, event["id"])

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.danger, custom_id="raidhelper_leave")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        event = await db.get_event_by_message(interaction.message.id)
        if event is None or event["closed"]:
            await interaction.response.send_message("This event is no longer active.", ephemeral=True)
            return

        await db.remove_signup(event["id"], interaction.user.id, db.ACCEPTED)
        await interaction.response.defer()
        await self._refresh_embed(interaction, event["id"])
