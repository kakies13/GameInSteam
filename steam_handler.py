import os
import re
import time
import zipfile
import shutil
import subprocess
import tempfile
import requests
import concurrent.futures

# Selenium — kernelos.org'dan indirme için gerekli (Google Chrome)
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        CHROME_DRIVER_MANAGER_AVAILABLE = True
    except ImportError:
        CHROME_DRIVER_MANAGER_AVAILABLE = False
    SELENIUM_AVAILABLE = True
except ImportError:
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
def check_chrome_installed():
    """
    Google Chrome'un yüklü olup olmadığını kontrol eder.
    Returns: (is_installed: bool, chrome_path: str or None, error_message: str or None)
    """
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    
    # Registry kontrolü (Windows)
    try:
        import winreg
        reg_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Google\Chrome\BLBeacon"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Google\Chrome\BLBeacon"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Google\Chrome\BLBeacon"),
        ]
        
        for hkey, path in reg_paths:
            try:
                key = winreg.OpenKey(hkey, path)
                version = winreg.QueryValueEx(key, "version")[0]
                winreg.CloseKey(key)
                # Registry'de bulundu, dosya yolunu kontrol et
                for chrome_path in chrome_paths:
                    if os.path.isfile(chrome_path):
                        return True, chrome_path, None
            except (FileNotFoundError, OSError):
                continue
    except ImportError:
        # winreg modülü yok (nadir durum - Windows dışı sistem)
        pass
    except Exception:
        pass
    
    # Dosya yolu kontrolü
    for chrome_path in chrome_paths:
        if os.path.isfile(chrome_path):
            return True, chrome_path, None
    
    return False, None, "Google Chrome is not installed. Please download and install Chrome: https://www.google.com/chrome/"

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
# 4. MODÜL: ZOMBİ CHROME TEMİZLİĞİ
# =============================================================================
def _kill_zombie_chrome():
    """Arka planda kalmış headless Chrome ve ChromeDriver processlerini sonlandırır."""
    try:
        # ChromeDriver process'lerini kapat (hata vermeden)
        result = subprocess.run(
            ['taskkill', '/F', '/IM', 'chromedriver.exe'],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=2
        )
        # Process bulunamadıysa (exit code 128) bu normal, hata değil
        if result.returncode not in [0, 128]:
            pass  # Diğer hataları sessizce geç
    except subprocess.TimeoutExpired:
        pass  # Timeout olduysa sessizce geç
    except Exception:
        pass  # Tüm hataları sessizce geç


