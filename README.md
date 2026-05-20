# 小不点图片查看器

一个 Windows 本地图片目录实时预览工具。支持同时监控多个目录，保留左侧图片目录卡片、右侧大图预览、底部缩略图的原有风格。

默认监控目录：

```text
C:/Users/Administrator/.codex/generated_images/
```

## 功能

- 同时监控多个本地目录，配置持久化到 `%APPDATA%/xiaobudian-image-viewer/config.json`
- 自动扫描子目录里的 `PNG / JPG / JPEG / WebP / GIF / BMP` 图片
- 左侧按图片所在目录分组展示，保留 2x2 缩略图卡片风格
- 右侧大图预览，底部缩略图点击切换
- 图片预览支持：
  - 复制图片到系统剪贴板
  - 鼠标滚轮直接放大/缩小
  - 重置缩放
- 快捷键：
  - `Ctrl+C`：复制当前选中的图片
  - `+` / `-`：放大 / 缩小
  - `Ctrl+0`：重置缩放
  - `F5`：刷新
- 每 1.5 秒自动刷新，新增/删除/修改文件会自动同步
- 兼容读取旧版单目录配置字段 `watch_dir`

## 安装开发版

```powershell
cd D:\workspace\myself\xiaobudian-image-viewer
python -m pip install -e .
python run.py
```

也可以用命令启动：

```powershell
xiaobudian-image-viewer
```

兼容旧命令：

```powershell
codex-image-viewer
```

## 本地打包 EXE

```powershell
cd D:\workspace\myself\xiaobudian-image-viewer
python -m pip install -e .
python -m pip install pyinstaller
.\build_exe.bat
```

输出：

```text
dist/xiaobudian-image-viewer.exe
```
