"""Rebuild the included Excel and visualizations, optionally from upstream data.

python reproduce.py               # use the included sample; no data download
python reproduce.py --from-source # download one upstream session, extract clip
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-source",action="store_true",help="Download about 276 MB of upstream data before rebuilding")
    parser.add_argument("--skip-videos",action="store_true",help="Only rebuild Excel and verify sample values")
    args=parser.parse_args()
    os.chdir(ROOT)
    if args.from_source:
        from download_sample import download_session
        download_session("R0027-12-GoPro",Path("download_cache"))
        subprocess.run([sys.executable,"extract_hand_clip.py","--start","369","--duration","8"],check=True)
        from make_raw_excerpt import make_excerpt
        make_excerpt()
        shutil.copyfile("download_cache/R0027-12-GoPro/download_manifest.json","sample/download_manifest.json")
    else:
        from export_excel import export_workbook
        export_workbook(ROOT/"sample")
    subprocess.run([sys.executable,"verify_export.py"],check=True)
    if not args.skip_videos:
        subprocess.run([sys.executable,"make_signal_video.py"],check=True)
        subprocess.run([sys.executable,"diagnose_hand_signals.py"],check=True)
    subprocess.run([sys.executable,"make_manifest.py"],check=True)
    print("Done: sample/ contains the Excel workbook and video outputs.")


if __name__=="__main__":main()
