"""Compare camera-relative hand tracking with the original clip; expose failures.

Camera conversion follows the official PyHoloAssist implementation:
inv(axis convention) @ inv(camera world pose) @ joint world pose.
No fitted calibration, lag adjustment, smoothing, or motion-based filtering.
"""
import json
from pathlib import Path
from fractions import Fraction
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import make_signal_video as common
from matplotlib import pyplot as plt, font_manager
from extract_hand_clip import load_hand, usable, ffmpeg_executable, probe_video, digest

OUT=Path(__file__).resolve().parent/"sample"
COL={"Left":"#ce9fff","Right":"#63dfeb"}
BG=common.BG
LINKS=[(0,1),(1,2),(2,3),(3,4),(4,5),(1,6),(6,7),(7,8),(8,9),(9,10),
       (1,11),(11,12),(12,13),(13,14),(14,15),(1,16),(16,17),(17,18),(18,19),(19,20),
       (1,21),(21,22),(22,23),(23,24),(24,25)]
AXIS=np.array([[0.,-1,0],[0,0,-1],[1,0,0]])

def nearest(sorted_values, targets):
    k=np.clip(np.searchsorted(sorted_values,targets),0,len(sorted_values)-1)
    prev=np.maximum(0,k-1)
    use_prev=np.abs(sorted_values[prev]-targets)<=np.abs(sorted_values[k]-targets)
    return np.where(use_prev,prev,k)

def load():
    report=json.loads((OUT/"validation.json").read_text())
    root=OUT/"raw"
    origin=int(report["video_start_ticks_text"])
    lines=[line.split() for line in (root/"Video/Pose_sync.txt").read_text().splitlines() if line.strip()]
    camera_ticks=np.array([int(x[1]) for x in lines],dtype=np.int64)
    camera_grid=np.array([float(x[0]) for x in lines])
    poses=np.array([[float(x) for x in line[2:]] for line in lines]).reshape(-1,4,4)
    if np.any(np.diff(camera_ticks)<0): raise ValueError("Camera times are unordered")
    signals={}
    diagnostics={}
    for side in ["Left","Right"]:
        hand=load_hand(root/"Hands"/f"{side}_sync.txt")
        time=(hand["ticks"]-origin)/1e7-report["clip_start_video_s"]
        select=(time>=0)&(time<report["clip_duration_s"])
        indices=np.flatnonzero(select)
        ct=nearest(camera_ticks,hand["ticks"][select])
        inv_camera=np.linalg.inv(poses[ct])
        world=hand["matrix"][select,:,:3,3]
        local=np.einsum("nij,nkj->nki",inv_camera[:,:3,:3],world)+inv_camera[:,None,:3,3]
        xyz=np.einsum("ij,nkj->nki",AXIS,local)
        good=usable(hand)[select]
        depth=xyz[:,1,2]*100
        depth[~good[:,1]]=np.nan
        wrist=xyz[:,1]
        uv=np.full((len(indices),26,2),np.nan)
        projectable=good&(xyz[:,:,2]>0)
        uv[projectable]=xyz[projectable,:2]/xyz[projectable,2,None]
        separation_world=world[:,1].copy()
        separation_world[~good[:,1]]=np.nan
        delta_ms=(hand["ticks"][select]-camera_ticks[ct])/1e4
        grid_indices=np.searchsorted(camera_grid,hand["sync_time"][select])
        if np.any(grid_indices>=len(camera_grid)) or not np.array_equal(camera_grid[grid_indices],hand["sync_time"][select]):
            raise ValueError("Camera excerpt does not contain all hand synchronized-grid times")
        same_grid_ms=(hand["ticks"][select]-camera_ticks[grid_indices])/1e4
        bad=good[:,1]&(xyz[:,1,2]<=0)
        signals[side]=dict(time=time[select],uv=uv,depth=depth,good=good,world_wrist=separation_world,
                           camera_xyz=xyz,alignment_ms=delta_ms)
        diagnostics[side]=dict(behind_camera_tracked_wrist_samples=int(bad.sum()),
            behind_camera_times_s=[float(t) for t in time[select][bad]],
            camera_nearest_pose_max_difference_ms=float(np.max(np.abs(delta_ms))),
            original_same_grid_hand_camera_max_difference_ms=float(np.max(np.abs(same_grid_ms))))
    if not np.array_equal(signals["Left"]["time"],signals["Right"]["time"]):
        raise ValueError("This comparison requires equal left/right sample times")
    sep=np.linalg.norm(signals["Left"]["world_wrist"]-signals["Right"]["world_wrist"],axis=1)*100
    return report,signals,sep,diagnostics

