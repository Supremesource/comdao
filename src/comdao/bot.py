import asyncio
import datetime
import html
import logging
import os
import re
from collections import defaultdict
from functools import wraps
from typing import Any

import discord

# for valid url
import validators
from communex.client import CommuneClient
from communex.compat.key import classic_load_key
from communex.key import is_ss58_address
from communex.types import NetworkParams, Ss58Address
from discord.ext import commands
from dotenv import load_dotenv
from substrateinterface import Keypair
from substrateinterface.base import ExtrinsicReceipt
from tabulate import tabulate

# constants
load_dotenv()

MNEMONIC = os.getenv("MNEMONIC")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")
REQUEST_CHANNEL_ID = int(os.getenv("DISCORD_REQUEST_CHANNEL_ID", 0))
NOMINATOR_CHANNEL_ID = int(os.getenv("DISCORD_NOMINATOR_CHANNEL_ID", 0))

ROLE_NAME = "nominator"
NODE_URL = "ws://127.0.0.1:9944"  # "wss://commune.api.onfinality.io/public-ws"
MODULE_SUBMISSION_DELAY = 3600

INTENTS = discord.Intents.all()
BOT = commands.Bot(command_prefix="/", intents=INTENTS)

# module request storage
request_ids: list[Ss58Address] = []
# discord_user_id : voted_ticket_id
nomination_approvals: dict[str, list[Ss58Address]] = {}
removal_approvals: dict[str, list[Ss58Address]] = {}
rejection_approvals: dict[str, list[Ss58Address]] = {}
last_submission_times = {}

lock = asyncio.Lock()

# Set up logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("discord_bot")

# == Blockchain Communication ==


async def whitelist() -> list[Ss58Address]:
    client = CommuneClient(NODE_URL)
    # Get the whitelist from the blockchain
    # TODO: Implement this
    legit_whitelist = client.query("LegitWhitelist", params=[])
    return legit_whitelist


async def send_call(fn: str, keypair: Keypair, call: dict) -> None:
    # Send the call to the blockchain
    client = CommuneClient(NODE_URL)
    response = client.compose_call(fn=fn, params=call, key=keypair)
    print(f"response of the function {fn} is {response}")
    return response


# == Decorators ==


def has_required_role():
    def decorator(func):
        @wraps(func)
        async def wrapper(ctx: Any, *args, **kwargs):
            role = discord.utils.get(ctx.guild.roles, name=ROLE_NAME)
            if role not in ctx.author.roles:
                await ctx.respond(
                    "You do not have the required permissions to use this command.",
                    ephemeral=True,
                )
                return
            return await func(ctx, *args, **kwargs)

        return wrapper

    return decorator


def in_nominator_channel():
    def decorator(func):
        @wraps(func)
        async def wrapper(ctx: Any, *args, **kwargs):
            if ctx.channel.id != NOMINATOR_CHANNEL_ID:
                await ctx.respond(
                    "This command can only be used in the designated channel.",
                    ephemeral=True,
                )
                return
            return await func(ctx, *args, **kwargs)

        return wrapper

    return decorator


# == Discord Bot ==


@BOT.event
async def on_ready() -> None:
    print(f"{BOT.user} is now online!")
    await setup_module_request_ui()


@BOT.event
async def on_application_command_error(
    ctx: discord.ApplicationContext, error: discord.ApplicationCommandError
):
    if isinstance(error, commands.CommandOnCooldown):
        retry_after = round(error.retry_after, 2)
        await ctx.respond(
            f"You are on cooldown. Please try again in {retry_after} seconds.",
            ephemeral=True,
        )
    elif isinstance(error, commands.CheckFailure):
        await ctx.respond(
            "You do not have the required permissions to use this command.",
            ephemeral=True,
        )
    elif isinstance(error, discord.HTTPException):
        logger.error(f"HTTP Exception: {error}")
        await ctx.respond(
            "An error occurred while processing your request. Please try again later.",
            ephemeral=True,
        )
    elif isinstance(error, discord.Forbidden):
        logger.error(f"Forbidden: {error}")
        await ctx.respond(
            "The bot does not have the necessary permissions to perform this action.",
            ephemeral=True,
        )
    else:
        logger.error(f"Unhandled exception: {error}")
        await ctx.respond(
            "An unexpected error occurred. Please contact the bot administrator.",
            ephemeral=True,
        )
        # Raise the error for further investigation
        raise error


@BOT.slash_command(
    guild_ids=[GUILD_ID], description="Help command"  # ! make sure to pass as string
)
@commands.cooldown(1, 10, commands.BucketType.user)
async def help(ctx) -> None:
    help_message = """🚀 **Commune DAO Commands:**
1. `/approve <ss58 key>` - Approves a module for whitelist.
2. `/remove <ss58 key> <reason>` - Removes a module from the whitelist. 
3. `/reject <ss58 key> <reason>` - Rejects a module approval.
4. `/stats` - Lists a table of members and their `multisig_participation_count` and `multisig_abscence_count`, ranked by participation.
5. `/help` - Displays this help message.

📝 **Note:** Replace `<parameter>` with the appropriate value when using the commands."""

    await ctx.respond(help_message, ephemeral=True)


