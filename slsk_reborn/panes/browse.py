"""Browse tab: explore another user's shared folders."""
from __future__ import annotations

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, LoadingIndicator, Static, Tree
from textual.widgets.tree import TreeNode

from ..engine import FileEntry, Folder
from ..util import basename, human_duration, human_size, quality_text, split_path


class FolderTree(Tree):
    BINDINGS = [Binding("d", "download_folder", "Download folder")]

    def action_download_folder(self) -> None:
        node = self.cursor_node
        if node is not None:
            self.app.query_one(BrowsePane).download_node(node)


class FileTable(DataTable):
    BINDINGS = [Binding("d", "download", "Download")]

    def action_download(self) -> None:
        self.app.query_one(BrowsePane).download_selected_file()


class BrowsePane(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(id="browse-bar"):
            yield Static("◉", id="browse-icon")
            yield Input(placeholder="username to browse…", id="browse-user")
            yield Button("Browse", variant="primary", id="browse-go")
            yield Button("User info", id="browse-info")
        yield LoadingIndicator(id="browse-loading")
        with Horizontal(id="browse-body"):
            yield FolderTree("shares", id="browse-tree")
            yield FileTable(id="browse-files", cursor_type="row", zebra_stripes=True)
        yield Static(id="browse-status")

    def on_mount(self) -> None:
        self.user = ""
        self.folders: dict[str, Folder] = {}
        self.query_one("#browse-loading").display = False
        t = self.query_one(FileTable)
        t.add_column("File", key="file")
        t.add_column("Size", key="size", width=8)
        t.add_column("Quality", key="q", width=10)
        t.add_column("Len", key="len", width=7)
        self.files: list[FileEntry] = []
        self.query_one("#browse-status", Static).update(
            Text(" Enter a username. On the tree: d downloads a folder (with subfolders). "
                 "On files: enter downloads.", "dim"))

    @on(Input.Submitted, "#browse-user")
    @on(Button.Pressed, "#browse-go")
    def _go(self) -> None:
        u = self.query_one("#browse-user", Input).value.strip()
        if u:
            self.load(u)

    @on(Button.Pressed, "#browse-info")
    def _info(self) -> None:
        u = self.query_one("#browse-user", Input).value.strip()
        if u:
            self.app.show_user(u)

    @work(exclusive=True)
    async def load(self, user: str, focus_path: str | None = None) -> None:
        self.query_one("#browse-user", Input).value = user
        loading = self.query_one("#browse-loading")
        loading.display = True
        status = self.query_one("#browse-status", Static)
        status.update(Text(f" Asking {user} for their file list… (big shares can take a minute)", "#ffd23f"))
        try:
            folders = await self.app.engine.browse(user)
        except Exception as e:
            loading.display = False
            status.update(Text(f" Could not browse {user}: {type(e).__name__} {e}", "#ff4d6d"))
            return
        loading.display = False
        self.user = user
        self.folders = {f.path: f for f in folders}
        self._build_tree(user, folders, focus_path)
        nfiles = sum(len(f.files) for f in folders)
        size = sum(x.size for f in folders for x in f.files)
        status.update(Text.assemble((f" {user}", "bold #ff2bd6"),
                                    f"  {len(folders):,} folders · {nfiles:,} files · {human_size(size)}",
                                    ("   d = download folder · enter = download file", "dim")))

    def _build_tree(self, user: str, folders: list[Folder], focus_path: str | None) -> None:
        tree = self.query_one(FolderTree)
        tree.clear()
        tree.root.set_label(Text(f"◉ {user}", "bold #ff2bd6"))
        tree.root.data = ""
        nodes: dict[str, TreeNode] = {"": tree.root}
        focus_dir = focus_path[:max(focus_path.rfind("\\"), focus_path.rfind("/"))] if focus_path else None
        target = None
        for f in sorted(folders, key=lambda f: f.path.lower()):
            parts = split_path(f.path)
            acc = ""
            for p in parts:
                parent = nodes[acc]
                acc = f"{acc}\\{p}" if acc else p
                if acc not in nodes:
                    label = Text(("🔒 " if f.locked and acc == "\\".join(parts) else "") + p)
                    nodes[acc] = parent.add(label, data=acc)
            leaf = nodes["\\".join(parts)]
            if f.files:
                leaf.label.append(f"  {len(f.files)}", "dim")
            if focus_dir and "\\".join(split_path(focus_dir)) == "\\".join(parts):
                target = leaf
        tree.root.expand()
        node = tree.root
        while len(node.children) == 1:  # open single-child chains down to the albums
            node = node.children[0]
            node.expand()
        if target is None:  # land on the first folder that actually holds files
            n = node
            while n.children and not (self._folder_for(n.data or "") or Folder("")).files:
                n = n.children[0]
            target = n
        if target is not None:
            n = target
            while n is not None:
                n.expand()
                n = n.parent
            self.call_after_refresh(tree.move_cursor, target)
            self._show_folder(target.data)
        tree.focus()

    def _folder_for(self, key: str) -> Folder | None:
        for path, f in self.folders.items():
            if "\\".join(split_path(path)) == key:
                return f
        return None

    def _show_folder(self, key: str) -> None:
        t = self.query_one(FileTable)
        t.clear()
        f = self._folder_for(key)
        self.files = list(f.files) if f else []
        for i, x in enumerate(self.files):
            t.add_row(Text(basename(x.path), "bold" if not f.locked else "dim"), human_size(x.size),
                      quality_text(x.ext, x.bitrate), human_duration(x.duration), key=str(i))

    @on(Tree.NodeHighlighted, "#browse-tree")
    def _hl(self, e: Tree.NodeHighlighted) -> None:
        if e.node.data is not None:
            self._show_folder(e.node.data)

    @on(DataTable.RowSelected, "#browse-files")
    def _file(self, e: DataTable.RowSelected) -> None:
        self.download_selected_file()

    def download_selected_file(self) -> None:
        t = self.query_one(FileTable)
        if not t.row_count:
            return
        x = self.files[int(t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value)]
        self.app.start_download(self.user, x.path, x.size)

    def download_node(self, node: TreeNode) -> None:
        key = node.data or ""
        def inside(path: str) -> bool:
            p = "\\".join(split_path(path))
            return not key or p == key or p.startswith(key + "\\")

        files = [x for path, f in self.folders.items() if not f.locked and inside(path) for x in f.files]
        if not files:
            self.notify("No downloadable files in that folder.", severity="warning")
            return
        self.app.start_many(self.user, files)
