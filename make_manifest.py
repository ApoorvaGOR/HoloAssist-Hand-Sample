"""Write or check checksums for files distributed in sample/."""
import argparse
import json
from pathlib import Path
from extract_hand_clip import digest

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args()
    target=ROOT/"sample/sample_manifest.json"
    if args.check:
        manifest=json.loads(target.read_text())
        for name,item in manifest["files"].items():
            path=ROOT/name
            if not path.is_file() or digest(path)!=item["sha256"]:
                raise RuntimeError(f"Changed or missing sample file: {name}")
        print(f"Verified {len(manifest['files'])} distributed sample files")
        return
    files={}
    for path in sorted((ROOT/"sample").rglob("*")):
        if not path.is_file() or path==target or "_preview" in path.name:continue
        files[str(path.relative_to(ROOT))]={"bytes":path.stat().st_size,"sha256":digest(path)}
    result={"data_license":"CDLA-Permissive-2.0","source":"https://holoassist.github.io/",
            "recording":"R0027-12-GoPro","files":files}
    target.write_text(json.dumps(result,indent=2))
    print(f"Wrote {len(files)} sample checksums")


if __name__=="__main__":main()
