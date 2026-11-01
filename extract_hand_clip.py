"""Select a moving 5–10 s HoloAssist segment and export exactly matching poses.

Run after download_sample.py. Requires numpy and FFmpeg (or imageio-ffmpeg).
Excel export is performed by the portable Python export_excel.py module.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess

import numpy as np

JOINTS = ["Palm", "Wrist", "ThumbMetacarpal", "ThumbProximal", "ThumbDistal", "ThumbTip",
          "IndexMetacarpal", "IndexProximal", "IndexIntermediate", "IndexDistal", "IndexTip",
          "MiddleMetacarpal", "MiddleProximal", "MiddleIntermediate", "MiddleDistal", "MiddleTip",
          "RingMetacarpal", "RingProximal", "RingIntermediate", "RingDistal", "RingTip",
          "PinkyMetacarpal", "PinkyProximal", "PinkyIntermediate", "PinkyDistal", "PinkyTip"]
TICKS_PER_SECOND = 10_000_000


def load_hand(path):
    """Do NOT convert the 18-digit timestamp through float64 (precision loss)."""
    sync_times, ticks, matrices, active, valid, tracked = [], [], [], [], [], []
    width = None
    with Path(path).open() as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            fields = line.split()
            if width is None:
                width = len(fields)
            if len(fields) != width or width != 471:
                raise ValueError(f"{path}:{line_number}: expected verified 471-field sync format; got {len(fields)}")
            sync_times.append(float(fields[0]))
            ticks.append(int(fields[1]))
            active.append(int(fields[2]))
            matrices.append(np.asarray(fields[3:419], dtype=float).reshape(26, 4, 4))
            valid.append([int(x) for x in fields[419:445]])
            tracked.append([int(x) for x in fields[445:471]])
    data = dict(sync_time=np.array(sync_times), ticks=np.array(ticks, dtype=np.int64),
                matrix=np.array(matrices), active=np.array(active),
                valid=np.array(valid, dtype=bool), tracked=np.array(tracked, dtype=bool))
    if len(ticks) < 2 or np.any(np.diff(data["ticks"]) < 0):
        raise ValueError("Missing or nonmonotonic hand timestamps")
    if np.any(np.diff(data["sync_time"]) <= 0):
        raise ValueError("Duplicate or unordered synchronized grid times")
    if not set(active) <= {0, 1} or not set(np.array(valid).flat) <= {0, 1} or not set(np.array(tracked).flat) <= {0, 1}:
        raise ValueError("Nonbinary active/valid/tracked flag")
    return data


def usable(data):
    return ((data["active"][:, None] == 1) & data["valid"] & data["tracked"] &
            np.isfinite(data["matrix"]).all(axis=(2, 3)))


def validate_matrices(data):
    good = data["matrix"][usable(data)]
    if not len(good):
        raise ValueError("No usable tracked poses")
    bottom_error = float(np.max(np.abs(good[:, 3] - [0, 0, 0, 1])))
    rotation = good[:, :3, :3]
    orth_error = float(np.max(np.abs(rotation.transpose(0, 2, 1) @ rotation - np.eye(3))))
    determinant_error = float(np.max(np.abs(np.linalg.det(rotation) - 1)))
    if max(bottom_error, orth_error, determinant_error) > 1e-3:
        raise ValueError("Pose layout is inconsistent with rigid 4x4 transforms")
    return dict(bottom_row_max_error=bottom_error, rotation_orthogonality_max_error=orth_error,
                rotation_determinant_max_error=determinant_error)


def movement_stats(data, start_ticks, end_ticks):
    select = (data["ticks"] >= start_ticks) & (data["ticks"] < end_ticks)
    m, good, ticks = data["matrix"][select], usable(data)[select], data["ticks"][select]
    if len(m) < 2:
        return dict(tracked_fraction=0., path_m=0., extent_m=0., transitions=0)
    # Palm and wrist only; do not count tracking reacquisition jumps or long gaps.
    xyz = m[:, :2, :3, 3]
    pairs = good[1:, :2] & good[:-1, :2] & (np.diff(ticks)[:, None] > 0) & (np.diff(ticks)[:, None] < 1_000_000)
    distance = np.linalg.norm(np.diff(xyz, axis=0), axis=2)
    pairs &= np.isfinite(distance) & (distance < .1)
    paths = np.where(pairs, distance, 0).sum(axis=0)
    points = xyz[:, 0][good[:, 0]]
    extent = float(np.linalg.norm(np.ptp(points, axis=0))) if len(points) else 0.
    return dict(tracked_fraction=float(good[:, :2].mean()), path_m=float(paths.max()),
                extent_m=extent, transitions=int(pairs.sum()))


def select_start(hands, origin, duration, video_duration, requested=None):
    lower = max(0., min((int(h["ticks"][0]) - origin) / TICKS_PER_SECOND for h in hands.values()))
    upper = min(video_duration, max((int(h["ticks"][-1]) - origin) / TICKS_PER_SECOND for h in hands.values())) - duration
    candidates = [requested] if requested is not None else np.arange(math.ceil(lower), math.floor(upper) + 1, .5)
    best = None
    for start in candidates:
        if start < lower or start > upper:
            continue
        stats = {side: movement_stats(h, origin + round(start * TICKS_PER_SECOND),
                                      origin + round((start + duration) * TICKS_PER_SECOND))
                 for side, h in hands.items()}
        eligible = [s for s in stats.values() if s["tracked_fraction"] >= .9 and s["extent_m"] >= .08 and s["path_m"] >= .15]
        if not eligible:
            continue
        # Prefer broad displacement and consistent tracking over high-frequency jitter.
        score = max(s["extent_m"] * s["tracked_fraction"] for s in eligible)
        if best is None or score > best[0]:
            best = score, float(start), stats
    if best is None:
        raise ValueError("No interval meets tracked-motion thresholds; choose another recording/start")
    return best[1], best[2]


def ffmpeg_executable():
    if shutil.which("ffmpeg"):
        return shutil.which("ffmpeg")
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def probe_video(ffmpeg, video):
    # FFmpeg showinfo exposes actual decoded PTS, avoiding frame_number/fps assumptions.
    process = subprocess.run([ffmpeg, "-hide_banner", "-i", str(video), "-map", "0:v:0",
                              "-vf", "showinfo", "-an", "-f", "null", "-"], capture_output=True, text=True, check=True)
    import re
    frames = []
    for line in process.stderr.splitlines():
        match = re.search(r"\bn:\s*(\d+).*?\bpts_time:([\d.eE+\-]+)", line)
        if match:
            frames.append((int(match[1]), float(match[2])))
    if len(frames) < 2 or any(b[1] <= a[1] for a, b in zip(frames, frames[1:])):
        raise ValueError("Cannot establish ordered decoded video timestamps")
    return frames


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def export_payload(hands, origin, start, duration, frame_pts, output):
    start_ticks = origin + round(start * TICKS_PER_SECOND)
    end_ticks = start_ticks + round(duration * TICKS_PER_SECOND)
    header = ["source_sync_time_s", "sensor_timestamp_ticks_text", "video_time_s", "clip_time_s",
              "nearest_video_frame", "nearest_video_time_s", "sensor_minus_video_ms", "hand_active"]
    for joint in JOINTS:
        header += [f"{joint}_M{r}{c}" for r in range(4) for c in range(4)]
        header += [f"{joint}_{axis}_m" for axis in "xyz"] + [f"{joint}_valid", f"{joint}_tracked"]
    tables = {}
    pts = np.array([p for _, p in frame_pts])
    for side, data in hands.items():
        rows = []
        for i in np.flatnonzero((data["ticks"] >= start_ticks) & (data["ticks"] < end_ticks)):
            relative = (int(data["ticks"][i]) - origin) / TICKS_PER_SECOND
            k = int(np.searchsorted(pts, relative))
            k = min(k, len(pts) - 1)
            if k > 0 and abs(pts[k - 1] - relative) <= abs(pts[k] - relative):
                k -= 1
            row = [float(data["sync_time"][i]), str(data["ticks"][i]), relative, relative - start,
                   int(frame_pts[k][0]), float(pts[k]), float((relative - pts[k]) * 1000), int(data["active"][i])]
            for j, matrix in enumerate(data["matrix"][i]):
                # Preserve finite raw values even when invalid; flags remain explicit.
                row += [float(v) if np.isfinite(v) else None for v in matrix.flat]
                row += [float(v) if np.isfinite(v) else None for v in matrix[:3, 3]]
                row += [int(data["valid"][i, j]), int(data["tracked"][i, j])]
            rows.append(row)
        if not rows:
            raise ValueError(f"No {side} records in clip")
        tables[side] = {"header": header, "rows": rows}
    (output / "hand_data.json").write_text(json.dumps(tables, allow_nan=False))
    return tables


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default="R0027-12-GoPro")
    parser.add_argument("--root", type=Path, default=Path("download_cache"))
    parser.add_argument("--out", type=Path, default=Path("sample"))
    parser.add_argument("--duration", type=float, default=8.)
    parser.add_argument("--start", type=float, default=369., help="Requested start from original video start; pinned to 369 s for this sample")
    parser.add_argument("--json-only", action="store_true", help="Export numeric data without rebuilding Excel")
    args = parser.parse_args()
    if not 5 <= args.duration <= 10:
        parser.error("duration must be between 5 and 10 seconds")
    base = args.root / args.session / "Export_py"
    hands = {side: load_hand(base / "Hands" / f"{side}_sync.txt") for side in ["Left", "Right"]}
    checks = {side: validate_matrices(data) for side, data in hands.items()}
    timing = [int(x) for x in (base / "Video/VideoMp4Timing.txt").read_text().split()]
    if len(timing) != 2 or timing[1] <= timing[0]:
        raise ValueError("Expected exact start and end ticks in VideoMp4Timing.txt")
    origin = timing[0]
    ffmpeg = ffmpeg_executable()
    video = base / "Video_pitchshift.mp4"
    frames = probe_video(ffmpeg, video)
    video_duration = frames[-1][1] + np.median(np.diff([x[1] for x in frames]))
    if abs((timing[1] - origin) / TICKS_PER_SECOND - video_duration) > 1:
        raise ValueError("MP4 duration disagrees with recording timing by over 1 second")
    requested, movement = select_start(hands, origin, args.duration, video_duration, args.start)
    # Snap start and end to decoded video frame boundaries. Same [start,end) for hands.
    start_frame = next(i for i, (_, pts) in enumerate(frames) if pts >= requested)
    end_frame = next(i for i, (_, pts) in enumerate(frames) if pts >= requested + args.duration)
    start, end = frames[start_frame][1], frames[end_frame][1]
    movement = {side: movement_stats(data, origin + round(start * TICKS_PER_SECOND),
                                     origin + round(end * TICKS_PER_SECOND))
                for side, data in hands.items()}
    args.out.mkdir(parents=True, exist_ok=True)
    clip = args.out / "hand_movement.mp4"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(video), "-map", "0:v:0",
                    "-vf", f"trim=start_frame={start_frame}:end_frame={end_frame},setpts=PTS-STARTPTS",
                    "-an", "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-fps_mode", "vfr",
                    "-movflags", "+faststart", str(clip)], check=True)
    clip_frames = probe_video(ffmpeg, clip)
    if len(clip_frames) != end_frame - start_frame:
        raise ValueError("Output frame count does not match exact selected source frames")
    if max(abs(p[1] - (frames[start_frame + i][1] - start)) for i, p in enumerate(clip_frames)) > .001:
        raise ValueError("Output PTS differs from selected input PTS")
    tables = export_payload(hands, origin, start, end - start, frames, args.out)
    sources = [base / "Hands/Left_sync.txt", base / "Hands/Right_sync.txt", base / "Video/VideoMp4Timing.txt", video]
    report = dict(session=args.session, video_start_ticks_text=str(origin), clip_start_video_s=start,
                  clip_end_video_s=end, clip_duration_s=end - start, source_first_frame=start_frame,
                  source_end_frame_exclusive=end_frame, clip_frames=len(clip_frames),
                  movement=movement, matrix_checks=checks,
                  row_counts={side: len(table["rows"]) for side, table in tables.items()},
                  source_sha256={str(path): digest(path) for path in sources},
                  clip_sha256=digest(clip),
                  coordinates="Original PSI world coordinate system; translation in metres. Not image pixels.",
                  source_format="471 fields: synchronized grid time (seconds), integer sensor ticks, active, 26 row-major 4x4 matrices, 26 valid, 26 tracked",
                  timestamp_note="Ticks are text to avoid Excel's 15-significant-digit numeric limit; time_s calculated by integer subtraction first.",
                  missing_note="NaN/Inf exported as blank; raw finite invalid values retained with valid/tracked/active flags.",
                  synchronization="Sensor ticks minus VideoMp4Timing origin; nearest decoded MP4 PTS recorded with signed residual. No interpolation or latency correction.")
    (args.out / "validation.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if not args.json_only:
        from export_excel import export_workbook
        export_workbook(args.out)


if __name__ == "__main__":
    main()
