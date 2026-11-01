"""Create an MP4 showing the HoloAssist clip beside timestamp-aligned hand plots.

Run: python3 make_signal_video.py
Dependencies: numpy, matplotlib, Pillow; FFmpeg or local imageio-ffmpeg.
Reads the verified numeric export, without changing the Excel workbook.
"""
import argparse
from fractions import Fraction
import io
import json
import os
from pathlib import Path
import subprocess

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parent / ".cache/matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from extract_hand_clip import ffmpeg_executable, probe_video, digest

BG = "#0e1726"
TEXT = "#eef3fc"
MUTED = "#aabbd0"
COLORS = ["#59b4ff", "#6edba5", "#ffbf6b"]
HAND_COLORS = {"Left": "#ce9fff", "Right": "#63dfeb"}
WIDTH, HEIGHT = 1920, 1080
VIDEO_W, VIDEO_H = 1000, 562
VIDEO_X, VIDEO_Y = 36, 112
PLOT_X, PLOT_Y, PLOT_W, PLOT_H = 1070, 112, 818, 870


def load_signals(folder):
    tables = json.loads((folder / "hand_data.json").read_text())
    result = {}
    for side, table in tables.items():
        head, rows = table["header"], table["rows"]
        def col(name):
            return np.array([r[head.index(name)] for r in rows], dtype=float)
        times = col("clip_time_s")
        active = col("hand_active") == 1
        def joint(name):
            xyz = np.column_stack([col(f"{name}_{axis}_m") for axis in "xyz"])
            ok = active & (col(f"{name}_valid") == 1) & (col(f"{name}_tracked") == 1) & np.isfinite(xyz).all(axis=1)
            xyz[~ok] = np.nan
            return xyz, ok
        wrist, ok = joint("Wrist")
        thumb, thumb_ok = joint("ThumbTip")
        index, index_ok = joint("IndexTip")
        first = np.flatnonzero(ok)[0]
        delta = (wrist - wrist[first]) * 100
        gap = np.linalg.norm(thumb - index, axis=1) * 100
        gap[~(thumb_ok & index_ok)] = np.nan
        # Break lines across unusually long sampling gaps; never bridge missing tracking.
        long_gap = np.r_[False, np.diff(times) > .1]
        delta[long_gap] = np.nan
        gap[long_gap] = np.nan
        result[side] = dict(time=times, delta=delta, gap=gap, valid=ok,
                            sensor_ticks=[r[1] for r in rows], baseline_time=float(times[first]))
    return result


