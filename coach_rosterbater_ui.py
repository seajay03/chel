# coach_rosterbater_ui.py — Slash-command edition (buttons + modals + persistence)
# Deps:  pip install -U discord.py python-dotenv python-dateutil
# .env:  DISCORD_TOKEN=xxxx

import os, json, random, asyncio, traceback
from typing import Optional, List, Tuple
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from dateutil import parser as dtparser

import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv

# ========= CONFIG =========
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("ERROR: DISCORD_TOKEN not found in .env")

# Guild: instant slash sync to YOUR server
GUILD_ID = 1199032891074683023

# Channels
LINEUP_CHANNEL_ID    = 1404021808822226974   # lineup
GENERAL_CHANNEL_ID   = 1228418184403615796   # general
COACH_LOG_CHANNEL_ID = 1199032896862822598   # coach log

# Manager roles (by ID)
ROLE_IDS_MANAGER = {
    1199032891099840670,  # OWNER
    1404726528444731413,  # Captain
    1199032891099840669,  # GM
    1199032891099840666,  # MANAGEMENT
    1228392356550807653,  # Alternate Captain
}

# Mention @everyone for urgent fills
PING_EVERYONE_ON_URGENCY = True

# Files
STORAGE_FILE   = "storage.json"
COACHISMS_FILE = "data/coachisms.txt"

# Timezone & cadence
TZ = ZoneInfo("America/Toronto")
SIX_PM = time(18, 0)   # day before
SIX_AM = time(6, 0)    # day of
POST_T_MINUS_2H = 2 * 3600
POST_T_MINUS_1H = 1 * 3600
T30 = 30 * 60
T15 = 15 * 60
T5  = 5 * 60
PANIC_INTERVAL = 2 * 60
CHECK_INTERVAL = 60

# Positions
ALL_POSITIONS      = ["C", "LW", "RW", "LD", "RD", "G", "UTIL", "UTIL2"]
STARTER_POSITIONS  = ["C", "LW", "RW", "LD", "RD", "G"]
PRACTICE_POSITIONS = ["C", "LW", "RW", "LD", "RD", "G"]

# ========= UTILS =========
def now_tz() -> datetime:
    return datetime.now(tz=TZ)

def dt_to_iso(dt: datetime) -> str:
    return dt.astimezone(TZ).isoformat()

def parse_date_time(date_str: str, time_str: str) -> datetime:
    dt = dtparser.parse(f"{date_str} {time_str}", fuzzy=True)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)

def extract_user_id(mention: Optional[str]) -> Optional[int]:
    if not mention:
        return None
    if mention.startswith("<@") and mention.endswith(">"):
        inner = mention[2:-1]
        if inner.startswith("!"):
            inner = inner[1:]
        if inner.isdigit():
            return int(inner)
    return None

def member_is_manager(m: discord.Member) -> bool:
    if m.guild and m.id == m.guild.owner_id:
        return True
    return any(r.id in ROLE_IDS_MANAGER for r in m.roles)

def game_title(g: dict) -> str:
    return f"{g['opponent']} — {g['id']}"

def anchor_times(game_dt: datetime) -> dict:
    prev_day = (game_dt - timedelta(days=1)).date()
    day_of = game_dt.date()
    return {
        "6pm_prior": datetime.combine(prev_day, SIX_PM, tzinfo=TZ),
        "6am_day": datetime.combine(day_of, SIX_AM, tzinfo=TZ),
    }

def log_ex(where: str, e: Exception):
    print(f"⚠️ {where}: {e}\n{traceback.format_exc()}")

async def safe_reply_inter(inter: discord.Interaction, content: str, ephemeral: bool = True):
    try:
        if inter.response.is_done():
            await inter.followup.send(content, ephemeral=ephemeral)
        else:
            await inter.response.send_message(content, ephemeral=ephemeral)
    except Exception as e:
        log_ex("safe_reply_inter", e)

# ========= STORAGE =========
def load_storage() -> dict:
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_ex("load_storage", e)
    return {"games": [], "practices": [], "captain_id": None}

