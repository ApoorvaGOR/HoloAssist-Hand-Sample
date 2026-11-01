"""Generate a column-by-column dictionary for both exported hand worksheets."""
import csv
import json
from pathlib import Path
from openpyxl.utils import get_column_letter
from extract_hand_clip import JOINTS

ROOT=Path(__file__).resolve().parent


def main():
    tables=json.loads((ROOT/"sample/hand_data.json").read_text())
    meta=[
        ("time","s","number",0,"Original synchronized-grid time, preserved separately from sensor time."),
        ("time","100 ns UTC ticks","text",1,"Exact original .NET timestamp since 0001-01-01; do not convert to an Excel numeric cell."),
        ("time","s","number","derived","(integer sensor ticks - original MP4 start ticks) / 10000000."),
        ("time","s","number","derived","video_time_s - actual selected original-video start time; can repeat."),
        ("alignment","frame index","integer","derived","Nearest decoded original MP4 frame, zero-based; not clip-frame number."),
        ("alignment","s","number","derived","Presentation timestamp of nearest original MP4 frame."),
        ("alignment","ms","number","derived","1000 * (video_time_s - nearest_video_time_s); signed timing residual."),
        ("quality","0 or 1","integer",2,"Original hand active flag; combine with joint validity/tracking and finite-value checks.")]
    target=ROOT/"docs/column_dictionary.csv"
    with target.open("w",newline="",encoding="utf-8") as f:
        writer=csv.writer(f)
        writer.writerow(["sheet","excel_column","column_name","kind","unit","type","raw_field_index_0_based","description"])
        for side in ["Left","Right"]:
            for i,name in enumerate(tables[side]["header"]):
                if i<8:item=meta[i]
                else:
                    j,component=divmod(i-8,21);joint=JOINTS[j]
                    if component<16:
                        r,c=divmod(component,4)
                        translation=c==3 and r<3
                        text=f"{joint} pose matrix M{r}{c}, row-major. "
                        text+=("World translation component." if translation else "Rotation component." if r<3 and c<3 else "Homogeneous matrix bottom row; normally 0,0,0,1.")
                        item=("matrix","m" if translation else "dimensionless","number",3+j*16+component,text)
                    elif component<19:
                        axis=component-16
                        item=("position","m","number",3+j*16+axis*4+3,
                              f"{joint} world {'xyz'[axis]} position; duplicates the same joint's M{axis}3 value.")
                    else:
                        valid=component==19
                        item=("quality","0 or 1","integer",(419 if valid else 445)+j,
                              f"Original {joint} {'valid' if valid else 'tracked'} flag. A 1 does not certify physical accuracy.")
                writer.writerow([f"{side}_hand",get_column_letter(i+1),name,*item])
    print(f"Wrote 1108 header definitions: {target}")


if __name__=="__main__":main()
