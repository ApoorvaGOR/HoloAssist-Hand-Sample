"""Portable Excel export; no Node.js, Codex, or proprietary authoring package.

Run: python export_excel.py [sample_folder]
"""
import json
from pathlib import Path
import sys
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def export_workbook(folder=Path("sample")):
    folder=Path(folder)
    data=json.loads((folder/"hand_data.json").read_text())
    report=json.loads((folder/"validation.json").read_text())
    book=Workbook(write_only=True)
    def sheet(name,header,widths=None):
        ws=book.create_sheet(name)
        ws.sheet_view.showGridLines=False
        ws.freeze_panes="E2" if name.endswith("_hand") else "F2" if name=="Matrix_rows" else None
        ws.row_dimensions[1].height=42
        for i,title in enumerate(header,1):
            dim=ws.column_dimensions[get_column_letter(i)]
            dim.width=(widths or {}).get(i,18)
            dim.number_format="0.000000"
        cells=[]
        for title in header:
            cell=WriteOnlyCell(ws,title)
            cell.font=Font(name="Arial",size=10,bold=True,color="FFFFFF")
            cell.fill=PatternFill("solid",fgColor="23435E")
            cell.alignment=Alignment(horizontal="center",vertical="center",wrap_text=True)
            cells.append(cell)
        ws.append(cells)
        return ws
    for side in ["Left","Right"]:
        table=data[side]
        ws=sheet(f"{side}_hand",table["header"],{1:21,2:28,3:18,4:18,5:21,6:23,7:24,8:15})
        ws.column_dimensions["B"].number_format="@"
        for col in [5,8]:ws.column_dimensions[get_column_letter(col)].number_format="0"
        for j in range(26):
            for col in [8+j*21+20,8+j*21+21]:ws.column_dimensions[get_column_letter(col)].number_format="0"
        for source in table["rows"]:
            row=list(source)
            timestamp=WriteOnlyCell(ws,str(row[1]));timestamp.number_format="@";timestamp.data_type="s"
            row[1]=timestamp
            ws.append(row)
        ws.auto_filter.ref=f"A1:{get_column_letter(len(table['header']))}{len(table['rows'])+1}"
    header=["hand","source_sync_time_s","timestamp_ticks_text","clip_time_s","joint","matrix_row_0_based",
            "column_0","column_1","column_2","column_3","active","valid","tracked"]
    ws=sheet("Matrix_rows",header,{1:10,2:21,3:28,4:18,5:25,6:23})
    ws.column_dimensions["C"].number_format="@"
    for col in [6,11,12,13]:ws.column_dimensions[get_column_letter(col)].number_format="0"
    count=0
    for side in ["Left","Right"]:
        table=data[side]
        for row in table["rows"]:
            for j in range(26):
                offset=8+21*j
                joint=table["header"][offset].removesuffix("_M00")
                for r in range(4):
                    tick=WriteOnlyCell(ws,str(row[1]));tick.number_format="@";tick.data_type="s"
                    ws.append([side,row[0],tick,row[3],joint,r,*row[offset+4*r:offset+4*r+4],row[7],row[offset+19],row[offset+20]])
                    count+=1
    ws.auto_filter.ref=f"A1:M{count+1}"
    notes=[
        ["Recording",report["session"]],
        ["Original video interval (s)",f"[{report['clip_start_video_s']}, {report['clip_end_video_s']})"],
        ["Duration (s)",report["clip_duration_s"]],
        ["Video frames",report["clip_frames"]],
        ["Samples per hand",f"Left {len(data['Left']['rows'])}; Right {len(data['Right']['rows'])}"],
        ["Joint count","26 per hand, 52 total; PSI joint order. See docs/data_dictionary.md."],
        ["Columns per hand","554: 8 metadata + 26 joints x (16 matrix entries + 3 duplicated XYZ positions + 2 flags)."],
        ["Matrix_rows","Four consecutive rows and four columns per hand, timestamp and joint; all original observations included."],
        ["Pose matrix","4x4 row-major: upper-left 3x3 is rotation; x=M03, y=M13, z=M23; bottom row normally 0,0,0,1."],
        ["Position units","World coordinates, metres. These are not image pixels."],
        ["Timestamp ticks","Exact original integer represented as TEXT: .NET UTC ticks, 100 ns since 0001-01-01."],
        ["Source synchronized time","source_sync_time_s is the source synchronized-grid time, preserved independently of sensor time."],
        ["Video time","Integer sensor ticks minus VideoMp4Timing start ticks, divided by 10000000."],
        ["Clip time","video_time_s minus the actual selected clip start time."],
        ["Nearest video frame","Zero-based original MP4 frame matched by decoded presentation timestamp; timing residual is included."],
        ["Validity","For a usable joint require hand_active=1, joint_valid=1, joint_tracked=1, and finite values. Flags alone do not guarantee accuracy."],
        ["Missing values","NaN/Inf is blank; finite invalid poses are preserved with their flags. No zero replacement or interpolation."],
        ["Known issue","Two repeated tracked right-wrist records near clip time 7.411 s land behind the camera after transformation; inspect as a possible tracking/alignment artifact."],
        ["Reproducibility","python export_excel.py; python verify_export.py. Original excerpt: sample/raw/. Full dictionary: docs/column_dictionary.csv."],
        ["Data license","CDLA-Permissive-2.0. See LICENSE-DATA.txt; original data: https://holoassist.github.io/"],
        ["Source format specification","https://github.com/microsoft/psi/tree/master/Sources/MixedReality/HoloLensCapture/HoloLensCaptureExporter"],
        ["Camera transform reference","https://github.com/taeinkwon/PyHoloAssist/blob/main/hand_eye_project.py"],
    ]
    ws=sheet("Read_me",["Field","Definition"],{1:32,2:110})
    for number,row in enumerate(notes,2):
        ws.row_dimensions[number].height=32
        cells=[]
        for value in row:
            cell=WriteOnlyCell(ws,value)
            cell.font=Font(name="Arial",size=10)
            cell.alignment=Alignment(wrap_text=True,vertical="center")
            cells.append(cell)
        ws.append(cells)
    target=folder/"hand_tracking.xlsx"
    book.save(target)
    print(f"Saved {target}; {count} matrix rows")
    return target


if __name__=="__main__":
    export_workbook(Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parent/"sample")