@BOT.slash_command(
    guild_ids=[GUILD_ID],  # ! make sure to pass as string
    description="Lists member stats based on multisig participation.",
)
@commands.cooldown(1, 10, commands.BucketType.user)
async def stats(ctx: Any) -> None:
    role = discord.utils.get(ctx.guild.roles, name=ROLE_NAME)
    members = role.members
    stats_data = []
    for member in members:
        multisig_participation_count = sum(
            member.id == user_id for user_id in nomination_approvals.keys()
        ) + sum(member.id == user_id for user_id in removal_approvals.keys())
        multisig_absence_count = (
            len(nomination_approvals)
            + len(removal_approvals)
            - multisig_participation_count
        )
        stats_data.append(
            (member, multisig_participation_count, multisig_absence_count)
        )

    # Sort the stats data based on multisig participation count in descending order
    stats_data.sort(key=lambda x: x[1], reverse=True)

    # Create a table using tabulate
    headers = ["Member", "Multisig Participation Count", "Multisig Absence Count"]
    table_data = [
        (member.display_name, participation_count, absence_count)
        for member, participation_count, absence_count in stats_data
    ]
    table = tabulate(table_data, headers, tablefmt="grid")
    await ctx.respond(f"```\n{table}\n```", ephemeral=True)


@BOT.slash_command(
    guild_ids=[GUILD_ID],  # ! make sure to pass as string
    description="Approves module to a whitelist.",
    manage_roles=True,
)
@has_required_role()
@commands.cooldown(1, 60, commands.BucketType.user)
@in_nominator_channel()
async def approve(ctx: Any, module_key: str) -> None:
    # Validate and sanitize the module_key input
    module_key = html.escape(module_key.strip())
    if not re.match(r"^[a-zA-Z0-9]+$", module_key):
        await ctx.respond(
            "Invalid module key. Only alphanumeric characters are allowed.",
            ephemeral=True,
        )
        return

    signatores_count = len(discord.utils.get(ctx.guild.roles, name=ROLE_NAME).members)
    threshold = signatores_count // 2 + 1

    if not is_ss58_address(module_key):
        await ctx.respond("Invalid module key.", ephemeral=True)
        return

    nominated_modules = [
        approval[1] for approval in nomination_approvals.get(ctx.author.id, [])
    ]
    if module_key in nominated_modules:
        await ctx.respond(f"You have already nominated `{module_key}`.", ephemeral=True)
        return

    if module_key not in request_ids:
        await ctx.respond(
            f"Module key `{module_key}` is not submitted for access, open a request.",
            ephemeral=True,
        )
        return

    current_whitelist = await whitelist()
    if module_key in current_whitelist:
        await ctx.respond(
            f"Module key `{module_key}` is already whitelisted", ephemeral=True
        )
        return

    # make sure the author hasn't rejected the module before
    rejected_modules = [
        approval[1] for approval in rejection_approvals.get(ctx.author.id, [])
    ]

    if module_key in rejected_modules:
        await ctx.respond(f"You have rejected `{module_key}` before.", ephemeral=True)
        return

    # Acquire the lock before modifying nomination_approvals
    async with lock:
        nomination_approvals[ctx.author.id] = nomination_approvals.get(
            ctx.author.id, []
        ) + [(ctx.author.id, module_key)]

    agreement_count = sum(
        module == module_key
        for approvals in nomination_approvals.values()
        for _, module in approvals
    )
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
        await send_call(fn, current_keypair, call)

        # Acquire the lock before modifying nomination_approvals
        async with lock:
            for user_id in list(nomination_approvals.keys()):
                nomination_approvals[user_id] = [
                    approval
                    for approval in nomination_approvals[user_id]
                    if approval[1] != module_key
                ]


@BOT.slash_command(
    guild_ids=[GUILD_ID],  # ! make sure to pass as string
    description="Rejects module nomination.",
    manage_roles=True,
)
@has_required_role()
@commands.cooldown(1, 60, commands.BucketType.user)
@in_nominator_channel()
async def reject(ctx: Any, module_key: str, reason: str) -> None:
    # Validate and sanitize the module_key input
    module_key = html.escape(module_key.strip())
    if not re.match(r"^[a-zA-Z0-9]+$", module_key):
        await ctx.respond(
            "Invalid module key. Only alphanumeric characters are allowed.",
            ephemeral=True,
        )
        return

    # Validate and sanitize the reason input
    reason = html.escape(reason.strip())
    if not reason:
        await ctx.respond(
            "Please provide a valid reason for rejection.", ephemeral=True
        )
        return

    # Make sure that the author hasn't rejected the module before
    rejected_modules = [
        approval[1] for approval in rejection_approvals.get(ctx.author.id, [])
    ]

    if module_key in rejected_modules:
        await ctx.respond(f"You have already rejected `{module_key}`.", ephemeral=True)
        return

    # Acquire the lock before modifying rejection_approvals
    async with lock:
        rejection_approvals[ctx.author.id] = rejection_approvals.get(
            ctx.author.id, []
        ) + [(ctx.author.id, module_key)]

    await ctx.respond(
        f"{ctx.author.mention} is rejecting the module `{module_key}` for the reason: `{reason}`."
    )


