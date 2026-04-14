import os
import re
import time
import zipfile
import shutil
import subprocess
import tempfile
import requests
import concurrent.futures
import traceback
from steam.client import SteamClient
from steam.enums import EResult

# Selenium artık kullanılmıyor — GitHub tabanlı indirme sistemi kullanılıyor
SELENIUM_AVAILABLE = False
CHROME_DRIVER_MANAGER_AVAILABLE = False

# --- AYARLAR ---
STEAM_PATH = r"C:\Program Files (x86)\Steam"
TARGET_DOWNLOAD_DIR = r"C:\Users\Startklar\Desktop\lualua"

# Doğru dizin yapısı (Toprak Steam Cracker analizi ile doğrulandı):
# - Lua dosyaları → Steam/config/stplug-in/
# - Manifest dosyaları → Steam/config/depotcache/
# - xinput1_4.dll → Steam/ (proxy DLL - stplug-in lua'ları otomatik yükler)
STPLUGIN_DIR = os.path.join(STEAM_PATH, "config", "stplug-in")
DEPOTCACHE_DIR = os.path.join(STEAM_PATH, "config", "depotcache")

# Steam Store API (ücretsiz, key gerektirmez)
STEAM_API_URL = "https://store.steampowered.com/api/appdetails"


# =============================================================================
# 1. MODÜL: SİSTEM KONTROLÜ
# =============================================================================
def check_stplugin_system():
    """Checks if the stplug-in system is installed."""
    dll_path = os.path.join(STEAM_PATH, "xinput1_4.dll")
    if os.path.isfile(dll_path):
        size = os.path.getsize(dll_path)
        if size > 200000:
            return True, f"System active! xinput1_4.dll exists ({size:,} bytes)."
        else:
            return False, (
                "xinput1_4.dll exists but looks like the system version.\n"
                "Click the 'Download xinput1_4.dll' button in Toprak Steam Cracker."
            )
    return False, (
        "xinput1_4.dll not found!\n"
        "Open Toprak Steam Cracker and click the\n"
        "'Download xinput1_4.dll' button in the top right."
    )


def open_steam_folder(folder_type="stplugin"):
    """Steam dizinlerini dosya gezgininde açar."""
    path = STPLUGIN_DIR if folder_type == "stplugin" else DEPOTCACHE_DIR
    if os.path.isdir(path):
        os.startfile(path)
    else:
        os.makedirs(path, exist_ok=True)
        os.startfile(path)


def open_downloads_folder():
    """İndirme dizinini dosya gezgininde açar."""
    if not os.path.isdir(TARGET_DOWNLOAD_DIR):
        os.makedirs(TARGET_DOWNLOAD_DIR, exist_ok=True)
    os.startfile(TARGET_DOWNLOAD_DIR)


def setup_dirs():
    """stplug-in ve depotcache dizinlerini oluşturur."""
    os.makedirs(STPLUGIN_DIR, exist_ok=True)
    os.makedirs(DEPOTCACHE_DIR, exist_ok=True)


# =============================================================================
# 2. MODÜL: ÖNBELLEK TEMİZLEYİCİ
# =============================================================================
def clear_steam_cache():
    """Steam'in eski lisans verilerini zorla yenilemesi için cache temizler."""
    cache_path = os.path.join(STEAM_PATH, "appcache")
    if os.path.exists(cache_path):
        try:
            shutil.rmtree(cache_path)
            print("🧹 Steam cache (appcache) cleared.")
        except Exception as e:
            print(f"⚠️ Could not clear cache: {e}")


# =============================================================================
# 3. MODÜL: DOSYA DOĞRULAMA (Cloudflare HTML koruması)
# =============================================================================
def _validate_downloaded_file(file_path):
    """
    İndirilen dosyanın gerçekten lua/zip olup olmadığını doğrular.
    Cloudflare bazen HTML challenge sayfası döner — bunu yakalar.
    Bozuk dosya stplug-in'e yerleştirilirse Steam çöker!
    
    Dosya adı kontrolü: "plugin" içeren dosyalar reddedilir (yanlış indirme)
    """
    try:
        size = os.path.getsize(file_path)
        if size < 50:
            return False
        
        # Dosya adı kontrolü - "plugin" içeren dosyalar reddedilir
        file_name = os.path.basename(file_path).lower()
        if "plugin" in file_name:
            print(f"  ⚠️ Filename contains 'plugin', it might be a wrong download: {os.path.basename(file_path)}")
            return False
        
        with open(file_path, "rb") as f:
            header = f.read(200)
        
        # ZIP dosyası mı? (PK magic bytes)
        if header[:2] == b"PK":
            return True
        
        # HTML/Cloudflare engellemesi mi?
        text = header.decode("utf-8", errors="ignore").lower()
        html_markers = ["<!doctype", "<html", "cloudflare", "just a moment", "cf-chl"]
        for marker in html_markers:
            if marker in text:
                return False
        
        # Lua dosyası mı? (yorum veya addappid ile başlamalı)
        lua_markers = ["addappid", "setmanifestid", "--"]
        for marker in lua_markers:
            if marker in text:
                return True
        
        # Bilinmeyen içerik — güvenli tarafta kal
        return False
    except Exception:
        return False


