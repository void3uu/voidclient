import json
import re

from urllib.request import Request


from urllib.request import urlopen

# Increase this for each desktop release.
BUILD = 1
REPOSITORY = "void3uu/voidclient"


def check_update():
    owner_repo = REPOSITORY
    request = Request(
        f"https://api.github.com/repos/{owner_repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "VoidClient"},
    )
    with urlopen(request, timeout=5) as response:
        data = json.loads(response.read(262145))
    tag = data.get("tag_name", "")
    match = re.fullmatch(r"voidclient-(\d{1,9})", tag) if isinstance(tag, str) else None
    if match and int(match[1]) > BUILD:
        return f"https://github.com/{owner_repo}/releases/tag/{tag}"
    return None


