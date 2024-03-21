import asyncio
from collections import defaultdict
import datetime
import os
from typing import Any
import random

import discord
from discord.ext import commands
# for valid url
import validators

from substrateinterface import Keypair
from substrateinterface.base import ExtrinsicReceipt

from communex.key import is_ss58_address
from communex.client import CommuneClient
from communex.compat.key import classic_load_key
from communex.types import NetworkParams, Ss58Address

# 5H8ae6DK7kAdoa89V4BeR3fDtzajNurhVJDVc2TzLsCENGHs
# constants
MNEMONIC = os.environ['MNEMONIC']
BOT_TOKEN = os.environ['DISCORD_BOT_TOKEN']
GUILD_ID = str(os.environ['DISCORD_GUILD_ID'])
REQUEST_CHANNEL_ID = int(os.environ['DISCORD_REQUEST_CHANNEL_ID'])
NOMINATOR_CHANNEL_ID = int(os.environ['DISCORD_NOMINATOR_CHANNEL_ID'])

ROLE_NAME = "nominator"
NODE_URL = "ws://127.0.0.1:9944" # "wss://commune.api.onfinality.io/public-ws"

INTENTS = discord.Intents.all()
BOT = commands.Bot(command_prefix="/", intents=INTENTS)

# module request storage
request_ids: list[Ss58Address] = []
# discord_user_id : voted_ticket_id
nomination_approvals: dict[str, list[Ss58Address]] = {}
removal_approvals: dict[str, list[Ss58Address]] = {}

last_submission_times = {}


async def whitelist() -> list[Ss58Address]:
    "x"
    client = CommuneClient(NODE_URL)
    # Get the whitelist from the blockchain
    # TODO: Implement this
    legit_whitelist = client.query("LegitWhitelist", params=[])
    return legit_whitelist

async def send_call(fn: str, keypair: Keypair, call: dict) -> None:
    "x"
    # Send the call to the blockchain
    client = CommuneClient(NODE_URL)
    response = client.compose_call(fn=fn, params=call, key=keypair)
    print(f"response of the function {fn} is {response}")
    return response

@BOT.event
async def on_ready() -> None:
    "x"
    print(f"{BOT.user} is now online!")
    await setup_module_request_ui()


@BOT.slash_command(guild_ids=[GUILD_ID],  # !!! make sure to pass as string
                   description="Help command")
async def helpnominate(ctx) -> None:
    "x"
    help_message = """
🚀 **Available Commands:**

1. `/nominate <ss58 key>`
   - Starts a ticket for nominating a module for the whitelist.
   - ✅ Implemented

2. `/remove <ss58 key> <reason>`
   - Starts a ticket for removing a module from the whitelist.
   - ✅ Implemented

3. `/addvoter <discord tag>`
   - Creates a new multisig key and the bot DMs the user with an intro (guideline and commands).
   - ⏳ Not yet implemented

4. `/kickvoter <discord tag>`
   - Deletes the associated multisig key and the bot DMs the user with info about their removal.
   - ⏳ Not yet implemented

5. `/stats`
   - Lists a table of members and their `multisig_participation_count` and `multisig_abscence_count`, ranked by participation.
   - ✅ Implemented

6. `/help`
   - Displays this help message.
   - ✅ Implemented

📝 **Note:** Replace `<parameter>` with the appropriate value when using the commands.
"""

    await ctx.respond(help_message, ephemeral=True)


@BOT.slash_command(guild_ids=[GUILD_ID],  # !!! make sure to pass as string
                   description="Lists member stats based on multisig participation.")
async def stats(ctx) -> None:
    "x"
    member_stats = defaultdict(
        lambda: {"participation_count": 0, "absence_count": 0})

    for user_id, approvals in nomination_approvals.items():
        member = await ctx.guild.fetch_member(user_id)
        if member:
            for _, _ in approvals:
                member_stats[member.id]["participation_count"] += 1

    total_tickets = len(request_ids)
    for member_id in member_stats:
        member_stats[member_id]["absence_count"] = total_tickets - \
            member_stats[member_id]["participation_count"]

    sorted_stats = sorted(member_stats.items(
    ), key=lambda x: x[1]["participation_count"], reverse=True)

    table = "```\n"
    table += "| {:<25} | {:<30} | {:<25} |\n".format(
        "Member", "Multisig Participation Count", "Multisig Absence Count")
    table += "-" * 90 + "\n"

    for member_id, stat in sorted_stats:
        member = await ctx.guild.fetch_member(member_id)
        if member:
            table += "| {:<25} | {:<30} | {:<25} |\n".format(
                member.name, stat['participation_count'], stat['absence_count'])

    table += "```"

    await ctx.respond(f"**Member Stats:**\n\n{table}", ephemeral=True)


