from __future__ import annotations

import ctypes
import io
import json
import os
import subprocess
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox

from PIL import Image, ImageOps, ImageTk


DEFAULT_WATCH_DIR = Path(r"C:\Users\Administrator\.codex\generated_images")
CONFIG_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "xiaobudian-image-viewer"
CONFIG_FILE = CONFIG_DIR / "config.json"
LEGACY_CONFIG_FILE = Path(os.getenv("APPDATA", str(Path.home()))) / "codex-image-viewer" / "config.json"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

BG = "#FAF7F9"
SIDEBAR = "#FFF1F6"
CARD = "#FFFFFF"
TEXT = "#332233"
SOFT = "#8B6F82"
PINK = "#F4A3C0"
GREEN = "#BDF0CD"
LINE = "#E7D9E2"
ACTIVE = "#FFF7C7"
SCROLL_TRACK = "#FFF7FA"
SCROLL_THUMB = "#F4A3C0"
SCROLL_THUMB_ACTIVE = "#EC86AC"


@dataclass(frozen=True)
class ImageItem:
    path: Path
    mtime: float
    size: int


@dataclass(frozen=True)
class ImageGroup:
    directory: Path
    images: tuple[ImageItem, ...]
    mtime: float


def list_groups(roots: list[Path]) -> list[ImageGroup]:
    grouped: dict[Path, list[ImageItem]] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            grouped.setdefault(path.parent, []).append(ImageItem(path, stat.st_mtime, stat.st_size))

    groups: list[ImageGroup] = []
    for directory, images in grouped.items():
        images.sort(key=lambda item: item.mtime, reverse=True)
        groups.append(ImageGroup(directory, tuple(images), images[0].mtime))
    groups.sort(key=lambda group: group.mtime, reverse=True)
    return groups


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{size}B"


