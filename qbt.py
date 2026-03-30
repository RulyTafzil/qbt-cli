#!/usr/bin/env python3
"""
qbt.py — A CLI interface for qBittorrent-nox Web API
Usage: python qbt.py [OPTIONS] COMMAND [ARGS]...
"""

import os
import sys
import json
import time
import configparser
from pathlib import Path
from typing import Optional, List

import click
import requests
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

CONFIG_PATH = Path.home() / ".config" / "qbt-cli" / "config.ini"

# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def bytes_to_human(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"

def speed_to_human(n: int) -> str:
    return bytes_to_human(n) + "/s"

def seconds_to_human(s: int) -> str:
    if s < 0 or s > 8640000:
        return "∞"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"

STATUS_COLORS = {
    "downloading": "green",
    "uploading":   "cyan",
    "stalledDL":   "yellow",
    "stalledUP":   "yellow",
    "pausedDL":    "dim",
    "pausedUP":    "dim",
    "checkingDL":  "blue",
    "checkingUP":  "blue",
    "queuedDL":    "magenta",
    "queuedUP":    "magenta",
    "error":       "red",
    "missingFiles":"red",
    "moving":      "blue",
    "unknown":     "dim",
}

def state_badge(state: str) -> Text:
    color = STATUS_COLORS.get(state, "white")
    label = state.upper()
    return Text(label, style=f"bold {color}")


# ─────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────

def load_config() -> dict:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(CONFIG_PATH)
    section = cfg["qbittorrent"] if "qbittorrent" in cfg else {}
    return {
        "host":     section.get("host", "http://localhost"),
        "port":     section.get("port", "8080"),
        "username": section.get("username", "admin"),
        "password": section.get("password", "adminadmin"),
    }

def save_config(host, port, username, password):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg = configparser.ConfigParser()
    cfg["qbittorrent"] = {
        "host":     host,
        "port":     port,
        "username": username,
        "password": password,
    }
    with open(CONFIG_PATH, "w") as f:
        cfg.write(f)
    console.print(f"[green]✓[/] Config saved to [dim]{CONFIG_PATH}[/]")


# ─────────────────────────────────────────────
#  API Client
# ─────────────────────────────────────────────

class QBittorrentClient:
    def __init__(self, host: str, port: str, username: str, password: str):
        self.base = f"{host.rstrip('/')}:{port}/api/v2"
        self.session = requests.Session()
        self.username = username
        self.password = password

    def _url(self, path: str) -> str:
        return f"{self.base}/{path.lstrip('/')}"

    def login(self) -> bool:
        try:
            r = self.session.post(
                self._url("auth/login"),
                data={"username": self.username, "password": self.password},
                timeout=10,
            )
            return r.text.strip() == "Ok."
        except requests.exceptions.ConnectionError:
            return False

    def logout(self):
        self.session.post(self._url("auth/logout"))

    def get(self, path: str, **params) -> requests.Response:
        return self.session.get(self._url(path), params=params, timeout=15)

    def post(self, path: str, **data) -> requests.Response:
        return self.session.post(self._url(path), data=data, timeout=15)

    def post_multipart(self, path: str, data=None, files=None) -> requests.Response:
        return self.session.post(self._url(path), data=data, files=files, timeout=30)

    # ── Torrents ──────────────────────────────

    def list_torrents(self, filter="all", category=None, sort="added_on", reverse=True):
        params = {"filter": filter, "sort": sort, "reverse": reverse}
        if category:
            params["category"] = category
        return self.get("torrents/info", **params).json()

    def get_properties(self, hash: str):
        return self.get("torrents/properties", hash=hash).json()

    def get_trackers(self, hash: str):
        return self.get("torrents/trackers", hash=hash).json()

    def pause(self, hashes: str):
        return self.post("torrents/pause", hashes=hashes)

    def resume(self, hashes: str):
        return self.post("torrents/resume", hashes=hashes)

    def delete(self, hashes: str, delete_files: bool = False):
        return self.post("torrents/delete", hashes=hashes, deleteFiles=str(delete_files).lower())

    def recheck(self, hashes: str):
        return self.post("torrents/recheck", hashes=hashes)

    def set_category(self, hashes: str, category: str):
        return self.post("torrents/setCategory", hashes=hashes, category=category)

    def set_priority(self, hashes: str, priority: int):
        return self.post("torrents/topPrio" if priority == 0 else "torrents/bottomPrio", hashes=hashes)

    def add_torrent_url(self, urls: str, save_path=None, category=None, paused=False):
        data = {"urls": urls, "paused": str(paused).lower()}
        if save_path:
            data["savepath"] = save_path
        if category:
            data["category"] = category
        return self.post_multipart("torrents/add", data=data)

    def add_torrent_file(self, file_path: str, save_path=None, category=None, paused=False):
        data = {"paused": str(paused).lower()}
        if save_path:
            data["savepath"] = save_path
        if category:
            data["category"] = category
        with open(file_path, "rb") as f:
            files = {"torrents": (Path(file_path).name, f, "application/x-bittorrent")}
            return self.post_multipart("torrents/add", data=data, files=files)

    # ── Categories ────────────────────────────

    def get_categories(self):
        return self.get("torrents/categories").json()

    def create_category(self, name: str, save_path: str = ""):
        return self.post("torrents/createCategory", category=name, savePath=save_path)

    def edit_category(self, name: str, save_path: str):
        return self.post("torrents/editCategory", category=name, savePath=save_path)

    def remove_category(self, names: str):
        return self.post("torrents/removeCategories", categories=names)

    # ── App Info ──────────────────────────────

    def get_transfer_info(self):
        return self.get("transfer/info").json()

    def get_version(self):
        return self.get("app/version").text.strip()


