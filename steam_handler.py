import glob
import os
import re
import time
import zipfile
import shutil
import subprocess
import requests

# Selenium opsiyonel — sadece kernelos fallback modunda lazım
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

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
# 3. MODÜL: LOKAL LUA OLUŞTURUCU (Steam API ile DLC destekli)
# =============================================================================
def get_dlc_list(app_id):
    """
    Steam Store API'den oyunun DLC listesini çeker.
    Ücretsiz, API key gerektirmez.
    Returns: list of DLC app IDs (int) veya boş liste
    """
    try:
        resp = requests.get(
            STEAM_API_URL,
            params={"appids": str(app_id), "filters": "basic"},
            timeout=10,
        )
        data = resp.json()
        app_data = data.get(str(app_id), {})
        if app_data.get("success") and "data" in app_data:
            info = app_data["data"]
            dlc_ids = info.get("dlc", [])
            return [int(d) for d in dlc_ids]
    except Exception as e:
        print(f"⚠️ DLC listesi alınamadı: {e}")
    return []


def generate_local_lua(app_id):
    """
    Lokal olarak lua dosyası oluşturur — internetten indirme GEREKMEZ!
    
    1. Ana oyun App ID'si ile addappid() satırı oluşturur
    2. Steam API'den DLC listesini çeker ve onları da ekler
    3. Dosyayı direkt stplug-in/ dizinine yazar
    
    Returns: (lua_path, dlc_count) veya (None, 0)
    """
    setup_dirs()
    
    app_id = int(app_id)
    all_ids = [app_id]
    
    # Steam API'den DLC'leri çek
    print(f"🔍 Steam API'den DLC bilgileri çekiliyor...")
    dlc_ids = get_dlc_list(app_id)
    if dlc_ids:
        all_ids.extend(dlc_ids)
        print(f"  📦 {len(dlc_ids)} DLC bulundu!")
    else:
        print(f"  ℹ️ DLC bulunamadı veya DLC'siz oyun.")
    
    # Lua içeriği oluştur
    lines = [
        f"-- GameInSteam - Lokal oluşturuldu",
        f"-- Ana oyun: {app_id}",
        f"-- DLC sayısı: {len(dlc_ids)}",
        "",
    ]
    for aid in all_ids:
        lines.append(f"addappid({aid})")
    
    lua_content = "\n".join(lines) + "\n"
    
    # stplug-in dizinine yaz
    lua_path = os.path.join(STPLUGIN_DIR, f"{app_id}.lua")
    try:
        with open(lua_path, "w", encoding="utf-8") as f:
            f.write(lua_content)
        print(f"  ✅ Lua oluşturuldu: stplug-in/{app_id}.lua ({len(all_ids)} AppID)")
        return lua_path, len(dlc_ids)
    except Exception as e:
        print(f"  ❌ Lua yazılamadı: {e}")
        return None, 0


