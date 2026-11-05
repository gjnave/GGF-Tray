"""Member-facing setup and Quick Launch repair; never execute a package while inspecting it."""
import queue
import threading
import msvcrt
import os
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from ggf_installer import (discover_install_files, extract_archive, safe_install_path, sanitize_folder_name,
                           write_install_marker, upsert_registry, load_registry, InstallSafetyError)
from ggf_runtime import get_state_dir, run_local_target
from ggf_packages import reparse, LIMIT, COUNT

EXT = (".bat",".cmd",".exe")
PREF = Path(get_state_dir()) / "install-location.txt"
REG = str(PREF.with_name("installed_apps.txt"))

def pick_target(root, folder, initial, choices, title, allow_folder=False, archive_choice=False):
    options = list(dict.fromkeys([*([initial] if initial else []), *choices]))
    names = [os.path.relpath(x,folder) for x in options]
    default = "Keep packages as files" if archive_choice else "Open app folder" if allow_folder else "Skip this step"
    values = names + [default]
    value = tk.StringVar(value=names[0] if initial or (archive_choice and len(names)==1) else default)
    w = tk.Toplevel(root); w.title(title); w.attributes("-topmost",True)
    w.columnconfigure(0,weight=1)
    ttk.Label(w,text=title,font=("Segoe UI",12,"bold")).grid(row=0,column=0,sticky="w",padx=16,pady=(14,4))
    ttk.Label(w,text=str(folder),wraplength=530).grid(row=1,column=0,sticky="w",padx=16)
    combo = ttk.Combobox(w,textvariable=value,values=values,state="readonly",width=65)
    combo.grid(row=2,column=0,padx=16,pady=12,sticky="ew")
    result = [None]
    def browse():
        f=filedialog.askopenfilename(parent=w,initialdir=folder,filetypes=[("Windows programs","*.bat *.cmd *.exe")])
        if f:
            try: rel=validate_target(folder,f).relative_to(folder)
            except (ValueError,OSError,InstallSafetyError) as exc:
                messagebox.showwarning(title,str(exc),parent=w); return
            label=str(rel)
            if label not in values: values.append(label)
            combo["values"]=values;value.set(label)
    def select():
        if value.get()!=default:
            if archive_choice:
                chosen=str(folder/value.get())
                if chosen not in options: return
                result[0]=chosen
            else: result[0]=str(validate_target(folder,folder/value.get()))
        w.destroy()
    bar=ttk.Frame(w);bar.grid(row=3,column=0,sticky="e",padx=16,pady=(0,14))
    if not archive_choice: ttk.Button(bar,text="Browse…",command=browse).pack(side="left",padx=5)
    ttk.Button(bar,text="Use selection" if allow_folder else "Continue",command=select).pack(side="left")
    w.protocol("WM_DELETE_WINDOW", w.destroy); w.grab_set(); root.wait_window(w)
    return result[0]

def validate_target(folder, file):
    path=Path(file).resolve(strict=True); base=Path(folder).resolve(strict=True)
    if not path.is_relative_to(base) or not path.is_file() or path.suffix.lower() not in EXT:
        raise InstallSafetyError("Choose a BAT, CMD or EXE inside this app folder.")
    return path

def choose_location(root, default_name):
    try: base=PREF.read_text(encoding="utf-8").strip()
    except OSError: base=""
    base_var=tk.StringVar(value=base or str(Path.home()/"GGF Apps"))
    name=tk.StringVar(value=sanitize_folder_name(default_name))
    w=tk.Toplevel(root);w.title("Install a GGF app");w.attributes("-topmost",True)
    f=ttk.Frame(w,padding=18);f.pack(fill="both",expand=True); f.columnconfigure(0,weight=1)
    ttk.Label(f,text="Choose the app’s home",font=("Segoe UI",14,"bold")).grid(row=0,column=0,sticky="w")
    ttk.Label(f,text="Library location • remembered for the next install").grid(row=1,column=0,sticky="w",pady=(10,2))
    ttk.Entry(f,textvariable=base_var,width=54).grid(row=2,column=0,sticky="ew")
    def browse():
        folder=filedialog.askdirectory(parent=w,initialdir=base_var.get() if Path(base_var.get()).is_dir() else Path.home())
        if folder: base_var.set(folder)
    ttk.Button(f,text="Browse…",command=browse).grid(row=2,column=1,padx=6)
    ttk.Label(f,text="New folder for this app").grid(row=3,column=0,sticky="w",pady=(12,2))
    ttk.Entry(f,textvariable=name).grid(row=4,column=0,sticky="ew")
    ttk.Label(f,text="Files are prepared first. You choose whether to run setup.").grid(row=5,column=0,sticky="w",pady=12)
    result=[]
    def accept():
        try:
            if not Path(base_var.get()).is_absolute(): raise ValueError("Choose an absolute library path.")
            folder=Path(safe_install_path(base_var.get(),name.get()))
            if any(reparse(node) for node in (folder,*folder.parents)): raise ValueError("Choose a location without linked folders.")
            if folder.exists(): raise ValueError("That folder already exists. Choose a new name.")
            if any(k.casefold()==folder.name.casefold() for k in load_registry(REG)):
                raise ValueError("That app name is already in your library. Choose a distinct name.")
            folder.mkdir(parents=True,exist_ok=False)
            result.append(folder);w.destroy()
        except (ValueError,OSError,InstallSafetyError) as e: messagebox.showwarning("Installation location",str(e),parent=w)
    bar=ttk.Frame(f);bar.grid(row=6,column=0,columnspan=2,sticky="e")
    ttk.Button(bar,text="Cancel",command=w.destroy).pack(side="left",padx=5)
    ttk.Button(bar,text="Prepare files",command=accept).pack(side="left")
    w.grab_set();root.wait_window(w)
    return result[0] if result else None