@BOT.slash_command(
    guild_ids=[GUILD_ID],  # ! make sure to pass as string
    description="Removes module from a whitelist.",
    manage_roles=True,
)
@has_required_role()
@commands.cooldown(1, 60, commands.BucketType.user)
@in_nominator_channel()
async def remove(ctx: Any, module_key: str, reason: str) -> None:
    # Validate and sanitize the module_key input
    module_key = html.escape(module_key.strip())
    if not re.match(r"^[a-zA-Z0-9]+$", module_key):
        await ctx.respond(
            "Invalid module key. Only alphanumeric characters are allowed.",
            ephemeral=True,
        )
        return

    # Validate and sanitize the reason input
    reason = html.escape(reason.strip())
    if not reason:
        await ctx.respond("Please provide a valid reason for removal.", ephemeral=True)
        return

    signatores_count = len(discord.utils.get(ctx.guild.roles, name=ROLE_NAME).members)
    threshold = signatores_count // 2 + 1

    if not is_ss58_address(module_key):
        await ctx.respond("Invalid module key.", ephemeral=True)
        return

    nominated_modules = [
        approval[1] for approval in removal_approvals.get(ctx.author.id, [])
    ]
    if module_key in nominated_modules:
        await ctx.respond(
            f"You have already asked to remove `{module_key}`.", ephemeral=True
        )
        return

    current_whitelist = await whitelist()
    if module_key not in current_whitelist:
        await ctx.respond(
            f"Module key `{module_key}` is not whitelisted", ephemeral=True
        )
        return

    agreement_count = (
        1  # Start with 1 since the current user is asking to remove the module
    )
    for approvals in removal_approvals.values():
        for _, module in approvals:
            if module == module_key:
                agreement_count += 1

    onchain_message = (
        "Multisig is now removing this module onchain, it will soon be removed."
        if agreement_count == threshold
        else "Still waiting for more votes, before executing onchain."
    )

    # Acquire the lock before modifying removal_approvals
    async with lock:
        removal_approvals[ctx.author.id] = removal_approvals.get(ctx.author.id, []) + [
            (ctx.author.id, module_key)
        ]

    await ctx.respond(
        f"Nominator {ctx.author.mention} asked to remove module `{module_key}`.\n"
        f"For the reason: `{reason}`.\n"
        f"This is the `{agreement_count}` agreement out of `{threshold}` threshold.\n"
        f"{onchain_message}"
    )

    if agreement_count == threshold:
        current_keypair = Keypair.create_from_mnemonic(MNEMONIC)
        fn = "remove_from_whitelist"
        call = {"module_key": module_key}
        await send_call(fn, current_keypair, call)

        # Acquire the lock before modifying nomination_approvals
        async with lock:
            for user_id in list(nomination_approvals.keys()):
                nomination_approvals[user_id] = [
                    approval
                    for approval in nomination_approvals[user_id]
                    if approval[1] != module_key
                ]


async def setup_module_request_ui():
    channel = BOT.get_channel(REQUEST_CHANNEL_ID)  # as integer

    embed = discord.Embed(
        title="Submit Module Request To Subnet Zero",
        description="Click the button below to submit a module request. \n"
        "For further information visit: "
        "[Subnet Zero Consensus Explination](https://github.com/Supremesource/comdao/tree/main)\n"
        "For registration docs on other subnets follow: [Docs](https://docs.communex.ai/communex)",
        color=discord.Color(0xFF69B4),
    )
    embed.set_thumbnail(url="https://commune-t.pages.dev/gif/cubes/pink_small.gif")

    view = ModuleRequestView()
    message = await channel.send(embed=embed, view=view)

    # Keep the connection alive by sending message every 90 seconds
    while True:
        await asyncio.sleep(90)
        await message.edit(embed=embed, view=view)


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
        user_id = interaction.user.id
        current_time = datetime.datetime.now()

        if user_id in last_submission_times:
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

        # Validate repository link
        if not validators.url(repository_link):
            await interaction.response.send_message(
                "Invalid Repository Link", ephemeral=True
            )
            return

        # Check if the SS58 address is already submitted
        if ss58_address in request_ids:
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
        request_ids.append(ss58_address)

        # Update the last submission time for the user
        last_submission_times[user_id] = current_time

        # Send the embed to the specific channel
        channel_id = NOMINATOR_CHANNEL_ID
        channel = interaction.guild.get_channel(channel_id)
        await channel.send(embed=embed)

        # Respond to the interaction
        await interaction.response.send_message(
            "Module request submitted successfully", ephemeral=True
        )


class ModuleRequestView(discord.ui.View):
    @discord.ui.button(label="Submit Module Request", style=discord.ButtonStyle.primary)
    async def submit_module_request(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ) -> None:
        modal = ModuleRequestModal(title="Submit Module Request")
        await interaction.response.send_modal(modal)


def main() -> None:
    BOT.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
