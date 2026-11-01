"""Extract exact original hand rows and nearby camera poses for the shared clip."""
import argparse
import json
from pathlib import Path
import shutil
from extract_hand_clip import digest


def make_excerpt(root=Path("download_cache"),sample=Path("sample")):
    report=json.loads((sample/"validation.json").read_text())
    tables=json.loads((sample/"hand_data.json").read_text())
    base=root/report["session"]/"Export_py"
    raw=sample/"raw"
    manifest={"session":report["session"],"source":"https://holoassist.github.io/",
              "license":"CDLA-Permissive-2.0","files":{}}
    for side in ["Left","Right"]:
        wanted={(float(row[0]),row[1]) for row in tables[side]["rows"]}
        path=base/"Hands"/f"{side}_sync.txt"
        selected=[]
        with path.open("rb") as source:
            for line in source:
                fields=line.split()
                if fields and (float(fields[0]),fields[1].decode()) in wanted:
                    selected.append(line)
                    wanted.remove((float(fields[0]),fields[1].decode()))
        if wanted:raise ValueError(f"Missing original {side} hand samples")
        target=raw/"Hands"/path.name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(b"".join(selected))
        manifest["files"][str(target.relative_to(sample))]={"rows":len(selected),"sha256":digest(target),
            "source_member":f"{report['session']}/Export_py/Hands/{path.name}","transformation":"None; exact original lines"}
    origin=int(report["video_start_ticks_text"])
    lower=origin+round((report["clip_start_video_s"]-.25)*1e7)
    upper=origin+round((report["clip_end_video_s"]+.25)*1e7)
    selected=[]
    with (base/"Video/Pose_sync.txt").open("rb") as source:
        for line in source:
            fields=line.split()
            if fields and lower<=int(fields[1])<=upper:selected.append(line)
    target=raw/"Video/Pose_sync.txt"
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(b"".join(selected))
    manifest["files"][str(target.relative_to(sample))]={"rows":len(selected),"sha256":digest(target),
        "source_member":f"{report['session']}/Export_py/Video/Pose_sync.txt",
        "transformation":"Exact original lines, clip interval plus 0.25-second margins"}
    timing=raw/"Video/VideoMp4Timing.txt"
    shutil.copyfile(base/"Video/VideoMp4Timing.txt",timing)
    manifest["files"][str(timing.relative_to(sample))]={"sha256":digest(timing),
        "transformation":"Unmodified original recording start/end UTC ticks"}
    (sample/"raw_excerpt_manifest.json").write_text(json.dumps(manifest,indent=2))
    print(json.dumps(manifest,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path("download_cache"))
    parser.add_argument("--sample",type=Path,default=Path("sample"))
    args=parser.parse_args();make_excerpt(args.root,args.sample)
