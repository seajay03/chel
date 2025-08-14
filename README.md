# Coach Rosterbator

Early scaffold for a Discord bot that manages ice-hockey lineups and practice lobbies.

## Development

1. Create a virtual environment and install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and set `DISCORD_TOKEN`.
3. Run the bot:

   ```bash
   python -m rosterbator.bot
   ```

Commands are automatically scoped to the configured guild and a simple `/ping` command is available to verify the bot is online.
