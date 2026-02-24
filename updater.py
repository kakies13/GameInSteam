"""
GameInSteam — Auto Updater
Update check and download via GitHub Releases API.
"""

import os
import sys
import subprocess
import tempfile
import threading
import time
import requests

GITHUB_REPO = "kakies13/GameInSteam"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Read version number from VERSION.txt (fallback if missing)
def _get_version():
    try:
        # Use sys._MEIPASS if PyInstaller bundled
        if getattr(sys, 'frozen', False):
            # Running as EXE
            base_path = sys._MEIPASS
        else:
            # Running as normal Python script
            base_path = os.path.dirname(__file__)
        
        version_file = os.path.join(base_path, "VERSION.txt")
        if os.path.exists(version_file):
            with open(version_file, "r", encoding="utf-8") as f:
                version = f.read().strip()
                if version:
                    return version
    except Exception:
        pass
    return "4.1"  # Default

CURRENT_VERSION = _get_version()


def _parse_version(v: str) -> tuple:
    """'v2.3' or '2.3' or '2.3.0' → (2, 3, 0) (normalized)"""
    if not v or not isinstance(v, str):
        return (0, 0, 0)
    v = v.strip().lstrip("vV")
    # Take only numeric characters and dots
    v_clean = ""
    for char in v:
        if char.isdigit() or char == ".":
            v_clean += char
        else:
            break  # Stop at first non-digit character
    if not v_clean:
        return (0, 0, 0)
    parts = []
    for p in v_clean.split("."):
        try:
            num = int(p)
            if num < 0 or num > 999:  # Sensible version numbers
                return (0, 0, 0)
            parts.append(num)
        except ValueError:
            parts.append(0)
    # Normalize tuple: at least 3 elements (2, 3) → (2, 3, 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])  # Maximum 3 elements (major.minor.patch)


def _compare_versions(v1: tuple, v2: tuple) -> int:
    """
    Compares versions.
    Returns: -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2
    """
    # Both versions must be normalized tuples
    if v1 < v2:
        return -1
    elif v1 > v2:
        return 1
    else:
        return 0


def check_for_update() -> dict | None:
    """
    Checks for the latest version from GitHub Releases API.
    If a new version exists, returns a dict:
      {"version": "2.4", "download_url": "...", "size": 12345, "notes": "..."}
    Otherwise returns None.
    """
    try:
        resp = requests.get(GITHUB_API, timeout=8, headers={
            "Accept": "application/vnd.github.v3+json"
        })
        if resp.status_code != 200:
            return None

        data = resp.json()
        tag = data.get("tag_name", "")
        if not tag:
            return None
        
        latest = _parse_version(tag)
        current = _parse_version(CURRENT_VERSION)
        
        # If parsing fails, returns (0,0,0), ignore update in this case
        if latest == (0, 0, 0) or current == (0, 0, 0):
            return None

        # Compare versions - if equal or older, no update available
        if _compare_versions(latest, current) <= 0:
            return None

        # Find Setup EXE
        download_url = None
        file_size = 0
        for asset in data.get("assets", []):
            name = asset.get("name", "").lower()
            if "setup" in name and name.endswith(".exe"):
                download_url = asset.get("browser_download_url")
                file_size = asset.get("size", 0)
                break

        if not download_url:
            # If Setup missing, take any exe
            for asset in data.get("assets", []):
                if asset.get("name", "").lower().endswith(".exe"):
                    download_url = asset.get("browser_download_url")
                    file_size = asset.get("size", 0)
                    break

        if not download_url:
            return None

        # Clean version string
        version_str = tag.strip().lstrip("vV")
        # Take only numeric characters and dots
        version_clean = ""
        for char in version_str:
            if char.isdigit() or char == ".":
                version_clean += char
            else:
                break
        if not version_clean:
            version_clean = tag.lstrip("vV")
        
        return {
            "version": version_clean,
            "download_url": download_url,
            "size": file_size,
            "notes": data.get("body", ""),
            "filename": os.path.basename(download_url),
        }
    except Exception:
        return None


def download_update(url: str, on_progress=None) -> str | None:
    """
    Downloads update file.
    on_progress(downloaded_bytes, total_bytes) callback reports progress.
    Returns the path of the downloaded file.
    """
    try:
        resp = requests.get(url, stream=True, timeout=30)
        if resp.status_code != 200:
            return None

        total = int(resp.headers.get("content-length", 0))
        temp_dir = tempfile.gettempdir()
        filename = url.split("/")[-1]
        filepath = os.path.join(temp_dir, filename)

        downloaded = 0
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress and total > 0:
                        on_progress(downloaded, total)

        return filepath
    except Exception:
        return None


def apply_update(installer_path: str):
    """
    Runs the downloaded installer and closes the app.
    Inno Setup /SILENT flag performs silent update.
    """
    try:
        # Start installer via subprocess (safer)
        # /SILENT = silent install, /SP- = skip prompt
        subprocess.Popen(
            [installer_path, "/SILENT", "/SP-"],
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        # Add a short delay (for installer to start)
        time.sleep(1)
        # Close app (safe exit with try-except)
        try:
            sys.exit(0)
        except SystemExit:
            pass
        except Exception:
            # If sys.exit fails, use os._exit (more aggressive)
            os._exit(0)
    except Exception:
        # If subprocess fails, try with os.startfile
        try:
            os.startfile(installer_path)
            time.sleep(1)
            try:
                sys.exit(0)
            except SystemExit:
                pass
            except Exception:
                os._exit(0)
        except Exception:
            # Last resort: os._exit
            os._exit(0)

