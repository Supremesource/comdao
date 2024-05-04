from typing import Any
import requests


def get_json_from_cid(cid: str) -> dict[Any, Any] | None:
    cid = cid.split("ipfs://")[-1]
    gateway = "https://ipfs.io/ipfs/"
    try:
        result = requests.get(gateway + cid)
        if result.ok:
            return result.json()
        return None
    except Exception as e:
        return None

if __name__ == "__main__":
    #result = get_json_from_cid("QmPLgRGEcDbDJCmocM91yes6iBg49QvC7qdQcvRb4vVSMX")
    result = get_json_from_cid("QmR8X62PpEMtEik3cYq6VQ2Ug7YRZCqEqTXeHEVXp6zyem")
    breakpoint()



    # {'discord_id': '919913039682220062', 'title': 'test', 'body': "# Plz accept my"}    