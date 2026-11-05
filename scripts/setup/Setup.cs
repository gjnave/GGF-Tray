using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("GGF Tray Setup")]
[assembly: AssemblyCompany("Get Going Fast")]
[assembly: AssemblyProduct("GGF Tray")]
[assembly: AssemblyFileVersion(Package.Version + ".0")]

internal static class Setup
{
    // Only these names from the verified member ZIP have an installation destination.
    static readonly Dictionary<string, string> Files = new Dictionary<string, string> {
        {"Install GGF Tray.bat", "Install GGF Tray.bat"},
        {"ggf-menu/GGF-Tray.exe", "GGF-Tray.exe"},
        {"LICENSE.txt", "LICENSE.txt"},
        {"START HERE.txt", "START HERE.txt"},
        {"notices/Python-LICENSE.txt", @"notices\Python-LICENSE.txt"},
        {"notices/Tk-license.terms", @"notices\Tk-license.terms"},
        {"notices/PyInstaller-COPYING.txt", @"notices\PyInstaller-COPYING.txt"}
    };

    static string Hash(Stream stream)
    {
        using (var sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }

    static byte[] ReadPackage()
    {
        // The original ZIP is appended verbatim. Read it from our own EXE, never from Downloads.
        byte[] bytes;
        using (var file = File.OpenRead(Application.ExecutablePath))
        {
            if (file.Length <= Package.Length) throw new InvalidDataException("The installer is incomplete.");
            file.Seek(-Package.Length, SeekOrigin.End);
            using (var reader = new BinaryReader(file)) bytes = reader.ReadBytes(Package.Length);
        }
        using (var content = new MemoryStream(bytes))
            if (bytes.Length != Package.Length || Hash(content) != Package.Sha256)
                throw new InvalidDataException("The installer failed its integrity check. Download it again from the official GGF Tray page.");
        return bytes;
    }

    static void CheckOrdinaryPath(string path)
    {
        if ((File.Exists(path) || Directory.Exists(path)) &&
            (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            throw new IOException("Setup cannot install through a linked path: " + path);
    }

    static void Extract(byte[] bytes, string destination)
    {
        using (var zip = new ZipArchive(new MemoryStream(bytes), ZipArchiveMode.Read))
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var entry in zip.Entries)
                if (!Files.ContainsKey(entry.FullName) || !names.Add(entry.FullName))
                    throw new InvalidDataException("Unexpected or repeated file in this package.");
            if (names.Count != Files.Count) throw new InvalidDataException("The package is incomplete.");
            CheckOrdinaryPath(destination);
            CheckOrdinaryPath(Path.Combine(destination, "notices"));
            foreach (var entry in zip.Entries)
            {
                string target = Path.Combine(destination, Files[entry.FullName]);
                CheckOrdinaryPath(target);
                if (File.Exists(target))
                    using (var installed = File.OpenRead(target))
                    using (var member = entry.Open())
                        if (Hash(installed) != Hash(member))
                            throw new IOException("A different file already exists at " + target + ". Setup preserved it.");
            }
            foreach (var entry in zip.Entries)
            {
                string target = Path.Combine(destination, Files[entry.FullName]);
                if (File.Exists(target)) continue;
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                string partial = target + "." + Guid.NewGuid().ToString("N") + ".partial";
                using (var input = entry.Open())
                using (var output = new FileStream(partial, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                    input.CopyTo(output);
                File.Move(partial, target);
            }
        }
    }

    static bool ReadyToInstall()
    {
        while (true)
        {
            Mutex tray;
            if (!Mutex.TryOpenExisting(@"Global\GGF-Tray-Unique-Mutex-87A3F9B2", out tray)) return true;
            tray.Dispose();
            if (MessageBox.Show("Right-click the GGF icon by the Windows clock and choose Quit, then click Retry.",
                "Quit GGF Tray before installing", MessageBoxButtons.RetryCancel, MessageBoxIcon.Information)
                != DialogResult.Retry) return false;
        }
    }

    static bool AskInstall()
    {
        using (var form = new Form())
        using (var panel = new FlowLayoutPanel())
        {
            form.Text = "GGF Tray Setup";
            form.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            form.Font = SystemFonts.MessageBoxFont;
            form.StartPosition = FormStartPosition.CenterScreen;
            form.FormBorderStyle = FormBorderStyle.FixedDialog;
            form.MinimizeBox = false;
            form.MaximizeBox = false;
            form.AutoSize = true;
            form.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            panel.AutoSize = true;
            panel.FlowDirection = FlowDirection.TopDown;
            panel.WrapContents = false;
            panel.Padding = new Padding(18);
            var heading = new Label { AutoSize = true, Text = "Install GGF Tray " + Package.Version,
                Font = new Font(form.Font.FontFamily, 16, FontStyle.Bold), ForeColor = Color.FromArgb(18, 78, 68) };
            var text = new Label { AutoSize = true, MaximumSize = new Size(390, 0),
                Margin = new Padding(3, 9, 3, 14),
                Text = "Setup installs GGF Tray for your Windows account and opens it when ready. First setup downloads about 288 MiB of components." };
            var buttons = new FlowLayoutPanel { AutoSize = true, WrapContents = false };
            var install = new Button { AutoSize = true, Text = "Install GGF Tray", DialogResult = DialogResult.OK };
            var cancel = new Button { AutoSize = true, Text = "Cancel", DialogResult = DialogResult.Cancel };
            buttons.Controls.AddRange(new Control[] { install, cancel });
            panel.Controls.AddRange(new Control[] { heading, text, buttons });
            form.Controls.Add(panel);
            form.AcceptButton = install;
            form.CancelButton = cancel;
            return form.ShowDialog() == DialogResult.OK;
        }
    }

    [STAThread]
    static int Main(string[] args)
    {
        bool quiet = args.Length == 1 && args[0] == "--no-launch";
        if (args.Length != 0 && !quiet) return 2;
        Application.EnableVisualStyles();
        try
        {
            byte[] bytes = ReadPackage();
            if (!quiet && (!AskInstall() || !ReadyToInstall())) return 2;
            bool first;
            using (var installation = new Mutex(true, @"Local\GetGoingFast.Tray.Setup", out first))
            {
                if (!first) throw new IOException("Another GGF Tray installation is already open.");
                string local = Environment.GetEnvironmentVariable("LOCALAPPDATA");
                if (String.IsNullOrEmpty(local) || !Path.IsPathRooted(local)) throw new IOException("Windows local app data is unavailable.");
                string programs = Path.Combine(local, "Programs");
                string ggf = Path.Combine(programs, "Get Going Fast");
                CheckOrdinaryPath(programs);
                CheckOrdinaryPath(ggf);
                string destination = Path.Combine(ggf, "Tray-" + Package.Version);
                Extract(bytes, destination);
                var register = new ProcessStartInfo {
                    FileName = Path.Combine(Environment.SystemDirectory, "cmd.exe"),
                    WorkingDirectory = destination, CreateNoWindow = true, UseShellExecute = false,
                    Arguments = "/d /s /c \"\"Install GGF Tray.bat\" " + (quiet ? "--from-setup-quiet" : "--from-setup") + "\"",
                    RedirectStandardOutput = true
                };
                using (var process = Process.Start(register))
                {
                    string message = process.StandardOutput.ReadToEnd();
                    process.WaitForExit();
                    if (process.ExitCode != 0) throw new IOException("Setup could not finish. " + message.Trim());
                }
                if (!quiet)
                    Process.Start(new ProcessStartInfo(Path.Combine(destination, "GGF-Tray.exe")) {
                        WorkingDirectory = destination, UseShellExecute = false });
            }
            return 0;
        }
        catch (Exception error)
        {
            if (!quiet) MessageBox.Show(error.Message, "GGF Tray Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
            else Console.Error.WriteLine(error.Message);
            return 1;
        }
    }
}
