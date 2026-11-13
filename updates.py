import re
import json
import tempfile
from pathlib import Path
from time import time_ns
from urllib.request import Request, urlopen

# Increase this number on GitHub to publish an update.
BUILD = 4
REPOSITORY = "void3uu/voidclient"


def check_update():
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

