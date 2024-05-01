from typing import Any
from communex.types import Ss58Address
from pydantic import BaseModel

class Application(BaseModel):
    discord_id: str
    app_id: int
    title: str
    body: str
    app_key: Ss58Address