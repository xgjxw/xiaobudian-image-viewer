from __future__ import annotations

import ctypes
import io
import json
import os
import subprocess
import sys
import tkinter as tk
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from tkinter import filedialog, messagebox

from PIL import Image, ImageDraw, ImageOps, ImageTk


DEFAULT_WATCH_DIR = Path(r"C:\Users\Administrator\.codex\generated_images")
DEFAULT_EXTRA_WATCH_DIRS = [
    Path(r"D:\workspace\myself\xiaobudian-audio-library"),
    Path(r"D:\workspace\myself\xiaobudian-video-library"),
]
CONFIG_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "xiaobudian-image-viewer"
CONFIG_FILE = CONFIG_DIR / "config.json"
LEGACY_CONFIG_FILE = Path(os.getenv("APPDATA", str(Path.home()))) / "codex-image-viewer" / "config.json"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".m4v"}
ALL_EXTS = IMAGE_EXTS | AUDIO_EXTS | VIDEO_EXTS

VOICE_DISPLAY_NAMES = {
    "zh-CN-XiaoxiaoNeural": "女声-温柔（晓晓）",
    "zh-CN-XiaoyiNeural": "女声-甜美（晓伊）",
    "zh-CN-YunjianNeural": "男声-专业（云健）",
    "zh-CN-YunxiNeural": "男声-磁性（云希）",
    "zh-CN-YunyangNeural": "男声-新闻（云扬）",
    "zh-CN-YunyeNeural": "男声-自然（云野）",
    "zh-CN-YunfengNeural": "男声-沉稳（云锋）",
    "zh-CN-liaoning-XiaobeiNeural": "女声-东北（小北）",
    "zh-CN-YunxiaNeural": "男声-年轻（云夏）",
    "zh-CN-shaanxi-XiaoniNeural": "女声-陕西（小妮）",
}

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


class MediaKind(str, Enum):
    ALL = "all"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


KIND_LABEL = {
    MediaKind.ALL: "全部",
    MediaKind.IMAGE: "图片",
    MediaKind.AUDIO: "音频",
    MediaKind.VIDEO: "视频",
}


@dataclass(frozen=True)
class MediaItem:
    path: Path
    kind: MediaKind
    mtime: float
    size: int


@dataclass(frozen=True)
class MediaGroup:
    directory: Path
    items: tuple[MediaItem, ...]
    mtime: float


def media_kind(path: Path) -> MediaKind | None:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTS:
        return MediaKind.IMAGE
    if suffix in AUDIO_EXTS:
        return MediaKind.AUDIO
    if suffix in VIDEO_EXTS:
        return MediaKind.VIDEO
    return None


def list_groups(roots: list[Path], active_kind: MediaKind) -> list[MediaGroup]:
    return groups_from_items(scan_media_items(roots), active_kind)


def scan_media_items(roots: list[Path]) -> list[MediaItem]:
    items: list[MediaItem] = []
    grouped: dict[Path, list[MediaItem]] = {}
    seen_files: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in ALL_EXTS:
                continue
            file_key = str(path.resolve()).lower()
            if file_key in seen_files:
                continue
            seen_files.add(file_key)
            kind = media_kind(path)
            if kind is None:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            items.append(MediaItem(path, kind, stat.st_mtime, stat.st_size))
    return items


def groups_from_items(items: list[MediaItem], active_kind: MediaKind) -> list[MediaGroup]:
    grouped: dict[Path, list[MediaItem]] = {}
    for item in items:
        if active_kind != MediaKind.ALL and item.kind != active_kind:
            continue
        grouped.setdefault(item.path.parent, []).append(item)
    groups: list[MediaGroup] = []
    for directory, group_items in grouped.items():
        group_items.sort(key=lambda item: item.mtime, reverse=True)
        groups.append(MediaGroup(directory, tuple(group_items), group_items[0].mtime))
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


def display_media_name(path: Path) -> str:
    stem = path.stem
    if stem in VOICE_DISPLAY_NAMES:
        return VOICE_DISPLAY_NAMES[stem]
    return path.name


class WindowsAudioPlayer:
    def __init__(self) -> None:
        self.alias = "xiaobudian_audio"
        self.current: Path | None = None

    def play(self, path: Path) -> None:
        if not sys.platform.startswith("win"):
            raise RuntimeError("内置音频播放当前只支持 Windows。")
        self.stop()
        quoted = str(path).replace('"', "")
        self._mci(f'open "{quoted}" alias {self.alias}')
        self.current = path
        self._mci(f"play {self.alias}")

    def stop(self) -> None:
        if not sys.platform.startswith("win"):
            return
        self._mci(f"stop {self.alias}", check=False)
        self._mci(f"close {self.alias}", check=False)
        self.current = None

    def _mci(self, command: str, check: bool = True) -> None:
        winmm = ctypes.windll.winmm
        buffer = ctypes.create_unicode_buffer(512)
        code = winmm.mciSendStringW(command, buffer, len(buffer), None)
        if check and code:
            err = ctypes.create_unicode_buffer(512)
            winmm.mciGetErrorStringW(code, err, len(err))
            raise RuntimeError(err.value or f"MCI command failed: {command}")


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
    return default_watch_dirs()


