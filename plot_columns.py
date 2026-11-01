"""Plot literal exported columns, without camera transforms or baseline changes.

Example: python plot_columns.py --hand Right --columns Wrist_x_m Wrist_y_m Wrist_z_m
"""
import argparse
import json
from pathlib import Path
import make_signal_video  # configure a local Matplotlib cache and noninteractive backend
from matplotlib import pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hand",choices=["Left","Right"],default="Left")
    parser.add_argument("--columns",nargs="+",default=["Wrist_x_m","Wrist_y_m","Wrist_z_m"])
    parser.add_argument("--out",type=Path)
    args=parser.parse_args()
    table=json.loads((ROOT/"sample/hand_data.json").read_text())[args.hand]
    header=table["header"]
    time=np.array([r[header.index("clip_time_s")] for r in table["rows"]])
    fig,ax=plt.subplots(figsize=(10,4.5),layout="constrained")
    for name in args.columns:
        if name not in header:parser.error(f"Unknown column: {name}")
        value=np.array([r[header.index(name)] for r in table["rows"]],dtype=float)
        ax.plot(time,value,label=name,linewidth=1.4)
    ax.set_xlabel("Clip time (s)")
    ax.set_ylabel("World position (m)" if all(name.endswith("_m") for name in args.columns) else "Original exported value")
    ax.set_title(f"{args.hand} hand: original exported columns")
    ax.grid(alpha=.25);ax.legend()
    target=args.out or ROOT/"sample"/f"{args.hand.lower()}_wrist_positions.png"
    target.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(target,dpi=160);plt.close(fig)
    print(target.resolve())


if __name__=="__main__":main()
