"""Shares tab: what you share, live settings, and an activity log."""
from __future__ import annotations

import os

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical
from textual.widgets import Button, Checkbox, DataTable, Input, Label, RichLog, Static

from ..util import clock


class SharesPane(Horizontal):
    def compose(self) -> ComposeResult:
        with Vertical(id="shares-left"):
            yield Static(id="shares-title", classes="section-title")
            yield DataTable(id="shares-table", cursor_type="row", zebra_stripes=True)
            with Horizontal(id="shares-add"):
                yield Button("＋ Browse…", variant="primary", id="share-browse")
                yield Input(placeholder="…or type a folder path, e.g. D:\\Music", id="share-path")
                yield Button("Add", id="share-add")
            with Horizontal(id="shares-buttons"):
                yield Button("Remove selected", id="share-remove", variant="error")
                yield Button("Rescan all", id="share-rescan")
            yield Static(" Activity", classes="section-title")
            yield RichLog(id="activity", wrap=True, markup=False)
        with Vertical(id="shares-right"):
            yield Static(" ⚙ Settings", classes="section-title")
            with Grid(id="settings-grid"):
                yield Label("Download folder")
                with Horizontal(id="set-download-row"):
                    yield Input(id="set-download")
                    yield Button("…", id="set-download-browse")
                yield Label("Upload slots")
                yield Input(id="set-slots", type="integer")
                yield Label("Upload limit KB/s (0 = ∞)")
                yield Input(id="set-ulimit", type="integer")
                yield Label("Download limit KB/s")
                yield Input(id="set-dlimit", type="integer")
                yield Label("Hide results under kbps")
                yield Input(id="set-minbr", type="integer")
                yield Label("Listen port")
                yield Input(id="set-port", type="integer")
                yield Label("Profile description")
                yield Input(id="set-desc")
            yield Checkbox("Share my download folder", id="set-sharedl")
            yield Checkbox("UPnP port forwarding", id="set-upnp")
            yield Checkbox("Notify + bell when downloads finish", id="set-notify")
            yield Checkbox("Failed download: try the same file from another user", id="set-fallback")
            yield Button("Save settings", variant="primary", id="set-save")
            yield Static(Text("Port, UPnP and download folder apply on next start; the rest apply now.",
                              "dim"), id="set-note")

    def on_mount(self) -> None:
        t = self.query_one("#shares-table", DataTable)
        t.add_column("Shared folder", key="path")
        t.add_column("Files", key="files", width=9)
        self.app.bus.on("shares.scanned", self._scanned)
        self.app.bus.on("log", self._log)
        self.load_settings()
        self.refresh_table()

    def load_settings(self) -> None:
        c = self.app.cfg
        for wid, v in (("download", c.download_dir), ("slots", c.upload_slots), ("ulimit", c.upload_limit_kbps),
                       ("dlimit", c.download_limit_kbps), ("minbr", c.min_bitrate), ("port", c.listen_port),
                       ("desc", c.description)):
            self.query_one(f"#set-{wid}", Input).value = str(v)
        self.query_one("#set-sharedl", Checkbox).value = c.share_downloads
        self.query_one("#set-upnp", Checkbox).value = c.upnp
        self.query_one("#set-notify", Checkbox).value = c.notify_downloads
        self.query_one("#set-fallback", Checkbox).value = c.auto_fallback

    def refresh_table(self) -> None:
        t = self.query_one("#shares-table", DataTable)
        t.clear()
        dirs = self.app.engine.shared_dirs()
        for path, n in dirs:
            t.add_row(Text("▣ " + path, "bold"), Text(f"{n:,}", "#00e5ff"), key=path)
        folders, files = self.app.engine.share_stats()
        title = Text()
        title.append(" ▣ Shares ", "bold black on #39ff88")
        title.append(f"  {len(dirs)} roots · {folders:,} folders · {files:,} files", "bold")
        self.query_one("#shares-title", Static).update(title)

    def _scanned(self, folders: int, files: int) -> None:
        self.refresh_table()
        self._log(f"share scan complete: {folders:,} folders, {files:,} files", "info")

    def _log(self, msg: str, level: str = "info") -> None:
        color = {"error": "#ff4d6d", "warning": "#ffd23f"}.get(level, "#b388ff")
        self.query_one("#activity", RichLog).write(Text(f"{clock()}  ", "dim") + Text(msg, color))

    @on(Input.Submitted, "#share-path")
    @on(Button.Pressed, "#share-add")
    def _add(self) -> None:
        inp = self.query_one("#share-path", Input)
        path = os.path.abspath(os.path.expanduser(inp.value.strip().strip('"')))
        if not inp.value.strip():
            return
        if not os.path.isdir(path):
            self.notify(f"Not a folder: {path}", severity="error")
            return
        inp.value = ""
        self.add_share(path)

    @on(Button.Pressed, "#share-browse")
    def browse_for_share(self) -> None:
        from ..screens import FolderPickerScreen

        def done(path: str | None) -> None:
            if path:
                self.add_share(path)

        start = self.app.cfg.shared_dirs[-1] if self.app.cfg.shared_dirs else ""
        self.app.push_screen(FolderPickerScreen("Pick a folder to share", start, "Share this folder"), done)

    @on(Button.Pressed, "#set-download-browse")
    def browse_for_download_dir(self) -> None:
        from ..screens import FolderPickerScreen
        inp = self.query_one("#set-download", Input)

        def done(path: str | None) -> None:
            if path:
                inp.value = path
                self.notify("Press Save settings to keep it (applies on next start).")

        self.app.push_screen(FolderPickerScreen("Download folder", inp.value, "Use this folder"), done)

    @work
    async def add_share(self, path: str) -> None:
        cfg = self.app.cfg
        norm = os.path.normcase(os.path.abspath(path))
        if any(os.path.normcase(os.path.abspath(d)) == norm for d in cfg.shared_dirs):
            self.notify(f"Already shared: {path}", severity="warning")
            return
        self._log(f"scanning {path}…")
        try:
            await self.app.engine.add_share(path)
        except Exception as e:
            self.notify(f"Could not share {path}: {e}", severity="error")
            return
        cfg = self.app.cfg
        if path not in cfg.shared_dirs:
            cfg.shared_dirs.append(path)
            cfg.save()
        self.refresh_table()

    @on(Button.Pressed, "#share-remove")
    def _remove(self) -> None:
        t = self.query_one("#shares-table", DataTable)
        if t.row_count:
            self.remove_share(t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value)

    @work
    async def remove_share(self, path: str) -> None:
        try:
            await self.app.engine.remove_share(path)
        except Exception as e:
            self.notify(f"Could not unshare: {e}", severity="error")
            return
        cfg = self.app.cfg
        if path in cfg.shared_dirs:
            cfg.shared_dirs.remove(path)
        if os.path.normcase(path) == os.path.normcase(cfg.download_dir):
            cfg.share_downloads = False
            self.query_one("#set-sharedl", Checkbox).value = False
        cfg.save()
        self.refresh_table()

    @on(Button.Pressed, "#share-rescan")
    def _rescan_pressed(self) -> None:
        self._rescan()

    @work
    async def _rescan(self) -> None:
        self._log("rescanning shares…")
        await self.app.engine.rescan()

    @on(Button.Pressed, "#set-save")
    def _save(self) -> None:
        c = self.app.cfg

        def num(wid: str, default: int) -> int:
            try:
                return max(0, int(self.query_one(f"#set-{wid}", Input).value))
            except ValueError:
                return default

        c.download_dir = self.query_one("#set-download", Input).value.strip() or c.download_dir
        c.upload_slots = max(1, num("slots", c.upload_slots))
        c.upload_limit_kbps = num("ulimit", c.upload_limit_kbps)
        c.download_limit_kbps = num("dlimit", c.download_limit_kbps)
        c.min_bitrate = num("minbr", c.min_bitrate)
        c.listen_port = num("port", c.listen_port) or c.listen_port
        c.description = self.query_one("#set-desc", Input).value
        c.share_downloads = self.query_one("#set-sharedl", Checkbox).value
        c.upnp = self.query_one("#set-upnp", Checkbox).value
        c.notify_downloads = self.query_one("#set-notify", Checkbox).value
        c.auto_fallback = self.query_one("#set-fallback", Checkbox).value
        c.save()
        self.app.engine.apply_limits()
        self.notify("Settings saved", title="⚙")
        self._log("settings saved")