def default_watch_dirs() -> list[Path]:
    return dedupe_paths([DEFAULT_WATCH_DIR, *[path for path in DEFAULT_EXTRA_WATCH_DIRS if path.exists()]])


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
        self.active_kind = MediaKind.ALL
        self.all_items: list[MediaItem] = []
        self.groups: list[MediaGroup] = []
        self.selected_dir: Path | None = None
        self.selected_index = 0
        self.thumb_refs: dict[str, ImageTk.PhotoImage] = {}
        self.thumb_cache: dict[tuple[Path, int, float], ImageTk.PhotoImage] = {}
        self.icon_cache: dict[tuple[MediaKind, int], ImageTk.PhotoImage] = {}
        self.placeholder_cache: dict[int, ImageTk.PhotoImage] = {}
        self.group_cards: dict[Path, tuple[tk.Widget, ...]] = {}
        self.kind_buttons: dict[MediaKind, tk.Button] = {}
        self.preview_ref: ImageTk.PhotoImage | None = None
        self.preview_image_box = (0, 0, 1, 1)
        self.lazy_thumb_index = 0
        self.zoom = 1.0
        self.audio_player = WindowsAudioPlayer()
        self.video_cap = None
        self.video_after_id: str | None = None
        self.video_playing_path: Path | None = None
        self.poll_ms = 1500
        self.last_signature: tuple[tuple[str, str, float, int], ...] = ()

        self.title("小不点媒体预览器")
        self.geometry("1240x780")
        self.minsize(980, 640)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self.status_var.set("正在启动，媒体会在窗口打开后逐步加载...")
        self.after(80, self._initial_load)

    def _on_close(self) -> None:
        self._stop_video()
        self.audio_player.stop()
        self.destroy()

    def _initial_load(self) -> None:
        self.refresh(force=True)
        self.after(self.poll_ms, self._poll)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=BG, padx=20, pady=14)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        tk.Label(header, text="小不点媒体预览器", bg=BG, fg=TEXT, font=("Microsoft YaHei UI", 22, "bold")).grid(row=0, column=0, sticky="w")
        self.status_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self.status_var, bg=BG, fg=SOFT, font=("Microsoft YaHei UI", 10)).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._button(header, "刷新", self.refresh, PINK).grid(row=0, column=1, rowspan=2, padx=(8, 0))
        self._button(header, "系统配置", self._open_settings, "#FFE9A8").grid(row=0, column=2, rowspan=2, padx=(8, 0))
        self._button(header, "打开当前目录", self._open_selected_dir, GREEN).grid(row=0, column=3, rowspan=2, padx=(8, 0))

        sidebar = tk.Frame(self, bg=SIDEBAR, padx=12, pady=12, width=410)
        sidebar.grid(row=1, column=0, sticky="nsew", padx=(20, 10), pady=(0, 20))
        sidebar.grid_rowconfigure(2, weight=1)
        sidebar.grid_propagate(False)
        tk.Label(sidebar, text="媒体目录", bg=SIDEBAR, fg=TEXT, font=("Microsoft YaHei UI", 15, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 10))

        filter_bar = tk.Frame(sidebar, bg=SIDEBAR)
        filter_bar.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for kind in (MediaKind.ALL, MediaKind.IMAGE, MediaKind.AUDIO, MediaKind.VIDEO):
            btn = self._button(filter_bar, KIND_LABEL[kind], lambda k=kind: self._set_kind(k), ACTIVE if kind == self.active_kind else "#F4EAF0")
            btn.pack(side="left", padx=(0, 6))
            self.kind_buttons[kind] = btn

        list_wrap, self.list_canvas, self.list_body = self._scroll_area(sidebar, SIDEBAR)
        list_wrap.grid(row=2, column=0, sticky="nsew")

        preview = tk.Frame(self, bg=CARD, padx=18, pady=18, highlightthickness=1, highlightbackground=LINE)
        preview.grid(row=1, column=1, sticky="nsew", padx=(0, 20), pady=(0, 20))
        preview.grid_columnconfigure(0, weight=1)
        preview.grid_rowconfigure(1, weight=1)

        top = tk.Frame(preview, bg=CARD)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        top.grid_columnconfigure(0, weight=1)
        self.title_var = tk.StringVar(value="等待媒体")
        self.meta_var = tk.StringVar(value=self._watch_dirs_text())
        tk.Label(top, textvariable=self.title_var, bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(top, textvariable=self.meta_var, bg=CARD, fg=SOFT, font=("Microsoft YaHei UI", 10)).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._button(top, "上一个", self.prev_item, PINK).grid(row=0, column=1, rowspan=2, padx=(8, 0))
        self._button(top, "下一个", self.next_item, PINK).grid(row=0, column=2, rowspan=2, padx=(8, 0))
        self.copy_button = self._button(top, "复制图片", self.copy_selected_image, GREEN)
        self.copy_button.grid(row=0, column=3, rowspan=2, padx=(8, 0))
        self.open_button = self._button(top, "播放", self.play_selected_media, "#D6E7FF")
        self.open_button.grid(row=0, column=4, rowspan=2, padx=(8, 0))
        self.stop_button = self._button(top, "停止", self.stop_playback, "#F4EAF0")
        self.stop_button.grid(row=0, column=5, rowspan=2, padx=(8, 0))
        self._button(top, "重置缩放", self.zoom_reset, "#F4EAF0").grid(row=0, column=6, rowspan=2, padx=(8, 0))

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
        self.preview_canvas.bind("<Double-Button-1>", lambda _event: self.play_selected_media())
        self.bind("<Left>", lambda _event: self.prev_item())
        self.bind("<Right>", lambda _event: self.next_item())
        self.bind("<Control-c>", lambda _event: self.copy_selected_image())
        self.bind("<Control-0>", lambda _event: self.zoom_reset())
        self.bind("<plus>", lambda _event: self.zoom_in())
        self.bind("<equal>", lambda _event: self.zoom_in())
        self.bind("<minus>", lambda _event: self.zoom_out())
        self.bind("<F5>", lambda _event: self.refresh())

        self.strip_wrap = tk.Frame(preview, bg=CARD)
        self.strip_wrap.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.strip_wrap.grid_columnconfigure(0, weight=1)
        thumb_wrap, self.strip_canvas, self.strip_body = self._scroll_area(self.strip_wrap, CARD, horizontal=True)
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
        return tk.Button(parent, text=text, command=command, bg=bg, fg=TEXT, activebackground=bg, relief="flat", bd=0, padx=14, pady=8, font=("Microsoft YaHei UI", 10, "bold"), cursor="hand2")

    def _set_kind(self, kind: MediaKind) -> None:
        if kind == self.active_kind:
            return
        self.active_kind = kind
        for item_kind, button in self.kind_buttons.items():
            button.configure(bg=ACTIVE if item_kind == kind else "#F4EAF0", activebackground=ACTIVE if item_kind == kind else "#F4EAF0")
        if not self.all_items:
            self.refresh(force=True)
            return
        self.selected_dir = None
        self.selected_index = 0
        self.zoom = 1.0
        self.groups = groups_from_items(self.all_items, self.active_kind)
        self.selected_dir = self.groups[0].directory if self.groups else None
        self._render_groups()
        self._render_strip()
        self._update_strip_visibility()
        self._show_selected()
        counts = self._counts()
        self.status_var.set(
            f"已从缓存切换分类：{KIND_LABEL[self.active_kind]} · "
            f"目录 {len(self.groups)} 个 / 图片 {counts[MediaKind.IMAGE]} / 音频 {counts[MediaKind.AUDIO]} / 视频 {counts[MediaKind.VIDEO]}"
        )

    def _scroll_canvas(self, event: tk.Event, canvas: tk.Canvas, horizontal: bool = False) -> str:
        amount = int(-1 * (event.delta / 120))
        if horizontal:
            canvas.xview_scroll(amount, "units")
        else:
            canvas.yview_scroll(amount, "units")
        return "break"

    def _zoom_by_wheel(self, event: tk.Event) -> str:
        item = self._current_item()
        if item is None or item.kind != MediaKind.IMAGE:
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
        item = self._current_item()
        if item is None or item.kind != MediaKind.IMAGE:
            return
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
        items = scan_media_items(self.watch_dirs)
        signature = tuple((str(item.path), item.kind.value, item.mtime, item.size) for item in items)
        if not force and signature == self.last_signature:
            return
        self.last_signature = signature
        self.all_items = items
        groups = groups_from_items(items, self.active_kind)
        old_dir = self.selected_dir
        self.groups = groups
        existing_dirs = {group.directory for group in groups}
        if old_dir not in existing_dirs:
            self.selected_dir = groups[0].directory if groups else None
            self.selected_index = 0
            self.zoom = 1.0
        self._render_groups()
        self._render_strip()
        self._update_strip_visibility()
        self._show_selected()
        counts = self._counts()
        self.status_var.set(
            f"监听 {len(self.watch_dirs)} 个目录 · 当前分类：{KIND_LABEL[self.active_kind]} · "
            f"目录 {len(groups)} 个 / 图片 {counts[MediaKind.IMAGE]} / 音频 {counts[MediaKind.AUDIO]} / 视频 {counts[MediaKind.VIDEO]} · "
            f"自动刷新 {self.poll_ms / 1000:.1f}s"
        )

    def _counts(self) -> dict[MediaKind, int]:
        counts = {MediaKind.IMAGE: 0, MediaKind.AUDIO: 0, MediaKind.VIDEO: 0}
        for item in self.all_items:
            counts[item.kind] += 1
        return counts

    def _current_group(self) -> MediaGroup | None:
        if self.selected_dir is None:
            return None
        return next((group for group in self.groups if group.directory == self.selected_dir), None)

    def _current_item(self) -> MediaItem | None:
        group = self._current_group()
        if not group or not group.items:
            return None
        self.selected_index = max(0, min(self.selected_index, len(group.items) - 1))
        return group.items[self.selected_index]

    def _render_groups(self) -> None:
        self.lazy_thumb_index = 0
        for child in self.list_body.winfo_children():
            child.destroy()
        self.group_cards.clear()
        keys_to_keep: set[str] = set()
        if not self.groups:
            tk.Label(self.list_body, text=f"还没有发现{KIND_LABEL[self.active_kind]}媒体", bg=SIDEBAR, fg=SOFT, font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=20)
            return
        for group in self.groups[:160]:
            self._render_group_card(group, keys_to_keep)
        for key in list(self.thumb_refs):
            if key not in keys_to_keep:
                self.thumb_refs.pop(key, None)

    def _render_group_card(self, group: MediaGroup, keys_to_keep: set[str]) -> None:
        active = group.directory == self.selected_dir
        bg = ACTIVE if active else CARD
        row = tk.Frame(self.list_body, bg=bg, padx=10, pady=10, highlightthickness=1, highlightbackground=LINE, cursor="hand2")
        row.pack(fill="x", pady=(0, 10))

        thumbs = tk.Frame(row, bg=bg, cursor="hand2")
        thumbs.pack(side="left")
        card_widgets: list[tk.Widget] = [row, thumbs]
        for i, item in enumerate(group.items[:4]):
            key = f"group:{group.directory}:{i}:{item.path}"
            keys_to_keep.add(key)
            label = self._lazy_thumb_label(thumbs, key, item, 58, bg)
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
        counts = self._group_counts(group)
        detail = tk.Label(info, text=f"{len(group.items)} 个媒体 · 图 {counts[MediaKind.IMAGE]} / 音 {counts[MediaKind.AUDIO]} / 视 {counts[MediaKind.VIDEO]}", bg=bg, fg=SOFT, font=("Microsoft YaHei UI", 9), cursor="hand2")
        card_widgets.append(detail)
        detail.pack(anchor="w", pady=(4, 0))
        latest_label = tk.Label(info, text=middle_ellipsis(str(group.directory), 38), bg=bg, fg=SOFT, font=("Microsoft YaHei UI", 8), cursor="hand2")
        card_widgets.append(latest_label)
        latest_label.pack(anchor="w", pady=(4, 0))

        self.group_cards[group.directory] = tuple(card_widgets)
        for widget in card_widgets:
            widget.bind("<Button-1>", lambda _event, d=group.directory: self._select_group(d))
            widget.bind("<MouseWheel>", lambda event: self._scroll_canvas(event, self.list_canvas))

    def _group_counts(self, group: MediaGroup) -> dict[MediaKind, int]:
        counts = {MediaKind.IMAGE: 0, MediaKind.AUDIO: 0, MediaKind.VIDEO: 0}
        for item in group.items:
            counts[item.kind] += 1
        return counts

    def _render_strip(self) -> None:
        for child in self.strip_body.winfo_children():
            child.destroy()
        group = self._current_group()
        if not group:
            return
        for idx, item in enumerate(group.items[:120]):
            active = idx == self.selected_index
            bg = ACTIVE if active else "#F7F3F6"
            cell = tk.Frame(self.strip_body, bg=bg, padx=5, pady=5, highlightthickness=1, highlightbackground=LINE, cursor="hand2")
            cell.grid(row=0, column=idx, padx=(0, 8), sticky="n")
            key = f"strip:{idx}:{item.path}"
            image_label = self._lazy_thumb_label(cell, key, item, 84, bg)
            image_label.pack()
            label_text = display_media_name(item.path) if item.kind == MediaKind.AUDIO else KIND_LABEL[item.kind]
            tk.Label(cell, text=middle_ellipsis(label_text, 12), bg=bg, fg=SOFT, font=("Microsoft YaHei UI", 8), width=12).pack()
            cell.bind("<Button-1>", lambda _event, i=idx: self._select_item(i))
            cell.bind("<MouseWheel>", lambda event: self._scroll_canvas(event, self.strip_canvas, horizontal=True))
            image_label.bind("<Button-1>", lambda _event, i=idx: self._select_item(i))
            image_label.bind("<MouseWheel>", lambda event: self._scroll_canvas(event, self.strip_canvas, horizontal=True))

    def _update_strip_visibility(self) -> None:
        if self.active_kind == MediaKind.AUDIO:
            self.strip_wrap.grid_remove()
        else:
            self.strip_wrap.grid(row=2, column=0, sticky="ew", pady=(12, 0))

    def _lazy_thumb_label(self, parent: tk.Widget, key: str, item: MediaItem, size: int, bg: str) -> tk.Label:
        cached = self._cached_thumb(item, size)
        thumb = cached or self._placeholder_thumb(size)
        self.thumb_refs[key] = thumb
        label = tk.Label(parent, image=thumb, bg=bg, cursor="hand2")
        if cached is None:
            delay = 20 + self.lazy_thumb_index * 12
            self.lazy_thumb_index += 1
            self.after(delay, lambda: self._finish_lazy_thumb(label, key, item, size))
        return label

    def _cached_thumb(self, item: MediaItem, size: int) -> ImageTk.PhotoImage | None:
        try:
            mtime = item.path.stat().st_mtime
        except OSError:
            return None
        return self.thumb_cache.get((item.path, size, mtime))

    def _placeholder_thumb(self, size: int) -> ImageTk.PhotoImage:
        cached = self.placeholder_cache.get(size)
        if cached is not None:
            return cached
        canvas = Image.new("RGBA", (size, size), (247, 243, 246, 255))
        thumb = ImageTk.PhotoImage(canvas)
        self.placeholder_cache[size] = thumb
        return thumb

    def _finish_lazy_thumb(self, label: tk.Label, key: str, item: MediaItem, size: int) -> None:
        if not label.winfo_exists():
            return
        thumb = self._make_thumb(item, size)
        self.thumb_refs[key] = thumb
        try:
            label.configure(image=thumb)
        except tk.TclError:
            pass

    def _make_thumb(self, item: MediaItem, size: int) -> ImageTk.PhotoImage:
        try:
            mtime = item.path.stat().st_mtime
        except OSError:
            mtime = 0
        cache_key = (item.path, size, mtime)
        cached = self.thumb_cache.get(cache_key)
        if cached is not None:
            return cached
        if item.kind == MediaKind.IMAGE:
            canvas = self._image_thumb(item.path, size)
        elif item.kind == MediaKind.VIDEO:
            canvas = self._video_thumb(item.path, size) or self._icon_thumb(MediaKind.VIDEO, size)
        else:
            canvas = self._icon_thumb(MediaKind.AUDIO, size)
        thumb = ImageTk.PhotoImage(canvas)
        self.thumb_cache[cache_key] = thumb
        if len(self.thumb_cache) > 900:
            for old_key in list(self.thumb_cache)[:180]:
                self.thumb_cache.pop(old_key, None)
        return thumb

    def _image_thumb(self, path: Path, size: int) -> Image.Image:
        try:
            with Image.open(path) as img:
                img = ImageOps.exif_transpose(img).convert("RGBA")
                img.thumbnail((size, size), Image.Resampling.LANCZOS)
                canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))
                canvas.alpha_composite(img, ((size - img.width) // 2, (size - img.height) // 2))
                return canvas
        except Exception:
            return self._icon_thumb(MediaKind.IMAGE, size)

    def _video_thumb(self, path: Path, size: int) -> Image.Image | None:
        try:
            import cv2  # type: ignore

            cap = cv2.VideoCapture(str(path))
            ok, frame = cap.read()
            cap.release()
            if not ok:
                return None
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
            img = Image.fromarray(frame)
            img.thumbnail((size, size), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))
            canvas.alpha_composite(img, ((size - img.width) // 2, (size - img.height) // 2))
            draw = ImageDraw.Draw(canvas)
            draw.polygon([(size * 0.42, size * 0.34), (size * 0.42, size * 0.66), (size * 0.68, size * 0.50)], fill=(255, 255, 255, 220), outline=(60, 40, 60))
            return canvas
        except Exception:
            return None

    def _icon_thumb(self, kind: MediaKind, size: int) -> Image.Image:
        cache_key = (kind, size)
        cached = self.icon_cache.get(cache_key)
        if cached is not None:
            return ImageTk.getimage(cached).copy()
        color = {MediaKind.IMAGE: "#FFD6E7", MediaKind.AUDIO: "#D9F3FF", MediaKind.VIDEO: "#E6DDFF"}.get(kind, "#F7F3F6")
        symbol = {MediaKind.IMAGE: "图", MediaKind.AUDIO: "♪", MediaKind.VIDEO: "▶"}.get(kind, "?")
        canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle((4, 4, size - 4, size - 4), radius=max(8, size // 7), fill=color, outline="#E7D9E2", width=2)
        if kind == MediaKind.AUDIO:
            base_y = int(size * 0.70)
            for i, height_ratio in enumerate((0.18, 0.34, 0.26, 0.48, 0.30, 0.40, 0.22)):
                x = int(size * (0.20 + i * 0.10))
                bar_h = int(size * height_ratio)
                draw.rounded_rectangle((x, base_y - bar_h, x + max(3, size // 24), base_y), radius=3, fill="#58A7C8")
        elif kind == MediaKind.VIDEO:
            draw.rounded_rectangle((int(size * 0.18), int(size * 0.24), int(size * 0.82), int(size * 0.72)), radius=max(4, size // 14), fill="#F7F3FF", outline="#7B65B5", width=2)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", max(16, size // 3))
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), symbol, font=font)
        draw.text(((size - (bbox[2] - bbox[0])) / 2, (size - (bbox[3] - bbox[1])) / 2 - 2), symbol, fill=TEXT, font=font)
        photo = ImageTk.PhotoImage(canvas)
        self.icon_cache[cache_key] = photo
        return canvas

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

    def _select_item(self, index: int) -> None:
        self.selected_index = index
        self.zoom = 1.0
        self._render_strip()
        self._show_selected()
        self.after(20, lambda: self._scroll_strip_to_index(index))

    def _scroll_strip_to_index(self, index: int) -> None:
        group = self._current_group()
        if not group or len(group.items) <= 1:
            return
        visible_count = min(len(group.items), 120)
        fraction = max(0.0, min(1.0, index / max(1, visible_count - 1)))
        self.strip_canvas.xview_moveto(fraction)

    def prev_item(self) -> None:
        group = self._current_group()
        if not group:
            return
        self.selected_index = (self.selected_index - 1) % len(group.items)
        self.zoom = 1.0
        self._render_strip()
        self._show_selected()

    def next_item(self) -> None:
        group = self._current_group()
        if not group:
            return
        self.selected_index = (self.selected_index + 1) % len(group.items)
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
            self._set_preview_message("暂无媒体")
            self.title_var.set("等待媒体")
            self.meta_var.set(self._watch_dirs_text())
            return
        if item.kind != MediaKind.VIDEO:
            self._stop_video()
        self.copy_button.configure(state="normal" if item.kind == MediaKind.IMAGE else "disabled")
        self.open_button.configure(text="播放音频" if item.kind == MediaKind.AUDIO else "预览视频" if item.kind == MediaKind.VIDEO else "打开图片")
        if item.kind == MediaKind.IMAGE:
            self._show_image(item)
        elif item.kind == MediaKind.AUDIO:
            self._show_audio_playlist(item)
        else:
            self._show_media_card(item)

    def _show_image(self, item: MediaItem) -> None:
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
        count = len(group.items) if group else 1
        self.title_var.set(f"{display_media_name(path)}  ({self.selected_index + 1}/{count})")
        self.meta_var.set(f"{original_w} x {original_h} · {human_size(item.size)} · 缩放 {self.zoom:.0%} · {path.parent}")

    def _show_media_card(self, item: MediaItem) -> None:
        self.preview_canvas.delete("all")
        width = max(1, self.preview_canvas.winfo_width())
        height = max(1, self.preview_canvas.winfo_height())
        self.preview_canvas.configure(scrollregion=(0, 0, width, height))
        self.preview_image_box = (0, 0, 1, 1)
        cx = width // 2
        if item.kind == MediaKind.VIDEO:
            self._draw_video_preview_frame(item, autoplay=False)
            return
        self.preview_ref = self._make_thumb(item, min(240, max(150, width // 4)))
        top = 42
        self.preview_canvas.create_image(cx, top + 105, image=self.preview_ref)
        self.preview_canvas.create_text(cx, top + 235, text="音频试听", fill=TEXT, font=("Microsoft YaHei UI", 22, "bold"))
        self.preview_canvas.create_text(cx, top + 280, text=display_media_name(item.path), fill=TEXT, font=("Microsoft YaHei UI", 15), width=max(320, width - 160))
        self.preview_canvas.create_text(cx, top + 322, text=f"{human_size(item.size)} · {item.path.suffix.lower()} · 双击或点击“播放音频”在程序内播放", fill=SOFT, font=("Microsoft YaHei UI", 11), width=max(320, width - 160))
        group = self._current_group()
        count = len(group.items) if group else 1
        self.title_var.set(f"{display_media_name(item.path)}  ({self.selected_index + 1}/{count})")
        self.meta_var.set(f"{KIND_LABEL[item.kind]} · {human_size(item.size)} · {item.path.parent}")

    def _show_audio_playlist(self, item: MediaItem) -> None:
        self.preview_canvas.delete("all")
        width = max(1, self.preview_canvas.winfo_width())
        height = max(1, self.preview_canvas.winfo_height())
        group = self._current_group()
        if not group:
            self._set_preview_message("暂无音频")
            return

        rows = [(idx, audio) for idx, audio in enumerate(group.items) if audio.kind == MediaKind.AUDIO]
        row_h = 74
        pad_x = 26
        y = 24
        self.preview_canvas.create_text(
            pad_x,
            y,
            text="音色试听列表",
            anchor="nw",
            fill=TEXT,
            font=("Microsoft YaHei UI", 22, "bold"),
        )
        self.preview_canvas.create_text(
            pad_x,
            y + 38,
            text="点击任意音频即可在程序内播放，不会额外打开播放器。",
            anchor="nw",
            fill=SOFT,
            font=("Microsoft YaHei UI", 11),
        )
        y += 86

        for order, (idx, audio) in enumerate(rows, start=1):
            active = idx == self.selected_index
            bg = ACTIVE if active else CARD
            outline = PINK if active else LINE
            tag = f"audio_row_{idx}"
            self.preview_canvas.create_rectangle(
                pad_x,
                y,
                max(pad_x + 300, width - pad_x),
                y + row_h - 10,
                fill=bg,
                outline=outline,
                width=2 if active else 1,
                tags=(tag,),
            )
            self.preview_canvas.create_oval(
                pad_x + 18,
                y + 15,
                pad_x + 54,
                y + 51,
                fill="#D9F3FF",
                outline="#58A7C8",
                tags=(tag,),
            )
            self.preview_canvas.create_text(
                pad_x + 36,
                y + 32,
                text="♪",
                fill=TEXT,
                font=("Microsoft YaHei UI", 18, "bold"),
                tags=(tag,),
            )
            self.preview_canvas.create_text(
                pad_x + 72,
                y + 13,
                text=f"{order:02d}. {display_media_name(audio.path)}",
                anchor="nw",
                fill=TEXT,
                font=("Microsoft YaHei UI", 13, "bold"),
                tags=(tag,),
            )
            self.preview_canvas.create_text(
                pad_x + 72,
                y + 39,
                text=f"{audio.path.name} · {human_size(audio.size)}",
                anchor="nw",
                fill=SOFT,
                font=("Microsoft YaHei UI", 9),
                tags=(tag,),
            )
            self.preview_canvas.create_text(
                max(pad_x + 270, width - pad_x - 90),
                y + 28,
                text="播放",
                anchor="nw",
                fill=TEXT,
                font=("Microsoft YaHei UI", 10, "bold"),
                tags=(tag,),
            )
            self.preview_canvas.tag_bind(tag, "<Button-1>", lambda _event, i=idx: self._select_and_play_audio(i))
            y += row_h

        self.preview_image_box = (0, 0, 1, 1)
        self.preview_canvas.configure(scrollregion=(0, 0, width, max(height, y + 24)))
        count = len(group.items)
        self.title_var.set(f"音频试听列表  ({len(rows)} 个)")
        self.meta_var.set(f"{item.path.parent}")

    def _select_and_play_audio(self, index: int) -> None:
        self.selected_index = index
        self.zoom = 1.0
        self._render_strip()
        self._show_selected()
        self.play_selected_media()

    def _draw_video_preview_frame(self, item: MediaItem, autoplay: bool) -> None:
        self.preview_canvas.delete("all")
        width = max(1, self.preview_canvas.winfo_width())
        height = max(1, self.preview_canvas.winfo_height())
        self.preview_canvas.configure(scrollregion=(0, 0, width, height))
        self.preview_image_box = (0, 0, 1, 1)

        frame_img = self._video_first_frame(item.path)
        max_w = max(240, int(width * 0.62))
        max_h = max(180, int(height * 0.62))
        if frame_img is None:
            frame_img = self._icon_thumb(MediaKind.VIDEO, min(260, max(160, width // 4))).convert("RGBA")
        else:
            frame_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

        self.preview_ref = ImageTk.PhotoImage(frame_img)
        image_y = 24
        self.preview_canvas.create_image(width // 2, image_y, anchor="n", image=self.preview_ref)
        text_top = image_y + frame_img.height + 26
        self.preview_canvas.create_text(width // 2, text_top, text="视频预览", fill=TEXT, font=("Microsoft YaHei UI", 22, "bold"))
        self.preview_canvas.create_text(width // 2, text_top + 42, text=display_media_name(item.path), fill=TEXT, font=("Microsoft YaHei UI", 15), width=max(320, width - 160))
        self.preview_canvas.create_text(width // 2, text_top + 82, text=f"{human_size(item.size)} · {item.path.suffix.lower()} · 点击“预览视频”在程序内播放", fill=SOFT, font=("Microsoft YaHei UI", 11), width=max(320, width - 160))
        self.preview_canvas.configure(scrollregion=(0, 0, width, max(height, text_top + 130)))
        group = self._current_group()
        count = len(group.items) if group else 1
        self.title_var.set(f"{display_media_name(item.path)}  ({self.selected_index + 1}/{count})")
        self.meta_var.set(f"视频 · {human_size(item.size)} · {item.path.parent}")
        if autoplay:
            self._start_video(item.path)

    def _video_first_frame(self, path: Path) -> Image.Image | None:
        try:
            import cv2  # type: ignore

            cap = cv2.VideoCapture(str(path))
            ok, frame = cap.read()
            cap.release()
            if not ok:
                return None
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
            return Image.fromarray(frame)
        except Exception:
            return None

    def _start_video(self, path: Path) -> None:
        self._stop_video()
        try:
            import cv2  # type: ignore

            cap = cv2.VideoCapture(str(path))
            if not cap.isOpened():
                raise RuntimeError("无法打开视频文件")
            self.video_cap = cap
            self.video_playing_path = path
            self.status_var.set(f"正在预览视频：{path.name}")
            self._video_tick()
        except Exception as exc:
            self._stop_video()
            messagebox.showerror("视频播放失败", str(exc), parent=self)

    def _video_tick(self) -> None:
        if self.video_cap is None:
            return
        try:
            import cv2  # type: ignore

            ok, frame = self.video_cap.read()
            if not ok:
                self._stop_video()
                self.status_var.set("视频预览结束")
                return
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
            img = Image.fromarray(frame)
            width = max(1, self.preview_canvas.winfo_width())
            height = max(1, self.preview_canvas.winfo_height())
            img.thumbnail((max(240, int(width * 0.68)), max(180, int(height * 0.72))), Image.Resampling.LANCZOS)
            self.preview_ref = ImageTk.PhotoImage(img)
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(width // 2, 22, anchor="n", image=self.preview_ref)
            name = self.video_playing_path.name if self.video_playing_path else "视频"
            self.preview_canvas.create_text(width // 2, 36 + img.height, text=name, fill=TEXT, font=("Microsoft YaHei UI", 14, "bold"), width=max(320, width - 160))
            self.preview_canvas.create_text(width // 2, 70 + img.height, text="程序内视频预览中，点击“停止”结束", fill=SOFT, font=("Microsoft YaHei UI", 11))
            self.preview_canvas.configure(scrollregion=(0, 0, width, max(height, img.height + 120)))
            fps = self.video_cap.get(cv2.CAP_PROP_FPS) or 24
            delay = max(15, min(80, int(1000 / fps)))
            self.video_after_id = self.after(delay, self._video_tick)
        except Exception as exc:
            self._stop_video()
            messagebox.showerror("视频播放失败", str(exc), parent=self)

    def _stop_video(self) -> None:
        if self.video_after_id is not None:
            try:
                self.after_cancel(self.video_after_id)
            except tk.TclError:
                pass
            self.video_after_id = None
        if self.video_cap is not None:
            try:
                self.video_cap.release()
            except Exception:
                pass
            self.video_cap = None
        self.video_playing_path = None

    def _set_preview_message(self, text: str) -> None:
        self.preview_canvas.delete("all")
        width = max(1, self.preview_canvas.winfo_width())
        height = max(1, self.preview_canvas.winfo_height())
        self.preview_canvas.create_text(width // 2, height // 2, text=text, fill=SOFT, font=("Microsoft YaHei UI", 16))
        self.preview_image_box = (0, 0, 1, 1)
        self.preview_canvas.configure(scrollregion=(0, 0, width, height))

    def _set_preview_image(self, width: int, height: int) -> None:
        canvas_w = max(1, self.preview_canvas.winfo_width())
        canvas_h = max(1, self.preview_canvas.winfo_height())
        x = max(0, (canvas_w - width) // 2)
        y = max(0, (canvas_h - height) // 2)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(x, y, anchor="nw", image=self.preview_ref)
        self.preview_image_box = (x, y, width, height)
        region_w = max(canvas_w, x + width)
        region_h = max(canvas_h, y + height)
        self.preview_canvas.configure(scrollregion=(0, 0, region_w, region_h))

    def copy_selected_image(self) -> None:
        item = self._current_item()
        if not item:
            messagebox.showinfo("未选择媒体", "请先选择一项媒体。", parent=self)
            return
        if item.kind != MediaKind.IMAGE:
            self.clipboard_clear()
            self.clipboard_append(str(item.path))
            self.status_var.set(f"当前不是图片，已复制路径：{item.path}")
            return
        try:
            copy_image_to_clipboard(item.path)
            self.status_var.set(f"已复制图片到剪贴板：{item.path.name}")
        except Exception as exc:
            self.clipboard_clear()
            self.clipboard_append(str(item.path))
            self.status_var.set(f"图片复制失败，已改为复制路径：{item.path}")
            messagebox.showwarning("复制图片失败", f"{exc}\n\n已改为复制图片路径。", parent=self)

    def play_selected_media(self) -> None:
        item = self._current_item()
        if not item:
            return
        if item.kind == MediaKind.AUDIO:
            try:
                self.audio_player.play(item.path)
                self.status_var.set(f"正在播放：{display_media_name(item.path)}")
            except Exception as exc:
                messagebox.showerror("音频播放失败", str(exc), parent=self)
            return
        if item.kind == MediaKind.VIDEO:
            self.status_var.set("视频已在程序内显示首帧预览；完整内嵌播放后续接入。")
            return
        self._open_path(item.path)

    def stop_playback(self) -> None:
        self.audio_player.stop()
        self.status_var.set("已停止播放")

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
        tk.Label(card, text="每行一个监听目录。保存后会立即重新扫描，支持图片、音频、视频。", bg=CARD, fg=SOFT, font=("Microsoft YaHei UI", 10)).grid(row=1, column=0, sticky="w", pady=(8, 18))
        tk.Label(card, text="监听目录", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 10, "bold")).grid(row=2, column=0, sticky="w", pady=(0, 8))

        text = tk.Text(card, bg="#F2FBF4", fg=TEXT, insertbackground=TEXT, relief="flat", bd=0, font=("Microsoft YaHei UI", 10), height=8)
        text.grid(row=3, column=0, sticky="nsew")
        text.insert("1.0", "\n".join(str(path) for path in self.watch_dirs))

        actions = tk.Frame(card, bg=CARD)
        actions.grid(row=4, column=0, sticky="ew", pady=(18, 0))
        self._button(actions, "添加目录", lambda: self._browse_add_dir(text), PINK).pack(side="left")
        self._button(actions, "恢复默认", lambda: self._replace_text(text, "\n".join(str(path) for path in default_watch_dirs())), "#F4EAF0").pack(side="left", padx=(8, 0))
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