# ─────────────────────────────────────────────
#  Context / shared client
# ─────────────────────────────────────────────

pass_client = click.make_pass_decorator(dict, ensure=True)

def get_client(ctx_obj: dict) -> QBittorrentClient:
    if "client" not in ctx_obj:
        cfg = load_config()
        client = QBittorrentClient(cfg["host"], cfg["port"], cfg["username"], cfg["password"])
        with console.status("[bold blue]Connecting to qBittorrent…"):
            ok = client.login()
        if not ok:
            console.print("[bold red]✗ Login failed.[/] Check your config with [cyan]qbt config[/]")
            sys.exit(1)
        ctx_obj["client"] = client
    return ctx_obj["client"]


# ─────────────────────────────────────────────
#  CLI Root
# ─────────────────────────────────────────────

@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.pass_context
def cli(ctx):
    """[bold cyan]qbt[/] — CLI interface for qBittorrent-nox Web API\n
    Run [bold]qbt config[/] first to set your connection details."""
    ctx.ensure_object(dict)


# ─────────────────────────────────────────────
#  Config command
# ─────────────────────────────────────────────

@cli.command()
@click.option("--host",     default=None, help="Host URL, e.g. http://localhost")
@click.option("--port",     default=None, help="Web UI port (default 8080)")
@click.option("--username", default=None, help="Web UI username")
@click.option("--password", default=None, help="Web UI password")
def config(host, port, username, password):
    """Set connection details for qBittorrent Web UI."""
    cfg = load_config()

    host     = host     or Prompt.ask("Host",     default=cfg["host"])
    port     = port     or Prompt.ask("Port",     default=cfg["port"])
    username = username or Prompt.ask("Username", default=cfg["username"])
    if not password:
        hint = " [dim](leave blank to keep current)[/]" if cfg["password"] else ""
        new_pw = Prompt.ask(f"Password{hint}", password=True, default="")
        password = new_pw if new_pw else cfg["password"]

    save_config(host, port, username, password)

    # test connection
    client = QBittorrentClient(host, port, username, password)
    with console.status("[bold blue]Testing connection…"):
        ok = client.login()
    if ok:
        ver = client.get_version()
        console.print(f"[green]✓[/] Connected! qBittorrent [bold]{ver}[/]")
        client.logout()
    else:
        console.print("[red]✗ Could not connect. Double-check host/port/credentials.[/]")


