#!/usr/bin/env python3
"""
qbt-cli — An interactive TUI for qBittorrent-nox built with Textual.

Usage:
  qbt           # Launch the TUI
  qbt config    # Run the setup wizard to update credentials
"""

import configparser
import os
import sys
from pathlib import Path

import requests
from rich.console import Console
from rich.prompt import Prompt
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Label, Static

try:
    import keyring

    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False

# ─────────────────────────────────────────────
#  Helpers & Formatters
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
    "uploading": "cyan",
    "stalledDL": "yellow",
    "stalledUP": "yellow",
    "pausedDL": "dim",
    "pausedUP": "dim",
    "checkingDL": "blue",
    "checkingUP": "blue",
    "queuedDL": "magenta",
    "queuedUP": "magenta",
    "error": "red",
    "missingFiles": "red",
    "moving": "blue",
    "unknown": "dim",
}


def state_badge(state: str) -> str:
    # Map the API state string to your chosen icon
    # You can use the Emoji set for zero-configuration
    STATE_MAP = {
        "downloading": "⬇️",
        "uploading": "⬆️",
        "seeding": "⬆️",
        "paused": "⏸️",
        "completed": "✅",
        "error": "❌",
        "checking": "🔍",
        "queued": "⏳",
        "metadata": "⏳",
    }

    # Return the icon, or a default symbol if the state is unknown
    return STATE_MAP.get(state.lower(), "❓")


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

    def get(self, path: str, **params) -> requests.Response:
        return self.session.get(self._url(path), params=params, timeout=15)

    def post(self, path: str, **data) -> requests.Response:
        return self.session.post(self._url(path), data=data, timeout=15)

    def list_torrents(self, filter="all", sort="name", reverse=False):
        return self.get(
            "torrents/info", filter=filter, sort=sort, reverse=reverse
        ).json()

    def get_properties(self, hash: str):
        return self.get("torrents/properties", hash=hash).json()

    def pause(self, hashes: str):
        return self.post("torrents/pause", hashes=hashes)

    def resume(self, hashes: str):
        return self.post("torrents/resume", hashes=hashes)

    def delete(self, hashes: str, delete_files: bool = False):
        return self.post(
            "torrents/delete", hashes=hashes, deleteFiles=str(delete_files).lower()
        )

    def set_category(self, hashes: str, category: str):
        return self.post("torrents/setCategory", hashes=hashes, category=category)

    def get_categories(self) -> dict:
        return self.get("torrents/categories").json()

    def get_transfer_info(self):
        return self.get("transfer/info").json()


# ─────────────────────────────────────────────
#  Config Logic & Safe Credential Storage
# ─────────────────────────────────────────────

CONFIG_PATH = Path.home() / ".config" / "qbt-cli" / "config.ini"
SERVICE_NAME = "qbt-cli"
console = Console()


def run_config_flow():
    """Interactive prompt for updating connection details securely."""
    console.print("[bold cyan]qBittorrent CLI Configuration[/]")

    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(CONFIG_PATH)
    section = cfg["qbittorrent"] if "qbittorrent" in cfg else {}

    host = Prompt.ask("Host", default=section.get("host", "http://localhost"))
    port = Prompt.ask("Port", default=section.get("port", "8080"))
    username = Prompt.ask("Username", default=section.get("username", "admin"))
    password = Prompt.ask("Password", password=True)

    # Prepare config file
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg["qbittorrent"] = {"host": host, "port": port, "username": username}

    # Attempt to securely store the password using OS Keyring
    saved_to_keyring = False
    if HAS_KEYRING:
        try:
            keyring.set_password(SERVICE_NAME, username, password)
            saved_to_keyring = True
        except Exception:
            pass

    # Fallback to plaintext config if keyring is missing or fails
    if not saved_to_keyring:
        console.print(
            "[yellow]⚠ OS Keyring unavailable. Saving password to config file.[/]"
        )
        if not HAS_KEYRING:
            console.print(
                "[dim]Tip: run `pip install keyring` for secure password storage.[/dim]"
            )
        cfg["qbittorrent"]["password"] = password

    # Write config
    with open(CONFIG_PATH, "w") as f:
        cfg.write(f)
    os.chmod(CONFIG_PATH, 0o600)  # Secure the file regardless

    # Test Connection
    with console.status("[bold blue]Testing connection..."):
        client = QBittorrentClient(host, port, username, password)
        if client.login():
            console.print("[green]✓ Connection successful! Configuration saved.[/]")
        else:
            console.print(
                "[red]✗ Login failed. Please check credentials and try again.[/]"
            )


