import os
import sys
import json
import time
import threading
import requests # type: ignore
import io
import webbrowser
import customtkinter as ctk # type: ignore
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageDraw, ImageTk # type: ignore
from typing import Any
try:
    from steam_handler import ( # type: ignore
        check_stplugin_system, add_shortcut_from_manifest, list_added_games,
        remove_game, update_game, get_game_name_from_steam, restart_steam,
        open_steam_folder, restart_steam
    )
except ImportError:
    print("Error: steam_handler.py not found!")

try:
    from updater import check_for_update, download_update, apply_update, CURRENT_VERSION # type: ignore
except ImportError:
    print("Error: updater.py not found!")
    CURRENT_VERSION = "4.5"
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
    def __init__(self):
        super().__init__()

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
        self._name_cache: dict[str, str] = {}
        self._img_cache: dict[str, Any] = {}
        self._crack_cache: dict[str, Any] = {}
        
        # Generate a fallback image for missing game banners
        fallback_img = Image.new('RGB', (IMG_W, IMG_H), color=self.c_sidebar)
        try:
            draw = ImageDraw.Draw(fallback_img)
            # Try to center the text manually since we might not have a loaded font
            draw.text((IMG_W//2 - 25, IMG_H//2 - 5), "NO IMAGE", fill=self.c_text_dim)
        except Exception:
            pass
        self._empty_img = ImageTk.PhotoImage(fallback_img)
        
        self._busy = False
        self._config: dict[str, Any] = self._load_config()
        self._current_page: str = ""
        
        # Güncelleme Kontrolü Event'i
        self._update_lock = threading.Lock()
        self._update_checking = False
        self._update_dialog_open = False
        self._update_info = None

        # Wishlist & Discover State
        self._name_cache = {}
        self._trending_games = []
        self._categories = ["All", "Cracked", "Protected", "Clean / No DRM"]
        self.current_category = "All"

        # Arayüzü İnşa Et
        self._build_ui()
        self._check_system()

        if self._config.get("auto_check_updates", True):
            threading.Thread(target=self._check_update_on_start, daemon=True).start()

    # ─────────────────────────────────────────────────────────
    # OVERRIDE & CHECK
    # ─────────────────────────────────────────────────────────


    def _load_config(self) -> dict[str, Any]:
        default = {
            "auto_check_updates": True,
            "auto_download_updates": False,
            "discord_webhook_enabled": True,
            "discord_webhook_url": DEFAULT_WEBHOOK_URL,
            "suppressed_version": "0.0"
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

        self._build_dash()
        self._build_lib()
        self._build_settings()

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
        for b in [self.btn_dash, self.btn_lib, self.btn_settings]:
            b.configure(fg_color="transparent", text_color=self.c_text_dim)
        for page in [self.page_dash, self.page_lib, self.page_settings]:
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

    # ─────────────────────────────────────────────────────────
    # DASHBOARD (Oyun Ekleme Sayfası)
    # ─────────────────────────────────────────────────────────
    def _build_dash(self):
        # Dashboard Artık Ana Bir Container İçinde (Scrollable)
        self.dash_scroll = ctk.CTkScrollableFrame(self.page_dash, fg_color="transparent")
        self.dash_scroll.pack(fill="both", expand=True)

        lbl_title = ctk.CTkLabel(self.dash_scroll, text="DASHBOARD", font=ctk.CTkFont("Segoe UI", size=26, weight="bold"), text_color=self.c_text)
        lbl_title.pack(anchor="w", pady=(10, 25), padx=10)
        
        # --- ADD GAME CENTER ---
        add_card = ctk.CTkFrame(self.dash_scroll, fg_color=self.c_card, corner_radius=20)
        add_card.pack(fill="x", pady=(0, 25), padx=5)
        
        add_inner = ctk.CTkFrame(add_card, fg_color="transparent")
        add_inner.pack(padx=25, pady=25, fill="x")

        # Row 1: Quick Find
        ctk.CTkLabel(add_inner, text="🔍 Quick Find (ID or URL Manager)", text_color=self.c_accent, font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w")
        
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_change)
        self.inp_search = ctk.CTkEntry(add_inner, height=45, placeholder_text="Type game name to find AppID...", 
                                        fg_color=self.c_bg, border_color=self.c_sidebar, text_color=self.c_text, textvariable=self.search_var)
        self.inp_search.pack(fill="x", pady=(10, 10))

        # Area for search results
        self.search_results_frame = ctk.CTkScrollableFrame(add_inner, height=0, fg_color=self.c_bg, corner_radius=5)
        # We pack_forget() it dynamically later

        # Row 2: Manual Data
        input_row = ctk.CTkFrame(add_inner, fg_color="transparent")
        input_row.pack(fill="x", pady=10)

        id_col = ctk.CTkFrame(input_row, fg_color="transparent")
        id_col.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkLabel(id_col, text="Steam App ID", text_color=self.c_text_dim, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
        self.inp_id = ctk.CTkEntry(id_col, height=45, placeholder_text="e.g. 730, 440", 
                                   fg_color=self.c_bg, border_color=self.c_sidebar, text_color=self.c_text)
        self.inp_id.pack(fill="x", pady=5)

        name_col = ctk.CTkFrame(input_row, fg_color="transparent")
        name_col.pack(side="left", fill="x", expand=True, padx=(10, 0))
        ctk.CTkLabel(name_col, text="Game Name (Optional)", text_color=self.c_text_dim, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
        self.inp_name = ctk.CTkEntry(name_col, height=45, placeholder_text="Enter name...",
                                     fg_color=self.c_bg, border_color=self.c_sidebar, text_color=self.c_text)
        self.inp_name.pack(fill="x", pady=5)

        # Action Buttons
        btn_container = ctk.CTkFrame(add_inner, fg_color="transparent")
        btn_container.pack(fill="x", pady=(15, 0))

        self.btn_add = ctk.CTkButton(btn_container, text="ADD TO LIBRARY", height=50, fg_color=self.c_accent, text_color=self.c_bg, 
                                     hover_color=self.c_accent_hover, font=ctk.CTkFont(size=14, weight="bold"),
                                     command=self._do_add)
        self.btn_add.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.btn_restart = ctk.CTkButton(btn_container, text="🚀 RESTART STEAM", height=50,
                                         fg_color="#1e293b", text_color="#FFFFFF",
                                         hover_color="#334155", font=ctk.CTkFont(size=14, weight="bold"),
                                         command=self._do_steam_restart)
        self.btn_restart.pack(side="left", fill="x", expand=True, padx=(5, 0))

        self.status_lbl = ctk.CTkLabel(add_inner, text="", text_color=self.c_text_dim)
        self.status_lbl.pack(pady=(15, 0))
        
        self.prog_bar = ctk.CTkProgressBar(add_inner, fg_color=self.c_sidebar, progress_color=self.c_accent, height=8)
        self.prog_bar.set(0)
        self.prog_bar.pack(fill="x", pady=10)



    # ─────────────────────────────────────────────────────────
    # ARAMA (SEARCH) İŞLEMLERİ
    # ─────────────────────────────────────────────────────────
    def _on_search_change(self, *args):
        query = self.search_var.get().strip()
        
        if len(query) < 3:
            self.search_results_frame.pack_forget()
            return
            
        if hasattr(self, '_search_timer'):
            self.after_cancel(self._search_timer)
        self._search_timer = self.after(500, lambda: self._start_search(query))

    def _start_search(self, query):
        for widget in self.search_results_frame.winfo_children():
            widget.destroy()
        self.search_results_frame.pack(fill="x", pady=(5, 0))
        lbl = ctk.CTkLabel(self.search_results_frame, text="Searching Steam Store...", font=ctk.CTkFont(size=12, slant="italic"), text_color=self.c_text_dim)
        lbl.pack(pady=10)
        
        threading.Thread(target=self._perform_steam_search, args=(query,), daemon=True).start()

    def _perform_steam_search(self, query):
        try:
            url = f"https://store.steampowered.com/api/storesearch/?term={query}&l=english&cc=US"
            resp = requests.get(url, timeout=5)
            data = resp.json()
            items = data.get("items", [])[:6]
            
            # --- DENUVO / DRM DEDEKTÖRÜ (Curator Yöntemi) ---
            if items:
                try:
                    # Steam'in API'si Denuvo'yu gizlediği için "Denuvo Games" Curator'ünün listesini çekip oradan ID arıyoruz
                    curator_url = "https://store.steampowered.com/curator/26095454-Denuvo-Games/ajaxgetfilteredrecommendations/render/?query=&start=0&count=1000"
                    c_resp = requests.get(curator_url, timeout=5)
                    c_data = c_resp.json()
                    html_data = c_data.get('results_html', '')
                    
                    for item in items:
                        aid_str = str(item.get("id"))
                        item["has_denuvo"] = False
                        
                        # Eğer ID curator sayfasının HTML kodlarında geçiyorsa, bu oyun %99 Denuvo'ludur veya 3. parti DRM içerir
                        if aid_str in html_data:
                            item["has_denuvo"] = True
                            
                except Exception:
                    pass # İstek başarısız olursa normal listeye devam
                    
            self.after(0, self._render_search_results, items)
        except Exception as e:
            self.after(0, lambda: self._render_search_results([], error=True))

    def _render_search_results(self, items, error=False):
        for widget in self.search_results_frame.winfo_children():
            widget.destroy()
            
        if error:
            lbl = ctk.CTkLabel(self.search_results_frame, text="Search failed. Please check internet.", text_color=self.c_danger)
            lbl.pack(pady=5)
            return
            
        if not items:
            lbl = ctk.CTkLabel(self.search_results_frame, text="No games found.", text_color=self.c_text_dim)
            lbl.pack(pady=5)
            return
            
        for item in items: # Slicing was done in the search function
            app_id = str(item.get("id", ""))
            name = item.get("name", "Unknown Game")
            has_denuvo = item.get("has_denuvo", False)
            
            row = ctk.CTkFrame(self.search_results_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            
            display_text = f"{name}  [{app_id}]"
            text_color = self.c_text
            
            if has_denuvo:
                display_text = f"⚠️ DENUVO/DRM: {name} [{app_id}]"
                text_color = self.c_danger # Kırmızı uyarı rengi
            
            btn = ctk.CTkButton(
                row, 
                text=display_text, 
                anchor="w", 
                fg_color="transparent", 
                text_color=text_color, 
                hover_color=self.c_sidebar,
                command=lambda aid=app_id, n=name, den=has_denuvo: self._select_search_result(aid, n, den)
            )
            btn.pack(fill="x", expand=True)

    def _select_search_result(self, app_id, name, has_denuvo=False):
        if has_denuvo:
            # Kullanıcıyı uyar ama yine de eklemesine izin ver
            msg = f"'{name}' uses Denuvo or a 3rd-party DRM protection.\n\nEven though GameInSteam can add it successfully, the game WILL NOT LAUNCH without a proper bypass ticket.\n\nDo you still want to add it?"
            if not messagebox.askyesno("DRM Protection Warning", msg):
                self.search_var.set("")
                self.search_results_frame.pack_forget()
                return
                
        self.inp_id.delete(0, 'end')
        self.inp_id.insert(0, app_id)
        
        self.inp_name.delete(0, 'end')
        self.inp_name.insert(0, name)
        
        self.search_var.set("")
        self.search_results_frame.pack_forget()

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
        
        # --- SMART CATEGORIES ---
        self.cat_var = ctk.StringVar(value="All")
        self.cat_menu = ctk.CTkOptionMenu(top, values=self._categories, variable=self.cat_var, 
                                         height=28, width=120, fg_color=self.c_sidebar, 
                                         button_color=self.c_sidebar, button_hover_color=self.c_accent,
                                         command=self._filter_library)
        self.cat_menu.pack(side="left", padx=15)
        
        # --- KÜTÜPHANE ARAMA (Library Search) ---
        search_frame = ctk.CTkFrame(top, fg_color="transparent")
        search_frame.pack(side="left", fill="x", expand=True, padx=20)
        
        self.lib_search_var = tk.StringVar()
        self.lib_search_var.trace_add("write", self._filter_library)
        self.lib_search_entry = ctk.CTkEntry(search_frame, height=28, placeholder_text="🔍 Filter by Name or AppID...", 
                                         font=ctk.CTkFont(size=12), fg_color=self.c_bg, border_width=1, 
                                         border_color=self.c_sidebar, textvariable=self.lib_search_var)
        self.lib_search_entry.pack(fill="x")
        
        ctk.CTkButton(top, text="Refresh", width=80, height=28, fg_color=self.c_card, hover_color=self.c_sidebar, 
                      command=self._load_games).pack(side="right")

        self.lib_container = ctk.CTkFrame(self.page_lib, fg_color="transparent")
        self.lib_container.pack(fill="both", expand=True)

    def _filter_library(self, *args):
        query = self.lib_search_var.get().strip().lower()
        cat = self.cat_var.get()
        
        for idx, card in enumerate(self.lib_container.winfo_children()):
            if not hasattr(card, '_app_id'):
                continue
                
            aid = card._app_id
            name = self._name_cache.get(aid, "").lower()
            
            # Category Filter
            status = self._crack_cache.get(aid, {})
            # Use safe retrieval for linting
            is_cracked = bool(status.get("cracked", False))
            match_cat = True
            if cat == "Cracked": match_cat = is_cracked
            elif cat == "Protected": match_cat = not is_cracked and status.get("protection") != "Unknown"
            elif cat == "Clean / No DRM": match_cat = status.get("protection") == "Unknown"
            
            # Text Filter
            match_text = query in name or query in aid
            
            if match_text and match_cat:
                card.pack(fill="x", pady=6) 
            else:
                card.pack_forget()

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
        card._app_id = aid # Attach AppID for quick searching filtering
        card.pack(fill="x", pady=6)
        
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=15)

        img_lbl = tk.Label(row, bg=self.c_bg, image=self._empty_img, bd=0)
        img_lbl.pack(side="left", padx=(0, 20))

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)

        cached = self._name_cache.get(aid, "")
        name_lbl = ctk.CTkLabel(info, text=cached or f"Game #{aid}", font=ctk.CTkFont(size=18, weight="bold"), text_color=self.c_text)
        name_lbl.pack(anchor="w")

        id_row = ctk.CTkFrame(info, fg_color="transparent")
        id_row.pack(anchor="w")
        ctk.CTkLabel(id_row, text=f"AppID: {aid}", font=ctk.CTkFont(size=11), text_color=self.c_text_dim).pack(side="left")
        
        # Status Label (Crack/Denuvo)
        status_lbl = ctk.CTkLabel(id_row, text="checking status...", font=ctk.CTkFont(size=10, weight="bold"), 
                                   fg_color=self.c_sidebar, corner_radius=4, padx=5)
        status_lbl.pack(side="left", padx=10)
        
        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.pack(side="right")

        ctk.CTkButton(btns, text="Update", width=80, fg_color=self.c_sidebar, hover_color=self.c_accent, 
                      command=lambda: self._do_update(aid)).pack(side="left", padx=5)
        ctk.CTkButton(btns, text="Delete", width=50, fg_color=self.c_sidebar, hover_color=self.c_danger, 
                      command=lambda: self._do_remove(aid, card)).pack(side="left", padx=5)

        if not cached: threading.Thread(target=self._fetch_name, args=(aid, name_lbl), daemon=True).start()
        if aid not in self._img_cache: threading.Thread(target=self._fetch_image, args=(aid, img_lbl), daemon=True).start()
        else: img_lbl.configure(image=self._img_cache[aid])
        
        # Fetch Crack Status
        threading.Thread(target=self._fetch_crack_status, args=(aid, cached, status_lbl), daemon=True).start()

    def _fetch_name(self, aid, lbl):
        try:
            name = get_game_name_from_steam(aid)
            if name:
                self._name_cache[aid] = name
                def safe_update():
                    if lbl.winfo_exists():
                        lbl.configure(text=name)
                        # Re-trigger search filter just in case this game matches the current typed query
                        if hasattr(self, 'lib_search_var') and len(self.lib_search_var.get()) > 0:
                            self._filter_library()
                self.after(0, safe_update)
        except Exception:
            pass

    def _fetch_image(self, aid, lbl):
        try:
            url = HEADER_URL.format(aid)
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                img = Image.open(io.BytesIO(resp.content)).resize((IMG_W, IMG_H), Image.LANCZOS)
                from PIL import ImageTk # type: ignore
                photo = ImageTk.PhotoImage(img) # using standard ImageTk inside Tkinter Label is still okay or use CTkImage
                self._img_cache[aid] = photo
                def safe_update():
                    if lbl.winfo_exists():
                        lbl.configure(image=photo)
                self.after(0, safe_update)
        except: pass

    def _fetch_crack_status(self, aid, name, lbl):
        # Check cache
        if aid in self._crack_cache:
            self.after(0, lambda: self._apply_status_ui(lbl, self._crack_cache[aid]))
            return

        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            # Search by AppID first
            r = requests.get(f"https://gamestatus.info/back/api/gameinfo/game/?search={aid}", headers=headers, timeout=10)
            data = r.json()
            results = data.get("results", [])
            
            game_data = None
            for res in results:
                if str(res.get("steam_prod_id")) == str(aid):
                    game_data = res
                    break
            
            if not game_data and name:
                # Fallback to name search
                r = requests.get(f"https://gamestatus.info/back/api/gameinfo/game/?search={name}", headers=headers, timeout=10)
                results = r.json().get("results", [])
                for res in results:
                    if res.get("title").lower() == name.lower():
                        game_data = res
                        break

            if game_data:
                status = {
                    "cracked": bool(game_data.get("crack_date")),
                    "protection": game_data.get("protections", "Unknown"),
                    "date": game_data.get("crack_date") or "Uncracked"
                }
                # Use update to avoid item assignment lint error on some type checkers
                self._crack_cache.update({aid: status})
                def safe_update():
                    if lbl.winfo_exists():
                        self._apply_status_ui(lbl, status)
                self.after(0, safe_update)
            else:
                def safe_not_found():
                    if lbl.winfo_exists():
                        lbl.configure(text="CLEAN / NO DRM", fg_color="#34495e")
                self.after(0, safe_not_found)
        except Exception:
            def safe_err():
                if lbl.winfo_exists():
                    lbl.configure(text="ERROR", fg_color=self.c_danger)
            self.after(0, safe_err)

    def _apply_status_ui(self, lbl, status):
        if status["cracked"]:
            lbl.configure(text=f"CRACKED ({status['date']})", fg_color=self.c_success)
        else:
            prot = status["protection"] if status["protection"] else "PROTECTED"
            lbl.configure(text=prot.upper(), fg_color="#e67e22")



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

        # Discord/Global
        card2 = ctk.CTkFrame(self.page_settings, fg_color=self.c_card, corner_radius=15)
        card2.pack(fill="x", pady=10)
        c2i = ctk.CTkFrame(card2, fg_color="transparent")
        c2i.pack(padx=20, pady=20, fill="x")

        ctk.CTkLabel(c2i, text="Community & Support", font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", pady=(0, 5))
        ctk.CTkLabel(c2i, text="Join our Discord for news and support:", text_color=self.c_text_dim).pack(anchor="w", pady=(0, 10))
        
        discord_btn = ctk.CTkButton(c2i, text="🎮 JOIN DISCORD SERVER", fg_color="#5865F2", text_color="#FFFFFF", 
                                  hover_color="#4752C4", font=ctk.CTkFont(weight="bold"), 
                                  command=lambda: webbrowser.open("https://discord.gg/krzbgakKJf"))
        discord_btn.pack(fill="x", pady=(0, 15))
        
        ctk.CTkButton(c2i, text="SAVE ALL SETTINGS", fg_color=self.c_accent, text_color=self.c_bg, font=ctk.CTkFont(weight="bold"), command=self._save_settings).pack(fill="x")

    def _save_settings(self, *args):
        try:
            self._config["auto_check_updates"] = bool(self.sw_auto_check.get() == 1)
            self._config["auto_download_updates"] = bool(self.sw_auto_dl.get() == 1)
            self._save_config()
        except: pass



    def _do_steam_restart(self):
        """Manuel Steam restart işlemini tetikler"""
        self.status_lbl.configure(text="⏳ Restarting Steam...", text_color=self.c_accent)
        threading.Thread(target=self._worker_steam_restart, daemon=True).start()

    def _worker_steam_restart(self):
        try:
            from steam_handler import restart_steam # type: ignore
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

    def _do_process_manual(self):
        """İndirilen dosyaları otomatik kurar."""
        self.status_lbl.configure(text="⏳ Processing downloads...", text_color=self.c_accent)
        threading.Thread(target=self._worker_process_manual, daemon=True).start()

    def _worker_process_manual(self):
        try:
            results = process_downloads()
            if not results:
                self.after(0, lambda: self.status_lbl.configure(text="ℹ️ No new files found in downloads", text_color=self.c_text_dim))
                return
            
            success = [f for f, ok, m in results if ok]
            failed = [f"{f}: {m}" for f, ok, m in results if not ok]
            
            msg = f"Processed {len(results)} files.\nSuccess: {len(success)}\nFailed: {len(failed)}"
            if failed:
                msg += "\n\nErrors:\n" + "\n".join(failed)
            
            self.after(0, lambda: [
                self.status_lbl.configure(text=f"✅ Processed {len(success)} files", text_color=self.c_success),
                messagebox.showinfo("Import Results", msg),
                self._load_games() if self._current_page == "lib" else None
            ])
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", f"Process error: {str(e)}"))

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
                
                # Callback to update the progress bar and status text dynamically
                def prog_cb(pct, m):
                    # pct is 0.0 to 1.0 from steam_handler
                    self.after(0, lambda p=pct, text=m, i=idx: [
                        self.prog_bar.set(p),
                        self.status_lbl.configure(text=f"[{i+1}/{total}] {text}")
                    ])
                
                ok, msg = add_shortcut_from_manifest(app_id, game_name, on_progress=prog_cb)
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
        self.btn_add.configure(state="disabled" if busy else "normal")
        self.btn_restart.configure(state="disabled" if busy else "normal")
        self.inp_id.configure(state="disabled" if busy else "normal")
        self.inp_name.configure(state="disabled" if busy else "normal")
        self.inp_search.configure(state="disabled" if busy else "normal")
        
        if busy:
            self.status_lbl.configure(text=msg, text_color=self.c_accent)
            self.prog_bar.pack(fill="x", pady=10) # Ensure progress bar is visible
            self.prog_bar.stop() # Ensure indeterminate mode is off
            self.prog_bar.set(0) # Reset to 0 for determinate progress
        else:
            self.btn_add.configure(state="normal", text="ADD")
            self.prog_bar.stop()
            self.prog_bar.set(0)
            self.prog_bar.pack_forget() # Hide progress bar when not busy

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
                ver = update_info.get("version", "")
                if ver == self._config.get("suppressed_version", ""):
                    return
                
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
            if messagebox.askyesno("Update", msg): 
                self._download_and_install_update(update_info)
            else:
                # Suppress this version if user clicks No
                self._config["suppressed_version"] = version
                self._save_config()
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
        if self._update_info:
            ver = self._update_info.get("version", "0.0")
            self._config["suppressed_version"] = ver
            self._save_config()
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
                err_msg = str(e)
                self.after(0, lambda: messagebox.showerror("Error", f"Connection error: {err_msg}"))
        
        threading.Thread(target=worker, daemon=True).start()

    def _send_discord_webhook(self, title, description, color=0x66c0f4, fields=None, thumbnail_url=None):
        if not self._config.get("discord_webhook_enabled", True): return
        webhook_url = self._config.get("discord_webhook_url", DEFAULT_WEBHOOK_URL)
        if not webhook_url or not str(webhook_url).startswith("http"): return
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

def start_main_app():
    # Eğer custom tkinter ile uyumlu bir çözünürlük farkındalığı istiyorsan:
    try:
        from ctypes import windll # type: ignore
        windll.shcore.SetProcessDpiAwareness(1)
    except: pass
    
    app = GameInSteamApp()
    app.mainloop()

def main():
    start_main_app()

if __name__ == "__main__":
    main()