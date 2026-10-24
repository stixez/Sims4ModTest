"""Is there a newer Sims 4 Mod Test? Asks GitHub for the latest release, at most once a day,
in the background. Nothing is downloaded or installed: the app offers the download for this
system and the user decides. Nothing about the user is sent."""
from __future__ import annotations

import http.client
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

from version import __version__

REPO = "stixez/Sims4ModTest"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
_MAX_RESPONSE = 1 << 20  # a release's JSON is a few KB
_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


@dataclass(frozen=True)
class Release:
    version: str          # "1.1.0"
    download: str         # this system's file, or the release page if there is none


def parse_version(text: str) -> tuple[int, int, int] | None:
    m = _VERSION.match(text.strip())
    if m is None:
        return None
    return int(m[1]), int(m[2]), int(m[3] or 0)


def is_newer(latest: str, current: str = __version__) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def _asset_for(assets: list[dict], platform: str) -> str | None:
    """The installer on Windows, the app on macOS, the archive on Linux (see packaging/build.py)."""
    suffix = {"win32": "-setup.exe", "darwin": "-macos.zip"}.get(platform, "-linux-x86_64.tar.gz")
    for asset in assets:
        name, url = asset.get("name"), asset.get("browser_download_url")
        if isinstance(name, str) and isinstance(url, str) and name.endswith(suffix):
            return url
    return None


def parse_release(data: object, platform: str = sys.platform) -> Release | None:
    """The release GitHub's API describes, or None if it isn't one to offer."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name")
    if not isinstance(tag, str) or parse_version(tag) is None:
        return None
    page = data.get("html_url")
    if not isinstance(page, str) or not page.startswith(f"https://github.com/{REPO}/"):
        page = RELEASES_PAGE
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    download = _asset_for([a for a in assets if isinstance(a, dict)], platform)
    if download is None or not download.startswith(f"https://github.com/{REPO}/"):
        download = page  # only ever send the user to this project's own GitHub pages
    return Release(tag.lstrip("v"), download)


def _tls_context() -> ssl.SSLContext:
    """Windows has the system's certificates; a frozen app on macOS or Linux may not find them
    where Python looks, so it brings its own (certifi)."""
    if sys.platform == "win32":
        return ssl.create_default_context()
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        return ssl.create_default_context()


class CheckFailed(Exception):
    """GitHub couldn't be asked: offline, rate limited, a private repo, or a broken answer."""


def find_update(skipped: str = "", timeout: float = 5.0) -> Release | None:
    """A release newer than this one that the user hasn't said "not now" to, or None if there
    is none. Raises CheckFailed when it can't tell."""
    request = urllib.request.Request(LATEST_API, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"Sims4ModTest/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_tls_context()) as response:
            raw = response.read(_MAX_RESPONSE + 1)
        if len(raw) > _MAX_RESPONSE:
            raise CheckFailed("answer too large")
        release = parse_release(json.loads(raw))
    except (urllib.error.URLError, OSError, ValueError, RecursionError, http.client.HTTPException) as e:
        raise CheckFailed(str(e)) from e
    if release is None or not is_newer(release.version) or release.version == skipped:
        return None
    return release



