import os, re, shutil, tempfile, asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
import yt_dlp

BASE = Path(__file__).resolve().parent
app = FastAPI(title="PulseMP3 API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

YT_RE = re.compile(r"^(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.I)

class Request(BaseModel):
    url: str
    quality: str = "192"
    @field_validator("url")
    @classmethod
    def valid_url(cls, v):
        v=v.strip()
        if not YT_RE.match(v): raise ValueError("Please enter a valid YouTube URL.")
        return v
    @field_validator("quality")
    @classmethod
    def valid_quality(cls, v):
        if v not in {"128","192","256","320"}: raise ValueError("Invalid quality.")
        return v

def extract_info(url):
    opts={"quiet":True,"no_warnings":True,"noplaylist":True,"skip_download":True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

@app.post("/api/info")
async def info(req: Request):
    try:
        data=await asyncio.to_thread(extract_info, req.url)
        return {"title":data.get("title"),"thumbnail":data.get("thumbnail"),"duration":data.get("duration_string"),"uploader":data.get("uploader")}
    except Exception as e:
        raise HTTPException(400, f"Could not read this video: {str(e)[:350]}")

@app.post("/api/convert")
async def convert(req: Request):
    job=Path(tempfile.mkdtemp(prefix="pulsemp3_"))
    try:
        out=str(job/"%(title).80s.%(ext)s")
        opts={
            "ffmpeg_location": r"C:\Rockkey\ffmpeg-master-latest-win64-gpl\bin",
            "format":"bestaudio/best",
            "outtmpl":out,
            "noplaylist":True,
            "quiet":True,
            "no_warnings":True,
            "restrictfilenames":True,
            "postprocessors":[{
                "key":"FFmpegExtractAudio",
                "preferredcodec":"mp3",
                "preferredquality":req.quality
            }],
        }
        await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(opts).download([req.url]))
        files=list(job.glob("*.mp3"))
        if not files: raise RuntimeError("MP3 file was not produced.")
        return FileResponse(files[0],media_type="audio/mpeg",filename=files[0].name,background=None)
    except Exception as e:
        shutil.rmtree(job,ignore_errors=True)
        raise HTTPException(400,f"Conversion failed: {str(e)[:500]}")
    finally:
        # FileResponse keeps the file open while sending. Cleanup is handled by a
        # small delayed task after the response is returned.
        if 'files' in locals() and files:
            async def cleanup():
                await asyncio.sleep(20)
                shutil.rmtree(job,ignore_errors=True)
            asyncio.create_task(cleanup())

app.mount("/", StaticFiles(directory=BASE, html=True), name="site")
