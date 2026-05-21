from __future__ import annotations

import json
import re
import shutil
from pathlib import Path


DEST = Path("D:/workspace/myself/xiaobudian-audio-library")
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"}

VOICE_NAMES = {
    "zh-CN-XiaoxiaoNeural": "女声-温柔-晓晓",
    "zh-CN-XiaoyiNeural": "女声-甜美-晓伊",
    "zh-CN-YunjianNeural": "男声-专业-云健",
    "zh-CN-YunxiNeural": "男声-磁性-云希",
    "zh-CN-YunyangNeural": "男声-新闻-云扬",
    "zh-CN-liaoning-XiaobeiNeural": "女声-东北-小北",
    "zh-CN-YunxiaNeural": "男声-年轻-云夏",
    "zh-CN-shaanxi-XiaoniNeural": "女声-陕西-小妮",
}


def safe(name: str) -> str:
    return re.sub(r'[<>:"/\\\\|?*]+', "-", name).strip().strip(".")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 999):
        candidate = path.with_name(f"{path.stem}-{i:02d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"cannot allocate filename for {path}")


def add(items: list[dict], src: Path, category: str, label: str) -> None:
    if not src.exists() or src.stat().st_size <= 0:
        return
    dst = unique_path(DEST / safe(f"{category}-{label}{src.suffix.lower()}"))
    shutil.copy2(src, dst)
    items.append(
        {
            "file": dst.name,
            "source": str(src),
            "category": category,
            "label": label,
            "size": dst.stat().st_size,
        }
    )


def main() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []

    voice_dir = Path("C:/Users/Administrator/.codex/skills/auto-video-editor/references/voice_samples")
    for i, src in enumerate(sorted(voice_dir.glob("*.mp3")), 1):
        add(items, src, "01-TTS音色", f"{i:02d}-{VOICE_NAMES.get(src.stem, src.stem)}")

    preview_dir = Path("D:/workspace/myself/520_project/data/to_sucai/auto_video_preview")
    preview_files = sorted(p for p in preview_dir.glob("*") if p.suffix.lower() in AUDIO_EXTS)
    for i, src in enumerate(preview_files, 1):
        add(items, src, "02-视频项目音频", f"{i:02d}-{src.stem}")

    songs_dir = Path("D:/workspace/myself/MoneyPrinterTurbo-Portable-Windows-1.2.6/MoneyPrinterTurbo/resource/songs")
    for i, src in enumerate(sorted(songs_dir.glob("*.mp3")), 1):
        add(items, src, "03-MPT内置配乐", f"{i:02d}-{src.stem}")

    mpt_root = Path("D:/workspace/myself/MoneyPrinterTurbo-Portable-Windows-1.2.6/MoneyPrinterTurbo")
    generated = []
    for src in mpt_root.rglob("*"):
        if src.is_file() and src.suffix.lower() in AUDIO_EXTS and songs_dir not in src.parents:
            generated.append(src)
    for i, src in enumerate(sorted(generated), 1):
        add(items, src, "04-MPT生成音频", f"{i:02d}-{src.parent.name}-{src.stem}")

    (DEST / "index.json").write_text(json.dumps({"count": len(items), "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    (DEST / "audio-library-index.md").write_text(
        "# Audio Library Index\n\n" + "\n".join(f"- `{it['file']}` <- {it['source']}" for it in items),
        encoding="utf-8",
    )
    print(DEST)
    print(len(items))


if __name__ == "__main__":
    main()
