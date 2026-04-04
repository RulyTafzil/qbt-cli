# qbt-tui

An interactive terminal UI for [qBittorrent-nox](https://github.com/qbittorrent/qBittorrent) built with [Textual](https://textual.textualize.io/).

## Install

```bash
pipx install qbt-tui
```

## Usage

```bash
qbt           # launch the TUI
qbt config    # run the setup wizard
```

## First run

If no config is found, the setup wizard runs automatically. It will prompt for:

- **Host** — e.g. `http://localhost` or `http://192.168.1.10`
- **Port** — default `8080`
- **Username / Password** — your qBittorrent Web UI credentials

Credentials are stored in your OS keyring where available, falling back to `~/.config/qbt-cli/config.ini` (chmod 600).

## Keybinds

| Key | Action |
|-----|--------|
| `j` / `k` | Move cursor down / up |
| `p` | Pause selected torrent |
| `r` | Resume selected torrent |
| `d` | Delete torrent (with confirmation) |
| `c` | Set category from server-defined list |
| `s` | Toggle sort: name / date added |
| `i` | Show torrent info |
| `q` | Quit |

## Requirements

- Python 3.10+
- qBittorrent with Web UI enabled
