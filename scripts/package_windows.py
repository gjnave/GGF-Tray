"""Package and install-test the official Windows tray."""
import argparse
import hashlib
import json
from importlib import metadata
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import winreg
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "ggf-menu"
PORTABLE = "GGF-Tray-OneFile.exe"
BUNDLE = "GGF-Tray-Windows-x64.zip"
SETUP = "GGF-Tray-Setup.exe"
UNINSTALL = "Uninstall GGF Tray.js"


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_setup(bundle, target, work, version):
    compiler = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    constants = work / "Package.g.cs"
    constants.write_text(
        'internal static class Package {\n'
        f'    internal const string Version = "{version}";\n'
        f'    internal const int Length = {bundle.stat().st_size};\n'
        f'    internal const string Sha256 = "{file_hash(bundle)}";\n'
        '}\n', encoding="ascii")
    source = ROOT / "scripts/setup"
    subprocess.run([str(compiler), "/nologo", "/optimize+", "/target:winexe", "/platform:x64",
                    "/reference:System.IO.Compression.dll", f"/win32icon:{APP / 'ggf-mark.ico'}",
                    f"/win32manifest:{source / 'as-user.manifest'}", f"/out:{target}",
                    str(source / "Setup.cs"), str(constants)], check=True)
    with target.open("ab") as installer, bundle.open("rb") as payload:
        shutil.copyfileobj(payload, installer)


def smoke_install(bundle, setup, work, version, expected_hash):
    extracted = work / "Member install & test"
    with zipfile.ZipFile(bundle) as archive:
        archive.extractall(extracted)
    local = work / "Local"
    roaming = work / "Roaming"
    system = Path(os.environ["SystemRoot"])
    test_id = uuid.uuid4().hex
    env = dict(os.environ, LOCALAPPDATA=str(local), APPDATA=str(roaming), GGF_TRAY_INSTALL_TEST_ID=test_id,
               PATH=os.pathsep.join(map(str, [system / "System32", system])))
    cmd = system / "System32/cmd.exe"
    # Make the self-extractor perform the first install on an empty profile.
    subprocess.run([str(setup), "--no-launch"], cwd=work, env=env, check=True, timeout=300)
    installed = local / "Programs/Get Going Fast" / f"Tray-{version}" / "GGF-Tray.exe"
    if file_hash(installed) != expected_hash or not (installed.parent / "notices/Tk-license.terms").is_file():
        raise ValueError("Self-extracting installer did not install the published application and notices")
    menu = roaming / "Microsoft/Windows/Start Menu/Programs"
    for link in ("Get Going Fast Tray.lnk", "Startup/GGF Tray.lnk"):
        if not (menu / link).is_file():
            raise ValueError(f"Self-extracting installer did not register {link}")
    # The BAT filename is fixed. The test folder deliberately contains spaces and an ampersand.
    subprocess.run(f'"{cmd}" /d /s /c ""Install GGF Tray.bat" --no-launch"', cwd=extracted,
                   env=env, check=True, timeout=180)
    if file_hash(installed) != expected_hash:
        raise ValueError("Installed executable differs from the release asset")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\GetGoingFast\InstallerTests\{test_id}") as registration:
        uninstall_command = winreg.QueryValueEx(registration, "UninstallString")[0]
        if (winreg.QueryValueEx(registration, "DisplayVersion")[0] != version
                or not uninstall_command.endswith(f'//E:JScript "{installed.parent / UNINSTALL}"')
                or not (installed.parent / UNINSTALL).is_file()):
            raise ValueError("Windows uninstall registration does not point to the installed version")
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"Software\GetGoingFast\InstallerTests\{test_id}")
    subprocess.run([str(installed), "--self-test"], cwd=installed.parent, env=env, check=True, timeout=180)
    diagnostics = (local / "GGF-Tray/release-diagnostics.txt").read_text()
    if diagnostics != f"GGF Tray {version} self-test OK":
        raise ValueError(f"Unexpected packaged diagnostics: {diagnostics}")
    if list((local / "GGF-Tray").glob("tray-notice-*.seen")):
        raise ValueError("An unattended installation consumed the first interactive welcome")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", type=Path)
    parser.add_argument("output", type=Path, help="New folder for the public release assets")
    parser.add_argument("--tag", help="For releases, require an exact match to the app version")
    args = parser.parse_args()
    match = re.search(r"StringStruct\('ProductVersion', '(\d+\.\d+\.\d+)'\)", (APP / "version_info.txt").read_text())
    version = match.group(1)
    tag = os.environ["GITHUB_REF_NAME"] if os.environ.get("GITHUB_REF_TYPE") == "tag" else args.tag
    if tag and tag != "v" + version:
        parser.error(f"Tag must be v{version} to release this executable")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    work = Path(tempfile.mkdtemp(prefix="ggf-release-"))
    exe = out / PORTABLE
    shutil.copyfile(args.exe, exe)
    bundle = out / BUNDLE
    base = Path(sys.base_prefix)
    boot = metadata.distribution("pyinstaller")
    terms = next(f for f in boot.files if f.name == "COPYING.txt")
    members = [
        (exe, "ggf-menu/GGF-Tray.exe"),  # Check for a running/locked EXE first on uninstall.
        (ROOT / "install-ggf-menu.bat", "Install GGF Tray.bat"),
        (ROOT / "LICENSE.txt", "LICENSE.txt"),
        (APP / "MEMBER-GUIDE.txt", "START HERE.txt"),
        (base / "LICENSE.txt", "notices/Python-LICENSE.txt"),
        (base / "tcl/tk8.6/license.terms", "notices/Tk-license.terms"),
        (boot.locate_file(terms), "notices/PyInstaller-COPYING.txt"),
    ]
    inventory = [[name.removeprefix("ggf-menu/").replace("/", "\\"), file_hash(path)]
                 for path, name in members]
    with zipfile.ZipFile(bundle, "x", zipfile.ZIP_DEFLATED) as archive:
        for path, name in members:
            archive.write(path, name)
        source = (ROOT / "scripts/setup/uninstall.js.in").read_text(encoding="utf-8")
        archive.writestr("ggf-menu/" + UNINSTALL, source.replace("@@VERSION@@", version)
                         .replace("@@FILES@@", json.dumps(inventory)).encode("ascii"))
    exe_hash = file_hash(exe)
    setup = out / SETUP
    build_setup(bundle, setup, work, version)
    smoke_install(bundle, setup, work, version, exe_hash)
    (out / "SHA256SUMS.txt").write_text(
        f"{file_hash(setup)}  {SETUP}\n{file_hash(bundle)}  {BUNDLE}\n{exe_hash}  {PORTABLE}\n",
        encoding="ascii", newline="\n"
    )
    print(f"Verified GGF Tray {version} assets in {out}")


if __name__ == "__main__":
    main()
