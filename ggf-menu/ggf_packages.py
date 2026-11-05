"""Inspect the entire package before writing anything; Windows paths are case insensitive."""
import ctypes as C
import os
import re
import shutil
import stat
import zipfile
from pathlib import Path, PureWindowsPath

LIMIT = 40 * 1024**3
COUNT = 20000
BLOCK = 1024**2

class PackageError(RuntimeError):
    pass

def components(name):
    raw = name.replace("\\", "/").removesuffix("/")
    parts = raw.split("/")
    while parts and parts[0] == ".":
        parts.pop(0)
    if not parts or any(not s or s in {".",".."} or s.endswith((".", " ")) or
                        re.search(r'[<>:"|?*\x00-\x1f]', s) or PureWindowsPath(s).is_reserved()
                        or s.casefold() == ".ggf-install.json" for s in parts):
        raise PackageError(f"Unsafe Windows archive path: {name!r}")
    return parts

def reparse(path):
    try:
        return bool(os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except FileNotFoundError:
        return False

def safe_target(base, name):
    p = Path(base).absolute()
    parts = components(name)
    for node in (*reversed(p.parents), p):
        if reparse(node):
            raise PackageError(f"Cannot extract through a Windows link: {node}")
    for s in parts:
        p = p / s
        if reparse(p):
            raise PackageError(f"Cannot extract through a Windows link: {p}")
    return p

def zip_entries(archive, writing=False):
    with zipfile.ZipFile(archive) as z:
        if len(z.infolist()) > COUNT:
            raise PackageError("Too many archive entries.")
        for info in z.infolist():
            mode = (info.external_attr >> 16) & 0o170000
            if mode not in (0, stat.S_IFDIR, stat.S_IFREG) or info.external_attr & 0x400 or info.flag_bits & 1:
                raise PackageError("Links, special files and encrypted ZIPs cannot be installed.")
            is_dir = info.is_dir() or info.filename.endswith("\\")
            if info.filename in ("./", ".") and is_dir: continue
            with z.open(info) if writing and not is_dir else _empty() as stream:
                yield info.orig_filename, is_dir, info.file_size, stream

from contextlib import nullcontext as _empty

def native_entries(archive, writing=False):
    # Read libarchive streams; never let an external extractor write a path.
    from ctypes import c_void_p as ptr, c_int, c_longlong, c_wchar_p, c_size_t, c_ssize_t
    try:
        lib = C.CDLL(os.path.join(os.environ["SystemRoot"], "System32", "archiveint.dll"))
        def fn(name, result, *args):
            f = getattr(lib, name); f.restype = result; f.argtypes = args; return f
        new = fn("archive_read_new", ptr)
        free = fn("archive_read_free", c_int, ptr)
        supports = [fn("archive_read_support_format_" + typ, c_int, ptr) for typ in ("rar","rar5","7zip")]
        op = fn("archive_read_open_filename_w", c_int, ptr, c_wchar_p, c_size_t)
        next_header = fn("archive_read_next_header", c_int, ptr, C.POINTER(ptr))
        pathname = fn("archive_entry_pathname_w", c_wchar_p, ptr)
        islink = fn("archive_entry_hardlink_w", c_wchar_p, ptr)
        typ = fn("archive_entry_filetype", C.c_uint, ptr)
        size = fn("archive_entry_size", c_longlong, ptr)
        read = fn("archive_read_data", c_ssize_t, ptr, ptr, c_size_t)
    except (OSError, AttributeError) as exc:
        raise PackageError("This Windows version cannot inspect RAR/7z files. Use a ZIP package.") from exc
    a = new()
    if not a: raise PackageError("Could not create archive reader.")
    try:
        for f in supports: f(a)
        if op(a, str(archive), BLOCK): raise PackageError("Cannot open RAR/7z package.")
        class Stream:
            def read(self, n):
                buf = C.create_string_buffer(n)
                count = read(a, buf, n)
                if count < 0: raise PackageError("Damaged or encrypted archive.")
                return buf.raw[:count]
        stream = Stream()
        while True:
            e = ptr()
            rc = next_header(a, C.byref(e))
            if rc == 1: return
            if rc or not e: raise PackageError("Invalid archive header.")
            k = typ(e); name = pathname(e)
            if k not in (stat.S_IFDIR,stat.S_IFREG) or islink(e) or not name:
                raise PackageError("Archive contains a link, special file or unreadable name.")
            if name in ("./",".") and k == stat.S_IFDIR: continue
            yield name, k == stat.S_IFDIR, size(e), stream
    finally:
        free(a)

def extract(archive, base, max_bytes=LIMIT, max_count=COUNT):
    ext = Path(archive).suffix.lower()
    entries = zip_entries if ext == ".zip" else native_entries
    if ext not in {".zip",".7z",".rar"}: raise PackageError("Unsupported archive format.")
    files, dirs, explicit, plan, total = set(), set(), set(), [], 0
    for name, directory, size, _ in entries(archive):
        if len(plan) >= max_count or size < 0 or total + size > max_bytes or (directory and size):
            raise PackageError("Archive size or entry count exceeds the installation limits.")
        target = safe_target(base, name)
        key = tuple(s.casefold() for s in components(name))
        prefixes = [key[:n] for n in range(1,len(key))]
        if key in explicit or any(p in files for p in prefixes) or (not directory and key in dirs):
            raise PackageError("Conflicting Windows paths in archive: " + name)
        explicit.add(key); dirs.update(prefixes); (dirs if directory else files).add(key)
        if target.exists() and (not directory or not target.is_dir()):
            raise PackageError("Refusing to overwrite " + str(target))
        total += size
        plan.append((name,directory,size))
    if not files: raise PackageError("The archive contains no files.")
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(base).free < total + 32*1024**2:
        raise PackageError("There is not enough space on the selected drive.")
    count = 0
    for name, directory, size, stream in entries(archive, True):
        if count >= len(plan) or plan[count] != (name,directory,size):
            raise PackageError("The archive changed during extraction.")
        count += 1
        target = safe_target(base, name)
        if directory: target.mkdir(parents=True, exist_ok=True); continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as dest:
            remaining = size
            while remaining:
                block = stream.read(min(remaining,BLOCK))
                if not block: raise PackageError("Incomplete archive entry: " + name)
                dest.write(block); remaining -= len(block)
            if stream.read(1): raise PackageError("Archive entry exceeds its declared size.")
    if count != len(plan): raise PackageError("Incomplete archive.")
    return count, total