# ─────────────────────────────────────────────
#  List command
# ─────────────────────────────────────────────

def _build_list_table(client, filt, category, sort, asc) -> Table:
    """Build the torrent list table (used by the live list loop)."""
    torrents = client.list_torrents(filter=filt, category=category, sort=sort, reverse=not asc)

    try:
        xfer = client.get_transfer_info()
        dl  = speed_to_human(xfer.get("dl_info_speed", 0))
        up  = speed_to_human(xfer.get("up_info_speed", 0))
        header = (
            f"[bold cyan]{len(torrents)}[/] torrent(s)"
            f"  ↓ [green]{dl}[/]  ↑ [cyan]{up}[/]"
            f"  [dim]{time.strftime('%H:%M:%S')}[/]"
        )
    except Exception:
        header = f"[bold cyan]{len(torrents)}[/] torrent(s)"

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold dim",
        title=header,
        expand=True,
    )
    table.add_column("#",        style="dim",     width=4,  no_wrap=True)
    table.add_column("Name",                      min_width=20, max_width=50)
    table.add_column("State",                     width=13, no_wrap=True)
    table.add_column("Size",     style="cyan",    width=9,  no_wrap=True)
    table.add_column("Progress", style="green",   width=8,  no_wrap=True)
    table.add_column("↓ Speed",  style="green",   width=10, no_wrap=True)
    table.add_column("↑ Speed",  style="cyan",    width=10, no_wrap=True)
    table.add_column("ETA",      style="yellow",  width=8,  no_wrap=True)
    table.add_column("Ratio",                     width=6,  no_wrap=True)
    table.add_column("Category", style="magenta", width=12, no_wrap=True)

    for i, t in enumerate(torrents, 1):
        table.add_row(
            str(i),
            t["name"],
            state_badge(t["state"]),
            bytes_to_human(t["size"]),
            f"{t['progress']*100:.1f}%",
            speed_to_human(t["dlspeed"]),
            speed_to_human(t["upspeed"]),
            seconds_to_human(t.get("eta", -1)),
            f"{t.get('ratio', 0):.2f}",
            t.get("category", "") or "[dim]—[/]",
        )

    return table


@cli.command("list")
@click.option("-f", "--filter",   "filt",    default="all",
              type=click.Choice(["all","downloading","seeding","completed","paused","active","inactive","stalled","checking","moving","errored"]),
              help="Filter by torrent state")
@click.option("-c", "--category", default=None, help="Filter by category")
@click.option("-s", "--sort",     default="added_on",
              type=click.Choice(["name","size","progress","dlspeed","upspeed","eta","ratio","added_on","completion_on"]),
              help="Sort field")
@click.option("--asc",            is_flag=True, help="Sort ascending (default: descending)")
@click.option("-i", "--interval", default=5, show_default=True,
              help="Auto-refresh interval in seconds (0 = one-shot, no live loop)")
@click.pass_obj
def list_torrents(obj, filt, category, sort, asc, interval):
    """Live auto-updating torrent list. Press Ctrl-C to exit."""
    from rich.live import Live
    from rich.console import Group

    client = get_client(obj)

    if interval == 0:
        table = _build_list_table(client, filt, category, sort, asc)
        console.print(table)
        console.print("[dim]Tip: use hash prefixes (from qbt info) or 'all' with pause/resume/delete/etc.[/]")
        return

    footer = Text(f"Auto-refreshing every {interval}s — Ctrl-C to exit", style="dim", justify="center")
    with Live(console=console, refresh_per_second=1, screen=False) as live:
        try:
            while True:
                table = _build_list_table(client, filt, category, sort, asc)
                live.update(Group(table, footer))
                time.sleep(interval)
        except KeyboardInterrupt:
            pass


# ─────────────────────────────────────────────
#  Info command
# ─────────────────────────────────────────────