def chart(signals,separation,duration):
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"text.color":common.TEXT,
        "axes.labelcolor":common.MUTED,"xtick.color":common.MUTED,"ytick.color":common.MUTED})
    W,H,X,Y=818,890,1070,105
    fig,axes=plt.subplots(4,1,figsize=(W/100,H/100),dpi=100)
    fig.patch.set_facecolor(BG)
    fig.subplots_adjust(left=.13,right=.98,top=.96,bottom=.06,hspace=.68)
    titles=["Wrist horizontal position · increasing means right", "Wrist vertical position · increasing means down",
            "Wrist distance in front of camera · negative is suspect", "Distance between wrists · raw tracking"]
    for n,ax in enumerate(axes):
        ax.set_facecolor("#142237"); ax.set_xlim(0,duration)
        ax.set_title(titles[n],loc="left",fontsize=12,weight="bold",pad=9)
        ax.set_xlabel("Clip time (s)",fontsize=9)
        ax.grid(color="#33465f",alpha=.5,linewidth=.6)
        ax.spines[["top","right"]].set_visible(False)
        ax.spines[["bottom","left"]].set_color("#41546e")
        if n<3:
            for side,s in signals.items():
                values=s["uv"][:,1,n] if n<2 else s["depth"]
                ax.plot(s["time"],values,color=COL[side],label=side,linewidth=1.7)
            ax.legend(loc="upper right",ncol=2,frameon=False,labelcolor=common.TEXT,fontsize=9)
        else:
            ax.plot(signals["Left"]["time"],separation,color="#ffbf6b",linewidth=1.7)
    axes[0].set_ylabel("Camera X / Z")
    axes[1].set_ylabel("Camera Y / Z"); axes[1].invert_yaxis()
    axes[2].set_ylabel("Depth (cm)")
    axes[2].axhline(0,color="#ff9d9d",linewidth=1)
    lo,hi=axes[2].get_ylim()
    if lo<0: axes[2].axhspan(lo,0,color="#ff6969",alpha=.16)
    axes[3].set_ylabel("Distance (cm)")
    fig.canvas.draw()
    img=Image.fromarray(np.asarray(fig.canvas.buffer_rgba()).copy()).convert("RGB")
    maps=[]
    for ax in axes:
        p0=ax.transData.transform((0,0));p1=ax.transData.transform((1,1))
        maps.append(dict(x0=X+p0[0],sx=p1[0]-p0[0],y0=Y+H-p0[1],sy=-(p1[1]-p0[1]),
                         top=Y+H-ax.bbox.y1,bottom=Y+H-ax.bbox.y0))
    plt.close(fig)
    return img,maps

