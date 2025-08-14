# coach_rosterbater.py
# Full Coach Rosterbator implementation (reaction-based replacements, UTIL logic,
# scheduling timeline, persistent storage, coach quote usage).
#
# Put .env (DISCORD_TOKEN=...) in the same folder.
# Put coachisms in data/coachisms.txt (we already added earlier).
#
# Install deps: pip install -U discord.py python-dotenv python-dateutil

import os
import json
import asyncio
import random
from datetime import datetime, timedelta, timezone
from dateutil import parser as dtparser
from zoneinfo import ZoneInfo  # Python 3.9+
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# --- CONFIG ---
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("ERROR: DISCORD_TOKEN not found in .env")
    raise SystemExit(1)

LINEUP_CHANNEL_ID = 1403600024927076407
GENERAL_CHANNEL_ID = 1228418184403615796

# file storage
STORAGE_FILE = "storage.json"
COACHISMS_FILE = "data/coachisms.txt"

# Claim emoji
CLAIM_EMOJI = "✅"

# Timezone — always use Eastern
NY = ZoneInfo("America/New_York")

# Posting intervals (seconds)
POST_2D_THRESHOLD = 48 * 3600  # 48h
POST_1D_THRESHOLD = 24 * 3600  # 24h
POST_T_MINUS_2H = 2 * 3600
POST_T_MINUS_1H = 1 * 3600
T30 = 30 * 60
T15 = 15 * 60
T5 = 5 * 60

# repeating intervals
REPEAT_10_MIN = 10 * 60
PANIC_INTERVAL = 2 * 60  # every 2 minutes during last 15
CHECK_INTERVAL = 60  # background loop checks every 60s

# positions order expected in !addroster:
POSITIONS = ["C", "LW", "RW", "LD", "RD", "G", "UTIL"]