def unpack_with_status(root, package, folder, max_bytes=LIMIT, max_count=COUNT):
    w=tk.Toplevel(root);w.title("Preparing app");w.attributes("-topmost",True)
    box=ttk.Frame(w,padding=16);box.pack(fill="both",expand=True)
    ttk.Label(box,text=package.name,wraplength=500).pack(anchor="w")
    ttk.Label(box,text="Checking and extracting into "+str(folder),wraplength=500).pack(anchor="w",pady=6)
    bar=ttk.Progressbar(box,mode="indeterminate",length=440);bar.pack();bar.start(20)
    done=queue.Queue()
    def worker():
        try:
            if package.suffix.lower() in EXT:
                shutil.copyfile(package,folder/package.name)
                used=(1,package.stat().st_size)
            else: used=extract_archive(str(package),str(folder),max_bytes=max_bytes,max_count=max_count)
            done.put(used)
        except Exception as exc: done.put(exc)
    answer=[]
    def poll():
        try: answer.append(done.get_nowait())
        except queue.Empty: w.after(80,poll); return
        bar.stop();w.destroy()
    w.protocol("WM_DELETE_WINDOW",lambda:None);w.grab_set()
    threading.Thread(target=worker,daemon=True).start();w.after(60,poll);root.wait_window(w)
    if isinstance(answer[0],Exception): raise answer[0]
    return answer[0]

def prepare(tray, source=None):
    root=tk.Tk();root.withdraw();root.attributes("-topmost",True)
    folder=None;lock=None
    try:
        lock=open(PREF.with_name("setup.lock"),"a+b")
        try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError: raise ValueError("Another GGF setup is open. Finish it before starting this one.")
        if not source: source=filedialog.askopenfilename(parent=root,title="Select a GGF package",filetypes=[("Windows packages","*.zip *.rar *.7z *.bat *.cmd *.exe")])
        if not source: return
        package=Path(source).absolute()
        if not package.is_file(): raise ValueError("Package not found.")
        folder=choose_location(root,package.stem)
        if not folder: return
        used_count,used_bytes=unpack_with_status(root,package,folder)
        PREF.write_text(str(folder.parent),encoding="utf-8")
        found=discover_install_files(str(folder))
        if not (found["installers"] or found["launchers"] or found["executables"]):
            choices=sorted((str(path) for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in {".zip",".rar",".7z"}),key=str.casefold)
            if choices:
                selected=pick_target(root,folder,None,choices,"Choose a package inside this download",archive_choice=True)
                if selected:
                    # Only unpack one member-selected inner archive. Charge both layers to the same budgets.
                    dest=folder/"GGF package contents"
                    dest.mkdir(exist_ok=False)
                    unpack_with_status(root,Path(selected),dest,LIMIT-used_bytes,COUNT-used_count)
                    found=discover_install_files(str(dest))
        all_files=found["installers"]+found["launchers"]+found["executables"]
        setup=None
        if found["installers"] or (all_files and not found["best_launcher"]):
            setup=pick_target(root,folder,found["best_installer"],all_files,"Choose setup to run")
        launcher=None
        if all_files:
            launcher=pick_target(root,folder,found["best_launcher"],[p for p in all_files if p!=setup],"Choose a Quick Launch target",True)
        write_install_marker(str(folder),folder.name,str(package),launcher)
        upsert_registry(REG,folder.name,str(folder),launcher)
        tray.upsert_shortcut(folder.name,launcher or str(folder))
        tray.refresh_shortcuts()
        if tray.utility_mode and tray.ipc_token: tray.send_command_to_running_tray("refresh_shortcuts")
        if setup:
            run_local_target(validate_target(folder,setup))
        messagebox.showinfo("GGF library",f"{folder.name} added to Quick Launch.\n\n{folder}\n\n"+
            ("Setup started. Let it finish before launching the app.\n" if setup else "")+
            (f"Launcher: {Path(launcher).name}" if launcher else "Quick Launch will look for a launcher when you use it, or open this folder."),parent=root)
    except Exception as exc:
        messagebox.showerror("Could not finish setup",str(exc)+(f"\n\nFiles already prepared remain in:\n{folder}" if folder else ""),parent=root)
    finally:
        if lock: lock.close()
        root.destroy()

def launch_entry(tray,name,path):
    folder=Path(path)
    if not folder.is_dir():
        run_local_target(folder);return
    entry=load_registry(REG).get(name)
    if not entry or os.path.normcase(os.path.abspath(entry[0]))!=os.path.normcase(str(folder.absolute())):
        os.startfile(str(folder));return
    found=discover_install_files(str(folder))
    options=found["launchers"]+found["executables"]
    if not options: os.startfile(str(folder));return
    root=tk.Tk();root.withdraw();root.attributes("-topmost",True)
    try: picked=pick_target(root,folder,found["best_launcher"],options,"Run this app",True)
    finally: root.destroy()
    if picked:
        tray.upsert_shortcut(name,picked);upsert_registry(REG,name,str(folder),picked);tray.refresh_shortcuts()
        run_local_target(validate_target(folder,picked))
    else: os.startfile(str(folder))