# =============================================================================
# 4. MODÜL: DOSYA DOĞRULAMA (Cloudflare HTML koruması)
# =============================================================================
def _validate_downloaded_file(file_path):
    """
    İndirilen dosyanın gerçekten lua/zip olup olmadığını doğrular.
    Cloudflare bazen HTML challenge sayfası döner — bunu yakalar.
    Bozuk dosya stplug-in'e yerleştirilirse Steam çöker!
    """
    try:
        size = os.path.getsize(file_path)
        if size < 50:
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
# 4A. MODÜL: KERNELOS SELENIUM (Headless — optimize edilmiş)
# =============================================================================
def download_from_kernelos_selenium(app_id, target_dir):
    """kernelos.org'dan Headless Selenium ile indirir — optimize edilmiş sürüm."""
    if not SELENIUM_AVAILABLE:
        print("❌ Selenium yüklü değil — kernelos Selenium kullanılamaz.")
        return None
    os.makedirs(target_dir, exist_ok=True)
    before_files = set(os.listdir(target_dir))

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-images")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.page_load_strategy = "eager"  # DOM hazır olunca devam et (görseller beklenmez)

    prefs = {
        "download.default_directory": target_dir,
        "download.prompt_for_download": False,
    }
    chrome_options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options,
    )
    wait = WebDriverWait(driver, 15)  # 25 → 15 saniye timeout

    try:
        driver.get("https://kernelos.org/games/")
        # time.sleep(3) yerine akıllı bekleme
        time.sleep(1.5)

        # Input kutusunu bul — optimize edilmiş sıralama
        input_box = None
        selectors = [
            "input[type='text']",
            "input[type='number']",
            "input:not([type='hidden']):not([type='submit']):not([type='button'])",
        ]
        for sel in selectors:
            try:
                input_box = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                break
            except Exception:
                continue

        if not input_box:
            input_box = driver.execute_script("""
                var inputs = document.querySelectorAll('input');
                for (var i = 0; i < inputs.length; i++) {
                    var t = inputs[i].type.toLowerCase();
                    if (t !== 'hidden' && t !== 'submit' && t !== 'button'
                        && inputs[i].offsetParent !== null) {
                        return inputs[i];
                    }
                }
                return null;
            """)

        if not input_box:
            print("❌ Sayfada input alanı bulunamadı!")
            return None

        input_box.clear()
        input_box.send_keys(str(app_id))

        get_link_btn = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Get link')]"))
        )
        get_link_y = get_link_btn.location.get("y", 0)
        driver.execute_script("arguments[0].click();", get_link_btn)

        # time.sleep(3) yerine akıllı bekleme — download linki çıkana kadar bekle
        time.sleep(1.5)
        
        # Download linkinin oluşmasını bekle (max 8 saniye)
        for _ in range(16):
            result = driver.execute_script("""
                var glY = arguments[0];
                var els = document.querySelectorAll('a, button');
                for (var i = 0; i < els.length; i++) {
                    var el = els[i];
                    var txt = (el.textContent || '').toLowerCase();
                    var rect = el.getBoundingClientRect();
                    var absY = rect.top + window.scrollY;
                    if (absY <= glY + 10) continue;
                    if (txt.indexOf('download') !== -1
                        || txt.indexOf('open link') !== -1) {
                        return {idx: i, href: el.href || null};
                    }
                }
                return null;
            """, get_link_y)
            
            if result:
                break
            time.sleep(0.5)

        if result:
            if result["href"]:
                session = requests.Session()
                for cookie in driver.get_cookies():
                    session.cookies.set(cookie["name"], cookie["value"])
                res = session.get(result["href"], stream=True)
                ct = res.headers.get("Content-Type", "")
                ext = ".zip" if "zip" in ct else ".lua"
                fp = os.path.join(target_dir, f"{app_id}{ext}")
                with open(fp, "wb") as f:
                    for chunk in res.iter_content(chunk_size=8192):
                        f.write(chunk)
                if _validate_downloaded_file(fp):
                    return fp
                os.remove(fp)
                print("  ⚠️ Selenium indirmesi geçersiz dosya döndü (Cloudflare?).")
            else:
                all_els = driver.find_elements(By.CSS_SELECTOR, "a, button")
                driver.execute_script(
                    "arguments[0].click();", all_els[result["idx"]]
                )
                for _ in range(15):
                    time.sleep(1)
                    new_files = set(os.listdir(target_dir)) - before_files
                    for f in new_files:
                        if not f.endswith((".tmp", ".crdownload")):
                            return os.path.join(target_dir, f)
    finally:
        driver.quit()
    return None