def main():
    report,signals,sep,diagnostics=load()
    ffmpeg=ffmpeg_executable();video=OUT/"hand_movement.mp4"
    if digest(video)!=report["clip_sha256"]:raise ValueError("Source video changed")
    frames=probe_video(ffmpeg,video);duration=report["clip_duration_s"]
    fps=Fraction(len(frames)/duration).limit_denominator(1000000)
    plot,maps=chart(signals,sep,duration)
    base=Image.new("RGB",(1920,1080),BG);base.paste(plot,(1070,105))
    font_path=font_manager.findfont("DejaVu Sans")
    fonts={size:ImageFont.truetype(font_path,size) for size in [17,19,20,22,24,38]}
    pen=ImageDraw.Draw(base)
    pen.text((36,23),"Checking the hand tracker against the video",font=fonts[38],fill=common.TEXT)
    pen.text((38,75),"Camera-relative signals + recorded hand geometry; no lag fitting or smoothing",font=fonts[20],fill=common.MUTED)
    pen.text((36,700),"Recorded hand skeleton",font=fonts[24],fill=common.TEXT)
    pen.text((36,735),"Schematic camera plane · not a calibrated pixel overlay",font=fonts[17],fill=common.MUTED)
    for y,line in [(770,"Purple: left hand     Cyan: right hand"),(809,"Right/down here follow image directions."),
                    (848,"Negative depth means the tracker placed"),(875,"a visible wrist behind the camera."),
                    (914,"Gaps: untracked, invalid, or behind camera."),(951,"Camera and hand records are paired"),
                    (978,"by their nearest original sensor timestamps.")]:
        pen.text((540,y),line,font=fonts[19],fill=common.MUTED)
    pen.text((36,1035),"Raw source measurements are retained. Camera-axis agreement and physical tracking accuracy are separate checks.",font=fonts[20],fill=common.MUTED)
    # Skeleton drawing viewport: normalized camera X/Z and Y/Z, fixed across all frames.
    box=(36,775,500,1008)
    def screen(uv):
        return (box[0]+(uv[0]+.9)/1.8*(box[2]-box[0]),box[1]+(uv[1]+.1)/1.1*(box[3]-box[1]))
    decoder=subprocess.Popen([ffmpeg,"-v","error","-i",str(video),"-vf","scale=1000:562",
        "-fps_mode","passthrough","-f","rawvideo","-pix_fmt","rgb24","pipe:1"],stdout=subprocess.PIPE)
    target=OUT/"hand_tracking_diagnostic.mp4"
    encoder=subprocess.Popen([ffmpeg,"-y","-v","error","-f","rawvideo","-pix_fmt","rgb24","-s","1920x1080",
        "-r",f"{fps.numerator}/{fps.denominator}","-i","pipe:0","-an","-c:v","libx264","-preset","fast",
        "-crf","18","-pix_fmt","yuv420p","-movflags","+faststart",str(target)],stdin=subprocess.PIPE)
    try:
        for i,(_,t) in enumerate(frames):
            img=base.copy();pen=ImageDraw.Draw(img)
            actual=Image.frombytes("RGB",(1000,562),common.read_exact(decoder.stdout,1000*562*3))
            img.paste(actual,(36,112))
            pen.rounded_rectangle((52,128,350,174),radius=7,fill=BG)
            pen.text((64,136),f"Clip time  {t:.2f} / {duration:.2f} s",font=fonts[22],fill=common.TEXT)
            for m in maps:
                x=m["x0"]+m["sx"]*t;pen.line((x,m["top"],x,m["bottom"]),fill="white",width=2)
            panel=Image.new("RGB",(box[2]-box[0],box[3]-box[1]),"#142237");pd=ImageDraw.Draw(panel)
            j=int(np.argmin(np.abs(signals["Left"]["time"]-t)))
            for side,s in signals.items():
                for a,b in LINKS:
                    uv=s["uv"][j,[a,b]]
                    if np.isfinite(uv).all():
                        pts=[(screen(v)[0]-box[0],screen(v)[1]-box[1]) for v in uv]
                        pd.line(pts,fill=COL[side],width=3)
                for uv in s["uv"][j]:
                    if np.isfinite(uv).all():
                        x,y=screen(uv);x-=box[0];y-=box[1]
                        pd.ellipse((x-2,y-2,x+2,y+2),fill=COL[side])
                values=[s["uv"][j,1,0],s["uv"][j,1,1],s["depth"][j]]
                for n,value in enumerate(values):
                    if np.isfinite(value):
                        m=maps[n];x=m["x0"]+m["sx"]*s["time"][j];y=m["y0"]+m["sy"]*value
                        pen.ellipse((x-4,y-4,x+4,y+4),fill=COL[side],outline=BG,width=1)
                if np.isfinite(s["depth"][j]) and s["depth"][j]<=0:
                    pen.rounded_rectangle((52,615,740,658),radius=7,fill="#4a222b")
                    pen.text((64,625),f"{side} wrist: tracked flag is ON, but depth is behind camera",font=fonts[19],fill="#ffc1c1")
            img.paste(panel,(box[0],box[1]))
            if np.isfinite(sep[j]):
                m=maps[3];x=m["x0"]+m["sx"]*signals["Left"]["time"][j];y=m["y0"]+m["sy"]*sep[j]
                pen.ellipse((x-4,y-4,x+4,y+4),fill="#ffbf6b")
            encoder.stdin.write(img.tobytes())
            if i in [0,49,98,181,195]:img.save(OUT/f"diagnostic_preview_{i:03d}.jpg",quality=92)
        if decoder.stdout.read(1):raise RuntimeError("Unexpected extra frames")
        encoder.stdin.close()
        if decoder.wait()!=0 or encoder.wait()!=0:raise RuntimeError("FFmpeg failed")
    finally:
        if decoder.poll() is None:decoder.kill()
        if encoder.poll() is None:encoder.kill()
    output_frames=probe_video(ffmpeg,target)
    assert len(output_frames)==len(frames)
    error=max(abs(a[1]-b[1]) for a,b in zip(output_frames,frames))
    assert error<.001
    result=dict(source_report=report["session"],diagnostics=diagnostics,frame_count=len(frames),
        reencoding_pts_max_error_s=error,output_sha256=digest(target),
        calibration="Normalized X/Z,Y/Z only. Intrinsics unavailable; no calibrated overlay claimed.",
        source_reference="https://github.com/taeinkwon/PyHoloAssist/blob/main/hand_eye_project.py",
        interpretation="Export fidelity does not establish physical tracking accuracy. No chosen lag or smoothing.")
    (OUT/"tracking_diagnostic.json").write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2));print(target.resolve())

if __name__=="__main__":main()
