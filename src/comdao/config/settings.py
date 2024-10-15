from dotenv import load_dotenv
import os
from dataclasses import dataclass
from pydantic_settings import BaseSettings
import discord
from discord.ext import commands
from communex._common import get_node_url
# load_dotenv()


class DiscordParams(BaseSettings):
    BOT_TOKEN: str
    GUILD_ID: str
    REQUEST_CHANNEL_ID: str
    NOMINATOR_CHANNEL_ID: str
    ROLE_ID: str

    class Config:
        env_prefix = "DISCORD_"
        env_file = "env/dev.env"
        extra = "ignore"


class Subspace(BaseSettings):
    MNEMONIC: str

    class Config:
        env_prefix = "SUBSPACE_"
        env_file = "env/dev.env"
        extra = "ignore"


class APIParams(BaseSettings):
    TOKEN: str

    class Config:
        env_prefix = "API_"
        env_file = "env/dev.env"
        extra = "ignore"


ROLE_NAME = "dao-member"
USE_TESTNET = True
MODULE_SUBMISSION_DELAY = 3600
INTENTS = discord.Intents.all()
BOT = commands.Bot(command_prefix="/", intents=INTENTS)
MNEMONIC = Subspace().MNEMONIC  # type: ignore
DISCORD_PARAMS = DiscordParams()  # type: ignore
API_PARAMS = APIParams()  # type: ignore
ROLE_ID = DISCORD_PARAMS.ROLE_ID
