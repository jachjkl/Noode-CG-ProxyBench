# Windows packaging

Build the public ZIP with `python scripts/build_windows_package.py` and its single-file EXE with `python scripts/build_windows_installer.py`. Add `--personal` to each command only for the owner-authorized local package containing the real profile. Personal packages must not be uploaded to public Releases.

The package contains embedded Python, PyYAML, psutil, GitHub CLI, Mihomo, and Windows curl. The EXE extracts to a Noode-CG-ProxyBench subdirectory beside the running EXE and opens the local window. ZIP users can launch `Start-ProxyBench.vbs`. Work begins after the user clicks the primary start button.

Reinstallation preserves existing local profiles and state. Active cloud or core locks prevent replacement during a benchmark. Identical existing files are skipped, reducing replacement conflicts with loaded runtime files. The installer uses explicit UTF-8 compilation and validates archive paths.

The application uses the owner's local GitHub login. Discovery and publication run on Ubuntu, while the local benchmark runs directly under the desktop controller. A self-hosted Windows Runner is no longer required for normal use. Candidate and core assets use digest-checked public mirrors; authenticated GitHub operations use official endpoints. Local HTTP proxy variables are not automatically adopted for cloud control. Existing VPN routes and proxy clients are inspected without being changed.

The interface is Chinese, with 300 IPs per page and an on-demand detail dialog. Initial discovery fetches both full feeds plus 10,000 official candidates. Subsequent discovery requests fresh 10,000-address edge samples only. Final retests compete with the previous ordinary TOP100 and append verified Japanese exits. Insufficient results continue replenishment; pause and stop preserve progress.

Public archives exclude local credentials, runner registration, measurements, logs, and transient configurations. Version 1.0.1 initializes the isolated rule-mode core and starts the candidate scan without the former startup bandwidth gate. The speed probe follows the original local package's 512 KiB / 95% / 3 Mbps defaults; failures remain per-candidate results.

## Combined repair package

`python scripts/build_delivery_bundle.py --personal` creates the owner's combined maintenance ZIP in the project directory. Omit `--personal` for the public variant. The archive contains:

```text
Local Windows role / installation packages / Windows EXE and ZIP
Cloud GitHub role / source / source ZIP
Build cache / embedded Python archive, wheels, GitHub CLI, Mihomo
SHA-256 inventory
Actual directory listing
Chinese repair and rebuild instructions
Prepare-workspace CMD
Rebuild CMD and PowerShell helper
```

The generated PowerShell helper verifies the archive inventory, extracts a separate repair workspace and portable build environment, copies only missing build inputs, and preserves existing source edits and local profiles. Its UTF-8 BOM supports Windows PowerShell 5.1. It invokes the embedded Python to regenerate both role packages and the combined ZIP. An extracted source tree can be enumerated without Git, while local credentials, runner registrations, caches, and measurements remain excluded from public source.

Both role packages include the version and build scripts. Initial `output/nodes.txt` placeholders are empty; measurement results belong to the live application's output and the published repository. A common `VERSION` value controls file names. Animation code is included with the dashboard and is verified in browser checks.
