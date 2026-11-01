# Data dictionary

This document describes `sample/hand_tracking.xlsx` and `sample/hand_data.json`. [column_dictionary.csv](column_dictionary.csv) contains one definition for every header in both hand worksheets, including units and the corresponding raw-field index.

## Workbook structure

| Worksheet | Records / columns | Meaning |
|---|---|---|
| `Left_hand` | 240 data rows x 554 columns | One original synchronized left-hand sample per row |
| `Right_hand` | 240 data rows x 554 columns | One original synchronized right-hand sample per row |
| `Matrix_rows` | 49,920 data rows x 13 columns | Every hand/time/joint matrix displayed as four consecutive rows |
| `Read_me` | Definitions | Units, source, quality flags, reproduction and license notes |

Both hand worksheets extend from column A through UH. Columns A:H are metadata; I:UH contain the joint values. Source row order is preserved. Different sensor/video rates mean the 240 hand samples do not correspond one-to-one to the 196 video frames.

## The first eight columns

| Column | Meaning | Unit / storage |
|---|---|---|
| `source_sync_time_s` | Source synchronized-grid time | seconds, numeric; strictly increasing in this sample |
| `sensor_timestamp_ticks_text` | Original sensor UTC timestamp | exact text; 100-ns ticks since 0001-01-01 |
| `video_time_s` | Sensor timestamp minus original MP4 origin | seconds; integer subtraction performed before float conversion |
| `clip_time_s` | `video_time_s` minus selected clip start | seconds; may repeat because source sensor timestamps can repeat |
| `nearest_video_frame` | Nearest original MP4 decoded frame | zero-based integer; refers to original recording, not the short clip |
| `nearest_video_time_s` | Nearest original MP4 presentation timestamp | seconds from original video start |
| `sensor_minus_video_ms` | Sensor time minus nearest MP4 frame time | signed milliseconds |
| `hand_active` | Original active flag | 0 or 1 |

The original video origin is in `sample/raw/Video/VideoMp4Timing.txt`. Its two lines are the original recording start and end ticks, not the short clip's rebased start/end ticks. Never parse the 18-digit original tick field through a floating-point number or store it as an ordinary Excel numeric value: the final digits would be lost.

## The 26 joints per hand

| Zero-based joint indices | Names, in order |
|---|---|
| 0 | Palm |
| 1 | Wrist |
| 2–5 | ThumbMetacarpal, ThumbProximal, ThumbDistal, ThumbTip |
| 6–10 | IndexMetacarpal, IndexProximal, IndexIntermediate, IndexDistal, IndexTip |
| 11–15 | MiddleMetacarpal, MiddleProximal, MiddleIntermediate, MiddleDistal, MiddleTip |
| 16–20 | RingMetacarpal, RingProximal, RingIntermediate, RingDistal, RingTip |
| 21–25 | PinkyMetacarpal, PinkyProximal, PinkyIntermediate, PinkyDistal, PinkyTip |

## Twenty-one columns per joint

For a joint named `Wrist`, the columns are:

```text
Wrist_M00 Wrist_M01 Wrist_M02 Wrist_M03
Wrist_M10 Wrist_M11 Wrist_M12 Wrist_M13
Wrist_M20 Wrist_M21 Wrist_M22 Wrist_M23
Wrist_M30 Wrist_M31 Wrist_M32 Wrist_M33
Wrist_x_m Wrist_y_m Wrist_z_m Wrist_valid Wrist_tracked
```

The matrix is a **4x4 pose**, flattened in row-major order. Its upper-left 3x3 block is rotation. Translation is the last column: `x_m=M03`, `y_m=M13`, `z_m=M23`, in **world-coordinate metres**. The bottom row of a valid rigid pose is `[0,0,0,1]`. The explicit XYZ columns duplicate the matrix translation; they are not extra sensor observations. These are not image-pixel positions, velocities or per-frame displacements.

There are 16 matrix entries + 3 duplicated position entries + 2 quality flags = 21 columns per joint. Thus 26 x 21 + 8 = **554 columns per hand**, or **1,092 joint-related numeric columns** when both hands are combined after excluding their metadata.

For the included full sample, 234 combined columns are constant and 571 duplicate an earlier column exactly under the benchmark's byte-equality check. These categories overlap. Constants include homogeneous matrix entries and some flags; repeated positions and shared constant patterns account for many duplicates. All are retained.

## Quality and missing values

A candidate usable joint requires `hand_active=1`, that joint's `valid=1`, its `tracked=1`, and finite matrix values. NaN/Inf becomes blank in Excel and `null` in JSON. Finite values in an invalid observation are retained with their original flags. Nothing is silently replaced with zero or interpolated.

Flags do not guarantee physical accuracy. The right wrist has two repeated flagged-as-tracked observations near clip time 7.411 s that become negative-depth camera points. The camera-plane view omits those points, while the depth plot preserves the negative source measurement. See `sample/tracking_diagnostic.json` and the README limitations.

## Original raw hand format

Each original synchronized hand line has **471 whitespace-separated fields**:

| Zero-based raw fields | Contents |
|---|---|
| 0 | synchronized-grid time, seconds |
| 1 | original integer UTC sensor ticks |
| 2 | hand active flag |
| 3–418 | 26 row-major 4x4 matrices, 416 numbers |
| 419–444 | 26 joint valid flags |
| 445–470 | 26 joint tracked flags |

`sample/raw/Hands/` preserves the exact original lines matching the 240 exported observations per hand. `sample/raw/Video/Pose_sync.txt` contains nearby original camera rows, including 0.25-second time margins, so camera/hand matching does not depend on excerpt row numbers being identical.

## Derived visualizations

The world-signal video uses `(position - first usable position) * 100` to show wrist changes in centimetres, plus `100 * norm(ThumbTip - IndexTip)` for finger opening. These transformations are not new raw columns in the workbook.

The diagnostic uses `AXIS @ inverse(camera_world_pose) @ joint_world_pose`, with the camera convention from the official PyHoloAssist implementation. It plots normalized camera `X/Z` and `Y/Z`, camera Z depth in centimetres and 3D wrist separation in centimetres. The separate skeleton is a schematic projection. Without camera intrinsics, it is not a calibrated overlay on the original pixels.

The raw-column plotting script `plot_columns.py` applies neither of these transformations and can be compared directly to the chosen workbook columns.
