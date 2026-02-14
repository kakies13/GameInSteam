import io
import json
import os
import threading
import time
import tkinter as tk
from tkinter import messagebox

import requests
from PIL import Image, ImageTk

# Senin yazdığın backend fonksiyonlarını buradan çekiyoruz
try:
    from steam_handler import (
        add_shortcut_from_manifest,
        check_stplugin_system,
        get_game_name_from_steam,
        list_added_games,
        remove_game,
        restart_steam,
        update_game,
    )
except ImportError:
    # Eğer dosya ismi farklıysa burayı düzeltmen gerekebilir
    print("Hata: steam_handler.py bulunamadı veya fonksiyonlar eksik!")

# Güncelleme modülü
try:
    from updater import check_for_update, download_update, apply_update, CURRENT_VERSION
except ImportError:
    print("Hata: updater.py bulunamadı!")
    CURRENT_VERSION = "2.7"
    def check_for_update(): return None
    def download_update(*args): return None
    def apply_update(*args): pass

# Görsel boyutu (px)
IMG_W, IMG_H = 136, 64

# Steam CDN
HEADER_URL = "https://cdn.akamai.steamstatic.com/steam/apps/{}/header.jpg"

# Ayarlar dosyası
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".gameinsteam_config.json")

# Discord Webhook URL (varsayılan)
DEFAULT_WEBHOOK_URL = "https://discord.com/api/webhooks/1472005555873779864/ToCJUYyztEyCfOCrNd23EuXcx8N3dysOnkweInKTAeXWcCJf7pJuXsgWu9LPKGRLiYVB"


# ═══════════════════════════════════════════════════════════════
# RENK PALETİ (Steam Modern Dark Theme)
# ═══════════════════════════════════════════════════════════════
C = {
    "bg_dark": "#171a21",
    "bg_main": "#1b2838",
    "bg_card": "#2a475e",
    "bg_input": "#32404e",
    "accent": "#66c0f4",
    "accent_hover": "#7fd1ff",
    "text": "#c7d5e0",
    "text_dim": "#8f98a0",
    "text_bright": "#ffffff",
    "green": "#5ba32b",
    "green_hover": "#6ec338",
    "yellow": "#d4a017",
    "red": "#c74040",
    "red_hover": "#e04e4e",
    "border": "#3d5a73",
    "tab_on": "#1b2838",
    "tab_off": "#141d26",
}


# ═══════════════════════════════════════════════════════════════
# HOVER BUTON BİLEŞENİ
# ═══════════════════════════════════════════════════════════════
class HoverButton(tk.Button):
    def __init__(self, master, bg_n, bg_h, **kw):
        super().__init__(master, **kw)
        self.bg_n = bg_n
        self.bg_h = bg_h
        self.configure(bg=bg_n)
        self.bind("<Enter>", lambda e: self.configure(bg=self.bg_h))
        self.bind("<Leave>", lambda e: self.configure(bg=self.bg_n))


