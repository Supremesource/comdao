import asyncio
import html
from functools import wraps
from typing import Any, cast

import discord
from discord.ext import tasks
from discord import Option

# for valid url
from typeguard import check_type
from communex.key import is_ss58_address
from communex.types import Ss58Address
from discord.ext import commands
from comdao.helpers.substrate_interface import refuse_dao_application
from tabulate import tabulate

from .config.settings import (
    ROLE_NAME,
    BOT,
    DISCORD_PARAMS,
    ROLE_ID,
)
from .helpers.substrate_interface import whitelist
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
    build_application_embeds,
)
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
    show_pending_applications.start()


@tasks.loop(seconds=600)
async def show_pending_applications():
    channel = await BOT.fetch_channel(REQUEST_CHANNEL_ID)  # as integer
    channel = check_type(channel, discord.channel.TextChannel)
    guild = BOT.get_guild(GUILD_ID)
    assert guild
    markdown, discord_uid = build_application_embeds(CACHE, guild)
    # means that we have a new application to be displayed
    if markdown and discord_uid is not None:
        role = guild.get_role(ROLE_ID)
        role = check_type(role, discord.Role)
        reply_message = (
            "Please use the commands `/approve` or `/reject` to vote. "
            "If the propposal is accepted, " 
            "the module will be added to the DAO whitelist "
            "and will be eligible to register on the subnet 0."

        )

        discord_user = guild.get_member(int(discord_uid))

        if discord_user is not None:
            overwrites = channel.overwrites # type: ignore just one more ignore bro
            overwrites[discord_user] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            await channel.edit(overwrites=overwrites) # type: ignore I HATE pycord
        sent_message: discord.Message = await channel.send(markdown) # type: ignore
        await sent_message.reply(role.mention + "\n" + reply_message)
    with CACHE:
        CACHE.save_to_disk()

@BOT.slash_command(
    guild_ids=[GUILD_ID], description="Help command"  # ! make sure to pass as string
)
@commands.cooldown(1, 10, commands.BucketType.user)
async def help(ctx) -> None:
    help_message = """🚀 **Commune DAO Commands:**
1. `/approve <ss58 key> <recommended_weight (int 1 ~ 100)>` - Approves a module for whitelist and sets the weight as the median of the weights passed on votes.
2. `/reject <ss58 key> <reason>` - Rejects a module approval.
3. `/remove <ss58 key> <reason>` - Vote to remove a module from the whitelist. 
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
    #role: discord.Role = discord.utils.get(guild.roles, name=ROLE_NAME)
    role = guild.get_role(ROLE_ID)
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
@commands.has_role(ROLE_ID)
@commands.cooldown(1, 60, commands.BucketType.user)
@in_nominator_channel()
async def approve(
    ctx: discord.ApplicationContext, 
    application_id: Option(int, description="The ID of the application"),
    recommended_weight: Option(int, description="Between 1 and 100"),
    ) -> None:
    # Validate and sanitize the module_key input
    if recommended_weight <= 0 or recommended_weight > 100:
        await ctx.respond(
            "Invalid recommended weight. It should be a value between 1 and 100.", 
            ephemeral=True
            )
        return
    curr_app = CACHE.app_being_voted
    if not curr_app or curr_app[0].app_id != application_id:
        await ctx.respond("Invalid application id.", ephemeral=True)
        return
    application_key = curr_app[0].app_key

    user_id = str(ctx.author.id)
    threshold = get_votes_threshold(ctx)
    #threshold = 1

    valid = await valid_for_approval(application_key, CACHE, ctx)
    if not valid:
        return
    
    guild = ctx.guild
    assert guild
    role = guild.get_role(ROLE_ID)
    role = check_type(role, discord.Role)
    discord_user = guild.get_member(int(CACHE.applicator_discord_id))
    agreement_count = add_approval_vote(CACHE, user_id, application_key, recommended_weight)

    onchain_message = (
        "Multisig is now adding this module onchain, it will soon start getting votes."
        if agreement_count == threshold
        else "Still waiting for more votes, before executing onchain."
    )

    await ctx.respond(
        f"Nominator {ctx.author.mention} accepted module `{application_key}`.\n"
        f"This is the `{agreement_count}` agreement out of `{threshold}` threshold.\n"
        f"{onchain_message}"
    )
    if agreement_count >= threshold:
        await push_to_white_list(CACHE, application_key)
        CACHE.app_being_voted = None
        CACHE.app_being_voted_age = 0
        if discord_user is not None:
            overwrites = ctx.channel.overwrites # type: ignore just one more ignore bro
            overwrites[discord_user] = discord.PermissionOverwrite(read_messages=False, send_messages=False)
            await ctx.channel.edit(overwrites=overwrites) # type: ignore I HATE pycord
    CACHE.save_to_disk()

@BOT.slash_command(
    guild_ids=[GUILD_ID],  # ! make sure to pass as string
    description="Rejects module nomination.",
    manage_roles=True,
    name="reject"
)
@commands.has_role(ROLE_ID)
@commands.cooldown(1, 60, commands.BucketType.user)
@in_nominator_channel()
async def reject(
    ctx: discord.ApplicationContext, 
    module_id: Option(int, description="The id of the application"), 
    reason: Option(str, description="The reason of the reffusal"),
    ) -> None:
    # Validate and sanitize the module_key input
    valid = await valid_for_rejection(ctx, CACHE, module_id, reason)
    if not valid:
        return

    # Acquire the lock before modifying rejection_approvals
    user_id = str(ctx.author.id)
    rejection_count = add_rejection_vote(CACHE, user_id, module_id)
    await ctx.respond(
        f"{ctx.author.mention} is rejecting the module `{module_id}` for the reason: `{reason}`."
    )
    guild = ctx.guild
    assert guild
    role = guild.get_role(ROLE_ID)
    role = check_type(role, discord.Role)
    discord_user = guild.get_member(int(CACHE.applicator_discord_id))
    threshold = get_votes_threshold(ctx)
    if rejection_count >= threshold:
        refuse_dao_application(module_id)
        CACHE.app_being_voted = None
        CACHE.app_being_voted_age = 0
        if discord_user is not None:
            overwrites = ctx.channel.overwrites # type: ignore just one more ignore bro
            overwrites[discord_user] = discord.PermissionOverwrite(read_messages=False, send_messages=False)
            await ctx.channel.edit(overwrites=overwrites) # type: ignore I HATE pycord


    CACHE.save_to_disk()

@BOT.slash_command(
    guild_ids=[GUILD_ID],  # ! make sure to pass as string
    description="Removes module from a whitelist.",
    manage_roles=True,
    name="remove"
)
@commands.has_role(ROLE_ID)
@commands.cooldown(1, 60, commands.BucketType.user)
@in_nominator_channel()
async def remove(ctx: discord.ApplicationContext, module_key: str, reason: str) -> None:

    # Validate and sanitize the module_key input
    module_key = html.escape(module_key.strip())
    reason = html.escape(reason.strip())
    user_id = str(ctx.author.id)
    
    threshold = get_votes_threshold(ctx)
    #threshold = 1

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

    CACHE.save_to_disk()



def main() -> None:
    # get the whitelist, so we don't have to query many times
    white = whitelist()
    CACHE.current_whitelist = white
    print(f"WHITELIST: {CACHE.current_whitelist}")
    BOT.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
