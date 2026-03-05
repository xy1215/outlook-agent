from __future__ import annotations
import os

import discord
import httpx
from discord import app_commands
from dotenv import load_dotenv

# Ensure local .env takes precedence over shell leftovers for local runs.
load_dotenv(override=True)


API_BASE = os.getenv("DISCORD_BOT_API_BASE", "http://127.0.0.1:8000").rstrip("/")
API_TOKEN = os.getenv("BOT_API_TOKEN", "")
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
GUILD_ID = os.getenv("DISCORD_BOT_GUILD_ID", "").strip()
AUTO_SYNC_ALL_GUILDS = os.getenv("DISCORD_BOT_AUTO_SYNC_ALL_GUILDS", "true").strip().lower() in {"1", "true", "yes", "on"}


def _api_bases() -> list[str]:
    bases = [API_BASE]
    fallbacks = ["http://127.0.0.1:8000", "http://localhost:8000"]
    for item in fallbacks:
        if item not in bases:
            bases.append(item)
    return bases


def _headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    if API_TOKEN:
        headers["X-Bot-Token"] = API_TOKEN
    return headers


async def _api_get(path: str) -> dict:
    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=8) as client:
        for base in _api_bases():
            try:
                resp = await client.get(f"{base}{path}", headers=_headers())
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                last_exc = exc
                continue
    raise RuntimeError(f"Bot API GET failed for {path}; tried: {', '.join(_api_bases())}; last_error={last_exc}")


async def _api_post(path: str, payload: dict) -> dict:
    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=8) as client:
        for base in _api_bases():
            try:
                resp = await client.post(f"{base}{path}", json=payload, headers=_headers())
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                last_exc = exc
                continue
    raise RuntimeError(f"Bot API POST failed for {path}; tried: {', '.join(_api_bases())}; last_error={last_exc}")


class CampusBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        print("setup_hook: syncing commands...", flush=True)
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        print("setup_hook: command sync done", flush=True)

    async def on_ready(self) -> None:
        print(f"Discord bot ready as {self.user} (guilds={len(self.guilds)})", flush=True)
        print(f"Bot API base candidates: {', '.join(_api_bases())}", flush=True)
        try:
            ping = await _api_get("/api/health")
            print(f"Bot API health OK: pid={ping.get('pid')} now={ping.get('now_utc')}", flush=True)
        except Exception as exc:
            print(f"Bot API health failed at startup: {exc}", flush=True)
        if GUILD_ID or not AUTO_SYNC_ALL_GUILDS:
            return
        # Guild sync makes slash commands appear quickly without waiting for global propagation.
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                print(f"Synced commands to guild: {guild.name} ({guild.id})", flush=True)
            except Exception as exc:
                print(f"Guild sync failed for {guild.id}: {exc}", flush=True)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        text = (message.content or "").strip().lower()
        if text not in {"today", "tasks", "!today", "!tasks", "bot today", "bot tasks"}:
            return
        try:
            if "today" in text:
                data = await _api_get("/api/bot/today")
                top = data.get("top_task")
                lines = [
                    f"Summary: {data.get('summary', '')}",
                    f"Tasks: {data.get('task_count', 0)} | Immediate: {data.get('immediate_count', 0)} | Weekly: {data.get('weekly_count', 0)}",
                ]
                if top:
                    lines.append(f"Top: {top.get('title')} ({top.get('remaining')})")
                    lines.append(f"task_id: `{top.get('task_id')}`")
                await message.reply("\n".join(lines), mention_author=False)
            else:
                data = await _api_get("/api/bot/tasks")
                tasks = data.get("tasks", [])
                if not tasks:
                    await message.reply("No active tasks.", mention_author=False)
                    return
                lines = [f"- `{t['task_id']}` {t['title']} | {t['remaining']}" for t in tasks[:8]]
                await message.reply("\n".join(lines), mention_author=False)
        except Exception as exc:
            await message.reply(f"Bot error: {exc}", mention_author=False)


bot = CampusBot()


@bot.tree.command(name="today", description="Show today's digest summary")
async def today_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        data = await _api_get("/api/bot/today")
        if not data.get("ok"):
            await interaction.followup.send("Failed to get today summary.", ephemeral=True)
            return
        top = data.get("top_task")
        lines = [
            f"Summary: {data.get('summary', '')}",
            f"Tasks: {data.get('task_count', 0)} | Immediate: {data.get('immediate_count', 0)} | Weekly: {data.get('weekly_count', 0)}",
        ]
        if top:
            lines.append(f"Top: {top.get('title')} ({top.get('remaining')})")
            if top.get("task_id"):
                lines.append(f"task_id: `{top.get('task_id')}`")
        await interaction.followup.send("\n".join(lines), ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"后端不可达或报错: {exc}", ephemeral=True)


@bot.tree.command(name="tasks", description="List active tasks")
async def tasks_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        data = await _api_get("/api/bot/tasks")
        if not data.get("ok"):
            await interaction.followup.send("Failed to get tasks.", ephemeral=True)
            return
        tasks = data.get("tasks", [])
        if not tasks:
            await interaction.followup.send("No active tasks.", ephemeral=True)
            return
        lines = []
        for t in tasks[:8]:
            lines.append(f"- `{t['task_id']}` {t['title']} | {t['remaining']}")
        await interaction.followup.send("\n".join(lines), ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"后端不可达或报错: {exc}", ephemeral=True)


@bot.tree.command(name="snooze", description="Snooze a task")
@app_commands.describe(hours="Snooze hours", task_id="Optional task id; default nearest task")
async def snooze_cmd(interaction: discord.Interaction, hours: int, task_id: str = "") -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        data = await _api_post("/api/bot/snooze", {"hours": max(1, hours), "task_id": task_id})
        await interaction.followup.send(data.get("message", "Done"), ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"后端不可达或报错: {exc}", ephemeral=True)


@bot.tree.command(name="done", description="Mark task done")
@app_commands.describe(task_id="Optional task id; default nearest task")
async def done_cmd(interaction: discord.Interaction, task_id: str = "") -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        data = await _api_post("/api/bot/done", {"task_id": task_id})
        await interaction.followup.send(data.get("message", "Done"), ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"后端不可达或报错: {exc}", ephemeral=True)


def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN is required")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
