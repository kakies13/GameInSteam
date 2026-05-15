import os
import sys
import glob
import time
import zipfile
import shutil
import subprocess
import tempfile
import requests

# --- AYARLAR ---
_DEFAULT_STEAM = r"C:\Program Files (x86)\Steam"
MIN_XINPUT_DLL_SIZE = 200_000
XINPUT_DLL_NAME = "xinput1_4.dll"


def get_steam_path() -> str:
    """Steam kurulum dizinini registry'den okur, yoksa varsayilan yolu kullanir."""
    try:
        import winreg

        candidates = (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        )
        for root, subkey in candidates:
            try:
                with winreg.OpenKey(root, subkey) as key:
                    path, _ = winreg.QueryValueEx(key, "InstallPath")
                    if path and os.path.isdir(path):
                        return path
            except OSError:
                continue
    except Exception:
        pass
    return _DEFAULT_STEAM


def get_stplugin_dir() -> str:
    return os.path.join(get_steam_path(), "config", "stplug-in")


def _bundled_xinput_path() -> str:
    """Paketlenmis veya gelistirme ortamindaki xinput1_4.dll yolunu dondurur."""
    if getattr(sys, "frozen", False):
        for base in (getattr(sys, "_MEIPASS", None), os.path.dirname(sys.executable)):
            if base:
                candidate = os.path.join(base, XINPUT_DLL_NAME)
                if os.path.isfile(candidate):
                    return candidate
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), XINPUT_DLL_NAME)


def install_stplugin_dll(force: bool = False) -> tuple[bool, str]:
    """
    xinput1_4.dll dosyasini Steam klasorune kopyalar (stplug-in sistemi).
    ISS kurulumu veya uygulama acilisinda otomatik cagrilir.
    """
    steam_path = get_steam_path()
    dest = os.path.join(steam_path, XINPUT_DLL_NAME)
    src = _bundled_xinput_path()

    if not os.path.isfile(src):
        return False, f"Bundled {XINPUT_DLL_NAME} not found in application files."

    if os.path.isfile(dest) and not force:
        try:
            if os.path.getsize(dest) > MIN_XINPUT_DLL_SIZE:
                return True, f"{XINPUT_DLL_NAME} already installed in Steam."
        except OSError:
            pass

    try:
        shutil.copy2(src, dest)
        size = os.path.getsize(dest)
        return True, f"{XINPUT_DLL_NAME} installed to Steam ({size:,} bytes)."
    except PermissionError:
        return False, (
            f"Could not write to {dest}.\n"
            "Run GameInSteam as Administrator or reinstall with the setup installer."
        )
    except Exception as e:
        return False, f"Failed to install {XINPUT_DLL_NAME}: {e}"

STEAM_API_URL = "https://store.steampowered.com/api/appdetails"
GAMELIST_BASE_URL = "https://raw.githubusercontent.com/kakies13/gamelist/main"


# =============================================================================
# 1. MODÜL: SİSTEM KONTROLÜ
# =============================================================================
def check_stplugin_system():
    """Checks if the stplug-in system is installed."""
    dll_path = os.path.join(get_steam_path(), XINPUT_DLL_NAME)
    if os.path.isfile(dll_path):
        size = os.path.getsize(dll_path)
        if size > MIN_XINPUT_DLL_SIZE:
            return True, f"System active! {XINPUT_DLL_NAME} exists ({size:,} bytes)."
        return False, (
            f"{XINPUT_DLL_NAME} exists but looks like the system version.\n"
            "Reinstall GameInSteam or run as Administrator to replace it."
        )
    return False, (
        f"{XINPUT_DLL_NAME} not found in Steam folder!\n"
        "Restart GameInSteam or reinstall the setup to install it automatically."
    )


def setup_dirs():
    """stplug-in dizinini oluşturur."""
    os.makedirs(get_stplugin_dir(), exist_ok=True)


# =============================================================================
# 2. MODÜL: ÖNBELLEK TEMİZLEYİCİ
# =============================================================================
def clear_steam_cache():
    """Steam'in eski lisans verilerini zorla yenilemesi için cache temizler."""
    cache_path = os.path.join(get_steam_path(), "appcache")
    if os.path.exists(cache_path):
        try:
            shutil.rmtree(cache_path)
            print("🧹 Steam cache (appcache) cleared.")
        except Exception as e:
            print(f"⚠️ Could not clear cache: {e}")