# --- utility: storage load/save
def load_storage():
    if os.path.exists(STORAGE_FILE):
        with open(STORAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # empty template
    return {"games": [], "captain_id": None}

def save_storage(data):
    with open(STORAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

storage = load_storage()

# --- Coach quotes loader (coachisms)
def load_coach_quotes():
    quotes = {}
    if not os.path.exists(COACHISMS_FILE):
        print("Warning: coachisms file not found:", COACHISMS_FILE)
        return quotes
    cat = None
    with open(COACHISMS_FILE, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                cat = line[1:-1]
                quotes.setdefault(cat, [])
            else:
                if cat:
                    quotes[cat].append(line)
    return quotes

COACH_QUOTES = load_coach_quotes()

def random_quote(cat, player_mention=None):
    arr = COACH_QUOTES.get(cat, [])
    if not arr:
        return None
    q = random.choice(arr)
    if player_mention:
        return q.replace("{player}", player_mention)
    return q

# --- helpers
def dt_to_iso(dt):
    return dt.astimezone(NY).isoformat()

def parse_date_time(date_str, time_str):
    # Accept flexible inputs: date_str can be 'YYYY-MM-DD' or 'Aug-15-2025'
    # time_str can be '19:00' or '7:00PM' etc.
    combined = f"{date_str} {time_str}"
    dt = dtparser.parse(combined, fuzzy=True)
    # localize to America/New_York
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    else:
        dt = dt.astimezone(NY)
    return dt

def find_game_by_id(game_id):
    for g in storage["games"]:
        if g["id"] == game_id:
            return g
    return None

def ensure_game_structure(game):
    # Initialize missing fields
    if "roster" not in game:
        game["roster"] = {p: None for p in POSITIONS}
    if "confirmed" not in game:
        game["confirmed"] = {p: False for p in POSITIONS}
    if "posted_requests" not in game:
        game["posted_requests"] = {p: None for p in POSITIONS}  # store message ids for deletion
    if "flags" not in game:
        game["flags"] = {}  # track which scheduled actions have fired
    return game

# --- discord bot init
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- background scheduler loop
@tasks.loop(seconds=CHECK_INTERVAL)
async def scheduler_loop():
    now = datetime.now(tz=NY)
    to_save = False
    for game in storage["games"]:
        ensure_game_structure(game)
        game_dt = dtparser.parse(game["dt_iso"])
        # compute seconds until game (in NY)
        secs = (game_dt - now).total_seconds()
        gid = game["id"]

        # 2 days check: if roster is set and not yet posted 2d, post lineup in lineup channel
        if secs <= POST_2D_THRESHOLD and secs > POST_1D_THRESHOLD:
            if not game["flags"].get("posted_2d"):
                # If roster is full (all 6 starters set) -> post lineup in lineup channel
                starters_filled = all(game["roster"].get(p) for p in ["C","LW","RW","LD","RD","G"])
                if starters_filled:
                    await post_lineup_embed(game, note="Lineup posted 2 days before game.")
                else:
                    # roster missing: DM captain and post poll in general to gather interest
                    await notify_roster_missing(game)
                game["flags"]["posted_2d"] = True
                to_save = True

        # day-before (24h): send initial DM confirmations to assigned players
        if secs <= POST_1D_THRESHOLD and not game["flags"].get("dm_24h"):
            # DM assigned players to confirm — only those assigned
            await send_dm_confirm_requests(game, stage="24h")
            game["flags"]["dm_24h"] = True
            to_save = True

        # T - 2 hours
        if secs <= POST_T_MINUS_2H and not game["flags"].get("remind_2h"):
            await send_dm_confirm_requests(game, stage="2h")
            game["flags"]["remind_2h"] = True
            to_save = True

        # T - 1 hour
        if secs <= POST_T_MINUS_1H and not game["flags"].get("remind_1h"):
            # For each unconfirmed starter: post replacement request + DM UTIL
            await replacement_round(game, reason="1h")
            game["flags"]["remind_1h"] = True
            to_save = True

        # T - 30 minutes
        if secs <= T30 and not game["flags"].get("t30_done"):
            # If a starter still missing, DM UTIL and post requests
            await replacement_round(game, reason="30m")
            game["flags"]["t30_done"] = True
            to_save = True

        # Between T-30 and T-15: every 10 minutes post requests for unfilled starters
        # We do this by checking if secs <= 30min and > 15min, then post every REPEAT_10_MIN
        if secs <= T30 and secs > T15:
            last_post = game["flags"].get("last_10min_post", 0)
            # determine current 10min bucket using integer division
            # We'll simply post if not posted in this minute window
            if (now.minute % 10 == 0) and game["flags"].get("last_10min_minute") != now.minute:
                # Post for missing starters
                await replacement_round(game, reason="10min")
                game["flags"]["last_10min_minute"] = now.minute
                to_save = True

        # Between T-15 and start: panic mode every PANIC_INTERVAL seconds
        if secs <= T15 and secs > 0:
            last_panic = game["flags"].get("last_panic_ts", 0)
            if (datetime.now(tz=NY).timestamp() - last_panic) >= PANIC_INTERVAL:
                await replacement_round(game, reason="panic")
                game["flags"]["last_panic_ts"] = datetime.now(tz=NY).timestamp()
                to_save = True

        # At T-5 final desperate call (ensures final attempt)
        if secs <= T5 and not game["flags"].get("final_call"):
            await replacement_round(game, reason="final")
            game["flags"]["final_call"] = True
            to_save = True

    if to_save:
        save_storage(storage)

# --- core actions
async def post_lineup_embed(game, note=None):
    lineup_channel = bot.get_channel(LINEUP_CHANNEL_ID)
    if not lineup_channel:
        print("Lineup channel not found.")
        return
    embed = discord.Embed(title=f"📋 Lineup — {game['opponent']} ({game['id']})",
                          description=f"Game at {game['dt_iso']}\n{note or ''}",
                          color=discord.Color.blue())
    for pos in ["C","LW","RW","LD","RD","G","UTIL"]:
        p = game["roster"].get(pos)
        display = p if p else "—"
        embed.add_field(name=pos, value=display, inline=True)
    await lineup_channel.send(embed=embed)

async def notify_roster_missing(game):
    # DM captain if set, and post poll in general channel
    captain = storage.get("captain_id")
    general = bot.get_channel(GENERAL_CHANNEL_ID)
    # DM captain
    if captain:
        try:
            user = await bot.fetch_user(captain)
            await user.send(f"Roster missing for game {game['id']} vs {game['opponent']} at {game['dt_iso']}. Please set the lineup.")
        except Exception:
            pass
    # Post poll in general to ask who wants to play (one post for the whole game)
    if general:
        msg = await general.send(f"📣 Who wants to play vs **{game['opponent']}** on **{game['id']}**? React with {CLAIM_EMOJI} to volunteer — post separate per game.")
        await msg.add_reaction(CLAIM_EMOJI)

async def send_dm_confirm_requests(game, stage="24h"):
    # DM assigned players and UTIL asking to confirm — we will mark confirmed when they respond by DMing 'yes'
    for pos, member_mention in game["roster"].items():
        if member_mention:
            # fetch user id from mention format <@!id> or <@id>
            uid = extract_user_id(member_mention)
            if not uid:
                continue
            try:
                user = await bot.fetch_user(uid)
                quote = random_quote("PLAYER_CONFIRMED") or f"You are listed as {pos} for the game on {game['id']} vs {game['opponent']}. Reply 'yes' to confirm."
                await user.send(f"[{stage} reminder] {quote}\nReply 'yes' to this DM to confirm you will play.")
            except discord.Forbidden:
                pass

async def replacement_round(game, reason=""):
    """Post one message per missing starter in general chat and DM UTIL as specified.
       reason indicates stage: '1h','30m','10min','panic','final' etc."""
    general = bot.get_channel(GENERAL_CHANNEL_ID)
    if not general:
        return

    # For each starter position (not UTIL), if no confirmed starter or no assigned, post request
    for pos in ["C","LW","RW","LD","RD","G"]:
        assigned = game["roster"].get(pos)
        confirmed = game["confirmed"].get(pos, False)
        # If assigned but not confirmed, or not assigned at all -> post a replacement request
        need_post = (not assigned) or (not confirmed)
        if need_post:
            # Post one message for this position (avoid posting duplicate if already have live request)
            existing_msg_id = game["posted_requests"].get(pos)
            if existing_msg_id:
                # try to see if it still exists; if not, we'll post new
                try:
                    msg = await general.fetch_message(existing_msg_id)
                    # If it exists and reason is panic and we are allowed unlimited, we can post another too.
                    # To keep single active request, we won't post again if msg exists (unless panic mode forces extra posts).
                    if reason == "panic":
                        # post another panic message (allow multiples in panic)
                        pass
                    else:
                        continue
                except Exception:
                    # message no longer exists -> we'll post a new one
                    game["posted_requests"][pos] = None

            # Compose message
            human_pos = pos if pos != "G" else "Goalie"
            text = random_quote("PLAYER_MISSING") or f"Need a **{human_pos}** for game {game['id']} vs {game['opponent']} at {game['dt_iso']}. React {CLAIM_EMOJI} to claim."
            # attach coach flavor for reason
            if reason == "panic":
                text = (random_quote("GAME_DAY_START") or "") + "\n\n" + text
            # Post it
            posted = await general.send(text)
            try:
                await posted.add_reaction(CLAIM_EMOJI)
            except Exception:
                pass
            # save message id so we can delete if filled later
            game["posted_requests"][pos] = posted.id
            save_storage(storage)

    # UTIL logic at 30m: if starter missing and UTIL exists and confirmed True, DM UTIL and post in lineup channel as promoted
    if reason == "30m":
        # If any starter still missing, DM util (if present)
        util_mention = game["roster"].get("UTIL")
        util_confirmed = game["confirmed"].get("UTIL", False)
        any_missing = any((not game["roster"].get(p) or not game["confirmed"].get(p, False)) for p in ["C","LW","RW","LD","RD","G"])
        if util_mention and util_confirmed and any_missing:
            util_id = extract_user_id(util_mention)
            if util_id:
                try:
                    util_user = await bot.fetch_user(util_id)
                    # DM util that he's on deck; the bot will not auto-promote without util confirmation earlier.
                    await util_user.send(f"You are the UTIL for game {game['id']}. There are still missing starter slots — react to the general requests or reply 'take' to me if you want to fill a specific slot.")
                except discord.Forbidden:
                    pass

    # Save storage state (posted messages)
    save_storage(storage)

# --- reaction handler for claiming open slot
@bot.event
async def on_raw_reaction_add(payload):
    # Only care about CLAIM_EMOJI in general chat
    if payload.emoji.name != CLAIM_EMOJI and payload.emoji != CLAIM_EMOJI:
        return
    if payload.channel_id != GENERAL_CHANNEL_ID:
        return
    if payload.user_id == bot.user.id:
        return

    # Find which game & position this message refers to
    for game in storage["games"]:
        ensure_game_structure(game)
        for pos, msg_id in game["posted_requests"].items():
            if msg_id and msg_id == payload.message_id:
                # Someone reacted to the request for this pos
                user = await bot.fetch_user(payload.user_id)
                # send DM asking for confirmation
                try:
                    dm = await user.send(f"You reacted to claim **{pos}** for game {game['id']} vs {game['opponent']}. Reply 'yes' to this DM within 5 minutes to confirm and be added as starter.")
                except discord.Forbidden:
                    # can't DM
                    gchannel = bot.get_channel(GENERAL_CHANNEL_ID)
                    if gchannel:
                        await gchannel.send(f"{user.mention}, I tried to DM you but couldn't — make sure DMs are open.")
                    continue

                # wait for confirmation
                def check(m):
                    return m.author.id == user.id and isinstance(m.channel, discord.DMChannel) and m.content.lower().strip() in ("yes","y","confirm","i'm in","im in","i am in","take")

                try:
                    reply = await bot.wait_for("message", check=check, timeout=300)  # 5 minutes
                except asyncio.TimeoutError:
                    try:
                        await user.send("You didn’t confirm in time. If you still want the spot, react again in general.")
                    except:
                        pass
                    continue

                # double-check that slot is still open
                assigned = game["roster"].get(pos)
                confirmed = game["confirmed"].get(pos, False)
                if assigned and confirmed:
                    # someone else already took it
                    await user.send("Sorry, that position has already been filled.")
                    continue

                # assign user to the position
                mention = f"<@{user.id}>"
                game["roster"][pos] = mention
                game["confirmed"][pos] = True
                # delete the posted request message from general to keep chat clean
                try:
                    gc = bot.get_channel(GENERAL_CHANNEL_ID)
                    if gc:
                        msg = await gc.fetch_message(payload.message_id)
                        await msg.delete()
                except Exception:
                    pass
                game["posted_requests"][pos] = None
                save_storage(storage)

                # send confirmation DM and post lineup update
                try:
                    await user.send(f"You’re in! You are now **{pos}** for game {game['id']}. See you at {game['dt_iso']}.")
                except:
                    pass

                # If this was a starter filled by UTIL (i.e., the user was the UTIL), handle UTIL replacement flow
                # Check if the user was the UTIL previously for this game
                if any(game["roster"].get("UTIL") == f"<@{user.id}>" for _ in (1,)):
                    # UTIL took starter; need new UTIL post
                    await post_new_util_request(game)

                # update lineup post (post new lineup embed to lineup channel)
                await post_lineup_embed(game, note=f"{pos} filled by {mention}")
                break  # stop iterating positions once handled

async def post_new_util_request(game):
    general = bot.get_channel(GENERAL_CHANNEL_ID)
    if not general:
        return
    text = f"🛟 Our UTIL got pulled into the lineup for game {game['id']}. We need a new UTIL — react {CLAIM_EMOJI} to volunteer and then confirm by DM to me!"
    msg = await general.send(text)
    await msg.add_reaction(CLAIM_EMOJI)
    # store this special UTIL request under key 'UTIL_NEED' on game.posted_requests
    game["posted_requests"]["UTIL_NEED"] = msg.id
    save_storage(storage)

# --- admin commands to manage games / rosters
def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.manage_guild or ctx.author.guild_permissions.manage_roles
    return commands.check(predicate)

@bot.command(name="listgames")
async def list_games(ctx):
    if not storage["games"]:
        await ctx.send("No games scheduled.")
        return
    lines = []
    for g in storage["games"]:
        lines.append(f"ID: {g['id']} — vs {g['opponent']} at {g['dt_iso']}")
    await ctx.send("\n".join(lines))

@bot.command(name="addroster")
@is_admin()
async def add_roster(ctx, date: str, time: str, *, rest: str):
    """
    Usage:
    !addroster YYYY-MM-DD 19:00 Opponent @p1 @p2 @p3 @p4 @p5 @p6 @p7
    Order of players (mentions): C, LW, RW, LD, RD, G, UTIL
    """
    # split rest into opponent and mentions
    parts = rest.split()
    # find first mention start index (mentions are parsed by Discord and available in ctx.message.mentions)
    mentions = ctx.message.mentions
    if len(mentions) < 7:
        await ctx.send("You must mention 7 players in the command in this order: C, LW, RW, LD, RD, G, UTIL.")
        return
    opponent_tokens = []
    # build opponent string from parts until first mention token
    for token in parts:
        if token.startswith("<@"):
            break
        opponent_tokens.append(token)
    opponent = " ".join(opponent_tokens) if opponent_tokens else "UNKNOWN"

    # Parse date/time to NY tz
    try:
        dt = parse_date_time(date, time)
    except Exception as e:
        await ctx.send("Failed to parse date/time. Use YYYY-MM-DD and HH:MM or '7:00PM' style.")
        return

    gid = dt_to_iso(dt)
    # create game dict
    game = {
        "id": gid,
        "dt_iso": gid,
        "opponent": opponent,
        "roster": {},  # fill below
        "confirmed": {},
        "posted_requests": {},
        "flags": {}
    }
    ensure_game_structure(game)
    # map mentions in order to POSITIONS
    for i, pos in enumerate(POSITIONS):
        mention = f"<@{mentions[i].id}>"
        game["roster"][pos] = mention
        game["confirmed"][pos] = False  # will be set when they DM 'yes'
    storage["games"].append(game)
    save_storage(storage)

    # post lineup embed in lineup channel
    await post_lineup_embed(game, note="New roster created — players DMed to confirm.")
    # DM each player telling them they are listed as starter/UTIL
    for pos in POSITIONS:
        mention = game["roster"].get(pos)
        if mention:
            uid = extract_user_id(mention)
            if uid:
                try:
                    user = await bot.fetch_user(uid)
                    quote = random_quote("PLAYER_CONFIRMED") or f"You are listed as {pos} for game {game['id']} vs {opponent}. Reply 'yes' in DM to confirm."
                    await user.send(quote + "\nReply 'yes' to confirm.")
                except discord.Forbidden:
                    await ctx.send(f"Couldn't DM {mention}")

    await ctx.send(f"Roster for game {gid} vs {opponent} added. Players have been DM'd to confirm.")

@bot.command(name="showlineup")
async def show_lineup(ctx, game_id: str):
    g = find_game_by_id(game_id)
    if not g:
        await ctx.send("No such game ID.")
        return
    await post_lineup_embed(g)

@bot.command(name="setcaptain")
@is_admin()
async def set_captain(ctx, member: discord.Member):
    storage["captain_id"] = member.id
    save_storage(storage)
    await ctx.send(f"Captain set to {member.mention} — they will be DM'd when rosters are missing.")

@bot.command(name="forcecheck")
@is_admin()
async def force_check(ctx):
    await ctx.send("Forcing schedule check now.")
    await scheduler_loop()

# --- utility to extract user id from mention string
def extract_user_id(mention):
    # mention formats: <@1234567890> or <@!1234567890>
    if not mention:
        return None
    if mention.startswith("<@") and mention.endswith(">"):
        inner = mention[2:-1]
        if inner.startswith("!"):
            inner = inner[1:]
        if inner.isdigit():
            return int(inner)
    return None

# --- on DM reply handler to pick up confirmations (users replying "yes")
@bot.event
async def on_message(message):
    # ensure commands still processed
    await bot.process_commands(message)

    if message.author == bot.user:
        return

    # Only handle DMs for "yes" confirmations
    if isinstance(message.channel, discord.DMChannel):
        content = message.content.strip().lower()
        if content in ("yes","y","i'm in","im in","confirm","take","i am in"):
            uid = message.author.id
            # Find any game where this user is listed and not yet confirmed, pick the nearest upcoming game they are listed for
            now = datetime.now(tz=NY)
            candidates = []
            for g in storage["games"]:
                ensure_game_structure(g)
                # find positions where user is listed and not confirmed yet
                for pos, mention in g["roster"].items():
                    if mention and extract_user_id(mention) == uid and not g["confirmed"].get(pos, False):
                        dt = dtparser.parse(g["dt_iso"])
                        if dt > now:
                            candidates.append((dt, g, pos))
            if not candidates:
                await message.channel.send("I couldn't find any upcoming game where you're listed and waiting for confirmation.")
                return
            # pick the nearest game
            candidates.sort(key=lambda x: x[0])
            dt, game, pos = candidates[0]
            game["confirmed"][pos] = True
            save_storage(storage)
            await message.channel.send(f"Thanks — you're confirmed as **{pos}** for game {game['id']}. See you at {game['dt_iso']}!")
            # update lineup post
            await post_lineup_embed(game, note=f"{pos} confirmed by <@{uid}>")
            return

# --- startup
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="Rosterbating the bench"))
    if not scheduler_loop.is_running():
        scheduler_loop.start()

# Save storage on clean exit
import atexit
def _save_on_exit():
    save_storage(storage)
atexit.register(_save_on_exit)

# start bot
if __name__ == "__main__":
    print("Starting Coach Rosterbater...")
    # First-time ensure data structures are present
    save_storage(storage)
    bot.run(TOKEN)