def load_client_from_config() -> QBittorrentClient | None:
    """Loads client silently. Returns None if login fails or config is missing."""
    cfg = configparser.ConfigParser()
    if not CONFIG_PATH.exists():
        return None

    cfg.read(CONFIG_PATH)
    if "qbittorrent" not in cfg:
        return None

    section = cfg["qbittorrent"]
    host, port, username = (
        section.get("host"),
        section.get("port"),
        section.get("username"),
    )

    # Try retrieving password from keyring first, fallback to config.ini
    password = None
    if HAS_KEYRING:
        try:
            password = keyring.get_password(SERVICE_NAME, username)
        except Exception:
            pass

    if not password:
        password = section.get("password")

    if not host or not username or not password:
        return None

    client = QBittorrentClient(host, port, username, password)
    if client.login():
        return client
    return None


# ─────────────────────────────────────────────
#  TUI Modals
# ─────────────────────────────────────────────


class DeleteModal(ModalScreen[tuple[bool, bool]]):
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("j", "next_option", "Down"),
        ("k", "prev_option", "Up"),
        ("enter", "confirm", "Confirm"),
    ]
    CSS = """
    DeleteModal { align: center middle; }
    #dialog { padding: 1 2; width: 52; height: 11; border: thick $background 80%; background: $surface; }
    #question { height: 2; content-align: center middle; width: 100%; }
    #options { height: auto; margin-top: 1; }
    .option { height: 1; padding-left: 2; color: $text-muted; }
    .option.selected { color: $text; }
    """

    _OPTIONS = [
        ("Delete torrent and keep files", (True, False)),
        ("Delete torrent and files", (True, True)),
        ("Cancel", (False, False)),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._focused_index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Are you sure?", id="question")
            with Vertical(id="options"):
                for i, (label, _) in enumerate(self._OPTIONS):
                    yield Static(f"  {label}", classes="option", id=f"opt_{i}")

    def on_mount(self) -> None:
        self._render_options()

    def _render_options(self) -> None:
        for i, (label, _) in enumerate(self._OPTIONS):
            widget = self.query_one(f"#opt_{i}", Static)
            cursor = ">" if i == self._focused_index else " "
            widget.update(f"{cursor} {label}")
            widget.set_class(i == self._focused_index, "selected")

    def action_next_option(self) -> None:
        self._focused_index = (self._focused_index + 1) % len(self._OPTIONS)
        self._render_options()

    def action_prev_option(self) -> None:
        self._focused_index = (self._focused_index - 1) % len(self._OPTIONS)
        self._render_options()

    def action_confirm(self) -> None:
        self.dismiss(self._OPTIONS[self._focused_index][1])

    def action_cancel(self) -> None:
        self.dismiss((False, False))


class CategoryModal(ModalScreen[str | None]):
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("j", "next_option", "Down"),
        ("k", "prev_option", "Up"),
        ("enter", "confirm", "Confirm"),
    ]
    CSS = """
    CategoryModal { align: center middle; }
    #dialog { padding: 1 2; width: 52; border: thick $background 80%; background: $surface; height: auto; max-height: 80%; }
    #title { height: 1; color: $text-muted; margin-bottom: 1; }
    .option { height: 1; color: $text-muted; }
    .option.selected { color: $text; }
    """

    def __init__(self, current_category: str, categories: list[str]) -> None:
        super().__init__()
        self._current = current_category
        # Always offer "No category" as the first option to allow clearing
        self._options = ["(no category)"] + categories
        # Pre-select the torrent's current category if it's in the list
        self._focused_index = (
            self._options.index(current_category)
            if current_category in self._options
            else 0
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Select category:", id="title")
            for i, name in enumerate(self._options):
                yield Static(f"  {name}", classes="option", id=f"opt_{i}")

    def on_mount(self) -> None:
        self._render_options()

    def _render_options(self) -> None:
        for i, name in enumerate(self._options):
            widget = self.query_one(f"#opt_{i}", Static)
            cursor = ">" if i == self._focused_index else " "
            widget.update(f"{cursor} {name}")
            widget.set_class(i == self._focused_index, "selected")

    def action_next_option(self) -> None:
        self._focused_index = (self._focused_index + 1) % len(self._options)
        self._render_options()

    def action_prev_option(self) -> None:
        self._focused_index = (self._focused_index - 1) % len(self._options)
        self._render_options()

    def action_confirm(self) -> None:
        selected = self._options[self._focused_index]
        # "(no category)" maps to an empty string for the API
        self.dismiss("" if selected == "(no category)" else selected)

    def action_cancel(self) -> None:
        self.dismiss(None)


class InfoModal(ModalScreen):
    BINDINGS = [
        ("escape", "close", "Close"),
        ("enter", "close", "Close"),
    ]
    CSS = """
    InfoModal { align: center middle; }
    #info-dialog { padding: 1 2; width: 80; height: 24; border: thick $background 80%; background: $surface; }
    #close-hint { height: 1; margin-top: 1; color: $text; }
    """

    def __init__(self, torrent_data: dict, props: dict):
        super().__init__()
        self.torrent_data = torrent_data
        self.props = props

    def compose(self) -> ComposeResult:
        t = self.torrent_data
        content = f"""[bold cyan]{t["name"]}[/]

[dim]Hash:[/]        {t["hash"]}
[dim]State:[/]       {t["state"]}
[dim]Size:[/]        {bytes_to_human(t["size"])} (done: {bytes_to_human(t.get("completed", 0))})
[dim]Progress:[/]    {t["progress"] * 100:.2f}%
[dim]Download:[/]    ↓ {speed_to_human(t["dlspeed"])}  ↑ {speed_to_human(t["upspeed"])}
[dim]ETA:[/]         {seconds_to_human(t.get("eta", -1))}
[dim]Category:[/]    {t.get("category") or "—"}
[dim]Seeds:[/]       {t.get("num_seeds", "?")} ({t.get("num_complete", "?")} in swarm)
[dim]Peers:[/]       {t.get("num_leechs", "?")} ({t.get("num_incomplete", "?")} in swarm)
[dim]Save path:[/]   {self.props.get("save_path", "?")}
[dim]Tracker:[/]     {t.get("tracker") or "-"}
"""
        with Vertical(id="info-dialog"):
            yield Static(content)
            yield Static("> Close", id="close-hint")

    def action_close(self) -> None:
        self.dismiss()


# ─────────────────────────────────────────────
#  Main TUI Application
# ─────────────────────────────────────────────


class QbtApp(App):
    TITLE = "qBittorrent CLI"
    CSS = "DataTable { height: 100%; }"

    # App-level bindings
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("p", "pause", "Pause"),
        ("r", "resume", "Resume"),
        ("d", "delete", "Delete"),
        ("c", "edit_category", "Category"),
        ("s", "toggle_sort", "Sort"),
        ("i", "info", "Info"),
    ]

    def __init__(self, client: QBittorrentClient):
        super().__init__()
        self.client = client
        self.torrent_map = {}
        self.column_keys = []
        self._sort_by_name = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(id="torrents", cursor_type="row")
        yield Footer()

    # Setup DataTable
    def on_mount(self) -> None:
        table = self.query_one(DataTable)

        # Setting fixed widths for the non-name columns.
        fixed_widths = {
            "State": 9,
            "Category": 8,
            "Size": 10,
            "Progress": 6,
            "↓ Speed": 7,
            "↑ Speed": 7,
            "ETA": 6,
        }

        # Add columns individually to apply fixed widths.
        # The Name column width is recalculated dynamically based on window size.
        self.column_keys = [
            table.add_column("Name", width=12, key="name"),
            table.add_column("State", width=fixed_widths["State"]),
            table.add_column("Category", width=fixed_widths["Category"]),
            table.add_column("      Size", width=fixed_widths["Size"]),
            table.add_column("Prog", width=fixed_widths["Progress"]),
            table.add_column("↓", width=fixed_widths["↓ Speed"]),
            table.add_column("↑", width=fixed_widths["↑ Speed"]),
            table.add_column("ETA", width=fixed_widths["ETA"]),
        ]

        self.call_after_refresh(self.recalculate_table_width)

        self.update_data()
        self.set_interval(1.5, self.update_data)

    def recalculate_table_width(self) -> None:
        """Calculates and sets the width of the 'Name' column."""
        try:
            table = self.query_one(DataTable)
        except Exception:
            return

        # 1. Sum up the widths of all columns EXCEPT "name"
        # Note: we check col.key.value to compare the actual string
        fixed_width_sum = sum(
            col.width for col in table.columns.values() if col.key.value != "name"
        )

        # 2. Calculate remaining space
        # A buffer of 2-4 is usually enough for the vertical scrollbar/borders
        chrome_buffer = 16
        available_width = self.size.width - fixed_width_sum - chrome_buffer

        # 3. Update the Name column width using the columns dict
        # This avoids the "generator" error
        if "name" in table.columns:
            table.columns["name"].width = max(15, available_width)

        # 4. Refresh the table to apply the new layout
        table.refresh()

    def on_resize(self) -> None:
        """Called automatically by Textual when the terminal resizes."""
        self.recalculate_table_width()

    def update_data(self) -> None:
        try:
            if self._sort_by_name:
                torrents = self.client.list_torrents(sort="name", reverse=False)
            else:
                torrents = self.client.list_torrents(sort="added_on", reverse=True)
            xfer = self.client.get_transfer_info()
        except Exception:
            self.sub_title = "[red]Connection lost![/]"
            return

        dl = speed_to_human(xfer.get("dl_info_speed", 0))
        up = speed_to_human(xfer.get("up_info_speed", 0))
        sort_label = "name" if self._sort_by_name else "added"
        self.sub_title = f"↓ {dl}   ↑ {up}   sorted by {sort_label}"

        table = self.query_one(DataTable)
        fetched_hashes = set()

        for t in torrents:
            hash_str = t["hash"]
            fetched_hashes.add(hash_str)

            # Pad size string to 10 chars so it right-aligns neatly in the cell
            size_formatted = f"{bytes_to_human(t['size']):>10}"

            cells = (
                t["name"],
                state_badge(t["state"]),
                t.get("category", "") or "[dim]—[/]",
                size_formatted,
                f"{t['progress'] * 100:.1f}%",
                speed_to_human(t["dlspeed"]),
                speed_to_human(t["upspeed"]),
                seconds_to_human(t.get("eta", -1)),
            )

            if hash_str in self.torrent_map:
                for col_key, val in zip(self.column_keys, cells):
                    table.update_cell(hash_str, col_key, val, update_width=True)
            else:
                table.add_row(*cells, key=hash_str)

            self.torrent_map[hash_str] = t

        for hash_str in list(self.torrent_map.keys()):
            if hash_str not in fetched_hashes:
                table.remove_row(hash_str)
                self.torrent_map.pop(hash_str)

    def get_selected_hash(self) -> str | None:
        table = self.query_one(DataTable)
        if not table.is_valid_coordinate(table.cursor_coordinate):
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return row_key.value

    # ── Navigation ──────────────────────────────

    def action_cursor_down(self) -> None:
        """Pass Vim motion 'j' down to the data table."""
        self.query_one(DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        """Pass Vim motion 'k' up to the data table."""
        self.query_one(DataTable).action_cursor_up()

    def action_pause(self) -> None:
        t_hash = self.get_selected_hash()
        if t_hash:
            self.client.pause(t_hash)
            self.notify("Paused torrent.")
            self.update_data()

    def action_resume(self) -> None:
        t_hash = self.get_selected_hash()
        if t_hash:
            self.client.resume(t_hash)
            self.notify("Resumed torrent.")
            self.update_data()

    def action_delete(self) -> None:
        t_hash = self.get_selected_hash()
        if not t_hash:
            return

        def check_delete(result: tuple[bool, bool] | None) -> None:
            if not result:
                return
            confirm, delete_files = result
            if confirm:
                self.client.delete(t_hash, delete_files=delete_files)
                self.notify("Torrent deleted.", severity="warning")
                self.update_data()

        self.push_screen(DeleteModal(), check_delete)

    def action_toggle_sort(self) -> None:
        self._sort_by_name = not self._sort_by_name
        table = self.query_one(DataTable)
        table.clear()
        self.torrent_map.clear()
        self.update_data()

    def action_edit_category(self) -> None:
        t_hash = self.get_selected_hash()
        if not t_hash:
            return

        t_data = self.torrent_map.get(t_hash)
        current = t_data.get("category", "") if t_data else ""

        try:
            categories = sorted(self.client.get_categories().keys())
        except Exception as e:
            self.notify(f"Could not fetch categories: {e}", severity="error")
            return

        if not categories:
            self.notify("No categories defined on server.", severity="warning")
            return

        def apply_category(result: str | None) -> None:
            if result is None:
                return
            try:
                self.client.set_category(t_hash, result)
                self.notify(
                    f"Category set to '{result}'." if result else "Category cleared."
                )
                self.update_data()
            except Exception as e:
                self.notify(f"Failed to set category: {e}", severity="error")

        self.push_screen(CategoryModal(current, categories), apply_category)

    def action_info(self) -> None:
        t_hash = self.get_selected_hash()
        if not t_hash:
            return

        t_data = self.torrent_map.get(t_hash)
        if t_data:
            try:
                props = self.client.get_properties(t_hash)
                self.push_screen(InfoModal(t_data, props))
            except Exception as e:
                self.notify(f"Could not load details: {e}", severity="error")


# ─────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────


def main() -> None:
    """Entry point for the qbt CLI."""
    if len(sys.argv) > 1 and sys.argv[1] == "config":
        run_config_flow()
        sys.exit(0)

    client = load_client_from_config()

    if not client:
        console.print(
            "[yellow]Could not connect to qBittorrent. Please configure your settings:[/]"
        )
        run_config_flow()
        client = load_client_from_config()
        if not client:
            console.print("[red]Fatal: Cannot login to qBittorrent. Exiting.[/]")
            sys.exit(1)

    app = QbtApp(client)
    app.run()


if __name__ == "__main__":
    main()
