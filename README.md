# qbt-cli

An interactive terminal UI for [qBittorrent-nox](https://github.com/qbittorrent/qBittorrent) built with [Textual](https://textual.textualize.io/).

## Requirements

- Python 3.10+
- qBittorrent with Web UI enabled

## Install

```bash
pipx install qbt-cli
```

## Usage

```bash
qbt           # launch the TUI
qbt config    # run the setup wizard to update credentials
```

## First run

If no configuration is found, the setup wizard runs automatically. It will prompt for:

- **Host** — e.g. `http://localhost` or `http://192.168.1.10`
- **Port** — default `8080`
- **Username / Password** — your qBittorrent Web UI credentials

Credentials are stored in your OS keyring where available, with a fallback to `~/.config/qbt-cli/config.ini` (stored with chmod 600).

Run `qbt config` at any time to update your connection settings.

## Keybinds

| Key | Action |
|-----|--------|
| `j` / `k` | Move cursor down / up |
| `p` | Pause selected torrent |
| `r` | Resume selected torrent |
| `d` | Delete torrent (prompts to keep or remove files) |
| `c` | Set category from server-defined list |
| `s` | Toggle sort between name and date added |
| `i` | Show torrent details |
| `q` | Quit |

All modal prompts can be navigated with `j` / `k` and confirmed with `Enter`. Press `Escape` to cancel.
