#!/usr/bin/env python3
"""
Opens a Discord category for a fixed window each day, then closes it again.

Requires: discord.py >= 2.3, Python >= 3.9
"""

import asyncio
import datetime as dt
import logging
import os
from dataclasses import dataclass
from typing import Optional
from zoneinfo import ZoneInfo

import discord
from discord.ext import tasks
from dotenv import load_dotenv

from hours import Schedule

log = logging.getLogger("hourbot")


@dataclass(frozen=True)
class Config:
    token: str
    guild_id: int
    category_id: int
    lobby_channel_id: int  # 0 = no lobby channel
    mode: str  # "hide" or "lock"
    schedule: Schedule


def load_config() -> Config:
    load_dotenv()
    mode = (os.environ.get("MODE") or "hide").lower()
    if mode not in ("hide", "lock"):
        raise SystemExit("MODE must be 'hide' or 'lock'")
    return Config(
        token=os.environ["DISCORD_TOKEN"],
        guild_id=int(os.environ["GUILD_ID"]),
        category_id=int(os.environ["CATEGORY_ID"]),
        lobby_channel_id=int(os.environ.get("LOBBY_CHANNEL_ID") or 0),
        mode=mode,
        schedule=Schedule(
            tz=ZoneInfo(os.environ.get("TIMEZONE") or "Europe/London"),
            open_at=dt.time.fromisoformat(os.environ.get("OPEN_TIME") or "21:00"),
            duration=dt.timedelta(minutes=int(os.environ.get("OPEN_MINUTES") or 60)),
        ),
    )


CFG = load_config()
SCHEDULE = CFG.schedule

# Permissions that follow the clock. "hide" removes the channels entirely;
# "lock" leaves them readable (but not writable or reactable) so last night's
# conversation is still there in the morning.
TOGGLED = ("view_channel",) if CFG.mode == "hide" else ("send_messages", "add_reactions")

# Permissions that stay off regardless of the clock: no threads, ever.
ALWAYS_OFF = ("create_public_threads", "create_private_threads", "send_messages_in_threads")

MANAGED = TOGGLED + ALWAYS_OFF


intents = discord.Intents.none()
intents.guilds = True
client = discord.Client(intents=intents)


async def ensure_own_access(guild: discord.Guild, category: discord.CategoryChannel) -> None:
    """Give the bot an explicit allow for every permission it manages. Without
    this, denying view_channel to @everyone hides the category from the bot
    too, and Discord only lets us set overwrite bits we hold ourselves."""
    me = guild.me
    overwrite = category.overwrites_for(me)
    missing = [p for p in MANAGED if getattr(overwrite, p) is not True]
    if missing:
        overwrite.update(**{p: True for p in missing})
        await category.set_permissions(
            me,
            overwrite=overwrite,
            reason="hourbot must keep access to the category it manages",
        )
        log.info("granted myself %s on the category", ", ".join(missing))


async def apply_state() -> None:
    """Bring the category in line with the clock. Idempotent and cheap: makes
    no API call when the permissions are already correct."""
    guild = client.get_guild(CFG.guild_id)
    if guild is None:
        log.warning("guild %s not in cache, skipping", CFG.guild_id)
        return

    category = guild.get_channel(CFG.category_id)
    if not isinstance(category, discord.CategoryChannel):
        log.error("category %s not found", CFG.category_id)
        return

    # Must come before any write to @everyone, or we lock ourselves out.
    await ensure_own_access(guild, category)

    now = dt.datetime.now(SCHEDULE.tz)
    window = SCHEDULE.current_window(now)
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
    if not CFG.lobby_channel_id:
        return
    channel = guild.get_channel(CFG.lobby_channel_id)
    if not isinstance(channel, discord.TextChannel):
        return

    if window is not None:
        topic = f"Open now — closes at {window + SCHEDULE.duration:%H:%M %Z}."
    else:
        topic = f"Closed. Opens {SCHEDULE.next_opening(now):%A %H:%M %Z}."

    if channel.topic != topic:
        await channel.edit(topic=topic, reason="scheduled opening hours")


async def _apply_safely(what: str) -> None:
    try:
        await apply_state()
    except discord.HTTPException:
        log.exception("%s failed", what)


@tasks.loop(time=SCHEDULE.boundaries)
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

    guild = client.get_guild(CFG.guild_id)
    category = guild.get_channel(CFG.category_id) if guild else None
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
    client.run(CFG.token, log_handler=None)
