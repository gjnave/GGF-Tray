"""Browse public Hub repositories and download complete, revision-pinned weights."""
import hashlib
import json
import msvcrt
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ggf_packages import components, reparse
from ggf_runtime import urlopen_with_ssl

ORIGIN = "https://huggingface.co"
FORMATS = (".safetensors", ".gguf", ".bin", ".pt", ".pth", ".ckpt")
PARTS = re.compile(r"(.+?)-(\d{5})-of-(\d{5})(\.(?:safetensors|gguf|bin|pt|pth|ckpt))$", re.I)
CHUNK = 1024**2


@dataclass(frozen=True)
class File:
    path: str
    size: int
    digest: str
    lfs: bool


@dataclass(frozen=True)
class Model:
    repo: str
    revision: str
    label: str
    files: tuple
    missing: bool = False

    @property
    def size(self):
        return sum(f.size for f in self.files)


def stop_if_requested(stop):
    if stop.is_set(): raise InterruptedError("Cancelled")


def repository_id(query):
    query = query.strip()
    from_url = "://" in query
    if from_url:
        parsed = urllib.parse.urlsplit(query)
        if (parsed.scheme, parsed.netloc) != ("https","huggingface.co"):
            raise ValueError("Enter a Hugging Face model page or repository ID.")
        query = "/".join(parsed.path.strip("/").split("/")[:2])
        if re.fullmatch(r"[\w-]+",query,re.ASCII): return query
    if re.fullmatch(r"[\w.-]+/[\w.-]+",query,re.ASCII) and all(p not in (".","..") for p in query.split("/")):
        return query
    return None


def _page(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme,parsed.netloc)!=("https","huggingface.co") or not parsed.path.startswith("/api/models"):
        raise ValueError("Unexpected model API address.")
    req = urllib.request.Request(url,headers={"User-Agent":"GGF-Tray/0.14","Accept":"application/json"})
    try:
        with urlopen_with_ssl(req,timeout=18) as response:
            data = response.read(16*1024**2+1)
            if len(data)>16*1024**2: raise ValueError("This model listing exceeds the size limit.")
            links = response.headers.get("Link","")
    except urllib.error.HTTPError as exc:
        if exc.code in (401,403): raise ValueError("This repository requires Hugging Face access. Use its model page to review access.") from exc
        if exc.code == 429: raise ValueError("Hugging Face's request limit was reached. Try again later.") from exc
        raise
    link = re.search(r'<([^>]+)>;\s*rel="next"',links)
    return json.loads(data),link.group(1) if link else None


def search(query, cursor=None, weight_format=""):
    direct = repository_id(query)
    if direct and not cursor: return [direct],None
    params = {"search":query.strip(),"limit":20}
    if weight_format in (".safetensors",".gguf"):
        params["filter"] = weight_format[1:]
    url = cursor or ORIGIN+"/api/models?"+urllib.parse.urlencode(params)
    rows,more = _page(url)
    return [r["id"] for r in rows if isinstance(r,dict) and isinstance(r.get("id"),str)], more


def choices(repo, revision, rows):
    candidates = {}
    groups = {}
    for row in rows:
        if row.get("type") != "file": continue
        path = row.get("path","")
        if not path.lower().endswith(FORMATS+(".index.json",)): continue
        parts = components(path)
        if "/".join(parts)!=path: raise ValueError("Unexpected path in model repository.")
        lfs = row.get("lfs") or {}
        digest = lfs.get("oid") if lfs else row.get("oid")
        if not isinstance(digest,str) or not re.fullmatch(r"[a-f0-9]{64}" if lfs else r"[a-f0-9]{40}",digest):
            raise ValueError("Hugging Face omitted the file verification hash.")
        size = int(row["size"])
        if size<0: raise ValueError("Invalid model file size.")
        candidates[path] = File(path,size,digest,bool(lfs))
    results=[]
    for path,f in candidates.items():
        if path.endswith(".index.json"): continue
        match = PARTS.fullmatch(path)
        if match:
            prefix,num,total,ext=match.groups()
            groups.setdefault((prefix,int(total),ext),{})[int(num)] = f
        else:
            results.append(Model(repo,revision,path,(f,)))
    for (prefix,total,ext),parts in groups.items():
        ordered = [parts[i] for i in sorted(parts)]
        index = candidates.get(prefix+ext+".index.json")
        if index: ordered.append(index)
        complete = total>0 and len(parts)==total and min(parts)==1 and max(parts)==total
        results.append(Model(repo,revision,f"{prefix}{ext}  [{total} shards]",tuple(ordered),not complete))
    return sorted(results,key=lambda item:item.label.casefold())


def list_files(repo,stop):
    quoted = urllib.parse.quote(repo,safe="/")
    info,_ = _page(ORIGIN+"/api/models/"+quoted)
    revision=info.get("sha","")
    if not re.fullmatch("[a-f0-9]{40}",revision): raise ValueError("The repository revision could not be verified.")
    url=ORIGIN+f"/api/models/{quoted}/tree/{revision}?recursive=true&limit=1000"
    rows=[];seen=set()
    while url:
        stop_if_requested(stop)
        if url in seen or len(seen)>=200: raise ValueError("The repository listing is too large or repeated a page.")
        seen.add(url)
        page,url=_page(url)
        if not isinstance(page,list): raise ValueError("Unexpected model listing.")
        rows.extend(page)
    return choices(repo,revision,rows)


