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
def check_stplugin_system():
    """
    stplug-in sisteminin kurulu olup olmadığını kontrol eder.
    Gerekli: xinput1_4.dll (proxy DLL) Steam dizininde olmalı.
    """
    dll_path = os.path.join(STEAM_PATH, "xinput1_4.dll")
    if os.path.isfile(dll_path):
        size = os.path.getsize(dll_path)
        # Proxy DLL genelde ~670KB+ olur (sistem DLL'i ~100KB)
        if size > 200000:
            return True, f"Sistem aktif! xinput1_4.dll mevcut ({size:,} byte)."
        else:
            return False, (
                "xinput1_4.dll var ama sistem versiyonu gibi görünüyor.\n"
                "Toprak Steam Cracker'dan 'Download xinput1_4.dll' butonuna bas."
            )
    return False, (
        "xinput1_4.dll bulunamadı!\n"
        "Toprak Steam Cracker'ı aç ve sağ üstteki\n"
        "'Download xinput1_4.dll' butonuna bas."
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
            print("🧹 Steam önbelleği (appcache) temizlendi.")
        except Exception as e:
            print(f"⚠️ Önbellek silinemedi: {e}")


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
            print(f"  ⚠️ Dosya adı 'plugin' içeriyor, yanlış indirme olabilir: {os.path.basename(file_path)}")
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
    time.sleep(0.5)
    
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
        
        chrome_options.page_load_strategy = "eager"  # Hızlı yükleme (normal yerine)
        
        # Native Selenium Manager dene (Selenium 4.6+ otomatik Chrome driver yönetir)
        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.set_page_load_timeout(30)  # Sayfa yükleme timeout
            driver.implicitly_wait(5)  # Element bulma için bekleme
            print("  ✅ Chrome driver başlatıldı")
            return driver, temp_profile
        except Exception as e1:
            error_msg = str(e1).lower()
            # Chrome yüklü değil veya erişilemiyor hatası
            if "chrome" in error_msg and ("not found" in error_msg or "cannot find" in error_msg or "not installed" in error_msg):
                print(f"  ❌ Chrome yüklü değil veya bulunamadı")
            else:
                print(f"  ⚠️ Native Chrome başarısız: {type(e1).__name__}")
        
        # WebDriver Manager dene (fallback)
        if CHROME_DRIVER_MANAGER_AVAILABLE:
            try:
                driver_path = ChromeDriverManager().install()
                driver = webdriver.Chrome(
                    service=Service(driver_path),
                    options=chrome_options,
                )
                driver.set_page_load_timeout(30)  # Sayfa yükleme timeout
                driver.implicitly_wait(5)  # Element bulma için bekleme
                print("  ✅ Chrome driver başlatıldı (webdriver-manager)")
                return driver, temp_profile
            except Exception as e2:
                error_msg = str(e2).lower()
                if "chrome" in error_msg and ("not found" in error_msg or "cannot find" in error_msg or "not installed" in error_msg):
                    print(f"  ❌ Chrome yüklü değil veya bulunamadı")
                else:
                    print(f"  ⚠️ Chrome WebDriver Manager başarısız: {type(e2).__name__}")
        
        print(f"  ❌ Chrome driver başlatılamadı")
        return None, None
    
    except Exception as e:
        print(f"  ❌ Hata: {type(e).__name__}")
        try:
            shutil.rmtree(temp_profile, ignore_errors=True)
        except Exception:
            pass
        return None, None


# =============================================================================
# 6. MODÜL: KERNELOS BASİT İNDİRİCİ (Toprak Steam Cracker tarzı)
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
        print("❌ Selenium yüklü değil!")
        return None
    
    os.makedirs(target_dir, exist_ok=True)
    before_files = set(os.listdir(target_dir))  # İndirme öncesi dosyalar
    driver, temp_profile = _create_chrome_driver(target_dir)
    if driver is None:
        # Chrome driver başlatılamadı - özel hata kodu
        print("  ❌ Chrome driver başlatılamadı!")
        return "CHROME_DRIVER_ERROR"
    
    try:
        # 1. Sayfayı aç (timeout süresini artır)
        print(f"  🌐 kernelos.org/games/ açılıyor...")
        try:
            driver.get("https://kernelos.org/games/")
            print(f"  ✅ Sayfa yüklendi")
        except Exception as page_error:
            print(f"  ⚠️ Sayfa yükleme hatası: {type(page_error).__name__}")
            # TimeoutException olsa bile devam et, belki DOM hazır
            if "Timeout" not in str(type(page_error).__name__):
                return None
        
        # Sayfanın tam yüklenmesi için bekle (input alanı görünene kadar)
        print(f"  ⏳ Sayfa yükleniyor, input alanı bekleniyor...")
        input_box = None
        
        # Farklı selector'ları dene
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
                input_box = WebDriverWait(driver, 3).until(  # 5'ten 3'e düşürüldü
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                print(f"  ✅ Input alanı bulundu: {selector}")
                break
            except Exception:
                continue
        
        if not input_box:
            print(f"  ❌ Input alanı bulunamadı! Sayfa yüklenmemiş olabilir.")
            return None
        
        # 2. AppID'yi input'a yaz
        
        input_box.clear()
        input_box.send_keys(str(app_id))
        print(f"  ✍️ AppID yazıldı: {app_id}")
        
        # 3. "Get link" butonuna tıkla
        get_link_btn = WebDriverWait(driver, 10).until(  # 20'den 10'a düşürüldü
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Get link')]"))
        )
        driver.execute_script("arguments[0].click();", get_link_btn)
        print(f"  🔗 'Get link' butonuna tıklandı...")
        
        # 4. "Ready..." mesajını bekle (hızlandırıldı)
        time.sleep(1)  # 2'den 1'e düşürüldü
        for _ in range(10):  # 20'den 10'a düşürüldü
            if "ready" in driver.page_source.lower():
                break
            time.sleep(0.3)  # 0.5'ten 0.3'e düşürüldü
        
        # 5. EN ALTTAKİ "Download" veya "Open link" butonunu bul
        time.sleep(1)  # 3'ten 1'e düşürüldü
        download_btn = None
        open_link_btn = None
        download_href = None
        
        print(f"  🔍 Open link/Download butonu aranıyor...")
        for _ in range(15):  # 20'den 15'e düşürüldü
            # Tüm butonları ve linkleri bul
            all_elements = driver.find_elements(By.CSS_SELECTOR, "button, a")
            
            # "Download" ve "Open link" butonlarını bul
            download_candidates = []
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
                    
                    # Download butonu
                    if "download" in text and "open link" not in text and "get link" not in text:
                        download_candidates.append((y_pos, el, href))
                    # Open link butonu
                    elif "open link" in text:
                        open_link_candidates.append((y_pos, el, href))
                except Exception:
                    continue
            
            # Open link butonunu öncelikle seç (daha güvenilir)
            if open_link_candidates:
                open_link_candidates.sort(key=lambda x: x[0], reverse=True)
                open_link_btn = open_link_candidates[0][1]
                download_href = open_link_candidates[0][2]
                print(f"  ✅ Open link butonu bulundu (href: {'var' if download_href else 'yok'})")
                download_btn = open_link_btn  # Aynı değişkeni kullan
                break
            # Open link yoksa Download butonunu kullan
            elif download_candidates:
                download_candidates.sort(key=lambda x: x[0], reverse=True)
                download_btn = download_candidates[0][1]
                download_href = download_candidates[0][2]
                print(f"  ✅ Download butonu bulundu (href: {'var' if download_href else 'yok'})")
                break
            
            time.sleep(0.3)  # 0.5'ten 0.3'e düşürüldü
        
        if not download_btn:
            print("  ❌ Download/Open link butonu bulunamadı!")
            return None
        
        # 6. İndirme yöntemi: href varsa requests, yoksa tarayıcı indirmesi
        # href varsa ve gerçek bir dosya linkiyse requests ile indir
        # Anchor link kontrolü: #downloads, # gibi linkler gerçek dosya değil
        if download_href and download_href.startswith("http"):
            # Anchor link kontrolü (kernelos.org/#downloads gibi)
            if "#" in download_href and not download_href.endswith((".zip", ".lua")):
                # Anchor link, tarayıcı indirmesini kullan
                print(f"  ⚠️ Anchor link tespit edildi, tarayıcı indirmesine geçiliyor...")
                download_href = None
            else:
                print(f"  📥 Download linki bulundu, requests ile indiriliyor...")
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
                    
                    # HTML değilse indir
                    if "text/html" not in ct:
                        # Dosya uzantısını belirle
                        ext = ".zip" if "zip" in ct or "application/zip" in ct else ".lua"
                        fp = os.path.join(target_dir, f"{app_id}{ext}")
                        
                        # Dosyayı kaydet
                        with open(fp, "wb") as f:
                            for chunk in res.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        
                        file_size = os.path.getsize(fp)
                        print(f"  💾 Dosya kaydedildi: {os.path.basename(fp)} ({file_size:,} bytes)")
                        
                        # Dosyayı doğrula
                        if _validate_downloaded_file(fp):
                            print(f"  ✅ Dosya geçerli: {os.path.basename(fp)}")
                            return fp
                        else:
                            os.remove(fp)
                            print("  ❌ İndirilen dosya geçersiz, tarayıcı indirmesine geçiliyor...")
                            download_href = None
                    else:
                        print("  ⚠️ Link HTML sayfasına yönlendiriyor, tarayıcı indirmesine geçiliyor...")
                        download_href = None
                except Exception as e:
                    print(f"  ⚠️ requests ile indirme başarısız: {type(e).__name__}, tarayıcı indirmesine geçiliyor...")
                    download_href = None
        
        # href yoksa veya başarısız olduysa, butona tıkla ve tarayıcı indirmesini bekle
        if not download_href:
            print(f"  🖱️ Butona tıklanıyor (tarayıcı indirmesi)...")
            try:
                # Butona tıkla
                driver.execute_script("arguments[0].click();", download_btn)
                time.sleep(1)  # 2'den 1'e düşürüldü
                
                # İndirmenin tamamlanmasını bekle (max 60 saniye)
                download_started = False
                for i in range(60):
                    time.sleep(0.5)  # 1'den 0.5'e düşürüldü (2x daha hızlı kontrol)
                    current_files = set(os.listdir(target_dir))
                    new_files = current_files - before_files
                    
                    # İndirme devam ediyor mu kontrol et (.crdownload, .tmp)
                    downloading = [f for f in new_files if f.endswith((".crdownload", ".tmp", ".part"))]
                    if downloading:
                        download_started = True
                        if i % 10 == 0:  # Her 5 saniyede bir log (0.5s * 10 = 5s)
                            print(f"  ⏳ İndirme devam ediyor... ({i*0.5:.0f}s)")
                        continue
                    
                    # Tamamlanmış dosyaları kontrol et
                    completed = [f for f in new_files if not f.endswith((".tmp", ".crdownload", ".part"))]
                    for f in completed:
                        fpath = os.path.join(target_dir, f)
                        try:
                            file_size = os.path.getsize(fpath)
                            print(f"  💾 İndirilen: {f} ({file_size:,} bytes)")
                            
                            # Dosya doğrulaması (boyut kontrolü yok, sadece içerik kontrolü)
                            if _validate_downloaded_file(fpath):
                                print(f"  ✅ Dosya geçerli: {f}")
                                return fpath
                            else:
                                print(f"  ⚠️ Dosya geçersiz (HTML/Cloudflare?), siliniyor...")
                                os.remove(fpath)
                        except Exception as e:
                            print(f"  ⚠️ Dosya kontrolü hatası: {type(e).__name__}")
                            continue
                    
                    # İndirme başladıysa ve tamamlandıysa çık
                    if download_started and not downloading and completed:
                        break
                
                if not download_started:
                    print("  ❌ İndirme başlamadı! Buton çalışmıyor olabilir.")
                else:
                    print("  ❌ İndirme zaman aşımına uğradı!")
                return None
            except Exception as e:
                print(f"  ❌ Tarayıcı indirmesi başarısız: {type(e).__name__}: {e}")
                return None
    
    except Exception as e:
        print(f"  ❌ Hata: {type(e).__name__}: {e}")
        return None
    
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass
        time.sleep(0.3)
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
                        # Cloudflare HTML koruması kontrolü!
                        if not _validate_downloaded_file(extracted):
                            print(f"  ⚠️ ATLANIDI: {base_name} geçersiz (HTML/Cloudflare)")
                            os.remove(extracted)
                            continue
                        
                        # Dosyayı olduğu gibi kopyala (yeniden adlandırma yok)
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
                    print(f"  ℹ️ README atlandı: {base_name}")
    
    elif file_path.endswith(".lua"):
        # Tek lua dosyası — Cloudflare kontrolü yap!
        if not _validate_downloaded_file(file_path):
            print(f"  ❌ Lua dosyası geçersiz (HTML/Cloudflare engeli)!")
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
    
    print("\n🔄 Steam yeniden başlatılıyor...")
    subprocess.run(
        ["taskkill", "/F", "/IM", "steam.exe"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(4)
    
    clear_steam_cache()
    
    if os.path.isfile(steam_exe):
        print("🚀 Steam başlatılıyor...")
        subprocess.Popen([steam_exe])
        time.sleep(10)
        print("✅ Steam başlatıldı.")
        return True
    else:
        print("❌ Steam.exe bulunamadı!")
        return False


def add_shortcut_from_manifest(app_id, app_name, on_progress=None):
    """
    Oyunu Steam kütüphanesine ekler.
    
    AKIŞ:
    1. kernelos.org'dan Selenium ile lua/zip indir
    2. Dosyaları doğru dizinlere dağıt (stplug-in + depotcache)
    3. Steam'i yeniden başlat
    
    on_progress: callable(pct: float, msg: str) — UI progress güncellemesi (opsiyonel)
    """
    def _prog(pct, msg=""):
        if on_progress:
            on_progress(pct, msg)
    
    # 0. Sistem kontrolü
    _prog(0.05, "Sistem kontrol ediliyor...")
    system_ok, system_msg = check_stplugin_system()
    if not system_ok:
        print(f"⚠️ {system_msg}")
    else:
        print(f"✅ {system_msg}")
    
    if not SELENIUM_AVAILABLE:
        return False, (
            "Selenium yüklü değil!\n"
            "Lütfen şu komutu çalıştır:\n"
            "pip install selenium webdriver-manager"
        )
    
    lua_ok = False
    manifest_count = 0
    file_path = None
    
    # ═══════════════════════════════════════════
    # KERNELOS.ORG İNDİRME (Selenium, max 60sn timeout)
    # ═══════════════════════════════════════════
    _prog(0.10, "kernelos.org'dan indiriliyor...")
    print(f"\n📥 Kernelos Selenium ile indiriliyor...")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(download_from_kernelos_selenium, app_id, TARGET_DOWNLOAD_DIR)
            file_path = future.result(timeout=60)
    except concurrent.futures.TimeoutError:
        print(f"⏰ Selenium 60sn timeout! kernelos.org'dan indirme zaman aşımına uğradı.")
        _kill_zombie_chrome()
        file_path = None
    except Exception as e:
        print(f"⚠️ Selenium hatası: {type(e).__name__}: {e}")
        _kill_zombie_chrome()
        file_path = None
    
    # Chrome driver hatası kontrolü
    if file_path == "CHROME_DRIVER_ERROR":
        return False, (
            "Chrome driver başlatılamadı!\n\n"
            "Olası sebepler:\n"
            "• Google Chrome yüklü değil\n"
            "• Chrome güncel değil\n"
            "• Chrome erişilemiyor\n\n"
            "Çözüm:\n"
            "1. Google Chrome'u indirip kur: https://www.google.com/chrome/\n"
            "2. Chrome'u güncelle\n"
            "3. Bilgisayarı yeniden başlat\n"
            "4. Tekrar dene"
        )
    
    if file_path:
        _prog(0.55, "Dosyalar yerleştiriliyor...")
        print(f"📦 İndirilen: {os.path.basename(file_path)}")
        lua_ok, manifest_count = place_game_files(file_path, app_id)
    
    if not lua_ok:
        return False, (
            "kernelos.org'dan indirme başarısız!\n\n"
            "Olası sebepler:\n"
            "• kernelos.org geçici olarak erişilemez\n"
            "• Ağ bağlantı sorunu\n"
            "• İnternet bağlantısı yok\n"
            "• Oyun dosyaları bulunamadı\n\n"
            "Çözüm: Birkaç dakika bekle ve tekrar dene."
        )
    
    _prog(0.65, "Temizlik yapılıyor...")
    print(f"\n📊 Sonuç: Lua ✅ | Yöntem: Kernelos | Manifest: {manifest_count}")
    
    # Eski hatalı ACF manifest varsa temizle
    old_acf = os.path.join(STEAM_PATH, "steamapps", f"appmanifest_{app_id}.acf")
    if os.path.isfile(old_acf):
        try:
            os.remove(old_acf)
            print(f"🧹 Eski ACF manifest silindi.")
        except Exception:
            pass
    
    # Steam'i yeniden başlat
    _prog(0.70, "Steam yeniden başlatılıyor...")
    steam_started = restart_steam()
    _prog(0.95, "Steam başlatıldı, bekleniyor...")
    if not steam_started:
        return False, "Steam.exe bulunamadı!"
    
    # Sonuç
    if system_ok:
        return True, (
            f"'{app_name}' (AppID: {app_id}) başarıyla eklendi!\n"
            f"Yöntem: Kernelos\n"
            f"Lua: stplug-in/{app_id}.lua ✅\n"
            f"Manifest: {manifest_count} dosya\n\n"
            f"Steam kütüphanenizi kontrol edin."
        )
    else:
        return True, (
            f"Dosyalar yerleştirildi ama xinput1_4.dll eksik!\n\n"
            f"Toprak Steam Cracker'ı aç ve sağ üstteki\n"
            f"'Download xinput1_4.dll' butonuna bas.\n"
            f"Sonra Steam'i yeniden başlat."
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
        print(f"🗑️ Silinen dosyalar: {', '.join(removed)}")
        return True, f"AppID {app_id} kaldırıldı.\nSilinen: {len(removed)} dosya."
    else:
        return False, f"AppID {app_id} için silinecek dosya bulunamadı."


def update_game(app_id):
    """
    Oyunun lua/manifest dosyalarını kernelos.org'dan günceller.
    Eski dosyaları siler ve yenisini indirir.

    Returns: (success: bool, message: str)
    """
    app_id = str(app_id)
    print(f"🔄 AppID {app_id} güncelleniyor...")

    if not SELENIUM_AVAILABLE:
        return False, "Selenium yüklü değil! pip install selenium webdriver-manager"

    # Eski lua'yı sil (yeni indirilecek)
    old_lua = os.path.join(STPLUGIN_DIR, f"{app_id}.lua")
    if os.path.isfile(old_lua):
        os.remove(old_lua)
        print(f"  🧹 Eski lua silindi.")

    lua_ok = False
    file_path = None

    # Kernelos Selenium ile güncelle (60sn timeout)
    print(f"\n📥 Kernelos Selenium ile indiriliyor...")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(download_from_kernelos_selenium, app_id, TARGET_DOWNLOAD_DIR)
            file_path = future.result(timeout=60)
    except concurrent.futures.TimeoutError:
        print(f"⏰ Selenium 60sn timeout!")
        _kill_zombie_chrome()
        file_path = None
    except Exception as e:
        print(f"⚠️ Selenium hatası: {type(e).__name__}")
        _kill_zombie_chrome()
        file_path = None
    
    if file_path:
        lua_ok, _ = place_game_files(file_path, app_id)

    if lua_ok:
        print(f"✅ Güncelleme tamamlandı!")
        return True, f"AppID {app_id} güncellendi.\nYöntem: Kernelos"
    else:
        return False, (
            f"AppID {app_id} güncellenemedi!\n"
            "kernelos.org'dan indirme başarısız.\n"
            "Chrome'u kapat ve tekrar dene."
        )