# =============================================================================
# 3. MODÜL: GAMELİST REPO İNDİRİCİ
# =============================================================================
def download_from_gamelist(app_id):
    """
    kakies13/gamelist reposundan AppID'ye ait zip dosyasını indirir,
    içindeki lua dosyasını doğrudan stplug-in dizinine yerleştirir.

    Returns: lua_path veya None
    """
    setup_dirs()
    zip_url = f"{GAMELIST_BASE_URL}/{app_id}.zip"
    lua_dest = os.path.join(get_stplugin_dir(), f"{app_id}.lua")

    print(f"  📥 Downloading AppID {app_id} from gamelist repo...")

    try:
        resp = requests.get(zip_url, timeout=15)
        if resp.status_code != 200:
            print(f"  ❌ AppID {app_id} not found in gamelist repo (HTTP {resp.status_code}).")
            return None

        zip_bytes = resp.content

        if zip_bytes[:2] != b"PK":
            print(f"  ❌ Response is not a valid ZIP file.")
            return None

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(zip_bytes)
            tmp_path = tmp.name

        try:
            with zipfile.ZipFile(tmp_path, "r") as z:
                lua_found = False
                for name in z.namelist():
                    if name.lower().endswith(".lua") and "readme" not in name.lower():
                        lua_data = z.read(name)
                        with open(lua_dest, "wb") as f:
                            f.write(lua_data)
                        lua_found = True
                        print(f"  ✅ Lua extracted → stplug-in/{app_id}.lua")
                        break

                if not lua_found:
                    print(f"  ❌ No lua file found inside zip.")
                    return None
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

        return lua_dest

    except Exception as e:
        print(f"  ⚠️ Gamelist error: {type(e).__name__}: {e}")
        return None


