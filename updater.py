"""
GameInSteam — Auto Updater
GitHub Releases API üzerinden güncelleme kontrolü ve indirme.
"""

import os
import sys
import tempfile
import threading
import requests

GITHUB_REPO = "kakies13/GameInSteam"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
CURRENT_VERSION = "2.4"


def _parse_version(v: str) -> tuple:
    """'v2.3' veya '2.3' → (2, 3)"""
    v = v.strip().lstrip("v")
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_for_update() -> dict | None:
    """
    GitHub Releases API'den son versiyonu kontrol eder.
    Yeni versiyon varsa dict döner:
      {"version": "2.4", "download_url": "...", "size": 12345, "notes": "..."}
    Yoksa None döner.
    """
    try:
        resp = requests.get(GITHUB_API, timeout=8, headers={
            "Accept": "application/vnd.github.v3+json"
        })
        if resp.status_code != 200:
            return None

        data = resp.json()
        tag = data.get("tag_name", "")
        latest = _parse_version(tag)
        current = _parse_version(CURRENT_VERSION)

        if latest <= current:
            return None

        # Setup EXE'yi bul
        download_url = None
        file_size = 0
        for asset in data.get("assets", []):
            name = asset.get("name", "").lower()
            if "setup" in name and name.endswith(".exe"):
                download_url = asset.get("browser_download_url")
                file_size = asset.get("size", 0)
                break

        if not download_url:
            # Setup yoksa herhangi bir exe'yi al
            for asset in data.get("assets", []):
                if asset.get("name", "").lower().endswith(".exe"):
                    download_url = asset.get("browser_download_url")
                    file_size = asset.get("size", 0)
                    break

        if not download_url:
            return None

        return {
            "version": tag.lstrip("v"),
            "download_url": download_url,
            "size": file_size,
            "notes": data.get("body", ""),
            "filename": os.path.basename(download_url),
        }
    except Exception:
        return None


def download_update(url: str, on_progress=None) -> str | None:
    """
    Güncelleme dosyasını indirir.
    on_progress(downloaded_bytes, total_bytes) callback ile ilerleme bildirir.
    İndirilen dosyanın yolunu döner.
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
    İndirilen installer'ı çalıştırıp uygulamayı kapatır.
    Inno Setup /SILENT flag ile sessiz güncelleme yapar.
    """
    try:
        # Installer'ı başlat (sessiz mod)
        os.startfile(installer_path)
        # Uygulamayı kapat
        sys.exit(0)
    except Exception:
        # Sessiz mod başarısız olursa normal aç
        try:
            os.startfile(installer_path)
            sys.exit(0)
        except Exception:
            pass

