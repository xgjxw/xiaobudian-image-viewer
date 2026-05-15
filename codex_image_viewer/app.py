from __future__ import annotations

import os
import json
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


def list_groups(root: Path) -> list[ImageGroup]:
    if not root.exists():
        return []

    grouped: dict[Path, list[ImageItem]] = {}
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


def load_config() -> dict[str, str]:
    for path in (CONFIG_FILE, LEGACY_CONFIG_FILE):
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def save_config(data: dict[str, str]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


class CodexImageViewer(tk.Tk):
    def __init__(self, watch_dir: Path | None = None) -> None:
        super().__init__()
        config = load_config()
        configured_dir = config.get("watch_dir")
        self.watch_dir = watch_dir or (Path(configured_dir) if configured_dir else DEFAULT_WATCH_DIR)
        self.config_vars: dict[str, tk.StringVar] = {}
        self.groups: list[ImageGroup] = []
        self.selected_dir: Path | None = None
        self.selected_index = 0
        self.thumb_refs: dict[str, ImageTk.PhotoImage] = {}
        self.thumb_cache: dict[tuple[Path, int, float], ImageTk.PhotoImage] = {}
        self.group_cards: dict[Path, tuple[tk.Widget, ...]] = {}
        self.preview_ref: ImageTk.PhotoImage | None = None
        self.poll_ms = 1500
        self.last_signature: tuple[tuple[str, float, int], ...] = ()

        self.title("小不点图片预览器")
        self.geometry("1240x780")
        self.minsize(980, 640)
        self.configure(bg=BG)

        self._build_ui()
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
        self._button(header, "打开监听目录", lambda: self._open_path(self.watch_dir), GREEN).grid(row=0, column=3, rowspan=2, padx=(8, 0))

        sidebar = tk.Frame(self, bg=SIDEBAR, padx=12, pady=12, width=410)
        sidebar.grid(row=1, column=0, sticky="nsew", padx=(20, 10), pady=(0, 20))
        sidebar.grid_rowconfigure(1, weight=1)
        sidebar.grid_propagate(False)
        tk.Label(sidebar, text="生成目录", bg=SIDEBAR, fg=TEXT, font=("Microsoft YaHei UI", 15, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 10))

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
        self.meta_var = tk.StringVar(value=str(self.watch_dir))
        tk.Label(top, textvariable=self.title_var, bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(top, textvariable=self.meta_var, bg=CARD, fg=SOFT, font=("Microsoft YaHei UI", 10)).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._button(top, "上一张", self.prev_image, PINK).grid(row=0, column=1, rowspan=2, padx=(8, 0))
        self._button(top, "下一张", self.next_image, PINK).grid(row=0, column=2, rowspan=2, padx=(8, 0))
        self._button(top, "打开当前目录", self._open_selected_dir, GREEN).grid(row=0, column=3, rowspan=2, padx=(8, 0))

        self.preview_area = tk.Frame(preview, bg="#F7F3F6")
        self.preview_area.grid(row=1, column=0, sticky="nsew")
        self.preview_area.grid_columnconfigure(0, weight=1)
        self.preview_area.grid_rowconfigure(0, weight=1)
        self.preview_label = tk.Label(self.preview_area, bg="#F7F3F6", fg=SOFT, text="暂无图片", font=("Microsoft YaHei UI", 16))
        self.preview_label.grid(row=0, column=0, sticky="nsew")
        self.preview_area.bind("<Configure>", lambda _event: self._show_selected())
        self.bind("<Left>", lambda _event: self.prev_image())
        self.bind("<Right>", lambda _event: self.next_image())

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
        scrollbar = tk.Scrollbar(
            wrap,
            orient=orient,
            command=canvas.xview if horizontal else canvas.yview,
            width=8,
            bd=0,
            relief="flat",
            bg=PINK,
            activebackground=PINK,
            troughcolor="#FFF7FA",
            highlightthickness=0,
            elementborderwidth=0,
        )
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

    def _poll(self) -> None:
        try:
            self.refresh(force=False)
        finally:
            self.after(self.poll_ms, self._poll)

    def refresh(self, force: bool = True) -> None:
        groups = list_groups(self.watch_dir)
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
        self._render_groups()
        self._render_strip()
        self._show_selected()
        image_count = sum(len(group.images) for group in groups)
        self.status_var.set(f"监听：{self.watch_dir}    共 {len(groups)} 个目录 / {image_count} 张图片，自动刷新 {self.poll_ms / 1000:.1f}s")

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
        for child in self.list_body.winfo_children():
            child.destroy()
        self.group_cards.clear()
        keys_to_keep: set[str] = set()
        if not self.groups:
            tk.Label(self.list_body, text="还没有发现图片目录", bg=SIDEBAR, fg=SOFT, font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=20)
            return
        for group in self.groups[:100]:
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
            thumb = self._make_thumb(item.path, 58)
            self.thumb_refs[key] = thumb
            keys_to_keep.add(key)
            label = tk.Label(thumbs, image=thumb, bg=bg, cursor="hand2")
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
        latest = group.images[0].path.name
        latest_label = tk.Label(info, text=middle_ellipsis(latest, 34), bg=bg, fg=SOFT, font=("Microsoft YaHei UI", 8), cursor="hand2")
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
        for idx, item in enumerate(group.images[:80]):
            active = idx == self.selected_index
            bg = ACTIVE if active else "#F7F3F6"
            cell = tk.Frame(self.strip_body, bg=bg, padx=5, pady=5, highlightthickness=1, highlightbackground=LINE, cursor="hand2")
            cell.grid(row=0, column=idx, padx=(0, 8), sticky="n")
            key = f"strip:{idx}:{item.path}"
            thumb = self._make_thumb(item.path, 84)
            self.thumb_refs[key] = thumb
            image_label = tk.Label(cell, image=thumb, bg=bg, cursor="hand2")
            image_label.pack()
            cell.bind("<Button-1>", lambda _event, i=idx: self._select_image(i))
            cell.bind("<MouseWheel>", lambda event: self._scroll_canvas(event, self.strip_canvas, horizontal=True))
            image_label.bind("<Button-1>", lambda _event, i=idx: self._select_image(i))
            image_label.bind("<MouseWheel>", lambda event: self._scroll_canvas(event, self.strip_canvas, horizontal=True))

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
        if len(self.thumb_cache) > 600:
            for old_key in list(self.thumb_cache)[:120]:
                self.thumb_cache.pop(old_key, None)
        return thumb

    def _select_group(self, directory: Path) -> None:
        if directory == self.selected_dir:
            return
        old_dir = self.selected_dir
        self.selected_dir = directory
        self.selected_index = 0
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
        self._render_strip()
        self._show_selected()
        self.after(20, lambda: self._scroll_strip_to_index(index))

    def _scroll_strip_to_index(self, index: int) -> None:
        group = self._current_group()
        if not group or len(group.images) <= 1:
            return
        visible_count = min(len(group.images), 80)
        fraction = max(0.0, min(1.0, index / max(1, visible_count - 1)))
        self.strip_canvas.xview_moveto(fraction)

    def prev_image(self) -> None:
        group = self._current_group()
        if not group:
            return
        self.selected_index = (self.selected_index - 1) % len(group.images)
        self._render_strip()
        self._show_selected()

    def next_image(self) -> None:
        group = self._current_group()
        if not group:
            return
        self.selected_index = (self.selected_index + 1) % len(group.images)
        self._render_strip()
        self._show_selected()

    def _show_selected(self) -> None:
        item = self._current_item()
        if not item or not item.path.exists():
            self.preview_ref = None
            self.preview_label.configure(image="", text="暂无图片")
            self.title_var.set("等待图片")
            self.meta_var.set(str(self.watch_dir))
            return

        path = item.path
        try:
            with Image.open(path) as img:
                img = ImageOps.exif_transpose(img).convert("RGBA")
                area_w = max(300, self.preview_area.winfo_width() - 28)
                area_h = max(300, self.preview_area.winfo_height() - 28)
                img.thumbnail((area_w, area_h), Image.Resampling.LANCZOS)
                self.preview_ref = ImageTk.PhotoImage(img)
        except Exception as exc:
            self.preview_ref = None
            self.preview_label.configure(image="", text=f"图片读取失败：{exc}")
            return
        self.preview_label.configure(image=self.preview_ref, text="")
        try:
            with Image.open(path) as probe:
                size_text = f"{probe.width} × {probe.height}"
            group = self._current_group()
            count = len(group.images) if group else 1
            self.title_var.set(f"{path.name}  ({self.selected_index + 1}/{count})")
            self.meta_var.set(f"{size_text} · {human_size(item.size)} · {path.parent}")
        except OSError:
            self.title_var.set(path.name)
            self.meta_var.set(str(path.parent))

    def _open_selected_dir(self) -> None:
        if self.selected_dir:
            self._open_path(self.selected_dir)
        else:
            self._open_path(self.watch_dir)

    def _open_settings(self) -> None:
        win = tk.Toplevel(self)
        win.title("系统配置")
        win.geometry("760x360")
        win.minsize(680, 320)
        win.configure(bg=BG)
        win.transient(self)
        win.grab_set()

        card = tk.Frame(win, bg=CARD, padx=24, pady=22, highlightthickness=1, highlightbackground=LINE)
        card.pack(fill="both", expand=True, padx=18, pady=18)
        card.grid_columnconfigure(1, weight=1)
        card.grid_rowconfigure(5, weight=1)

        tk.Label(card, text="系统配置", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 18, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        tk.Label(card, text="修改后会立即重新扫描目录。", bg=CARD, fg=SOFT, font=("Microsoft YaHei UI", 10)).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 18))

        watch_var = tk.StringVar(value=str(self.watch_dir))
        self.config_vars["watch_dir"] = watch_var
        tk.Label(card, text="监听目录", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 10, "bold")).grid(row=2, column=0, sticky="w", pady=(0, 10))
        entry = tk.Entry(card, textvariable=watch_var, bg="#F2FBF4", fg=TEXT, insertbackground=TEXT, relief="flat", bd=0, font=("Microsoft YaHei UI", 10))
        entry.grid(row=2, column=1, sticky="ew", padx=(12, 8), ipady=8, pady=(0, 10))
        self._button(card, "浏览", lambda: self._browse_watch_dir(watch_var), PINK).grid(row=2, column=2, pady=(0, 10))

        hint = f"默认目录：{DEFAULT_WATCH_DIR}"
        tk.Label(card, text=hint, bg=CARD, fg=SOFT, font=("Microsoft YaHei UI", 9)).grid(row=3, column=1, sticky="w", padx=(12, 0))

        actions = tk.Frame(card, bg=CARD)
        actions.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(24, 0))
        self._button(actions, "恢复默认", lambda: watch_var.set(str(DEFAULT_WATCH_DIR)), "#F4EAF0").pack(side="left")
        self._button(actions, "保存并刷新", lambda: self._save_settings(win, watch_var.get()), GREEN).pack(side="right")
        self._button(actions, "取消", win.destroy, "#F4EAF0").pack(side="right", padx=(0, 8))
        entry.focus_set()

    def _browse_watch_dir(self, variable: tk.StringVar) -> None:
        initial = variable.get().strip() or str(DEFAULT_WATCH_DIR)
        path = filedialog.askdirectory(parent=self, title="选择监听目录", initialdir=initial if Path(initial).exists() else str(DEFAULT_WATCH_DIR.parent))
        if path:
            variable.set(path)

    def _save_settings(self, win: tk.Toplevel, watch_dir_text: str) -> None:
        path = Path(watch_dir_text.strip()).expanduser()
        if not path.exists() or not path.is_dir():
            messagebox.showerror("目录无效", "监听目录不存在或不是文件夹。", parent=win)
            return
        self.watch_dir = path
        save_config({"watch_dir": str(path)})
        self.groups = []
        self.selected_dir = None
        self.selected_index = 0
        self.last_signature = ()
        self.refresh(force=True)
        win.destroy()

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))


def main() -> None:
    app = CodexImageViewer()
    app.mainloop()
