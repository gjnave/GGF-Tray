# Get Going Fast Tray for Windows

Browse the GGF app catalog, install tools your membership includes, and launch them again from the tray. The tray also includes media conversion, a music player and a Hugging Face model browser.

**[Get GGF Tray for Windows](https://gjnave.github.io/GGF-Tray/)**

The download page shows the recommended installer, its release date, and earlier versions.

Quit any running GGF Tray, double-click **GGF-Tray-Setup.exe**, and choose **Install GGF Tray**. Setup extracts the files, installs for your Windows account, and opens the tray. Right-click the turquoise G by the clock to open the catalog or change **Start silently with Windows**.

The first installation downloads about 288 MiB of Windows components from their publishers on PyPI. Setup verifies each download and stores the libraries under your Windows account. Subsequent launches use the installed copies. The standalone EXE uses the same setup.

GGF licenses its original code and artwork for end-user operation of the official, unmodified release. Each third-party component retains its own license and can be replaced independently. [Read the GGF end-user license](LICENSE.txt).

To link your membership, click **Sign in** in the catalog. Sign in on the website, match the code, and choose **Link Desktop App**. If you land on the member homepage, **Continue in browser** reopens the matching confirmation page.

[Manual ZIP](https://github.com/gjnave/GGF-Tray/releases/latest/download/GGF-Tray-Windows-x64.zip) · [Standalone EXE](https://github.com/gjnave/GGF-Tray/releases/latest/download/GGF-Tray-OneFile.exe) · [SHA-256 checksums](https://github.com/gjnave/GGF-Tray/releases/latest/download/SHA256SUMS.txt) · [All releases](https://github.com/gjnave/GGF-Tray/releases)

## Windows build instructions for authorized maintainers

From the repository root in Command Prompt, install the Python 3.11 x64 build dependencies and run the local build.

```bat
cd ggf-menu
py -3.11 -m venv build-venv
build-venv\Scripts\python.exe -m pip install -r requirements-release.txt
build-ggf-tray.bat
```

To create the public downloads locally, return to the repository root. Pass the verified EXE path printed by the build and a new output folder. The packager uses the Windows .NET Framework x64 C# compiler for the self-extracting installer.

```bat
ggf-menu\build-venv\Scripts\python.exe scripts\package_windows.py "PATH-TO-BUILT-EXE" "release\public-assets"
```

Pushes to main run the Windows tests, build Setup, install it in a fresh profile, check the manual ZIP installer, and run the installed app's self-test. To publish, tag the intended commit with the matching app version (for example, `v0.16.1`). The release workflow attaches Setup, the manual ZIP, the standalone EXE, and their checksums to GitHub Releases.
