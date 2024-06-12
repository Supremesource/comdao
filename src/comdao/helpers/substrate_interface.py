from communex.client import CommuneClient
from communex.types import Ss58Address
from substrateinterface import Keypair
from communex.compat.key import classic_load_key

from communex._common import get_node_url

from ..config.settings import (
    USE_TESTNET, MNEMONIC
)


def whitelist() -> list[Ss58Address]:
    node_url = get_node_url(use_testnet=USE_TESTNET)
    client = CommuneClient(node_url)
    # Get the whitelist from the blockchain
    legit_whitelist: list[Ss58Address] = []
    query_result = client.query_map(
        "LegitWhitelist", 
        params=[], 
        extract_value=False,
        module="GovernanceModule",
    )

    if query_result:
        legit_whitelist = list(query_result["LegitWhitelist"].keys())
    return legit_whitelist



async def send_call(
        fn: str, 
        keypair: 
        Keypair, 
        call: dict,
        module: str = "GovernanceModule"
    ):
    # Send the call to the blockchain
    node_url = get_node_url(use_testnet=USE_TESTNET)
    client = CommuneClient(node_url)
    response = client.compose_call(
        fn=fn, 
        params=call, 
        key=keypair,
        module=module
    )
    print(f"response of the function {fn} is {response}")
    return response


def get_applications() -> dict[str, dict[str, str]]:
    node_url = get_node_url(use_testnet=USE_TESTNET)
    client = CommuneClient(node_url)
    query_result = client.query_map(
        "CuratorApplications", 
        params=[], 
        extract_value=False,
        module="GovernanceModule"
    )
    applications = query_result.get("CuratorApplications", {})
    return applications


def add_dao_application():
    node_url = get_node_url(use_testnet=USE_TESTNET)
    client = CommuneClient(node_url)
    key = classic_load_key("dev01")
    key2 = classic_load_key("dev02")
    params = {
        "application_key": key2.ss58_address, 
        "data": "QmR8X62PpEMtEik3cYq6VQ2Ug7YRZCqEqTXeHEVXp6zyem"
    }
    fn = "add_dao_application"
    query_result = client.compose_call(
        fn, 
        params=params, 
        key=key,
        module="GovernanceModule"
    )


def refuse_dao_application(app_id: int):
    node_url = get_node_url(use_testnet=USE_TESTNET)
    client = CommuneClient(node_url)
    current_keypair = Keypair.create_from_mnemonic(MNEMONIC)
    fn = "refuse_dao_application"
    params = {"id": app_id}
    query_result = client.compose_call(
        fn, 
        params=params, 
        key=current_keypair,
        module="GovernanceModule"
    )
    return query_result
    


if __name__ == "__main__":
    # print(NODE_URL)
    # wl = get_applications()
    # print(wl)
    # refuse_dao_application(8)
    # add_dao_application()
    wl = whitelist()
    print(wl)