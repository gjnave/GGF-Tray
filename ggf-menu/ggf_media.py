"""Local media operations for the tray. FFmpeg runs without a command shell."""
import configparser
import os
import re
import subprocess
import threading
import uuid
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageOps
from ggf_runtime import get_ffmpeg_executable, user_file


AUDIO = ("mp3", "wav", "aac", "m4a", "flac", "ogg")
VIDEO = ("mp4", "webm", "mkv", "mov", "avi", "gif")
IMAGES = ("jpg", "png", "webp", "bmp")
ACTIONS = {"convert_" + ext for ext in AUDIO + IMAGES} | {
    "convert_video", "shrink_video", "save_first_frame", "save_last_frame", "resize_image", "download"
}


def settings():
    config = configparser.ConfigParser(interpolation=None)
    config.read(user_file("config.txt"), encoding="utf-8-sig")
    return config


def _number(config, key, default, low, high):
    try:
        return max(low, min(high, config.getint("Video", key, fallback=default)))
    except ValueError:
        return default


def check_cancel(stop):
    if stop.is_set():
        raise InterruptedError("Cancelled")


def _movie_args(ext, config):
    bitrate = config.get("Video", "audio_bitrate", fallback="192k")
    first_video = ["-map", "0:V:0"]
    if ext in AUDIO:
        codec = {"mp3":"libmp3lame", "wav":"pcm_s16le", "ogg":"libvorbis",
                 "aac":"aac", "m4a":"aac", "flac":"flac"}[ext]
        args = ["-map", "0:a:0", "-vn", "-c:a", codec]
        return args + ([] if ext in ("wav","flac") else ["-b:a",bitrate])
    if ext == "gif":
        fps = _number(config, "gif_fps", 10, 1, 60)
        width = _number(config, "gif_scale", 480, 16, 4096)
        palette = (f"[0:V:0]fps={fps},scale='min(iw,{width})':-1:flags=lanczos,"
                   "split[a][b];[a]palettegen[p];[b][p]paletteuse[v]")
        return ["-filter_complex", palette, "-map", "[v]", "-an", "-loop", "0"]
    args = first_video + ["-map", "0:a:0?"]
    crf = str(_number(config, "video_crf", 23, 0, 51))
    preset = config.get("Video","video_preset",fallback="medium")
    if ext == "webm":
        args += ["-c:v","libvpx-vp9","-crf",crf,"-b:v","0","-c:a","libopus"]
    elif ext == "avi":
        args += ["-c:v","mpeg4","-q:v","4","-c:a","libmp3lame"]
    else:
        args += ["-c:v",config.get("Video","video_codec",fallback="libx264"),
                 "-crf",crf,"-preset",preset,"-c:a",config.get("Video","audio_codec",fallback="aac")]
    args += ["-b:a",bitrate,"-vf","pad=ceil(iw/2)*2:ceil(ih/2)*2","-pix_fmt","yuv420p"]
    if ext in ("mp4","mov"):
        args += ["-movflags","+faststart"]
    return args


def _encode(args, stop, progress):
    ffmpeg = get_ffmpeg_executable()
    if not ffmpeg:
        raise ValueError("The installed FFmpeg encoder could not be found.")
    cmd = [ffmpeg, "-nostdin","-hide_banner","-nostats","-progress","pipe:1", *map(str,args)]
    # Combining the pipes prevents stderr from filling while encoding long clips.
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace",
                               creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    def interrupt():
        while not finished.wait(.15):
            if stop.is_set():
                try: process.terminate()
                except OSError: pass
                return
    finished = threading.Event()
    watcher = threading.Thread(target=interrupt,daemon=True)
    watcher.start()
    duration = 0.0
    tail = deque(maxlen=12)
    try:
        with process.stdout:
            for line in process.stdout:
                if "Duration:" in line:
                    match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", line)
                    if match:
                        h,m,s = map(float,match.groups())
                        duration = 3600*h+60*m+s
                if line.startswith("out_time_us="):
                    value = line.strip().partition("=")[2]
                    if value.lstrip("-").isdigit():
                        sec = max(0,int(value)/1_000_000)
                        progress(round(min(99,sec*100/duration)) if duration else -1, f"Encoded {sec:.1f} s")
                elif "=" not in line[:22] and line.strip():
                    tail.append(line.strip())
        code = process.wait()
        check_cancel(stop)
        if code:
            detail = "\n".join(tail)[-1200:]
            if "matches no streams" in detail.lower() or "matches no stream" in detail.lower():
                raise ValueError("The file has no matching video or audio track for this operation.")
            raise ValueError(detail or f"FFmpeg stopped with code {code}.")
    finally:
        finished.set()
        if process.poll() is None:
            process.terminate()
            process.wait()
        watcher.join()


def _image(source, temp, ext, percent):
    with Image.open(source) as original:
        img = ImageOps.exif_transpose(original)
        if percent is not None:
            size = tuple(max(1,round(n*percent/100)) for n in img.size)
            if size[0]*size[1] > 120_000_000:
                raise ValueError("The requested image exceeds 120 megapixels.")
            img = img.resize(size, Image.Resampling.LANCZOS)
        if ext in ("jpg","bmp") and img.mode != "RGB":
            rgba = img.convert("RGBA")
            img = Image.new("RGB", rgba.size, "white")
            img.paste(rgba, mask=rgba.getchannel("A"))
        fmt = {"jpg":"JPEG","png":"PNG","bmp":"BMP","webp":"WEBP"}[ext]
        img.save(temp, format=fmt, **({"quality":95} if ext in ("jpg","webp") else {}))


