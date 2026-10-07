using System;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Diagnostics;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows.Forms;

internal static class ProxyBenchSetup
{
    [STAThread]
    private static int Main(string[] args)
    {
        string destination = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "软件", "Noode-CG-ProxyBench");
        bool installOnly = args.Length == 2 && args[0] == "--install-only";
        if (installOnly) destination = Path.GetFullPath(args[1]);
        if (installOnly)
        {
            try { Install(destination, delegate(int value) {}); return 0; }
            catch { return 2; }
        }
        Application.EnableVisualStyles();
        using (Form window = new Form())
        {
            window.Text = "Noode-CG · 真实代理优选";
            window.ClientSize = new Size(560, 170);
            window.StartPosition = FormStartPosition.CenterScreen;
            window.FormBorderStyle = FormBorderStyle.FixedDialog;
            window.MaximizeBox = false;
            window.BackColor = Color.FromArgb(25, 29, 37);
            window.Font = new Font("Microsoft YaHei UI", 10);
            Label title = new Label { Text = "正在准备自动测速窗口", AutoSize = true, ForeColor = Color.White, Location = new Point(25, 25) };
            Label message = new Label { Text = "内置 Mihomo 内核和运行环境，完成后自动开始。", AutoSize = true, ForeColor = Color.LightGray, Location = new Point(25, 60) };
            ProgressBar progress = new ProgressBar { Minimum = 0, Maximum = 100, Size = new Size(510, 20), Location = new Point(25, 102) };
            window.Controls.Add(title); window.Controls.Add(message); window.Controls.Add(progress);
            window.Shown += async delegate
            {
                try
                {
                    await Task.Run(delegate { Install(destination, delegate(int value) { window.BeginInvoke((Action)delegate { progress.Value = value; }); }); });
                    Process.Start(new ProcessStartInfo("wscript.exe", "\"" + Path.Combine(destination, "Start-ProxyBench.vbs") + "\"") {
                        UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden, WorkingDirectory = destination
                    });
                    window.Close();
                }
                catch
                {
                    title.Text = "安装暂未完成";
                    message.Text = "请先关闭正在运行的优选窗口，再双击重试。";
                    progress.Value = 0;
                }
            };
            Application.Run(window);
        }
        return 0;
    }

    private static void Install(string destination, Action<int> progress)
    {
        destination = Path.GetFullPath(destination);
        Directory.CreateDirectory(destination);
        string prefix = destination.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        // Refuse overwriting an application that owns an active cloud or Mihomo run.
        foreach (string relative in new string[] { "app/runtime/cloud/run.lock", "app/runtime/mihomo/run.lock" })
        {
            string marker = Path.Combine(destination, relative.Replace('/', Path.DirectorySeparatorChar));
            if (!File.Exists(marker)) continue;
            using (FileStream check = new FileStream(marker, FileMode.Open, FileAccess.ReadWrite, FileShare.ReadWrite))
            { check.Lock(0, 1); check.Unlock(0, 1); }
        }
        using (FileStream installLock = new FileStream(Path.Combine(destination, ".install.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None))
        using (Stream payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("ProxyBenchPackage"))
        using (ZipArchive archive = new ZipArchive(payload, ZipArchiveMode.Read))
        {
            int index = 0;
            foreach (ZipArchiveEntry entry in archive.Entries)
            {
                int slash = entry.FullName.IndexOf('/');
                if (slash < 0) throw new InvalidDataException();
                string relative = entry.FullName.Substring(slash + 1).Replace('/', Path.DirectorySeparatorChar);
                string target = Path.GetFullPath(Path.Combine(destination, relative));
                if (!target.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException();
                if (entry.FullName.EndsWith("/")) { Directory.CreateDirectory(target); continue; }
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                // A later package never overwrites the owner's saved real Profile.
                if (!(relative.Contains(".local.") && File.Exists(target)))
                {
                    string temporary = target + ".install-new";
                    using (Stream source = entry.Open())
                    using (FileStream file = new FileStream(temporary, FileMode.Create, FileAccess.Write, FileShare.None)) source.CopyTo(file);
                    if (File.Exists(target)) File.Replace(temporary, target, null);
                    else File.Move(temporary, target);
                }
                progress(++index * 100 / archive.Entries.Count);
            }
        }
        progress(100);
    }
}