# =============================================================================
# 5. MODÜL: CHROME DRIVER OLUŞTURUCU (Basitleştirilmiş)
# =============================================================================
def _create_chrome_driver(download_dir):
    """
    Google Chrome driver'ı oluşturur — BASİT YAKLAŞIM.
    
    Toprak Steam Cracker tarzı: Sadece gerekli ayarlar, temp profil.
    
    Returns: (driver, temp_profile_path) veya (None, None)
    """
    _kill_zombie_chrome()
    time.sleep(0.2)  # 0.5'ten 0.2'ye düşürüldü
    
    temp_profile = tempfile.mkdtemp(prefix="gis_chrome_")
    
    try:
        chrome_options = Options()
        chrome_options.add_argument(f"--user-data-dir={temp_profile}")
        # Headless mod (görünmez)
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-logging")
        chrome_options.add_argument("--log-level=3")  # Sadece fatal hataları göster
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-software-rasterizer")
        chrome_options.add_argument("--blink-settings=imagesEnabled=false")  # Resimleri yükleme (hızlandırır)
        
        # Chrome açıkken bile çalışabilmesi için ek ayarlar
        chrome_options.add_argument("--remote-debugging-port=0")  # Rastgele port (çakışmayı önler)
        chrome_options.add_argument("--disable-background-networking")  # Arka plan ağ isteklerini kapat
        chrome_options.add_argument("--disable-background-timer-throttling")  # Arka plan timer'ları kapat
        chrome_options.add_argument("--disable-sync")  # Sync'i kapat (açık Chrome ile çakışmayı önler)
        chrome_options.add_argument("--disable-default-apps")  # Varsayılan uygulamaları kapat
        chrome_options.add_argument("--no-first-run")  # İlk çalıştırma ekranını atla
        chrome_options.add_argument("--disable-features=TranslateUI")  # Çeviri özelliklerini kapat
        
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        # Download ayarları: Otomatik indirme, soru sorma
        prefs = {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": False,
            "profile.default_content_setting_values.automatic_downloads": 1,
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        chrome_options.page_load_strategy = "none"  # Çok hızlı yükleme (Tamamlanmasını bekleme)
        
        # Native Selenium Manager dene (Selenium 4.6+ otomatik Chrome driver yönetir)
        try:
            print(f"  ⏳ Starting Chrome driver (native)...")
            driver = webdriver.Chrome(options=chrome_options)
            driver.set_page_load_timeout(15)  # Hızlı timeout
            driver.implicitly_wait(3)  # Dengeli wait
            print("  ✅ Chrome driver started")
            return driver, temp_profile
        except Exception as e1:
            error_msg = str(e1).lower()
            error_type = type(e1).__name__
            error_detail = str(e1)[:300]  # İlk 300 karakter
            print(f"  ⚠️ Native Chrome failed: {error_type}")
            print(f"  📝 Detail: {error_detail}")
            # Chrome yüklü değil veya erişilemiyor hatası
            if "chrome" in error_msg and ("not found" in error_msg or "cannot find" in error_msg or "not installed" in error_msg):
                print(f"  ❌ Chrome not installed or not found")
            elif "timeout" in error_msg or "timed out" in error_msg:
                print(f"  ⚠️ Chrome startup timeout - retrying...")
            elif "connection" in error_msg or "refused" in error_msg:
                print(f"  ⚠️ Chrome connection error - retrying...")
        
        # WebDriver Manager dene (fallback)
        if CHROME_DRIVER_MANAGER_AVAILABLE:
            try:
                print(f"  ⏳ Starting Chrome driver (webdriver-manager)...")
                driver_path = ChromeDriverManager().install()
                driver = webdriver.Chrome(
                    service=Service(driver_path),
                    options=chrome_options,
                )
                driver.set_page_load_timeout(15)  # Hızlı timeout
                driver.implicitly_wait(3)  # Dengeli wait
                print("  ✅ Chrome driver started (webdriver-manager)")
                return driver, temp_profile
            except Exception as e2:
                error_msg = str(e2).lower()
                error_type = type(e2).__name__
                error_detail = str(e2)[:300]  # İlk 300 karakter
                print(f"  ⚠️ Chrome WebDriver Manager failed: {error_type}")
                print(f"  📝 Detail: {error_detail}")
                if "chrome" in error_msg and ("not found" in error_msg or "cannot find" in error_msg or "not installed" in error_msg):
                    print(f"  ❌ Chrome not installed or not found")
                elif "timeout" in error_msg or "timed out" in error_msg:
                    print(f"  ⚠️ Chrome startup timeout")
                elif "connection" in error_msg or "refused" in error_msg:
                    print(f"  ⚠️ Chrome connection error")
        
        print(f"  ❌ Failed to start Chrome driver - all methods failed")
        return None, None
    
    except Exception as e:
        print(f"  ❌ Error: {type(e).__name__}")
        try:
            shutil.rmtree(temp_profile, ignore_errors=True)
        except Exception:
            pass
        return None, None


# =============================================================================
# 6. MODÜL: GITHUB TURBO İNDİRİCİ (ManifestHub branş yapısı)
# =============================================================================
def download_from_manifesthub(app_id):
    """
    SteamAutoCracks/ManifestHub deposunun AppID branşından dosyaları doğrudan çeker.
    Hız: Milisaniyeler. Selenium (Chrome) açılmasına gerek kalmaz.
    
    Returns: (lua_path, manifest_count) veya (None, 0)
    """
    branch = str(app_id)
    base_url = f"https://raw.githubusercontent.com/SteamAutoCracks/ManifestHub/{branch}"
    setup_dirs()
    
    lua_name = f"{app_id}.lua"
    json_name = f"{app_id}.json"
    
    lua_dest = os.path.join(STPLUGIN_DIR, lua_name)
    
    print(f"  🚀 Checking AppID {app_id} via GitHub (Turbo)...")
    
    try:
        # 1. Check LUA file and write directly to stplug-in
        response = requests.get(f"{base_url}/{lua_name}", timeout=10)
        
        if response.status_code != 200:
            print(f"  ❌ GitHub (Turbo): Branch not found or LUA missing.")
            return None, 0
            
        with open(lua_dest, "wb") as f:
            f.write(response.content)
        print(f"  ✅ LUA fetched: {lua_name}")
        
        # 2. JSON dosyasını çekerek içindeki manifestleri bul
        manifest_count = 0
        r_json = requests.get(f"{base_url}/{json_name}", timeout=10)
        if r_json.status_code == 200:
            try:
                data = r_json.json()
                depots = data.get("depots", [])
                if depots:
                    print(f"  📦 {len(depots)} manifest files detected...")
                    for depot in depots:
                        d_id = depot.get("depotid")
                        m_id = depot.get("manifestid")
                        if d_id and m_id:
                            m_file = f"{d_id}_{m_id}.manifest"
                            m_url = f"{base_url}/{m_file}"
                            m_dest = os.path.join(DEPOTCACHE_DIR, m_file)
                            
                            r_m = requests.get(m_url, timeout=10)
                            if r_m.status_code == 200:
                                with open(m_dest, "wb") as f_m:
                                    f_m.write(r_m.content)
                                manifest_count += 1
                                print(f"  ✅ Manifest downloaded: {m_file}")
            except Exception as json_err:
                print(f"  ⚠️ JSON read error: {json_err}")
        
        return lua_dest, manifest_count
        
    except Exception as e:
        print(f"  ⚠️ GitHub Error: {str(e)}")
        return None, 0


# =============================================================================
# 7. MODÜL: KERNELOS BASİT İNDİRİCİ (B Planı - Selenium)
# =============================================================================
def download_from_kernelos_selenium(app_id, target_dir):
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
    
    if not SELENIUM_AVAILABLE:
        return False, (
            "Selenium not installed!\n"
            "Please run this command:\n"
            "pip install selenium webdriver-manager"
        )
    
    # Chrome check (before download)
    _prog(0.08, "Checking Chrome...")
    chrome_installed, chrome_path, chrome_error = check_chrome_installed()
    if not chrome_installed:
        return False, (
            "Google Chrome not found!\n\n"
            f"{chrome_error}\n\n"
            "GameInSteam needs Chrome to download game files.\n\n"
            "Solution:\n"
            "1. Download Google Chrome: https://www.google.com/chrome/\n"
            "2. Install and start Chrome\n"
            "3. Restart GameInSteam\n"
            "4. Try adding the game again"
        )
    print(f"✅ Chrome found: {chrome_path}")
    
    lua_ok = False
    manifest_count = 0
    file_path = None
    
    # ═══════════════════════════════════════════
    # PLAN A: GITHUB TURBO (In seconds)
    # ═══════════════════════════════════════════
    _prog(0.10, "Checking GitHub (Turbo)...")
    turbo_lua, turbo_manifests = download_from_manifesthub(app_id)
    
    if turbo_lua:
        lua_ok = True
        manifest_count = turbo_manifests
        print(f"🚀 GitHub (Turbo) completed successfully! Speed: < 2s")
    else:
        # ═══════════════════════════════════════════
        # PLAN B: KERNELOS.ORG (Selenium, Fallback)
        # ═══════════════════════════════════════════
        _prog(0.20, "Not on GitHub, trying Kernelos (Selenium)...")
        print(f"\n📥 Not found on GitHub. Downloading with Kernelos Selenium...")
        
        # Chrome check (only if Selenium is needed)
        chrome_installed, chrome_path, chrome_error = check_chrome_installed()
        if not chrome_installed:
            return False, (
                "Google Chrome not found!\n\n"
                f"{chrome_error}\n\n"
                "GameInSteam needs Chrome for the backup download method (Kernelos).\n\n"
                "Solution:\n"
                "1. Download Google Chrome: https://www.google.com/chrome/\n"
                "2. Install and start Chrome\n"
                "3. Restart GameInSteam"
            )
            
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(download_from_kernelos_selenium, app_id, TARGET_DOWNLOAD_DIR)
                file_path = future.result(timeout=50)  # Balanced timeout
        except concurrent.futures.TimeoutError:
            print(f"⏰ Selenium 50s timeout! fallback failed.")
            _kill_zombie_chrome()
            file_path = None
        except Exception as e:
            print(f"⚠️ Selenium error: {type(e).__name__}: {e}")
            _kill_zombie_chrome()
            file_path = None
    
    if file_path:
        _prog(0.60, "Placing files...")
        print(f"📦 Downloaded: {os.path.basename(file_path)}")
        lua_ok, manifest_count = place_game_files(file_path, app_id)
    
    # Chrome error checks
    if file_path == "CHROME_NOT_INSTALLED":
        return False, (
            "Google Chrome not found!\n\n"
            "GameInSteam needs Chrome to download game files.\n\n"
            "Solution:\n"
            "1. Download Google Chrome: https://www.google.com/chrome/\n"
            "2. Install and start Chrome\n"
            "3. Restart GameInSteam\n"
            "4. Try adding the game again"
        )
    
    if file_path == "CHROME_DRIVER_ERROR":
        return False, (
            "Chrome driver could not be started!\n\n"
            "Possible reasons:\n"
            "• Chrome driver could not be downloaded\n"
            "• Chrome version mismatch\n"
            "• No internet connection (needed for driver download)\n"
            "• Antivirus/firewall is blocking\n"
            "• Chrome cannot be started\n\n"
            "Solution:\n"
            "1. Check your internet connection\n"
            "2. Update Chrome (Chrome menu → Help → About Google Chrome)\n"
            "3. Close and reopen Chrome\n"
            "4. Temporarily disable antivirus/firewall and try again\n"
            "5. Restart your computer\n"
            "6. Run GameInSteam as administrator"
        )
    
    if file_path:
        _prog(0.55, "Placing files...")
        print(f"📦 Downloaded: {os.path.basename(file_path)}")
        lua_ok, manifest_count = place_game_files(file_path, app_id)
    
    if not lua_ok:
        # If file_path is None, download failed
        if file_path is None:
            return False, (
                f"{app_id}: Download from kernelos.org failed!\n\n"
                "Possible reasons:\n"
                "• kernelos.org is temporarily unreachable\n"
                "• Network connection issue\n"
                "• No internet connection\n"
                "• Game files not found\n"
                "• Chrome driver could not be started\n"
                "• Page load timeout\n\n"
                "Solution:\n"
                "1. Check your internet connection\n"
                "2. Wait a few minutes and try again\n"
                "3. Make sure Chrome is up to date\n"
                "4. Try a different App ID\n"
                "5. Run GameInSteam as administrator"
            )
        else:
            # File downloaded but invalid
            return False, (
                f"{app_id}: Downloaded file is invalid!\n\n"
                "Possible reasons:\n"
                "• Cloudflare protection returned an HTML page\n"
                "• File is corrupted or incomplete\n"
                "• Wrong file type downloaded\n\n"
                "Solution:\n"
                "1. Wait a few minutes and try again\n"
                "2. Try a different App ID\n"
                "3. Check your internet connection"
            )
    
    _prog(0.65, "Cleaning up...")
    print(f"\n📊 Result: Lua ✅ | Method: Kernelos | Manifests: {manifest_count}")
    
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
        print(f"🗑️ Deleted files: {', '.join(removed)}")
        return True, f"AppID {app_id} removed.\nDeleted: {len(removed)} files."
    else:
        return False, f"No files found to delete for AppID {app_id}."


def update_game(app_id):
    """
    Oyunun lua/manifest dosyalarını kernelos.org'dan günceller.
    Eski dosyaları siler ve yenisini indirir.

    Returns: (success: bool, message: str)
    """
    app_id = str(app_id)
    print(f"🔄 Updating AppID {app_id}...")

    if not SELENIUM_AVAILABLE:
        return False, "Selenium not installed! pip install selenium webdriver-manager"

    # Delete old lua (new one will be downloaded)
    old_lua = os.path.join(STPLUGIN_DIR, f"{app_id}.lua")
    if os.path.isfile(old_lua):
        os.remove(old_lua)
        print(f"  🧹 Old lua deleted.")

    lua_ok = False
    file_path = None

    # Update with Kernelos Selenium (50s timeout)
    print(f"\n📥 Downloading with Kernelos Selenium...")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(download_from_kernelos_selenium, app_id, TARGET_DOWNLOAD_DIR)
            file_path = future.result(timeout=50)  # Balanced timeout
    except concurrent.futures.TimeoutError:
        print(f"⏰ Selenium 50s timeout!")
        _kill_zombie_chrome()
        file_path = None
    except Exception as e:
        print(f"⚠️ Selenium error: {type(e).__name__}")
        _kill_zombie_chrome()
        file_path = None
    
    if file_path:
        lua_ok, _ = place_game_files(file_path, app_id)

    if lua_ok:
        print(f"✅ Update completed!")
        return True, f"AppID {app_id} updated.\nMethod: Kernelos"
    else:
        return False, (
            f"AppID {app_id} could not be updated!\n"
            "Download from kernelos.org failed.\n"
            "Close Chrome and try again."
        )