# =============================================================================
# 6. MODÜL: ÇOKLU KAYNAK İNDİRİCİ
# =============================================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
}

# SSMGAlt/ManifestHub2: Tüm depot key'leri tek JSON'da tutuyor (branch yapısı yok)
MANIFESTHUB2_DEPOTKEYS_URL = "https://raw.githubusercontent.com/SSMGAlt/ManifestHub2/main/depotkeys.json"
MANIFESTHUB2_TOKENS_URL   = "https://raw.githubusercontent.com/SSMGAlt/ManifestHub2/main/appaccesstokens.json"

# Önbellek — her çalıştırmada bir kez indir
_manifesthub2_depotkeys_cache = None
_manifesthub2_tokens_cache    = None


def _load_manifesthub2_data():
    """SSMGAlt/ManifestHub2 depotkeys + appaccesstokens JSON'larını bir kez yükler."""
    global _manifesthub2_depotkeys_cache, _manifesthub2_tokens_cache
    if _manifesthub2_depotkeys_cache is None:
        try:
            print("  📥 Loading ManifestHub2 depot keys...")
            r = requests.get(MANIFESTHUB2_DEPOTKEYS_URL, timeout=15, headers=HEADERS)
            if r.status_code == 200:
                _manifesthub2_depotkeys_cache = r.json()
                print(f"  ✅ ManifestHub2: {len(_manifesthub2_depotkeys_cache)} depot keys loaded")
            else:
                print(f"  ❌ ManifestHub2 depotkeys HTTP {r.status_code}")
                _manifesthub2_depotkeys_cache = {}
        except Exception as e:
            print(f"  ⚠️ ManifestHub2 load error: {e}")
            _manifesthub2_depotkeys_cache = {}
    if _manifesthub2_tokens_cache is None:
        try:
            r = requests.get(MANIFESTHUB2_TOKENS_URL, timeout=15, headers=HEADERS)
            _manifesthub2_tokens_cache = r.json() if r.status_code == 200 else {}
        except Exception:
            _manifesthub2_tokens_cache = {}
    return _manifesthub2_depotkeys_cache, _manifesthub2_tokens_cache


def _build_lua_from_manifesthub2(app_id):
    """
    SSMGAlt/ManifestHub2 branch sisteminden LUA içeriği üretir.
    Mapping logic:
    1. https://raw.githubusercontent.com/SSMGAlt/ManifestHub2/[AppID]/[AppID].json -> Depot listesi
    2. DepotIDs -> depotkeys.json (root) -> Decryption Keys
    3. AppID -> appaccesstokens.json (root) -> Access Token
    """
    app_id_str = str(app_id)
    depot_keys, access_tokens = _load_manifesthub2_data()
    
    matching_depots = {}
    
    # 1. Deneme: Orijinal AppID key'i (eğer flat formatta ise)
    if app_id_str in depot_keys and isinstance(depot_keys[app_id_str], dict):
        matching_depots = depot_keys[app_id_str]
    
    # 2. Deneme: Branch bazlı mapping dosyasını çek
    if not matching_depots:
        print(f"  🔍 Fetching branch mapping for AppID {app_id}...")
        branch_url = f"https://raw.githubusercontent.com/SSMGAlt/ManifestHub2/{app_id}/{app_id}.json"
        try:
            r = requests.get(branch_url, timeout=10, headers=HEADERS)
            if r.status_code == 200:
                app_info = r.json()
                # App info içindeki "depots" veya filenames
                depots_section = app_info.get("depots", {})
                if not depots_section:
                    # Fallback: "depot" section'ı ara
                    common = app_info.get("common", {})
                    # Genelde app_info JSON'larında root seviyesindedir
                
                # Basitçe tüm depot_keys içindeki Key'leri bu AppID'nin branch dosyasından bulmaya çalışmıyoruz,
                # çünkü depot_keys zaten elimizde. Sadece HANGİ depotların bu app'e ait olduğunu bilmeliyiz.
                # app_info["depots"] içindeki ID'leri al:
                depot_list = []
                if isinstance(depots_section, dict):
                    depot_list = list(depots_section.keys())
                
                for did in depot_list:
                    if did in depot_keys:
                        matching_depots[did] = depot_keys[did]
        except Exception as e:
            print(f"  ⚠️ Branch mapping fetch error: {e}")

    # 3. Deneme: Heuristic (± 200 range) - Son çare
    if not matching_depots:
        try:
            app_id_int = int(app_id)
            for k, v in depot_keys.items():
                try:
                    k_int = int(k)
                    if abs(k_int - app_id_int) <= 200:
                        matching_depots[k] = v
                except: pass
        except: pass

    if not matching_depots:
        print(f"  ❌ ManifestHub2: No depot keys found for AppID {app_id}")
        return None

    # LUA oluştur
    access_token = access_tokens.get(app_id_str, "0")
    lines = [f"addappid({app_id}, 1, \"{access_token}\")"]
    for d_id, d_key in matching_depots.items():
        if d_key and d_key != "0":
            lines.append(f"addappid({d_id}, 0, \"{d_key}\")")

    if len(lines) <= 1:
        return None

    print(f"  ✅ ManifestHub2: LUA generated with {len(lines)-1} depots.")
    return "\n".join(lines) + "\n"


