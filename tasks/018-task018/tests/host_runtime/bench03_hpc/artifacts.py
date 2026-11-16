"""Bounded, no-follow artifact export used only by this bench's HPC bridge.

Extracted from the provided runner; origin hashes are in SOURCES.json.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import tarfile
import tempfile
import time

class P04ArtifactExportError(RuntimeError):
    def __init__(self, message: str, *, exit_code: int | None = None,
                 stdout_bytes: int = 0, stdout_sha256: str | None = None,
                 stderr_bytes: int = 0, stderr_text: str = "",
                 stderr_sha256: str | None = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.stdout_bytes = stdout_bytes
        self.stdout_sha256 = stdout_sha256
        self.stderr_bytes = stderr_bytes
        self.stderr_text = stderr_text[:4096]
        self.stderr_sha256 = stderr_sha256

_P04_EXPORT_SCRIPT = r'''import os,sys,stat,tarfile,io,json,hashlib,tempfile
roots=json.loads(sys.argv[1]); rows=[]; seen=set(); total=0
max_entries=int(sys.argv[2]); max_file=int(sys.argv[3]); max_total=int(sys.argv[4])
NO=getattr(os,'O_NOFOLLOW',0); NB=getattr(os,'O_NONBLOCK',0); OD=getattr(os,'O_DIRECTORY',0)
def same(a,b): return (a.st_ino,a.st_dev,a.st_mode,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_ino,b.st_dev,b.st_mode,b.st_size,b.st_mtime_ns,b.st_ctime_ns)
def add(parent,name,arc,tf):
 global total
 st=os.stat(name,dir_fd=parent,follow_symlinks=False)
 if stat.S_ISLNK(st.st_mode) or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)): raise RuntimeError('unsafe source type')
 if arc in seen: raise RuntimeError('duplicate source path')
 seen.add(arc)
 if len(seen)>max_entries: raise RuntimeError('entry limit')
 flags=os.O_RDONLY|NO|NB|(OD if stat.S_ISDIR(st.st_mode) else 0)
 fd=os.open(name,flags,dir_fd=parent)
 try:
  before=os.fstat(fd)
  if not same(st,before): raise RuntimeError('source changed while opening')
  if stat.S_ISDIR(before.st_mode):
   rows.append({'path':arc,'type':'directory','bytes':0,'sha256':None})
   ti=tarfile.TarInfo(arc.rstrip('/')+'/'); ti.type=tarfile.DIRTYPE; ti.mode=0o755; ti.mtime=0; tf.addfile(ti)
   names=[]
   with os.scandir(fd) as scan:
    for entry in scan:
     names.append(entry.name)
     if len(names)+len(seen)>max_entries: raise RuntimeError('entry limit')
   names.sort()
   for child in names:
    if child in ('','.','..') or '/' in child: raise RuntimeError('unsafe name')
    add(fd,child,arc.rstrip('/')+'/'+child,tf)
   if names!=sorted(os.listdir(fd)) or not same(before,os.fstat(fd)): raise RuntimeError('directory changed')
  else:
   if before.st_nlink!=1 or before.st_size>max_file: raise RuntimeError('unsafe/oversize file')
   spool=tempfile.SpooledTemporaryFile(max_size=1024*1024); h=hashlib.sha256(); n=0
   try:
    while True:
     b=os.read(fd,min(65536,max_file+1-n))
     if not b: break
     n+=len(b); total+=len(b)
     if n>max_file or total>max_total: raise RuntimeError('byte limit')
     h.update(b); spool.write(b)
    after=os.fstat(fd)
    if n!=before.st_size or not same(before,after): raise RuntimeError('file changed')
    rows.append({'path':arc,'type':'file','bytes':n,'sha256':h.hexdigest()})
    ti=tarfile.TarInfo(arc); ti.size=n; ti.mode=0o644; ti.mtime=0; spool.seek(0); tf.addfile(ti,spool)
   finally: spool.close()
 finally: os.close(fd)
def rootfd(raw,base):
 parts=raw.split('/'); current=os.dup(base)
 try:
  for part in parts[:-1]:
   try: nxt=os.open(part,os.O_RDONLY|OD|NO|NB,dir_fd=current)
   except FileNotFoundError: os.close(current); return None,None
   os.close(current); current=nxt
  return current,parts[-1]
 except BaseException: os.close(current); raise
base=os.open('/app',os.O_RDONLY|OD|NO|NB)
try:
 with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as tf:
  for raw in roots:
   if not isinstance(raw,str) or raw.startswith('/') or not raw or any(p in ('','.','..') for p in raw.split('/')): raise RuntimeError('invalid root')
   parent,name=rootfd(raw,base)
   if parent is None:
    rows.append({'path':raw,'type':'missing','bytes':0,'sha256':None}); continue
   try:
    try: os.stat(name,dir_fd=parent,follow_symlinks=False)
    except FileNotFoundError:
     rows.append({'path':raw,'type':'missing','bytes':0,'sha256':None}); continue
    add(parent,name,raw,tf)
   finally: os.close(parent)
  payload=json.dumps(rows,sort_keys=True,separators=(',',':')).encode()
  ti=tarfile.TarInfo('__ccb_manifest__.json'); ti.size=len(payload); ti.mode=0o600; ti.mtime=0
  tf.addfile(ti,io.BytesIO(payload))
finally: os.close(base)
'''

def _materialize_export(stream_path: Path, dest: Path, roots: list[str], *,
                             max_entries: int, max_file_bytes: int,
                             max_total_bytes: int) -> list[dict]:
    """Validate a bounded P04 export tar and materialize it without extractall."""
    dest = Path(dest)
    if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
        raise RuntimeError("P04 export destination is unsafe")
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve(strict=True)
    rows: list[dict] = []; members: set[str] = set(); total = 0; manifest_bytes = None
    with tarfile.open(stream_path, mode="r:") as tf:
        for member in tf:
            name = member.name.rstrip("/")
            parts = name.split("/")
            if (not name or name.startswith("/") or any(p in {"", ".", ".."} for p in parts)
                    or name in members):
                raise RuntimeError("P04 export contains an unsafe or duplicate path")
            members.add(name)
            if name == "__ccb_manifest__.json":
                if not member.isfile() or member.size > 4 * 1024 * 1024:
                    raise RuntimeError("P04 export manifest is unsafe")
                src=tf.extractfile(member)
                if src is None: raise RuntimeError("P04 export manifest is truncated")
                manifest_bytes=src.read(4 * 1024 * 1024 + 1)
                if len(manifest_bytes)!=member.size: raise RuntimeError("P04 export manifest is truncated")
                continue
            if name != "__ccb_manifest__.json" and len(members) - int("__ccb_manifest__.json" in members) > max_entries:
                raise RuntimeError("P04 export entry limit exceeded")
            if member.isdir():
                row = {"path": name, "type": "directory", "bytes": 0, "sha256": None}
                out = root.joinpath(*parts)
                out.mkdir(parents=True, exist_ok=True)
            elif member.isfile() and member.isreg():
                if member.size < 0 or member.size > max_file_bytes:
                    raise RuntimeError("P04 export file size exceeds limit")
                total += member.size
                if total > max_total_bytes:
                    raise RuntimeError("P04 export total size exceeds limit")
                source = tf.extractfile(member)
                if source is None: raise RuntimeError("P04 export file payload is missing")
                h=hashlib.sha256(); count=0
                out = root.joinpath(*parts)
                out.parent.mkdir(parents=True, exist_ok=True)
                if out.exists() or out.is_symlink(): raise RuntimeError("P04 export destination path already exists")
                fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
                try:
                    with os.fdopen(fd,"wb") as target:
                        while True:
                            block=source.read(min(65536, member.size-count+1))
                            if not block: break
                            count+=len(block)
                            if count>member.size: raise RuntimeError("P04 export file exceeds declared size")
                            h.update(block); target.write(block)
                        target.flush(); os.fsync(target.fileno())
                except BaseException:
                    out.unlink(missing_ok=True); raise
                if count != member.size: raise RuntimeError("P04 export stream is truncated")
                row={"path":name,"type":"file","bytes":count,"sha256":h.hexdigest()}
            else:
                raise RuntimeError("P04 export contains a link or special member")
            rows.append(row)
    if manifest_bytes is None: raise RuntimeError("P04 export manifest is absent")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if not isinstance(manifest, list) or any(not isinstance(r,dict) or set(r)!={"path","type","bytes","sha256"}
            or not isinstance(r.get("path"),str) or not r["path"]
            or r.get("type") not in {"missing","directory","file"}
            or type(r.get("bytes")) is not int or r["bytes"]<0
            or (r.get("type") in {"missing","directory"} and (r["bytes"]!=0 or r.get("sha256") is not None))
            or (r.get("type")=="file" and (not isinstance(r.get("sha256"),str)
                or re.fullmatch(r"[0-9a-f]{64}",r["sha256"]) is None)) for r in manifest):
        raise RuntimeError("P04 export manifest rows are malformed")
    paths=[r["path"] for r in manifest]
    if (len(paths)!=len(set(paths))
            or {r["path"] for r in manifest if r["type"] != "missing"} != members-{"__ccb_manifest__.json"}
            or not set(roots).issubset(set(paths))
            or any(not any(r["path"] == declared or r["path"].startswith(declared.rstrip("/")+"/")
                           for declared in roots) for r in manifest)
            or any(r["type"]=="missing" and r["path"] not in roots for r in manifest)):
        raise RuntimeError("P04 export manifest is malformed")
    observed = {r["path"]: r for r in rows}
    for entry in manifest:
        if entry["type"] == "missing":
            if any(name.startswith(entry["path"].rstrip("/") + "/")
                   for name in observed):
                raise RuntimeError("missing artifact root has descendant archive members")
            continue
        prefix = entry["path"].rstrip("/")
        subrows = [row for name, row in observed.items() if name == prefix or name.startswith(prefix + "/")]
        if not subrows or observed.get(prefix, {}).get("type") != entry["type"]:
            raise RuntimeError("P04 export observation differs from its manifest")
        if entry["type"] == "file" and observed[prefix] != entry:
            raise RuntimeError("P04 exported bytes differ from the producer manifest")
        if entry["type"] == "directory" and observed.get(prefix) != entry:
            raise RuntimeError("P04 directory export manifest is inconsistent")
    for name in observed:
        parents=name.split("/")[:-1]
        for end in range(1,len(parents)+1):
            parent="/".join(parents[:end])
            if parent in observed and observed[parent]["type"]!="directory":
                raise RuntimeError("P04 export file is used as a directory")
        if name not in roots and not any(name.startswith(root_name.rstrip("/")+"/") for root_name in roots):
            raise RuntimeError("P04 export contains an undeclared artifact")
    return manifest

def _safe_materialize_export(stream_path: Path, dest: Path, roots: list[str], *,
                             max_entries: int, max_file_bytes: int,
                             max_total_bytes: int) -> list[dict]:
    dest = Path(dest)
    if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
        raise RuntimeError("P04 export destination is unsafe")
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.iterdir()):
        raise RuntimeError("P04 export destination must be empty before materialization")
    with tempfile.TemporaryDirectory(prefix=".p04-export-", dir=dest.parent) as temp:
        staging = Path(temp) / "tree"
        staging.mkdir(mode=0o700)
        manifest = _materialize_export(stream_path, staging, roots,
            max_entries=max_entries, max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes)
        for child in staging.iterdir():
            os.replace(child, dest / child.name)
        return manifest

def export_declared_artifacts(cid: str, artifacts, dest: Path, *,
                              max_entries: int = 20000, max_file_bytes: int = 256*1024*1024,
                              max_total_bytes: int = 1024*1024*1024, timeout: float = 30) -> list[dict]:
    """Stream only declared /app artifact roots through a bounded host tempfile."""
    roots=[]
    for item in artifacts:
        raw = item[0] if isinstance(item,(tuple,list)) else item
        value=str(raw)
        if value.startswith("/app/"): value=value[5:]
        if not value or value.startswith("/") or any(p in {"", ".", ".."} for p in value.split("/")):
            raise ValueError("declared artifact source is not a canonical /app-relative path")
        roots.append(value)
    if len(set(roots)) != len(roots): raise ValueError("duplicate declared artifact root")
    if any(a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")
           for i, a in enumerate(roots) for b in roots[i+1:]):
        raise ValueError("overlapping declared artifact roots")
    cmd=["docker","exec",cid,"python3","-I","-B","-c",_P04_EXPORT_SCRIPT,
         json.dumps(roots,separators=(",",":")),str(max_entries),str(max_file_bytes),str(max_total_bytes)]
    # The command streams tar bytes to a host tempfile; no unbounded capture_output.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error_output:
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=error_output)
        start=time.monotonic(); written=0; err=[]; stdout_hash=hashlib.sha256()
        try:
            assert proc.stdout is not None
            os.set_blocking(proc.stdout.fileno(), False)
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                eof=False
                while not eof:
                    remaining=timeout-(time.monotonic()-start)
                    if remaining<=0:
                        proc.kill(); proc.wait(); error_output.seek(0); err=error_output.read(65536)
                        raise P04ArtifactExportError("P04 artifact export timed out",
                            exit_code=proc.returncode,stdout_bytes=written,
                            stdout_sha256=stdout_hash.hexdigest(),stderr_bytes=len(err),
                            stderr_text=err.decode('utf-8','replace'),stderr_sha256=hashlib.sha256(err).hexdigest())
                    ready=selector.select(min(0.1,remaining))
                    if not ready:
                        if proc.poll() is None:
                            continue
                    block=proc.stdout.read(65536)
                    if not block:
                        eof=True; continue
                    written+=len(block)
                    if written>max_total_bytes+max_entries*1024+4*1024*1024:
                        proc.kill(); raise P04ArtifactExportError("P04 artifact export stream exceeds bound",
                            stdout_bytes=written,stdout_sha256=stdout_hash.hexdigest())
                    stdout_hash.update(block)
                    output.write(block)
            error_output.seek(0); err=error_output.read(65536)
            code=proc.wait(timeout=max(0.1,timeout-(time.monotonic()-start)))
            if code: raise P04ArtifactExportError(f"P04 artifact export failed ({code})",
                exit_code=code,stdout_bytes=written,stdout_sha256=stdout_hash.hexdigest(),
                stderr_bytes=len(err),stderr_text=err.decode('utf-8','replace'),
                stderr_sha256=hashlib.sha256(err).hexdigest())
        finally:
            if proc.poll() is None: proc.kill(); proc.wait()
        output.flush(); output.seek(0)
        with tempfile.NamedTemporaryFile() as archive:
            shutil.copyfileobj(output,archive,length=65536); archive.flush(); archive.seek(0)
            temp_path=Path(archive.name)
            try:
                return _safe_materialize_export(temp_path,Path(dest),roots,
                    max_entries=max_entries,max_file_bytes=max_file_bytes,max_total_bytes=max_total_bytes)
            except Exception as exc:
                raise P04ArtifactExportError(f"P04 artifact stream validation failed: {exc}",
                    exit_code=proc.returncode,stdout_bytes=written,stdout_sha256=stdout_hash.hexdigest(),
                    stderr_bytes=len(err),stderr_text=err.decode('utf-8','replace'),
                    stderr_sha256=hashlib.sha256(err).hexdigest()) from exc