# ═══════════════════════════════════════════════════════════════
# ANA UYGULAMA SINIFI
# ═══════════════════════════════════════════════════════════════
class GameInSteamApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"GameInSteam v{CURRENT_VERSION}")
        self.root.geometry("680x600")
        self.root.minsize(620, 520)
        self.root.configure(bg=C["bg_dark"])

        # Pencereyi ortala
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - 340
        y = (self.root.winfo_screenheight() // 2) - 300
        self.root.geometry(f"+{x}+{y}")

        self._busy = False
        self._name_cache = {}
        self._img_cache = {}       # app_id -> ImageTk.PhotoImage (GC koruması)
        self._placeholder = None   # gri placeholder resim
        self._config = self._load_config()  # Ayarları yükle
        self._update_info = None  # Güncelleme bilgisi
        
        self._build_ui()
        self._check_system()
        self._create_placeholder()
        
        # Uygulama açılışında güncelleme kontrolü
        if self._config.get("auto_check_updates", True):
            threading.Thread(target=self._check_update_on_start, daemon=True).start()

    def _create_placeholder(self):
        """Oyun görseli yüklenene kadar gösterilecek gri placeholder."""
        img = Image.new("RGB", (IMG_W, IMG_H), color=(42, 71, 94))
        self._placeholder = ImageTk.PhotoImage(img)
    
    def _load_config(self):
        """Ayarları dosyadan yükle."""
        default = {
            "auto_check_updates": True,
            "auto_download_updates": False,
            "discord_webhook_enabled": True,
            "discord_webhook_url": DEFAULT_WEBHOOK_URL
        }
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    return {**default, **config}
        except Exception:
            pass
        return default
    
    def _save_config(self):
        """Ayarları dosyaya kaydet."""
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────
    # UI İNŞA ETME
    # ─────────────────────────────────────────────────────────
    def _build_ui(self):
        # ─── HEADER (Logo ve Başlık) ───
        hdr = tk.Frame(self.root, bg=C["bg_main"], height=68)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        hdr_in = tk.Frame(hdr, bg=C["bg_main"])
        hdr_in.pack(expand=True)

        tk.Label(hdr_in, text="🎮", font=("Segoe UI Emoji", 24),
                 bg=C["bg_main"], fg=C["accent"]).pack(side="left", padx=(0, 10))

        tf = tk.Frame(hdr_in, bg=C["bg_main"])
        tf.pack(side="left")
        tk.Label(tf, text="GameInSteam", font=("Segoe UI", 17, "bold"),
                 bg=C["bg_main"], fg=C["text_bright"]).pack(anchor="w")
        tk.Label(tf, text="Steam Kütüphane Yöneticisi", font=("Segoe UI", 8),
                 bg=C["bg_main"], fg=C["text_dim"]).pack(anchor="w")

        # ─── SİSTEM DURUM BARI ───
        sb = tk.Frame(self.root, bg=C["bg_card"], height=32)
        sb.pack(fill="x")
        sb.pack_propagate(False)
        sb_in = tk.Frame(sb, bg=C["bg_card"])
        sb_in.pack(fill="x", padx=14)

        self.sys_icon = tk.Label(sb_in, text="⏳", font=("Segoe UI Emoji", 10),
                                 bg=C["bg_card"], fg=C["yellow"])
        self.sys_icon.pack(side="left", pady=5)
        self.sys_label = tk.Label(sb_in, text="Kontrol ediliyor...", font=("Segoe UI", 8),
                                  bg=C["bg_card"], fg=C["text"], anchor="w")
        self.sys_label.pack(side="left", padx=(5, 0), fill="x", expand=True)

        # ─── TABS (Navigasyon) ───
        tb = tk.Frame(self.root, bg=C["bg_dark"])
        tb.pack(fill="x")

        self.tab_add = tk.Button(
            tb, text="➕  Oyun Ekle", font=("Segoe UI", 10, "bold"),
            bg=C["tab_on"], fg=C["accent"], bd=0, activebackground=C["tab_on"],
            activeforeground=C["accent"], cursor="hand2",
            command=lambda: self._tab("add"))
        self.tab_add.pack(side="left", ipadx=18, ipady=7)

        self.tab_lib = tk.Button(
            tb, text="📚  Oyunlarım", font=("Segoe UI", 10, "bold"),
            bg=C["tab_off"], fg=C["text_dim"], bd=0, activebackground=C["tab_off"],
            activeforeground=C["text_dim"], cursor="hand2",
            command=lambda: self._tab("lib"))
        self.tab_lib.pack(side="left", ipadx=18, ipady=7)

        self.tab_settings = tk.Button(
            tb, text="⚙️  Ayarlar", font=("Segoe UI", 10, "bold"),
            bg=C["tab_off"], fg=C["text_dim"], bd=0, activebackground=C["tab_off"],
            activeforeground=C["text_dim"], cursor="hand2",
            command=lambda: self._tab("settings"))
        self.tab_settings.pack(side="left", ipadx=18, ipady=7)

        tk.Frame(self.root, bg=C["accent"], height=2).pack(fill="x")

        # ─── TAB İÇERİK ALANI ───
        self.body = tk.Frame(self.root, bg=C["bg_dark"])
        self.body.pack(fill="both", expand=True)

        self._build_add_page()
        self._build_lib_page()
        self._build_settings_page()

        # ─── FOOTER ───
        ft = tk.Frame(self.root, bg=C["bg_main"], height=28)
        ft.pack(fill="x", side="bottom")
        ft.pack_propagate(False)
        tk.Label(ft, text=f"v{CURRENT_VERSION}", font=("Segoe UI", 7),
                 bg=C["bg_main"], fg=C["text_dim"]).pack(side="left", padx=10)
        self.footer = tk.Label(ft, text="Hazır", font=("Segoe UI", 7),
                               bg=C["bg_main"], fg=C["text_dim"])
        self.footer.pack(side="right", padx=10)

        self._tab("add")

    # ─── SAYFA: OYUN EKLE ───
    def _build_add_page(self):
        self.pg_add = tk.Frame(self.body, bg=C["bg_dark"])

        card = tk.Frame(self.pg_add, bg=C["bg_main"],
                        highlightbackground=C["border"], highlightthickness=1)
        card.pack(fill="both", expand=True, padx=16, pady=14)

        inner = tk.Frame(card, bg=C["bg_main"])
        inner.pack(fill="both", expand=True, padx=24, pady=20)

        tk.Label(inner, text="Yeni Oyun Ekle", font=("Segoe UI", 14, "bold"),
                 bg=C["bg_main"], fg=C["text_bright"]).pack(anchor="w", pady=(0, 18))

        # App ID Girişi
        r1 = tk.Frame(inner, bg=C["bg_main"])
        r1.pack(fill="x", pady=(0, 10))
        tk.Label(r1, text="App ID", font=("Segoe UI", 10, "bold"),
                 bg=C["bg_main"], fg=C["text"], width=10, anchor="w").pack(side="left")
        self.inp_id = tk.Entry(
            r1, font=("Segoe UI", 12), bg=C["bg_input"], fg=C["text_bright"],
            insertbackground=C["accent"], relief="flat",
            highlightbackground=C["border"], highlightcolor=C["accent"],
            highlightthickness=1)
        self.inp_id.pack(side="left", fill="x", expand=True, ipady=7)

        tk.Label(inner, text="💡 Steam mağaza URL'sindeki sayıyı girin (örn: 730) veya birden fazla App ID (virgülle ayırın: 730, 440, 570)",
                 font=("Segoe UI", 8), bg=C["bg_main"], fg=C["text_dim"]).pack(anchor="w", pady=(0, 14))

        # Oyun Adı Girişi
        r2 = tk.Frame(inner, bg=C["bg_main"])
        r2.pack(fill="x", pady=(0, 18))
        tk.Label(r2, text="Oyun Adı", font=("Segoe UI", 10, "bold"),
                 bg=C["bg_main"], fg=C["text"], width=10, anchor="w").pack(side="left")
        self.inp_name = tk.Entry(
            r2, font=("Segoe UI", 12), bg=C["bg_input"], fg=C["text_bright"],
            insertbackground=C["accent"], relief="flat",
            highlightbackground=C["border"], highlightcolor=C["accent"],
            highlightthickness=1)
        self.inp_name.pack(side="left", fill="x", expand=True, ipady=7)
        tk.Label(r2, text="opsiyonel", font=("Segoe UI", 8),
                 bg=C["bg_main"], fg=C["text_dim"]).pack(side="left", padx=(8, 0))

        # Ekle Butonu
        self.btn_add = HoverButton(
            inner, bg_n=C["accent"], bg_h=C["accent_hover"],
            text="⚡  Oyunu Ekle", font=("Segoe UI", 13, "bold"),
            fg="#0b0f14", activebackground=C["accent_hover"],
            activeforeground="#0b0f14", relief="flat", cursor="hand2",
            command=self._do_add)
        self.btn_add.pack(fill="x", ipady=10)

        # Status & Progress Canvas
        self.status_frame = tk.Frame(inner, bg=C["bg_main"])
        self.status_icon = tk.Label(self.status_frame, text="", font=("Segoe UI Emoji", 10), bg=C["bg_main"])
        self.status_icon.pack(side="left")
        self.status_text = tk.Label(self.status_frame, text="", font=("Segoe UI", 10), bg=C["bg_main"], fg=C["text"], anchor="w")
        self.status_text.pack(side="left", padx=(6, 0), fill="x", expand=True)
        self.prog = tk.Canvas(self.status_frame, height=4, bg=C["bg_card"], highlightthickness=0)

    # ─── SAYFA: OYUNLARIM ───
    def _build_lib_page(self):
        self.pg_lib = tk.Frame(self.body, bg=C["bg_dark"])

        top = tk.Frame(self.pg_lib, bg=C["bg_dark"])
        top.pack(fill="x", padx=16, pady=(14, 8))

        self.lib_count = tk.Label(top, text="Ekli Oyunlar", font=("Segoe UI", 13, "bold"),
                                  bg=C["bg_dark"], fg=C["text_bright"])
        self.lib_count.pack(side="left")

        HoverButton(top, bg_n=C["bg_card"], bg_h=C["border"],
                     text="🔄 Yenile", font=("Segoe UI", 9),
                     fg=C["text"], activebackground=C["border"],
                     activeforeground=C["text_bright"], relief="flat", cursor="hand2", bd=0,
                     command=self._load_games).pack(side="right")

        wrap = tk.Frame(self.pg_lib, bg=C["bg_dark"])
        wrap.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        self.cv = tk.Canvas(wrap, bg=C["bg_dark"], highlightthickness=0)
        sb = tk.Scrollbar(wrap, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.cv.pack(side="left", fill="both", expand=True)

        self.cv_inner = tk.Frame(self.cv, bg=C["bg_dark"])
        self.cv_win = self.cv.create_window((0, 0), window=self.cv_inner, anchor="nw")
        self.cv_inner.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfig(self.cv_win, width=e.width))
        self.cv.bind_all("<MouseWheel>", lambda e: self.cv.yview_scroll(int(-1 * (e.delta / 120)), "units"))
    
    # ─── SAYFA: AYARLAR ───
    def _build_settings_page(self):
        self.pg_settings = tk.Frame(self.body, bg=C["bg_dark"])
        
        card = tk.Frame(self.pg_settings, bg=C["bg_main"],
                        highlightbackground=C["border"], highlightthickness=1)
        card.pack(fill="both", expand=True, padx=16, pady=14)
        
        inner = tk.Frame(card, bg=C["bg_main"])
        inner.pack(fill="both", expand=True, padx=24, pady=20)
        
        tk.Label(inner, text="Ayarlar", font=("Segoe UI", 14, "bold"),
                 bg=C["bg_main"], fg=C["text_bright"]).pack(anchor="w", pady=(0, 20))
        
        # Güncelleme Ayarları
        update_frame = tk.Frame(inner, bg=C["bg_main"])
        update_frame.pack(fill="x", pady=(0, 20))
        
        tk.Label(update_frame, text="Güncellemeler", font=("Segoe UI", 11, "bold"),
                 bg=C["bg_main"], fg=C["text_bright"]).pack(anchor="w", pady=(0, 10))
        
        # Otomatik güncelleme kontrolü
        auto_check_frame = tk.Frame(update_frame, bg=C["bg_main"])
        auto_check_frame.pack(fill="x", pady=(0, 8))
        
        self.auto_check_var = tk.BooleanVar(value=self._config.get("auto_check_updates", True))
        tk.Checkbutton(auto_check_frame, text="Uygulama açılışında güncelleme kontrolü yap",
                      variable=self.auto_check_var, bg=C["bg_main"], fg=C["text"],
                      selectcolor=C["bg_card"], activebackground=C["bg_main"],
                      activeforeground=C["text"], font=("Segoe UI", 9),
                      command=self._on_auto_check_changed).pack(side="left")
        
        # Otomatik indirme
        auto_dl_frame = tk.Frame(update_frame, bg=C["bg_main"])
        auto_dl_frame.pack(fill="x", pady=(0, 8))
        
        self.auto_dl_var = tk.BooleanVar(value=self._config.get("auto_download_updates", False))
        tk.Checkbutton(auto_dl_frame, text="Güncellemeleri otomatik indir",
                      variable=self.auto_dl_var, bg=C["bg_main"], fg=C["text"],
                      selectcolor=C["bg_card"], activebackground=C["bg_main"],
                      activeforeground=C["text"], font=("Segoe UI", 9),
                      command=self._on_auto_dl_changed).pack(side="left")
        
        # Manuel güncelleme butonu
        update_btn_frame = tk.Frame(update_frame, bg=C["bg_main"])
        update_btn_frame.pack(fill="x", pady=(10, 0))
        
        self.btn_check_update = HoverButton(
            update_btn_frame, bg_n=C["accent"], bg_h=C["accent_hover"],
            text="🔄 Güncellemeleri Kontrol Et", font=("Segoe UI", 10, "bold"),
            fg="#0b0f14", activebackground=C["accent_hover"],
            activeforeground="#0b0f14", relief="flat", cursor="hand2",
            command=self._manual_check_update)
        self.btn_check_update.pack(side="left", ipadx=15, ipady=8)
        
        self.update_status_label = tk.Label(update_btn_frame, text="",
                                            font=("Segoe UI", 8), bg=C["bg_main"], fg=C["text_dim"])
        self.update_status_label.pack(side="left", padx=(10, 0))
        
        # Steam Ayarları
        steam_frame = tk.Frame(inner, bg=C["bg_main"])
        steam_frame.pack(fill="x", pady=(20, 0))
        
        tk.Label(steam_frame, text="Steam", font=("Segoe UI", 11, "bold"),
                 bg=C["bg_main"], fg=C["text_bright"]).pack(anchor="w", pady=(0, 10))
        
        # Restart Steam butonu
        restart_btn = HoverButton(
            steam_frame, bg_n=C["green"], bg_h=C["green_hover"],
            text="🔄 Steam'i Yeniden Başlat", font=("Segoe UI", 10, "bold"),
            fg="#ffffff", activebackground=C["green_hover"],
            activeforeground="#ffffff", relief="flat", cursor="hand2",
            command=self._do_restart_steam)
        restart_btn.pack(anchor="w", ipadx=15, ipady=8)
        
        tk.Label(steam_frame, text="Steam'i kapatıp yeniden başlatır",
                font=("Segoe UI", 8), bg=C["bg_main"], fg=C["text_dim"]).pack(anchor="w", pady=(5, 0))
        
        # Discord Webhook Ayarları
        discord_frame = tk.Frame(inner, bg=C["bg_main"])
        discord_frame.pack(fill="x", pady=(20, 0))
        
        tk.Label(discord_frame, text="Discord Bildirimleri", font=("Segoe UI", 11, "bold"),
                 bg=C["bg_main"], fg=C["text_bright"]).pack(anchor="w", pady=(0, 10))
        
        # Discord webhook aktif/pasif
        discord_enable_frame = tk.Frame(discord_frame, bg=C["bg_main"])
        discord_enable_frame.pack(fill="x", pady=(0, 8))
        
        self.discord_enabled_var = tk.BooleanVar(value=self._config.get("discord_webhook_enabled", True))
        tk.Checkbutton(discord_enable_frame, text="Discord bildirimlerini etkinleştir",
                      variable=self.discord_enabled_var, bg=C["bg_main"], fg=C["text"],
                      selectcolor=C["bg_card"], activebackground=C["bg_main"],
                      activeforeground=C["text"], font=("Segoe UI", 9),
                      command=self._on_discord_enabled_changed).pack(side="left")
        
        # Webhook URL girişi
        webhook_url_frame = tk.Frame(discord_frame, bg=C["bg_main"])
        webhook_url_frame.pack(fill="x", pady=(0, 5))
        
        tk.Label(webhook_url_frame, text="Webhook URL", font=("Segoe UI", 9),
                 bg=C["bg_main"], fg=C["text"], width=12, anchor="w").pack(side="left")
        
        self.webhook_url_entry = tk.Entry(
            webhook_url_frame, font=("Segoe UI", 9), bg=C["bg_input"], fg=C["text_bright"],
            insertbackground=C["accent"], relief="flat",
            highlightbackground=C["border"], highlightcolor=C["accent"],
            highlightthickness=1)
        self.webhook_url_entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(5, 0))
        self.webhook_url_entry.insert(0, self._config.get("discord_webhook_url", DEFAULT_WEBHOOK_URL))
        self.webhook_url_entry.bind("<KeyRelease>", lambda e: self._on_webhook_url_changed())
        
        tk.Label(discord_frame, text="Oyun eklendiğinde, güncellendiğinde veya kaldırıldığında Discord'a bildirim gönderilir",
                font=("Segoe UI", 8), bg=C["bg_main"], fg=C["text_dim"]).pack(anchor="w", pady=(5, 0))

    # ─────────────────────────────────────────────────────────
    # LOJİK & EVENTLER
    # ─────────────────────────────────────────────────────────
    def _tab(self, t):
        # Tüm tab'ları sıfırla
        self.tab_add.configure(bg=C["tab_off"], fg=C["text_dim"])
        self.tab_lib.configure(bg=C["tab_off"], fg=C["text_dim"])
        self.tab_settings.configure(bg=C["tab_off"], fg=C["text_dim"])
        
        # Tüm sayfaları gizle
        self.pg_add.pack_forget()
        self.pg_lib.pack_forget()
        self.pg_settings.pack_forget()
        
        if t == "add":
            self.tab_add.configure(bg=C["tab_on"], fg=C["accent"])
            self.pg_add.pack(in_=self.body, fill="both", expand=True)
        elif t == "lib":
            self.tab_lib.configure(bg=C["tab_on"], fg=C["accent"])
            self.pg_lib.pack(in_=self.body, fill="both", expand=True)
            self._load_games()
        elif t == "settings":
            self.tab_settings.configure(bg=C["tab_on"], fg=C["accent"])
            self.pg_settings.pack(in_=self.body, fill="both", expand=True)

    def _check_system(self):
        try:
            ok, msg = check_stplugin_system()
            if ok:
                self.sys_icon.configure(text="✅", fg=C["green"])
                self.sys_label.configure(text="Sistem aktif — stplug-in hazır", fg=C["green"])
            else:
                self.sys_icon.configure(text="⚠️", fg=C["yellow"])
                self.sys_label.configure(text=msg.split("\n")[0], fg=C["yellow"])
        except: pass

    def _do_add(self):
        app_ids_str = self.inp_id.get().strip()
        name = self.inp_name.get().strip()
        
        if not app_ids_str:
            messagebox.showerror("Hata", "Geçerli bir App ID girin.")
            return
        
        # Birden fazla App ID desteği (virgülle ayrılmış)
        app_ids = [aid.strip() for aid in app_ids_str.split(",") if aid.strip()]
        
        # Geçerlilik kontrolü
        valid_ids = []
        for aid in app_ids:
            if aid.isdigit():
                valid_ids.append(aid)
            else:
                messagebox.showerror("Hata", f"Geçersiz App ID: {aid}")
                return
        
        if not valid_ids:
            messagebox.showerror("Hata", "Geçerli bir App ID girin.")
            return
        
        if not name and len(valid_ids) == 1:
            name = f"Game_{valid_ids[0]}"
        elif not name:
            name = f"{len(valid_ids)} Oyun"
        
        self._set_busy(True, f"{len(valid_ids)} oyun ekleniyor...")
        threading.Thread(target=self._worker_add_multiple, args=(valid_ids, name), daemon=True).start()

    def _worker_add(self, app_id, name):
        try:
            ok, msg = add_shortcut_from_manifest(app_id, name)
        except Exception as e:
            ok, msg = False, str(e)
        self.root.after(0, lambda: self._done_add(ok, msg))
    
    def _worker_add_multiple(self, app_ids, base_name):
        """Birden fazla oyunu sırayla ekle."""
        results = []
        total = len(app_ids)
        
        for idx, app_id in enumerate(app_ids):
            try:
                game_name = base_name if total == 1 else f"{base_name} ({idx+1}/{total})"
                self.root.after(0, lambda i=idx+1, t=total: self._update_progress(f"Oyun {i}/{t} ekleniyor..."))
                ok, msg = add_shortcut_from_manifest(app_id, game_name)
                results.append((app_id, ok, msg))
            except Exception as e:
                results.append((app_id, False, str(e)))
        
        self.root.after(0, lambda: self._done_add_multiple(results))
    
    def _update_progress(self, msg):
        """İlerleme mesajını güncelle."""
        self._show_status("⏳", msg, C["accent"])
        self.footer.configure(text=msg)
    
    def _done_add_multiple(self, results):
        """Birden fazla oyun ekleme sonucu."""
        self._set_busy(False)
        self._check_system()
        
        success_count = sum(1 for _, ok, _ in results if ok)
        total_count = len(results)
        
        if success_count == total_count:
            self._show_status("✅", f"{success_count} oyun başarıyla eklendi!", C["green"])
            messagebox.showinfo("Başarılı", f"{success_count} oyun başarıyla eklendi!")
        elif success_count > 0:
            self._show_status("⚠️", f"{success_count}/{total_count} oyun eklendi", C["yellow"])
            failed = [aid for aid, ok, _ in results if not ok]
            msg = f"{success_count}/{total_count} oyun eklendi.\n\nBaşarısız App ID'ler:\n" + "\n".join(failed)
            messagebox.showwarning("Kısmi Başarı", msg)
        else:
            self._show_status("❌", "Hiçbir oyun eklenemedi", C["red"])
            failed = [f"{aid}: {msg}" for aid, _, msg in results]
            messagebox.showerror("Hata", "Hiçbir oyun eklenemedi:\n\n" + "\n".join(failed))
        
        # Discord bildirimi (çoklu oyun için)
        if success_count > 0:
            try:
                first_app_id = results[0][0] if results else ""
                base_name = self.inp_name.get().strip() or f"{success_count} Oyun"
                self._send_game_added_notification(first_app_id, base_name, success_count, total_count)
            except Exception:
                pass
        
        # Input'ları temizle
        self.inp_id.delete(0, tk.END)
        self.inp_name.delete(0, tk.END)

    def _done_add(self, ok, msg):
        self._set_busy(False)
        self._check_system()
        if ok:
            self._show_status("✅", "Başarıyla eklendi!", C["green"])
            messagebox.showinfo("Başarılı", msg)
            # Discord bildirimi (tek oyun için)
            try:
                app_id = self.inp_id.get().strip()
                game_name = self.inp_name.get().strip() or f"Game_{app_id}"
                if app_id and app_id.isdigit():
                    self._send_game_added_notification(app_id, game_name)
            except Exception:
                pass
        else:
            self._show_status("❌", "Hata oluştu", C["red"])
            messagebox.showerror("Hata", msg)

    def _load_games(self):
        for w in self.cv_inner.winfo_children(): w.destroy()
        try:
            games = list_added_games()
            self.lib_count.configure(text=f"Ekli Oyunlar ({len(games)})")
            if not games:
                empty = tk.Frame(self.cv_inner, bg=C["bg_main"], highlightbackground=C["border"], highlightthickness=1)
                empty.pack(fill="x", pady=4)
                tk.Label(empty, text="📭 Henüz oyun eklenmemiş", font=("Segoe UI", 10), bg=C["bg_main"], fg=C["text_dim"], pady=30).pack()
                return
            for g in games: self._game_card(g)
        except: pass

    def _game_card(self, g):
        aid = g["app_id"]
        card = tk.Frame(self.cv_inner, bg=C["bg_main"], highlightbackground=C["border"], highlightthickness=1)
        card.pack(fill="x", pady=3)
        row = tk.Frame(card, bg=C["bg_main"])
        row.pack(fill="x", padx=10, pady=8)

        img_lbl = tk.Label(row, bg=C["bg_card"], width=IMG_W, height=IMG_H, image=self._placeholder)
        img_lbl.pack(side="left", padx=(0, 12))

        info = tk.Frame(row, bg=C["bg_main"])
        info.pack(side="left", fill="x", expand=True)

        cached = self._name_cache.get(aid, "")
        name_lbl = tk.Label(info, text=cached or f"Oyun #{aid}", font=("Segoe UI", 11, "bold"), bg=C["bg_main"], fg=C["text_bright"], anchor="w")
        name_lbl.pack(anchor="w")

        tk.Label(info, text=f"AppID: {aid}", font=("Segoe UI", 8), bg=C["bg_main"], fg=C["accent"]).pack(anchor="w")
        
        btns = tk.Frame(row, bg=C["bg_main"])
        btns.pack(side="right")

        HoverButton(btns, bg_n=C["bg_card"], bg_h=C["green_hover"], text="🔄", font=("Segoe UI Emoji", 12), fg=C["text"], relief="flat", width=3, command=lambda: self._do_update(aid)).pack(side="left", padx=2)
        HoverButton(btns, bg_n=C["bg_card"], bg_h=C["red_hover"], text="🗑️", font=("Segoe UI Emoji", 12), fg=C["text"], relief="flat", width=3, command=lambda: self._do_remove(aid, card)).pack(side="left", padx=2)

        if not cached: threading.Thread(target=self._fetch_name, args=(aid, name_lbl), daemon=True).start()
        if aid not in self._img_cache: threading.Thread(target=self._fetch_image, args=(aid, img_lbl), daemon=True).start()
        else: img_lbl.configure(image=self._img_cache[aid])

    def _fetch_name(self, aid, lbl):
        try:
            name = get_game_name_from_steam(aid)
            if name:
                self._name_cache[aid] = name
                self.root.after(0, lambda: lbl.configure(text=name))
        except: pass

    def _fetch_image(self, aid, lbl):
        try:
            url = HEADER_URL.format(aid)
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                img = Image.open(io.BytesIO(resp.content)).resize((IMG_W, IMG_H), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._img_cache[aid] = photo
                # Widget hala var mı kontrol et (try-except ile güvenli)
                def safe_update():
                    try:
                        lbl.configure(image=photo)
                    except:
                        pass  # Widget silinmiş, görmezden gel
                self.root.after(0, safe_update)
        except: pass

    def _do_update(self, aid):
        self._set_busy(True, "Güncelleniyor...")
        threading.Thread(target=lambda: self._worker_update(aid), daemon=True).start()

    def _worker_update(self, aid):
        ok, msg = update_game(aid)
        # Discord bildirimi
        if ok:
            try:
                game_name = get_game_name_from_steam(aid) or f"Game_{aid}"
                self.root.after(0, lambda: self._send_game_updated_notification(aid, game_name))
            except Exception:
                pass
        self.root.after(0, lambda: [self._set_busy(False), self._load_games(), messagebox.showinfo("Bilgi", msg)])

    def _do_remove(self, aid, card):
        if messagebox.askyesno("Onay", "Bu oyunu kaldırmak istediğine emin misin?"):
            ok, msg = remove_game(aid)
            if ok:
                card.destroy()
                # Discord bildirimi
                try:
                    game_name = get_game_name_from_steam(aid) or f"Game_{aid}"
                    self._send_game_removed_notification(aid, game_name)
                except Exception:
                    pass
            else:
                messagebox.showerror("Hata", msg)

    def _set_busy(self, busy, msg=""):
        self._busy = busy
        if busy:
            self.btn_add.configure(state="disabled", text="⏳ Bekleyiniz...")
            self._show_status("⏳", msg, C["accent"])
            self.prog.pack(fill="x", pady=(6, 0))
            self._anim()
        else:
            self.btn_add.configure(state="normal", text="⚡  Oyunu Ekle")
            self.prog.pack_forget()

    def _show_status(self, icon, text, color):
        self.status_frame.pack(fill="x", pady=(12, 0))
        self.status_icon.configure(text=icon, fg=color)
        self.status_text.configure(text=text, fg=color)

    def _anim(self):
        if not self._busy: return
        w = self.prog.winfo_width() or 400
        self.prog.delete("all")
        pos = int((time.time() * 80) % (w + 120)) - 60
        self.prog.create_rectangle(max(0, pos), 0, min(w, pos + 120), 4, fill=C["accent"], outline="")
        self.root.after(30, self._anim)
    
    # ─────────────────────────────────────────────────────────
    # GÜNCELLEME FONKSİYONLARI
    # ─────────────────────────────────────────────────────────
    def _check_update_on_start(self):
        """Uygulama açılışında güncelleme kontrolü."""
        time.sleep(2)  # UI yüklensin diye bekle
        try:
            update_info = check_for_update()
            if update_info:
                self._update_info = update_info
                self.root.after(0, lambda: self._show_update_notification(update_info))
        except Exception:
            pass
    
    def _show_update_notification(self, update_info):
        """Güncelleme bildirimi göster."""
        version = update_info.get("version", "?")
        size_mb = update_info.get("size", 0) / (1024 * 1024)
        
        msg = (
            f"Yeni versiyon mevcut!\n\n"
            f"Mevcut: v{CURRENT_VERSION}\n"
            f"Yeni: v{version}\n"
            f"Boyut: {size_mb:.1f} MB\n\n"
            f"Güncellemeyi şimdi indirmek ister misiniz?"
        )
        
        if messagebox.askyesno("Güncelleme Mevcut", msg):
            self._download_and_install_update(update_info)
    
    def _manual_check_update(self):
        """Manuel güncelleme kontrolü."""
        self.btn_check_update.configure(state="disabled", text="⏳ Kontrol ediliyor...")
        self.update_status_label.configure(text="Kontrol ediliyor...", fg=C["accent"])
        threading.Thread(target=self._worker_check_update, daemon=True).start()
    
    def _worker_check_update(self):
        """Güncelleme kontrolü worker thread."""
        try:
            update_info = check_for_update()
            if update_info:
                self._update_info = update_info
                self.root.after(0, lambda: self._on_update_found(update_info))
            else:
                self.root.after(0, self._on_no_update)
        except Exception as e:
            self.root.after(0, lambda: self._on_update_error(str(e)))
    
    def _on_update_found(self, update_info):
        """Güncelleme bulundu."""
        version = update_info.get("version", "?")
        size_mb = update_info.get("size", 0) / (1024 * 1024)
        
        self.btn_check_update.configure(state="normal", text="🔄 Güncellemeleri Kontrol Et")
        self.update_status_label.configure(
            text=f"v{version} mevcut! ({size_mb:.1f} MB)",
            fg=C["green"]
        )
        
        msg = (
            f"Yeni versiyon mevcut!\n\n"
            f"Mevcut: v{CURRENT_VERSION}\n"
            f"Yeni: v{version}\n"
            f"Boyut: {size_mb:.1f} MB\n\n"
            f"Güncellemeyi şimdi indirmek ister misiniz?"
        )
        
        if messagebox.askyesno("Güncelleme Mevcut", msg):
            self._download_and_install_update(update_info)
    
    def _on_no_update(self):
        """Güncelleme yok."""
        self.btn_check_update.configure(state="normal", text="🔄 Güncellemeleri Kontrol Et")
        self.update_status_label.configure(text="En son versiyon kullanılıyor", fg=C["green"])
    
    def _on_update_error(self, error):
        """Güncelleme kontrolü hatası."""
        self.btn_check_update.configure(state="normal", text="🔄 Güncellemeleri Kontrol Et")
        self.update_status_label.configure(text="Kontrol edilemedi", fg=C["red"])
    
    def _download_and_install_update(self, update_info):
        """Güncellemeyi indir ve kur."""
        url = update_info.get("download_url")
        if not url:
            messagebox.showerror("Hata", "İndirme linki bulunamadı!")
            return
        
        self.btn_check_update.configure(state="disabled", text="⏳ İndiriliyor...")
        self.update_status_label.configure(text="İndiriliyor...", fg=C["accent"])
        
        def on_progress(downloaded, total):
            if total > 0:
                pct = (downloaded / total) * 100
                mb_dl = downloaded / (1024 * 1024)
                mb_total = total / (1024 * 1024)
                self.root.after(0, lambda: self.update_status_label.configure(
                    text=f"İndiriliyor: {pct:.1f}% ({mb_dl:.1f}/{mb_total:.1f} MB)",
                    fg=C["accent"]
                ))
        
        def worker():
            try:
                filepath = download_update(url, on_progress)
                if filepath:
                    self.root.after(0, lambda: self._install_update(filepath))
                else:
                    self.root.after(0, lambda: [
                        self.btn_check_update.configure(state="normal", text="🔄 Güncellemeleri Kontrol Et"),
                        self.update_status_label.configure(text="İndirme başarısız", fg=C["red"]),
                        messagebox.showerror("Hata", "Güncelleme indirilemedi!")
                    ])
            except Exception as e:
                self.root.after(0, lambda: [
                    self.btn_check_update.configure(state="normal", text="🔄 Güncellemeleri Kontrol Et"),
                    self.update_status_label.configure(text="Hata oluştu", fg=C["red"]),
                    messagebox.showerror("Hata", f"Güncelleme hatası: {str(e)}")
                ])
        
        threading.Thread(target=worker, daemon=True).start()
    
    def _install_update(self, filepath):
        """Güncellemeyi kur."""
        self.update_status_label.configure(text="Kuruluyor...", fg=C["accent"])
        try:
            apply_update(filepath)
        except Exception as e:
            messagebox.showerror("Hata", f"Kurulum hatası: {str(e)}")
            self.btn_check_update.configure(state="normal", text="🔄 Güncellemeleri Kontrol Et")
            self.update_status_label.configure(text="Kurulum başarısız", fg=C["red"])
    
    def _on_auto_check_changed(self):
        """Otomatik güncelleme kontrolü ayarı değişti."""
        self._config["auto_check_updates"] = self.auto_check_var.get()
        self._save_config()
    
    def _on_auto_dl_changed(self):
        """Otomatik indirme ayarı değişti."""
        self._config["auto_download_updates"] = self.auto_dl_var.get()
        self._save_config()
    
    def _on_discord_enabled_changed(self):
        """Discord webhook aktif/pasif ayarı değişti."""
        self._config["discord_webhook_enabled"] = self.discord_enabled_var.get()
        self._save_config()
    
    def _on_webhook_url_changed(self):
        """Webhook URL değişti."""
        self._config["discord_webhook_url"] = self.webhook_url_entry.get().strip()
        self._save_config()
    
    # ─────────────────────────────────────────────────────────
    # STEAM FONKSİYONLARI
    # ─────────────────────────────────────────────────────────
    def _do_restart_steam(self):
        """Steam'i yeniden başlat."""
        if messagebox.askyesno("Onay", "Steam'i kapatıp yeniden başlatmak istediğinize emin misiniz?"):
            threading.Thread(target=self._worker_restart_steam, daemon=True).start()
    
    def _worker_restart_steam(self):
        """Steam restart worker thread."""
        try:
            self.root.after(0, lambda: self.footer.configure(text="Steam yeniden başlatılıyor..."))
            success = restart_steam()
            if success:
                self.root.after(0, lambda: [
                    self.footer.configure(text="Steam başarıyla yeniden başlatıldı"),
                    messagebox.showinfo("Başarılı", "Steam başarıyla yeniden başlatıldı!")
                ])
            else:
                self.root.after(0, lambda: [
                    self.footer.configure(text="Steam başlatılamadı"),
                    messagebox.showerror("Hata", "Steam başlatılamadı!")
                ])
        except Exception as e:
            self.root.after(0, lambda: [
                self.footer.configure(text="Hata oluştu"),
                messagebox.showerror("Hata", f"Steam yeniden başlatma hatası: {str(e)}")
            ])
    
    # ─────────────────────────────────────────────────────────
    # DISCORD WEBHOOK FONKSİYONLARI
    # ─────────────────────────────────────────────────────────
    def _send_discord_webhook(self, title, description, color=0x66c0f4, fields=None):
        """Discord webhook'a mesaj gönder."""
        if not self._config.get("discord_webhook_enabled", True):
            return
        
        webhook_url = self._config.get("discord_webhook_url", DEFAULT_WEBHOOK_URL)
        if not webhook_url or not webhook_url.startswith("http"):
            return
        
        try:
            embed = {
                "title": title,
                "description": description,
                "color": color,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            }
            
            if fields:
                embed["fields"] = fields
            
            payload = {
                "embeds": [embed],
                "username": "GameInSteam",
                "avatar_url": "https://cdn.akamai.steamstatic.com/steam/apps/730/header.jpg"
            }
            
            threading.Thread(
                target=lambda: requests.post(webhook_url, json=payload, timeout=5),
                daemon=True
            ).start()
        except Exception:
            pass  # Sessizce geç, webhook hatası uygulamayı etkilemesin
    
    def _send_game_added_notification(self, app_id, game_name, success_count=1, total_count=1):
        """Oyun eklendi bildirimi gönder."""
        if total_count == 1:
            title = "🎮 Oyun Eklendi"
            description = f"**{game_name}** (AppID: {app_id}) Steam kütüphanenize eklendi!"
            color = 0x5ba32b  # Yeşil
        else:
            title = "🎮 Oyunlar Eklendi"
            description = f"**{success_count}/{total_count}** oyun başarıyla Steam kütüphanenize eklendi!"
            color = 0x5ba32b if success_count == total_count else 0xd4a017  # Yeşil veya sarı
        
        self._send_discord_webhook(title, description, color)
    
    def _send_game_updated_notification(self, app_id, game_name):
        """Oyun güncellendi bildirimi gönder."""
        title = "🔄 Oyun Güncellendi"
        description = f"**{game_name}** (AppID: {app_id}) güncellendi!"
        color = 0x66c0f4  # Mavi
        self._send_discord_webhook(title, description, color)
    
    def _send_game_removed_notification(self, app_id, game_name):
        """Oyun kaldırıldı bildirimi gönder."""
        title = "🗑️ Oyun Kaldırıldı"
        description = f"**{game_name}** (AppID: {app_id}) Steam kütüphanenizden kaldırıldı!"
        color = 0xc74040  # Kırmızı
        self._send_discord_webhook(title, description, color)

def main():
    root = tk.Tk()
    # DPI Farkındalığı (Net görüntü için)
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except: pass
    app = GameInSteamApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()