def download_from_steam_local(app_id):
    """
    SteamKit mantığı: Anonim olarak Steam sunucularına bağlanır ve ManifestID'leri çeker.
    Returns: (lua_path, manifest_count)
    """
    client = SteamClient()
    print(f"  📡 Connecting to Steam (Anonymous)...")
    
    if client.anonymous_login() != EResult.OK:
        print("  ❌ Could not connect to Steam anonymously.")
        return None, 0

    try:
        print(f"  🔍 Querying Product Info for AppID {app_id}...")
        # Get product info (AppInfo + DepotInfo)
        product_info = client.get_product_info(apps=[int(app_id)])
        if not product_info or 'apps' not in product_info or int(app_id) not in product_info['apps']:
            print(f"  ❌ AppID {app_id} not found on Steam (or restricted).")
            return None, 0

        app_data = product_info['apps'][int(app_id)]
        depots = app_data.get('depots', {})
        
        # LUA içeriği oluştur
        lua_lines = [f'addappid({app_id}, 1, "0") -- Local Generated']
        manifest_count = 0
        
        for d_id, d_data in depots.items():
            if not d_id.isdigit(): continue
            
            # ManifestID bul (config veya manifests altından)
            manifest_id = "0"
            if 'manifests' in d_data:
                # Genelde 'public' veya 'external' branch kullanılır
                m_list = d_data['manifests']
                manifest_id = m_list.get('public', m_list.get(next(iter(m_list)))) if m_list else "0"
            
            if manifest_id != "0":
                manifest_count += 1
                # Local fetch'te key'leri anonim olarak alamayız, bu yüzden 0 bırakıyoruz
                # Ancak ManifestID'yi setmanifestid olarak yorum satırına veya loga ekleyebiliriz
                lua_lines.append(f'-- setmanifestid({d_id}, {manifest_id})')
                lua_lines.append(f'addappid({d_id}, 0, "0")')

        if manifest_count == 0:
            print(f"  ⚠️ No manifests found for AppID {app_id} in local query.")
            return None, 0

        lua_name = f"{app_id}.lua"
        lua_dest = os.path.join(STPLUGIN_DIR, lua_name)
        with open(lua_dest, "w", encoding="utf-8") as f:
            f.write("\n".join(lua_lines) + "\n")
            
        print(f"  ✅ Local Fetch: LUA generated with {manifest_count} depots (IDs verified).")
        return lua_dest, manifest_count

    except Exception as e:
        print(f"  ⚠️ Local fetch error: {e}")
        return None, 0
    finally:
        client.disconnect()


def download_from_manifesthub(app_id):
    """
    Birden fazla kaynağı sırayla deneyerek LUA + manifest dosyalarını indirir.
    Chrome/Selenium gerektirmez — sadece requests kullanır.

    Kaynak sırası:
    1. SSMGAlt/ManifestHub2 (orijinal ManifestHub'ın fork'u, aktif)
    2. Manuel Destek / Topluluk Kaynakları (fallback)

    Returns: (lua_path, manifest_count) veya (None, 0)
    """
    setup_dirs()
    app_id_str = str(app_id)
    lua_name = f"{app_id_str}.lua"
    lua_dest = os.path.join(STPLUGIN_DIR, lua_name)

    # ── KAYNAK 1: SSMGAlt/ManifestHub2 (JSON tabanlı) ──────────────────────
    print(f"  🚀 [1/1] Trying ManifestHub2 (SSMGAlt) for AppID {app_id}...")
    lua_content = _build_lua_from_manifesthub2(app_id)
    if lua_content:
        with open(lua_dest, "w", encoding="utf-8") as f:
            f.write(lua_content)
        print(f"  ✅ LUA written: {lua_name}")
        return lua_dest, 0  # .manifest dosyaları için manuel kaynaklar önerilir

    print(f"  ❌ GitHub sources (SSMGAlt) could not find AppID {app_id}")
    print(f"  💡 İpucu: Eğer otomatik bulunamazsa şu kaynaklara göz atın:")
    print(f"     - https://manifestlua.blog/")
    print(f"     - Toprak Steam Discord/Telegram grupları")
    
    return None, 0


# =============================================================================
# 7. MODÜL: KERNELOS (KALDIRILDI — GitHub kaynakları kullanılıyor)
# =============================================================================
def download_from_kernelos_selenium(app_id, target_dir):
    """
    Bu fonksiyon artık kullanılmıyor.
    Kernelos.org Selenium indirmesi kaldırıldı; yerine download_from_manifesthub()
    birden fazla GitHub kaynağını otomatik dener.
    """
    print("  ℹ️ Kernelos Selenium devre dışı — GitHub kaynakları kullanılıyor.")
    return None