# =============================================================================
# 4. MODÜL: STEAM YENİDEN BAŞLATMA
# =============================================================================
def restart_steam():
    """Steam'i kapatıp yeniden başlatır."""
    steam_exe = os.path.join(get_steam_path(), "steam.exe")

    print("\n🔄 Restarting Steam...")
    subprocess.run(
        ["taskkill", "/F", "/IM", "steam.exe"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(4)

    clear_steam_cache()

    if os.path.isfile(steam_exe):
        print("🚀 Starting Steam...")
        subprocess.Popen([steam_exe])
        time.sleep(10)
        print("✅ Steam started.")
        return True
    else:
        print("❌ Steam.exe not found!")
        return False


# =============================================================================
# 5. MODÜL: ANA AKIŞ
# =============================================================================
def add_shortcut_from_manifest(app_id, app_name, on_progress=None, auto_restart=False):
    """
    Oyunu Steam kütüphanesine ekler.

    AKIŞ:
    1. Gamelist repodan zip indir → lua'yı stplug-in'e koy
    2. Steam'i yeniden başlat (isteğe bağlı)

    on_progress: callable(pct: float, msg: str)
    auto_restart: bool
    """
    def _prog(pct, msg=""):
        if on_progress:
            on_progress(pct, msg)

    _prog(0.05, "Checking system...")
    install_stplugin_dll()
    system_ok, system_msg = check_stplugin_system()
    if not system_ok:
        print(f"⚠️ {system_msg}")
    else:
        print(f"✅ {system_msg}")

    _prog(0.20, f"Downloading AppID {app_id} from gamelist repo...")
    lua_path = download_from_gamelist(app_id)

    if not lua_path:
        return False, (
            f"{app_id}: Lua file could not be downloaded!\n\n"
            "This AppID was not found in the gamelist repo.\n\n"
            "Possible reasons:\n"
            "• This game hasn't been added to the gamelist repo yet\n"
            "• No internet connection\n"
            "• Invalid App ID\n\n"
            "Solution:\n"
            "1. Check your internet connection\n"
            "2. Verify the App ID is correct\n"
            "3. Request this game to be added to the gamelist repo"
        )

    _prog(0.70, "Cleaning up...")

    old_acf = os.path.join(get_steam_path(), "steamapps", f"appmanifest_{app_id}.acf")
    if os.path.isfile(old_acf):
        try:
            os.remove(old_acf)
            print(f"🧹 Old ACF manifest deleted.")
        except Exception:
            pass

    print(f"\n📊 Result: Lua ✅ | Source: Gamelist Repo")

    if auto_restart:
        _prog(0.75, "Restarting Steam...")
        steam_started = restart_steam()
        _prog(0.95, "Steam started, waiting...")
        if not steam_started:
            return False, "Steam.exe not found!"
    else:
        print("  ℹ️ Manual restart selected.")
        _prog(0.85, "Done! Please restart Steam manually.")

    if system_ok:
        return True, (
            f"'{app_name}' (AppID: {app_id}) successfully added!\n"
            f"Source: Gamelist Repo\n"
            f"Lua: stplug-in/{app_id}.lua ✅\n\n"
            f"Please restart Steam to see it in your library."
        )
    else:
        return True, (
            f"Files placed but {XINPUT_DLL_NAME} is missing!\n\n"
            f"Reinstall GameInSteam setup or restart the app as Administrator.\n"
            f"Then restart Steam."
        )


# =============================================================================
# 6. MODÜL: OYUN YÖNETİMİ
# =============================================================================
def get_game_name_from_steam(app_id):
    """Steam Store API'den oyun adını çeker."""
    try:
        resp = requests.get(
            STEAM_API_URL,
            params={"appids": str(app_id), "filters": "basic"},
            timeout=8,
        )
        data = resp.json()
        app_data = data.get(str(app_id), {})
        if app_data.get("success") and "data" in app_data:
            return app_data["data"].get("name", "")
    except Exception:
        pass
    return ""


def list_added_games():
    """
    stplug-in dizinindeki lua dosyalarını tarayarak eklenmiş oyunları listeler.

    Returns: list of dict with keys: app_id, mtime
    """
    games = []
    stplugin_dir = get_stplugin_dir()
    if not os.path.isdir(stplugin_dir):
        return games

    for lua_file in sorted(glob.glob(os.path.join(stplugin_dir, "*.lua"))):
        name_part = os.path.splitext(os.path.basename(lua_file))[0]
        if not name_part.isdigit():
            continue
        games.append({
            "app_id": name_part,
            "mtime": os.path.getmtime(lua_file),
        })

    return games


def list_recent_games(limit: int = 20):
    """
    En son eklenen oyunları mtime'a göre sıralı döner.

    Returns: list of dict (en yeni → en eski)
    """
    games = list_added_games()
    games.sort(key=lambda g: g.get("mtime", 0), reverse=True)
    return games[:limit]


def remove_game(app_id):
    """
    Oyunu stplug-in sisteminden kaldırır.

    Returns: (success: bool, message: str)
    """
    app_id = str(app_id)
    removed = []

    lua_path = os.path.join(get_stplugin_dir(), f"{app_id}.lua")
    if os.path.isfile(lua_path):
        os.remove(lua_path)
        removed.append(f"stplug-in/{app_id}.lua")

    acf_path = os.path.join(get_steam_path(), "steamapps", f"appmanifest_{app_id}.acf")
    if os.path.isfile(acf_path):
        os.remove(acf_path)
        removed.append(f"appmanifest_{app_id}.acf")

    if removed:
        print(f"🗑️ Deleted files: {', '.join(removed)}")
        return True, f"AppID {app_id} removed.\nDeleted: {len(removed)} files."
    else:
        return False, f"No files found to delete for AppID {app_id}."


def is_game_in_repo(app_id: str) -> bool:
    """
    AppID'nin gamelist repoda olup olmadığını hızlıca kontrol eder (HEAD isteği).
    Hata durumunda True döner (kullanıcıyı engelleme).
    """
    try:
        resp = requests.head(
            f"{GAMELIST_BASE_URL}/{app_id}.zip",
            timeout=6,
        )
        return resp.status_code == 200
    except Exception:
        return True  # İnternet yoksa engelleme, denemeye bırak


def get_gamelist_repo_games():
    """
    kakies13/gamelist reposundaki mevcut tüm oyunları listeler.
    GitHub Contents API'den zip dosya adlarını çeker ve AppID'leri döner.

    Returns: list of str (app_id'ler) veya boş liste
    """
    try:
        resp = requests.get(
            "https://api.github.com/repos/kakies13/gamelist/contents",
            timeout=15,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        if resp.status_code != 200:
            print(f"⚠️ Gamelist API error: HTTP {resp.status_code}")
            return []
        data = resp.json()
        app_ids = []
        for item in data:
            name = item.get("name", "")
            if name.endswith(".zip"):
                app_id = name[:-4]
                if app_id.isdigit():
                    app_ids.append(app_id)
        return sorted(app_ids, key=lambda x: int(x))
    except Exception as e:
        print(f"⚠️ Gamelist repo fetch error: {type(e).__name__}: {e}")
        return []


def update_game(app_id):
    """
    Oyunun lua dosyasını gamelist repodan yeniler.

    Returns: (success: bool, message: str)
    """
    app_id = str(app_id)
    print(f"🔄 Updating AppID {app_id}...")

    old_lua = os.path.join(get_stplugin_dir(), f"{app_id}.lua")
    if os.path.isfile(old_lua):
        os.remove(old_lua)
        print(f"  🧹 Old lua deleted.")

    lua_path = download_from_gamelist(app_id)

    if lua_path:
        print(f"✅ Update completed!")
        return True, f"AppID {app_id} updated.\nSource: Gamelist Repo"
    else:
        return False, (
            f"AppID {app_id} could not be updated!\n"
            "Not found in gamelist repo."
        )