@BOT.slash_command(guild_ids=[GUILD_ID],  # !!! make sure to pass as string
                   description="Nominates module to a whitelist.",
                   manage_roles=True)
async def nominate(ctx, module_key: str) -> None:
    "x"
    if ctx.channel.id != NOMINATOR_CHANNEL_ID:
        await ctx.respond("This command can only be used in the designated channel.",
                           ephemeral=True)
        return

    role = discord.utils.get(ctx.guild.roles, name=ROLE_NAME)
    if role not in ctx.author.roles:
        await ctx.respond("You don't have the required role to use this command.", ephemeral=True)
        return

    signatores_count = len(role.members)
    threshold = signatores_count // 2 + 1

    if not is_ss58_address(module_key):
        await ctx.respond("Invalid module key.", ephemeral=True)
        return

    nominated_modules = [approval[1] for approval in nomination_approvals.get(ctx.author.id, [])]
    if module_key in nominated_modules:
        await ctx.respond(f"You have already nominated {module_key}.", ephemeral=True)
        return

    if module_key not in request_ids:
        await ctx.respond(
            f"Module key {module_key} is not submitted for access, open a request.",
            ephemeral=True
        )
        return

    current_whitelist = await whitelist()
    if module_key in current_whitelist:
        await ctx.respond(f"Module key {module_key} is already whitelisted", ephemeral=True)
        return

    agreement_count = sum(module == module_key for approvals
                          in nomination_approvals.values() for _, module in approvals)
    onchain_message = (
        "Multisig is now adding this module onchain, it will soon start getting votes."
        if agreement_count == threshold
        else "Still waiting for more votes, before executing onchain."
    )

    await ctx.respond(
        f"Nominator {ctx.author.mention} accepted module `{module_key}`.\n"
        f"This is the `{agreement_count}` agreement out of `{threshold}` threshold.\n"
        f"{onchain_message}"
    )

    if agreement_count == threshold:
        current_keypair = Keypair.create_from_mnemonic(MNEMONIC)
        fn = "add_to_whitelist"
        call = {"module_key": module_key}
        response = await send_call(fn, current_keypair, call)
        print(f"Response of the function {fn} is {response}")

        for user_id in list(nomination_approvals.keys()):
            nomination_approvals[user_id] = [
                approval for approval in nomination_approvals[user_id] if approval[1] != module_key
            ]

@BOT.slash_command(guild_ids=[GUILD_ID],  # !!! make sure to pass as string
                   description="Removes module from a whitelist.",
                   manage_roles=True)
async def remove(ctx, module_key: str, reason: str) -> None:
    "x"
    if ctx.channel.id != NOMINATOR_CHANNEL_ID:
        await ctx.respond("This command can only be used in the designated channel.",
                           ephemeral=True)
        return

    role = discord.utils.get(ctx.guild.roles, name=ROLE_NAME)
    if role not in ctx.author.roles:
        await ctx.respond("You don't have the required role to use this command.", ephemeral=True)
        return

    signatores_count = len(role.members)
    threshold = signatores_count // 2 + 1

    if not is_ss58_address(module_key):
        await ctx.respond("Invalid module key.", ephemeral=True)
        return

    nominated_modules = [approval[1] for approval in removal_approvals.get(ctx.author.id, [])]
    if module_key in nominated_modules:
        await ctx.respond(f"You have already asked to remove {module_key}.", ephemeral=True)
        return


    current_whitelist = await whitelist()
    if module_key not in current_whitelist:
        await ctx.respond(f"Module key {module_key} is not whitelisted", ephemeral=True)
        return

    agreement_count = sum(module == module_key for approvals
                          in removal_approvals.values() for _, module in approvals)
    onchain_message = (
        "Multisig is now removing this module onchain, it will soon be removed."
        if agreement_count == threshold
        else "Still waiting for more votes, before executing onchain."
    )

    await ctx.respond(
        f"Nominator {ctx.author.mention} asked to remove module `{module_key}`.\n"
        f"For the reason of `{reason}`.\n"
        f"This is the `{agreement_count}` agreement out of `{threshold}` threshold.\n"
        f"{onchain_message}"
    )

    if agreement_count == threshold:
        current_keypair = Keypair.create_from_mnemonic(MNEMONIC)
        fn = "remove_from_whitelist"
        call = {"module_key": module_key}
        response = await send_call(fn, current_keypair, call)
        print(f"Response of the function {fn} is {response}")

        for user_id in list(nomination_approvals.keys()):
            nomination_approvals[user_id] = [
                approval for approval in nomination_approvals[user_id] if approval[1] != module_key
            ]


