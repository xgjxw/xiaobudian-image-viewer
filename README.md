# 小不点媒体预览器

一个 Windows 本地媒体目录实时预览工具。支持同时监听多个目录，并按分类预览图片、音频、视频。

默认监听目录：

```text
C:/Users/Administrator/.codex/generated_images/
D:/workspace/myself/xiaobudian-audio-library/
D:/workspace/myself/xiaobudian-video-library/
```

## 功能

- 同时监听多个本地目录，配置持久化到 `%APPDATA%/xiaobudian-image-viewer/config.json`
- 自动扫描子目录里的媒体文件：
  - 图片：`PNG / JPG / JPEG / WebP / GIF / BMP`
  - 音频：`MP3 / WAV / M4A / AAC / FLAC / OGG / WMA`
  - 视频：`MP4 / MOV / MKV / AVI / WebM / WMV / M4V`
- 左侧按目录分组展示，支持分类筛选：全部 / 图片 / 音频 / 视频
- 图片支持右侧大图预览、滚轮缩放、拖拽查看、复制图片到系统剪贴板
- 音频支持内置无感播放，不再额外打开系统播放器
- 视频支持首帧/信息卡预览，后续可扩展为完整内嵌播放
- 视频缩略图会尽量提取首帧；不可用时显示视频图标
- Edge TTS 音色文件会显示源码里的中文音色名，例如“女声-温柔（晓晓）”
- 底部缩略图条支持快速切换
- 每 1.5 秒自动刷新，新增/删除/修改文件会自动同步
- 兼容旧版单目录配置字段 `watch_dir`

## 快捷键

- `←` / `→`：上一个 / 下一个
- `Ctrl+C`：图片复制到剪贴板；音频/视频复制路径
- `+` / `-`：图片放大 / 缩小
- `Ctrl+0`：重置图片缩放
- `F5`：刷新

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
