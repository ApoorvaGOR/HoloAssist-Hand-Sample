"""Download one HoloAssist session using HTTP ranges, never whole release archives.

Python standard library only. Run: python3 download_sample.py
"""
import argparse
import io
import json
from pathlib import Path
import tarfile
import time
import urllib.request

BASE = "https://hl2data.z5.web.core.windows.net/holoassist-data-release/"


class RemoteTar(io.RawIOBase):
    def __init__(self, url):
        self.url, self.pos = url, 0
        self.cache_start, self.cache = 0, b""

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        if whence == 0:
            self.pos = offset
        elif whence == 1:
            self.pos += offset
        else:
            raise ValueError("Seeking relative to archive end is unsupported")
        return self.pos

    def read(self, size=-1):
        if size < 0:
            raise ValueError("Unbounded remote downloads are forbidden")
        if size == 0:
            return b""
        if self.cache_start <= self.pos and self.pos + size <= self.cache_start + len(self.cache):
            start = self.pos - self.cache_start
            self.pos += size
            return self.cache[start:start + size]
        start, length = self.pos, max(size, 65536)
        request = urllib.request.Request(self.url, headers={
            "Range": f"bytes={start}-{start + length - 1}",
            "Accept-Encoding": "identity",
        })
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    if response.status != 206:
                        raise RuntimeError("Server ignored Range; refusing full archive download")
                    content_range = response.headers.get("Content-Range", "")
                    if not content_range.startswith(f"bytes {start}-"):
                        raise RuntimeError(f"Wrong HTTP range: {content_range}")
                    data = response.read(length + 1)
                if len(data) > length:
                    raise RuntimeError("Oversized HTTP response")
                break
            except (OSError, TimeoutError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        self.cache_start, self.cache = start, data
        self.pos += min(size, len(data))
        return data[:size]


def download_session(session, root):
    root = Path(root)
    manifests = []
    for archive, wanted in [
        ("hands.tar", {"Left_sync.txt", "Right_sync.txt"}),
        ("video_pitch_shifted.tar", {"Video_pitchshift.mp4", "VideoMp4Timing.txt", "Pose_sync.txt"}),
    ]:
        print(f"Scanning {archive} for {session}", flush=True)
        remote = RemoteTar(BASE + archive)
        found = set()
        with tarfile.open(fileobj=remote, mode="r:") as tar:
            for member in tar:
                parts = Path(member.name).parts
                if session not in parts or Path(member.name).name not in wanted or not member.isfile():
                    continue
                relative = Path(*parts[parts.index(session):])
                if ".." in relative.parts:
                    raise ValueError("Unsafe archive path")
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or target.stat().st_size != member.size:
                    print(f"Downloading {relative} ({member.size / 1e6:.1f} MB)", flush=True)
                    temporary = target.with_suffix(target.suffix + ".part")
                    with tar.extractfile(member) as source, temporary.open("wb") as out:
                        while chunk := source.read(4 * 1024 * 1024):
                            out.write(chunk)
                    if temporary.stat().st_size != member.size:
                        raise RuntimeError(f"Incomplete download: {target}")
                    temporary.replace(target)
                manifests.append({"archive_url": BASE + archive, "member": member.name,
                                  "bytes": member.size, "archive_data_offset": member.offset_data})
                found.add(Path(member.name).name)
                if found == wanted:
                    break
        if found != wanted:
            raise RuntimeError(f"Missing {wanted - found} in {archive}")
    (root / session / "download_manifest.json").write_text(json.dumps(manifests, indent=2))
    return root / session / "Export_py"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default="R0027-12-GoPro")
    parser.add_argument("--root", default="download_cache")
    args = parser.parse_args()
    print(download_session(args.session, args.root))
