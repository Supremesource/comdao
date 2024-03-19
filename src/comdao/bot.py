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

from communex.types import Ss58Address
from communex.key import is_ss58_address

# constants
MNEMONICS = os.environ['MNEMONICS'].split(',')
BOT_TOKEN = os.environ['DISCORD_BOT_TOKEN']
GUILD_ID = str(os.environ['DISCORD_GUILD_ID'])
REQUEST_CHANNEL_ID = int(os.environ['REQUEST_CHANNEL_ID'])
NOMINATOR_CHANNEL_ID = int(os.environ['NOMINATOR_CHANNEL_ID'])

INTENTS = discord.Intents.default()
BOT = commands.Bot(command_prefix="/", intents=INTENTS)

# module request storage
request_ids: list[Ss58Address] = []
# discord_user_id : list[multisig_key_used, voted_ticket_id]
nomination_approvals: dict[str, list[tuple[Ss58Address, Ss58Address]]] = {}
last_submission_times = {}


def whitelist() -> list[Ss58Address]:
    # Get the whitelist from the blockchain
    # TODO: Implement this
    return []


def send_call(keypair: Keypair, call: dict) -> None:
    # Send the call to the blockchain
    print(f"Sending call {call} with keypair {keypair.ss58_address}")
    pass


def get_keys() -> tuple[list[Any], int]:  #  keypairs, threshold
    # Load the keypairs from enviroment variables
    signatories_count = len(MNEMONICS)
    assert signatories_count > 2, 'You need at least 3 private keys to run the bot'
    assert signatories_count % 3 == 0, 'The number of private keys must be a multiple of 3'
    threshold = int(signatories_count / 3) * 2
    keypairs = [Keypair.create_from_mnemonic(
        mnemonic) for mnemonic in MNEMONICS]
    return keypairs, threshold


keypairs, threshold = get_keys()


@BOT.event
async def on_ready() -> None:
    print(f"{BOT.user} is now online!")
    await setup_module_request_ui()


@BOT.slash_command(guild_ids=[GUILD_ID],  # !!! make sure to pass as string
                   description="Help command")
async def helpnominate(ctx) -> None:
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
    member_stats = defaultdict(
        lambda: {"participation_count": 0, "absence_count": 0})

    for user_id, approvals in nomination_approvals.items():
        member = await ctx.guild.fetch_member(user_id)
        if member:
            for multisig_key, _ in approvals:
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

    for member_id, stats in sorted_stats:
        member = await ctx.guild.fetch_member(member_id)
        if member:
            table += "| {:<25} | {:<30} | {:<25} |\n".format(
                member.name, stats['participation_count'], stats['absence_count'])

    table += "```"

    await ctx.respond(f"**Member Stats:**\n\n{table}", ephemeral=True)


@BOT.slash_command(guild_ids=[GUILD_ID],  # !!! make sure to pass as string
                   description="Nominates module to a whitelist.",
                   manage_roles=True)
async def nominate(ctx, module_key: str) -> None:
    if ctx.channel.id != NOMINATOR_CHANNEL_ID:
        await ctx.respond("This command can only be used in the designated channel.", ephemeral=True)
        return

    member = await ctx.guild.fetch_member(ctx.author.id)
    role = discord.utils.get(ctx.guild.roles, name="nominator")

    if role not in member.roles:
        await ctx.respond("You don't have the required role to use this command.", ephemeral=True)
        return

    if not is_ss58_address(module_key):
        await ctx.respond("Invalid module key.", ephemeral=True)
        return

    nominated_modules = [approval[1]
                         for approval in nomination_approvals.get(ctx.author.id, [])]
    if module_key in nominated_modules:
        await ctx.respond(f"You have already nominated {module_key}.", ephemeral=True)
        return

    if module_key not in request_ids:
        await ctx.respond(f"Module key {module_key} is not not submitted for access, open a request.", ephemeral=True)
        return

    signatores_addys = [keypair.ss58_address for keypair in keypairs]
    free_signatories = [signatory for signatory in signatores_addys if signatory not in [
        approval[0] for approval in nomination_approvals.get(ctx.author.id, [])]]
    current_addy = random.choice(free_signatories)
    current_keypair = [
        keypair for keypair in keypairs if keypair.ss58_address == current_addy][0]

    nomination_approvals.setdefault(
        ctx.author.id, []).append((current_addy, module_key))
    agreement_count: int = 0
    for _, approvals in nomination_approvals.items():
        for _, module in approvals:
            if module == module_key:
                agreement_count += 1

    onchain_message = "Multisig is now adding this module onchain, it will soon start getting votes." if agreement_count == threshold else "Still waiting for more votes, before executing onchain."

    await ctx.respond(f"Nominator {ctx.author.mention} accepted module `{module_key}`. This is the `{agreement_count}` agreement out of `{threshold}` threshold."
                      f"\n{onchain_message}")
    call = {
        "call_module": "SubspaceModule",
        "call_function": "add_to_whitelist",
        "call_args": {
            "module_key": module_key,
            "signatories": free_signatories,
            "threshold": threshold
        }
    }
    send_call(current_keypair, call)


@BOT.slash_command(guild_ids=[GUILD_ID],  # !!! make sure to pass as string
                   description="Removes module from a whitelist.",
                   manage_roles=True)
async def remove(ctx, module_key: str, reason: str) -> None:
    if ctx.channel.id != NOMINATOR_CHANNEL_ID:
        await ctx.respond("This command can only be used in the designated channel.", ephemeral=True)
        return

    member = await ctx.guild.fetch_member(ctx.author.id)
    role = discord.utils.get(ctx.guild.roles, name="nominator")

    if role not in member.roles:
        await ctx.respond("You don't have the required role to use this command.", ephemeral=True)
        return

    if not is_ss58_address(module_key):
        await ctx.respond("Invalid module key.", ephemeral=True)
        return

    current_whitelist = whitelist()

    if module_key not in current_whitelist:
        await ctx.respond(f"Module key {module_key} is not in a whitelist", ephemeral=True)
        return

    signatores_addys = [keypair.ss58_address for keypair in keypairs]
    free_signatories = [signatory for signatory in signatores_addys if signatory not in [
        approval[0] for approval in nomination_approvals.get(ctx.author.id, [])]]
    current_addy = random.choice(free_signatories)
    current_keypair = [
        keypair for keypair in keypairs if keypair.ss58_address == current_addy][0]

    nomination_approvals.setdefault(
        ctx.author.id, []).append((current_addy, module_key))
    agreement_count: int = 0
    for _, approvals in nomination_approvals.items():
        for _, module in approvals:
            if module == module_key:
                agreement_count += 1

    onchain_message = "Multisig is now removing this module onchain, it will be deleted from the whitelist soon." if agreement_count == threshold else "Still waiting for more votes, before executing onchain."

    await ctx.respond(f"Nominator {ctx.author.mention} accepted removal of module `{module_key}` for the reason of `{reason}`. This is the `{agreement_count}` agreement out of `{threshold}` threshold."
                      f"\n{onchain_message}")
    call = {
        "call_module": "SubspaceModule",
        "call_function": "remove_from_whitelist",
        "call_args": {
            "module_key": module_key,
            "reason": reason,
            "signatories": free_signatories,
            "threshold": threshold
        }
    }
    send_call(current_keypair, call)


async def setup_module_request_ui():
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
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.add_item(discord.ui.InputText(label="SS58 Address of the Module"))
        self.add_item(discord.ui.InputText(label="What your module does"))
        self.add_item(discord.ui.InputText(
            label="Module Endpoint Information"))
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
        channel_id = 1219329785344426189
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
