from dotenv import load_dotenv
import os
from dataclasses import dataclass
from pydantic_settings import BaseSettings
import discord
from discord.ext import commands


#load_dotenv()

class DiscordParams(BaseSettings):
    BOT_TOKEN: str
    GUILD_ID: int
    REQUEST_CHANNEL_ID: int
    NOMINATOR_CHANNEL_ID: int

    class Config:
        env_prefix = "DISCORD_"
        env_file = "env/dev.env"
        extra="ignore"


class Subspace(BaseSettings):
    MNEMONIC: str

    class Config:
        env_prefix = "SUBSPACE_"
        env_file = "env/dev.env"
        extra="ignore"


ROLE_NAME = "admin"
NODE_URL = "wss://testnet-commune-api-node-0.communeai.net"  # "wss://commune.api.onfinality.io/public-ws"
MODULE_SUBMISSION_DELAY = 3600
INTENTS = discord.Intents.all()
BOT = commands.Bot(command_prefix="/", intents=INTENTS)
MNEMONIC = Subspace().MNEMONIC # type: ignore
DISCORD_PARAMS = DiscordParams()