def _kill_zombie_chrome():
    """Artık gerekli değil — Chrome kullanılmıyor."""
    pass
    """
    kernelos.org/games/ sayfasından dosya indirir — BASİT YAKLAŞIM.
    
    Toprak Steam Cracker mantığı:
    1. Sayfayı aç → AppID gir → Get link → Download butonunu bul
    2. Download linkini (href) al
    3. requests ile indir → zip/lua dosyasını kaydet
    4. Bitir
    
    Returns: dosya yolu veya None
    """
    if not SELENIUM_AVAILABLE:
        print("❌ Selenium not installed!")
        return None
    
    # Check Chrome first
    print(f"  🔍 Checking Chrome...")
    chrome_installed, chrome_path, chrome_error = check_chrome_installed()
    if not chrome_installed:
        print(f"  ❌ {chrome_error}")
        return "CHROME_NOT_INSTALLED"
    print(f"  ✅ Chrome found: {chrome_path}")
    
    os.makedirs(target_dir, exist_ok=True)
    before_files = set(os.listdir(target_dir))  # İndirme öncesi dosyalar
    
    # Create Chrome driver
    print(f"  ⏳ Starting Chrome driver...")
    try:
        driver, temp_profile = _create_chrome_driver(target_dir)
        if driver is None:
            print("  ❌ Failed to start Chrome driver!")
            print("  💡 Solution: Update Chrome or restart your browser")
            return "CHROME_DRIVER_ERROR"
    except Exception as driver_error:
        print(f"  ❌ Chrome driver error: {type(driver_error).__name__}")
        print(f"  📝 Detail: {str(driver_error)[:200]}")
        print("  💡 Solution: Update Chrome or restart your computer")
        return "CHROME_DRIVER_ERROR"
    
    try:
        # 1. Open page
        print(f"  🌐 Opening kernelos.org/games/...")
        try:
            driver.get("https://kernelos.org/games/")
            print(f"  ✅ Page loaded (or loading in background)")
        except Exception as page_error:
            if "Timeout" in type(page_error).__name__:
                print(f"  ⚠️ Page load timeout, but continuing...")
            else:
                print(f"  ❌ Page open error: {type(page_error).__name__}")
                return None
        
        # Wait for page load
        print(f"  ⏳ Page loading, waiting for input field...")
        time.sleep(1)  # Dengeli bekleme
        input_box = None
        
        # Try different selectors
        selectors = [
            "input[type='text']",
            "input[type='number']",
            "input[placeholder*='AppID' i]",
            "input[placeholder*='appid' i]",
            "input:not([type='hidden']):not([type='submit']):not([type='button'])",
            "input",
        ]
        
        for selector in selectors:
            try:
                input_box = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                print(f"  ✅ Input field found: {selector}")
                break
            except Exception as e:
                continue
        
        if not input_box:
            print(f"  ❌ Input field not found! Page might not have loaded.")
            # Debug
            try:
                page_source_preview = driver.page_source[:200] if driver.page_source else "Empty"
                print(f"  📄 Page source preview: {page_source_preview}")
            except Exception:
                pass
            return None
        
        # 2. Enter AppID
        
        input_box.clear()
        input_box.send_keys(str(app_id))
        print(f"  ✍️ AppID entered: {app_id}")
        
        # 3. Click "Get link" button
        print(f"  🔍 Searching for 'Get link' button...")
        get_link_btn = None
        for attempt in range(5):
            try:
                get_link_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Get link')]"))
                )
                print(f"  ✅ 'Get link' button found")
                break
            except Exception:
                if attempt < 4:
                    print(f"  ⏳ Waiting for 'Get link' button... ({attempt + 1}/5)")
                    time.sleep(1)
                else:
                    print(f"  ❌ 'Get link' button not found!")
                    return None
        
        if not get_link_btn:
            return None
        
        driver.execute_script("arguments[0].click();", get_link_btn)
        print(f"  🔗 Clicked 'Get link' button...")
        
        # 4. Wait for "Ready..." message
        print(f"  ⏳ Preparing file, waiting...")
        time.sleep(1.5)
        ready_found = False
        for i in range(25):
            page_text = driver.page_source.lower()
            if "ready" in page_text or "download" in page_text or "open link" in page_text:
                ready_found = True
                print(f"  ✅ File ready!")
                break
            if i % 5 == 0 and i > 0:
                print(f"  ⏳ Still waiting... ({i*0.5:.0f}s)")
            time.sleep(0.5)
        
        if not ready_found:
            print(f"  ⚠️ 'Ready' message not found, continuing...")
        
        # 5. Find "Open link" button below "Get link" (don't use Download button)
        time.sleep(1)
        open_link_btn = None
        download_href = None
        
        print(f"  🔍 Searching for 'Open link' button...")
        for attempt in range(25):
            # Tüm butonları ve linkleri bul
            all_elements = driver.find_elements(By.CSS_SELECTOR, "button, a")
            
            # Sadece "Open link" butonlarını bul (Download butonunu kullanma)
            open_link_candidates = []
            
            for el in all_elements:
                try:
                    text = (el.text or "").strip().lower()
                    y_pos = el.location.get("y", 0) + el.size.get("height", 0)
                    # href'i bul (attribute veya onclick'ten)
                    href = el.get_attribute("href")
                    if not href:
                        # onclick'ten href çıkar
                        onclick = el.get_attribute("onclick") or ""
                        if "window.open" in onclick or "location.href" in onclick:
                            import re
                            match = re.search(r"['\"](https?://[^'\"]+)['\"]", onclick)
                            if match:
                                href = match.group(1)
                    
                    # Sadece "Open link" butonunu kullan (Download butonunu atla)
                    if "open link" in text:
                        open_link_candidates.append((y_pos, el, href))
                except Exception:
                    continue
            
            # Find "Open link" button (bottom one)
            if open_link_candidates:
                open_link_candidates.sort(key=lambda x: x[0], reverse=True)
                open_link_btn = open_link_candidates[0][1]
                download_href = open_link_candidates[0][2]
                print(f"  ✅ 'Open link' button found (href: {'available' if download_href else 'none'})")
                break
            
            # Log every 5 attempts
            if attempt % 5 == 0 and attempt > 0:
                print(f"  ⏳ Searching for 'Open link' button... ({attempt}/25)")
            
            time.sleep(0.5)
        
        if not open_link_btn:
            print("  ❌ 'Open link' button not found!")
            # Debug
            try:
                page_text = driver.page_source[:500]
                print(f"  📄 Page content (first 500 chars): {page_text}")
            except Exception:
                pass
            return None
        
        # 6. Download method: requests if href, else browser download
        if download_href and download_href.startswith("http"):
            # Anchor link check
            if "#" in download_href and not download_href.endswith((".zip", ".lua")):
                print(f"  ⚠️ Anchor link detected, switching to browser download...")
                download_href = None
            else:
                print(f"  📥 Download link found, downloading via requests...")
                session = requests.Session()
                
                # Cookie'leri aktar
                for cookie in driver.get_cookies():
                    session.cookies.set(cookie["name"], cookie["value"])
                
                # Cloudflare bypass için header'lar
                headers = {
                    'User-Agent': driver.execute_script("return navigator.userAgent;"),
                    'Referer': 'https://kernelos.org/games/',
                    'Accept': 'application/octet-stream, application/zip, */*',
                }
                
                try:
                    res = session.get(download_href, stream=True, timeout=30, headers=headers)
                    res.raise_for_status()
                    
                    # Content-Type kontrolü
                    ct = res.headers.get("Content-Type", "").lower()
                    content_length = int(res.headers.get("Content-Length", "0") or "0")
                    print(f"  📊 Content-Type: {ct}, Size: {content_length:,} bytes")
                    
                    # If not HTML, download
                    if "text/html" not in ct:
                        # Determine extension
                        ext = ".zip" if "zip" in ct or "application/zip" in ct else ".lua"
                        fp = os.path.join(target_dir, f"{app_id}{ext}")
                        
                        # Save file
                        with open(fp, "wb") as f:
                            for chunk in res.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        
                        file_size = os.path.getsize(fp)
                        print(f"  💾 File saved: {os.path.basename(fp)} ({file_size:,} bytes)")
                        
                        # Validate
                        if _validate_downloaded_file(fp):
                            print(f"  ✅ File valid: {os.path.basename(fp)}")
                            return fp
                        else:
                            os.remove(fp)
                            print("  ❌ Downloaded file invalid, switching to browser download...")
                            download_href = None
                    else:
                        print("  ⚠️ Link redirects to HTML page, switching to browser download...")
                        download_href = None
                except Exception as e:
                    print(f"  ⚠️ Download via requests failed: {type(e).__name__}, switching to browser download...")
                    download_href = None
        
        # Try browser download if requests failed or no href
        if not download_href:
            print(f"  🖱️ Clicking 'Open link' button (browser download)...")
            try:
                driver.execute_script("arguments[0].click();", open_link_btn)
                print(f"  ✅ Clicked 'Open link' button, waiting for download...")
                time.sleep(1.5)
                
                # Wait for download to complete
                download_started = False
                for i in range(70):
                    time.sleep(0.5)
                    current_files = set(os.listdir(target_dir))
                    new_files = current_files - before_files
                    
                    # Check if downloading (.crdownload, .tmp)
                    downloading = [f for f in new_files if f.endswith((".crdownload", ".tmp", ".part"))]
                    if downloading:
                        download_started = True
                        if i % 20 == 0:
                            print(f"  ⏳ Download in progress... ({i*0.5:.0f}s)")
                        continue
                    
                    # Check completed files
                    completed = [f for f in new_files if not f.endswith((".tmp", ".crdownload", ".part"))]
                    for f in completed:
                        fpath = os.path.join(target_dir, f)
                        try:
                            file_size = os.path.getsize(fpath)
                            print(f"  💾 Downloaded: {f} ({file_size:,} bytes)")
                            
                            # Validate
                            if _validate_downloaded_file(fpath):
                                print(f"  ✅ File valid: {f}")
                                return fpath
                            else:
                                print(f"  ⚠️ File invalid (HTML/Cloudflare?), deleting...")
                                os.remove(fpath)
                        except Exception as e:
                            print(f"  ⚠️ File check error: {type(e).__name__}")
                            continue
                    
                    if download_started and not downloading and completed:
                        break
                
                if not download_started:
                    print("  ❌ Download didn't start! Button might not be working.")
                else:
                    print("  ❌ Download timed out!")
                return None
            except Exception as e:
                print(f"  ❌ Browser download failed: {type(e).__name__}: {e}")
                return None
    
    except Exception as e:
        print(f"  ❌ Error: {type(e).__name__}: {e}")
        return None
    
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass
        time.sleep(0.1)  # 0.3'ten 0.1'e düşürüldü
        if temp_profile:
            try:
                shutil.rmtree(temp_profile, ignore_errors=True)
            except Exception:
                pass
        _kill_zombie_chrome()
    
    return None


