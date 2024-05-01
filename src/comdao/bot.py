import asyncio
import datetime
import html
import logging
import os
import re
from collections import defaultdict
from functools import wraps
from typing import Any, cast

import discord

# for valid url
from typeguard import check_type
from communex.client import CommuneClient
from communex.compat.key import classic_load_key
from communex.key import is_ss58_address
from communex.types import NetworkParams, Ss58Address
from discord.ext import commands
from substrateinterface import Keypair
from substrateinterface.base import ExtrinsicReceipt
from tabulate import tabulate

from .config.settings import (
    ROLE_NAME,
    NODE_URL,
    MODULE_SUBMISSION_DELAY,
    INTENTS,
    BOT,
    DISCORD_PARAMS,
    MNEMONIC
)
from .helpers.substrate_interface import whitelist, send_call
from .helpers.errors import on_application_command_error
from .helpers.domain_logic import (
    get_member_stats, 
    valid_for_approval, 
    add_approval_vote, 
    push_to_white_list,
    valid_for_rejection,
    add_rejection_vote,
    valid_for_removal,
    add_removal_vote,
    pop_from_whitelist,
    get_votes_threshold,
    get_pending_applications,
)
from .helpers.ui import ModuleRequestView
from .db.cache import CACHE

BOT_TOKEN = DISCORD_PARAMS.BOT_TOKEN
GUILD_ID = DISCORD_PARAMS.GUILD_ID
REQUEST_CHANNEL_ID = DISCORD_PARAMS.REQUEST_CHANNEL_ID
NOMINATOR_CHANNEL_ID = DISCORD_PARAMS.NOMINATOR_CHANNEL_ID


lock = asyncio.Lock()

# Set up logging

BOT.on_application_command_error = on_application_command_error

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
    await show_pending_applications()
    exit(0)


async def show_pending_applications():
    channel = await BOT.fetch_channel(REQUEST_CHANNEL_ID)  # as integer
    channel = check_type(channel, discord.channel.TextChannel)
    applications = get_pending_applications()
    embed = discord.Embed(title="New pending applications", color=discord.Color.nitro_pink())
    #headers = ["Application ID", "Applicant", "Data", "Cost"]
    #table_data: list[tuple[str, str, str, str]] = []
    for app_dict in applications:
        #row_data = (app_dict["id"], app_dict["user_id"], app_dict["data"], app_dict["application_cost"])
        application_id = app_dict["id"]
        applicant = app_dict["user_id"]
        data = app_dict["data"]
        cost = app_dict["application_cost"]
        
        embed.add_field(name=f"Application ID: {application_id}", value=f"Applicant: {applicant}", inline=False)
        embed.add_field(name="Data", value=data, inline=True)
        embed.add_field(name="Cost", value=cost, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=False)  # Empty field for spacing
        embed.add_field(name="\u200b", value="[0x818589]------------------------[/0x818589]", inline=False)  # Horizontal line
        #table_data.append(row_data)
    #table = tabulate(table_data, headers, tablefmt="grid")
    #await channel.send(f"```\n{table}\n```")
    await channel.send(embed=embed)


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
    name="stats"
)
@commands.cooldown(1, 10, commands.BucketType.user)
async def stats(ctx: discord.ApplicationContext) -> None:
    guild = ctx.guild
    assert guild
    role: discord.Role = discord.utils.get(guild.roles, name=ROLE_NAME)
    role = check_type(role, discord.Role)
    members = role.members
    stats_data = get_member_stats(
        members, 
        CACHE.nomination_approvals.keys(), 
        CACHE.removal_approvals.keys(), 
        CACHE.rejection_approvals.keys()
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
    name="approve",
)
@commands.has_role(ROLE_NAME)
@commands.cooldown(1, 60, commands.BucketType.user)
@in_nominator_channel()
async def approve(
    ctx: discord.ApplicationContext, 
    module_key: str,
    recommended_weight: int
    ) -> None:
    try:
        # Validate and sanitize the module_key input
        module_key = html.escape(module_key.strip())
        if not is_ss58_address(module_key):
            await ctx.respond("Invalid module key.", ephemeral=True)
            return
        if recommended_weight <= 0 or recommended_weight > 100:
            await ctx.respond(
                "Invalid recommended weight. It should be a value between 1 and 100.", 
                ephemeral=True
                )
            return

        user_id = str(ctx.author.id)
        guild = ctx.guild
        guild = check_type(guild, discord.Guild)
        role = discord.utils.get(guild.roles, name=ROLE_NAME)
        role = check_type(role, discord.Role)
        signatores_count = len(role.members)
        #threshold = signatores_count // 2 + 1
        threshold = 1


        valid = await valid_for_approval(module_key, CACHE, ctx)
        if not valid:
            return
        
        agreement_count = add_approval_vote(CACHE, user_id, module_key, recommended_weight)

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
        if agreement_count >= threshold:
            await push_to_white_list(CACHE, module_key)
    finally:
        print(CACHE.request_ids)
        CACHE.save_to_disk()

