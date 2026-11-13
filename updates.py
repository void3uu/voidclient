import re
import hashlib
import os
import subprocess
import sys
import json
import tempfile
from pathlib import Path
from time import time_ns
from urllib.request import Request, urlopen

# Increase this number on GitHub to publish an update.
BUILD = 7
REPOSITORY = "void3uu/voidclient"


def check_update():
    if getattr(sys, "frozen", False):
        return packaged_release()

    request = Request(
        f"https://raw.githubusercontent.com/{REPOSITORY}/main/updates.py?check={time_ns()}",
        headers={"User-Agent": "VoidClient", "Cache-Control": "no-cache"},
    )
    with urlopen(request, timeout=5) as response:
        source = response.read(16385)
    if len(source) > 16384:
        return None
    builds = re.findall(rb"^BUILD[ \t]*=[ \t]*([0-9]{1,9})[ \t]*\r?$", source, re.MULTILINE)
    if len(builds) == 1 and int(builds[0]) > BUILD:
        return f"https://github.com/{REPOSITORY}/archive/refs/heads/main.zip"
    return None


def install_update():
    if getattr(sys, "frozen", False):
        install_packaged_update()
        return

    # Resolve main once so every file comes from the same commit.
    request = Request(f"https://api.github.com/repos/{REPOSITORY}/commits/main",
                      headers={"User-Agent": "VoidClient", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=8) as response:
        commit = json.loads(response.read(262145))["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("GitHub returned an invalid commit.")

    directory = Path(__file__).resolve().parent
    names = ("main.py", "chrome.py", "updates.py")
    with tempfile.TemporaryDirectory(dir=directory) as stage:
        stage = Path(stage)
        originals = {}
        for name in names:
            url = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{name}"
            with urlopen(url, timeout=8) as response:
                data = response.read(262145)
            if len(data) > 262144:
                raise ValueError(f"{name} exceeds the update size limit.")
            compile(data, name, "exec")
            if name == "updates.py":
                builds = re.findall(rb"^BUILD[ \t]*=[ \t]*([0-9]{1,9})[ \t]*\r?$", data, re.MULTILINE)
                if len(builds) != 1 or int(builds[0]) <= BUILD:
                    raise ValueError("GitHub no longer has a newer build.")
            originals[name] = (directory / name).read_bytes()
            (stage / name).write_bytes(data)

        replaced = []
        try:
            for name in names:
                (stage / name).replace(directory / name)
                replaced.append(name)
        except OSError:
            for name in reversed(replaced):
                backup = stage / name
                backup.write_bytes(originals[name])
                backup.replace(directory / name)
            raise

def packaged_release():
    request = Request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
                      headers={"User-Agent": "VoidClient", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=8) as response:
        release = json.loads(response.read(262145))
    tag = re.fullmatch(r"voidclient-(\d{1,9})", release.get("tag_name", ""))
    if not tag or int(tag[1]) <= BUILD:
        return None
    for asset in release.get("assets", []):
        digest = asset.get("digest") or ""
        size = asset.get("size", 0)
        if (asset.get("name") == "voidclient.exe"
                and re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
                and 0 < size <= 80 * 1024 * 1024):
            url = f"https://github.com/{REPOSITORY}/releases/download/{tag[0]}/voidclient.exe"
            return url, digest[7:], size
    return None


def install_packaged_update():
    release = packaged_release()
    if not release:
        raise ValueError("No newer packaged build is available.")
    url, digest, size = release
    target = Path(sys.executable).resolve()
    fd, staged = tempfile.mkstemp(prefix="voidclient-update-", suffix=".exe", dir=target.parent)
    try:
        checksum = hashlib.sha256()
        with os.fdopen(fd, "wb") as output, urlopen(url, timeout=15) as response:
            remaining = size
            while remaining:
                chunk = response.read(min(remaining, 65536))
                if not chunk:
                    break
                output.write(chunk)
                checksum.update(chunk)
                remaining -= len(chunk)
            if remaining or response.read(1) or checksum.hexdigest() != digest:
                raise ValueError("The update download did not match the release checksum.")

        environment = dict(os.environ, VOIDCLIENT_TARGET=str(target), VOIDCLIENT_STAGE=staged,
                           PYINSTALLER_RESET_ENVIRONMENT="1")
        shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        subprocess.Popen(
            [str(shell), "-NoProfile", "-NonInteractive", "-Command", """
$target = $env:VOIDCLIENT_TARGET
$stage = $env:VOIDCLIENT_STAGE
$backup = $stage + '.bak'
$replaced = $false
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    try {
        [IO.File]::Replace($stage, $target, $backup)
        $replaced = $true
        break
    } catch [IO.IOException] {
        Start-Sleep -Milliseconds 250
    }
}
if ($replaced) {
    try {
        Start-Process -FilePath $target -ErrorAction Stop
        [IO.File]::Delete($backup)
    } catch {
        if ([IO.File]::Exists($backup)) {
            [IO.File]::Replace($backup, $target, $null)
            Start-Process -FilePath $target
        }
    }
} else {
    [IO.File]::Delete($stage)
}
"""], env=environment, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        Path(staged).unlink(missing_ok=True)
        raise