# =============================================================================
# 7. MODÜL: DOSYA YERLEŞTİRME (Toprak Steam Cracker mantığı)
# =============================================================================
def place_game_files(file_path, app_id):
    """
    İndirilen dosyaları doğru Steam dizinlerine yerleştirir.
    
    Toprak Steam Cracker analizi ile doğrulanmış yapı:
    - .lua dosyaları → Steam/config/stplug-in/   (addappid formatı, DÖNÜŞTÜRME YOK!)
    - .manifest dosyaları → Steam/config/depotcache/
    
    ÖNEMLİ: kernelos.org lua dosyaları zaten doğru formattadır (addappid).
    ASLA add_license() formatına dönüştürülmemeli!
    """
    setup_dirs()
    
    lua_placed = False
    manifest_count = 0
    
    if file_path.endswith(".zip") and zipfile.is_zipfile(file_path):
        with zipfile.ZipFile(file_path, "r") as z:
            for name in z.namelist():
                lower = name.lower()
                base_name = os.path.basename(name)
                
                # Lua dosyalarını stplug-in dizinine koy (SADECE AppID ile eşleşen)
                if lower.endswith(".lua"):
                    # Dosya adı AppID ile eşleşmeli (örn: 3834090.lua)
                    # Veya README hariç tüm .lua dosyaları (eğer AppID eşleşmiyorsa)
                    expected_lua_name = f"{app_id}.lua"
                    
                    # Lua dosyalarını kullan (README hariç)
                    if base_name.endswith(".lua") and "readme" not in lower:
                        z.extract(name, TARGET_DOWNLOAD_DIR)
                        extracted = os.path.join(TARGET_DOWNLOAD_DIR, name)
                        # Validate
                        if not _validate_downloaded_file(extracted):
                            print(f"  ⚠️ SKIPPED: {base_name} invalid (HTML/Cloudflare)")
                            os.remove(extracted)
                            continue
                        
                        # Copy as is
                        dest = os.path.join(STPLUGIN_DIR, base_name)
                        shutil.copy2(extracted, dest)
                        lua_placed = True
                        print(f"  ✅ Lua → stplug-in/{base_name}")
                        
                        # Geçici dosyayı sil
                        try:
                            os.remove(extracted)
                        except Exception:
                            pass
                
                # Manifest dosyalarını depotcache dizinine koy
                elif lower.endswith(".manifest"):
                    z.extract(name, TARGET_DOWNLOAD_DIR)
                    extracted = os.path.join(TARGET_DOWNLOAD_DIR, name)
                    dest = os.path.join(DEPOTCACHE_DIR, base_name)
                    shutil.copy2(extracted, dest)
                    manifest_count += 1
                    print(f"  ✅ Manifest → depotcache/{base_name}")
                    
                    # Geçici dosyayı sil
                    try:
                        os.remove(extracted)
                    except Exception:
                        pass
                
                # README dosyalarını atla (gerekli değil)
                elif "readme" in lower:
                    print(f"  ℹ️ README skipped: {base_name}")
    
    elif file_path.endswith(".lua"):
        # Single lua file - check Cloudflare!
        if not _validate_downloaded_file(file_path):
            print(f"  ❌ Lua file invalid (HTML/Cloudflare blocked)!")
            return False, 0
        dest = os.path.join(STPLUGIN_DIR, f"{app_id}.lua")
        shutil.copy2(file_path, dest)
        lua_placed = True
        print(f"  ✅ Lua → stplug-in/{app_id}.lua")
    
    return lua_placed, manifest_count