def _hasher(file):
    if file.lfs: return hashlib.sha256()
    return hashlib.sha1(f"blob {file.size}\0".encode())


def _verify(path,file,stop):
    if not path.is_file() or path.stat().st_size!=file.size: return False
    h=_hasher(file)
    with path.open("rb") as src:
        while True:
            stop_if_requested(stop)
            block=src.read(4*CHUNK)
            if not block: break
            h.update(block)
    return h.hexdigest()==file.digest


@contextmanager
def _download_lock(folder, key):
    # The persistent lock file is harmless. Windows releases the byte lock on exit.
    path=folder/(".ggf-lock-"+key)
    if reparse(path): raise ValueError("Choose a destination without linked transfer files.")
    with path.open("a+b") as lock:
        lock.seek(0)
        try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc: raise ValueError("Another transfer is using this model destination.") from exc
        try: yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


def _paths(folder,file):
    name=components(file.path)[-1]
    # Compatible-model selection is flat within the chosen folder (including index files).
    key=hashlib.sha256((name.casefold()+file.digest).encode()).hexdigest()[:20]
    final=folder/name
    partial=folder/(".ggf-"+key+".part")
    if reparse(final) or reparse(partial): raise ValueError("The selected output contains a linked file.")
    return final,partial


def _transfer(model,file,folder,stop,notify):
    final,partial=_paths(folder,file)
    if final.exists():
        notify(0,"Checking existing "+final.name)
        if _verify(final,file,stop): return final
        raise FileExistsError(f"{final.name} already exists with different contents. Choose a different folder.")
    offset=partial.stat().st_size if partial.exists() else 0
    if offset>file.size: raise ValueError("The retained partial exceeds the expected size.")
    if offset<file.size or not partial.exists():
        if shutil.disk_usage(folder).free < file.size-offset+8*CHUNK: raise ValueError("Insufficient free space for this model.")
        url=ORIGIN+"/"+urllib.parse.quote(model.repo,safe="/")+"/resolve/"+model.revision+"/"+urllib.parse.quote(file.path,safe="/")+"?download=true"
        headers={"User-Agent":"GGF-Tray/0.14","Accept-Encoding":"identity"}
        if offset: headers["Range"]=f"bytes={offset}-"
        req=urllib.request.Request(url,headers=headers)
        with urlopen_with_ssl(req,timeout=30) as response:
            if urllib.parse.urlsplit(response.geturl()).scheme!="https": raise ValueError("Insecure model download redirect.")
            if response.status==206:
                bounds=response.headers.get("Content-Range","")
                if bounds!=f"bytes {offset}-{file.size-1}/{file.size}": raise ValueError("Hugging Face returned an unexpected byte range.")
            elif response.status==200 and offset:
                # Some storage servers ignore Range. Verify the prefix before appending.
                with partial.open("rb") as retained:
                    while retained.tell()<offset:
                        stop_if_requested(stop)
                        block=retained.read(CHUNK)
                        if response.read(len(block))!=block: raise ValueError("The retained partial differs from the server file.")
            elif response.status!=200:
                raise ValueError("Unexpected response to model download.")
            with partial.open("ab") as dst:
                written=offset; last=0
                while True:
                    stop_if_requested(stop)
                    block=response.read(CHUNK)
                    if not block: break
                    if written+len(block)>file.size: raise ValueError("The server exceeded the expected file size.")
                    dst.write(block);written+=len(block)
                    if time.monotonic()-last>=.12:
                        notify(written,"Downloading "+final.name);last=time.monotonic()
    notify(file.size,"Verifying "+final.name)
    if partial.stat().st_size!=file.size: raise IOError("Download interrupted. Retry in the same folder to resume.")
    if not _verify(partial,file,stop):
        import uuid
        preserved=partial.with_name(partial.name+"."+uuid.uuid4().hex[:8]+".invalid")
        partial.rename(preserved)
        raise ValueError("File verification failed. The incomplete copy was set aside. Retry the download.")
    stop_if_requested(stop)
    partial.rename(final)
    return final


def download(model,folder,stop,progress):
    if model.missing: raise ValueError("This repository is missing part of the selected shard set.")
    folder=Path(folder).resolve(strict=True)
    if not folder.is_dir(): raise ValueError("Choose an existing output folder.")
    key=hashlib.sha256(str(folder).casefold().encode()).hexdigest()[:16]
    with _download_lock(folder,key):
        need=0
        for file in model.files:
            final,part=_paths(folder,file)
            if not final.exists(): need+=max(0,file.size-(part.stat().st_size if part.exists() else 0))
        if shutil.disk_usage(folder).free<need+8*CHUNK: raise ValueError("There is not enough free space for the complete selection.")
        done=0;results=[]
        for file in model.files:
            stop_if_requested(stop)
            def notify(n,status):
                progress(int((done+n)*100/max(1,model.size)),status)
            results.append(_transfer(model,file,folder,stop,notify))
            done+=file.size
        return results

