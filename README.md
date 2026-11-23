# slsk-reborn

A Soulseek client for the terminal, built on [Textual](https://textual.textualize.io/) and [aioslsk](https://github.com/JurgenR/aioslsk). You can search, download, share, browse users and chat without leaving the terminal.

![search](docs/search.svg)

## Features

- **Search**: each search gets its own tab and results stream in live. Results show a quality badge (green FLAC, bitrate for lossy files), the peer's speed and whether they have a free slot. You can filter as you type (`flac`, `>256`, `-live`) and sort by quality, speed, size or user. One key downloads a file, another downloads the whole album folder. Stop a search with `x` or the Stop button; each search also stops itself at 10,000 files.
- **Album view**: `a` groups results into one row per folder, with track count, size, format and a completeness mark (`✔` when the track numbers run 1..n without gaps, `9/12` when some are missing). Enter downloads the album.
- **Tracklists**: paste a list of `Artist - Title` lines (numbers and timestamps are fine) with `ctrl+o` or the **♫ Tracklist** button. Each track is searched, the best copy is picked (right artist and title, no unasked-for remix, best quality, free slot) and queued, and the ♫ tab follows every download. It reads the `tracklist.txt` that [mixgrab](https://github.com/avtii/mixgrab) writes for a YouTube mix: `slsk-reborn --tracklist tracklist.txt`.
- **Transfers**: downloads and uploads update live with progress bars, speed, ETA and queue place. Keys pause, resume or retry, abort, remove, clear finished transfers and open the folder. Downloads keep the album folder structure. A notification (and terminal bell) says when downloads finish.
- **Another source**: when a download fails, the same file is looked up at other users (same size, or the same name and nearly the same size) and the best one is queued instead. This happens once by itself; `n` does it by hand, for example when a download is stuck far back in a queue.
- **Player**: enter on a finished download plays it, and the rest of its folder follows. MP3, FLAC, WAV and OGG play built in; other formats play through mpv or ffplay if one is installed. `space` pauses, `←` `→` (or `[` `]`) seek 10 seconds, `shift+←` `shift+→` a minute, `-` `+` change the volume, `<` `>` skip. The arrows seek only while something is playing; otherwise they work as usual.
- **Wishlist, friends, blocked users** (`ctrl+l`): wishlist searches are re-run by the server every few minutes and new results open in a ★ tab (`w` adds the current search). Blocked users can't message you, see your searches, browse you or download from you, and their results are hidden. Friend or block anyone from their user card (`i`).
- **Browse**: opens another user's shares as a folder tree with a file list. Press `d` on a folder to download it and everything below it.
- **Chat**: rooms with a user list, private messages, unread badges, highlights when someone mentions your name, and `/join` `/leave` `/msg` `/rooms` `/clear`.
- **Sharing**: pick folders to share with a built-in folder browser (drives, home, Music), or type a path. Remove or rescan them. You can also share your download folder, and set upload slots and upload/download speed limits, which apply live. UPnP port mapping is optional.
- **Looks**: three themes (`slsk-neon`, `slsk-amber`, `slsk-matrix`; cycle with `ctrl+t`), a top bar with live speeds, and a command palette (`ctrl+p`).
- **First start**: a short note explains that Soulseek is about sharing and which ports to open on your router if UPnP can't.
- **Demo mode**: `--demo` runs the whole UI against a simulated network, which is handy for trying it out without an account.

| Transfers | Browse |
|---|---|
| ![transfers](docs/transfers.svg) | ![browse](docs/browse.svg) |
| **Chat** | **Shares & settings** |
| ![chat](docs/chat.svg) | ![shares](docs/shares.svg) |

## Download

Ready-to-run executables (no Python needed) are on the [Releases page](https://github.com/avtii/slsk-reborn/releases/latest):

| System | File |
|---|---|
| Windows 10/11 (64-bit) | `slsk-reborn-windows-x64.exe` |
| macOS, Apple Silicon (M1 and later) | `slsk-reborn-macos-arm64` |
| macOS, Intel | `slsk-reborn-macos-x64` |
| Linux x86-64 (glibc 2.35+) | `slsk-reborn-linux-x64` |
| Linux ARM64 (glibc 2.35+, e.g. Raspberry Pi 4/5 with a 64-bit OS) | `slsk-reborn-linux-arm64` |

Run them from a terminal: Windows Terminal on Windows, Terminal or iTerm2 on macOS.

- **Windows:** SmartScreen may warn about an unknown publisher because the exe is not signed. Click *More info* → *Run anyway*.
- **macOS:** the binary is not notarized. Make it executable and clear the quarantine flag once:
  ```sh
  chmod +x slsk-reborn-macos-arm64
  xattr -d com.apple.quarantine slsk-reborn-macos-arm64
  ./slsk-reborn-macos-arm64
  ```

## Linux

### Ready-made binary

Works on any glibc distro from 2022 on: Ubuntu 22.04+, Debian 12+, Fedora 36+, Linux Mint 21+,
Pop!_OS 22.04+, Arch, Manjaro, openSUSE Leap 15.5+/Tumbleweed, and others.

```sh
curl -LO https://github.com/avtii/slsk-reborn/releases/latest/download/slsk-reborn-linux-x64
chmod +x slsk-reborn-linux-x64
sudo install -m 755 slsk-reborn-linux-x64 /usr/local/bin/slsk-reborn
slsk-reborn
```

On ARM64 use `slsk-reborn-linux-arm64`. Alpine and other musl distros can't run the binary; use one of
the Python installs below.

### Install with Python (any distro)

Distros mark the system Python as externally managed, so install into an isolated tool environment
with **pipx** or **uv**. You get a `slsk-reborn` command on your PATH, and updating is one command.

| Distro | Setup | Install |
|---|---|---|
| Ubuntu 24.04+, Debian 12+, Mint 22+ | `sudo apt install pipx && pipx ensurepath` | `pipx install slsk-reborn` |
| Fedora | `sudo dnf install pipx && pipx ensurepath` | same |
| Arch, Manjaro, EndeavourOS | `sudo pacman -S python-pipx && pipx ensurepath` | same |
| Ubuntu 22.04, Mint 21, openSUSE, others | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `uv tool install slsk-reborn` |

Open a new terminal after `ensurepath` or the uv installer so the PATH change applies. Update with
`pipx upgrade slsk-reborn` or `uv tool upgrade slsk-reborn`. Python 3.11+ is needed. On Ubuntu 22.04
(Python 3.10) use the uv line, which downloads a current Python on its own.

### Build the executable yourself

```sh
# Debian/Ubuntu: sudo apt install git python3-venv binutils
# Fedora:        sudo dnf install git python3 binutils
# Arch:          sudo pacman -S git python binutils
git clone https://github.com/avtii/slsk-reborn
cd slsk-reborn
python3 -m venv .venv && . .venv/bin/activate
pip install . pyinstaller
python packaging/build.py          # -> dist/slsk-reborn-linux-<arch>
./dist/slsk-reborn-linux-* --self-test
```

PyInstaller uses `objdump` from binutils. The binary only runs on systems with the same or a newer glibc
than the one it was built on.

## Install with Python (Windows, macOS, Linux)

Requires Python 3.11 or newer. slsk-reborn is [on PyPI](https://pypi.org/project/slsk-reborn/):

```sh
pipx install slsk-reborn        # or: uv tool install slsk-reborn   /   pip install slsk-reborn
```

The latest code from GitHub: `pipx install git+https://github.com/avtii/slsk-reborn`. From a clone:

```sh
git clone https://github.com/avtii/slsk-reborn
cd slsk-reborn
pip install -e ".[dev]"
```

## Run

```sh
slsk-reborn            # connect (asks for login on first start)
slsk-reborn --demo     # offline demo with fake peers
slsk-reborn --theme slsk-matrix
slsk-reborn --port 2234  # listening port for this run (also uses 2235)
slsk-reborn --tracklist tracklist.txt   # find and download every track in a list
python -m slsk_reborn  # same thing
```

On the first start a login box opens. A Soulseek account is created automatically the first time you log in with a new name. **Use a different account from any other Soulseek client you run.** The server allows only one session per name, so two clients on the same account keep kicking each other off.

![login](docs/login.svg)

## Keys

| Where | Key | Action |
|---|---|---|
| everywhere | `1`–`5` / `F2`–`F6` | switch tab |
| | `/` or `ctrl+f` | new search |
| | `esc` | leave a text box (so single-key shortcuts work) |
| | `?` / `F1` | help |
| | `ctrl+t` | cycle theme |
| | `ctrl+l` | wishlist, friends, blocked users |
| | `ctrl+o` | download a tracklist |
| | `space` `←` `→` `-` `+` `<` `>` | player: pause, seek (also `[` `]`; shift = 1 min), volume, prev/next |
| | `ctrl+q` or `ctrl+c` | quit: saves transfers and logs out (`ctrl+c` copies instead when text is selected; press it again to leave without waiting) |
| search results | `enter` / `d` | download file |
| | `f` | download whole folder |
| | `a` | album view on/off |
| | `w` | add the search to the wishlist |
| | `b` / `i` / `m` | browse user / user info / message |
| | `s` | cycle sort |
| | `x` | stop search (keeps the results) |
| | `ctrl+w` | close search tab |
| transfers | `enter` | play a finished download |
| | `p` `r` `x` `del` | pause, resume/retry, abort, remove |
| | `n` | get the same file from another user |
| | `c` / `o` | clear finished / open folder |
| ♫ tracklist | `enter` / `r` / `x` | search a track yourself / retry it / stop the rest |
| browse | `d` on a folder | download it and its subfolders |

The filter box above the results takes words to include, `-word` to exclude, `flac`/`mp3`/`lossless` for format, and `>256` for a minimum bitrate.

## Files

Everything lives in `~/.slsk-reborn/` (set `SLSK_REBORN_HOME` to move it):

- `config.toml`: account, folders, limits, theme, rooms, wishlist, friends and blocked users. It is written with `chmod 600` because it holds your password.
- `shares/` and `transfers/`: caches, so the shares index and the transfer queue survive restarts.
- `slsk-reborn.log`: run with `--debug` for full protocol logging.

Downloads go to `~/Music/slsk-reborn` by default. You can change this in the Shares tab.

**Port:** the default listening port is `61000` (plus `61001` for obfuscated connections). Change it in the Shares tab or for a single run with `--port N` / `-p N`. Forward it on your router, or enable UPnP, so that other peers can connect to you. If they can't, some uploads and downloads will fail to start.

## Development

```sh
pytest                       # UI tests run against the demo engine
python docs/make_screenshots.py
pip install pyinstaller && python packaging/build.py   # executable for this OS in dist/
```

Pushing a `v*` tag builds the executables, publishes the GitHub release and uploads the package to PyPI. See [RELEASING.md](RELEASING.md).

The UI talks only to an `Engine` interface (`slsk_reborn/engine.py`) through plain dataclasses and a small event bus. `SlskEngine` wraps aioslsk, and `DemoEngine` (`slsk_reborn/demo.py`) simulates the network for tests and screenshots.

## License

MIT