def make_plot(signals, duration):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.labelcolor": MUTED, "text.color": TEXT,
                         "xtick.color": MUTED, "ytick.color": MUTED})
    fig, axes = plt.subplots(3, 1, figsize=(PLOT_W/100, PLOT_H/100), dpi=100)
    fig.patch.set_facecolor(BG)
    fig.subplots_adjust(left=.13, right=.98, top=.95, bottom=.07, hspace=.48)
    for ax in axes:
        ax.set_facecolor("#142237")
        ax.set_xlim(0, duration)
        ax.grid(color="#33465f", alpha=.5, linewidth=.6)
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["bottom", "left"]].set_color("#41546e")
        ax.set_xlabel("Clip time (s)", fontsize=10)
    for side, ax in zip(["Left", "Right"], axes[:2]):
        s = signals[side]
        for k, (axis, color) in enumerate(zip("XYZ", COLORS)):
            ax.plot(s["time"], s["delta"][:, k], color=color, linewidth=1.8, label=axis)
        ax.set_title(f"{side} wrist · change in world position", loc="left", fontsize=14, weight="bold", pad=13)
        ax.set_ylabel("Change (cm)", fontsize=11)
        ax.legend(loc="upper right", ncol=3, frameon=False, labelcolor=TEXT, fontsize=10)
        ax.axhline(0, color=MUTED, linewidth=.7, alpha=.7)
        steps = np.linalg.norm(np.diff(s["delta"], axis=0), axis=1)
        if np.isfinite(steps).any() and np.nanmax(steps) > 30:
            k = int(np.nanargmax(steps)) + 1
            axis = int(np.argmax(np.abs(s["delta"][k] - s["delta"][k-1])))
            ax.annotate("Sharp step in source tracking", xy=(s["time"][k], s["delta"][k,axis]),
                        xytext=(.03,.86),textcoords="axes fraction",color="#ffa8a8",fontsize=10,
                        arrowprops=dict(arrowstyle="->",color="#ffa8a8",linewidth=1.1))
    for side in ["Left", "Right"]:
        s = signals[side]
        axes[2].plot(s["time"], s["gap"], color=HAND_COLORS[side], linewidth=1.8, label=side)
    axes[2].set_title("Thumb tip to index tip · finger opening", loc="left", fontsize=14, weight="bold", pad=13)
    axes[2].set_ylabel("Distance (cm)", fontsize=11)
    axes[2].set_ylim(bottom=0)
    axes[2].legend(loc="upper right", ncol=2, frameon=False, labelcolor=TEXT, fontsize=10)
    fig.canvas.draw()
    backgrounds = Image.fromarray(np.asarray(fig.canvas.buffer_rgba()).copy()).convert("RGB")
    # Save each plot's exact data-to-image map for the animated cursor and markers.
    transforms = []
    for ax in axes:
        p0 = ax.transData.transform((0, 0))
        p1 = ax.transData.transform((1, 1))
        transforms.append(dict(x0=p0[0]+PLOT_X, sx=p1[0]-p0[0],
                               y0=PLOT_Y+PLOT_H-p0[1], sy=-(p1[1]-p0[1]),
                               top=PLOT_Y+PLOT_H-ax.bbox.y1, bottom=PLOT_Y+PLOT_H-ax.bbox.y0))
    plt.close(fig)
    return backgrounds, transforms


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        block = stream.read(size - len(data))
        if not block:
            raise RuntimeError("Video decoder ended before the expected frame")
        data.extend(block)
    return bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=Path(__file__).resolve().parent/"sample")
    args = parser.parse_args()
    folder = args.folder
    report = json.loads((folder / "validation.json").read_text())
    video = folder / "hand_movement.mp4"
    if digest(video) != report["clip_sha256"]:
        raise ValueError("Source clip was modified; recreate it before generating the visualization")
    ffmpeg = ffmpeg_executable()
    frames = probe_video(ffmpeg, video)
    duration = report["clip_duration_s"]
    fps = Fraction(len(frames) / duration).limit_denominator(1_000_000)
    output_times = np.arange(len(frames)) / float(fps)
    pts_error = float(np.max(np.abs(np.array([p for _, p in frames]) - output_times)))
    if pts_error > .001:
        raise ValueError("This source has variable timestamps; constant-rate visualization would misalign it")
    signals = load_signals(folder)
    plot, maps = make_plot(signals, duration)
    font_path = font_manager.findfont("DejaVu Sans")
    font = lambda size: ImageFont.truetype(font_path, size)
    fonts = {n:font(n) for n in [19, 21, 23, 26, 30, 42]}
    base = Image.new("RGB", (WIDTH, HEIGHT), BG)
    base.paste(plot, (PLOT_X, PLOT_Y))
    draw = ImageDraw.Draw(base)
    draw.text((36, 23), "Hand movement and recorded signals", font=fonts[42], fill=TEXT)
    draw.text((38, 79), "HoloAssist · R0027-12-GoPro · 8-second excerpt", font=fonts[21], fill=MUTED)
    draw.text((VIDEO_X, 696), "How to read this", font=fonts[30], fill=TEXT)
    for y, line in [(743,"The white cursor follows the video time on every plot."),
                    (777,"Wrist X / Y / Z: change from each hand's first tracked sample."),
                    (811,"Finger opening: 3D distance between thumb tip and index tip."),
                    (845,"Blank line segments indicate invalid or missing tracking."),
                    (879,"World coordinates in centimetres; these are not screen pixels.")]:
        draw.text((VIDEO_X, y), line, font=fonts[21], fill=MUTED)
    draw.text((36, 1015), "A sharp right-wrist spike near 7.4 s may be a tracking artifact. It is preserved in the plotted source data.", font=fonts[19], fill="#ffa8a8")
    draw.text((36, 1048), "Original sensor timestamps · no signal interpolation · all exported rows retained in the workbook", font=fonts[19], fill=MUTED)
    decoder = subprocess.Popen([ffmpeg,"-v","error","-i",str(video),"-vf",f"scale={VIDEO_W}:{VIDEO_H}",
                                "-fps_mode","passthrough","-f","rawvideo","-pix_fmt","rgb24","pipe:1"], stdout=subprocess.PIPE)
    target = folder / "hand_signals_with_video.mp4"
    encoder = subprocess.Popen([ffmpeg,"-y","-v","error","-f","rawvideo","-pix_fmt","rgb24",
                                "-s",f"{WIDTH}x{HEIGHT}","-r",f"{fps.numerator}/{fps.denominator}","-i","pipe:0",
                                "-an","-c:v","libx264","-preset","fast","-crf","18","-pix_fmt","yuv420p",
                                "-movflags","+faststart",str(target)], stdin=subprocess.PIPE)
    max_sample_offset = 0.
    try:
        for i, (_, time_s) in enumerate(frames):
            frame = base.copy()
            source = Image.frombytes("RGB",(VIDEO_W,VIDEO_H),read_exact(decoder.stdout, VIDEO_W*VIDEO_H*3))
            frame.paste(source,(VIDEO_X,VIDEO_Y))
            pen = ImageDraw.Draw(frame)
            pen.rounded_rectangle((VIDEO_X+16,VIDEO_Y+16,VIDEO_X+335,VIDEO_Y+65),radius=8,fill=BG)
            pen.text((VIDEO_X+30,VIDEO_Y+24),f"Clip time  {time_s:05.2f} / {duration:.2f} s",font=fonts[23],fill=TEXT)
            for m in maps:
                x = m["x0"] + m["sx"]*time_s
                pen.line((x,m["top"],x,m["bottom"]),fill="#ffffff",width=2)
            for side_index, side in enumerate(["Left", "Right"]):
                signal = signals[side]
                j = int(np.argmin(np.abs(signal["time"]-time_s)))
                dt = float(signal["time"][j]-time_s)
                max_sample_offset = max(max_sample_offset, abs(dt))
                near = abs(dt) <= .06
                # Markers sit on the actual sensor sample time, independently of the video cursor.
                for k in range(3):
                    value = signal["delta"][j,k]
                    m = maps[side_index]
                    if near and np.isfinite(value):
                        x,y=m["x0"]+m["sx"]*signal["time"][j],m["y0"]+m["sy"]*value
                        pen.ellipse((x-5,y-5,x+5,y+5),fill=COLORS[k],outline=BG,width=1)
                gap = signal["gap"][j]
                if near and np.isfinite(gap):
                    m=maps[2]
                    x,y=m["x0"]+m["sx"]*signal["time"][j],m["y0"]+m["sy"]*gap
                    pen.ellipse((x-5,y-5,x+5,y+5),fill=HAND_COLORS[side],outline=BG,width=1)
                y=932+side_index*37
                status="wrist tracked" if near and signal["valid"][j] else "wrist tracking unavailable"
                gap_text=f"{gap:.1f} cm" if near and np.isfinite(gap) else "unavailable"
                pen.text((VIDEO_X,y),f"{side}: {status}   |   finger opening {gap_text}",font=fonts[21],fill=HAND_COLORS[side])
            encoder.stdin.write(frame.tobytes())
            if i in [0,len(frames)//2,len(frames)-1]:
                frame.save(folder / f"signals_preview_{i:03d}.jpg",quality=92)
        if decoder.stdout.read(1):
            raise RuntimeError("Unexpected extra decoded video frames")
        encoder.stdin.close()
        if decoder.wait() != 0 or encoder.wait() != 0:
            raise RuntimeError("FFmpeg decode or encode failed")
    finally:
        if decoder.poll() is None: decoder.kill()
        if encoder.poll() is None: encoder.kill()
    output_pts=probe_video(ffmpeg,target)
    if len(output_pts) != len(frames):
        raise RuntimeError("Visualization frame count mismatch")
    residual=float(max(abs(a[1]-b[1]) for a,b in zip(output_pts,frames)))
    if residual>.001: raise RuntimeError("Visualization timing drift exceeds 1 ms")
    verification=dict(frames=len(frames),duration_s=duration,output_pts_max_difference_s=residual,
                      maximum_nearest_sensor_offset_s=max_sample_offset,
                      source_clip_sha256=digest(video),source_signal_sha256=digest(folder / "hand_data.json"),
                      visualization_sha256=digest(target),signals=["Left wrist delta X/Y/Z (cm)",
                      "Right wrist delta X/Y/Z (cm)","Left and right thumb-tip to index-tip distance (cm)"],
                      baseline_times_s={side:s["baseline_time"] for side,s in signals.items()},
                      missing_data="NaN gaps; no interpolation; invalid samples have no markers")
    (folder / "signal_video_validation.json").write_text(json.dumps(verification,indent=2))
    print(json.dumps(verification,indent=2))
    print(target.resolve())


if __name__ == "__main__":
    main()