def import_local_file(file_path):
    """Kullanıcının indirdiği dosyayı kurar."""
    if not os.path.isfile(file_path): return False, "File not found."
    file_name = os.path.basename(file_path).lower()
    app_id_match = re.search(r"(\d+)", file_name)
    app_id = app_id_match.group(1) if app_id_match else "unknown"

    # validate
    if not _validate_downloaded_file(file_path):
        return False, "File is invalid or blocked by Cloudflare."

    try:
        lua_placed, manifests = place_game_files(file_path, app_id)
        if lua_placed or manifests > 0:
            return True, f"Successfully imported {file_name}."
        return False, "No Steam files found in package."
    except Exception as e:
        return False, str(e)


def process_downloads():
    """Download klasöründeki yeni dosyaları otomatik işler."""
    setup_dirs()
    if not os.path.isdir(TARGET_DOWNLOAD_DIR):
        return []
    
    files = [f for f in os.listdir(TARGET_DOWNLOAD_DIR) if f.lower().endswith((".zip", ".lua"))]
    results = []
    for f in files:
        path = os.path.join(TARGET_DOWNLOAD_DIR, f)
        ok, msg = import_local_file(path)
        if ok:
            # İşlenen dosyayı sil
            try: os.remove(path)
            except: pass
        results.append((f, ok, msg))
    return results


