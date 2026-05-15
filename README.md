# 小不点图片预览器

一个 Windows 本地图片目录实时预览工具。默认监听 Codex 生成图片目录，也可以在“系统配置”里切换成任意图片目录。

默认监听目录：

```text
C:/Users/Administrator/.codex/generated_images/
```

## 功能

- 自动扫描子目录里的 `PNG / JPG / JPEG / WebP / GIF / BMP` 图片
- 按生成目录分组展示，不把所有图片扁平展开
- 左侧目录卡片展示：
  - 2x2 缩略图
  - 图片数量
  - 最新文件名
- 右侧大图预览：
  - 上一张 / 下一张
  - 底部缩略图点击切换
  - 打开当前目录
- 每 1.5 秒自动刷新，新生成图片会自动出现
- 系统配置：
  - 手动填写监听目录
  - 浏览选择监听目录
  - 保存后立即刷新
- 配置持久化到本机 `%APPDATA%`

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

## 配置文件

```text
%APPDATA%/xiaobudian-image-viewer/config.json
```

旧配置路径会自动兼容读取：

```text
%APPDATA%/codex-image-viewer/config.json
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

## GitHub Actions 自动打包

仓库推送到 `main` 后会自动执行：

1. 安装 Python 依赖
2. 语法检查
3. 使用 PyInstaller 打包 Windows EXE
4. 上传 workflow artifact
5. 发布/更新固定 Release：

```text
https://github.com/xgjxw/xiaobudian-image-viewer/releases/tag/windows-latest
```

Release 附件名：

```text
xiaobudian-image-viewer-windows.exe
```

