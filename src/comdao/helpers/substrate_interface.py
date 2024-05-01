from communex.client import CommuneClient
from communex.types import NetworkParams, Ss58Address
from substrateinterface import Keypair
from communex.compat.key import classic_load_key
import json


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


def get_applications() -> dict[str, dict[str, str]]:
    client = CommuneClient(NODE_URL)
    query_result = client.query_map("CuratorApplications", params=[], extract_value=False)
    applications = query_result.get("CuratorApplications", {})
    return applications


def add_dao_application():
    client = CommuneClient(NODE_URL)
    key = classic_load_key("dev01")
    key2 = classic_load_key("dev02")
    params = {
        "application_key": key2.ss58_address, 
        "data": json.dumps({"testing": "json"})
    }
    fn = "add_dao_application"
    query_result = client.compose_call(fn, params=params, key=key)


def refuse_dao_application():
    client = CommuneClient(NODE_URL)
    key = classic_load_key("dev01")
    fn = "refuse_dao_application"
    params = {"id": 0}
    query_result = client.compose_call(fn, params=params, key=key)
    breakpoint()

    


if __name__ == "__main__":
    get_applications()