def _publish(temp, dest):
    # Windows rename refuses an existing target, including in a concurrent conversion.
    for i in range(1,10001):
        candidate = dest if i==1 else dest.with_name(f"{dest.stem} ({i}){dest.suffix}")
        try:
            os.rename(temp,candidate)
            return candidate
        except FileExistsError:
            continue
    raise ValueError("Choose another output folder.")


def convert(source, folder, action, ext, percent, stop, progress, quality=None):
    source = Path(source).resolve(strict=True)
    folder = Path(folder or source.parent).resolve(strict=True)
    if not source.is_file() or not folder.is_dir():
        raise ValueError("Choose an existing input file and output folder.")
    check_cancel(stop)
    config = settings()
    if quality:
        crf, bitrate = {"Compact": (28,"128k"), "Balanced": (23,"192k"), "High": (18,"256k")}[quality]
        if not config.has_section("Video"):
            config.add_section("Video")
        config.set("Video","video_crf",str(crf))
        config.set("Video","audio_bitrate",bitrate)
    suffix = {"shrink_video":"_smaller","resize_image":"_resized","save_first_frame":"_first_frame",
              "save_last_frame":"_last_frame"}.get(action,"_converted")
    if action == "shrink_video":
        ext = "mp4"
    elif action in ("resize_image","save_first_frame","save_last_frame"):
        ext = "png"
    elif action.startswith("convert_") and action!="convert_video":
        ext = action.removeprefix("convert_")
    if action not in ACTIONS or ext not in VIDEO + AUDIO + IMAGES:
        raise ValueError("Unsupported output format.")
    dest = folder / (source.stem+suffix+"."+ext)
    temp = folder / (".ggf-"+uuid.uuid4().hex+".partial."+ext)
    try:
        _export(source, temp, action, ext, percent, config, stop, progress)
        check_cancel(stop)
        if not temp.is_file() or not temp.stat().st_size:
            raise ValueError("The file contained no frames to export.")
        return _publish(temp,dest)
    except Exception as exc:
        if temp.exists():
            saved = _publish(temp,folder / (dest.name+".unfinished"))
            message = f"{exc}\nUnfinished export retained at {saved}"
            if isinstance(exc,InterruptedError):
                raise InterruptedError(message) from exc
            raise ValueError(message) from exc
        raise


def _export(source, temp, action, ext, percent, config, stop, progress):
    if action in {"convert_"+fmt for fmt in IMAGES} or action == "resize_image":
        if not 1 <= percent <= 400:
            raise ValueError("Choose a resize percentage between 1 and 400.")
        _image(source, temp, ext, percent if action=="resize_image" else None)
    elif action in ("save_first_frame","save_last_frame"):
        frame = ["-map","0:V:0","-an","-fps_mode","passthrough","-update","1","-f","image2"]
        if action == "save_first_frame":
            _encode(["-i",source,*frame,"-frames:v","1",temp],stop,progress)
        else:
            # Write the last decoded frame. Inputs with long trailing audio can
            # have no video at all in the final two seconds; decode in full then.
            _encode(["-sseof","-2","-i",source,*frame,temp],stop,progress)
            if not temp.is_file() or not temp.stat().st_size:
                _encode(["-i",source,*frame,"-y",temp],stop,progress)
    else:
        args = _movie_args(ext,config)
        if action == "shrink_video":
            height = re.fullmatch(r"(\d+)p?",config.get("Video","shrink_resolution",fallback="1080p"))
            bound = max(2,min(4320,int(height[1]))) if height else 1080
            args = ["-map","0:V:0","-map","0:a:0?","-vf",
                    f"scale=-2:'max(2,trunc(min(ih,{bound})/2)*2)'","-pix_fmt","yuv420p",
                    "-c:v","libx264","-preset","medium","-crf","28","-maxrate",
                    config.get("Video","shrink_bitrate",fallback="2000k"),"-bufsize","4M",
                    "-c:a","aac","-b:a","128k","-movflags","+faststart"]
        _encode(["-i",source,*args,temp],stop,progress)


def download_video(url, directory, stop, progress):
    import yt_dlp
    if urlsplit(url).scheme not in ("http","https") or not urlsplit(url).hostname:
        raise ValueError("Enter a complete HTTP or HTTPS video URL.")
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    def update(info):
        check_cancel(stop)
        done = info.get("downloaded_bytes") or 0
        total = info.get("total_bytes") or info.get("total_bytes_estimate")
        progress(min(99,int(done*100/total)) if total else -1, f"Downloaded {done/1024**2:.1f} MiB")
    opts = {"noplaylist":True,"quiet":True,"noprogress":True,"no_warnings":True,"overwrites":False,
            "ffmpeg_location":get_ffmpeg_executable(),"windowsfilenames":True,
            "paths":{"home":str(folder)},"outtmpl":"%(title).100s [%(id)s].%(ext)s",
            "progress_hooks":[update],"post_hooks":[saved.append],"socket_timeout":15,"retries":2}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url,download=True)
        check_cancel(stop)
        if not info: raise ValueError("The video service returned no downloadable item.")
        result = Path(saved[-1] if saved else info.get("filepath") or ydl.prepare_filename(info))
    if not result.is_file(): raise ValueError("No completed video file was found in the output folder.")
    return result

