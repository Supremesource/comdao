from typing import Iterable, Sized, TypeVar, Protocol, Iterator
import statistics
import html
import json

import discord
from communex.types import Ss58Address
from communex.key import is_ss58_address
from substrateinterface import Keypair
from typeguard import check_type

from ..db.cache import Cache, NominationVote, CACHE, save_state
from ..config.settings import MNEMONIC, ROLE_NAME
from ..config.application import Application
from .substrate_interface import send_call
from .substrate_interface import get_applications

from .ipfs import get_json_from_cid



T = TypeVar('T', covariant=True)
class SizedIterable(Protocol[T]):
    def __iter__(self) -> Iterator[T]:
        ...

    def __len__(self) -> int:
        ...



def get_new_pending_applications(cache: Cache) -> list[Application]:
    applications = get_applications()
    pending: list[Application] = []
    for app in applications.values():
        try:
            app_id = app["id"]
            app_status = app["status"]
            proposal_dict = get_json_from_cid(app["data"])
            if not proposal_dict:
                continue

            ss58_key = app["user_id"]
            assert is_ss58_address(ss58_key)
            application_obj = Application(
                discord_id=proposal_dict["discord_id"],
                title=proposal_dict["title"],
                body=json.dumps(proposal_dict["body"]),
                app_id=app_id, # type: ignore,
                app_key=ss58_key
            )
            if app_status.lower() == "pending":
                if app_id not in cache.dao_applications:
                    cache.dao_applications.append(app_id)
                    cache.request_ids.append(ss58_key)
                    pending.append(application_obj)
        except Exception as e:
            print(e)
            continue
    return pending


def get_votes_threshold(ctx: discord.ApplicationContext):
    guild = ctx.guild
    #guild = discord.Client().get_guild(919913039682220062)
    guild = check_type(guild, discord.Guild)
    nominators = discord.utils.get(guild.roles, name=ROLE_NAME)
    nominators = check_type(nominators, discord.Role)
    signatores_count = len(nominators.members)
    threshold = signatores_count // 2 + 1
    return threshold


def get_member_stats(
        members: SizedIterable[discord.Member],
        nomination_approvals: SizedIterable[str],
        removal_approvals: SizedIterable[str],
        rejection_approvals: SizedIterable[str],
    ):
    stats_data: list[tuple[discord.Member, int, int]] = []
    for member in members:
        multisig_participation_count = (
            sum(member.id == user_id for user_id in nomination_approvals)
            + sum(member.id == user_id for user_id in removal_approvals)
            + sum(member.id == user_id for user_id in rejection_approvals)
        )
        multisig_absence_count = (
            len(nomination_approvals)
            + len(removal_approvals)
            + len(rejection_approvals)
            - multisig_participation_count
        )
        stats_data.append(
            (member, multisig_participation_count, multisig_absence_count)
        )
    return stats_data


async def valid_for_approval(
        module_key: Ss58Address, cache: Cache,
        ctx: discord.ApplicationContext,
        ) -> bool:
    
    user_id = str(ctx.author.id)
    approvals_by_user = cache.nomination_approvals.get(user_id, [])
    modules_approved = [approval.module_key for approval in approvals_by_user]
    if module_key in modules_approved:
        await ctx.respond(f"You have already nominated `{module_key}`.", ephemeral=True)
        return False

    if module_key not in cache.request_ids:
        await ctx.respond(
            f"Module key `{module_key}` is not submitted for access, open a request.",
            ephemeral=True,
        )
        return False

    rejected_by_user = cache.rejection_approvals.get(user_id, [])
    if module_key in rejected_by_user:
        await ctx.respond(f"You have rejected `{module_key}` before.", ephemeral=True)
        return False
    return True


def add_approval_vote(
        cache: Cache, 
        user_id: str, 
        module_key: Ss58Address,
        recommended_weight: int
    ):
    with cache:
        approvals_by_user = cache.nomination_approvals.get(user_id, [])
        approvals_by_user.append(NominationVote(module_key, recommended_weight))
        cache.nomination_approvals[user_id] = approvals_by_user

        agreement_count = 0
        for votes in cache.nomination_approvals.values():
            for vote in votes:
                if vote.module_key == module_key:
                    agreement_count += 1
        
    return agreement_count


