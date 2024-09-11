import discord
from discord.ext import commands
from ..config.loggers import LOGGER


async def on_application_command_error(
    context: discord.ApplicationContext, exception: discord.DiscordException
):
    if isinstance(exception, commands.CommandOnCooldown):
        retry_after = round(exception.retry_after, 2)
        await context.respond(
            f"You are on cooldown. Please try again in {retry_after} seconds.",
            ephemeral=True,
        )
    elif isinstance(exception, commands.CheckFailure):
        await context.respond(
            "You do not have the required permissions to use this command.",
            ephemeral=True,
        )
    elif isinstance(exception, discord.HTTPException):
        LOGGER.error(f"HTTP Exception: {exception}")
        await context.respond(
            "An error occurred while processing your request. Please try again later.",
            ephemeral=True,
        )
    elif isinstance(exception, discord.Forbidden):
        LOGGER.error(f"Forbidden: {exception}")
        await context.respond(
            "The bot does not have the necessary permissions to perform this action.",
            ephemeral=True,
        )
    else:
        LOGGER.error(f"Unhandled exception: {exception}")
        await context.respond(
            "An unexpected error occurred. Please contact the bot administrator.",
            ephemeral=True,
        )
        # Raise the error for further investigation
        raise exception