def save_storage():
    try:
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(storage, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log_ex("save_storage", e)

storage = load_storage()

def ensure_game(g: dict) -> dict:
    g.setdefault("roster", {})
    g.setdefault("confirmed", {})
    for p in ALL_POSITIONS:
        g["roster"].setdefault(p, None)
        g["confirmed"].setdefault(p, False)
    g.setdefault("posted_requests", {p: None for p in ALL_POSITIONS})
    g.setdefault("flags", {})
    g.setdefault("lineup_message_id", None)
    g.setdefault("thread_id", None)
    g.setdefault("status", "upcoming")
    return g

def ensure_practice(p: dict) -> dict:
    p.setdefault("roster", {pos: None for pos in PRACTICE_POSITIONS})
    p.setdefault("creator_id", None)
    p.setdefault("channel_id", LINEUP_CHANNEL_ID)
    p.setdefault("message_id", None)
    p.setdefault("thread_id", None)
    p.setdefault("opponent", "Random Online")
    p.setdefault("start_in_min", 5)
    p.setdefault("flags", {"announced": False, "canceled": False, "started": False})
    return p

def find_game_by_id(game_id: str) -> Optional[dict]:
    for g in storage["games"]:
        if g["id"] == game_id:
            return ensure_game(g)
    return None

def find_practice_by_id(pid: str) -> Optional[dict]:
    for p in storage["practices"]:
        if p["id"] == pid:
            return ensure_practice(p)
    return None

def upcoming_games_for_user(uid: int) -> List[Tuple[datetime, dict, str]]:
    rows = []
    for g in storage["games"]:
        ensure_game(g)
        if g.get("status") == "past":
            continue
        dt = dtparser.parse(g["dt_iso"]).astimezone(TZ)
        if dt <= now_tz():
            continue
        for pos, mention in g["roster"].items():
            if mention and extract_user_id(mention) == uid:
                rows.append((dt, g, pos))
    rows.sort(key=lambda x: x[0])
    return rows

# ========= COACH QUOTES =========
def load_coach_quotes() -> dict:
    quotes = {}
    if not os.path.exists(COACHISMS_FILE):
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
DEFAULT_QUOTES = {
    "PLAYER_CONFIRMED": [
        "Heads up {player}, you’re penciled in. Tap confirm so I stop pacing.",
        "{player}, the slot is yours—confirm before I juggle lines again.",
    ],
    "PLAYER_MISSING": [
        "Need a **{player}** to step in. Click to claim and be a hero.",
        "Bench is squeaky—fill the **{player}** slot and tighten it up.",
    ],
    "GAME_DAY_START": [
        "Game day. Tape your sticks and your feelings.",
        "Skates on. Excuses off.",
    ],
}
def random_quote(cat: str, player_mention: Optional[str] = None) -> Optional[str]:
    arr = COACH_QUOTES.get(cat, []) or DEFAULT_QUOTES.get(cat, [])
    if not arr:
        return None
    q = random.choice(arr)
    return q.replace("{player}", player_mention or "this") if "{player}" in q else q

# ========= DISCORD BOOT =========
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
GUILD = discord.Object(id=GUILD_ID)

async def coach_log(text: str):
    ch = bot.get_channel(COACH_LOG_CHANNEL_ID)
    if ch:
        try:
            await ch.send(text)
        except Exception as e:
            log_ex("coach_log", e)

async def broadcast_to_general(text: str):
    ch = bot.get_channel(GENERAL_CHANNEL_ID)
    if ch:
        await ch.send(text)

async def get_or_create_game_thread(g: dict, lineup_message: Optional[discord.Message] = None) -> Optional[discord.Thread]:
    if g.get("thread_id"):
        th = bot.get_channel(int(g["thread_id"]))
        if isinstance(th, discord.Thread):
            return th
    if not lineup_message:
        ch = bot.get_channel(LINEUP_CHANNEL_ID)
        if not ch or not g.get("lineup_message_id"):
            return None
        try:
            lineup_message = await ch.fetch_message(int(g["lineup_message_id"]))
        except Exception:
            return None
    try:
        name = f"{g['opponent']} — {g['id']}"
        th = await lineup_message.create_thread(name=name, auto_archive_duration=1440)
        g["thread_id"] = th.id
        save_storage()
        await th.send("🏒 Game thread created. Lineup updates and urgent fills will appear here.")
        return th
    except Exception:
        return None

async def send_to_game_thread(g: dict, content: str, view: Optional[discord.ui.View] = None):
    th = await get_or_create_game_thread(g)
    if th:
        try:
            await th.send(content, view=view)
        except Exception:
            pass

# ========= LINEUP CARD (single editable) =========
class OpenManageFromCard(discord.ui.Button):
    def __init__(self, gid: str):
        super().__init__(label="Manage", style=discord.ButtonStyle.secondary, custom_id=f"card:manage:{gid}")
    async def callback(self, inter: discord.Interaction):
        if not isinstance(inter.user, discord.Member) or not member_is_manager(inter.user):
            return await inter.response.send_message("Only managers.", ephemeral=True)
        g = find_game_by_id(self.custom_id.split(":")[-1])
        if not g:
            return await inter.response.send_message("Game not found.", ephemeral=True)
        await inter.response.send_message(f"Managing **{g['id']}**", view=ManageGameView(game_id=g["id"]), ephemeral=True)

class EditRosterFromCard(discord.ui.Button):
    def __init__(self, gid: str):
        super().__init__(label="Edit Roster", style=discord.ButtonStyle.success, custom_id=f"card:edit:{gid}")
    async def callback(self, inter: discord.Interaction):
        if not isinstance(inter.user, discord.Member) or not member_is_manager(inter.user):
            return await inter.response.send_message("Only managers.", ephemeral=True)
        g = find_game_by_id(self.custom_id.split(":")[-1])
        if not g:
            return await inter.response.send_message("Game not found.", ephemeral=True)
        if g["flags"].get("locked"):
            return await inter.response.send_message("Roster is locked.", ephemeral=True)
        if g["flags"].get("canceled"):
            return await inter.response.send_message("Game is canceled.", ephemeral=True)
        await inter.response.send_message(
            f"Editing roster for **{g['opponent']}** — {g['id']}",
            view=RosterBuilderView(g["id"]),
            ephemeral=True,
        )

async def post_or_update_lineup(game: dict, note: Optional[str] = None):
    ch = bot.get_channel(LINEUP_CHANNEL_ID)
    if not ch:
        return
    desc = f"Game at {game['dt_iso']}"
    if note:
        desc += f"\n{note}"
    if game["flags"].get("locked"):
        desc += "\n🔒 Roster is locked."
    if game["flags"].get("canceled"):
        desc += "\n🚫 Game canceled."
    embed = discord.Embed(
        title=f"📋 Lineup — {game['opponent']} ({game['id']})",
        description=desc,
        color=discord.Color.blurple(),
    )
    for pos in ALL_POSITIONS:
        embed.add_field(name=pos, value=game["roster"].get(pos) or "—", inline=True)
    v = discord.ui.View(timeout=None)
    v.add_item(OpenManageFromCard(game["id"]))
    if not game["flags"].get("locked") and not game["flags"].get("canceled"):
        v.add_item(EditRosterFromCard(game["id"]))
    msg_id = game.get("lineup_message_id")
    if msg_id:
        try:
            msg = await ch.fetch_message(msg_id)
            await msg.edit(embed=embed, view=v)
            await get_or_create_game_thread(game, lineup_message=msg)
            return
        except Exception:
            game["lineup_message_id"] = None
    sent = await ch.send(embed=embed, view=v)
    game["lineup_message_id"] = sent.id
    save_storage()
    await get_or_create_game_thread(game, lineup_message=sent)

# ========= ROSTER BUILDER =========
class PositionSelect(discord.ui.Select):
    def __init__(self, gid: str):
        super().__init__(
            placeholder="Position…",
            options=[discord.SelectOption(label=p, value=p) for p in ALL_POSITIONS],
            min_values=1, max_values=1, custom_id=f"possel:{gid}",
        )
    async def callback(self, inter: discord.Interaction):
        await inter.response.defer()

class PlayerSelect(discord.ui.UserSelect):
    def __init__(self, gid: str):
        super().__init__(placeholder="Player…", min_values=1, max_values=1, custom_id=f"playersel:{gid}")
    async def callback(self, inter: discord.Interaction):
        await inter.response.defer()

class RosterBuilderView(discord.ui.View):
    def __init__(self, gid: str):
        super().__init__(timeout=300)
        self.gid = gid
        self.pos = PositionSelect(gid)
        self.user = PlayerSelect(gid)
        self.add_item(self.pos)
        self.add_item(self.user)
        self.add_item(SaveSlotBtn())
        self.add_item(FinishEditBtn())
    def selection(self):
        p = self.pos.values[0] if self.pos.values else None
        u = self.user.values[0] if self.user.values else None
        return p, u

class SaveSlotBtn(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Assign Selected", style=discord.ButtonStyle.primary)
    async def callback(self, inter: discord.Interaction):
        if not isinstance(inter.user, discord.Member) or not member_is_manager(inter.user):
            return await inter.response.send_message("Only managers.", ephemeral=True)
        v: RosterBuilderView = self.view  # type: ignore
        g = find_game_by_id(v.gid)
        if not g:
            return await inter.response.send_message("Game not found.", ephemeral=True)
        if g["flags"].get("locked"):
            return await inter.response.send_message("Roster is locked.", ephemeral=True)
        if g["flags"].get("canceled"):
            return await inter.response.send_message("Game is canceled.", ephemeral=True)
        pos, user = v.selection()
        if not pos or not user:
            return await inter.response.send_message("Pick a position and player.", ephemeral=True)
        mention = f"<@{user.id}>"
        g["roster"][pos] = mention
        g["confirmed"][pos] = False
        save_storage()
        try:
            dm = await user.send(
                (random_quote("PLAYER_CONFIRMED", mention) or f"You are listed as **{pos}** for game {g['id']}.")
                + "\nTap to confirm."
            )
            await dm.edit(view=ConfirmDMView(g["id"], pos, user.id))
        except discord.Forbidden:
            pass
        await inter.response.send_message(f"Assigned {mention} to **{pos}**.", ephemeral=True)
        await post_or_update_lineup(g, note="Roster updated.")

class FinishEditBtn(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Done", style=discord.ButtonStyle.success)
    async def callback(self, inter: discord.Interaction):
        v: RosterBuilderView = self.view  # type: ignore
        g = find_game_by_id(v.gid)
        if g:
            await post_or_update_lineup(g, note="Roster updated.")
        await inter.response.edit_message(content="Roster editing finished.", view=None)

class ConfirmDMView(discord.ui.View):
    def __init__(self, gid: str, pos: str, uid: int):
        super().__init__(timeout=600)
        self.gid = gid
        self.pos = pos
        self.uid = uid
    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success, custom_id="dm:confirm")
    async def confirm(self, inter: discord.Interaction, _button: discord.ui.Button):
        if inter.user.id != self.uid:
            return await inter.response.send_message("This isn’t for you.", ephemeral=True)
        g = find_game_by_id(self.gid)
        if not g:
            return await inter.response.send_message("Game not found.", ephemeral=True)
        if g["flags"].get("canceled"):
            return await inter.response.send_message("Game is canceled.", ephemeral=True)
        g["confirmed"][self.pos] = True
        save_storage()
        await inter.response.send_message(f"Confirmed for **{self.pos}** — see you at {g['dt_iso']}!", ephemeral=True)
        await post_or_update_lineup(g, note=f"{self.pos} confirmed by <@{self.uid}>")

# ========= CLAIM / REPLACEMENTS =========
class ClaimButton(discord.ui.Button):
    def __init__(self, gid: str, pos: str):
        super().__init__(label=f"Claim {pos}", style=discord.ButtonStyle.primary, custom_id=f"claim:{gid}:{pos}")
    async def callback(self, inter: discord.Interaction):
        gid, pos = self.custom_id.split(":")[1:]
        g = find_game_by_id(gid)
        if not g:
            return await inter.response.send_message("Game not found.", ephemeral=True)
        if g["flags"].get("locked"):
            return await inter.response.send_message("Roster is locked.", ephemeral=True)
        if g["flags"].get("canceled"):
            return await inter.response.send_message("Game is canceled.", ephemeral=True)
        if g["roster"].get(pos) and g["confirmed"].get(pos):
            return await inter.response.send_message("That spot is already filled.", ephemeral=True)
        await inter.response.send_message(
            f"Claim **{pos}** for {g['id']}?",
            view=ConfirmClaimView(gid, pos, inter.user.id),
            ephemeral=True,
        )

class ConfirmClaimView(discord.ui.View):
    def __init__(self, gid: str, pos: str, uid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self.pos = pos
        self.uid = uid
    @discord.ui.button(label="Yes, I’m in", style=discord.ButtonStyle.success)
    async def yes(self, inter: discord.Interaction, _button: discord.ui.Button):
        if inter.user.id != self.uid:
            return await inter.response.send_message("Not your button.", ephemeral=True)
        g = find_game_by_id(self.gid)
        if not g:
            return await inter.response.send_message("Game not found.", ephemeral=True)
        if g["flags"].get("locked"):
            return await inter.response.send_message("Roster is locked.", ephemeral=True)
        if g["flags"].get("canceled"):
            return await inter.response.send_message("Game is canceled.", ephemeral=True)
        if g["roster"].get(self.pos) and g["confirmed"].get(self.pos):
            return await inter.response.send_message("Too late — already filled.", ephemeral=True)
        mention = f"<@{inter.user.id}>"
        g["roster"][self.pos] = mention
        g["confirmed"][self.pos] = True
        # remove posted request if we have it
        try:
            mid = g["posted_requests"].get(self.pos)
            if mid:
                gen = bot.get_channel(GENERAL_CHANNEL_ID)
                if gen:
                    m = await gen.fetch_message(mid)
                    await m.delete()
        except Exception:
            pass
        g["posted_requests"][self.pos] = None
        save_storage()
        await inter.response.edit_message(content=f"Locked in. You’re **{self.pos}**.", view=None)
        await post_or_update_lineup(g, note=f"{self.pos} filled by {mention}")
        # UTIL moved to starter → find new UTIL
        if g["roster"].get("UTIL") == mention and self.pos != "UTIL":
            await post_new_util_request(g, "UTIL")

async def post_claim_request(g: dict, pos: str, reason: str = ""):
    if g["flags"].get("locked") or g["flags"].get("canceled"):
        return
    gen = bot.get_channel(GENERAL_CHANNEL_ID)
    if not gen:
        return
    human = "Goalie" if pos == "G" else pos
    text = (random_quote("PLAYER_MISSING", human)
            or f"Need a **{human}** for {g['id']} vs {g['opponent']} at {g['dt_iso']}.")
    urgent = {"aggressive", "panic", "final", "1h", "6am"}
    prefix = "@everyone " if (PING_EVERYONE_ON_URGENCY and reason in urgent) else ""
    v1 = discord.ui.View(timeout=None)
    v1.add_item(ClaimButton(g["id"], pos))
    msg = await gen.send(prefix + text, view=v1)
    g["posted_requests"][pos] = msg.id
    save_storage()
    v2 = discord.ui.View(timeout=None)
    v2.add_item(ClaimButton(g["id"], pos))
    await send_to_game_thread(g, prefix + text, view=v2)

async def post_new_util_request(g: dict, util_slot: str = "UTIL"):
    if g["flags"].get("locked") or g["flags"].get("canceled"):
        return
    gen = bot.get_channel(GENERAL_CHANNEL_ID)
    if not gen:
        return
    prefix = "@everyone "
    v = discord.ui.View(timeout=None)
    v.add_item(ClaimButton(g["id"], util_slot))
    msg = await gen.send(prefix + f"🛟 Need a **{util_slot}** for {g['id']} — click to claim.", view=v)
    g["posted_requests"][util_slot] = msg.id
    save_storage()
    v2 = discord.ui.View(timeout=None)
    v2.add_item(ClaimButton(g["id"], util_slot))
    await send_to_game_thread(g, prefix + f"🛟 Need a **{util_slot}**.", view=v2)

async def clear_open_requests(g: dict):
    gen = bot.get_channel(GENERAL_CHANNEL_ID)
    if not gen:
        return
    for pos, mid in list(g["posted_requests"].items()):
        if not mid:
            continue
        try:
            m = await gen.fetch_message(mid)
            await m.delete()
        except Exception:
            pass
        g["posted_requests"][pos] = None
    save_storage()

# ========= PLAYER EMERGENCY REMOVAL =========
class RequestRemovalButton(discord.ui.Button):
    def __init__(self, gid: str, pos: str):
        super().__init__(label=f"Request Removal ({pos})", style=discord.ButtonStyle.danger, custom_id=f"rm:req:{gid}:{pos}")
    async def callback(self, inter: discord.Interaction):
        gid, pos = self.custom_id.split(":")[2:]
        g = find_game_by_id(gid)
        if not g:
            return await inter.response.send_message("Game not found.", ephemeral=True)
        mention = g["roster"].get(pos)
        if not mention or extract_user_id(mention) != inter.user.id:
            return await inter.response.send_message("You’re not assigned to that slot.", ephemeral=True)
        await inter.response.send_modal(RequestRemovalModal(gid, pos))

class RequestRemovalModal(discord.ui.Modal, title="Request Removal"):
    reason = discord.ui.TextInput(label="Reason (sent to coach)", style=discord.TextStyle.paragraph, required=True)
    def __init__(self, gid: str, pos: str):
        super().__init__()
        self.gid = gid
        self.pos = pos
    async def on_submit(self, inter: discord.Interaction):
        try:
            g = find_game_by_id(self.gid)
            if not g:
                return await safe_reply_inter(inter, "Game not found.")
            uid = inter.user.id
            mention = g["roster"].get(self.pos)
            if not mention or extract_user_id(mention) != uid:
                return await safe_reply_inter(inter, "You’re not assigned to that slot.")
            g["confirmed"][self.pos] = False
            save_storage()
            await coach_log(f"🆘 Removal requested by <@{uid}> for **{self.pos}** in {game_title(g)}:\n> {self.reason}")
            await replacement_round(g, reason="emergency")
            await post_or_update_lineup(g, note=f"{self.pos} opened due to player emergency.")
            await safe_reply_inter(inter, "Coach notified. Replacement search started.")
        except Exception as e:
            log_ex("RequestRemovalModal.on_submit", e)
            await safe_reply_inter(inter, "Couldn’t process that removal (coach notified).")

# ========= MANAGER DASHBOARD =========
class AdminPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(NewGameButton())
        self.add_item(OpenManageGameButton())
        self.add_item(ListGamesButton())
        self.add_item(NewPracticeButton())  # for everyone

class NewGameButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="New Game", style=discord.ButtonStyle.primary, custom_id="admin:new_game")
    async def callback(self, inter: discord.Interaction):
        if not isinstance(inter.user, discord.Member) or not member_is_manager(inter.user):
            return await inter.response.send_message("Only managers can create games.", ephemeral=True)
        await inter.response.send_modal(NewGameModal())

class OpenManageGameButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Manage Game…", style=discord.ButtonStyle.secondary, custom_id="admin:manage")
    async def callback(self, inter: discord.Interaction):
        if not isinstance(inter.user, discord.Member) or not member_is_manager(inter.user):
            return await inter.response.send_message("Only managers.", ephemeral=True)
        if not storage["games"]:
            return await inter.response.send_message("No games to manage.", ephemeral=True)
        await inter.response.send_message("Pick a game to manage:", view=GamePickerView(), ephemeral=True)

class ListGamesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="List Games", style=discord.ButtonStyle.secondary, custom_id="admin:list")
    async def callback(self, inter: discord.Interaction):
        if not isinstance(inter.user, discord.Member) or not member_is_manager(inter.user):
            return await inter.response.send_message("Only managers.", ephemeral=True)
        if not storage["games"]:
            return await inter.response.send_message("No games scheduled.", ephemeral=True)
        lines = [f"• {g['id']} — vs **{g['opponent']}** at {g['dt_iso']}" for g in storage["games"]]
        await inter.response.send_message("\n".join(lines), ephemeral=True)

class NewGameModal(discord.ui.Modal, title="Create Game"):
    date = discord.ui.TextInput(label="Date", placeholder="YYYY-MM-DD or Aug 15 2025")
    time = discord.ui.TextInput(label="Time", placeholder="19:00 or 7:00PM")
    opponent = discord.ui.TextInput(label="Opponent", placeholder="Team Name")
    async def on_submit(self, inter: discord.Interaction):
        try:
            if not isinstance(inter.user, discord.Member) or not member_is_manager(inter.user):
                return await safe_reply_inter(inter, "Only managers.")
            try:
                dt = parse_date_time(str(self.date), str(self.time))
            except Exception:
                return await safe_reply_inter(inter, "Could not parse date/time.")
            gid = dt_to_iso(dt)
            g = ensure_game({
                "id": gid,
                "dt_iso": gid,
                "opponent": str(self.opponent) or "UNKNOWN",
                "roster": {},
                "confirmed": {},
                "posted_requests": {},
                "flags": {}
            })
            storage["games"].append(g)
            save_storage()
            await post_or_update_lineup(g, note="New game created.")
            await safe_reply_inter(inter, f"Game **{gid}** created vs **{g['opponent']}**.")
        except Exception as e:
            log_ex("NewGameModal.on_submit", e)
            await safe_reply_inter(inter, "Couldn’t create that game.")

class GamePicker(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Select a game…",
            options=[discord.SelectOption(label=g["opponent"], description=g["id"], value=g["id"]) for g in storage["games"]],
            min_values=1, max_values=1, custom_id="pick:game",
        )
    async def callback(self, inter: discord.Interaction):
        gid = self.values[0]
        await inter.response.edit_message(content=f"Managing **{gid}**", view=ManageGameView(gid))

class GamePickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(GamePicker())

class ManageGameView(discord.ui.View):
    def __init__(self, gid: str):
        super().__init__(timeout=600)
        self.gid = gid
        self.add_item(PostLineupNow())
        self.add_item(ToggleLockRoster())
        self.add_item(EditRosterFromCard(gid))
        self.add_item(StartConfirms())
        self.add_item(BroadcastReminder())
        self.add_item(RescheduleGame())
        self.add_item(CancelGame())
        self.add_item(DeleteGame())
        self.add_item(NudgeUtil())
        self.add_item(ClearRequests())
    def g(self):
        return find_game_by_id(self.gid)

class PostLineupNow(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Post/Update Lineup Now", style=discord.ButtonStyle.primary)
    async def callback(self, inter: discord.Interaction):
        g = self.view.g()  # type: ignore
        if not g:
            return await inter.response.send_message("Game not found.", ephemeral=True)
        await post_or_update_lineup(g, note="Manual lineup update.")
        await inter.response.send_message("Lineup updated.", ephemeral=True)

class ToggleLockRoster(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Lock/Unlock Roster", style=discord.ButtonStyle.secondary)
    async def callback(self, inter: discord.Interaction):
        g = self.view.g()  # type: ignore
        if not g:
            return await inter.response.send_message("Game not found.", ephemeral=True)
        g["flags"]["locked"] = not g["flags"].get("locked", False)
        save_storage()
        await post_or_update_lineup(g, note="Roster locked." if g["flags"]["locked"] else "Roster unlocked.")
        await inter.response.send_message("Toggled.", ephemeral=True)

class StartConfirms(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Start Confirms (DM all)", style=discord.ButtonStyle.primary)
    async def callback(self, inter: discord.Interaction):
        g = self.view.g()  # type: ignore
        if not g:
            return await inter.response.send_message("Game not found.", ephemeral=True)
        await send_dm_confirm_requests(g, stage="manual")
        await inter.response.send_message("Sent confirm DMs.", ephemeral=True)

class BroadcastReminder(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Broadcast Reminder", style=discord.ButtonStyle.secondary)
    async def callback(self, inter: discord.Interaction):
        await inter.response.send_modal(BroadcastModal(self.view.gid))  # type: ignore

class BroadcastModal(discord.ui.Modal, title="Broadcast Reminder"):
    text = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph)
    def __init__(self, gid: str):
        super().__init__()
        self.gid = gid
    async def on_submit(self, inter: discord.Interaction):
        try:
            g = find_game_by_id(self.gid)
            if not g:
                return await safe_reply_inter(inter, "Game not found.")
            await broadcast_to_general(f"📣 {self.text}\n(Game: {game_title(g)})")
            await safe_reply_inter(inter, "Broadcast sent.")
        except Exception as e:
            log_ex("BroadcastModal.on_submit", e)
            await safe_reply_inter(inter, "Couldn’t broadcast that.")

class RescheduleGame(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Reschedule", style=discord.ButtonStyle.primary)
    async def callback(self, inter: discord.Interaction):
        await inter.response.send_modal(RescheduleModal(self.view.gid))  # type: ignore

class RescheduleModal(discord.ui.Modal, title="Reschedule Game"):
    date = discord.ui.TextInput(label="New Date", placeholder="YYYY-MM-DD or Aug 15 2025")
    time = discord.ui.TextInput(label="New Time", placeholder="19:00 or 7:00PM")
    def __init__(self, gid: str):
        super().__init__()
        self.gid = gid
    async def on_submit(self, inter: discord.Interaction):
        try:
            g = find_game_by_id(self.gid)
            if not g:
                return await safe_reply_inter(inter, "Game not found.")
            try:
                dt = parse_date_time(str(self.date), str(self.time))
            except Exception:
                return await safe_reply_inter(inter, "Could not parse date/time.")
            iso = dt_to_iso(dt)
            g["id"] = iso
            g["dt_iso"] = iso
            g["flags"] = {}
            save_storage()
            await post_or_update_lineup(g, note="Rescheduled.")
            await safe_reply_inter(inter, f"Rescheduled to **{iso}**.")
        except Exception as e:
            log_ex("RescheduleModal.on_submit", e)
            await safe_reply_inter(inter, "Couldn’t reschedule.")

class CancelGame(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel Game", style=discord.ButtonStyle.danger)
    async def callback(self, inter: discord.Interaction):
        g = self.view.g()  # type: ignore
        if not g:
            return await inter.response.send_message("Game not found.", ephemeral=True)
        g["flags"]["canceled"] = True
        await clear_open_requests(g)
        await broadcast_to_general(f"🚫 Game canceled: {game_title(g)}")
        await post_or_update_lineup(g, note="Game canceled.")
        await inter.response.send_message("Canceled.", ephemeral=True)
        save_storage()

class DeleteGame(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Delete Game", style=discord.ButtonStyle.danger)
    async def callback(self, inter: discord.Interaction):
        gid = self.view.gid  # type: ignore
        idx = next((i for i, gg in enumerate(storage["games"]) if gg["id"] == gid), None)
        if idx is None:
            return await inter.response.send_message("Game not found.", ephemeral=True)
        storage["games"].pop(idx)
        save_storage()
        await inter.response.edit_message(content="Game deleted.", view=None)

class NudgeUtil(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Nudge UTIL", style=discord.ButtonStyle.secondary)
    async def callback(self, inter: discord.Interaction):
        g = self.view.g()  # type: ignore
        if not g:
            return await inter.response.send_message("Game not found.", ephemeral=True)
        util = g["roster"].get("UTIL")
        uid = extract_user_id(util) if util else None
        if not uid:
            return await inter.response.send_message("No UTIL set.", ephemeral=True)
        try:
            u = await bot.fetch_user(uid)
            await u.send(f"Coach here. Starters might be light for {g['id']}. Watch claim buttons in #general.")
            await inter.response.send_message("UTIL nudged.", ephemeral=True)
        except discord.Forbidden:
            await inter.response.send_message("DM to UTIL blocked.", ephemeral=True)

class ClearRequests(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Clear Open Requests", style=discord.ButtonStyle.secondary)
    async def callback(self, inter: discord.Interaction):
        g = self.view.g()  # type: ignore
        if not g:
            return await inter.response.send_message("Game not found.", ephemeral=True)
        await clear_open_requests(g)
        await inter.response.send_message("Cleared.", ephemeral=True)

# ========= CONFIRM / REPLACEMENTS ENGINE =========
async def send_dm_confirm_requests(g: dict, stage: str = "confirm"):
    if g["flags"].get("canceled"):
        return
    for pos in ALL_POSITIONS:
        mention = g["roster"].get(pos)
        if not mention:
            continue
        uid = extract_user_id(mention)
        if not uid:
            continue
        try:
            user = await bot.fetch_user(uid)
            text = random_quote("PLAYER_CONFIRMED", mention) or f"You are listed as **{pos}** for game {g['id']}."
            dm = await user.send(f"[{stage}] {text}\nTap to confirm.")
            await dm.edit(view=ConfirmDMView(g["id"], pos, uid))
        except discord.Forbidden:
            pass

async def replacement_round(g: dict, reason: str = ""):
    if g["flags"].get("locked") or g["flags"].get("canceled"):
        return
    missing = 0
    for pos in STARTER_POSITIONS:
        need = (not g["roster"].get(pos)) or (not g["confirmed"].get(pos, False))
        if need and not g["posted_requests"].get(pos):
            await post_claim_request(g, pos, reason=reason)
            missing += 1
    if missing >= 2 and not g["posted_requests"].get("UTIL2") and not g["roster"].get("UTIL2"):
        await post_new_util_request(g, "UTIL2")
    if reason == "30m":
        util = g["roster"].get("UTIL")
        util_ok = g["confirmed"].get("UTIL", False)
        if util and util_ok and missing > 0:
            uid = extract_user_id(util)
            if uid:
                try:
                    u = await bot.fetch_user(uid)
                    await u.send(f"UTIL on deck for {g['id']}. Starters missing — claim a slot in #general or reply here.")
                except discord.Forbidden:
                    pass

# ========= PRACTICE LOBBIES =========
class NewPracticeButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="New Practice Lobby", style=discord.ButtonStyle.success, custom_id="practice:new")
    async def callback(self, inter: discord.Interaction):
        origin = inter.channel.id if isinstance(inter.channel, (discord.TextChannel, discord.Thread)) else LINEUP_CHANNEL_ID
        await inter.response.send_modal(PracticeCreateModal(inter.user.id, origin))

class PracticeCreateModal(discord.ui.Modal, title="Create Practice Lobby"):
    start_in = discord.ui.TextInput(label="Start In (Minutes)", placeholder="5", default="5")
    opponent = discord.ui.TextInput(label="Opponent (optional)", placeholder="Random Online", required=False)
    def __init__(self, creator_id: int, origin_channel_id: int):
        super().__init__()
        self.creator_id = creator_id
        self.origin_channel_id = origin_channel_id
    async def on_submit(self, inter: discord.Interaction):
        try:
            try:
                mins = max(1, min(120, int(str(self.start_in).strip())))
            except Exception:
                return await safe_reply_inter(inter, "Enter minutes as a number (1–120).")
            opp = (str(self.opponent).strip() or "Random Online")[:60]
            pid = f"PRAC-{int(now_tz().timestamp())}"
            lobby = ensure_practice({
                "id": pid,
                "creator_id": self.creator_id,
                "channel_id": self.origin_channel_id,
                "opponent": opp,
                "start_in_min": mins,
            })
            storage["practices"].append(lobby)
            save_storage()
            await post_or_update_practice(lobby, note="Practice lobby created.")
            await safe_reply_inter(inter, f"Practice lobby **{pid}** created.")
        except Exception as e:
            log_ex("PracticeCreateModal.on_submit", e)
            await safe_reply_inter(inter, "Couldn’t create that lobby. The coach was notified.")

class PracticeClaimButton(discord.ui.Button):
    def __init__(self, pid: str, pos: str):
        super().__init__(label=f"{pos}", style=discord.ButtonStyle.primary, custom_id=f"prac:claim:{pid}:{pos}")
    async def callback(self, inter: discord.Interaction):
        pid, pos = self.custom_id.split(":")[2:]
        lobby = find_practice_by_id(pid)
        if not lobby:
            return await inter.response.send_message("Lobby not found.", ephemeral=True)
        if lobby["flags"].get("canceled"):
            return await inter.response.send_message("Lobby canceled.", ephemeral=True)
        if lobby["roster"].get(pos):
            return await inter.response.send_message("That slot is taken.", ephemeral=True)
        # prevent duplicate slots by the same person
        for k, mention in lobby["roster"].items():
            if mention and extract_user_id(mention) == inter.user.id:
                return await inter.response.send_message(f"You already occupy **{k}**.", ephemeral=True)
        lobby["roster"][pos] = f"<@{inter.user.id}>"
        save_storage()
        await post_or_update_practice(lobby, note=f"{inter.user.mention} joined as **{pos}**.")
        await inter.response.send_message(f"You claimed **{pos}**.", ephemeral=True)

class PracticeLeaveButton(discord.ui.Button):
    def __init__(self, pid: str):
        super().__init__(label="Leave My Slot", style=discord.ButtonStyle.secondary, custom_id=f"prac:leave:{pid}")
    async def callback(self, inter: discord.Interaction):
        pid = self.custom_id.split(":")[2]
        lobby = find_practice_by_id(pid)
        if not lobby:
            return await inter.response.send_message("Lobby not found.", ephemeral=True)
        if lobby["flags"].get("canceled"):
            return await inter.response.send_message("Lobby canceled.", ephemeral=True)
        for k, mention in lobby["roster"].items():
            if mention and extract_user_id(mention) == inter.user.id:
                lobby["roster"][k] = None
                save_storage()
                await post_or_update_practice(lobby, note=f"{inter.user.mention} left **{k}**.")
                return await inter.response.send_message("Left your slot.", ephemeral=True)
        await inter.response.send_message("You’re not in this lobby.", ephemeral=True)

class PracticeSetStartButton(discord.ui.Button):
    def __init__(self, pid: str):
        super().__init__(label="Set Start Minutes", style=discord.ButtonStyle.secondary, custom_id=f"prac:setstart:{pid}")
    async def callback(self, inter: discord.Interaction):
        pid = self.custom_id.split(":")[2]
        lobby = find_practice_by_id(pid)
        if not lobby:
            return await inter.response.send_message("Lobby not found.", ephemeral=True)
        if inter.user.id != lobby["creator_id"] and not (isinstance(inter.user, discord.Member) and member_is_manager(inter.user)):
            return await inter.response.send_message("Only the lobby creator or managers can change this.", ephemeral=True)
        await inter.response.send_modal(PracticeSetStartModal(pid))

class PracticeSetStartModal(discord.ui.Modal, title="Set Start Minutes"):
    minutes = discord.ui.TextInput(label="Minutes", placeholder="5", default="5")
    def __init__(self, pid: str):
        super().__init__()
        self.pid = pid
    async def on_submit(self, inter: discord.Interaction):
        try:
            lobby = find_practice_by_id(self.pid)
            if not lobby:
                return await safe_reply_inter(inter, "Lobby not found.")
            try:
                mins = max(1, min(120, int(str(self.minutes).strip())))
            except Exception:
                return await safe_reply_inter(inter, "Enter minutes as a number (1–120).")
            lobby["start_in_min"] = mins
            save_storage()
            await post_or_update_practice(lobby, note=f"Start window set to **{mins}** minutes.")
            await safe_reply_inter(inter, "Updated.")
        except Exception as e:
            log_ex("PracticeSetStartModal.on_submit", e)
            await safe_reply_inter(inter, "Couldn’t update that lobby.")

class PracticeAnnounceButton(discord.ui.Button):
    def __init__(self, pid: str):
        super().__init__(label="Announce Start", style=discord.ButtonStyle.success, custom_id=f"prac:announce:{pid}")
    async def callback(self, inter: discord.Interaction):
        pid = self.custom_id.split(":")[2]
        lobby = find_practice_by_id(pid)
        if not lobby:
            return await inter.response.send_message("Lobby not found.", ephemeral=True)
        if inter.user.id != lobby["creator_id"] and not (isinstance(inter.user, discord.Member) and member_is_manager(inter.user)):
            return await inter.response.send_message("Only the lobby creator or managers can announce.", ephemeral=True)
        players = [m for m in lobby["roster"].values() if m]
        when_ts = now_tz() + timedelta(minutes=int(lobby["start_in_min"]))
        when_str = when_ts.strftime("%-I:%M %p %Z")
        for m in players:
            uid = extract_user_id(m)
            if not uid:
                continue
            try:
                u = await bot.fetch_user(uid)
                await u.send(f"🏒 **Practice starting in {lobby['start_in_min']} minutes** (around {when_str}).\nOpponent: {lobby['opponent']}\nLobby: {lobby['id']}")
            except discord.Forbidden:
                pass
        lobby["flags"]["announced"] = True
        save_storage()
        await post_or_update_practice(lobby, note="Start announced to squad.")
        await inter.response.send_message("Announced. Check your DMs!", ephemeral=True)

class PracticeCancelButton(discord.ui.Button):
    def __init__(self, pid: str):
        super().__init__(label="Cancel Lobby", style=discord.ButtonStyle.danger, custom_id=f"prac:cancel:{pid}")
    async def callback(self, inter: discord.Interaction):
        pid = self.custom_id.split(":")[2]
        lobby = find_practice_by_id(pid)
        if not lobby:
            return await inter.response.send_message("Lobby not found.", ephemeral=True)
        if inter.user.id != lobby["creator_id"] and not (isinstance(inter.user, discord.Member) and member_is_manager(inter.user)):
            return await inter.response.send_message("Only the lobby creator or managers can cancel.", ephemeral=True)
        lobby["flags"]["canceled"] = True
        save_storage()
        await post_or_update_practice(lobby, note="Lobby canceled.")
        await inter.response.send_message("Lobby canceled.", ephemeral=True)

async def post_or_update_practice(lobby: dict, note: Optional[str] = None):
    ch = bot.get_channel(lobby.get("channel_id", LINEUP_CHANNEL_ID))
    if not isinstance(ch, (discord.TextChannel, discord.Thread)):
        ch = bot.get_channel(LINEUP_CHANNEL_ID)
    desc = f"Creator: <@{lobby['creator_id']}> • Opponent: {lobby['opponent']}\nStart in: **{lobby['start_in_min']}** min"
    if note:
        desc += f"\n{note}"
    if lobby["flags"].get("canceled"):
        desc += "\n🚫 Lobby canceled."
    embed = discord.Embed(title=f"🟩 Practice Lobby — {lobby['id']}", description=desc, color=discord.Color.green())
    for pos in PRACTICE_POSITIONS:
        embed.add_field(name=pos, value=lobby["roster"].get(pos) or "—", inline=True)
    v = discord.ui.View(timeout=None)
    for pos in PRACTICE_POSITIONS:
        v.add_item(PracticeClaimButton(lobby["id"], pos))
    v.add_item(PracticeLeaveButton(lobby["id"]))
    v.add_item(PracticeSetStartButton(lobby["id"]))
    v.add_item(PracticeAnnounceButton(lobby["id"]))
    v.add_item(PracticeCancelButton(lobby["id"]))
    msg_id = lobby.get("message_id")
    if msg_id:
        try:
            msg = await ch.fetch_message(msg_id)
            await msg.edit(embed=embed, view=v)
            if not lobby.get("thread_id") and isinstance(ch, discord.TextChannel):
                try:
                    th = await msg.create_thread(name=f"Practice {lobby['id']}", auto_archive_duration=1440)
                    lobby["thread_id"] = th.id
                    save_storage()
                    await th.send("🟩 Practice thread created. Chat here.")
                except Exception:
                    pass
            return
        except Exception:
            lobby["message_id"] = None
    sent = await ch.send(embed=embed, view=v)
    lobby["message_id"] = sent.id
    save_storage()
    if isinstance(ch, discord.TextChannel):
        try:
            th = await sent.create_thread(name=f"Practice {lobby['id']}", auto_archive_duration=1440)
            lobby["thread_id"] = th.id
            save_storage()
            await th.send("🟩 Practice thread created. Chat here.")
        except Exception:
            pass

# ========= SCHEDULER =========
async def scheduler_pass():
    now = now_tz()
    changed = False
    for g in storage["games"]:
        ensure_game(g)
        dt = dtparser.parse(g["dt_iso"]).astimezone(TZ)
        secs = (dt - now).total_seconds()
        if secs <= 0 and g.get("status") != "past":
            g["status"] = "past"
            changed = True
            continue
        if g["flags"].get("canceled"):
            continue
        anch = anchor_times(dt)

        if now >= anch["6pm_prior"] and not g["flags"].get("dm_6pm"):
            await send_dm_confirm_requests(g, stage="6pm-day-before")
            g["flags"]["dm_6pm"] = True
            changed = True
            await coach_log(f"📫 6pm confirms sent for {game_title(g)}")

        if now >= anch["6am_day"] and not g["flags"].get("claims_6am"):
            need = False
            for pos in STARTER_POSITIONS:
                if not g["roster"].get(pos) or not g["confirmed"].get(pos, False):
                    await post_claim_request(g, pos, reason="6am")
                    need = True
            if need:
                for pos in STARTER_POSITIONS:
                    mention = g["roster"].get(pos)
                    if mention and not g["confirmed"].get(pos, False):
                        uid = extract_user_id(mention)
                        if uid:
                            try:
                                u = await bot.fetch_user(uid)
                                await u.send(f"Morning! You’re still down as **{pos}** for {g['id']}. Confirm ASAP or we’ll fill your spot.")
                            except discord.Forbidden:
                                pass
            g["flags"]["claims_6am"] = True
            changed = True

        if secs <= POST_T_MINUS_2H and not g["flags"].get("aggressive_2h"):
            await replacement_round(g, reason="aggressive")
            g["flags"]["aggressive_2h"] = True
            changed = True

        if secs <= POST_T_MINUS_1H and not g["flags"].get("util_promoted_1h"):
            miss = [p for p in STARTER_POSITIONS if not g["roster"].get(p) or not g["confirmed"].get(p, False)]
            util = g["roster"].get("UTIL")
            util_ok = g["confirmed"].get("UTIL", False)
            if miss and util and util_ok:
                oldest = miss[0]
                g["roster"][oldest] = util
                g["confirmed"][oldest] = True
                g["roster"]["UTIL"] = None
                g["confirmed"]["UTIL"] = False
                await coach_log(f"🔄 Auto-promoted UTIL {util} to **{oldest}** for {game_title(g)}")
                await post_new_util_request(g, "UTIL")
                await post_or_update_lineup(g, note=f"UTIL auto-promoted to **{oldest}** at T-1h.")
                changed = True
            g["flags"]["util_promoted_1h"] = True

        if secs <= T30 and not g["flags"].get("t30_done"):
            await replacement_round(g, reason="30m")
            g["flags"]["t30_done"] = True
            changed = True

        if T15 >= secs > 0:
            last = g["flags"].get("last_panic_ts", 0)
            if (now_tz().timestamp() - last) >= PANIC_INTERVAL:
                await replacement_round(g, reason="panic")
                g["flags"]["last_panic_ts"] = now_tz().timestamp()
                changed = True

        if secs <= T5 and not g["flags"].get("final_call"):
            await replacement_round(g, reason="final")
            g["flags"]["final_call"] = True
            changed = True

    if changed:
        save_storage()

@tasks.loop(seconds=CHECK_INTERVAL)
async def scheduler_loop():
    await scheduler_pass()

# ========= PERSISTENT VIEWS =========
def register_persistent_views():
    bot.add_view(AdminPanelView())
    for g in storage.get("games", []):
        g = ensure_game(g)
        v = discord.ui.View(timeout=None)
        v.add_item(OpenManageFromCard(g["id"]))
        if not g["flags"].get("locked") and not g["flags"].get("canceled"):
            v.add_item(EditRosterFromCard(g["id"]))
        bot.add_view(v)
        for pos, mid in g.get("posted_requests", {}).items():
            if mid:
                vb = discord.ui.View(timeout=None)
                vb.add_item(ClaimButton(g["id"], pos))
                bot.add_view(vb)
    for p in storage.get("practices", []):
        p = ensure_practice(p)
        v = discord.ui.View(timeout=None)
        for pos in PRACTICE_POSITIONS:
            v.add_item(PracticeClaimButton(p["id"], pos))
        v.add_item(PracticeLeaveButton(p["id"]))
        v.add_item(PracticeSetStartButton(p["id"]))
        v.add_item(PracticeAnnounceButton(p["id"]))
        v.add_item(PracticeCancelButton(p["id"]))
        bot.add_view(v)

# ========= SLASH COMMANDS =========
@tree.command(name="dashboard", description="Post and pin the Coach Rosterbator dashboard (managers only).", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(channel="Channel to post the dashboard in (defaults to lineup channel)")
async def dashboard_cmd(inter: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    if not isinstance(inter.user, discord.Member) or not member_is_manager(inter.user):
        return await inter.response.send_message("Only managers.", ephemeral=True)
    target = channel or bot.get_channel(LINEUP_CHANNEL_ID) or inter.channel
    if not isinstance(target, (discord.TextChannel, discord.Thread)):
        return await inter.response.send_message("Need a text channel.", ephemeral=True)
    msg = await target.send("🏒 **Coach Rosterbator — Admin Dashboard**", view=AdminPanelView())
    try:
        await msg.pin()
    except Exception:
        pass
    await inter.response.send_message("Dashboard posted and pinned.", ephemeral=True)

@tree.command(name="mygames", description="See your upcoming assignments and request removal.", guild=discord.Object(id=GUILD_ID))
async def mygames_cmd(inter: discord.Interaction):
    rows = upcoming_games_for_user(inter.user.id)
    if not rows:
        return await inter.response.send_message("No upcoming assignments.", ephemeral=True)
    v = discord.ui.View(timeout=600)
    lines = []
    for i, (dt, g, pos) in enumerate(rows[:5], 1):
        lines.append(f"{i}. {g['opponent']} — {g['id']} as **{pos}**")
        v.add_item(RequestRemovalButton(g["id"], pos))
    if len(rows) > 5:
        lines.append(f"...and {len(rows) - 5} more.")
    await inter.response.send_message("\n".join(lines) + "\n(Use the red buttons to request removal if needed.)", view=v, ephemeral=True)

@tree.command(name="setcaptain", description="Set team captain (managers only).", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(member="Choose the member who is captain")
async def setcaptain_cmd(inter: discord.Interaction, member: discord.Member):
    if not isinstance(inter.user, discord.Member) or not member_is_manager(inter.user):
        return await inter.response.send_message("Only managers.", ephemeral=True)
    storage["captain_id"] = member.id
    save_storage()
    await inter.response.send_message(f"Captain set to {member.mention}.", ephemeral=True)

@tree.command(name="forcecheck", description="Force a scheduler pass (managers only).", guild=discord.Object(id=GUILD_ID))
async def forcecheck_cmd(inter: discord.Interaction):
    if not isinstance(inter.user, discord.Member) or not member_is_manager(inter.user):
        return await inter.response.send_message("Only managers.", ephemeral=True)
    await scheduler_pass()
    await inter.response.send_message("Checks completed.", ephemeral=True)

@tree.command(name="practice", description="Create a practice lobby (anyone).", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(start_in_minutes="Start in N minutes (1–120)", opponent="Optional opponent label")
async def practice_cmd(inter: discord.Interaction, start_in_minutes: app_commands.Range[int, 1, 120], opponent: Optional[str] = None):
    pid = f"PRAC-{int(now_tz().timestamp())}"
    lobby = ensure_practice({
        "id": pid,
        "creator_id": inter.user.id,
        "channel_id": inter.channel.id if isinstance(inter.channel, (discord.TextChannel, discord.Thread)) else LINEUP_CHANNEL_ID,
        "opponent": (opponent or "Random Online")[:60],
        "start_in_min": int(start_in_minutes),
    })
    storage["practices"].append(lobby)
    save_storage()
    await post_or_update_practice(lobby, note="Practice lobby created.")
    await inter.response.send_message(f"Practice lobby **{pid}** created.", ephemeral=True)

# ========= LIFECYCLE =========
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="Rosterbating (slash)"))
    try:
        await tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"📜 Slash commands synced to guild {GUILD_ID}.")
    except Exception as e:
        log_ex("tree.sync", e)
    register_persistent_views()

    # Auto-post dashboard (best effort)
    try:
        lineup = bot.get_channel(LINEUP_CHANNEL_ID)
        if isinstance(lineup, discord.TextChannel):
            already = False
            async for m in lineup.history(limit=50):
                if m.author.id == bot.user.id and "Coach Rosterbator — Admin Dashboard" in (m.content or ""):
                    already = True
                    break
            if not already:
                msg = await lineup.send("🏒 **Coach Rosterbator — Admin Dashboard**", view=AdminPanelView())
                try:
                    await msg.pin()
                except Exception:
                    pass
    except Exception as e:
        log_ex("auto_dashboard", e)

    if not scheduler_loop.is_running():
        scheduler_loop.start()

# Save on exit
import atexit
atexit.register(save_storage)

if __name__ == "__main__":
    print("Starting Coach Rosterbator (UI, slash)…")
    save_storage()
    bot.run(TOKEN)
