from communex.client import CommuneClient
from communex.types import NetworkParams, Ss58Address
from substrateinterface import Keypair


from ..config.settings import (
    NODE_URL,
)


def whitelist() -> list[Ss58Address]:
    client = CommuneClient(NODE_URL)
    # Get the whitelist from the blockchain
    legit_whitelist: list[Ss58Address] = []
    query_result = client.query_map("LegitWhitelist", params=[], extract_value=False)
    if query_result:
        legit_whitelist = list(
            (
                client.query_map("LegitWhitelist", params=[], extract_value=False)["LegitWhitelist"]
            ).keys()
        )
    return legit_whitelist



async def send_call(fn: str, keypair: Keypair, call: dict):
    # Send the call to the blockchain
    client = CommuneClient(NODE_URL)
    response = client.compose_call(fn=fn, params=call, key=keypair)
    print(f"response of the function {fn} is {response}")
    return response