async def push_to_white_list(cache: Cache, module_key: Ss58Address):
    assert MNEMONIC is not None
    current_keypair = Keypair.create_from_mnemonic(MNEMONIC)
    # update the whitelist
    fn = "add_to_whitelist"
    recommended_weights: list[int] = []
    for user_approvals in cache.nomination_approvals.values():
        for user_vote in user_approvals:
            if user_vote.module_key == module_key:
                recommended_weights.append(user_vote.recommended_weight)

    weight = statistics.median(recommended_weights)
    call = {"module_key": module_key, "recommended_weight": weight}
    wlr = await send_call(fn, current_keypair, call)
    print(wlr)
    # Acquire the lock before modifying nomination_approvals
    with cache:
        cache.current_whitelist.append(module_key)
        for user_id in list(cache.nomination_approvals.keys()):
            cache.nomination_approvals[user_id].remove(module_key) # type: ignore
    print(f"Module {module_key} added to whitelist.")


async def valid_for_rejection(
        ctx: discord.ApplicationContext, 
        cache: Cache,
        module_key: str,
        reason: str,
    ) -> bool:
    
    user_id = str(ctx.author.id)
    module_key = html.escape(module_key.strip())
    if not is_ss58_address(module_key):
        await ctx.respond("Invalid module key.", ephemeral=True)
        return False
    
    reason = html.escape(reason.strip())
    if not reason:
        await ctx.respond(
            "Please provide a valid reason for rejection.", ephemeral=True
        )
        return False
    
    rejected_modules = cache.rejection_approvals.get(user_id, [])
    if module_key in rejected_modules:
        await ctx.respond(f"You have already rejected `{module_key}`.", ephemeral=True)
        return False
    
    return True


def add_rejection_vote(
        cache: Cache,
        user_id: str,
        module_key: Ss58Address,
    ):
    with cache:
        rejected_by_user = cache.rejection_approvals.get(user_id, [])
        rejected_by_user.append(module_key)
        cache.rejection_approvals[user_id] = rejected_by_user


async def valid_for_removal(
    ctx: discord.ApplicationContext,
    cache: Cache,
    module_key: str,
    user_id: str,
    reason: str,
) -> bool:
    if not is_ss58_address(module_key):
        await ctx.respond("Invalid module key.", ephemeral=True)
        return False
    
    if not reason:
        await ctx.respond("Please provide a valid reason for removal.", ephemeral=True)
        return False
    
    nominated = cache.removal_approvals.get(user_id, [])
    if module_key in nominated:
        await ctx.respond(
            f"You have already asked to remove `{module_key}`.", ephemeral=True
        )
        return False

    if module_key not in cache.current_whitelist:
        await ctx.respond(
            f"Module key `{module_key}` is not whitelisted", ephemeral=True
        )
        return False
    
    return True

def add_removal_vote(
    cache: Cache, 
    user_id: str, 
    module_key: Ss58Address
):
    agreement_count = 0
    with cache:
        removals = cache.removal_approvals.get(user_id, [])
        removals.append(module_key)
        cache.removal_approvals[user_id] = removals

        for removal_list in cache.removal_approvals.values():
            for module in removal_list:
                if module == module_key:
                    agreement_count += 1
    return agreement_count


async def pop_from_whitelist(cache: Cache, module_key: Ss58Address):
    assert MNEMONIC is not None
    current_keypair = Keypair.create_from_mnemonic(MNEMONIC)
    # update the whitelist
    fn = "remove_from_whitelist"
    call = {"module_key": module_key}
    await send_call(fn, current_keypair, call)
    with cache:
        cache.current_whitelist.remove(module_key)

if __name__ == "__main__":
#    applications = get_applications()
#    print(applications)
#    breakpoint()
    ths = get_votes_threshold("afsds")
    print(ths)