@cli.command()
@click.argument("hash_prefix")
@click.pass_obj
def info(obj, hash_prefix):
    """Show detailed info for a torrent. Provide at least 8 hash chars."""
    client = get_client(obj)
    torrents = client.list_torrents()
    match = [t for t in torrents if t["hash"].startswith(hash_prefix)]
    if not match:
        console.print(f"[red]No torrent matching hash prefix [bold]{hash_prefix}[/][/]")
        return
    t = match[0]
    props = client.get_properties(t["hash"])

    panel_content = f"""[bold]{t['name']}[/]

[dim]Hash:[/]        {t['hash']}
[dim]State:[/]       {state_badge(t['state'])}
[dim]Category:[/]    {t.get('category') or '—'}
[dim]Size:[/]        {bytes_to_human(t['size'])} (done: {bytes_to_human(t['completed'])})
[dim]Progress:[/]    {t['progress']*100:.2f}%
[dim]Download:[/]    ↓ {speed_to_human(t['dlspeed'])}  ↑ {speed_to_human(t['upspeed'])}
[dim]ETA:[/]         {seconds_to_human(t.get('eta', -1))}
[dim]Ratio:[/]       {t.get('ratio', 0):.3f}
[dim]Seeds:[/]       {t.get('num_seeds', '?')} ({t.get('num_complete', '?')} in swarm)
[dim]Peers:[/]       {t.get('num_leechs', '?')} ({t.get('num_incomplete', '?')} in swarm)
[dim]Save path:[/]   {props.get('save_path', '?')}
[dim]Added:[/]       {time.strftime('%Y-%m-%d %H:%M', time.localtime(t.get('added_on', 0)))}
[dim]Tracker:[/]     {t.get('tracker', '—')}
"""
    console.print(Panel(panel_content, title="[bold cyan]Torrent Info[/]", border_style="cyan"))


# ─────────────────────────────────────────────
#  Pause command
# ─────────────────────────────────────────────

@cli.command()
@click.argument("hashes", nargs=-1, required=True)
@click.pass_obj
def pause(obj, hashes):
    """Pause one or more torrents. Use hash prefixes or 'all'."""
    client = get_client(obj)
    joined = "|".join(hashes)
    r = client.pause(joined)
    if r.ok:
        console.print(f"[yellow]⏸[/]  Paused: [bold]{', '.join(hashes)}[/]")
    else:
        console.print(f"[red]✗ Failed ({r.status_code})[/]")


# ─────────────────────────────────────────────
#  Resume command
# ─────────────────────────────────────────────

@cli.command()
@click.argument("hashes", nargs=-1, required=True)
@click.pass_obj
def resume(obj, hashes):
    """Resume one or more torrents. Use hash prefixes or 'all'."""
    client = get_client(obj)
    joined = "|".join(hashes)
    r = client.resume(joined)
    if r.ok:
        console.print(f"[green]▶[/]  Resumed: [bold]{', '.join(hashes)}[/]")
    else:
        console.print(f"[red]✗ Failed ({r.status_code})[/]")


# ─────────────────────────────────────────────
#  Delete command
# ─────────────────────────────────────────────

@cli.command()
@click.argument("hashes", nargs=-1, required=True)
@click.option("--with-files", is_flag=True, help="Also delete downloaded files")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt")
@click.pass_obj
def delete(obj, hashes, with_files, yes):
    """Delete one or more torrents (optionally with files)."""
    if not yes:
        msg = f"Delete [bold]{len(hashes)}[/] torrent(s)"
        if with_files:
            msg += " [red bold]AND their files[/]"
        msg += "?"
        if not Confirm.ask(msg):
            console.print("[dim]Aborted.[/]")
            return
    client = get_client(obj)
    joined = "|".join(hashes)
    r = client.delete(joined, delete_files=with_files)
    if r.ok:
        icon = "🗑" if with_files else "✗"
        console.print(f"{icon}  Deleted: [bold]{', '.join(hashes)}[/]" + (" (+ files)" if with_files else ""))
    else:
        console.print(f"[red]✗ Failed ({r.status_code})[/]")


# ─────────────────────────────────────────────
#  Recheck command
# ─────────────────────────────────────────────