# =============================================================================
# 5. MODÜL: DOSYA YERLEŞTİRME (Toprak Steam Cracker mantığı — kernelos fallback)
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
                
                # Lua dosyalarını stplug-in dizinine koy
                if lower.endswith(".lua"):
                    z.extract(name, TARGET_DOWNLOAD_DIR)
                    extracted = os.path.join(TARGET_DOWNLOAD_DIR, name)
                    # Cloudflare HTML koruması kontrolü!
                    if not _validate_downloaded_file(extracted):
                        print(f"  ⚠️ ATLANIDI: {os.path.basename(name)} geçersiz (HTML/Cloudflare)")
                        os.remove(extracted)
                        continue
                    dest = os.path.join(STPLUGIN_DIR, os.path.basename(name))
                    shutil.copy2(extracted, dest)
                    lua_placed = True
                    print(f"  ✅ Lua → stplug-in/{os.path.basename(name)}")
                
                # Manifest dosyalarını depotcache dizinine koy
                elif lower.endswith(".manifest"):
                    z.extract(name, TARGET_DOWNLOAD_DIR)
                    extracted = os.path.join(TARGET_DOWNLOAD_DIR, name)
                    dest = os.path.join(DEPOTCACHE_DIR, os.path.basename(name))
                    shutil.copy2(extracted, dest)
                    manifest_count += 1
                    print(f"  ✅ Manifest → depotcache/{os.path.basename(name)}")
    
    elif file_path.endswith(".lua"):
        # Tek lua dosyası — Cloudflare kontrolü yap!
        if not _validate_downloaded_file(file_path):
            print(f"  ❌ Lua dosyası geçersiz (HTML/Cloudflare engeli)!")
            return False, 0
        dest = os.path.join(STPLUGIN_DIR, f"{app_id}.lua")
        shutil.copy2(file_path, dest)
        lua_placed = True
        print(f"  ✅ Lua → stplug-in/{app_id}.lua")
    
    # Eski hatalı add_license formatındaki dosyaları temizle
    old_config_lua = os.path.join(STEAM_PATH, "config", f"{app_id}.lua")
    if os.path.isfile(old_config_lua):
        try:
            with open(old_config_lua, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if "add_license(" in content:
                os.remove(old_config_lua)
                print(f"  🧹 Eski hatalı config/{app_id}.lua silindi (add_license formatı)")
        except Exception:
            pass
    
    return lua_placed, manifest_count


# =============================================================================
# 6. MODÜL: ANA AKIŞ (Önce Lokal Lua → Fallback Kernelos)
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
    1. KERNELOS.ORG (Headless Chrome) — Depot anahtarları + manifest dahil tam veri
    2. FALLBACK: LOKAL LUA — Kernelos başarısız olursa basit addappid() oluşturur
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
    
    lua_ok = False
    manifest_count = 0
    method_used = ""
    file_path = None
    
    # ═══════════════════════════════════════════
    # YÖNTEM 1: KERNELOS SELENIUM (~8-15 saniye)
    # ═══════════════════════════════════════════
    if SELENIUM_AVAILABLE:
        _prog(0.10, "kernelos.org'dan indiriliyor...")
        print(f"\n📥 Kernelos Selenium ile indiriliyor...")
        try:
            file_path = download_from_kernelos_selenium(app_id, TARGET_DOWNLOAD_DIR)
        except Exception as e:
            print(f"⚠️ Selenium hatası (fallback'e geçiliyor): {type(e).__name__}")
            file_path = None
        
        if file_path:
            _prog(0.55, "Dosyalar yerleştiriliyor...")
            print(f"📦 İndirilen: {os.path.basename(file_path)}")
            lua_ok, manifest_count = place_game_files(file_path, app_id)
            if lua_ok:
                method_used = "Kernelos (depot anahtarları dahil)"
    else:
        print("⚠️ Selenium yüklü değil, lokal lua oluşturulacak.")
    
    # ═══════════════════════════════════════════
    # YÖNTEM 2: LOKAL LUA FALLBACK (~0.1 saniye)
    # ═══════════════════════════════════════════
    if not lua_ok:
        _prog(0.50, "Lokal lua oluşturuluyor...")
        print(f"\n🔧 Lokal lua oluşturuluyor (fallback)...")
        lua_path, dlc_count = generate_local_lua(app_id)
        
        if lua_path:
            lua_ok = True
            method_used = "Lokal Lua (depot anahtarları YOK)"
            print(f"✅ Lokal lua oluşturuldu ({dlc_count} DLC dahil)")
            print("⚠️ Not: Depot şifre anahtarları eksik — bazı oyunlar başlamayabilir.")
    
    if not lua_ok:
        return False, "Hiçbir yöntem başarılı olmadı! kernelos erişilemez ve lokal oluşturma başarısız."
    
    _prog(0.65, "Temizlik yapılıyor...")
    print(f"\n📊 Sonuç: Lua ✅ | Yöntem: {method_used} | Manifest: {manifest_count}")
    
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
            f"Yöntem: {method_used}\n"
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
# 7. MODÜL: OYUN YÖNETİMİ (Listeleme, Güncelleme, Kaldırma)
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

    # Eski lua'yı sil (yeni indirilecek)
    old_lua = os.path.join(STPLUGIN_DIR, f"{app_id}.lua")
    if os.path.isfile(old_lua):
        os.remove(old_lua)
        print(f"  🧹 Eski lua silindi.")

    lua_ok = False
    method_used = ""

    # Yöntem 1: Kernelos Selenium
    if SELENIUM_AVAILABLE:
        print(f"\n📥 Kernelos Selenium ile indiriliyor...")
        try:
            file_path = download_from_kernelos_selenium(app_id, TARGET_DOWNLOAD_DIR)
        except Exception as e:
            print(f"⚠️ Selenium hatası: {type(e).__name__}")
            file_path = None
        if file_path:
            lua_ok, _ = place_game_files(file_path, app_id)
            if lua_ok:
                method_used = "Kernelos (depot anahtarlı)"

    # Yöntem 2: Lokal fallback
    if not lua_ok:
        print(f"\n🔧 Lokal lua fallback...")
        lua_path, dlc_count = generate_local_lua(app_id)
        if lua_path:
            lua_ok = True
            method_used = "Lokal (depot anahtarsız)"

    if lua_ok:
        print(f"✅ Güncelleme tamamlandı! Yöntem: {method_used}")
        return True, f"AppID {app_id} güncellendi.\nYöntem: {method_used}"
    else:
        return False, f"AppID {app_id} güncellenemedi!"
