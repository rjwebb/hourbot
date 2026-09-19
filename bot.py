#!/usr/bin/env python3
"""
Opens a Discord category for a fixed window each day, then closes it again.

Requires: discord.py >= 2.3, Python >= 3.9
"""

import asyncio
import datetime as dt
import logging
import os
from typing import Optional
from zoneinfo import ZoneInfo

import discord
from discord.ext import tasks
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("hourbot")

TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["GUILD_ID"])
CATEGORY_ID = int(os.environ["CATEGORY_ID"])
LOBBY_CHANNEL_ID = int(os.environ.get("LOBBY_CHANNEL_ID") or 0)
TZ = ZoneInfo(os.environ.get("TIMEZONE") or "Europe/London")
OPEN_AT = dt.time.fromisoformat(os.environ.get("OPEN_TIME") or "21:00")
DURATION = dt.timedelta(minutes=int(os.environ.get("OPEN_MINUTES") or 60))
MODE = (os.environ.get("MODE") or "hide").lower()

if MODE not in ("hide", "lock"):
    raise SystemExit("MODE must be 'hide' or 'lock'")
if not dt.timedelta(0) < DURATION < dt.timedelta(days=1):
    raise SystemExit("OPEN_MINUTES must be between 1 and 1439")

# Permissions that follow the clock. "hide" removes the channels entirely;
# "lock" leaves them readable (but not writable or reactable) so last night's
# conversation is still there in the morning.
TOGGLED = ("view_channel",) if MODE == "hide" else ("send_messages", "add_reactions")

# Permissions that stay off regardless of the clock: no threads, ever.
ALWAYS_OFF = ("create_public_threads", "create_private_threads", "send_messages_in_threads")

# Boundary times for the scheduler. Attaching a real zone (not a fixed UTC
# offset) is what keeps the opening hour fixed in local time across DST.
_CLOSE_AT = (dt.datetime.combine(dt.date.min, OPEN_AT) + DURATION).time()
BOUNDARIES = [OPEN_AT.replace(tzinfo=TZ), _CLOSE_AT.replace(tzinfo=TZ)]


def _opening_on(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, OPEN_AT, tzinfo=TZ)


def current_window(now: dt.datetime) -> Optional[dt.datetime]:
    """Start of the window containing now, or None if closed. Checks
    yesterday's window too, for windows that run past midnight."""
    for offset in (0, -1):
        start = _opening_on(now.date() + dt.timedelta(days=offset))
        if start <= now < start + DURATION:
            return start
    return None


def next_opening(now: dt.datetime) -> dt.datetime:
    for offset in (0, 1):
        start = _opening_on(now.date() + dt.timedelta(days=offset))
        if start > now:
            return start
    raise RuntimeError("unreachable")


intents = discord.Intents.none()
intents.guilds = True
client = discord.Client(intents=intents)


async def apply_state() -> None:
    """Bring the category in line with the clock. Idempotent and cheap: makes
    no API call when the permissions are already correct."""
    guild = client.get_guild(GUILD_ID)
    if guild is None:
        log.warning("guild %s not in cache, skipping", GUILD_ID)
        return

    category = guild.get_channel(CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        log.error("category %s not found", CATEGORY_ID)
        return

    now = dt.datetime.now(TZ)
    window = current_window(now)
    want = window is not None

    wanted = {perm: want for perm in TOGGLED}
    wanted.update({perm: False for perm in ALWAYS_OFF})

    overwrite = category.overwrites_for(guild.default_role)
    changed = {p: v for p, v in wanted.items() if getattr(overwrite, p) is not v}
    if changed:
        overwrite.update(**changed)
        await category.set_permissions(
            guild.default_role,
            overwrite=overwrite,
            reason="scheduled opening hours",
        )
        log.info(
            "category now %s (%s)",
            "open" if want else "closed",
            ", ".join(f"{p}={v}" for p, v in changed.items()),
        )

    await update_lobby(guild, window, now)


async def update_lobby(
    guild: discord.Guild, window: Optional[dt.datetime], now: dt.datetime
) -> None:
    if not LOBBY_CHANNEL_ID:
        return
    channel = guild.get_channel(LOBBY_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        return

    if window is not None:
        topic = f"Open now — closes at {window + DURATION:%H:%M %Z}."
    else:
        topic = f"Closed. Opens {next_opening(now):%A %H:%M %Z}."

    if channel.topic != topic:
        await channel.edit(topic=topic, reason="scheduled opening hours")


async def _apply_safely(what: str) -> None:
    try:
        await apply_state()
    except discord.HTTPException:
        log.exception("%s failed", what)


@tasks.loop(time=BOUNDARIES)
async def on_boundary() -> None:
    # asyncio can wake a hair before the scheduled time; make sure the clock
    # has actually crossed the boundary before we read it.
    await asyncio.sleep(1)
    await _apply_safely("boundary update")


@tasks.loop(minutes=10)
async def reconcile() -> None:
    """Safety net for a boundary missed during a disconnect."""
    await _apply_safely("reconcile")


@on_boundary.before_loop
@reconcile.before_loop
async def _wait_ready() -> None:
    await client.wait_until_ready()


@client.event
async def on_ready() -> None:
    log.info("connected as %s", client.user)

    guild = client.get_guild(GUILD_ID)
    category = guild.get_channel(CATEGORY_ID) if guild else None
    if isinstance(category, discord.CategoryChannel):
        stray = [c.name for c in category.channels if not c.permissions_synced]
        if stray:
            log.warning(
                "these channels don't inherit from the category and won't be "
                "opened or closed: %s — right-click each and Sync Permissions",
                ", ".join(stray),
            )

    if not on_boundary.is_running():
        on_boundary.start()
    if not reconcile.is_running():
        reconcile.start()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("discord").setLevel(logging.WARNING)
    client.run(TOKEN, log_handler=None)