@cli.command()
@click.argument("hashes", nargs=-1, required=True)
@click.pass_obj
def recheck(obj, hashes):
    """Force re-check/hash-verify one or more torrents."""
    client = get_client(obj)
    r = client.recheck("|".join(hashes))
    if r.ok:
        console.print(f"[blue]🔍[/] Rechecking: [bold]{', '.join(hashes)}[/]")
    else:
        console.print(f"[red]✗ Failed ({r.status_code})[/]")


# ─────────────────────────────────────────────
#  Set-category command
# ─────────────────────────────────────────────

@cli.command("set-category")
@click.argument("category")
@click.argument("hashes", nargs=-1, required=True)
@click.pass_obj
def set_category(obj, category, hashes):
    """Assign CATEGORY to one or more torrents.\n
    Example: qbt set-category Movies a1b2c3d4 e5f6a7b8"""
    client = get_client(obj)
    r = client.set_category("|".join(hashes), category)
    if r.ok:
        console.print(f"[magenta]🏷[/]  Set category [bold]{category!r}[/] on: {', '.join(hashes)}")
    else:
        console.print(f"[red]✗ Failed ({r.status_code}) — does the category exist? Use [cyan]qbt categories create[/][/]")


# ─────────────────────────────────────────────
#  Add command
# ─────────────────────────────────────────────

@cli.command()
@click.argument("torrent")
@click.option("-p", "--path",     "save_path", default=None, help="Save path override")
@click.option("-c", "--category", default=None, help="Assign category")
@click.option("--paused",         is_flag=True, help="Add in paused state")
@click.pass_obj
def add(obj, torrent, save_path, category, paused):
    """Add a torrent by URL (magnet/http) or local .torrent file path."""
    client = get_client(obj)
    with console.status("[bold blue]Adding torrent…"):
        if torrent.startswith(("magnet:", "http://", "https://")):
            r = client.add_torrent_url(torrent, save_path=save_path, category=category, paused=paused)
        else:
            path = Path(torrent)
            if not path.exists():
                console.print(f"[red]✗ File not found: {torrent}[/]")
                return
            r = client.add_torrent_file(str(path), save_path=save_path, category=category, paused=paused)

    if r.ok and r.text.strip() == "Ok.":
        status = "paused" if paused else "started"
        console.print(f"[green]✓[/] Torrent added ({status})" + (f" → category [magenta]{category}[/]" if category else ""))
    else:
        console.print(f"[red]✗ Failed: {r.text.strip()}[/]")


# ─────────────────────────────────────────────
#  Categories group
# ─────────────────────────────────────────────

@cli.group()
def categories():
    """Manage torrent categories (list / create / edit / remove)."""
    pass

@categories.command("list")
@click.pass_obj
def categories_list(obj):
    """List all categories."""
    client = get_client(obj)
    cats = client.get_categories()
    if not cats:
        console.print("[dim]No categories defined.[/]")
        return
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold dim")
    table.add_column("Category",  style="magenta bold")
    table.add_column("Save Path", style="dim")
    for name, meta in sorted(cats.items()):
        table.add_row(name, meta.get("savePath") or "[dim]—[/]")
    console.print(table)

@categories.command("create")
@click.argument("name")
@click.option("-p", "--path", "save_path", default="", help="Default save path for category")
@click.pass_obj
def categories_create(obj, name, save_path):
    """Create a new category."""
    client = get_client(obj)
    r = client.create_category(name, save_path)
    if r.ok:
        console.print(f"[green]✓[/] Category [magenta bold]{name}[/] created" + (f" → [dim]{save_path}[/]" if save_path else ""))
    else:
        console.print(f"[red]✗ Failed ({r.status_code}) — category may already exist[/]")

@categories.command("edit")
@click.argument("name")
@click.argument("save_path")
@click.pass_obj
def categories_edit(obj, name, save_path):
    """Update the save path for an existing category."""
    client = get_client(obj)
    r = client.edit_category(name, save_path)
    if r.ok:
        console.print(f"[green]✓[/] Category [magenta bold]{name}[/] → [dim]{save_path}[/]")
    else:
        console.print(f"[red]✗ Failed ({r.status_code})[/]")

