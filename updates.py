import re
from time import time_ns
from urllib.request import Request, urlopen

# Increase this number on GitHub to publish an update.
BUILD = 2
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