def middle_ellipsis(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    left = max(4, limit // 2 - 2)
    right = max(4, limit - left - 3)
    return f"{text[:left]}...{text[-right:]}"


def load_config() -> dict:
    for path in (CONFIG_FILE, LEGACY_CONFIG_FILE):
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        text = str(path.expanduser())
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(Path(text))
    return result


def load_watch_dirs(config: dict, explicit: Path | None = None) -> list[Path]:
    if explicit is not None:
        return [explicit]
    raw_dirs = config.get("watch_dirs")
    if isinstance(raw_dirs, list):
        paths = [Path(str(item)).expanduser() for item in raw_dirs if str(item).strip()]
        if paths:
            return dedupe_paths(paths)
    legacy = config.get("watch_dir")
    if legacy:
        return [Path(str(legacy)).expanduser()]
    return [DEFAULT_WATCH_DIR]


def save_config(watch_dirs: list[Path]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as fh:
        json.dump({"watch_dirs": [str(path) for path in watch_dirs]}, fh, ensure_ascii=False, indent=2)


def copy_image_to_clipboard(path: Path) -> None:
    if not sys.platform.startswith("win"):
        raise RuntimeError("当前系统不支持直接复制图片到剪贴板。")

    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        buffer = io.BytesIO()
        img.save(buffer, "BMP")
        data = buffer.getvalue()[14:]

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    CF_DIB = 8
    GMEM_MOVEABLE = 0x0002

    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.EmptyClipboard.restype = ctypes.c_bool
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.restype = ctypes.c_bool

    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        raise RuntimeError("GlobalAlloc failed")
    locked = kernel32.GlobalLock(handle)
    if not locked:
        kernel32.GlobalFree(handle)
        raise RuntimeError("GlobalLock failed")
    ctypes.memmove(locked, data, len(data))
    kernel32.GlobalUnlock(handle)

    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(handle)
        raise RuntimeError("OpenClipboard failed")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_DIB, handle):
            kernel32.GlobalFree(handle)
            raise RuntimeError("SetClipboardData failed")
    finally:
        user32.CloseClipboard()


class SlimScrollbar(tk.Canvas):
    def __init__(self, parent: tk.Widget, orient: str, command, bg: str) -> None:
        self.orient = orient
        self.command = command
        self.first = 0.0
        self.last = 1.0
        self.dragging = False
        size = 10
        super().__init__(
            parent,
            width=size if orient == "vertical" else 1,
            height=size if orient == "horizontal" else 1,
            bg=bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.thumb_id: int | None = None
        self.bind("<Configure>", lambda _event: self._redraw())
        self.bind("<Button-1>", self._move_to_event)
        self.bind("<B1-Motion>", self._move_to_event)
        self.bind("<Enter>", lambda _event: self._paint_thumb(SCROLL_THUMB_ACTIVE))
        self.bind("<Leave>", lambda _event: self._paint_thumb(SCROLL_THUMB))

    def set(self, first: str, last: str) -> None:
        self.first = max(0.0, min(1.0, float(first)))
        self.last = max(0.0, min(1.0, float(last)))
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        self.create_rectangle(0, 0, width, height, fill=SCROLL_TRACK, outline="")

        if self.last - self.first >= 0.999:
            self.thumb_id = self.create_rectangle(0, 0, 0, 0, fill=SCROLL_TRACK, outline="")
            return

        if self.orient == "vertical":
            length = height
            min_len = min(42, max(18, length))
            thumb_len = max(min_len, int(length * (self.last - self.first)))
            start = int((length - thumb_len) * self.first / max(0.001, 1.0 - (self.last - self.first)))
            self.thumb_id = self.create_rectangle(2, start, width - 2, start + thumb_len, fill=SCROLL_THUMB, outline="")
        else:
            length = width
            min_len = min(48, max(22, length))
            thumb_len = max(min_len, int(length * (self.last - self.first)))
            start = int((length - thumb_len) * self.first / max(0.001, 1.0 - (self.last - self.first)))
            self.thumb_id = self.create_rectangle(start, 2, start + thumb_len, height - 2, fill=SCROLL_THUMB, outline="")

    def _paint_thumb(self, color: str) -> None:
        if self.thumb_id is not None and self.last - self.first < 0.999:
            self.itemconfigure(self.thumb_id, fill=color)

    def _move_to_event(self, event: tk.Event) -> str:
        if self.last - self.first >= 0.999:
            return "break"
        if self.orient == "vertical":
            length = max(1, self.winfo_height())
            thumb_len = max(18, int(length * (self.last - self.first)))
            pos = event.y - thumb_len / 2
            fraction = pos / max(1, length - thumb_len)
        else:
            length = max(1, self.winfo_width())
            thumb_len = max(22, int(length * (self.last - self.first)))
            pos = event.x - thumb_len / 2
            fraction = pos / max(1, length - thumb_len)
        self.command("moveto", max(0.0, min(1.0, fraction)))
        return "break"


class CodexImageViewer(tk.Tk):
    def __init__(self, watch_dir: Path | None = None) -> None:
        super().__init__()
        config = load_config()
        self.watch_dirs = load_watch_dirs(config, watch_dir)
        self.groups: list[ImageGroup] = []
        self.selected_dir: Path | None = None
        self.selected_index = 0
        self.thumb_refs: dict[str, ImageTk.PhotoImage] = {}
        self.thumb_cache: dict[tuple[Path, int, float], ImageTk.PhotoImage] = {}
        self.placeholder_cache: dict[int, ImageTk.PhotoImage] = {}
        self.group_cards: dict[Path, tuple[tk.Widget, ...]] = {}
        self.preview_ref: ImageTk.PhotoImage | None = None
        self.preview_image_id: int | None = None
        self.preview_text_id: int | None = None
        self.preview_image_box = (0, 0, 1, 1)
        self.lazy_thumb_index = 0
        self.zoom = 1.0
        self.poll_ms = 1500
        self.last_signature: tuple[tuple[str, float, int], ...] = ()

        self.title("小不点图片预览器")
        self.geometry("1240x780")
        self.minsize(980, 640)
        self.configure(bg=BG)

        self._build_ui()
        self.status_var.set("正在启动，图片会在窗口打开后逐步加载...")
        self.after(80, self._initial_load)

    def _initial_load(self) -> None:
        self.refresh(force=True)
        self.after(self.poll_ms, self._poll)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=BG, padx=20, pady=14)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        tk.Label(header, text="小不点图片预览器", bg=BG, fg=TEXT, font=("Microsoft YaHei UI", 22, "bold")).grid(row=0, column=0, sticky="w")
        self.status_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self.status_var, bg=BG, fg=SOFT, font=("Microsoft YaHei UI", 10)).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._button(header, "刷新", self.refresh, PINK).grid(row=0, column=1, rowspan=2, padx=(8, 0))
        self._button(header, "系统配置", self._open_settings, "#FFE9A8").grid(row=0, column=2, rowspan=2, padx=(8, 0))
        self._button(header, "打开当前目录", self._open_selected_dir, GREEN).grid(row=0, column=3, rowspan=2, padx=(8, 0))

        sidebar = tk.Frame(self, bg=SIDEBAR, padx=12, pady=12, width=410)
        sidebar.grid(row=1, column=0, sticky="nsew", padx=(20, 10), pady=(0, 20))
        sidebar.grid_rowconfigure(1, weight=1)
        sidebar.grid_propagate(False)
        tk.Label(sidebar, text="图片目录", bg=SIDEBAR, fg=TEXT, font=("Microsoft YaHei UI", 15, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 10))

        list_wrap, self.list_canvas, self.list_body = self._scroll_area(sidebar, SIDEBAR)
        list_wrap.grid(row=1, column=0, sticky="nsew")

        preview = tk.Frame(self, bg=CARD, padx=18, pady=18, highlightthickness=1, highlightbackground=LINE)
        preview.grid(row=1, column=1, sticky="nsew", padx=(0, 20), pady=(0, 20))
        preview.grid_columnconfigure(0, weight=1)
        preview.grid_rowconfigure(1, weight=1)

        top = tk.Frame(preview, bg=CARD)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        top.grid_columnconfigure(0, weight=1)
        self.title_var = tk.StringVar(value="等待图片")
        self.meta_var = tk.StringVar(value=self._watch_dirs_text())
        tk.Label(top, textvariable=self.title_var, bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(top, textvariable=self.meta_var, bg=CARD, fg=SOFT, font=("Microsoft YaHei UI", 10)).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._button(top, "上一张", self.prev_image, PINK).grid(row=0, column=1, rowspan=2, padx=(8, 0))
        self._button(top, "下一张", self.next_image, PINK).grid(row=0, column=2, rowspan=2, padx=(8, 0))
        self._button(top, "复制图片", self.copy_selected_image, GREEN).grid(row=0, column=3, rowspan=2, padx=(8, 0))
        self._button(top, "重置缩放", self.zoom_reset, "#F4EAF0").grid(row=0, column=4, rowspan=2, padx=(8, 0))

        self.preview_area = tk.Frame(preview, bg="#F7F3F6")
        self.preview_area.grid(row=1, column=0, sticky="nsew")
        self.preview_area.grid_columnconfigure(0, weight=1)
        self.preview_area.grid_rowconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(self.preview_area, bg="#F7F3F6", highlightthickness=0)
        self.preview_vbar = SlimScrollbar(self.preview_area, orient="vertical", command=self.preview_canvas.yview, bg="#F7F3F6")
        self.preview_hbar = SlimScrollbar(self.preview_area, orient="horizontal", command=self.preview_canvas.xview, bg="#F7F3F6")
        self.preview_canvas.configure(xscrollcommand=self.preview_hbar.set, yscrollcommand=self.preview_vbar.set)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_vbar.grid(row=0, column=1, sticky="ns")
        self.preview_hbar.grid(row=1, column=0, sticky="ew")
        self.preview_area.bind("<Configure>", lambda _event: self._show_selected())
        self.preview_canvas.bind("<MouseWheel>", self._zoom_by_wheel)
        self.preview_canvas.bind("<ButtonPress-1>", self._start_preview_pan)
        self.preview_canvas.bind("<B1-Motion>", self._pan_preview)
        self.bind("<Left>", lambda _event: self.prev_image())
        self.bind("<Right>", lambda _event: self.next_image())
        self.bind("<Control-c>", lambda _event: self.copy_selected_image())
        self.bind("<Control-0>", lambda _event: self.zoom_reset())
        self.bind("<plus>", lambda _event: self.zoom_in())
        self.bind("<equal>", lambda _event: self.zoom_in())
        self.bind("<minus>", lambda _event: self.zoom_out())

        strip_wrap = tk.Frame(preview, bg=CARD)
        strip_wrap.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        strip_wrap.grid_columnconfigure(0, weight=1)
        thumb_wrap, self.strip_canvas, self.strip_body = self._scroll_area(strip_wrap, CARD, horizontal=True)
        thumb_wrap.grid(row=0, column=0, sticky="ew")
        self.strip_canvas.configure(height=108)

    def _scroll_area(self, parent: tk.Widget, bg: str, horizontal: bool = False) -> tuple[tk.Frame, tk.Canvas, tk.Frame]:
        wrap = tk.Frame(parent, bg=bg)
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(0, weight=1)
        canvas = tk.Canvas(wrap, bg=bg, highlightthickness=0)
        orient = "horizontal" if horizontal else "vertical"
        scrollbar = SlimScrollbar(wrap, orient=orient, command=canvas.xview if horizontal else canvas.yview, bg=bg)
        if horizontal:
            canvas.configure(xscrollcommand=scrollbar.set)
            canvas.grid(row=0, column=0, sticky="ew")
            scrollbar.grid(row=1, column=0, sticky="ew")
        else:
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.grid(row=0, column=0, sticky="nsew")
            scrollbar.grid(row=0, column=1, sticky="ns")
        body = tk.Frame(canvas, bg=bg)
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        if horizontal:
            canvas.bind("<MouseWheel>", lambda event: self._scroll_canvas(event, canvas, horizontal=True))
            body.bind("<MouseWheel>", lambda event: self._scroll_canvas(event, canvas, horizontal=True))
        else:
            canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
            canvas.bind("<MouseWheel>", lambda event: self._scroll_canvas(event, canvas))
            body.bind("<MouseWheel>", lambda event: self._scroll_canvas(event, canvas))
        return wrap, canvas, body

    def _button(self, parent: tk.Widget, text: str, command, bg: str) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=bg, fg=TEXT, activebackground=bg, relief="flat", bd=0, padx=16, pady=9, font=("Microsoft YaHei UI", 10, "bold"), cursor="hand2")

    def _scroll_canvas(self, event: tk.Event, canvas: tk.Canvas, horizontal: bool = False) -> str:
        amount = int(-1 * (event.delta / 120))
        if horizontal:
            canvas.xview_scroll(amount, "units")
        else:
            canvas.yview_scroll(amount, "units")
        return "break"

    def _zoom_by_wheel(self, event: tk.Event) -> str:
        if self._current_item() is None:
            return "break"
        self._set_zoom(self.zoom * (1.12 if event.delta > 0 else 1 / 1.12), event.x, event.y)
        return "break"

    def _start_preview_pan(self, event: tk.Event) -> None:
        self.preview_canvas.scan_mark(event.x, event.y)

    def _pan_preview(self, event: tk.Event) -> str:
        self.preview_canvas.scan_dragto(event.x, event.y, gain=1)
        return "break"

    def zoom_in(self) -> str:
        self._set_zoom(self.zoom * 1.12)
        return "break"

    def zoom_out(self) -> str:
        self._set_zoom(self.zoom / 1.12)
        return "break"

    def _set_zoom(self, zoom: float, anchor_x: int | None = None, anchor_y: int | None = None) -> None:
        old_x, old_y, old_w, old_h = self.preview_image_box
        if anchor_x is None:
            anchor_x = max(1, self.preview_canvas.winfo_width()) // 2
        if anchor_y is None:
            anchor_y = max(1, self.preview_canvas.winfo_height()) // 2

        canvas_x = self.preview_canvas.canvasx(anchor_x)
        canvas_y = self.preview_canvas.canvasy(anchor_y)
        rel_x = (canvas_x - old_x) / max(1, old_w)
        rel_y = (canvas_y - old_y) / max(1, old_h)

        self.zoom = max(0.2, min(6.0, zoom))
        self._show_selected()

        new_x, new_y, new_w, new_h = self.preview_image_box
        target_x = new_x + rel_x * new_w - anchor_x
        target_y = new_y + rel_y * new_h - anchor_y
        self._move_preview_view(target_x, target_y)

    def _move_preview_view(self, left: float, top: float) -> None:
        bbox = self.preview_canvas.bbox("all")
        if not bbox:
            return
        region_w = max(1, bbox[2] - bbox[0])
        region_h = max(1, bbox[3] - bbox[1])
        self.preview_canvas.xview_moveto(max(0.0, min(1.0, (left - bbox[0]) / region_w)))
        self.preview_canvas.yview_moveto(max(0.0, min(1.0, (top - bbox[1]) / region_h)))

    def _poll(self) -> None:
        try:
            self.refresh(force=False)
        finally:
            self.after(self.poll_ms, self._poll)

    def refresh(self, force: bool = True) -> None:
        groups = list_groups(self.watch_dirs)
        signature = tuple((str(item.path), item.mtime, item.size) for group in groups for item in group.images)
        if not force and signature == self.last_signature:
            return
        self.last_signature = signature
        old_dir = self.selected_dir
        self.groups = groups
        existing_dirs = {group.directory for group in groups}
        if old_dir not in existing_dirs:
            self.selected_dir = groups[0].directory if groups else None
            self.selected_index = 0
            self.zoom = 1.0
        self._render_groups()
        self._render_strip()
        self._show_selected()
        image_count = sum(len(group.images) for group in groups)
        self.status_var.set(f"监听 {len(self.watch_dirs)} 个目录    共 {len(groups)} 个图片目录 / {image_count} 张图片，自动刷新 {self.poll_ms / 1000:.1f}s")

    def _current_group(self) -> ImageGroup | None:
        if self.selected_dir is None:
            return None
        return next((group for group in self.groups if group.directory == self.selected_dir), None)

    def _current_item(self) -> ImageItem | None:
        group = self._current_group()
        if not group or not group.images:
            return None
        self.selected_index = max(0, min(self.selected_index, len(group.images) - 1))
        return group.images[self.selected_index]

    def _render_groups(self) -> None:
        self.lazy_thumb_index = 0
        for child in self.list_body.winfo_children():
            child.destroy()
        self.group_cards.clear()
        keys_to_keep: set[str] = set()
        if not self.groups:
            tk.Label(self.list_body, text="还没有发现图片目录", bg=SIDEBAR, fg=SOFT, font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=20)
            return
        for group in self.groups[:160]:
            self._render_group_card(group, keys_to_keep)
        for key in list(self.thumb_refs):
            if key not in keys_to_keep:
                self.thumb_refs.pop(key, None)

    def _render_group_card(self, group: ImageGroup, keys_to_keep: set[str]) -> None:
        active = group.directory == self.selected_dir
        bg = ACTIVE if active else CARD
        row = tk.Frame(self.list_body, bg=bg, padx=10, pady=10, highlightthickness=1, highlightbackground=LINE, cursor="hand2")
        row.pack(fill="x", pady=(0, 10))

        thumbs = tk.Frame(row, bg=bg, cursor="hand2")
        thumbs.pack(side="left")
        card_widgets: list[tk.Widget] = [row, thumbs]
        for i, item in enumerate(group.images[:4]):
            key = f"group:{group.directory}:{i}:{item.path}"
            keys_to_keep.add(key)
            label = self._lazy_thumb_label(thumbs, key, item.path, 58, bg)
            card_widgets.append(label)
            label.grid(row=i // 2, column=i % 2, padx=2, pady=2)
            label.bind("<Button-1>", lambda _event, d=group.directory: self._select_group(d))
            label.bind("<MouseWheel>", lambda event: self._scroll_canvas(event, self.list_canvas))

        info = tk.Frame(row, bg=bg, cursor="hand2")
        card_widgets.append(info)
        info.pack(side="left", fill="x", expand=True, padx=(10, 0))
        title = tk.Label(info, text=middle_ellipsis(group.directory.name, 32), bg=bg, fg=TEXT, font=("Microsoft YaHei UI", 10, "bold"), cursor="hand2")
        card_widgets.append(title)
        title.pack(anchor="w")
        detail = tk.Label(info, text=f"{len(group.images)} 张图片", bg=bg, fg=SOFT, font=("Microsoft YaHei UI", 9), cursor="hand2")
        card_widgets.append(detail)
        detail.pack(anchor="w", pady=(4, 0))
        latest_label = tk.Label(info, text=middle_ellipsis(str(group.directory), 38), bg=bg, fg=SOFT, font=("Microsoft YaHei UI", 8), cursor="hand2")
        card_widgets.append(latest_label)
        latest_label.pack(anchor="w", pady=(4, 0))

        self.group_cards[group.directory] = tuple(card_widgets)
        for widget in card_widgets:
            widget.bind("<Button-1>", lambda _event, d=group.directory: self._select_group(d))
            widget.bind("<MouseWheel>", lambda event: self._scroll_canvas(event, self.list_canvas))

    def _render_strip(self) -> None:
        for child in self.strip_body.winfo_children():
            child.destroy()
        group = self._current_group()
        if not group:
            return
        for idx, item in enumerate(group.images[:120]):
            active = idx == self.selected_index
            bg = ACTIVE if active else "#F7F3F6"
            cell = tk.Frame(self.strip_body, bg=bg, padx=5, pady=5, highlightthickness=1, highlightbackground=LINE, cursor="hand2")
            cell.grid(row=0, column=idx, padx=(0, 8), sticky="n")
            key = f"strip:{idx}:{item.path}"
            image_label = self._lazy_thumb_label(cell, key, item.path, 84, bg)
            image_label.pack()
            cell.bind("<Button-1>", lambda _event, i=idx: self._select_image(i))
            cell.bind("<MouseWheel>", lambda event: self._scroll_canvas(event, self.strip_canvas, horizontal=True))
            image_label.bind("<Button-1>", lambda _event, i=idx: self._select_image(i))
            image_label.bind("<MouseWheel>", lambda event: self._scroll_canvas(event, self.strip_canvas, horizontal=True))

    def _lazy_thumb_label(self, parent: tk.Widget, key: str, path: Path, size: int, bg: str) -> tk.Label:
        cached = self._cached_thumb(path, size)
        thumb = cached or self._placeholder_thumb(size)
        self.thumb_refs[key] = thumb
        label = tk.Label(parent, image=thumb, bg=bg, cursor="hand2")
        if cached is None:
            delay = 20 + self.lazy_thumb_index * 12
            self.lazy_thumb_index += 1
            self.after(delay, lambda: self._finish_lazy_thumb(label, key, path, size))
        return label

    def _cached_thumb(self, path: Path, size: int) -> ImageTk.PhotoImage | None:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        return self.thumb_cache.get((path, size, mtime))

    def _placeholder_thumb(self, size: int) -> ImageTk.PhotoImage:
        cached = self.placeholder_cache.get(size)
        if cached is not None:
            return cached
        canvas = Image.new("RGBA", (size, size), (247, 243, 246, 255))
        thumb = ImageTk.PhotoImage(canvas)
        self.placeholder_cache[size] = thumb
        return thumb

    def _finish_lazy_thumb(self, label: tk.Label, key: str, path: Path, size: int) -> None:
        if not label.winfo_exists():
            return
        thumb = self._make_thumb(path, size)
        self.thumb_refs[key] = thumb
        try:
            label.configure(image=thumb)
        except tk.TclError:
            pass

    def _make_thumb(self, path: Path, size: int) -> ImageTk.PhotoImage:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0
        cache_key = (path, size, mtime)
        cached = self.thumb_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            with Image.open(path) as img:
                img = ImageOps.exif_transpose(img).convert("RGBA")
                img.thumbnail((size, size), Image.Resampling.LANCZOS)
                canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))
                canvas.alpha_composite(img, ((size - img.width) // 2, (size - img.height) // 2))
        except Exception:
            canvas = Image.new("RGBA", (size, size), (240, 220, 230, 255))
        thumb = ImageTk.PhotoImage(canvas)
        self.thumb_cache[cache_key] = thumb
        if len(self.thumb_cache) > 900:
            for old_key in list(self.thumb_cache)[:180]:
                self.thumb_cache.pop(old_key, None)
        return thumb

    def _select_group(self, directory: Path) -> None:
        if directory == self.selected_dir:
            return
        old_dir = self.selected_dir
        self.selected_dir = directory
        self.selected_index = 0
        self.zoom = 1.0
        self._paint_group_card(old_dir, CARD)
        self._paint_group_card(directory, ACTIVE)
        self._render_strip()
        self._show_selected()

    def _paint_group_card(self, directory: Path | None, color: str) -> None:
        if directory is None:
            return
        for widget in self.group_cards.get(directory, ()):
            try:
                widget.configure(bg=color)
            except tk.TclError:
                pass

    def _select_image(self, index: int) -> None:
        self.selected_index = index
        self.zoom = 1.0
        self._render_strip()
        self._show_selected()
        self.after(20, lambda: self._scroll_strip_to_index(index))

    def _scroll_strip_to_index(self, index: int) -> None:
        group = self._current_group()
        if not group or len(group.images) <= 1:
            return
        visible_count = min(len(group.images), 120)
        fraction = max(0.0, min(1.0, index / max(1, visible_count - 1)))
        self.strip_canvas.xview_moveto(fraction)

    def prev_image(self) -> None:
        group = self._current_group()
        if not group:
            return
        self.selected_index = (self.selected_index - 1) % len(group.images)
        self.zoom = 1.0
        self._render_strip()
        self._show_selected()

    def next_image(self) -> None:
        group = self._current_group()
        if not group:
            return
        self.selected_index = (self.selected_index + 1) % len(group.images)
        self.zoom = 1.0
        self._render_strip()
        self._show_selected()

    def _show_selected(self) -> None:
        if not hasattr(self, "preview_canvas"):
            return
        if self.preview_canvas.winfo_width() <= 20 or self.preview_canvas.winfo_height() <= 20:
            self.after(60, self._show_selected)
            return

        item = self._current_item()
        if not item or not item.path.exists():
            self.preview_ref = None
            self._set_preview_message("暂无图片")
            self.title_var.set("等待图片")
            self.meta_var.set(self._watch_dirs_text())
            return

        path = item.path
        try:
            with Image.open(path) as img:
                original_w, original_h = img.size
                img = ImageOps.exif_transpose(img).convert("RGBA")
                viewport_w = max(1, self.preview_canvas.winfo_width() - 4)
                viewport_h = max(1, self.preview_canvas.winfo_height() - 4)
                fit_scale = min(viewport_w / max(1, img.width), viewport_h / max(1, img.height))
                scale = max(0.01, fit_scale * self.zoom)
                display_w = max(1, int(img.width * scale))
                display_h = max(1, int(img.height * scale))
                img = img.resize((display_w, display_h), Image.Resampling.LANCZOS)
                self.preview_ref = ImageTk.PhotoImage(img)
        except Exception as exc:
            self.preview_ref = None
            self._set_preview_message(f"图片读取失败：{exc}")
            return
        self._set_preview_image(display_w, display_h)
        group = self._current_group()
        count = len(group.images) if group else 1
        self.title_var.set(f"{path.name}  ({self.selected_index + 1}/{count})")
        self.meta_var.set(f"{original_w} × {original_h} · {human_size(item.size)} · 缩放 {self.zoom:.0%} · {path.parent}")

    def _set_preview_message(self, text: str) -> None:
        self.preview_canvas.delete("all")
        width = max(1, self.preview_canvas.winfo_width())
        height = max(1, self.preview_canvas.winfo_height())
        self.preview_text_id = self.preview_canvas.create_text(width // 2, height // 2, text=text, fill=SOFT, font=("Microsoft YaHei UI", 16))
        self.preview_image_id = None
        self.preview_image_box = (0, 0, 1, 1)
        self.preview_canvas.configure(scrollregion=(0, 0, width, height))

    def _set_preview_image(self, width: int, height: int) -> None:
        canvas_w = max(1, self.preview_canvas.winfo_width())
        canvas_h = max(1, self.preview_canvas.winfo_height())
        x = max(0, (canvas_w - width) // 2)
        y = max(0, (canvas_h - height) // 2)
        self.preview_canvas.delete("all")
        self.preview_image_id = self.preview_canvas.create_image(x, y, anchor="nw", image=self.preview_ref)
        self.preview_text_id = None
        self.preview_image_box = (x, y, width, height)
        region_w = max(canvas_w, x + width)
        region_h = max(canvas_h, y + height)
        self.preview_canvas.configure(scrollregion=(0, 0, region_w, region_h))

    def copy_selected_image(self) -> None:
        item = self._current_item()
        if not item:
            messagebox.showinfo("未选择图片", "请先选择一张图片。", parent=self)
            return
        try:
            copy_image_to_clipboard(item.path)
            self.status_var.set(f"已复制图片到剪贴板：{item.path.name}")
        except Exception as exc:
            self.clipboard_clear()
            self.clipboard_append(str(item.path))
            self.status_var.set(f"图片复制失败，已改为复制路径：{item.path}")
            messagebox.showwarning("复制图片失败", f"{exc}\n\n已改为复制图片路径。", parent=self)

    def zoom_reset(self) -> None:
        self.zoom = 1.0
        self._show_selected()

    def _open_selected_dir(self) -> None:
        if self.selected_dir:
            self._open_path(self.selected_dir)
        elif self.watch_dirs:
            self._open_path(self.watch_dirs[0])

    def _open_settings(self) -> None:
        win = tk.Toplevel(self)
        win.title("系统配置")
        win.geometry("800x460")
        win.minsize(700, 390)
        win.configure(bg=BG)
        win.transient(self)
        win.grab_set()

        card = tk.Frame(win, bg=CARD, padx=24, pady=22, highlightthickness=1, highlightbackground=LINE)
        card.pack(fill="both", expand=True, padx=18, pady=18)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(3, weight=1)

        tk.Label(card, text="系统配置", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(card, text="每行一个监听目录。保存后会立即重新扫描，只展示图片。", bg=CARD, fg=SOFT, font=("Microsoft YaHei UI", 10)).grid(row=1, column=0, sticky="w", pady=(8, 18))
        tk.Label(card, text="监听目录", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 10, "bold")).grid(row=2, column=0, sticky="w", pady=(0, 8))

        text = tk.Text(card, bg="#F2FBF4", fg=TEXT, insertbackground=TEXT, relief="flat", bd=0, font=("Microsoft YaHei UI", 10), height=8)
        text.grid(row=3, column=0, sticky="nsew")
        text.insert("1.0", "\n".join(str(path) for path in self.watch_dirs))

        actions = tk.Frame(card, bg=CARD)
        actions.grid(row=4, column=0, sticky="ew", pady=(18, 0))
        self._button(actions, "添加目录", lambda: self._browse_add_dir(text), PINK).pack(side="left")
        self._button(actions, "恢复默认", lambda: self._replace_text(text, str(DEFAULT_WATCH_DIR)), "#F4EAF0").pack(side="left", padx=(8, 0))
        self._button(actions, "保存并刷新", lambda: self._save_settings(win, text.get("1.0", "end")), GREEN).pack(side="right")
        self._button(actions, "取消", win.destroy, "#F4EAF0").pack(side="right", padx=(0, 8))
        text.focus_set()

    def _browse_add_dir(self, text: tk.Text) -> None:
        initial = str(self.selected_dir or self.watch_dirs[0] if self.watch_dirs else DEFAULT_WATCH_DIR.parent)
        path = filedialog.askdirectory(parent=self, title="添加监听目录", initialdir=initial if Path(initial).exists() else str(DEFAULT_WATCH_DIR.parent))
        if path:
            current = text.get("1.0", "end").strip()
            self._replace_text(text, f"{current}\n{path}" if current else path)

    def _replace_text(self, text: tk.Text, value: str) -> None:
        text.delete("1.0", "end")
        text.insert("1.0", value)

    def _save_settings(self, win: tk.Toplevel, raw_text: str) -> None:
        paths = dedupe_paths([Path(line.strip()).expanduser() for line in raw_text.splitlines() if line.strip()])
        if not paths:
            messagebox.showerror("目录无效", "至少需要配置一个监听目录。", parent=win)
            return
        invalid = [path for path in paths if not path.exists() or not path.is_dir()]
        if invalid:
            messagebox.showerror("目录无效", f"这些路径不存在或不是文件夹：\n{chr(10).join(str(path) for path in invalid)}", parent=win)
            return
        self.watch_dirs = paths
        save_config(paths)
        self.groups = []
        self.selected_dir = None
        self.selected_index = 0
        self.zoom = 1.0
        self.last_signature = ()
        self.refresh(force=True)
        win.destroy()

    def _watch_dirs_text(self) -> str:
        return "；".join(str(path) for path in self.watch_dirs)

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc), parent=self)


def main() -> None:
    app = CodexImageViewer()
    app.mainloop()
