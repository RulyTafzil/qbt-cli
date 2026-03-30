#!/usr/bin/env python3
"""
qbt.py — A CLI interface for qBittorrent-nox Web API
Usage: python qbt.py [OPTIONS] COMMAND [ARGS]...

To enable autocomplete in your shell (assuming you alias this script to 'qbt'):
  Bash: eval "$(_QBT_COMPLETE=bash_source qbt)"
  Zsh:  eval "$(_QBT_COMPLETE=zsh_source qbt)"
  Fish: _QBT_COMPLETE=fish_source qbt | source
"""

import os
import sys
import time
import configparser
from pathlib import Path

import click
import requests
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich import box
from rich.live import Live

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
    return Text(state.upper(), style=f"bold {color}")


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
    
    # Secure the config file since it contains a plaintext password
    os.chmod(CONFIG_PATH, 0o600)
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
                timeout=5,
            )
            return r.text.strip() == "Ok."
        except requests.exceptions.RequestException:
            return False

    def logout(self):
        self.session.post(self._url("auth/logout"))

    def get(self, path: str, **params) -> requests.Response:
        return self.session.get(self._url(path), params=params, timeout=15)

    def post(self, path: str, **data) -> requests.Response:
        return self.session.post(self._url(path), data=data, timeout=15)

    def post_multipart(self, path: str, data=None, files=None) -> requests.Response:
        return self.session.post(self._url(path), data=data, files=files, timeout=30)

    # ... [Rest of API Client methods remain exactly the same as original script] ...
    def list_torrents(self, filter="all", category=None, sort="added_on", reverse=True):
        params = {"filter": filter, "sort": sort, "reverse": reverse}
        if category: params["category"] = category
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

    def add_torrent_url(self, urls: str, save_path=None, category=None, paused=False):
        data = {"urls": urls, "paused": str(paused).lower()}
        if save_path: data["savepath"] = save_path
        if category: data["category"] = category
        return self.post_multipart("torrents/add", data=data)

    def add_torrent_file(self, file_path: str, save_path=None, category=None, paused=False):
        data = {"paused": str(paused).lower()}
        if save_path: data["savepath"] = save_path
        if category: data["category"] = category
        with open(file_path, "rb") as f:
            files = {"torrents": (Path(file_path).name, f, "application/x-bittorrent")}
            return self.post_multipart("torrents/add", data=data, files=files)

    def get_categories(self):
        return self.get("torrents/categories").json()

    def create_category(self, name: str, save_path: str = ""):
        return self.post("torrents/createCategory", category=name, savePath=save_path)

    def edit_category(self, name: str, save_path: str):
        return self.post("torrents/editCategory", category=name, savePath=save_path)

    def remove_category(self, names: str):
        return self.post("torrents/removeCategories", categories=names)

    def get_transfer_info(self):
        return self.get("transfer/info").json()

    def get_version(self):
        return self.get("app/version").text.strip()


# ─────────────────────────────────────────────
#  Autocomplete & Resolution logic
# ─────────────────────────────────────────────

def get_silent_client():
    """Returns a client for autocomplete without printing errors."""
    try:
        cfg = load_config()
        client = QBittorrentClient(cfg["host"], cfg["port"], cfg["username"], cfg["password"])
        if client.login():
            return client
    except Exception:
        pass
    return None

def complete_torrent_name(ctx, param, incomplete):
    """Provides shell autocomplete for torrent names."""
    client = get_silent_client()
    if not client: return []
    torrents = client.list_torrents()
    return [t["name"] for t in torrents if incomplete.lower() in t["name"].lower()]

def complete_category(ctx, param, incomplete):
    """Provides shell autocomplete for categories."""
    client = get_silent_client()
    if not client: return []
    cats = client.get_categories()
    return [c for c in cats.keys() if incomplete.lower() in c.lower()]

