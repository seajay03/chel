from __future__ import annotations

"""Entry point for the Coach Rosterbator Discord bot."""

import os
import discord
from discord.ext import commands

from . import config


class CoachBot(commands.Bot):
    """Basic bot skeleton with a health check command."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        guild_obj = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild_obj)
        await self.tree.sync(guild=guild_obj)


bot = CoachBot()


@bot.tree.command(description="Health check")
async def ping(interaction: discord.Interaction) -> None:
    """Simple ping command to verify the bot is responsive."""

    await interaction.response.send_message("Pong!", ephemeral=True)


def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN not set")
    bot.run(token)


if __name__ == "__main__":  # pragma: no cover - manual execution only
    main()