# =============================================================================
# 8. MODÜL: ANA AKIŞ (kernelos.org → dosya dağıtımı → Steam restart)
# =============================================================================
def restart_steam():
    """Steam'i kapatıp yeniden başlatır."""
    steam_exe = os.path.join(STEAM_PATH, "steam.exe")
    
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


def add_shortcut_from_manifest(app_id, app_name, on_progress=None, auto_restart=False):
    """
    Adds the game to the Steam library.
    
    FLOW:
    1. Fetch files via GitHub (Turbo) or Selenium
    2. Distribute files to correct directories (stplug-in + depotcache)
    3. Restart Steam (optional)
    
    on_progress: callable(pct: float, msg: str) — UI progress update (optional)
    auto_restart: bool — Restart Steam when finished (Default: False)
    """
    def _prog(pct, msg=""):
        if on_progress:
            on_progress(pct, msg)
    
    # 0. System check
    _prog(0.05, "Checking system...")
    system_ok, system_msg = check_stplugin_system()
    if not system_ok:
        print(f"⚠️ {system_msg}")
    else:
        print(f"✅ {system_msg}")
    
    lua_ok = False
    manifest_count = 0

    # ═══════════════════════════════════════════
    # PLAN A: YEREL STEAM SORGUSU (SteamKit Mantığı)
    # ═══════════════════════════════════════════
    _prog(0.10, "Local Steam query (SteamKit)...")
    local_lua, local_manifests = download_from_steam_local(app_id)
    if local_lua:
        lua_ok = True
        manifest_count = local_manifests
        print(f"🚀 Local Steam Fetch successful! Found {manifest_count} depots.")

    # ═══════════════════════════════════════════
    # PLAN B: GITHUB ÇOKLU KAYNAK (Fallback)
    # ═══════════════════════════════════════════
    if not lua_ok:
        _prog(0.20, "Searching GitHub sources (Fallback)...")
        turbo_lua, turbo_manifests = download_from_manifesthub(app_id)
        if turbo_lua:
            lua_ok = True
            manifest_count = turbo_manifests
            print(f"🚀 GitHub download completed! Manifests: {manifest_count}")
    
    if not lua_ok:
        return False, (
            f"{app_id}: Game files not found on any GitHub source!\n\n"
            "Possible reasons:\n"
            "• This AppID is not yet in the manifest repositories\n"
            "• Network connection issue\n"
            "• GitHub rate limit (try again in a few minutes)\n\n"
            "💡 Solution:\n"
            "Find the manifest/lua files manually on community sites:\n"
            "- https://manifestlua.blog/\n"
            "- Toprak Steam Discord/Telegram"
            "1. Check your internet connection\n"
            "2. Wait a few minutes and try again\n"
            "3. Make sure the App ID is correct\n"
            "4. Run GameInSteam as administrator"
        )
    
    _prog(0.65, "Cleaning up...")
    print(f"\n📊 Result: Lua ✅ | Method: GitHub | Manifests: {manifest_count}")
    
    # Clear old faulty ACF manifest if exists
    old_acf = os.path.join(STEAM_PATH, "steamapps", f"appmanifest_{app_id}.acf")
    if os.path.isfile(old_acf):
        try:
            os.remove(old_acf)
            print(f"🧹 Old ACF manifest deleted.")
        except Exception:
            pass
    
    # Restart Steam (Optional)
    if auto_restart:
        _prog(0.70, "Restarting Steam...")
        steam_started = restart_steam()
        _prog(0.95, "Steam started, waiting...")
        if not steam_started:
            return False, "Steam.exe not found!"
    else:
        print("  ℹ️ Manual restart selected, Steam is not restarting.")
        _prog(0.80, "Done! Please restart manually for changes to take effect.")
    
    # Result
    if system_ok:
        return True, (
            f"'{app_name}' (AppID: {app_id}) successfully added!\n"
            f"Method: Kernelos\n"
            f"Lua: stplug-in/{app_id}.lua ✅\n"
            f"Manifest: {manifest_count} files\n\n"
            f"Please check your Steam library."
        )
    else:
        return True, (
            f"Files placed but xinput1_4.dll is missing!\n\n"
            f"Open Toprak Steam Cracker and click the\n"
            f"'Download xinput1_4.dll' button in the top right.\n"
            f"Then restart Steam."
        )