async def setup_module_request_ui():
    "x"
    channel = BOT.get_channel(REQUEST_CHANNEL_ID)  # as integer

    embed = discord.Embed(
        title="Submit Module Request",
        description="Click the button below to submit a module request.",
        color=discord.Color.green()
    )
    embed.set_thumbnail(
        url="https://www.communeai.org/gif/cubes/green_small.gif")

    view = ModuleRequestView()
    message = await channel.send(embed=embed, view=view)

    # Keep the connection alive by sending message every 90 seconds
    while True:
        await asyncio.sleep(90)
        await message.edit(embed=embed, view=view)


class ModuleRequestModal(discord.ui.Modal):
    "x"
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.add_item(discord.ui.InputText(label="SS58 Address of the Module"))
        self.add_item(discord.ui.InputText(
            label="What your module does", style=discord.InputTextStyle.long))
        self.add_item(discord.ui.InputText(
            label="Module API docs", style=discord.InputTextStyle.long))
        self.add_item(discord.ui.InputText(
            label="Team Members (Developers of the Module)"))
        self.add_item(discord.ui.InputText(
            label="Repository Link (GitHub, GitLab, etc.)"))

    async def callback(self, interaction: discord.Interaction):

        user_id = interaction.user.id
        current_time = datetime.datetime.now()

        if user_id in last_submission_times:
            last_submission_time = last_submission_times[user_id]
            time_since_last_submission = current_time - last_submission_time

            if time_since_last_submission < datetime.timedelta(minutes=3600):
                remaining_time = datetime.timedelta(
                    minutes=3600) - time_since_last_submission
                await interaction.response.send_message(f"You can submit another module request in {remaining_time.seconds} seconds.", ephemeral=True)
                return

        embed = discord.Embed(title="Module Request",
                              color=discord.Color.green())
        embed.add_field(name="Submitted by",
                        value=interaction.user.mention, inline=False)
        embed.add_field(name="SS58 Address",
                        value=self.children[0].value, inline=False)
        embed.add_field(name="Module Description",
                        value=self.children[1].value, inline=False)
        embed.add_field(name="Endpoint Information",
                        value=self.children[2].value, inline=False)
        embed.add_field(name="Team Members",
                        value=self.children[3].value, inline=False)
        embed.add_field(name="Repository Link",
                        value=self.children[4].value, inline=False)

        # check if the ss58 address is valid
        if not is_ss58_address(self.children[0].value):
            await interaction.response.send_message("Invalid SS58 Address", ephemeral=True)
            return

        # check if repository link is valid
        if not validators.url(self.children[4].value):
            await interaction.response.send_message("Invalid Repository Link", ephemeral=True)
            return

        # check if the ss58 address is already submitted
        if self.children[0].value in request_ids:
            await interaction.response.send_message("Module request already submitted", ephemeral=True)
            return

        # key considered as the request id
        request_ids.append(self.children[0].value)

        # Update the last submission time for the user
        last_submission_times[user_id] = current_time

        # Send the embed to the specific channel
        channel_id = NOMINATOR_CHANNEL_ID
        channel = interaction.guild.get_channel(channel_id)
        await channel.send(embed=embed)

        # Respond to the interaction
        await interaction.response.send_message("Module request submitted successfully", ephemeral=True)


class ModuleRequestView(discord.ui.View):
    @discord.ui.button(label="Submit Module Request", style=discord.ButtonStyle.primary)
    async def submit_module_request(self, button: discord.ui.Button, interaction: discord.Interaction):
        modal = ModuleRequestModal(title="Submit Module Request")
        await interaction.response.send_modal(modal)


def main() -> None:
    BOT.run(BOT_TOKEN)
    return


main()
