import datetime

import discord
import html
from communex.key import is_ss58_address
import validators

from ..db.cache import CACHE
from ..config.settings import MODULE_SUBMISSION_DELAY, DISCORD_PARAMS

# == Module Request UI ==
class ModuleRequestModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.add_item(discord.ui.InputText(label="SS58 Address of the Module"))
        self.add_item(
            discord.ui.InputText(
                label="What your module does", style=discord.InputTextStyle.long
            )
        )
        self.add_item(
            discord.ui.InputText(
                label="Module API docs", style=discord.InputTextStyle.long
            )
        )
        self.add_item(
            discord.ui.InputText(label="Team Members (Developers of the Module)")
        )
        self.add_item(
            discord.ui.InputText(label="Repository Link (GitHub, GitLab, etc.)")
        )

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        assert user is not None
        user_id = str(user.id)
        current_time = datetime.datetime.now()
        last_submission_times = CACHE.last_submission_times
        if user_id in CACHE.last_submission_times:
            last_submission_time = last_submission_times[user_id]
            time_since_last_submission = current_time - last_submission_time

            if time_since_last_submission < datetime.timedelta(
                minutes=MODULE_SUBMISSION_DELAY
            ):
                remaining_time = (
                    datetime.timedelta(minutes=MODULE_SUBMISSION_DELAY)
                    - time_since_last_submission
                )
                await interaction.response.send_message(
                    f"You can submit another module request in {remaining_time.seconds} seconds.",
                    ephemeral=True,
                )
                return

        # Validate and sanitize user inputs
        ss58_address = html.escape(self.children[0].value.strip())
        module_description = html.escape(self.children[1].value.strip())
        endpoint_info = html.escape(self.children[2].value.strip())
        team_members = html.escape(self.children[3].value.strip())
        repository_link = html.escape(self.children[4].value.strip())

        # Validate SS58 address format
        if not is_ss58_address(ss58_address):
            await interaction.response.send_message(
                "Invalid SS58 Address", ephemeral=True
            )
            return

        if ss58_address in CACHE.current_whitelist:
            await interaction.response.send_message(
                "Module already whitelisted", ephemeral=True
            )
            return

        # Validate repository link
        if not validators.url(repository_link):
            await interaction.response.send_message(
                "Invalid Repository Link", ephemeral=True
            )
            return

        # Check if the SS58 address is already submitted
        if ss58_address in CACHE.request_ids:
            await interaction.response.send_message(
                "Module request already submitted", ephemeral=True
            )
            return

        embed = discord.Embed(title="Module Request", color=discord.Color(0xFF69B4))
        embed.add_field(
            name="Submitted by", value=interaction.user.mention, inline=False
        )
        embed.add_field(name="SS58 Address", value=ss58_address, inline=False)
        embed.add_field(
            name="Module Description", value=module_description, inline=False
        )
        embed.add_field(name="Endpoint Information", value=endpoint_info, inline=False)
        embed.add_field(name="Team Members", value=team_members, inline=False)
        embed.add_field(name="Repository Link", value=repository_link, inline=False)

        # Key considered as the request ID
        CACHE.request_ids.append(ss58_address)

        # Update the last submission time for the user
        last_submission_times[user_id] = current_time

        # Send the embed to the specific channel
        channel_id = DISCORD_PARAMS.NOMINATOR_CHANNEL_ID
        channel = interaction.guild.get_channel(channel_id)
        await channel.send(embed=embed)

        # Respond to the interaction
        await interaction.response.send_message(
            "Module request submitted successfully", ephemeral=True
        )
        CACHE.save_to_disk()


class ModuleRequestView(discord.ui.View):
    @discord.ui.button(label="Submit Module Request", style=discord.ButtonStyle.primary)
    async def submit_module_request(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ) -> None:
        modal = ModuleRequestModal(title="Submit Module Request")
        await interaction.response.send_modal(modal)
