"""GGF catalog and transfer protocol. Only the fixed member API receives credentials."""
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from ggf_packages import components, LIMIT
from ggf_runtime import urlopen_with_ssl

ORIGIN = "https://getgoingfast.pro"
EXT = {".zip",".7z",".rar",".exe",".bat",".json",".pptx",".kcppt",".safetensors"}
CODES = {"free":0,"pd":1,"fh":2}
TIERS = {"free":0,"prairie-dog":1,"farm-hand":2,"rancher":2,"gunslinger":2}
def membership_allows_download(tier, code):
    return tier in TIERS and code in CODES and TIERS[tier]>=CODES[code]

def catalog(state):
    path=Path(state)/"tools-list-cache.json"
    def decode(raw):
        rows=json.loads(raw)["tools"]
        if not isinstance(rows,list) or not all(isinstance(x,dict) and isinstance(x.get("name"),str) for x in rows):
            raise ValueError("Unexpected catalog format.")
        return rows
    try:
        request=urllib.request.Request(ORIGIN+"/tools/tools-list.json",headers={"User-Agent":"GGF-Tray/0.13 (Windows; Member Catalog)","Accept":"application/json"})
        with urlopen_with_ssl(request,timeout=12) as response: raw=response.read(4*1024**2+1)
        if len(raw)>4*1024**2: raise ValueError("Catalog too large.")
        rows=decode(raw)
    except Exception:
        if path.is_file(): return decode(path.read_bytes()),True
        raise
    try:
        with tempfile.NamedTemporaryFile(dir=state,delete=False) as f: f.write(raw);tmp=f.name
        os.replace(tmp,path)
    except OSError: pass
    return rows,False

class Variants(Exception):
    def __init__(self,names): self.names=names

def fetch(slug, token, dest, progress, cancelled=lambda:False, variant=None):
    if not re.fullmatch(r"[a-z0-9_-]{1,128}",slug or "") or not re.fullmatch(r"ggf_desktop_[A-Za-z0-9_-]{43}",token or ""):
        raise ValueError("Sign in to GGF before downloading.")
    args={"slug":slug}
    if variant: args["file"]=variant
    req=urllib.request.Request(ORIGIN+"/download-api.php?"+urllib.parse.urlencode(args),headers={
        "X-GGF-App-Token":token,"Cache-Control":"no-store","User-Agent":"GGF-Tray/0.13"})
    try: reply=urlopen_with_ssl(req,timeout=35)
    except urllib.error.HTTPError as exc:
        with exc:
            try: body=json.loads(exc.read(12000))
            except (ValueError,UnicodeError): body={}
            if not isinstance(body,dict): body={}
            if exc.code==409 and isinstance(body.get("files"),list):
                names=[s for s in body["files"] if isinstance(s,str) and len(components(s))==1 and Path(s).suffix.lower() in EXT]
                if names: raise Variants(names)
            fallback={401:"Sign in to GGF again.",403:"Your account does not have access to this package.",
                      429:"Download limit reached. Try again later."}
            raise ValueError(str(body.get("message") or body.get("error") or fallback.get(exc.code,"Download unavailable."))[:450]) from None
    partial=None
    with reply:
        if reply.status!=200 or reply.headers.get_content_disposition()!="attachment": raise ValueError("The server did not return a package.")
        filename=reply.headers.get_filename() or ""
        if len(components(filename))!=1 or filename!=components(filename)[0] or Path(filename).suffix.lower() not in EXT: raise ValueError("Invalid package filename.")
        dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
        size=int(reply.headers["Content-Length"]) if reply.headers.get("Content-Length") else None
        if size is not None and (size<=0 or size>LIMIT or size>shutil.disk_usage(dest).free): raise ValueError("Package is empty, too large, or the download drive is full.")
        try:
            n=0; last=0
            with tempfile.NamedTemporaryFile(dir=dest,prefix=".ggf-",suffix=".part",delete=False) as f:
                partial=Path(f.name)
                while True:
                    if cancelled(): raise InterruptedError("Download cancelled.")
                    chunk=reply.read(256*1024)
                    if not chunk: break
                    n+=len(chunk)
                    if n>LIMIT or (size is not None and n>size): raise ValueError("Download exceeded its declared size.")
                    f.write(chunk)
                    if time.monotonic()-last>=0.15: progress(n,size);last=time.monotonic()
            if not n or (size is not None and n!=size): raise ValueError("Incomplete download. Please retry.")
            if Path(filename).suffix.lower()==".zip" and not zipfile.is_zipfile(partial): raise ValueError("Invalid ZIP package.")
            with partial.open("rb") as f: head=f.read(256).lstrip().lower()
            if head.startswith((b"<!doctype html",b"<html")): raise ValueError("The server returned a web page.")
            result=dest/filename; i=1
            while True:
                try:
                    os.rename(partial,result)  # Windows: atomic, never replaces an existing file.
                    partial=None;return result
                except FileExistsError:
                    i+=1; result=dest/(Path(filename).stem+f"-{i}"+Path(filename).suffix)
        finally:
            if partial: partial.unlink(missing_ok=True)