def resolve_torrents(client, user_inputs):
    """Resolves names, exact hashes, or hash prefixes into a list of dicts: [{'hash': X, 'name': Y}]."""
    if "all" in [i.lower() for i in user_inputs]:
        return [{"hash": "all", "name": "All Torrents"}]

    torrents = client.list_torrents()
    results = []
    
    for ui in user_inputs:
        matched = False
        for t in torrents:
            if ui == t["name"] or ui == t["hash"] or t["hash"].startswith(ui):
                results.append({"hash": t["hash"], "name": t["name"]})
                matched = True
        
        if not matched:
            console.print(f"[yellow]⚠ Not found:[/] {ui}")

    # Remove duplicates (in case of overlap or multiple duplicate names mapping to identical torrents)
    seen = set()
    unique_results = []
    for r in results:
        if r["hash"] not in seen:
            seen.add(r["hash"])
            unique_results.append(r)
            
    return unique_results


# ─────────────────────────────────────────────
#  Context / shared client
# ─────────────────────────────────────────────

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

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold dim", title=header, expand=True)
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
            str(i), t["name"], state_badge(t["state"]), bytes_to_human(t["size"]),
            f"{t['progress']*100:.1f}%", speed_to_human(t["dlspeed"]), speed_to_human(t["upspeed"]),
            seconds_to_human(t.get("eta", -1)), f"{t.get('ratio', 0):.2f}",
            t.get("category", "") or "[dim]—[/]",
        )
    return table

@cli.command("list")
@click.option("-f", "--filter",   "filt",    default="all",
              type=click.Choice(["all","downloading","seeding","completed","paused","active","inactive","stalled","checking","moving","errored"]))
@click.option("-c", "--category", default=None, shell_complete=complete_category)
@click.option("-s", "--sort",     default="added_on",
              type=click.Choice(["name","size","progress","dlspeed","upspeed","eta","ratio","added_on","completion_on"]))
@click.option("--asc",            is_flag=True, help="Sort ascending (default: descending)")
@click.option("-i", "--interval", default=0, show_default=True, help="Auto-refresh interval in seconds (0 = one-shot)")
@click.pass_obj
def list_torrents(obj, filt, category, sort, asc, interval):
    """List torrents (use -i for live updating)."""
    from rich.console import Group
    client = get_client(obj)

    if interval == 0:
        table = _build_list_table(client, filt, category, sort, asc)
        console.print(table)
        console.print("[dim]Tip: Try pressing TAB after commands like pause/resume to autocomplete torrent names.[/]")
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
@click.argument("name_or_hash", shell_complete=complete_torrent_name)
@click.pass_obj
def info(obj, name_or_hash):
    """Show detailed info for a torrent."""
    client = get_client(obj)
    
    targets = resolve_torrents(client, [name_or_hash])
    if not targets: return
    
    # Just show the first match for Info
    t_hash = targets[0]["hash"]
    torrents = client.list_torrents()
    t = next(t for t in torrents if t["hash"] == t_hash)
    props = client.get_properties(t_hash)

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
#  Pause, Resume, Delete, Recheck
# ─────────────────────────────────────────────

@cli.command()
@click.argument("names", nargs=-1, required=True, shell_complete=complete_torrent_name)
@click.pass_obj
def pause(obj, names):
    """Pause one or more torrents."""
    client = get_client(obj)
    targets = resolve_torrents(client, names)
    if not targets: return

    joined_hashes = "|".join([t["hash"] for t in targets])
    if client.pause(joined_hashes).ok:
        affected_names = [t["name"] for t in targets]
        console.print(f"[yellow]⏸[/]  Paused: [bold]{', '.join(affected_names)}[/]")
    else:
        console.print("[red]✗ Failed to pause torrents.[/]")

@cli.command()
@click.argument("names", nargs=-1, required=True, shell_complete=complete_torrent_name)
@click.pass_obj
def resume(obj, names):
    """Resume one or more torrents."""
    client = get_client(obj)
    targets = resolve_torrents(client, names)
    if not targets: return

    joined_hashes = "|".join([t["hash"] for t in targets])
    if client.resume(joined_hashes).ok:
        affected_names = [t["name"] for t in targets]
        console.print(f"[green]▶[/]  Resumed: [bold]{', '.join(affected_names)}[/]")
    else:
        console.print("[red]✗ Failed to resume torrents.[/]")