# =============================================================================
# 9. MODÜL: OYUN YÖNETİMİ (Listeleme, Güncelleme, Kaldırma)
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

    Returns: list of dict:
        [{"app_id": "123456", "name": "Game Name", "lua_file": "path",
          "lua_size": 1234, "manifest_count": 2, "has_depot_keys": True}, ...]
    """
    import glob
    games = []
    if not os.path.isdir(STPLUGIN_DIR):
        return games

    for lua_file in sorted(glob.glob(os.path.join(STPLUGIN_DIR, "*.lua"))):
        basename = os.path.basename(lua_file)
        name_part = os.path.splitext(basename)[0]

        # Sadece sayı olan dosya adları (app_id.lua)
        if not name_part.isdigit():
            continue

        app_id = name_part
        lua_size = os.path.getsize(lua_file)

        # Lua içeriğini oku — depot key var mı kontrol et
        has_depot_keys = False
        dlc_count = 0
        try:
            with open(lua_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            # Depot key formatı: addappid(ID, 0, "HEXHASH")
            depot_matches = re.findall(r'addappid\(\d+\s*,\s*\d+\s*,\s*"', content)
            has_depot_keys = len(depot_matches) > 0
            # Toplam addappid sayısı (ana oyun hariç DLC'ler)
            all_ids = re.findall(r"addappid\((\d+)", content)
            dlc_count = max(0, len(all_ids) - 1)
        except Exception:
            pass

        # Manifest sayısını kontrol et
        manifest_count = 0
        if os.path.isdir(DEPOTCACHE_DIR):
            for f in os.listdir(DEPOTCACHE_DIR):
                if f.endswith(".manifest"):
                    manifest_count += 1

        games.append({
            "app_id": app_id,
            "name": "",  # UI tarafından lazy-load edilecek
            "lua_file": lua_file,
            "lua_size": lua_size,
            "dlc_count": dlc_count,
            "manifest_count": manifest_count,
            "has_depot_keys": has_depot_keys,
        })

    return games


def remove_game(app_id):
    """
    Oyunu stplug-in sisteminden kaldırır.
    - Lua dosyasını siler
    - İlişkili manifest dosyalarını siler
    - Eski ACF'yi siler

    Returns: (success: bool, message: str)
    """
    app_id = str(app_id)
    removed = []

    # 1. Lua dosyasını sil
    lua_path = os.path.join(STPLUGIN_DIR, f"{app_id}.lua")
    if os.path.isfile(lua_path):
        os.remove(lua_path)
        removed.append(f"stplug-in/{app_id}.lua")

    # 2. ACF manifest sil
    acf_path = os.path.join(STEAM_PATH, "steamapps", f"appmanifest_{app_id}.acf")
    if os.path.isfile(acf_path):
        os.remove(acf_path)
        removed.append(f"appmanifest_{app_id}.acf")

    # 3. İndirme klasöründeki dosyaları sil
    for ext in [".lua", ".zip"]:
        dl_path = os.path.join(TARGET_DOWNLOAD_DIR, f"{app_id}{ext}")
        if os.path.isfile(dl_path):
            os.remove(dl_path)
            removed.append(f"downloads/{app_id}{ext}")

    if removed:
        import traceback
        print(f"🗑️ Deleted files: {', '.join(removed)}")
        print("🔍 DELETION STACK TRACE:")
        traceback.print_stack()
        return True, f"AppID {app_id} removed.\nDeleted: {len(removed)} files."
    else:
        return False, f"No files found to delete for AppID {app_id}."


def update_game(app_id):
    """
    Oyunun lua/manifest dosyalarını GitHub kaynaklarından günceller.
    Eski dosyaları siler ve yenisini indirir.
    """
    app_id = str(app_id)
    print(f"🔄 Updating AppID {app_id}...")

    # Eski lua'yı sil (yenisi indirilecek)
    old_lua = os.path.join(STPLUGIN_DIR, f"{app_id}.lua")
    if os.path.isfile(old_lua):
        try:
            os.remove(old_lua)
            print(f"  🧹 Old lua deleted.")
        except Exception as e:
            print(f"  ⚠️ Could not delete old lua: {e}")

    # Yeni dosyaları indir (GitHub Turbo)
    lua_ok = False
    file_path, manifest_count = download_from_manifesthub(app_id)
    
    if file_path:
        lua_ok = True

    if lua_ok:
        print(f"✅ Update completed!")
        return True, f"AppID {app_id} updated via GitHub."
    else:
        return False, f"AppID {app_id} update failed! Please try again later."