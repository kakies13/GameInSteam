import os
import sys
import json
import time
import threading
import requests
import io
import webbrowser
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from PIL import Image

try:
    from steam_handler import (
        check_stplugin_system, add_shortcut_from_manifest, list_added_games,
        remove_game, update_game, get_game_name_from_steam, restart_steam
    )
except ImportError:
    print("Error: steam_handler.py not found!")

try:
    from updater import check_for_update, download_update, apply_update, CURRENT_VERSION
except ImportError:
    print("Error: updater.py not found!")
    CURRENT_VERSION = "4.1"
    def check_for_update(): return None
    def download_update(*args): return None
    def apply_update(*args): pass

SESSION_FILE = ".gameinsteam_session.json"
CONFIG_FILE = "config.json"
HEADER_URL = "https://cdn.akamai.steamstatic.com/steam/apps/{}/header.jpg"
IMG_W, IMG_H = 180, 85
DEFAULT_WEBHOOK_URL = ""

# Modern Koyu Tema
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class GameInSteamApp(ctk.CTk):
    def __init__(self, user):
        super().__init__()
        self.user = user

        # Temel Ayarlar
        self.title("GameInSteam - Steam Library Manager")
        self.geometry("1000x650")
        self.minsize(900, 600)
        
        # Tema Renkleri (Camgöbeği/Lacivert konseptine uygun)
        self.c_bg = "#0B0F19" # Arka plan
        self.c_sidebar = "#121A2F" # Yan menü
        self.c_card = "#162032" # Kart arka planı
        self.c_accent = "#00E5FF" # Camgöbeği Parlak Mavi
        self.c_accent_hover = "#00B8CC"
        self.c_text = "#FFFFFF"
        self.c_text_dim = "#8B9BB4"
        self.c_danger = "#EF4444"
        self.c_danger_hover = "#DC2626"
        self.c_success = "#10B981"
        
        self.configure(fg_color=self.c_bg)

        # Durum ve Data Yönetimi
        self._name_cache = {}
        self._img_cache = {}
        self._busy = False
        self._config = self._load_config()
        self._current_page = None
        
        self._check_license()
        
        # Güncelleme Kontrolü Event'i
        self._update_lock = threading.Lock()
        self._update_checking = False
        self._update_dialog_open = False
        self._update_info = None

        # Arayüzü İnşa Et
        self._build_ui()
        self._check_system()

        if self._config.get("auto_check_updates", True):
            threading.Thread(target=self._check_update_on_start, daemon=True).start()

    # ─────────────────────────────────────────────────────────
    # OVERRIDE & CHECK
    # ─────────────────────────────────────────────────────────
    def _check_license(self):
        try:
            plan = self.user.user_metadata.get("plan", None)
            if not plan:
                self._show_no_license_error()
        except AttributeError:
             self._show_no_license_error()
             
    def _show_no_license_error(self):
        messagebox.showerror(
            "Access Denied", 
            "You do not have a valid GameInSteam subscription.\nPlease purchase a Premium plan from our website."
        )
        self.destroy()
        sys.exit(0)

    def _load_config(self):
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
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────
    # ARAYÜZ YAPILANDIRMASI
    # ─────────────────────────────────────────────────────────
    def _build_ui(self):
        # --- Sol Menü (Sidebar) ---
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=self.c_sidebar)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        
        # Logo ve Başlık
        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(pady=(25, 30), padx=20, fill="x")
        
        ctk.CTkLabel(logo_frame, text="🎮", font=ctk.CTkFont(size=28)).pack(side="left", padx=(0, 10))
        text_frame = ctk.CTkFrame(logo_frame, fg_color="transparent")
        text_frame.pack(side="left", fill="x")
        
        ctk.CTkLabel(text_frame, text="GAME IN STEAM", font=ctk.CTkFont("Segoe UI", size=14, weight="bold"), text_color=self.c_text).pack(anchor="w")
        ctk.CTkLabel(text_frame, text="Library Manager", font=ctk.CTkFont("Segoe UI", size=10), text_color=self.c_text_dim).pack(anchor="w")

        # Butonlar
        self.btn_dash = self._create_nav_button("DASHBOARD", "add", self._show_dash)
        self.btn_lib = self._create_nav_button("LIBRARY", "lib", self._show_lib)
        self.btn_settings = self._create_nav_button("SETTINGS", "settings", self._show_settings)
        self.btn_profile = self._create_nav_button("PROFILE", "profile", self._show_profile)

        # Alt Bilgi ve Durum
        self.sys_status_lbl = ctk.CTkLabel(self.sidebar, text="Checking system...", text_color=self.c_text_dim, font=ctk.CTkFont(size=11))
        self.sys_status_lbl.pack(side="bottom", pady=20, padx=20, anchor="w")
        
        ctk.CTkLabel(self.sidebar, text=f"v{CURRENT_VERSION}", text_color=self.c_text_dim, font=ctk.CTkFont(size=10)).pack(side="bottom", anchor="w", padx=20)

        # --- Sağ İçerik Alanı (Main Frame) ---
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=self.c_bg)
        self.main_frame.pack(side="right", fill="both", expand=True)
        
        # Sayfalar
        self.page_dash = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.page_lib = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        self.page_settings = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        self.page_profile = ctk.CTkFrame(self.main_frame, fg_color="transparent")

        self._build_dash()
        self._build_lib()
        self._build_settings()
        self._build_profile()

        # İlk sayfa
        self._show_dash()

    def _create_nav_button(self, text, tag, command):
        """Sol menü butonlarını oluşturur"""
        btn = ctk.CTkButton(
            self.sidebar, text=f"  {text}", font=ctk.CTkFont("Segoe UI", size=12, weight="bold"),
            fg_color="transparent", text_color=self.c_text_dim, anchor="w",
            hover_color=self.c_card, height=40, corner_radius=8, command=command
        )
        btn.pack(fill="x", padx=15, pady=4)
        btn._tag = tag
        return btn

    def _reset_nav(self):
        for b in [self.btn_dash, self.btn_lib, self.btn_settings, self.btn_profile]:
            b.configure(fg_color="transparent", text_color=self.c_text_dim)
        for page in [self.page_dash, self.page_lib, self.page_settings, self.page_profile]:
            page.pack_forget()

    def _show_dash(self):
        self._reset_nav()
        self.btn_dash.configure(fg_color=self.c_accent, text_color=self.c_bg)
        self.page_dash.pack(fill="both", expand=True, padx=30, pady=30)
        self._current_page = "dash"

    def _show_lib(self):
        self._reset_nav()
        self.btn_lib.configure(fg_color=self.c_accent, text_color=self.c_bg)
        self.page_lib.pack(fill="both", expand=True, padx=30, pady=30)
        self._current_page = "lib"
        self._load_games()

    def _show_settings(self):
        self._reset_nav()
        self.btn_settings.configure(fg_color=self.c_accent, text_color=self.c_bg)
        self.page_settings.pack(fill="both", expand=True, padx=30, pady=30)
        self._current_page = "settings"

    def _show_profile(self):
        self._reset_nav()
        self.btn_profile.configure(fg_color=self.c_accent, text_color=self.c_bg)
        self.page_profile.pack(fill="both", expand=True, padx=30, pady=30)
        self._current_page = "profile"

    # ─────────────────────────────────────────────────────────
    # DASHBOARD (Oyun Ekleme Sayfası)
    # ─────────────────────────────────────────────────────────
    def _build_dash(self):
        lbl_title = ctk.CTkLabel(self.page_dash, text="ONE-CLICK ADD", font=ctk.CTkFont("Segoe UI", size=24, weight="bold"), text_color=self.c_text)
        lbl_title.pack(anchor="w", pady=(0, 20))

        card = ctk.CTkFrame(self.page_dash, fg_color=self.c_card, corner_radius=15)
        card.pack(fill="x", pady=10)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(padx=25, pady=25, fill="x")

        # App ID
        ctk.CTkLabel(inner, text="Steam App ID", text_color=self.c_text_dim, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 5))
        self.inp_id = ctk.CTkEntry(inner, height=45, placeholder_text="Can add multiple, separate with commas (e.g., 730, 440)", 
                                   fg_color=self.c_bg, border_color=self.c_sidebar, text_color=self.c_text)
        self.inp_id.pack(fill="x", pady=(0, 15))

        # Oyun Adı
        ctk.CTkLabel(inner, text="Game Name (Optional)", text_color=self.c_text_dim, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 5))
        self.inp_name = ctk.CTkEntry(inner, height=45, placeholder_text="In bulk adding, name is determined automatically...",
                                     fg_color=self.c_bg, border_color=self.c_sidebar, text_color=self.c_text)
        self.inp_name.pack(fill="x", pady=(0, 20))

        self.btn_add = ctk.CTkButton(inner, text="ADD", height=45, fg_color=self.c_accent, text_color=self.c_bg, 
                                     hover_color=self.c_accent_hover, font=ctk.CTkFont(weight="bold"),
                                     command=self._do_add)
        self.btn_add.pack(fill="x", pady=(0, 10))

        # Steam Restart Butonu
        self.btn_restart = ctk.CTkButton(inner, text="RESTART STEAM", height=45, 
                                         fg_color="transparent", border_width=2, border_color=self.c_accent,
                                         text_color=self.c_accent, hover_color=self.c_card, 
                                         font=ctk.CTkFont(weight="bold"),
                                         command=self._do_steam_restart)
        self.btn_restart.pack(fill="x")

        self.status_lbl = ctk.CTkLabel(inner, text="", text_color=self.c_text_dim)
        self.status_lbl.pack(pady=(10, 0))

        self.prog_bar = ctk.CTkProgressBar(inner, fg_color=self.c_sidebar, progress_color=self.c_accent, height=8)
        self.prog_bar.set(0)

    # ─────────────────────────────────────────────────────────
    # KÜTÜPHANE SAYFASI (Library)
    # ─────────────────────────────────────────────────────────
    def _build_lib(self):
        lbl_title = ctk.CTkLabel(self.page_lib, text="MY LIBRARY", font=ctk.CTkFont("Segoe UI", size=24, weight="bold"), text_color=self.c_text)
        lbl_title.pack(anchor="w", pady=(0, 5))
        
        top = ctk.CTkFrame(self.page_lib, fg_color="transparent")
        top.pack(fill="x", pady=(0, 15))
        
        self.lib_count = ctk.CTkLabel(top, text="Added Games: 0", text_color=self.c_text_dim)
        self.lib_count.pack(side="left")
        
        ctk.CTkButton(top, text="Refresh", width=80, height=28, fg_color=self.c_card, hover_color=self.c_sidebar, 
                      command=self._load_games).pack(side="right")

        self.lib_container = ctk.CTkFrame(self.page_lib, fg_color="transparent")
        self.lib_container.pack(fill="both", expand=True)

    def _load_games(self):
        for w in self.lib_container.winfo_children(): w.destroy()
        try:
            games = list_added_games()
            self.lib_count.configure(text=f"Added Games: {len(games)}")
            if not games:
                ctk.CTkLabel(self.lib_container, text="Your library is empty.", text_color=self.c_text_dim, pady=50).pack()
                return
            for g in games: self._game_card(g)
        except Exception as e: 
            print("Listed games err:", e)

    def _game_card(self, g):
        aid = g["app_id"]
        card = ctk.CTkFrame(self.lib_container, fg_color=self.c_card, corner_radius=10)
        card.pack(fill="x", pady=6)
        
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=15)

        img_lbl = tk.Label(row, bg=self.c_bg, width=180, height=85)
        img_lbl.pack(side="left", padx=(0, 20))

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)

        cached = self._name_cache.get(aid, "")
        name_lbl = ctk.CTkLabel(info, text=cached or f"Game #{aid}", font=ctk.CTkFont(size=18, weight="bold"), text_color=self.c_text)
        name_lbl.pack(anchor="w")

        ctk.CTkLabel(info, text=f"AppID: {aid}", font=ctk.CTkFont(size=11), text_color=self.c_accent).pack(anchor="w")
        
        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.pack(side="right")

        ctk.CTkButton(btns, text="Update", width=80, fg_color=self.c_sidebar, hover_color=self.c_accent, 
                      command=lambda: self._do_update(aid)).pack(side="left", padx=5)
        ctk.CTkButton(btns, text="Delete", width=50, fg_color=self.c_sidebar, hover_color=self.c_danger, 
                      command=lambda: self._do_remove(aid, card)).pack(side="left", padx=5)

        if not cached: threading.Thread(target=self._fetch_name, args=(aid, name_lbl), daemon=True).start()
        if aid not in self._img_cache: threading.Thread(target=self._fetch_image, args=(aid, img_lbl), daemon=True).start()
        else: img_lbl.configure(image=self._img_cache[aid])

    def _fetch_name(self, aid, lbl):
        try:
            name = get_game_name_from_steam(aid)
            if name:
                self._name_cache[aid] = name
                # Avoid GUI thread error if widget is destroyed
                def safe_lbl():
                    try: lbl.configure(text=name)
                    except: pass
                self.after(0, safe_lbl)
        except: pass

    def _fetch_image(self, aid, lbl):
        try:
            url = HEADER_URL.format(aid)
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                img = Image.open(io.BytesIO(resp.content)).resize((IMG_W, IMG_H), Image.LANCZOS)
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(img) # using standard ImageTk inside Tkinter Label is still okay or use CTkImage
                self._img_cache[aid] = photo
                def safe_update():
                    try: lbl.configure(image=photo)
                    except: pass
                self.after(0, safe_update)
        except: pass

    # ─────────────────────────────────────────────────────────
    # AYARLAR (Settings)
    # ─────────────────────────────────────────────────────────
    def _build_settings(self):
        lbl_title = ctk.CTkLabel(self.page_settings, text="SETTINGS", font=ctk.CTkFont("Segoe UI", size=24, weight="bold"), text_color=self.c_text)
        lbl_title.pack(anchor="w", pady=(0, 20))

        # Güncellemeler
        card1 = ctk.CTkFrame(self.page_settings, fg_color=self.c_card, corner_radius=15)
        card1.pack(fill="x", pady=10)
        c1i = ctk.CTkFrame(card1, fg_color="transparent")
        c1i.pack(padx=20, pady=20, fill="x")
        
        ctk.CTkLabel(c1i, text="Software Updates", font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", pady=(0, 10))
        
        self.sw_auto_check = ctk.CTkSwitch(c1i, text="Check for Updates on Startup", progress_color=self.c_accent, command=self._save_settings)
        if self._config.get("auto_check_updates", True): self.sw_auto_check.select()
        self.sw_auto_check.pack(anchor="w", pady=5)
        
        self.sw_auto_dl = ctk.CTkSwitch(c1i, text="Download Automatically (Beta)", progress_color=self.c_accent, command=self._save_settings)
        if self._config.get("auto_download_updates", False): self.sw_auto_dl.select()
        self.sw_auto_dl.pack(anchor="w", pady=5)

        self.btn_check_update = ctk.CTkButton(c1i, text="Check for Updates", fg_color=self.c_sidebar, hover_color=self.c_accent, command=self._manual_check_update)
        self.btn_check_update.pack(anchor="w", pady=(15, 0))
        self.update_status_label = ctk.CTkLabel(c1i, text="", text_color=self.c_text_dim)
        self.update_status_label.pack(anchor="w")

        # Steam Paneli
        card2 = ctk.CTkFrame(self.page_settings, fg_color=self.c_card, corner_radius=15)
        card2.pack(fill="x", pady=10)
        c2i = ctk.CTkFrame(card2, fg_color="transparent")
        c2i.pack(padx=20, pady=20, fill="x")
        
        ctk.CTkLabel(c2i, text="Steam Integration", font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", pady=(0, 10))
        ctk.CTkLabel(c2i, text="Steam may need to be closed and reopened after adding or removing games.", text_color=self.c_text_dim).pack(anchor="w", pady=(0, 10))
        ctk.CTkButton(c2i, text="Restart Steam", fg_color=self.c_success, hover_color="#0d9468", command=self._do_restart_steam).pack(anchor="w")

    def _save_settings(self, *args):
        self._config["auto_check_updates"] = self.sw_auto_check.get() == 1
        self._config["auto_download_updates"] = self.sw_auto_dl.get() == 1
        # Discord settings now persistent from config only, no UI update here
        self._save_config()

    # ─────────────────────────────────────────────────────────
    # PROFİL SAYFASI (YENİ)
    # ─────────────────────────────────────────────────────────
    def _build_profile(self):
        lbl_title = ctk.CTkLabel(self.page_profile, text="PROFILE", font=ctk.CTkFont("Segoe UI", size=24, weight="bold"), text_color=self.c_text)
        lbl_title.pack(anchor="w", pady=(0, 20))

        card = ctk.CTkFrame(self.page_profile, fg_color=self.c_card, corner_radius=15)
        card.pack(fill="x", pady=10)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(padx=30, pady=30, fill="x")

        # Veritabanından gelen kullanıcı eklentileri (Plan & E-Posta)
        email = self.user.email if hasattr(self.user, 'email') else "Unknown User"
        plan = self.user.user_metadata.get("plan", "Unknown Plan")
        
        ctk.CTkLabel(inner, text="ACCOUNT INFORMATION", text_color=self.c_text_dim, font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", pady=(0, 5))
        ctk.CTkLabel(inner, text=email, font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", pady=(0, 15))

        # Abonelik Kartı
        sub_frame = ctk.CTkFrame(inner, fg_color=self.c_sidebar, corner_radius=8)
        sub_frame.pack(fill="x", pady=(0, 20))
        
        ctk.CTkLabel(sub_frame, text="Subscription Status:", font=ctk.CTkFont(size=14)).pack(side="left", padx=15, pady=15)
        ctk.CTkLabel(sub_frame, text=f"💎 {plan}", font=ctk.CTkFont(size=14, weight="bold"), text_color=self.c_accent).pack(side="right", padx=15, pady=15)

        # Discord & Çıkış Yap alanı
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(10, 0))

        ctk.CTkButton(
            btn_frame, text="💬 Join Community Discord", fg_color="#5865F2", hover_color="#4752C4", height=40, font=ctk.CTkFont(weight="bold"),
            command=lambda: webbrowser.open("https://discord.gg/")  # Opsiyonel: Kendi sunucu bağlantını ekle
        ).pack(side="left", expand=True, fill="x", padx=(0, 10))

        ctk.CTkButton(
            btn_frame, text="✖ Logout", fg_color="transparent", border_width=1, border_color=self.c_danger, 
            text_color=self.c_danger, hover_color=self.c_danger_hover, height=40, font=ctk.CTkFont(weight="bold"),
            command=self._do_logout
        ).pack(side="right", expand=True, fill="x", padx=(10, 0))

    def _do_logout(self):
        if messagebox.askyesno("Exit", "You will be logged out and returned to the login screen. Do you confirm?"):
            if os.path.exists(SESSION_FILE):
                os.remove(SESSION_FILE)
            self.destroy()
            sys.exit(0) # main.py'ın programı kapatıp/yeniden açması için güvenli yol

    def _do_steam_restart(self):
        """Manuel Steam restart işlemini tetikler"""
        self.status_lbl.configure(text="⏳ Restarting Steam...", text_color=self.c_accent)
        threading.Thread(target=self._worker_steam_restart, daemon=True).start()

    def _worker_steam_restart(self):
        try:
            from steam_handler import restart_steam
            ok = restart_steam()
            if ok:
                self.after(0, lambda: [
                    self.status_lbl.configure(text="✅ Steam successfully restarted", text_color=self.c_success),
                    messagebox.showinfo("Success", "Steam successfully restarted!")
                ])
            else:
                self.after(0, lambda: [
                    self.status_lbl.configure(text="❌ Steam failed to start!", text_color=self.c_danger),
                    messagebox.showerror("Error", "Steam.exe not found or could not be started.")
                ])
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", f"Unexpected error: {str(e)}"))

    # ─────────────────────────────────────────────────────────
    # LOGIC (Ekleme, Güncelleme, Kaldırma)
    # ─────────────────────────────────────────────────────────
    def _check_system(self):
        try:
            ok, msg = check_stplugin_system()
            if ok:
                self.sys_status_lbl.configure(text="✅ stplug-in ready (System Active)", text_color=self.c_success)
            else:
                self.sys_status_lbl.configure(text=f"⚠️ {msg.split('\n')[0]}", text_color="#f59e0b")
        except: pass

    def _do_add(self):
        app_ids_str = self.inp_id.get().strip()
        name = self.inp_name.get().strip()
        if not app_ids_str:
            messagebox.showerror("Error", "Enter a valid App ID.")
            return

        app_ids = [aid.strip() for aid in app_ids_str.split(",") if aid.strip()]
        valid_ids = []
        for aid in app_ids:
            if aid.isdigit(): valid_ids.append(aid)
            else:
                messagebox.showerror("Error", f"Invalid App ID: {aid}")
                return
        
        if not valid_ids: return

        if not name and len(valid_ids) == 1: name = f"Game_{valid_ids[0]}"
        elif not name: name = f"{len(valid_ids)} Games"
        
        self._set_busy(True, f"Adding {len(valid_ids)} games...")
        threading.Thread(target=self._worker_add_multiple, args=(valid_ids, name), daemon=True).start()

    def _worker_add_multiple(self, app_ids, base_name):
        results = []
        total = len(app_ids)
        for idx, app_id in enumerate(app_ids):
            try:
                game_name = base_name if total == 1 else f"{base_name} ({idx+1}/{total})"
                self.after(0, lambda i=idx+1, t=total: self._update_progress(f"Adding game {i}/{t}..."))
                ok, msg = add_shortcut_from_manifest(app_id, game_name)
                results.append((app_id, ok, msg))
            except Exception as e:
                results.append((app_id, False, str(e)))
        self.after(0, lambda: self._done_add_multiple(results))

    def _update_progress(self, msg):
        self.status_lbl.configure(text=msg)
    
    def _done_add_multiple(self, results):
        self._set_busy(False)
        self._check_system()
        
        success_count = sum(1 for _, ok, _ in results if ok)
        total_count = len(results)
        
        if success_count == total_count:
            self.status_lbl.configure(text=f"✅ {success_count} games ready! (Restart Required)", text_color=self.c_success)
            messagebox.showinfo("Success", f"{success_count} games successfully prepared!\n\nPlease click the 'Restart Steam' button.")
        elif success_count > 0:
            failed = [aid for aid, ok, _ in results if not ok]
            msg = f"{success_count}/{total_count} games prepared.\n\nFailed:\n" + "\n".join(failed) + "\n\nRestart Steam for changes to take effect."
            self.status_lbl.configure(text=f"⚠️ {success_count} partial success (Restart Required)", text_color="#f59e0b")
            messagebox.showwarning("Partial Success", msg)
        else:
            self.status_lbl.configure(text="❌ Operation failed", text_color=self.c_danger)
            failed = [f"{aid}: {msg}" for aid, _, msg in results]
            messagebox.showerror("Error", "Could not add games:\n\n" + "\n".join(failed))
        
        if success_count > 0:
            try:
                first_app_id = results[0][0] if results else ""
                base_name = self.inp_name.get().strip() or f"{success_count} Games"
                self._send_game_added_notification(first_app_id, base_name, success_count, total_count)
            except Exception: pass
        
        self.inp_id.delete(0, 'end')
        self.inp_name.delete(0, 'end')

    def _set_busy(self, busy, msg=""):
        self._busy = busy
        if busy:
            self.btn_add.configure(state="disabled", text="PLEASE WAIT")
            self.status_lbl.configure(text=msg, text_color=self.c_accent)
            self.prog_bar.pack(fill="x", pady=10)
            self.prog_bar.start()
        else:
            self.btn_add.configure(state="normal", text="ADD")
            self.prog_bar.stop()
            self.prog_bar.pack_forget()

    def _do_update(self, aid):
        threading.Thread(target=lambda: self._worker_update(aid), daemon=True).start()

    def _worker_update(self, aid):
        ok, msg = update_game(aid)
        if ok:
            try:
                game_name = get_game_name_from_steam(aid) or f"Game_{aid}"
                self.after(0, lambda: self._send_game_updated_notification(aid, game_name))
            except: pass
        self.after(0, lambda: [self._load_games(), messagebox.showinfo("Info", msg)])

    def _do_remove(self, aid, card):
        if messagebox.askyesno("Confirm", "Are you sure you want to remove?"):
            ok, msg = remove_game(aid)
            if ok:
                card.destroy()
                try:
                    game_name = get_game_name_from_steam(aid) or f"Game_{aid}"
                    self._send_game_removed_notification(aid, game_name)
                except: pass
            else:
                messagebox.showerror("Error", msg)

    # ─────────────────────────────────────────────────────────
    # UPDATES & NOTIFICATIONS
    # ─────────────────────────────────────────────────────────
    def _check_update_on_start(self):
        time.sleep(2)
        with self._update_lock:
            if self._update_checking or self._update_dialog_open: return
            self._update_checking = True
        try:
            update_info = check_for_update()
            if update_info:
                self._update_info = update_info
                with self._update_lock:
                    if not self._update_dialog_open:
                        self.after(0, lambda: self._show_update_notification(update_info))
        except: pass
        finally:
            with self._update_lock: self._update_checking = False
    
    def _show_update_notification(self, update_info):
        with self._update_lock:
            if self._update_dialog_open: return
            self._update_dialog_open = True
        version = update_info.get("version", "?")
        size_mb = update_info.get("size", 0) / (1024 * 1024)
        msg = f"New version available!\n\nCurrent: v{CURRENT_VERSION}\nNew: v{version}\nSize: {size_mb:.1f} MB\n\nWould you like to download the update?"
        try:
            if messagebox.askyesno("Update", msg): self._download_and_install_update(update_info)
        finally:
            with self._update_lock: self._update_dialog_open = False

    def _manual_check_update(self):
        with self._update_lock:
            if self._update_checking or self._update_dialog_open: return
        self.btn_check_update.configure(state="disabled", text="Checking...")
        threading.Thread(target=self._worker_check_update, daemon=True).start()

    def _worker_check_update(self):
        with self._update_lock:
            if self._update_checking or self._update_dialog_open: return
            self._update_checking = True
        try:
            update_info = check_for_update()
            if update_info:
                self._update_info = update_info
                with self._update_lock:
                    if not self._update_dialog_open:
                        self.after(0, lambda: self._on_update_found(update_info))
            else:
                self.after(0, self._on_no_update)
        except Exception as e:
            self.after(0, lambda: self._on_update_error(str(e)))
        finally:
            with self._update_lock: self._update_checking = False
    
    def _on_update_found(self, update_info):
        with self._update_lock:
            if self._update_dialog_open: return
            self._update_dialog_open = True
        version = update_info.get("version", "?")
        size_mb = update_info.get("size", 0) / (1024 * 1024)
        self.btn_check_update.configure(state="normal", text="Check for Updates")
        self.update_status_label.configure(text=f"v{version} available! ({size_mb:.1f} MB)", text_color=self.c_success)
        msg = f"New version available!\n\nCurrent: v{CURRENT_VERSION}\nNew: v{version}\nSize: {size_mb:.1f} MB\n\nWould you like to download the update?"
        try:
            if messagebox.askyesno("Update Available", msg):
                self._download_and_install_update(update_info)
        finally:
            with self._update_lock: self._update_dialog_open = False
            
    def _on_no_update(self):
        self.btn_check_update.configure(state="normal", text="Check for Updates")
        self.update_status_label.configure(text="Using the latest version.", text_color=self.c_success)

    def _on_update_error(self, error):
        self.btn_check_update.configure(state="normal", text="Check for Updates")
        self.update_status_label.configure(text="Connection to system failed.", text_color=self.c_danger)

    def _download_and_install_update(self, update_info):
        url = update_info.get("download_url")
        if not url: return
        self.btn_check_update.configure(state="disabled", text="Downloading...")
        
        def on_progress(downloaded, total):
            if total > 0:
                pct = (downloaded / total) * 100
                mb_dl = downloaded / (1024 * 1024)
                mb_total = total / (1024 * 1024)
                self.after(0, lambda: self.update_status_label.configure(
                    text=f"Downloading: {pct:.1f}% ({mb_dl:.1f}/{mb_total:.1f} MB)", text_color=self.c_accent))
        
        def worker():
            try:
                filepath = download_update(url, on_progress)
                if filepath: self.after(0, lambda: self._install_update(filepath))
                else: self.after(0, lambda: [self.btn_check_update.configure(state="normal", text="Updated..."), messagebox.showerror("Error", "Download failed!")])
            except Exception as e:
                self.after(0, lambda: [self.btn_check_update.configure(state="normal", text="Updated..."), messagebox.showerror("Error", str(e))])
        threading.Thread(target=worker, daemon=True).start()
    
    def _install_update(self, filepath):
        self.update_status_label.configure(text="Installing...")
        try: apply_update(filepath)
        except Exception as e:
            messagebox.showerror("Error", f"Installation error: {str(e)}")
            self.btn_check_update.configure(state="normal", text="Retry")

    def _do_restart_steam(self):
        if messagebox.askyesno("Confirm", "Do you want to close and restart Steam?"):
            threading.Thread(target=self._worker_restart_steam, daemon=True).start()
            
    def _worker_restart_steam(self):
        try:
            success = restart_steam()
            if success: self.after(0, lambda: messagebox.showinfo("Info", "Steam restarted."))
            else: self.after(0, lambda: messagebox.showerror("Error", "Steam failed to start."))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))

    def _test_discord_webhook(self):
        """Sends a test message to the configured Discord Webhook."""
        self._save_settings() # Ensure URL is saved
        url = self._config.get("discord_webhook_url", "")
        if not url:
            messagebox.showwarning("Warning", "Please enter a Webhook URL first.")
            return
            
        def worker():
            try:
                payload = {
                    "embeds": [{
                        "title": "✅ Webhook Test",
                        "description": "GameInSteam Discord notifications are working correctly!",
                        "color": 0x10B981,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                        "footer": {"text": "Sent from GameInSteam v" + CURRENT_VERSION}
                    }],
                    "username": "GameInSteam"
                }
                resp = requests.post(url, json=payload, timeout=8)
                if resp.status_code in [200, 204]:
                    self.after(0, lambda: messagebox.showinfo("Success", "Test message sent successfully!"))
                else:
                    self.after(0, lambda: messagebox.showerror("Error", f"Failed to send! Discord returned: {resp.status_code}"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Connection error: {str(e)}"))
        
        threading.Thread(target=worker, daemon=True).start()

    def _send_discord_webhook(self, title, description, color=0x66c0f4, fields=None, thumbnail_url=None):
        if not self._config.get("discord_webhook_enabled", True): return
        webhook_url = self._config.get("discord_webhook_url", DEFAULT_WEBHOOK_URL)
        if not webhook_url or not webhook_url.startswith("http"): return
        try:
            embed = {
                "title": title, "description": description, "color": color,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            }
            if fields: embed["fields"] = fields
            if thumbnail_url: embed["thumbnail"] = {"url": thumbnail_url}
            payload = {
                "embeds": [embed], "username": "GameInSteam",
                "avatar_url": "https://cdn.akamai.steamstatic.com/steam/apps/730/header.jpg"
            }
            
            def do_post():
                try: requests.post(webhook_url, json=payload, timeout=8)
                except: pass
                
            threading.Thread(target=do_post, daemon=True).start()
        except: pass

    def _send_game_added_notification(self, app_id, game_name, success_count=1, total_count=1):
        if total_count == 1:
            self._send_discord_webhook("New Game Added!", f"**Game:** {game_name}\n**App ID:** {app_id}", 0x5ba32b, thumbnail_url=HEADER_URL.format(app_id))
        else:
            self._send_discord_webhook("🎮 Games Added", f"**{success_count}/{total_count}** games successfully added!", 0x5ba32b if success_count == total_count else 0xd4a017)

    def _send_game_updated_notification(self, app_id, game_name):
        self._send_discord_webhook("🔄 Game Updated", f"**Game:** {game_name}\n**App ID:** {app_id}", 0x66c0f4, thumbnail_url=HEADER_URL.format(app_id))

    def _send_game_removed_notification(self, app_id, game_name):
        self._send_discord_webhook("🗑️ Game Removed", f"**Game:** {game_name}\n**App ID:** {app_id}", 0xc74040, thumbnail_url=HEADER_URL.format(app_id))

def start_main_app(user):
    # Eğer custom tkinter ile uyumlu bir çözünürlük farkındalığı istiyorsan:
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except: pass
    
    app = GameInSteamApp(user)
    app.mainloop()

def main():
    try:
        from auth import run_auth_flow
        run_auth_flow(on_success_callback=start_main_app)
    except ImportError:
        print("auth.py missing, default run fallback")
        start_main_app(None)

if __name__ == "__main__":
    main()