@cli.command()
@click.argument("names", nargs=-1, required=True, shell_complete=complete_torrent_name)
@click.option("--with-files", is_flag=True, help="Also delete downloaded files")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt")
@click.pass_obj
def delete(obj, names, with_files, yes):
    """Delete one or more torrents (optionally with files)."""
    client = get_client(obj)
    targets = resolve_torrents(client, names)
    if not targets: return
    
    affected_names = [t["name"] for t in targets]

    if not yes:
        msg = f"Delete [bold]{len(targets)}[/] torrent(s):\n[cyan]" + "\n".join(affected_names) + "[/]\n"
        if with_files:
            msg += "\n[red bold]AND their files[/]"
        msg += "?"
        if not Confirm.ask(msg):
            console.print("[dim]Aborted.[/]")
            return

    joined_hashes = "|".join([t["hash"] for t in targets])
    r = client.delete(joined_hashes, delete_files=with_files)
    if r.ok:
        icon = "🗑" if with_files else "✗"
        console.print(f"{icon}  Deleted: [bold]{', '.join(affected_names)}[/]" + (" (+ files)" if with_files else ""))
    else:
        console.print(f"[red]✗ Failed ({r.status_code})[/]")

@cli.command()
@click.argument("names", nargs=-1, required=True, shell_complete=complete_torrent_name)
@click.pass_obj
def recheck(obj, names):
    """Force re-check/hash-verify one or more torrents."""
    client = get_client(obj)
    targets = resolve_torrents(client, names)
    if not targets: return

    joined_hashes = "|".join([t["hash"] for t in targets])
    if client.recheck(joined_hashes).ok:
        affected_names = [t["name"] for t in targets]
        console.print(f"[blue]🔍[/] Rechecking: [bold]{', '.join(affected_names)}[/]")
    else:
        console.print("[red]✗ Failed to recheck.[/]")


# ─────────────────────────────────────────────
#  Set-category command
# ─────────────────────────────────────────────

@cli.command("set-category")
@click.argument("category", shell_complete=complete_category)
@click.argument("names", nargs=-1, required=True, shell_complete=complete_torrent_name)
@click.pass_obj
def set_category(obj, category, names):
    """Assign CATEGORY to one or more torrents."""
    client = get_client(obj)
    targets = resolve_torrents(client, names)
    if not targets: return

    joined_hashes = "|".join([t["hash"] for t in targets])
    r = client.set_category(joined_hashes, category)
    if r.ok:
        affected_names = [t["name"] for t in targets]
        console.print(f"[magenta]🏷[/]  Set category [bold]{category!r}[/] on: {', '.join(affected_names)}")
    else:
        console.print(f"[red]✗ Failed ({r.status_code}) — does the category exist?[/]")


# ─────────────────────────────────────────────
#  Add command
# ─────────────────────────────────────────────

@cli.command()
@click.argument("torrent")
@click.option("-p", "--path",     "save_path", default=None, help="Save path override")
@click.option("-c", "--category", default=None, shell_complete=complete_category, help="Assign category")
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
    """Manage torrent categories."""
    pass

@categories.command("list")
@click.pass_obj
def categories_list(obj):
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
    client = get_client(obj)
    if client.create_category(name, save_path).ok:
        console.print(f"[green]✓[/] Category [magenta bold]{name}[/] created")
    else:
        console.print("[red]✗ Failed — category may already exist[/]")

@categories.command("remove")
@click.argument("names", nargs=-1, required=True, shell_complete=complete_category)
@click.option("-y", "--yes", is_flag=True)
@click.pass_obj
def categories_remove(obj, names, yes):
    if not yes and not Confirm.ask(f"Remove categories: [magenta]{', '.join(names)}[/]?"):
        return
    client = get_client(obj)
    if client.remove_category("\n".join(names)).ok:
        console.print(f"[green]✓[/] Removed: {', '.join(names)}")
    else:
        console.print("[red]✗ Failed to remove categories.[/]")




if __name__ == "__main__":
    cli(obj={})
