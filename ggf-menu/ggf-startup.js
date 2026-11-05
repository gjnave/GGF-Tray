// GGF owns only its named shortcut. Parking it preserves the user's opt-out on upgrade.
var a = WScript.Arguments;
var mode = a(0), active = a(1), parked = a(2), target = a(3), args = a(4), work = a(5);
var fs = new ActiveXObject("Scripting.FileSystemObject");
var shell = new ActiveXObject("WScript.Shell");
var marker = "Get Going Fast Tray - silent Windows startup";
function fail(text) { WScript.Echo(text); WScript.Quit(1); }
function norm(path) { return fs.GetAbsolutePathName(path).toLowerCase(); }
function owned(path) {
    var link = shell.CreateShortcut(path);
    if (link.Description === marker) return true;
    // The older source installer linked the root BAT from its own install folder.
    var legacy = fs.BuildPath(fs.GetParentFolderName(work), "GGF-Tray.bat");
    if (norm(link.TargetPath) === norm(legacy) && fs.FileExists(legacy)) return true;
    var parent = fs.GetParentFolderName(link.TargetPath);
    if (fs.GetFileName(link.TargetPath).toLowerCase() === "ggf-tray.bat" &&
        fs.FileExists(link.TargetPath) && norm(link.WorkingDirectory) === norm(parent) &&
        fs.FileExists(fs.BuildPath(parent,"ggf-menu\\ggf-tray.py"))) return true;
    return false;
}
function writeLink(path) {
    var link = shell.CreateShortcut(path);
    link.TargetPath = target;
    link.WorkingDirectory = work;
    link.Arguments = args;
    link.WindowStyle = 7;
    link.Description = marker;
    link.IconLocation = (/pythonw\.exe$/i.test(target) ? fs.BuildPath(work,"ggf-mark.ico") : target) + ",0";
    link.Save();
}
if (fs.FileExists(active) && !owned(active)) fail("A different Startup shortcut already uses the name GGF Tray. Windows Startup was left as configured.");
if (fs.FileExists(parked) && !owned(parked)) fail("The saved startup preference belongs to another shortcut.");
if (mode === "off") {
    if (fs.FileExists(active)) {
        if (fs.FileExists(parked)) fail("Two GGF startup preferences exist. Check the Startup folder.");
        fs.MoveFile(active, parked);
    } else if (!fs.FileExists(parked)) {
        writeLink(parked);
    }
} else if (fs.FileExists(parked) && !fs.FileExists(active)) {
    if (mode === "on") {
        writeLink(parked);
        fs.MoveFile(parked, active);
    } else if (mode === "install") {
        writeLink(parked);
    }
} else if (mode === "default" && fs.FileExists(active)) {
    var existing = shell.CreateShortcut(active);
    if (existing.Description !== marker || !fs.FileExists(existing.TargetPath)) writeLink(active);
} else {
    writeLink(active);
}