@BOT.slash_command(
    guild_ids=[GUILD_ID],  # ! make sure to pass as string
    description="Rejects module nomination.",
    manage_roles=True,
    name="reject"
)
@commands.has_role(ROLE_NAME)
@commands.cooldown(1, 60, commands.BucketType.user)
@in_nominator_channel()
async def reject(ctx: discord.ApplicationContext, module_key: str, reason: str) -> None:
    # Validate and sanitize the module_key input
    try:
        valid = await valid_for_rejection(ctx, CACHE, module_key, reason)
        if not valid:
            return

        # Acquire the lock before modifying rejection_approvals
        user_id = str(ctx.author.id)
        module_key = check_type(module_key, Ss58Address)
        add_rejection_vote(CACHE, user_id, module_key)
        await ctx.respond(
            f"{ctx.author.mention} is rejecting the module `{module_key}` for the reason: `{reason}`."
        )
    finally:
        CACHE.save_to_disk()

@BOT.slash_command(
    guild_ids=[GUILD_ID],  # ! make sure to pass as string
    description="Removes module from a whitelist.",
    manage_roles=True,
    name="remove"
)
@commands.has_role(ROLE_NAME)
@commands.cooldown(1, 60, commands.BucketType.user)
@in_nominator_channel()
async def remove(ctx: discord.ApplicationContext, module_key: str, reason: str) -> None:
    try:
        # Validate and sanitize the module_key input
        module_key = html.escape(module_key.strip())
        reason = html.escape(reason.strip())
        user_id = str(ctx.author.id)
        
        # threshold = get_votes_threshold(ctx)
        threshold = 1

        valid = await valid_for_removal(ctx, CACHE, module_key, user_id, reason)
        if not valid:
            return
        
        module_key = check_type(module_key, Ss58Address)
        agreement_count = add_removal_vote(CACHE, user_id, module_key)

        onchain_message = (
            "Multisig is now removing this module onchain, it will soon be removed."
            if agreement_count >= threshold
            else "Still waiting for more votes, before executing onchain."
        )

        await ctx.respond(
            f"Nominator {ctx.author.mention} asked to remove module `{module_key}`.\n"
            f"For the reason: `{reason}`.\n"
            f"This is the `{agreement_count}` agreement out of `{threshold}` threshold.\n"
            f"{onchain_message}"
        )

        if agreement_count >= threshold:
            await pop_from_whitelist(CACHE, module_key)
    finally:
        CACHE.save_to_disk()


async def setup_module_request_ui():
    channel = await BOT.fetch_channel(REQUEST_CHANNEL_ID)  # as integer
    channel = check_type(channel, discord.channel.TextChannel)
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



def main() -> None:
    # get the whitelist, so we don't have to query many times
    white = whitelist()
    CACHE.current_whitelist = white
    BOT.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
