using System;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Diagnostics;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading.Tasks;
using System.Windows.Forms;

internal static class ProxyBenchSetup
{
    [STAThread]
    private static int Main(string[] args)
    {
        string destination = Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location), "Noode-CG-ProxyBench");
        bool explicitDestination = args.Length == 2 && args[0] == "--install-only";
        bool installOnly = explicitDestination || (args.Length == 1 && args[0] == "--install-adjacent");
        if (explicitDestination) destination = Path.GetFullPath(args[1]);
        if (installOnly)
        {
            try { Install(destination, delegate(int value) {}); return 0; }
            catch (Exception error)
            {
                try { File.WriteAllText(Path.Combine(destination, "install-error.txt"), error.GetType().Name + ": " + error.Message + "\n" + error.Data["relative_file"]); } catch {}
                return 2;
            }
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
            Label title = new Label { Text = "正在准备代理测速窗口", AutoSize = true, ForeColor = Color.White, Location = new Point(25, 25) };
            Label message = new Label { Text = "已内置代理内核，窗口打开后点击【开始优选】。", AutoSize = true, ForeColor = Color.LightGray, Location = new Point(25, 60) };
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
        foreach (string relative in new string[] { "app/runtime/cloud/run.lock", "app/runtime/mihomo/run.lock", "app/runtime/tcp-bench/run.lock" })
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
                // Preserve installed profiles, saved rules, checkpoints and published output.
                string packagePath = entry.FullName.Substring(slash + 1);
                bool savedFile = relative.Contains(".local.") ||
                    packagePath.StartsWith("app/data/", StringComparison.OrdinalIgnoreCase) ||
                    packagePath.StartsWith("app/output/", StringComparison.OrdinalIgnoreCase);
                if (!(savedFile && File.Exists(target)))
                {
                    string temporary = target + ".install-new";
                    using (Stream source = entry.Open())
                    using (FileStream file = new FileStream(temporary, FileMode.Create, FileAccess.Write, FileShare.None)) source.CopyTo(file);
                    try
                    {
                        if (File.Exists(target) && EqualFile(temporary, target)) File.Delete(temporary);
                        else if (File.Exists(target)) File.Replace(temporary, target, null);
                        else File.Move(temporary, target);
                    }
                    catch (Exception error) { error.Data["relative_file"] = relative; throw; }
                }
                progress(++index * 100 / archive.Entries.Count);
            }
        }
        progress(100);
    }

    private static bool EqualFile(string first, string second)
    {
        if (new FileInfo(first).Length != new FileInfo(second).Length) return false;
        using (SHA256 algorithm = SHA256.Create())
        using (FileStream left = File.OpenRead(first))
        using (FileStream right = File.OpenRead(second))
            return Convert.ToBase64String(algorithm.ComputeHash(left)) == Convert.ToBase64String(algorithm.ComputeHash(right));
    }
}