@categories.command("remove")
@click.argument("names", nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True)
@click.pass_obj
def categories_remove(obj, names, yes):
    """Remove one or more categories."""
    if not yes and not Confirm.ask(f"Remove categories: [magenta]{', '.join(names)}[/]?"):
        console.print("[dim]Aborted.[/]")
        return
    client = get_client(obj)
    r = client.remove_category("\n".join(names))
    if r.ok:
        console.print(f"[green]✓[/] Removed: {', '.join(names)}")
    else:
        console.print(f"[red]✗ Failed ({r.status_code})[/]")


# ─────────────────────────────────────────────
#  Status / dashboard command
# ─────────────────────────────────────────────

@cli.command()
@click.pass_obj
def status(obj):
    """Show global transfer stats and a compact torrent summary."""
    client = get_client(obj)
    try:
        info   = client.get_transfer_info()
        ver    = client.get_version()
    except Exception as e:
        console.print(f"[red]✗ {e}[/]")
        return

    torrents = client.list_torrents()
    counts = {}
    for t in torrents:
        s = t["state"]
        counts[s] = counts.get(s, 0) + 1

    dl_speed  = speed_to_human(info.get("dl_info_speed", 0))
    up_speed  = speed_to_human(info.get("up_info_speed", 0))
    dl_total  = bytes_to_human(info.get("dl_info_data", 0))
    up_total  = bytes_to_human(info.get("up_info_data", 0))
    free_disk = bytes_to_human(info.get("free_space_on_disk", 0))

    lines = [
        f"[bold]qBittorrent[/] [dim]{ver}[/]",
        "",
        f"↓ [green bold]{dl_speed}[/]   ↑ [cyan bold]{up_speed}[/]",
        f"Session  ↓ [green]{dl_total}[/]   ↑ [cyan]{up_total}[/]",
        f"Free disk: [yellow]{free_disk}[/]",
        "",
        f"Torrents: [bold]{len(torrents)}[/] total",
    ]
    for state, count in sorted(counts.items()):
        color = STATUS_COLORS.get(state, "white")
        lines.append(f"  [{color}]{state}[/]: {count}")

    console.print(Panel("\n".join(lines), title="[bold cyan]Dashboard[/]", border_style="cyan", width=52))


# ─────────────────────────────────────────────
#  Watch / live mode
# ─────────────────────────────────────────────

@cli.command()
@click.option("-i", "--interval", default=3, help="Refresh interval in seconds (default: 3)")
@click.option("-f", "--filter", "filt", default="active",
              type=click.Choice(["all","downloading","seeding","active","paused","stalled"]),
              help="Filter torrents")
@click.pass_obj
def watch(obj, interval, filt):
    """Live-refresh torrent list. Press Ctrl-C to exit."""
    client = get_client(obj)
    console.print(f"[dim]Watching ({filt}) — refresh every {interval}s — Ctrl-C to stop[/]\n")
    try:
        while True:
            torrents = client.list_torrents(filter=filt)
            table = Table(box=box.MINIMAL, header_style="bold dim", expand=True)
            table.add_column("Name",       min_width=20, max_width=45)
            table.add_column("State",      width=13, no_wrap=True)
            table.add_column("Progress",   width=8,  no_wrap=True)
            table.add_column("↓",          width=10, no_wrap=True, style="green")
            table.add_column("↑",          width=10, no_wrap=True, style="cyan")
            table.add_column("ETA",        width=8,  no_wrap=True, style="yellow")
            for t in torrents:
                table.add_row(
                    t["name"],
                    state_badge(t["state"]),
                    f"{t['progress']*100:.1f}%",
                    speed_to_human(t["dlspeed"]),
                    speed_to_human(t["upspeed"]),
                    seconds_to_human(t.get("eta", -1)),
                )
            console.clear()
            console.print(f"[bold cyan]qbt watch[/] [dim]{filt}[/] — [dim]{time.strftime('%H:%M:%S')}[/]")
            console.print(table)
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/]")


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    cli(obj={})
