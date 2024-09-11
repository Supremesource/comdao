
import asyncio
from os import getenv

import discord
from fastapi import FastAPI, Header, HTTPException, status, Depends
from pydantic import BaseModel

# for valid url
from typeguard import check_type
from .config.settings import (
    BOT,
    DISCORD_PARAMS,
    API_PARAMS,
    ROLE_ID,
)

from contextlib import asynccontextmanager


BOT_TOKEN = DISCORD_PARAMS.BOT_TOKEN
GUILD_ID = DISCORD_PARAMS.GUILD_ID
REQUEST_CHANNEL_ID = DISCORD_PARAMS.REQUEST_CHANNEL_ID
NOMINATOR_CHANNEL_ID = DISCORD_PARAMS.NOMINATOR_CHANNEL_ID


async def verify_token(x_token: str = Header(...)):
    token = API_PARAMS.TOKEN
    print(f"Correct: {token} given: {x_token}")
    if x_token != token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid api token"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting...")
    # ihatepythonihatepythonihatepythonihatepythonihatepythonihatepython
    asyncio.create_task(BOT.start(BOT_TOKEN))
    # gambiarra to wait for the bot connection
    await asyncio.sleep(5)
    yield

app = FastAPI(lifespan=lifespan)


@BOT.event
async def on_ready() -> None:
    print(f"{BOT.user} is now online!")


class ApplicationNotification(BaseModel):
    discord_uid: int
    application_url: str
    app_id: str


@app.post(
    "/notify_application",
    status_code=200,
    dependencies=[Depends(verify_token)]
)
async def notify_new_application(notification: ApplicationNotification):
    guild = BOT.get_guild(GUILD_ID)
    discord_user = guild.get_member(notification.discord_uid)  # type: ignore
    role = guild.get_role(ROLE_ID)  # type: ignore
    role = check_type(role, discord.Role)
    channel = await BOT.fetch_channel(REQUEST_CHANNEL_ID)  # as integer
    channel = check_type(channel, discord.channel.TextChannel)
    embed = discord.Embed(
        title="New Pending DAO Application",
        description="A new DAO application has been submitted",
        color=discord.Color.green()
    )

    embed.add_field(name="Application URL",
                    value=f"[Click here to view the application]({notification.application_url})", inline=False)
    embed.add_field(name="Applicant", value=discord_user.mention, inline=False)
    embed.add_field(name="Application ID",
                    value=notification.app_id, inline=False)

    embed.set_footer(
        text="Please review and discuss the application on our website.")
    mention = f"<@&{ROLE_ID}>"
    embed.set_thumbnail(url="https://i.imgur.com/U9izm50.png")
    await channel.send(content=mention, embed=embed)
    return {"message": "Application notification sent successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
