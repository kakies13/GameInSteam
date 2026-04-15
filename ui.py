import os
import json
import time
import threading
import requests  # type: ignore
import io
import webbrowser
import customtkinter as ctk  # type: ignore
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageDraw, ImageTk  # type: ignore
from typing import Any

try:
    from steam_handler import (  # type: ignore
        check_stplugin_system, add_shortcut_from_manifest, list_added_games,
        list_recent_games, remove_game, update_game, get_game_name_from_steam,
        restart_steam, get_gamelist_repo_games, is_game_in_repo,
    )
except ImportError:
    print("Error: steam_handler.py not found!")

try:
    from updater import check_for_update, download_update, apply_update, CURRENT_VERSION  # type: ignore
except ImportError:
    CURRENT_VERSION = "5.0"
    def check_for_update(): return None
    def download_update(*a): return None
    def apply_update(*a): pass

CONFIG_FILE = "config.json"
HEADER_URL  = "https://cdn.akamai.steamstatic.com/steam/apps/{}/header.jpg"
IMG_W, IMG_H = 184, 86
DEFAULT_WEBHOOK_URL = ""

SPIN_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def _time_ago(mtime: float) -> str:
    diff = time.time() - mtime
    if diff < 60:   return "just now"
    if diff < 3600: return f"{int(diff//60)}m ago"
    if diff < 86400:return f"{int(diff//3600)}h ago"
    d = int(diff // 86400)
    return f"{d} day{'s' if d>1 else ''} ago"


def _hex_lerp(c1: str, c2: str, t: float) -> str:
    """Interpolate between two #rrggbb colors."""
    r1,g1,b1 = int(c1[1:3],16),int(c1[3:5],16),int(c1[5:7],16)
    r2,g2,b2 = int(c2[1:3],16),int(c2[3:5],16),int(c2[5:7],16)
    r,g,b = int(r1+(r2-r1)*t), int(g1+(g2-g1)*t), int(b1+(b2-b1)*t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _make_gradient_image(w: int, h: int, c1: str, c2: str) -> Image.Image:
    """PIL gradient image (left→right)."""
    img  = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    r1,g1,b1 = int(c1[1:3],16),int(c1[3:5],16),int(c1[5:7],16)
    r2,g2,b2 = int(c2[1:3],16),int(c2[3:5],16),int(c2[5:7],16)
    for x in range(0, w, 2):
        t  = x / max(w-1, 1)
        clr = (int(r1+(r2-r1)*t), int(g1+(g2-g1)*t), int(b1+(b2-b1)*t))
        draw.line([(x,0),(x+1,h)], fill=clr)
    return img


# ──────────────────────────────────────────────────────────────────────────────
class GameInSteamApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("GameInSteam — Steam Library Manager")
        self.geometry("1120x700")
        self.minsize(960, 640)

        # ── PALETTE ──────────────────────────────────────────────────────────
        self.c_bg           = "#080812"
        self.c_sidebar      = "#0C0C1E"
        self.c_card         = "#13132A"
        self.c_card_hi      = "#1C1C3C"
        self.c_sep          = "#1E1E40"
        self.c_accent       = "#8B5CF6"   # electric violet
        self.c_accent_hov   = "#7C3AED"
        self.c_accent_dim   = "#2D1B69"
        self.c_accent2      = "#EC4899"   # hot pink
        self.c_accent3      = "#06B6D4"   # cyan
        self.c_text         = "#F1F5F9"
        self.c_text_dim     = "#64748B"
        self.c_danger       = "#F43F5E"
        self.c_danger_hov   = "#E11D48"
        self.c_success      = "#10B981"
        self.c_warning      = "#F59E0B"

        self.configure(fg_color=self.c_bg)

        # ── STATE ─────────────────────────────────────────────────────────────
        self._name_cache:          dict[str,str]  = {}
        self._img_cache:           dict[str,Any]  = {}
        self._crack_cache:         dict[str,Any]  = {}
        self._available_games:     list[str]       = []
        self._available_loaded                      = False
        self._busy                                  = False
        self._spinner_active                        = False
        self._config:              dict[str,Any]   = self._load_config()
        self._current_page                          = ""
        self._categories = ["All", "Cracked", "Protected", "Clean / No DRM"]
        self._update_lock        = threading.Lock()
        self._update_checking    = False
        self._update_dialog_open = False
        self._update_info        = None

        # Fallback thumbnail
        fb = _make_gradient_image(IMG_W, IMG_H, self.c_card, self.c_card_hi)
        draw = ImageDraw.Draw(fb)
        draw.text((IMG_W//2-28, IMG_H//2-6), "NO IMAGE", fill=self.c_text_dim)
        self._empty_img = ImageTk.PhotoImage(fb)

        self._build_ui()
        self._check_system()

        if self._config.get("auto_check_updates", True):
            threading.Thread(target=self._check_update_on_start, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    # CONFIG
    # ─────────────────────────────────────────────────────────────────────────
    def _load_config(self) -> dict[str,Any]:
        default: dict[str,Any] = {
            "auto_check_updates": True,
            "auto_download_updates": False,
            "discord_webhook_enabled": True,
            "discord_webhook_url": DEFAULT_WEBHOOK_URL,
        }
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return {**default, **json.load(f)}
        except Exception:
            pass
        return default

    def _save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # ANIMATION HELPERS
    # ─────────────────────────────────────────────────────────────────────────
    def _anim_color(self, widget, attr: str, frm: str, to: str,
                    steps: int = 8, step: int = 0):
        """Smooth fg_color transition."""
        if step > steps:
            return
        col = _hex_lerp(frm, to, step / steps)
        try:
            widget.configure(**{attr: col})
            self.after(14, lambda: self._anim_color(widget, attr, frm, to, steps, step+1))
        except Exception:
            pass

    def _hover_on(self, w):
        self._anim_color(w, "fg_color", self.c_card, self.c_card_hi)

    def _hover_off(self, w):
        self._anim_color(w, "fg_color", self.c_card_hi, self.c_card)

    def _bind_hover(self, widget):
        widget.bind("<Enter>", lambda e: self._hover_on(widget), add="+")
        widget.bind("<Leave>", lambda e: self._hover_off(widget), add="+")

    def _spin(self, label, frame: int = 0):
        if not self._spinner_active:
            return
        try:
            if label.winfo_exists():
                label.configure(text=SPIN_FRAMES[frame % len(SPIN_FRAMES)])
                self.after(80, lambda: self._spin(label, frame+1))
        except Exception:
            pass

    def _start_spin(self, label):
        self._spinner_active = True
        self._spin(label)

    def _stop_spin(self):
        self._spinner_active = False

    # ─────────────────────────────────────────────────────────────────────────
    # BUILD UI
    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── SIDEBAR ──────────────────────────────────────────────────────────
        self.sidebar = ctk.CTkFrame(self, width=235, corner_radius=0,
                                    fg_color=self.c_sidebar)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Logo area (gradient background)
        logo_canvas = tk.Canvas(self.sidebar, width=235, height=90,
                                highlightthickness=0, bd=0)
        logo_canvas.pack(fill="x")

        grad_img = _make_gradient_image(235, 90, "#1A0A50", "#0C0C1E")
        self._logo_grad = ImageTk.PhotoImage(grad_img)
        logo_canvas.create_image(0, 0, anchor="nw", image=self._logo_grad)
        logo_canvas.create_text(24, 32, anchor="w", text="🎮",
                                font=("Segoe UI", 22), fill=self.c_text)
        logo_canvas.create_text(58, 26, anchor="w", text="GAME IN STEAM",
                                font=("Segoe UI", 12, "bold"), fill=self.c_text)
        logo_canvas.create_text(58, 46, anchor="w", text="Steam Library Manager",
                                font=("Segoe UI", 9), fill=self.c_text_dim)

        self._sep(self.sidebar)

        ctk.CTkLabel(self.sidebar, text="NAVIGATE",
                     font=ctk.CTkFont("Segoe UI", 9, weight="bold"),
                     text_color=self.c_text_dim).pack(anchor="w", padx=22, pady=(10,4))

        self.btn_dash      = self._nav_btn("Dashboard",      "⊞", self._show_dash)
        self.btn_lib       = self._nav_btn("My Library",     "📚", self._show_lib)
        self.btn_recent    = self._nav_btn("Recent",         "🕐", self._show_recent)
        self.btn_available = self._nav_btn("Available Games","🗂", self._show_available)

        self._sep(self.sidebar)
        ctk.CTkLabel(self.sidebar, text="SYSTEM",
                     font=ctk.CTkFont("Segoe UI", 9, weight="bold"),
                     text_color=self.c_text_dim).pack(anchor="w", padx=22, pady=(10,4))

        self.btn_settings  = self._nav_btn("Settings",       "⚙", self._show_settings)

        self.sys_status_lbl = ctk.CTkLabel(
            self.sidebar, text="Checking system…",
            text_color=self.c_text_dim, font=ctk.CTkFont(size=10),
            wraplength=200, justify="left")
        self.sys_status_lbl.pack(side="bottom", pady=(0,8), padx=18, anchor="w")
        ctk.CTkLabel(self.sidebar, text=f"v{CURRENT_VERSION}",
                     text_color=self.c_text_dim,
                     font=ctk.CTkFont(size=10)).pack(side="bottom", anchor="w", padx=18)
        self._sep(self.sidebar, side="bottom")

        # ── RIGHT BORDER ──────────────────────────────────────────────────────
        ctk.CTkFrame(self, width=1, fg_color=self.c_sep).pack(side="left", fill="y")

        # ── MAIN ──────────────────────────────────────────────────────────────
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=self.c_bg)
        self.main_frame.pack(side="right", fill="both", expand=True)

        _sf = lambda: ctk.CTkScrollableFrame(
            self.main_frame, fg_color="transparent",
            scrollbar_button_color=self.c_accent_dim,
            scrollbar_button_hover_color=self.c_accent)

        self.page_dash      = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.page_lib       = _sf()
        self.page_recent    = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.page_available = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.page_settings  = _sf()

        self._build_dash()
        self._build_lib()
        self._build_recent()
        self._build_available()
        self._build_settings()
        self._show_dash()

    # ── NAV HELPERS ───────────────────────────────────────────────────────────
    def _sep(self, parent, side="top"):
        ctk.CTkFrame(parent, height=1, fg_color=self.c_sep).pack(
            fill="x", padx=16, pady=6, side=side)

    def _nav_btn(self, text: str, icon: str, cmd) -> ctk.CTkButton:
        btn = ctk.CTkButton(
            self.sidebar, text=f" {icon}   {text}",
            font=ctk.CTkFont("Segoe UI", 12, weight="bold"),
            fg_color="transparent", text_color=self.c_text_dim,
            anchor="w", hover_color=self.c_sep,
            height=44, corner_radius=10, command=cmd)
        btn.pack(fill="x", padx=10, pady=2)
        return btn

    def _reset_nav(self):
        for b in [self.btn_dash, self.btn_lib, self.btn_recent,
                  self.btn_available, self.btn_settings]:
            b.configure(fg_color="transparent", text_color=self.c_text_dim)
        for p in [self.page_dash, self.page_lib, self.page_recent,
                  self.page_available, self.page_settings]:
            p.pack_forget()

    def _activate_nav(self, btn):
        btn.configure(fg_color=self.c_accent_dim, text_color=self.c_accent)

    def _show_dash(self):
        self._reset_nav(); self._activate_nav(self.btn_dash)
        self.page_dash.pack(fill="both", expand=True, padx=30, pady=24)
        self._current_page = "dash"
        self._refresh_hero_stats()

    def _show_lib(self):
        self._reset_nav(); self._activate_nav(self.btn_lib)
        self.page_lib.pack(fill="both", expand=True, padx=30, pady=24)
        self._current_page = "lib"; self._load_games()

    def _show_recent(self):
        self._reset_nav(); self._activate_nav(self.btn_recent)
        self.page_recent.pack(fill="both", expand=True, padx=30, pady=24)
        self._current_page = "recent"; self._load_recent()

    def _show_available(self):
        self._reset_nav(); self._activate_nav(self.btn_available)
        self.page_available.pack(fill="both", expand=True, padx=30, pady=24)
        self._current_page = "available"
        if not self._available_loaded:
            self._load_available_games()

    def _show_settings(self):
        self._reset_nav(); self._activate_nav(self.btn_settings)
        self.page_settings.pack(fill="both", expand=True, padx=30, pady=24)
        self._current_page = "settings"

    # ─────────────────────────────────────────────────────────────────────────
    # CARD & SECTION HELPERS
    # ─────────────────────────────────────────────────────────────────────────
    def _card(self, parent, hover: bool = True) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color=self.c_card, corner_radius=16)
        if hover:
            self._bind_hover(f)
        return f

    def _accent_card(self, parent, color: str | None = None) -> ctk.CTkFrame:
        """Card with a 3px left accent stripe."""
        outer = ctk.CTkFrame(parent, fg_color=color or self.c_accent, corner_radius=16)
        inner = ctk.CTkFrame(outer, fg_color=self.c_card, corner_radius=14)
        inner.pack(fill="both", expand=True, padx=(4,0))
        self._bind_hover(inner)
        return inner

    def _section_title(self, parent, text: str, sub: str = ""):
        ctk.CTkLabel(parent, text=text,
                     font=ctk.CTkFont("Segoe UI", 26, weight="bold"),
                     text_color=self.c_text).pack(anchor="w", pady=(6,2))
        if sub:
            ctk.CTkLabel(parent, text=sub,
                         font=ctk.CTkFont("Segoe UI", 12),
                         text_color=self.c_text_dim).pack(anchor="w", pady=(0,14))
        else:
            ctk.CTkFrame(parent, height=14, fg_color="transparent").pack()

    def _ghost_btn(self, parent, text: str, cmd, width: int = 90) -> ctk.CTkButton:
        return ctk.CTkButton(parent, text=text, width=width, height=32,
                             fg_color=self.c_card_hi, text_color=self.c_text,
                             hover_color=self.c_sep, corner_radius=10, command=cmd)

    # ─────────────────────────────────────────────────────────────────────────
    # DASHBOARD
    # ─────────────────────────────────────────────────────────────────────────
    def _build_dash(self):
        self.dash_scroll = ctk.CTkScrollableFrame(
            self.page_dash, fg_color="transparent",
            scrollbar_button_color=self.c_accent_dim,
            scrollbar_button_hover_color=self.c_accent)
        self.dash_scroll.pack(fill="both", expand=True)

        # ── HERO BANNER ──────────────────────────────────────────────────────
        self.hero_canvas = tk.Canvas(self.dash_scroll, height=110,
                                     highlightthickness=0, bd=0,
                                     bg=self.c_bg)
        self.hero_canvas.pack(fill="x", pady=(0,20))
        self._draw_hero()
        self.hero_canvas.bind("<Configure>", lambda e: self._draw_hero(e.width))

        # ── ADD GAME CARD ─────────────────────────────────────────────────────
        add_card = self._card(self.dash_scroll, hover=False)
        add_card.pack(fill="x", pady=(0,18))

        # Colored top bar on card
        ctk.CTkFrame(add_card, height=3, fg_color=self.c_accent,
                     corner_radius=0).pack(fill="x")

        inner = ctk.CTkFrame(add_card, fg_color="transparent")
        inner.pack(fill="x", padx=24, pady=20)

        # Label
        ctk.CTkLabel(inner, text="🔍  Quick Find",
                     font=ctk.CTkFont("Segoe UI", 13, weight="bold"),
                     text_color=self.c_accent).pack(anchor="w")

        # Search box
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_change)
        self.inp_search = ctk.CTkEntry(
            inner, height=44, textvariable=self.search_var,
            placeholder_text="Type a game name to find its AppID…",
            fg_color=self.c_card_hi, border_color=self.c_sep, border_width=1,
            text_color=self.c_text, corner_radius=12)
        self.inp_search.pack(fill="x", pady=(8,4))

        self.search_results_frame = ctk.CTkScrollableFrame(
            inner, height=0, fg_color=self.c_bg, corner_radius=10)

        # ID + Name row
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x", pady=10)

        def _lbl_entry(col_parent, label, placeholder):
            ctk.CTkLabel(col_parent, text=label,
                         font=ctk.CTkFont("Segoe UI", 11, weight="bold"),
                         text_color=self.c_text_dim).pack(anchor="w")
            e = ctk.CTkEntry(col_parent, height=44, placeholder_text=placeholder,
                             fg_color=self.c_card_hi, border_color=self.c_sep,
                             border_width=1, text_color=self.c_text, corner_radius=12)
            e.pack(fill="x", pady=4)
            return e

        c1 = ctk.CTkFrame(row, fg_color="transparent")
        c1.pack(side="left", fill="x", expand=True, padx=(0,8))
        self.inp_id = _lbl_entry(c1, "Steam App ID", "e.g. 730, 440")

        c2 = ctk.CTkFrame(row, fg_color="transparent")
        c2.pack(side="left", fill="x", expand=True, padx=(8,0))
        self.inp_name = _lbl_entry(c2, "Game Name (Optional)", "Auto-filled…")

        # Buttons
        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=(14,0))

        self.btn_add = ctk.CTkButton(
            btn_row, text="⚡  ADD TO LIBRARY", height=50,
            fg_color=self.c_accent, text_color="#FFFFFF",
            hover_color=self.c_accent_hov,
            font=ctk.CTkFont("Segoe UI", 14, weight="bold"),
            corner_radius=14, command=self._do_add)
        self.btn_add.pack(side="left", fill="x", expand=True, padx=(0,6))

        self.btn_restart = ctk.CTkButton(
            btn_row, text="🔄  RESTART STEAM", height=50,
            fg_color=self.c_card_hi, text_color=self.c_text,
            hover_color=self.c_sep,
            font=ctk.CTkFont("Segoe UI", 13, weight="bold"),
            corner_radius=14, command=self._do_steam_restart)
        self.btn_restart.pack(side="left", fill="x", expand=True, padx=(6,0))

        # Status
        self.status_lbl = ctk.CTkLabel(inner, text="",
                                        text_color=self.c_text_dim,
                                        font=ctk.CTkFont("Segoe UI", 12))
        self.status_lbl.pack(pady=(12,0))

        self.prog_bar = ctk.CTkProgressBar(
            inner, fg_color=self.c_card_hi,
            progress_color=self.c_accent, height=5, corner_radius=4)
        self.prog_bar.set(0)

    def _draw_hero(self, width: int = 900):
        """Draws the gradient hero banner with stats."""
        c = self.hero_canvas
        c.delete("all")
        w = max(width, 400)

        # Gradient background
        grad = _make_gradient_image(w, 110, "#1A0840", "#0C0C1E")
        self._hero_img = ImageTk.PhotoImage(grad)
        c.create_image(0, 0, anchor="nw", image=self._hero_img)

        # Accent line at top
        c.create_rectangle(0, 0, w, 3, fill=self.c_accent, outline="")

        # Title
        c.create_text(24, 38, anchor="w", text="Welcome back  👋",
                      font=("Segoe UI", 20, "bold"), fill=self.c_text)
        c.create_text(24, 68, anchor="w",
                      text="Add games to your Steam library in seconds.",
                      font=("Segoe UI", 11), fill=self.c_text_dim)

        # Stats pills (right side)
        lib_count  = len(list_added_games()) if os.path.isdir(
            os.path.join(r"C:\Program Files (x86)\Steam", "config", "stplug-in")) else 0
        repo_count = len(self._available_games)

        c.create_rectangle(w-260, 30, w-160, 82, fill="#2D1B69", outline="", width=0)
        c.create_text(w-210, 48, anchor="center", text=str(lib_count),
                      font=("Segoe UI", 20, "bold"), fill=self.c_accent)
        c.create_text(w-210, 68, anchor="center", text="In Library",
                      font=("Segoe UI", 9), fill=self.c_text_dim)

        c.create_rectangle(w-148, 30, w-24, 82, fill="#1B2D3A", outline="", width=0)
        c.create_text(w-86, 48, anchor="center", text=str(repo_count) if repo_count else "—",
                      font=("Segoe UI", 20, "bold"), fill=self.c_accent3)
        c.create_text(w-86, 68, anchor="center", text="In Repo",
                      font=("Segoe UI", 9), fill=self.c_text_dim)

    def _refresh_hero_stats(self):
        self.after(0, lambda: self._draw_hero(self.hero_canvas.winfo_width()))

    # ── SEARCH ────────────────────────────────────────────────────────────────
    def _on_search_change(self, *args):
        q = self.search_var.get().strip()
        if len(q) < 3:
            self.search_results_frame.pack_forget(); return
        if hasattr(self, "_st"):
            self.after_cancel(self._st)
        self._st = self.after(480, lambda: self._start_search(q))

    def _start_search(self, query):
        for w in self.search_results_frame.winfo_children(): w.destroy()
        self.search_results_frame.pack(fill="x", pady=(4,0))
        ctk.CTkLabel(self.search_results_frame, text="Searching…",
                     font=ctk.CTkFont(size=12, slant="italic"),
                     text_color=self.c_text_dim).pack(pady=8)
        threading.Thread(target=self._do_steam_search, args=(query,), daemon=True).start()

    def _do_steam_search(self, query):
        try:
            r = requests.get(
                f"https://store.steampowered.com/api/storesearch/?term={query}&l=english&cc=US",
                timeout=5)
            items = r.json().get("items", [])[:6]
            if items:
                try:
                    cr = requests.get(
                        "https://store.steampowered.com/curator/26095454-Denuvo-Games/"
                        "ajaxgetfilteredrecommendations/render/?start=0&count=1000", timeout=5)
                    html = cr.json().get("results_html", "")
                    for item in items:
                        item["has_denuvo"] = str(item.get("id")) in html
                except Exception:
                    pass
            self.after(0, self._render_search, items)
        except Exception:
            self.after(0, lambda: self._render_search([], error=True))

    def _render_search(self, items, error=False):
        for w in self.search_results_frame.winfo_children(): w.destroy()
        if error:
            ctk.CTkLabel(self.search_results_frame, text="Search failed.",
                         text_color=self.c_danger).pack(pady=5); return
        if not items:
            ctk.CTkLabel(self.search_results_frame, text="No games found.",
                         text_color=self.c_text_dim).pack(pady=5); return
        for item in items:
            aid  = str(item.get("id",""))
            name = item.get("name","Unknown")
            den  = item.get("has_denuvo", False)
            txt  = f"⚠️  DENUVO: {name} [{aid}]" if den else f"{name}  [{aid}]"
            ctk.CTkButton(
                self.search_results_frame, text=txt, anchor="w",
                fg_color="transparent", text_color=self.c_danger if den else self.c_text,
                hover_color=self.c_sep,
                command=lambda a=aid,n=name,d=den: self._pick_search(a,n,d)
            ).pack(fill="x", pady=1)

    def _pick_search(self, aid, name, den):
        if den and not messagebox.askyesno(
            "DRM Warning",
            f"'{name}' uses Denuvo/3rd-party DRM.\nGame WON'T LAUNCH without bypass.\nAdd anyway?"):
            self.search_var.set(""); self.search_results_frame.pack_forget(); return
        self.inp_id.delete(0,"end"); self.inp_id.insert(0, aid)
        self.inp_name.delete(0,"end"); self.inp_name.insert(0, name)
        self.search_var.set(""); self.search_results_frame.pack_forget()

    # ─────────────────────────────────────────────────────────────────────────
    # MY LIBRARY
    # ─────────────────────────────────────────────────────────────────────────
    def _build_lib(self):
        self._section_title(self.page_lib, "MY LIBRARY",
                            "Games you've added via stplug-in")

        top = ctk.CTkFrame(self.page_lib, fg_color="transparent")
        top.pack(fill="x", pady=(0,14))

        self.lib_count = ctk.CTkLabel(top, text="0 games",
                                       text_color=self.c_text_dim,
                                       font=ctk.CTkFont(size=12))
        self.lib_count.pack(side="left")

        self.cat_var = ctk.StringVar(value="All")
        ctk.CTkOptionMenu(top, values=self._categories, variable=self.cat_var,
                          height=32, width=140,
                          fg_color=self.c_card, button_color=self.c_card,
                          button_hover_color=self.c_accent,
                          command=self._filter_library).pack(side="left", padx=14)

        self.lib_search_var = tk.StringVar()
        self.lib_search_var.trace_add("write", self._filter_library)
        ctk.CTkEntry(top, height=32, placeholder_text="🔍  Filter…",
                     fg_color=self.c_card, border_color=self.c_sep,
                     textvariable=self.lib_search_var,
                     corner_radius=10).pack(side="left", fill="x", expand=True, padx=(0,12))

        ctk.CTkButton(top, text="↺  Refresh", width=100, height=32,
                      fg_color=self.c_card, hover_color=self.c_accent,
                      corner_radius=10, command=self._load_games).pack(side="right")

        self.lib_container = ctk.CTkFrame(self.page_lib, fg_color="transparent")
        self.lib_container.pack(fill="both", expand=True)

    def _filter_library(self, *args):
        q   = self.lib_search_var.get().strip().lower()
        cat = self.cat_var.get()
        for card in self.lib_container.winfo_children():
            if not hasattr(card,"_app_id"): continue
            aid  = card._app_id
            name = self._name_cache.get(aid,"").lower()
            st   = self._crack_cache.get(aid,{})
            cr   = bool(st.get("cracked",False))
            mc   = True
            if cat == "Cracked":          mc = cr
            elif cat == "Protected":      mc = not cr and st.get("protection") != "Unknown"
            elif cat == "Clean / No DRM": mc = st.get("protection") == "Unknown"
            show = (q in name or q in aid) and mc
            if show: card.pack(fill="x", pady=6)
            else:    card.pack_forget()

    def _load_games(self):
        for w in self.lib_container.winfo_children(): w.destroy()
        try:
            games = list_added_games()
            cnt   = len(games)
            self.lib_count.configure(text=f"{cnt} game{'s' if cnt!=1 else ''}")
            if not games:
                ctk.CTkLabel(self.lib_container,
                             text="Your library is empty.\nGo to Available Games to add some!",
                             text_color=self.c_text_dim, pady=60,
                             font=ctk.CTkFont(size=14)).pack()
                return
            for g in games: self._game_card(g)
        except Exception as e:
            print("Library err:", e)

    def _game_card(self, g):
        aid  = g["app_id"]
        card = self._card(self.lib_container)
        card._app_id = aid
        card.pack(fill="x", pady=6)

        # Colored top strip
        ctk.CTkFrame(card, height=2, fg_color=self.c_accent,
                     corner_radius=0).pack(fill="x")

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=14)

        img_lbl = tk.Label(row, bg=self.c_card, image=self._empty_img, bd=0)
        img_lbl.pack(side="left", padx=(0,16))

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)

        cached   = self._name_cache.get(aid,"")
        name_lbl = ctk.CTkLabel(info, text=cached or f"Game #{aid}",
                                 font=ctk.CTkFont("Segoe UI",17,weight="bold"),
                                 text_color=self.c_text)
        name_lbl.pack(anchor="w")

        badge_row = ctk.CTkFrame(info, fg_color="transparent")
        badge_row.pack(anchor="w", pady=(4,0))
        ctk.CTkLabel(badge_row, text=f"AppID: {aid}",
                     font=ctk.CTkFont(size=11),
                     text_color=self.c_text_dim).pack(side="left")
        status_lbl = ctk.CTkLabel(badge_row, text="checking…",
                                   font=ctk.CTkFont(size=10, weight="bold"),
                                   fg_color=self.c_card_hi,
                                   corner_radius=8, padx=8, pady=1)
        status_lbl.pack(side="left", padx=10)

        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.pack(side="right")
        self._ghost_btn(btns, "↺  Update", lambda: self._do_update(aid), 100).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Remove", width=86, height=32,
                      fg_color=self.c_card_hi, text_color=self.c_danger,
                      hover_color="#3A0F1A", corner_radius=10,
                      command=lambda: self._do_remove(aid, card)).pack(side="left", padx=4)

        if not cached:
            threading.Thread(target=self._fetch_name, args=(aid,name_lbl), daemon=True).start()
        if aid not in self._img_cache:
            threading.Thread(target=self._fetch_img, args=(aid,img_lbl), daemon=True).start()
        else:
            img_lbl.configure(image=self._img_cache[aid])
        threading.Thread(target=self._fetch_crack,
                         args=(aid,cached,status_lbl), daemon=True).start()

    def _fetch_name(self, aid, lbl):
        name = get_game_name_from_steam(aid)
        if name:
            self._name_cache[aid] = name
            self.after(0, lambda: lbl.configure(text=name) if lbl.winfo_exists() else None)

    def _fetch_img(self, aid, lbl, cache_key: str|None = None):
        key = cache_key or aid
        try:
            r = requests.get(HEADER_URL.format(aid), timeout=6)
            if r.status_code == 200:
                img   = Image.open(io.BytesIO(r.content)).resize((IMG_W,IMG_H), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._img_cache[key] = photo
                self.after(0, lambda: lbl.configure(image=photo) if lbl.winfo_exists() else None)
        except Exception:
            pass

    def _fetch_crack(self, aid, name, lbl):
        if aid in self._crack_cache:
            self.after(0, lambda: self._apply_crack_ui(lbl, self._crack_cache[aid])); return
        try:
            h = {"User-Agent":"Mozilla/5.0"}
            r = requests.get(f"https://gamestatus.info/back/api/gameinfo/game/?search={aid}",
                             headers=h, timeout=10)
            res  = r.json().get("results",[])
            data = next((x for x in res if str(x.get("steam_prod_id"))==str(aid)), None)
            if not data and name:
                r2  = requests.get(f"https://gamestatus.info/back/api/gameinfo/game/?search={name}",
                                   headers=h, timeout=10)
                res2 = r2.json().get("results",[])
                data = next((x for x in res2 if x.get("title","").lower()==name.lower()), None)
            if data:
                st = {"cracked":bool(data.get("crack_date")),
                      "protection":data.get("protections","Unknown"),
                      "date":data.get("crack_date") or "Uncracked"}
                self._crack_cache[aid] = st
                self.after(0, lambda: self._apply_crack_ui(lbl,st) if lbl.winfo_exists() else None)
            else:
                self.after(0, lambda: lbl.configure(
                    text="CLEAN / NO DRM", fg_color="#1A2E22",
                    text_color=self.c_success) if lbl.winfo_exists() else None)
        except Exception:
            self.after(0, lambda: lbl.configure(
                text="ERROR", fg_color="#2E1A1A",
                text_color=self.c_danger) if lbl.winfo_exists() else None)

    def _apply_crack_ui(self, lbl, st):
        if not lbl.winfo_exists(): return
        if st["cracked"]:
            lbl.configure(text=f"✓ CRACKED  {st['date']}",
                          fg_color="#1A3028", text_color=self.c_success)
        else:
            prot = (st.get("protection") or "PROTECTED").upper()
            lbl.configure(text=prot, fg_color="#2E2010", text_color=self.c_warning)

    # ─────────────────────────────────────────────────────────────────────────
    # RECENT
    # ─────────────────────────────────────────────────────────────────────────
    def _build_recent(self):
        top = ctk.CTkFrame(self.page_recent, fg_color="transparent")
        top.pack(fill="x", pady=(0,6))
        ctk.CTkLabel(top, text="🕐  SON EKLENENLER",
                     font=ctk.CTkFont("Segoe UI", 24, weight="bold"),
                     text_color=self.c_text).pack(side="left")
        ctk.CTkButton(top, text="↺  Refresh", width=110, height=34,
                      fg_color=self.c_card, hover_color=self.c_accent,
                      corner_radius=10, command=self._load_recent).pack(side="right")

        self.recent_info = ctk.CTkLabel(self.page_recent, text="",
                                         text_color=self.c_text_dim,
                                         font=ctk.CTkFont(size=12))
        self.recent_info.pack(anchor="w", pady=(2,10))

        self.recent_scroll = ctk.CTkScrollableFrame(
            self.page_recent, fg_color="transparent",
            scrollbar_button_color=self.c_accent_dim,
            scrollbar_button_hover_color=self.c_accent)
        self.recent_scroll.pack(fill="both", expand=True)

    def _load_recent(self):
        for w in self.recent_scroll.winfo_children(): w.destroy()
        self.recent_info.configure(text="Loading…")
        threading.Thread(target=lambda: self.after(
            0, lambda: self._render_recent(list_recent_games(30))), daemon=True).start()

    def _render_recent(self, games):
        if not games:
            self.recent_info.configure(text="No games added yet.")
            ctk.CTkLabel(self.recent_scroll,
                         text="You haven't added any games yet.\nGo to Available Games to get started.",
                         text_color=self.c_text_dim, pady=50,
                         font=ctk.CTkFont(size=14)).pack(); return

        self.recent_info.configure(text=f"Showing {len(games)} most recently added games")
        for g in games:
            aid   = g["app_id"]
            mtime = g.get("mtime", 0)
            card  = self._card(self.recent_scroll)
            card.pack(fill="x", pady=5)

            # Left time indicator
            ctk.CTkFrame(card, width=4, fg_color=self.c_accent2,
                         corner_radius=2).pack(side="left", fill="y", padx=(10,0), pady=10)

            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(side="left", fill="both", expand=True, padx=12, pady=12)

            img_lbl = tk.Label(row, bg=self.c_card, image=self._empty_img, bd=0)
            img_lbl.pack(side="left", padx=(0,14))

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True)

            name_lbl = ctk.CTkLabel(info,
                                     text=self._name_cache.get(aid, f"AppID: {aid}"),
                                     font=ctk.CTkFont("Segoe UI",16,weight="bold"),
                                     text_color=self.c_text)
            name_lbl.pack(anchor="w")

            meta = ctk.CTkFrame(info, fg_color="transparent")
            meta.pack(anchor="w", pady=(3,0))
            ctk.CTkLabel(meta, text=f"ID: {aid}",
                         font=ctk.CTkFont(size=11),
                         text_color=self.c_text_dim).pack(side="left")
            ctk.CTkLabel(meta, text=f"  •  Added {_time_ago(mtime)}",
                         font=ctk.CTkFont(size=11),
                         text_color=self.c_accent2).pack(side="left")

            right = ctk.CTkFrame(row, fg_color="transparent")
            right.pack(side="right")
            ctk.CTkButton(right, text="Remove", width=86, height=32,
                          fg_color=self.c_card_hi, text_color=self.c_danger,
                          hover_color="#3A0F1A", corner_radius=10,
                          command=lambda a=aid, c=card: self._do_remove(a,c)).pack()

            if aid not in self._name_cache:
                threading.Thread(target=self._fetch_name,
                                 args=(aid,name_lbl), daemon=True).start()
            if aid not in self._img_cache:
                threading.Thread(target=self._fetch_img,
                                 args=(aid,img_lbl), daemon=True).start()
            else:
                img_lbl.configure(image=self._img_cache[aid])

    # ─────────────────────────────────────────────────────────────────────────
    # AVAILABLE GAMES
    # ─────────────────────────────────────────────────────────────────────────
    def _build_available(self):
        top = ctk.CTkFrame(self.page_available, fg_color="transparent")
        top.pack(fill="x", pady=(0,6))
        ctk.CTkLabel(top, text="🗂  AVAILABLE GAMES",
                     font=ctk.CTkFont("Segoe UI",24,weight="bold"),
                     text_color=self.c_text).pack(side="left")
        self.avail_refresh_btn = ctk.CTkButton(
            top, text="↺  Refresh", width=110, height=34,
            fg_color=self.c_card, hover_color=self.c_accent,
            corner_radius=10, command=self._refresh_available_games)
        self.avail_refresh_btn.pack(side="right")

        # Search bar
        search_row = ctk.CTkFrame(self.page_available, fg_color="transparent")
        search_row.pack(fill="x", pady=(0,12))

        self.avail_count_lbl = ctk.CTkLabel(
            search_row, text="Loading…",
            text_color=self.c_text_dim, font=ctk.CTkFont(size=12))
        self.avail_count_lbl.pack(side="left")

        # Spinner label
        self.avail_spin_lbl = ctk.CTkLabel(
            search_row, text="",
            font=ctk.CTkFont("Courier", 14, weight="bold"),
            text_color=self.c_accent)
        self.avail_spin_lbl.pack(side="left", padx=8)

        self.avail_search_var = tk.StringVar()
        self.avail_search_var.trace_add("write", self._filter_available)
        ctk.CTkEntry(search_row, height=32, width=260,
                     placeholder_text="🔍  Filter by name or AppID…",
                     fg_color=self.c_card, border_color=self.c_sep,
                     textvariable=self.avail_search_var,
                     corner_radius=10).pack(side="right")

        self.avail_scroll = ctk.CTkScrollableFrame(
            self.page_available, fg_color="transparent",
            scrollbar_button_color=self.c_accent_dim,
            scrollbar_button_hover_color=self.c_accent)
        self.avail_scroll.pack(fill="both", expand=True)

    def _load_available_games(self):
        self.avail_count_lbl.configure(text="Fetching from repo…")
        self.avail_refresh_btn.configure(state="disabled", text="Loading…")
        for w in self.avail_scroll.winfo_children(): w.destroy()
        self._start_spin(self.avail_spin_lbl)
        threading.Thread(target=self._worker_fetch_available, daemon=True).start()

    def _refresh_available_games(self):
        self._available_loaded = False
        self._available_games  = []
        self._load_available_games()

    def _worker_fetch_available(self):
        ids = get_gamelist_repo_games()
        self.after(0, lambda: self._render_available(ids))

    def _render_available(self, ids: list):
        self._stop_spin()
        self.avail_spin_lbl.configure(text="")
        self._available_loaded = True
        self._available_games  = ids
        self.avail_refresh_btn.configure(state="normal", text="↺  Refresh")
        for w in self.avail_scroll.winfo_children(): w.destroy()

        if not ids:
            ctk.CTkLabel(self.avail_scroll,
                         text="Could not load game list. Check internet.",
                         text_color=self.c_danger, pady=40).pack()
            self.avail_count_lbl.configure(text="0 games found"); return

        self.avail_count_lbl.configure(text=f"{len(ids)} games available in repo")
        self._refresh_hero_stats()
        for aid in ids:
            self._available_card(aid)

    def _available_card(self, aid: str):
        card = self._card(self.avail_scroll)
        card._app_id   = aid
        card._name_str = ""
        card.pack(fill="x", pady=5)

        # Accent strip
        ctk.CTkFrame(card, width=4, fg_color=self.c_accent,
                     corner_radius=2).pack(side="left", fill="y", padx=(10,0), pady=10)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(side="left", fill="both", expand=True, padx=12, pady=12)

        img_lbl = tk.Label(row, bg=self.c_card, image=self._empty_img, bd=0)
        img_lbl.pack(side="left", padx=(0,14))

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)

        name_lbl = ctk.CTkLabel(info, text=f"AppID: {aid}",
                                  font=ctk.CTkFont("Segoe UI",16,weight="bold"),
                                  text_color=self.c_text)
        name_lbl.pack(anchor="w")
        ctk.CTkLabel(info, text=f"ID: {aid}",
                     font=ctk.CTkFont(size=11),
                     text_color=self.c_text_dim).pack(anchor="w")
        ctk.CTkLabel(info, text="✓  in gamelist repo",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     fg_color=self.c_accent_dim, text_color=self.c_accent,
                     corner_radius=8, padx=8, pady=1).pack(anchor="w", pady=(5,0))

        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right")
        ctk.CTkButton(right, text="⚡  ADD", width=100, height=40,
                      fg_color=self.c_accent, text_color="#FFFFFF",
                      hover_color=self.c_accent_hov,
                      font=ctk.CTkFont("Segoe UI",13,weight="bold"),
                      corner_radius=12,
                      command=lambda a=aid, nl=name_lbl: self._quick_add(a, nl)
                      ).pack()

        threading.Thread(target=self._fetch_avail_name,
                         args=(aid,name_lbl,card), daemon=True).start()
        if aid not in self._img_cache:
            threading.Thread(target=self._fetch_img,
                             args=(aid,img_lbl), daemon=True).start()
        else:
            img_lbl.configure(image=self._img_cache[aid])

    def _fetch_avail_name(self, aid, lbl, card):
        name = self._name_cache.get(aid) or get_game_name_from_steam(aid)
        if name:
            self._name_cache[aid] = name
            card._name_str        = name.lower()
            self.after(0, lambda: lbl.configure(text=name) if lbl.winfo_exists() else None)

    def _filter_available(self, *args):
        q = self.avail_search_var.get().strip().lower()
        for card in self.avail_scroll.winfo_children():
            if not hasattr(card,"_app_id"): continue
            aid  = card._app_id
            name = getattr(card,"_name_str","") or self._name_cache.get(aid,"").lower()
            if q in aid or q in name: card.pack(fill="x", pady=5)
            else: card.pack_forget()

    def _quick_add(self, aid, name_lbl):
        name = self._name_cache.get(aid,"")
        self._show_dash()
        self.inp_id.delete(0,"end");   self.inp_id.insert(0, aid)
        self.inp_name.delete(0,"end")
        if name: self.inp_name.insert(0, name)

    # ─────────────────────────────────────────────────────────────────────────
    # SETTINGS
    # ─────────────────────────────────────────────────────────────────────────
    def _build_settings(self):
        self._section_title(self.page_settings, "SETTINGS")

        # Updates card
        c1 = self._card(self.page_settings, hover=False)
        c1.pack(fill="x", pady=8)
        ctk.CTkFrame(c1, height=3, fg_color=self.c_accent, corner_radius=0).pack(fill="x")
        i1 = ctk.CTkFrame(c1, fg_color="transparent")
        i1.pack(padx=22, pady=20, fill="x")
        ctk.CTkLabel(i1, text="Software Updates",
                     font=ctk.CTkFont("Segoe UI",13,weight="bold")).pack(anchor="w",pady=(0,10))
        self.sw_auto_check = ctk.CTkSwitch(i1, text="Check for Updates on Startup",
                                            progress_color=self.c_accent,
                                            command=self._save_settings)
        if self._config.get("auto_check_updates", True): self.sw_auto_check.select()
        self.sw_auto_check.pack(anchor="w", pady=4)
        self.sw_auto_dl = ctk.CTkSwitch(i1, text="Download Automatically (Beta)",
                                         progress_color=self.c_accent,
                                         command=self._save_settings)
        if self._config.get("auto_download_updates", False): self.sw_auto_dl.select()
        self.sw_auto_dl.pack(anchor="w", pady=4)
        self.btn_check_update = ctk.CTkButton(i1, text="Check for Updates",
                                               fg_color=self.c_card_hi,
                                               hover_color=self.c_accent,
                                               corner_radius=10,
                                               command=self._manual_check_update)
        self.btn_check_update.pack(anchor="w", pady=(14,0))
        self.update_status_label = ctk.CTkLabel(i1, text="",
                                                 text_color=self.c_text_dim)
        self.update_status_label.pack(anchor="w")

        # Community card
        c2 = self._card(self.page_settings, hover=False)
        c2.pack(fill="x", pady=8)
        ctk.CTkFrame(c2, height=3, fg_color=self.c_accent2, corner_radius=0).pack(fill="x")
        i2 = ctk.CTkFrame(c2, fg_color="transparent")
        i2.pack(padx=22, pady=20, fill="x")
        ctk.CTkLabel(i2, text="Community & Support",
                     font=ctk.CTkFont("Segoe UI",13,weight="bold")).pack(anchor="w",pady=(0,6))
        ctk.CTkLabel(i2, text="Join our Discord for news and support:",
                     text_color=self.c_text_dim).pack(anchor="w",pady=(0,10))
        ctk.CTkButton(i2, text="🎮  JOIN DISCORD SERVER",
                      fg_color="#5865F2", text_color="#FFFFFF",
                      hover_color="#4752C4",
                      font=ctk.CTkFont(weight="bold"), corner_radius=10,
                      command=lambda: webbrowser.open("https://discord.gg/krzbgakKJf")
                      ).pack(fill="x", pady=(0,12))
        ctk.CTkButton(i2, text="SAVE SETTINGS",
                      fg_color=self.c_accent, text_color="#FFFFFF",
                      hover_color=self.c_accent_hov,
                      font=ctk.CTkFont(weight="bold"), corner_radius=10,
                      command=self._save_settings).pack(fill="x")

    def _save_settings(self, *args):
        try:
            self._config["auto_check_updates"]    = bool(self.sw_auto_check.get()==1)
            self._config["auto_download_updates"] = bool(self.sw_auto_dl.get()==1)
            self._save_config()
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # ADD LOGIC
    # ─────────────────────────────────────────────────────────────────────────
    def _check_system(self):
        try:
            ok, msg = check_stplugin_system()
            if ok: self.sys_status_lbl.configure(
                text=f"✅  {msg.split('!')[0]}!", text_color=self.c_success)
            else:  self.sys_status_lbl.configure(
                text=f"⚠  {msg.split(chr(10))[0]}", text_color=self.c_warning)
        except Exception:
            pass

    def _do_add(self):
        ids_str = self.inp_id.get().strip()
        name    = self.inp_name.get().strip()
        if not ids_str:
            messagebox.showerror("Error","Enter a valid App ID."); return
        app_ids, valid = [a.strip() for a in ids_str.split(",") if a.strip()], []
        for a in app_ids:
            if a.isdigit(): valid.append(a)
            else: messagebox.showerror("Error",f"Invalid App ID: {a}"); return
        if not valid: return
        if not name: name = f"Game_{valid[0]}" if len(valid)==1 else f"{len(valid)} Games"
        self._set_busy(True, "🔍  Checking repo…")
        threading.Thread(target=self._worker_repo_check,
                         args=(valid, name), daemon=True).start()

    def _worker_repo_check(self, valid_ids, name):
        not_found = []
        for aid in valid_ids:
            if self._available_games:
                if aid not in self._available_games: not_found.append(aid)
            else:
                if not is_game_in_repo(aid): not_found.append(aid)
        if not_found:
            self.after(0, lambda: self._handle_not_found(not_found, valid_ids, name))
        else:
            self.after(0, lambda: self._proceed_add(valid_ids, name))

    def _handle_not_found(self, not_found, valid_ids, name):
        self._set_busy(False)
        if len(not_found) == 1:
            gname = self._name_cache.get(not_found[0], f"AppID {not_found[0]}")
            msg   = (f"❌  '{gname}' repomuzda bulunamadı!\n\n"
                     f"App ID: {not_found[0]}\n\n"
                     f"Bu oyun henüz gamelist repoya eklenmemiş.\n"
                     f"'Available Games' sekmesinden mevcut oyunlara göz atın.")
        else:
            msg = (f"❌  Şu oyunlar repomuzda bulunamadı:\n\n"
                   f"{', '.join(not_found)}\n\n"
                   f"'Available Games' sekmesinden mevcut oyunlara göz atın.")
        found = [a for a in valid_ids if a not in not_found]
        if found:
            msg += f"\n\nRepoda bulunan {len(found)} oyun yine de eklensin mi?"
            if messagebox.askyesno("Bazı Oyunlar Bulunamadı", msg):
                self._proceed_add(found, name)
        else:
            messagebox.showerror("Oyun Bulunamadı", msg)

    def _proceed_add(self, valid_ids, name):
        self._set_busy(True, f"Adding {len(valid_ids)} game(s)…")
        threading.Thread(target=self._worker_add,
                         args=(valid_ids, name), daemon=True).start()

    def _worker_add(self, app_ids, base_name):
        results, total = [], len(app_ids)
        for idx, aid in enumerate(app_ids):
            try:
                gname = base_name if total==1 else f"{base_name} ({idx+1}/{total})"
                def cb(pct, m, i=idx):
                    self.after(0, lambda p=pct, t=m: [
                        self.prog_bar.set(p),
                        self.status_lbl.configure(text=f"[{i+1}/{total}] {t}")])
                ok, msg = add_shortcut_from_manifest(aid, gname, on_progress=cb)
                results.append((aid, ok, msg))
            except Exception as e:
                results.append((aid, False, str(e)))
        self.after(0, lambda: self._done_add(results))

    def _done_add(self, results):
        self._set_busy(False); self._check_system()
        ok_n = sum(1 for _,ok,_ in results if ok)
        tot  = len(results)
        if ok_n == tot:
            self.status_lbl.configure(text=f"✅  {ok_n} game(s) ready! Restart Steam.",
                                       text_color=self.c_success)
            messagebox.showinfo("Success",f"{ok_n} game(s) added!\nClick 'Restart Steam'.")
        elif ok_n > 0:
            failed = [a for a,ok,_ in results if not ok]
            self.status_lbl.configure(text=f"⚠  {ok_n}/{tot} added.",
                                       text_color=self.c_warning)
            messagebox.showwarning("Partial",f"{ok_n}/{tot} added.\nFailed: {', '.join(failed)}")
        else:
            self.status_lbl.configure(text="❌  Operation failed.", text_color=self.c_danger)
            messagebox.showerror("Error","Could not add:\n\n"+
                                 "\n".join(f"{a}: {m}" for a,_,m in results))
        if ok_n > 0:
            try: self._send_added(results[0][0],
                                  self.inp_name.get().strip() or f"{ok_n} Games", ok_n, tot)
            except Exception: pass
        self.inp_id.delete(0,"end"); self.inp_name.delete(0,"end")
        self._refresh_hero_stats()

    def _set_busy(self, busy, msg=""):
        self._busy = busy
        st = "disabled" if busy else "normal"
        for w in [self.btn_add, self.btn_restart, self.inp_id,
                  self.inp_name, self.inp_search]:
            w.configure(state=st)
        if busy:
            self.status_lbl.configure(text=msg, text_color=self.c_accent)
            self.prog_bar.set(0)
            self.prog_bar.pack(fill="x", pady=(8,0))
        else:
            self.btn_add.configure(state="normal", text="⚡  ADD TO LIBRARY")
            self.prog_bar.set(0); self.prog_bar.pack_forget()

    def _do_update(self, aid):
        threading.Thread(target=lambda: self._wk_update(aid), daemon=True).start()

    def _wk_update(self, aid):
        ok, msg = update_game(aid)
        if ok:
            gn = get_game_name_from_steam(aid) or f"Game_{aid}"
            self.after(0, lambda: self._send_updated(aid, gn))
        self.after(0, lambda: [self._load_games(), messagebox.showinfo("Info", msg)])

    def _do_remove(self, aid, card):
        if messagebox.askyesno("Confirm", "Remove this game?"):
            ok, msg = remove_game(aid)
            if ok:
                card.destroy()
                try:
                    gn = get_game_name_from_steam(aid) or f"Game_{aid}"
                    self._send_removed(aid, gn)
                except Exception: pass
                self._refresh_hero_stats()
            else:
                messagebox.showerror("Error", msg)

    def _do_steam_restart(self):
        self.status_lbl.configure(text="⏳  Restarting Steam…", text_color=self.c_accent)
        threading.Thread(target=self._wk_restart, daemon=True).start()

    def _wk_restart(self):
        ok = restart_steam()
        if ok:
            self.after(0, lambda: [
                self.status_lbl.configure(text="✅  Steam restarted!", text_color=self.c_success),
                messagebox.showinfo("Success","Steam restarted!")])
        else:
            self.after(0, lambda: [
                self.status_lbl.configure(text="❌  Steam not found!", text_color=self.c_danger),
                messagebox.showerror("Error","Steam.exe not found.")])

    # ─────────────────────────────────────────────────────────────────────────
    # UPDATES
    # ─────────────────────────────────────────────────────────────────────────
    def _check_update_on_start(self):
        time.sleep(2)
        with self._update_lock:
            if self._update_checking or self._update_dialog_open: return
            self._update_checking = True
        try:
            info = check_for_update()
            if info:
                self._update_info = info
                with self._update_lock:
                    if not self._update_dialog_open:
                        self.after(0, lambda: self._show_update_dlg(info))
        except Exception: pass
        finally:
            with self._update_lock: self._update_checking = False

    def _show_update_dlg(self, info):
        with self._update_lock:
            if self._update_dialog_open: return
            self._update_dialog_open = True
        ver  = info.get("version","?")
        size = info.get("size",0)/(1024*1024)
        try:
            if messagebox.askyesno("Update",
               f"New version available!\n\nCurrent: v{CURRENT_VERSION}\nNew: v{ver}\n"
               f"Size: {size:.1f} MB\n\nDownload?"):
                self._dl_update(info)
        finally:
            with self._update_lock: self._update_dialog_open = False

    def _manual_check_update(self):
        with self._update_lock:
            if self._update_checking or self._update_dialog_open: return
        self.btn_check_update.configure(state="disabled", text="Checking…")
        threading.Thread(target=self._wk_check_update, daemon=True).start()

    def _wk_check_update(self):
        with self._update_lock:
            if self._update_checking or self._update_dialog_open: return
            self._update_checking = True
        try:
            info = check_for_update()
            if info:
                self._update_info = info
                with self._update_lock:
                    if not self._update_dialog_open:
                        self.after(0, lambda: self._on_update_found(info))
            else:
                self.after(0, self._on_no_update)
        except Exception as e:
            self.after(0, lambda: self._on_update_err(str(e)))
        finally:
            with self._update_lock: self._update_checking = False

    def _on_update_found(self, info):
        with self._update_lock:
            if self._update_dialog_open: return
            self._update_dialog_open = True
        ver  = info.get("version","?")
        size = info.get("size",0)/(1024*1024)
        self.btn_check_update.configure(state="normal", text="Check for Updates")
        self.update_status_label.configure(
            text=f"v{ver} available! ({size:.1f} MB)", text_color=self.c_success)
        try:
            if messagebox.askyesno("Update Available",
               f"New version available!\nCurrent: v{CURRENT_VERSION}\nNew: v{ver}\n"
               f"Size: {size:.1f} MB\n\nDownload?"):
                self._dl_update(info)
        finally:
            with self._update_lock: self._update_dialog_open = False

    def _on_no_update(self):
        self.btn_check_update.configure(state="normal", text="Check for Updates")
        self.update_status_label.configure(text="You're on the latest version.",
                                            text_color=self.c_success)

    def _on_update_err(self, err):
        self.btn_check_update.configure(state="normal", text="Check for Updates")
        self.update_status_label.configure(text="Connection failed.", text_color=self.c_danger)

    def _dl_update(self, info):
        url = info.get("download_url")
        if not url: return
        self.btn_check_update.configure(state="disabled", text="Downloading…")
        def prog(dl, tot):
            if tot>0:
                self.after(0, lambda: self.update_status_label.configure(
                    text=f"Downloading: {dl/tot*100:.1f}% ({dl/1048576:.1f}/{tot/1048576:.1f} MB)",
                    text_color=self.c_accent))
        def worker():
            try:
                fp = download_update(url, prog)
                if fp: self.after(0, lambda: self._inst_update(fp))
                else:  self.after(0, lambda: messagebox.showerror("Error","Download failed!"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=worker, daemon=True).start()

    def _inst_update(self, fp):
        self.update_status_label.configure(text="Installing…")
        try: apply_update(fp)
        except Exception as e:
            messagebox.showerror("Error", f"Install error: {e}")
            self.btn_check_update.configure(state="normal", text="Retry")

    # ─────────────────────────────────────────────────────────────────────────
    # DISCORD
    # ─────────────────────────────────────────────────────────────────────────
    def _webhook(self, title, desc, color=0x8B5CF6, thumb=None):
        if not self._config.get("discord_webhook_enabled", True): return
        url = self._config.get("discord_webhook_url", DEFAULT_WEBHOOK_URL)
        if not url or not str(url).startswith("http"): return
        embed: dict[str,Any] = {"title":title,"description":desc,"color":color,
                                 "timestamp":time.strftime("%Y-%m-%dT%H:%M:%S.000Z",time.gmtime())}
        if thumb: embed["thumbnail"] = {"url": thumb}
        payload = {"embeds":[embed],"username":"GameInSteam",
                   "avatar_url":"https://cdn.akamai.steamstatic.com/steam/apps/730/header.jpg"}
        def post():
            try: requests.post(url, json=payload, timeout=8)
            except Exception: pass
        threading.Thread(target=post, daemon=True).start()

    def _send_added(self, aid, name, ok, tot):
        if tot==1: self._webhook("🎮 Game Added",f"**{name}**\nAppID: `{aid}`",
                                  0x8B5CF6, HEADER_URL.format(aid))
        else:      self._webhook("🎮 Games Added",f"**{ok}/{tot}** games added!",0x8B5CF6)

    def _send_updated(self, aid, name):
        self._webhook("🔄 Game Updated",f"**{name}**\nAppID: `{aid}`",
                      0x06B6D4, HEADER_URL.format(aid))

    def _send_removed(self, aid, name):
        self._webhook("🗑 Game Removed",f"**{name}**\nAppID: `{aid}`",
                      0xF43F5E, HEADER_URL.format(aid))


# ──────────────────────────────────────────────────────────────────────────────
def main():
    try:
        from ctypes import windll  # type: ignore
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    GameInSteamApp().mainloop()


if __name__ == "__main__":
    main()
