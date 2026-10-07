# Windows packaging

Build the public ZIP with `python scripts/build_windows_package.py` and its single-file EXE with `python scripts/build_windows_installer.py`. Add `--personal` to each command only for the owner-authorized local package containing the real profile. Personal packages must not be uploaded to public Releases.

The package contains embedded Python, PyYAML, psutil, GitHub CLI, Mihomo, and Windows curl. The EXE extracts to the owner's Desktop software directory and opens the local window. ZIP users can launch `Start-ProxyBench.vbs`. Work begins after the user clicks the primary start button.

Reinstallation preserves existing local profiles and state. Active cloud or core locks prevent replacement during a benchmark. Identical existing files are skipped, reducing replacement conflicts with loaded runtime files. The installer uses explicit UTF-8 compilation and validates archive paths.

The application uses the owner's local GitHub login and creates a separate repository-scoped runner. Its directory and registration are not bundled. The first operation downloads the official runner, verifies its digest, and configures it without logging registration tokens. The owned runner survives all replenishment rounds and its registration is cleaned up afterward.

The interface is Chinese, with 300 IPs per page and an on-demand detail dialog. Initial discovery fetches both full feeds plus 10,000 official candidates. Subsequent discovery requests fresh 10,000-address edge samples only. Final retests compete with the previous ordinary TOP100 and append verified Japanese exits. Insufficient results continue replenishment; pause and stop preserve progress.

Public archives exclude local credentials, runner registration, measurements, logs, and transient configurations. Version 1.0.1 initializes the isolated rule-mode core and starts the candidate scan without the former startup bandwidth gate. The speed probe follows the original local package's 512 KiB / 95% / 3 Mbps defaults; failures remain per-candidate results.
