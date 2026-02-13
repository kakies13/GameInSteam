"""
GameInSteam — Premium Soft-Dark UI
Canvas-based rounded buttons, gradient card overlays,
muted teal accents, generous spacing.
"""

import io
import threading
import time
import tkinter as tk

import requests
from PIL import Image, ImageTk, ImageDraw

from steam_handler import (
    add_shortcut_from_manifest,
    check_stplugin_system,
    get_game_name_from_steam,
    list_added_games,
    remove_game,
    update_game,
)
from updater import check_for_update, download_update, apply_update, CURRENT_VERSION

# ═══════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════
CARD_W = 175
CARD_IMG_H = 230
CARD_GAP = 16
SIDEBAR_W = 220
TOAST_IMG_SZ = (200, 94)

HEADER_URL = "https://cdn.akamai.steamstatic.com/steam/apps/{}/header.jpg"
CAPSULE_URL = "https://cdn.akamai.steamstatic.com/steam/apps/{}/library_600x900.jpg"

FONT = "Segoe UI"
FONT_E = "Segoe UI Emoji"

# ═══════════════════════════════════════════════════════════════
# SOFT-DARK PALETTE  — muted teal, deep blue-grays
# ═══════════════════════════════════════════════════════════════
C = dict(
    bg="#0f1117",
    sidebar="#161b23",
    main="#12161e",
    card="#1a2030",
    card_h="#232d3e",
    inp="#171e28",
    toast="#1a2030",
    accent="#38b2ac",
    accent_h="#4fd1c5",
    accent_b="#81e6d9",
    accent_d="#285e61",
    accent_sub="#234e52",
    tx="#a0aec0",
    tx_d="#4a5568",
    tx_b="#e2e8f0",
    green="#48bb78",
    green_h="#68d391",
    green_bg="#162416",
    yellow="#ecc94b",
    yellow_bg="#262416",
    red="#fc8181",
    red_h="#feb2b2",
    red_bg="#261616",
    border="#2d3748",
    sel="#1a2332",
    badge="#234e52",
)


# ═══════════════════════════════════════════════════════════════
# HELPER — rounded rectangle on Canvas
# ═══════════════════════════════════════════════════════════════
def _rrect(cv, x1, y1, x2, y2, r, **kw):
    """Draw a smooth rounded rectangle."""
    pts = [
        x1 + r, y1,   x2 - r, y1,   x2, y1,   x2, y1 + r,
        x2, y2 - r,   x2, y2,       x2 - r, y2, x1 + r, y2,
        x1, y2,       x1, y2 - r,   x1, y1 + r, x1, y1,
    ]
    return cv.create_polygon(pts, smooth=True, **kw)


# ═══════════════════════════════════════════════════════════════
# SOFT BUTTON  — rounded, hover, disable support
# ═══════════════════════════════════════════════════════════════
class SoftButton(tk.Canvas):
    def __init__(
        self, parent, text="", command=None,
        bg=None, fg=None, hover=None,
        width=None, height=48, radius=12,
        font_spec=None, parent_bg=None,
    ):
        _bg = bg or C["accent"]
        _fg = fg or "#0f1117"
        _hov = hover or C["accent_h"]
        _font = font_spec or (FONT, 13, "bold")
        pbg = parent_bg or parent.cget("bg")

        kw = dict(height=height, bg=pbg, highlightthickness=0, bd=0)
        if width:
            kw["width"] = width
        super().__init__(parent, **kw)

        self._bg = _bg
        self._fg = _fg
        self._hov = _hov
        self._cmd = command
        self._off = False
        self._r = radius
        self._ts = text
        self._fnt = _font
        self._h = height
        self._rid = None
        self._tid = None

        self.bind("<Configure>", self._draw)
        self.bind("<Enter>", lambda _: self._fill(self._hov))
        self.bind("<Leave>", lambda _: self._fill(self._bg))
        self.bind("<Button-1>", lambda _: self._click())
        self.configure(cursor="hand2")

    def _draw(self, _e=None):
        w = self.winfo_width()
        if w < 12:
            return
        h = self._h
        self.delete("all")
        fill = C["card"] if self._off else self._bg
        fg = C["tx_d"] if self._off else self._fg
        self._rid = _rrect(self, 1, 1, w - 1, h - 1, self._r, fill=fill, outline="")
        self._tid = self.create_text(w // 2, h // 2, text=self._ts, fill=fg, font=self._fnt)

    def _fill(self, color):
        if not self._off and self._rid:
            self.itemconfig(self._rid, fill=color)

    def _click(self):
        if not self._off and self._cmd:
            self._cmd()

    def set_state(self, disabled, text=None):
        self._off = disabled
        if text:
            self._ts = text
        self._draw()
        self.configure(cursor="" if disabled else "hand2")

    def set_text(self, text):
        self._ts = text
        if self._tid:
            self.itemconfig(self._tid, text=text)


# ═══════════════════════════════════════════════════════════════
# HOVER BUTTON (secondary)
# ═══════════════════════════════════════════════════════════════
class HoverButton(tk.Button):
    def __init__(self, master, bg_n, bg_h, **kw):
        super().__init__(master, **kw)
        self.bg_n, self.bg_h = bg_n, bg_h
        self.configure(bg=bg_n)
        self.bind("<Enter>", lambda _: self.configure(bg=self.bg_h))
        self.bind("<Leave>", lambda _: self.configure(bg=self.bg_n))


# ═══════════════════════════════════════════════════════════════
# MAIN APPLICATION
# ═══════════════════════════════════════════════════════════════
class GameInSteamApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GameInSteam")
        self.root.geometry("1100x720")
        self.root.minsize(900, 600)
        self.root.configure(bg=C["bg"])

        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - 550
        y = (self.root.winfo_screenheight() // 2) - 360
        self.root.geometry(f"+{x}+{y}")

        self._busy = False
        self._progress = 0.0
        self._prog_target = 0.0
        self._name_cache: dict = {}
        self._img_cache: dict = {}
        self._card_widgets: list = []
        self._games: list = []
        self._placeholder = None
        self._toast_ref = None
        self._toast_img_ref = None
        self._toast_after = None
        self._current_page = None
        self._menu_items: dict = {}
        self._resize_after = None

        self._update_info = None

        self._build_ui()
        self._create_placeholder()
        self._check_system()
        self._navigate("library")
        self._check_updates_bg()

    # ─── placeholder ────────────────────────────────────
    def _create_placeholder(self):
        img = Image.new("RGB", (CARD_W, CARD_IMG_H), (20, 28, 42))
        draw = ImageDraw.Draw(img)
        for y in range(CARD_IMG_H):
            t = y / CARD_IMG_H
            draw.line(
                [(0, y), (CARD_W, y)],
                fill=(int(20 + t * 8), int(28 + t * 6), int(42 + t * 10)),
            )
        cx, cy = CARD_W // 2, CARD_IMG_H // 2
        for dx in (-16, 0, 16):
            s = 40 + abs(dx)
            draw.ellipse(
                [cx + dx - 4, cy - 4, cx + dx + 4, cy + 4],
                fill=(s, s + 12, s + 22),
            )
        self._placeholder = ImageTk.PhotoImage(img)

    # ═══════════════════════════════════════════════════════════════
    # BUILD UI
    # ═══════════════════════════════════════════════════════════════
    def _build_ui(self):
        self._build_sidebar()
        tk.Frame(self.root, bg=C["border"], width=1).pack(side="left", fill="y")

        self.main_frame = tk.Frame(self.root, bg=C["main"])
        self.main_frame.pack(side="left", fill="both", expand=True)

        self._build_topbar()

        self.content = tk.Frame(self.main_frame, bg=C["main"])
        self.content.pack(fill="both", expand=True)

        self._build_library_page()
        self._build_add_page()
        self._build_settings_page()
        self._build_statusbar()

    # ═══════════════════════════════════════════════════════════════
    # SIDEBAR
    # ═══════════════════════════════════════════════════════════════
    def _build_sidebar(self):
        sb = tk.Frame(self.root, bg=C["sidebar"], width=SIDEBAR_W)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        # ── Logo ──
        logo = tk.Frame(sb, bg=C["sidebar"])
        logo.pack(fill="x", padx=20, pady=(26, 32))

        icon_cv = tk.Canvas(logo, width=42, height=42, bg=C["sidebar"], highlightthickness=0)
        icon_cv.pack(side="left")
        _rrect(icon_cv, 0, 0, 42, 42, 12, fill=C["accent_d"], outline="")
        icon_cv.create_text(21, 21, text="🎮", font=(FONT_E, 17))

        tf = tk.Frame(logo, bg=C["sidebar"])
        tf.pack(side="left", padx=(14, 0))
        tk.Label(tf, text="GAME", font=(FONT, 14, "bold"),
                 bg=C["sidebar"], fg=C["tx_b"]).pack(anchor="w")
        tk.Label(tf, text="IN STEAM", font=(FONT, 8, "bold"),
                 bg=C["sidebar"], fg=C["accent"]).pack(anchor="w")

        # ── Menu ──
        tk.Label(sb, text="MAIN MENU", font=(FONT, 8, "bold"),
                 bg=C["sidebar"], fg=C["tx_d"],
                 anchor="w").pack(fill="x", padx=24, pady=(0, 8))

        self._menu_items["library"] = self._sidebar_item(
            sb, "📚", "Library", lambda: self._navigate("library"))
        self._menu_items["add"] = self._sidebar_item(
            sb, "➕", "Add Game", lambda: self._navigate("add"))
        self._menu_items["settings"] = self._sidebar_item(
            sb, "⚙️", "Settings", lambda: self._navigate("settings"))

        # ── Separator ──
        tk.Frame(sb, bg=C["border"], height=1).pack(fill="x", padx=20, pady=(22, 16))

        # ── Categories ──
        tk.Label(sb, text="CATEGORIES", font=(FONT, 8, "bold"),
                 bg=C["sidebar"], fg=C["tx_d"],
                 anchor="w").pack(fill="x", padx=24, pady=(0, 10))

        for clr, txt in [(C["accent"], "All Games"),
                         (C["yellow"], "Recently Added"),
                         (C["green"], "With DLC")]:
            row = tk.Frame(sb, bg=C["sidebar"])
            row.pack(fill="x", padx=24, pady=3)
            tk.Label(row, text="●", font=(FONT, 7),
                     bg=C["sidebar"], fg=clr).pack(side="left")
            tk.Label(row, text=txt, font=(FONT, 10),
                     bg=C["sidebar"], fg=C["tx_d"]).pack(side="left", padx=(8, 0))

        tk.Frame(sb, bg=C["sidebar"]).pack(fill="both", expand=True)

        # ── System status ──
        tk.Frame(sb, bg=C["border"], height=1).pack(fill="x", padx=20, pady=(0, 12))

        sys_r = tk.Frame(sb, bg=C["sidebar"])
        sys_r.pack(fill="x", padx=24, pady=(0, 8))
        self.sys_icon = tk.Label(sys_r, text="⏳", font=(FONT_E, 10),
                                 bg=C["sidebar"], fg=C["yellow"])
        self.sys_icon.pack(side="left")
        self.sys_label = tk.Label(sys_r, text="Checking...", font=(FONT, 8),
                                  bg=C["sidebar"], fg=C["tx_d"], anchor="w")
        self.sys_label.pack(side="left", padx=(8, 0))

        # ── Update button ──
        self.update_frame = tk.Frame(sb, bg=C["sidebar"])
        self.update_frame.pack(fill="x", padx=20, pady=(0, 8))

        self.update_btn = tk.Frame(self.update_frame, bg=C["accent_d"],
                                   cursor="hand2")
        self.update_btn.pack(fill="x", ipady=8)
        self.update_icon = tk.Label(self.update_btn, text="🔄", font=(FONT_E, 11),
                                    bg=C["accent_d"], fg=C["accent_b"])
        self.update_icon.pack(side="left", padx=(12, 8))
        self.update_label = tk.Label(self.update_btn, text="Check for Updates",
                                     font=(FONT, 9), bg=C["accent_d"],
                                     fg=C["accent_b"])
        self.update_label.pack(side="left")
        self.update_frame.pack_forget()  # Başta gizle, kontrol sonrası göster

        # (Settings artık üstteki menüde)

    # ─── sidebar item ───
    def _sidebar_item(self, parent, icon, text, cmd):
        item = tk.Frame(parent, bg=C["sidebar"], cursor="hand2")
        item.pack(fill="x", padx=12, pady=2)

        inner = tk.Frame(item, bg=C["sidebar"])
        inner.pack(fill="x", ipady=11, padx=2)

        bar = tk.Frame(inner, bg=C["sidebar"], width=3)
        bar.pack(side="left", fill="y", padx=(0, 14))

        ic = tk.Label(inner, text=icon, font=(FONT_E, 13),
                      bg=C["sidebar"], fg=C["tx_d"])
        ic.pack(side="left", padx=(0, 12))

        tl = tk.Label(inner, text=text, font=(FONT, 11),
                      bg=C["sidebar"], fg=C["tx_d"])
        tl.pack(side="left")

        item._bar, item._ic, item._tl, item._inner = bar, ic, tl, inner
        item._active = False

        def _click(_e):
            cmd()

        def _enter(_e):
            if not item._active:
                for w in (inner, ic, tl):
                    w.configure(bg=C["sel"])
                tl.configure(fg=C["tx"])

        def _leave(_e):
            if not item._active:
                for w in (inner, ic, tl):
                    w.configure(bg=C["sidebar"])
                tl.configure(fg=C["tx_d"])

        for w in (item, inner, ic, tl):
            w.bind("<Button-1>", _click)
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)
        return item

    def _set_menu_active(self, key):
        for k, it in self._menu_items.items():
            a = k == key
            it._active = a
            bg = C["sel"] if a else C["sidebar"]
            it._inner.configure(bg=bg)
            it._bar.configure(bg=C["accent"] if a else C["sidebar"])
            it._ic.configure(bg=bg, fg=C["accent"] if a else C["tx_d"])
            it._tl.configure(bg=bg, fg=C["tx_b"] if a else C["tx_d"])

    # ═══════════════════════════════════════════════════════════════
    # TOP BAR  — rounded search, sort, avatar
    # ═══════════════════════════════════════════════════════════════
    def _build_topbar(self):
        bar = tk.Frame(self.main_frame, bg=C["bg"], height=58)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        inner = tk.Frame(bar, bg=C["bg"])
        inner.pack(fill="x", padx=24, expand=True, anchor="center")

        # Search (canvas-rounded)
        self._scv = tk.Canvas(inner, height=40, bg=C["bg"], highlightthickness=0)
        self._scv.pack(side="left", fill="x", expand=True, pady=9)
        self._scv.bind("<Configure>", self._draw_search)

        self.search_entry = tk.Entry(
            self._scv, font=(FONT, 11),
            bg=C["inp"], fg=C["tx_d"],
            insertbackground=C["accent"],
            relief="flat", bd=0, highlightthickness=0,
        )
        self.search_entry.insert(0, "Search your games...")
        self.search_entry.bind("<FocusIn>", self._sfocus_in)
        self.search_entry.bind("<FocusOut>", self._sfocus_out)
        self.search_entry.bind("<KeyRelease>", self._sfilter)

        # Sort
        sf = tk.Frame(inner, bg=C["bg"])
        sf.pack(side="right", padx=(20, 0))
        tk.Label(sf, text="SORT BY:", font=(FONT, 8, "bold"),
                 bg=C["bg"], fg=C["tx_d"]).pack(side="left")
        tk.Label(sf, text="Recent Activity  ▾", font=(FONT, 10),
                 bg=C["bg"], fg=C["tx_b"]).pack(side="left", padx=(6, 0))

        # Avatar
        av = tk.Canvas(inner, width=36, height=36, bg=C["bg"], highlightthickness=0)
        av.pack(side="right", padx=(14, 0))
        _rrect(av, 0, 0, 36, 36, 18, fill=C["accent_d"], outline="")
        av.create_text(18, 18, text="👤", font=(FONT_E, 13))

    def _draw_search(self, _e=None):
        cv = self._scv
        w = cv.winfo_width()
        cv.delete("bg")
        _rrect(cv, 0, 0, w, 40, 12, fill=C["inp"], outline=C["border"], tags="bg")
        cv.create_text(20, 20, text="🔍", font=(FONT_E, 10),
                       fill=C["tx_d"], anchor="w", tags="bg")
        cv.tag_lower("bg")
        self.search_entry.place(x=42, y=5, height=30, width=max(10, w - 58))

    def _sfocus_in(self, _e):
        if self.search_entry.get() == "Search your games...":
            self.search_entry.delete(0, "end")
            self.search_entry.configure(fg=C["tx_b"])

    def _sfocus_out(self, _e):
        if not self.search_entry.get().strip():
            self.search_entry.delete(0, "end")
            self.search_entry.insert(0, "Search your games...")
            self.search_entry.configure(fg=C["tx_d"])

    def _sfilter(self, _e=None):
        q = self.search_entry.get().strip().lower()
        if q == "search your games...":
            q = ""
        if self._current_page == "library":
            self._reflow_grid(q)

    # ═══════════════════════════════════════════════════════════════
    # STATUS BAR
    # ═══════════════════════════════════════════════════════════════
    def _build_statusbar(self):
        bar = tk.Frame(self.main_frame, bg=C["sidebar"], height=32)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        inner = tk.Frame(bar, bg=C["sidebar"])
        inner.pack(fill="x", padx=18)

        self.stat_total = tk.Label(
            inner, text="●  TOTAL GAMES: 0", font=(FONT, 8, "bold"),
            bg=C["sidebar"], fg=C["green"])
        self.stat_total.pack(side="left", pady=7)

        self.stat_update = tk.Label(
            inner, text="●  UPDATE READY: 0", font=(FONT, 8, "bold"),
            bg=C["sidebar"], fg=C["yellow"])
        self.stat_update.pack(side="left", padx=(20, 0))

        self.stat_steam = tk.Label(
            inner, text="🎮  STEAM STATUS: CONNECTED", font=(FONT, 8, "bold"),
            bg=C["sidebar"], fg=C["green"])
        self.stat_steam.pack(side="right")

        self.ver_label = tk.Label(inner, text=f"v{CURRENT_VERSION}", font=(FONT, 7),
                                  bg=C["sidebar"], fg=C["tx_d"])
        self.ver_label.pack(side="right", padx=(0, 18))

    # ═══════════════════════════════════════════════════════════════
    # LIBRARY PAGE
    # ═══════════════════════════════════════════════════════════════
    def _build_library_page(self):
        self.pg_lib = tk.Frame(self.content, bg=C["main"])

        hdr = tk.Frame(self.pg_lib, bg=C["main"])
        hdr.pack(fill="x", padx=24, pady=(20, 14))

        self.lib_title = tk.Label(hdr, text="Installed Games",
                                  font=(FONT, 18, "bold"),
                                  bg=C["main"], fg=C["tx_b"])
        self.lib_title.pack(side="left")

        self.lib_count_lbl = tk.Label(hdr, text="(0)", font=(FONT, 15),
                                      bg=C["main"], fg=C["tx_d"])
        self.lib_count_lbl.pack(side="left", padx=(10, 0))

        toggle = tk.Frame(hdr, bg=C["main"])
        toggle.pack(side="right")
        HoverButton(toggle, bg_n=C["card"], bg_h=C["accent_d"],
                     text="▣", font=(FONT, 14), fg=C["accent"],
                     relief="flat", bd=0, width=3,
                     activebackground=C["accent_d"],
                     activeforeground=C["accent"]).pack(side="left", padx=2)
        HoverButton(toggle, bg_n=C["card"], bg_h=C["accent_d"],
                     text="☰", font=(FONT, 14), fg=C["tx_d"],
                     relief="flat", bd=0, width=3,
                     activebackground=C["accent_d"],
                     activeforeground=C["tx"]).pack(side="left")

        # Scrollable grid
        gw = tk.Frame(self.pg_lib, bg=C["main"])
        gw.pack(fill="both", expand=True)

        self.cv = tk.Canvas(gw, bg=C["main"], highlightthickness=0)
        self.cv.pack(fill="both", expand=True)

        self.cv_inner = tk.Frame(self.cv, bg=C["main"])
        self.cv_win = self.cv.create_window((0, 0), window=self.cv_inner, anchor="nw")
        self.cv_inner.bind("<Configure>",
                           lambda _: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.bind("<Configure>", self._on_cv_resize)
        self.cv.bind("<Enter>",
                     lambda _: self.cv.bind_all("<MouseWheel>", self._on_mwheel))
        self.cv.bind("<Leave>",
                     lambda _: self.cv.unbind_all("<MouseWheel>"))

        # FAB
        self.fab = SoftButton(
            self.pg_lib, text="+", command=lambda: self._navigate("add"),
            bg=C["accent"], fg="#0f1117", hover=C["accent_h"],
            width=52, height=52, radius=26,
            font_spec=(FONT, 22, "bold"), parent_bg=C["main"])
        self.fab.place(relx=0.96, rely=0.93, anchor="se")

    def _on_mwheel(self, e):
        self.cv.yview_scroll(int(-1 * (e.delta / 120)), "units")

    def _on_cv_resize(self, ev):
        self.cv.itemconfig(self.cv_win, width=ev.width)
        if self._resize_after:
            self.root.after_cancel(self._resize_after)
        self._resize_after = self.root.after(80, self._reflow_grid)

    # ═══════════════════════════════════════════════════════════════
    # ADD GAME PAGE
    # ═══════════════════════════════════════════════════════════════
    def _build_add_page(self):
        self.pg_add = tk.Frame(self.content, bg=C["main"])

        center = tk.Frame(self.pg_add, bg=C["main"])
        center.place(relx=0.5, rely=0.43, anchor="center")

        card = tk.Frame(center, bg=C["card"],
                        highlightbackground=C["border"], highlightthickness=1)
        card.pack()

        inner = tk.Frame(card, bg=C["card"])
        inner.pack(padx=50, pady=40)

        tk.Label(inner, text="Add New Game", font=(FONT, 20, "bold"),
                 bg=C["card"], fg=C["tx_b"]).pack(anchor="w", pady=(0, 4))
        tk.Label(inner, text="Enter a Steam App ID to add it to your library",
                 font=(FONT, 10), bg=C["card"], fg=C["tx_d"]).pack(anchor="w", pady=(0, 30))

        # APP ID
        tk.Label(inner, text="APP ID", font=(FONT, 9, "bold"),
                 bg=C["card"], fg=C["tx_d"]).pack(anchor="w", pady=(0, 6))

        id_wrap = tk.Frame(inner, bg=C["inp"],
                           highlightbackground=C["border"],
                           highlightcolor=C["accent"], highlightthickness=1)
        id_wrap.pack(fill="x", pady=(0, 4))
        self.inp_id = tk.Entry(id_wrap, font=(FONT, 13),
                               bg=C["inp"], fg=C["tx_b"],
                               insertbackground=C["accent"],
                               relief="flat", bd=0, width=38)
        self.inp_id.pack(padx=14, ipady=10)

        tk.Label(inner, text="💡 e.g. store.steampowered.com/app/730",
                 font=(FONT, 8), bg=C["card"], fg=C["tx_d"]).pack(anchor="w", pady=(0, 22))

        # GAME NAME
        tk.Label(inner, text="GAME NAME  (optional)", font=(FONT, 9, "bold"),
                 bg=C["card"], fg=C["tx_d"]).pack(anchor="w", pady=(0, 6))

        nm_wrap = tk.Frame(inner, bg=C["inp"],
                           highlightbackground=C["border"],
                           highlightcolor=C["accent"], highlightthickness=1)
        nm_wrap.pack(fill="x", pady=(0, 30))
        self.inp_name = tk.Entry(nm_wrap, font=(FONT, 13),
                                 bg=C["inp"], fg=C["tx_b"],
                                 insertbackground=C["accent"],
                                 relief="flat", bd=0)
        self.inp_name.pack(padx=14, ipady=10)

        # Rounded button
        self.btn_add = SoftButton(
            inner, text="⚡  Add Game", command=self._do_add,
            bg=C["accent"], fg="#0f1117", hover=C["accent_h"],
            height=52, radius=14, font_spec=(FONT, 14, "bold"),
            parent_bg=C["card"])
        self.btn_add.pack(fill="x")

        # Status / progress
        self.status_frame = tk.Frame(inner, bg=C["card"])
        self.status_icon = tk.Label(self.status_frame, text="",
                                    font=(FONT_E, 11), bg=C["card"])
        self.status_icon.pack(side="left")
        self.status_text = tk.Label(self.status_frame, text="",
                                    font=(FONT, 10), bg=C["card"],
                                    fg=C["tx"], anchor="w")
        self.status_text.pack(side="left", padx=(6, 0))
        self.status_pct = tk.Label(self.status_frame, text="",
                                   font=(FONT, 11, "bold"), bg=C["card"],
                                   fg=C["accent"])
        self.status_pct.pack(side="right")
        self.prog = tk.Canvas(self.status_frame, height=8,
                              bg=C["card"], highlightthickness=0)
        self.prog.pack(fill="x", pady=(10, 0))

    # ═══════════════════════════════════════════════════════════════
    # SETTINGS PAGE
    # ═══════════════════════════════════════════════════════════════
    def _build_settings_page(self):
        self.pg_settings = tk.Frame(self.content, bg=C["main"])

        # ── Header ──
        hdr = tk.Frame(self.pg_settings, bg=C["main"])
        hdr.pack(fill="x", padx=24, pady=(20, 24))
        tk.Label(hdr, text="Settings", font=(FONT, 18, "bold"),
                 bg=C["main"], fg=C["tx_b"]).pack(side="left")

        # ── Scrollable content ──
        s_cv = tk.Canvas(self.pg_settings, bg=C["main"], highlightthickness=0)
        s_cv.pack(fill="both", expand=True)
        s_inner = tk.Frame(s_cv, bg=C["main"])
        s_cv.create_window((0, 0), window=s_inner, anchor="nw")
        s_inner.bind("<Configure>",
                     lambda _: s_cv.configure(scrollregion=s_cv.bbox("all")))
        s_cv.bind("<Enter>",
                  lambda _: s_cv.bind_all("<MouseWheel>",
                                          lambda e: s_cv.yview_scroll(int(-1 * (e.delta / 120)), "units")))
        s_cv.bind("<Leave>", lambda _: s_cv.unbind_all("<MouseWheel>"))

        wrap = tk.Frame(s_inner, bg=C["main"])
        wrap.pack(fill="x", padx=24, pady=(0, 20))

        # ════════════════════════════════════════
        # CARD 1: Updates
        # ════════════════════════════════════════
        upd_card = tk.Frame(wrap, bg=C["card"],
                            highlightbackground=C["border"], highlightthickness=1)
        upd_card.pack(fill="x", pady=(0, 16))
        upd_inner = tk.Frame(upd_card, bg=C["card"])
        upd_inner.pack(fill="x", padx=24, pady=20)

        # Title row
        upd_hdr = tk.Frame(upd_inner, bg=C["card"])
        upd_hdr.pack(fill="x", pady=(0, 16))
        tk.Label(upd_hdr, text="🔄", font=(FONT_E, 16),
                 bg=C["card"], fg=C["accent"]).pack(side="left")
        tk.Label(upd_hdr, text="Updates", font=(FONT, 15, "bold"),
                 bg=C["card"], fg=C["tx_b"]).pack(side="left", padx=(10, 0))

        # Current version
        ver_row = tk.Frame(upd_inner, bg=C["card"])
        ver_row.pack(fill="x", pady=(0, 12))
        tk.Label(ver_row, text="Current Version", font=(FONT, 10),
                 bg=C["card"], fg=C["tx_d"]).pack(side="left")
        self.set_ver_value = tk.Label(ver_row, text=f"v{CURRENT_VERSION}",
                                      font=(FONT, 11, "bold"),
                                      bg=C["card"], fg=C["accent"])
        self.set_ver_value.pack(side="right")

        # Auto-update toggle
        auto_row = tk.Frame(upd_inner, bg=C["card"])
        auto_row.pack(fill="x", pady=(0, 12))
        tk.Label(auto_row, text="Auto-Check Updates on Startup",
                 font=(FONT, 10), bg=C["card"], fg=C["tx"]).pack(side="left")

        self._auto_update_on = True
        self.auto_toggle = tk.Frame(auto_row, bg=C["accent"], width=44, height=24,
                                    cursor="hand2")
        self.auto_toggle.pack(side="right")
        self.auto_toggle.pack_propagate(False)
        self.toggle_knob = tk.Frame(self.auto_toggle, bg="#fff", width=20, height=20)
        self.toggle_knob.place(x=22, y=2)
        self.auto_toggle.bind("<Button-1>", lambda _: self._toggle_auto_update())

        tk.Frame(upd_inner, bg=C["border"], height=1).pack(fill="x", pady=(4, 16))

        # Update status
        self.set_update_status = tk.Label(
            upd_inner, text="", font=(FONT, 10),
            bg=C["card"], fg=C["tx_d"], anchor="w")
        self.set_update_status.pack(fill="x", pady=(0, 14))

        # Update progress bar
        self.set_update_prog = tk.Canvas(upd_inner, height=8,
                                         bg=C["card"], highlightthickness=0)
        self.set_update_prog.pack(fill="x", pady=(0, 14))
        self.set_update_prog.pack_forget()

        # Buttons row
        btn_row = tk.Frame(upd_inner, bg=C["card"])
        btn_row.pack(fill="x")

        self.btn_check_update = SoftButton(
            btn_row, text="🔍  Check for Updates",
            command=self._settings_check_update,
            bg=C["accent"], fg="#0f1117", hover=C["accent_h"],
            width=220, height=44, radius=12,
            font_spec=(FONT, 11, "bold"), parent_bg=C["card"])
        self.btn_check_update.pack(side="left", padx=(0, 12))

        self.btn_install_update = SoftButton(
            btn_row, text="⬇  Install Update",
            command=self._do_update_app,
            bg=C["green"], fg="#0f1117", hover=C["green_h"],
            width=200, height=44, radius=12,
            font_spec=(FONT, 11, "bold"), parent_bg=C["card"])
        self.btn_install_update.pack(side="left")
        self.btn_install_update.pack_forget()  # Güncelleme yoksa gizle

        # ════════════════════════════════════════
        # CARD 2: System Info
        # ════════════════════════════════════════
        sys_card = tk.Frame(wrap, bg=C["card"],
                            highlightbackground=C["border"], highlightthickness=1)
        sys_card.pack(fill="x", pady=(0, 16))
        sys_inner = tk.Frame(sys_card, bg=C["card"])
        sys_inner.pack(fill="x", padx=24, pady=20)

        sys_hdr = tk.Frame(sys_inner, bg=C["card"])
        sys_hdr.pack(fill="x", pady=(0, 16))
        tk.Label(sys_hdr, text="💻", font=(FONT_E, 16),
                 bg=C["card"], fg=C["accent"]).pack(side="left")
        tk.Label(sys_hdr, text="System Information", font=(FONT, 15, "bold"),
                 bg=C["card"], fg=C["tx_b"]).pack(side="left", padx=(10, 0))

        info_items = [
            ("Application", f"GameInSteam v{CURRENT_VERSION}"),
            ("Platform", "Windows 10/11 (64-bit)"),
            ("Steam Plugin", "stplug-in (Lua)"),
            ("Proxy DLL", "xinput1_4.dll"),
        ]
        for label, value in info_items:
            row = tk.Frame(sys_inner, bg=C["card"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, font=(FONT, 10),
                     bg=C["card"], fg=C["tx_d"]).pack(side="left")
            tk.Label(row, text=value, font=(FONT, 10, "bold"),
                     bg=C["card"], fg=C["tx"]).pack(side="right")

        tk.Frame(sys_inner, bg=C["border"], height=1).pack(fill="x", pady=(12, 12))

        self.set_dll_status = tk.Label(sys_inner, text="",
                                       font=(FONT, 10), bg=C["card"],
                                       fg=C["green"], anchor="w")
        self.set_dll_status.pack(fill="x")

        # ════════════════════════════════════════
        # CARD 3: About
        # ════════════════════════════════════════
        about_card = tk.Frame(wrap, bg=C["card"],
                              highlightbackground=C["border"], highlightthickness=1)
        about_card.pack(fill="x", pady=(0, 16))
        about_inner = tk.Frame(about_card, bg=C["card"])
        about_inner.pack(fill="x", padx=24, pady=20)

        about_hdr = tk.Frame(about_inner, bg=C["card"])
        about_hdr.pack(fill="x", pady=(0, 12))
        tk.Label(about_hdr, text="ℹ️", font=(FONT_E, 16),
                 bg=C["card"], fg=C["accent"]).pack(side="left")
        tk.Label(about_hdr, text="About", font=(FONT, 15, "bold"),
                 bg=C["card"], fg=C["tx_b"]).pack(side="left", padx=(10, 0))

        tk.Label(about_inner,
                 text="GameInSteam — Steam Library Manager\n"
                      "Add any game to your Steam library with one click.\n\n"
                      "© 2026 GameInSteam. Educational purposes only.",
                 font=(FONT, 10), bg=C["card"], fg=C["tx_d"],
                 justify="left", anchor="w").pack(fill="x")

    def _toggle_auto_update(self):
        self._auto_update_on = not self._auto_update_on
        if self._auto_update_on:
            self.auto_toggle.configure(bg=C["accent"])
            self.toggle_knob.place(x=22, y=2)
        else:
            self.auto_toggle.configure(bg=C["tx_d"])
            self.toggle_knob.place(x=2, y=2)

    def _refresh_settings(self):
        """Settings sayfası açıldığında bilgileri güncelle."""
        ok, _ = check_stplugin_system()
        if ok:
            self.set_dll_status.configure(
                text="✅ xinput1_4.dll — Active", fg=C["green"])
        else:
            self.set_dll_status.configure(
                text="⚠️ xinput1_4.dll — Missing", fg=C["yellow"])

        if self._update_info:
            ver = self._update_info["version"]
            size_mb = self._update_info["size"] / (1024 * 1024)
            self.set_update_status.configure(
                text=f"✨ New version available: v{ver} ({size_mb:.1f} MB)",
                fg=C["accent"])
            self.btn_install_update.pack(side="left")
            self.set_ver_value.configure(
                text=f"v{CURRENT_VERSION}  →  v{ver}", fg=C["yellow"])
        else:
            self.set_update_status.configure(
                text="✅ You're up to date!", fg=C["green"])
            self.btn_install_update.pack_forget()

    def _settings_check_update(self):
        """Settings'ten güncelleme kontrolü."""
        self.btn_check_update.set_state(True, "🔍  Checking...")
        self.set_update_status.configure(
            text="⏳ Checking for updates...", fg=C["accent"])

        def _worker():
            info = check_for_update()
            self.root.after(0, lambda: self._settings_check_done(info))

        threading.Thread(target=_worker, daemon=True).start()

    def _settings_check_done(self, info):
        """Güncelleme kontrol sonucu."""
        self.btn_check_update.set_state(False, "🔍  Check for Updates")
        if info:
            self._update_info = info
            self._show_update_available(info)
            self._refresh_settings()
        else:
            self._update_info = None
            self.set_update_status.configure(
                text="✅ You're on the latest version!", fg=C["green"])
            self.btn_install_update.pack_forget()
            self._toast("info", "No Updates", "You're already on the latest version.",
                        duration=3000)

    # ═══════════════════════════════════════════════════════════════
    # NAVIGATION
    # ═══════════════════════════════════════════════════════════════
    def _navigate(self, page):
        if page == self._current_page:
            return
        self._current_page = page
        self._set_menu_active(page)
        self.pg_lib.pack_forget()
        self.pg_add.pack_forget()
        self.pg_settings.pack_forget()
        if page == "library":
            self.pg_lib.pack(in_=self.content, fill="both", expand=True)
            self._load_games()
        elif page == "add":
            self.pg_add.pack(in_=self.content, fill="both", expand=True)
        elif page == "settings":
            self.pg_settings.pack(in_=self.content, fill="both", expand=True)
            self._refresh_settings()

    # ═══════════════════════════════════════════════════════════════
    # GAME LIBRARY
    # ═══════════════════════════════════════════════════════════════
    def _load_games(self):
        for w in self.cv_inner.winfo_children():
            w.destroy()
        self._card_widgets = []
        self._games = list_added_games()
        n = len(self._games)
        self.lib_count_lbl.configure(text=f"({n})")
        self.stat_total.configure(text=f"●  TOTAL GAMES: {n}")

        if not self._games:
            empty = tk.Frame(self.cv_inner, bg=C["main"])
            empty.pack(fill="both", expand=True, pady=100)
            tk.Label(empty, text="📭", font=(FONT_E, 48),
                     bg=C["main"], fg=C["tx_d"]).pack()
            tk.Label(empty, text="No games added yet",
                     font=(FONT, 16), bg=C["main"], fg=C["tx_d"]).pack(pady=(12, 4))
            tk.Label(empty, text="Click '+' or 'Add Game' to get started",
                     font=(FONT, 11), bg=C["main"], fg=C["tx_d"]).pack()
            return

        for g in self._games:
            self._card_widgets.append((self._make_card(g), g))
        self._reflow_grid()

    # ─── game card ──────────────────────────────────────
    def _make_card(self, g):
        aid = g["app_id"]

        card = tk.Frame(self.cv_inner, bg=C["card"], cursor="hand2",
                        highlightbackground=C["card"], highlightthickness=1)

        # Image
        img_lbl = tk.Label(card, bg=C["card"], image=self._placeholder,
                           width=CARD_W, height=CARD_IMG_H)
        img_lbl.pack(padx=4, pady=(4, 0))
        card._img_lbl = img_lbl

        # Badge
        badge = tk.Label(card, text=f"APPID: {aid}",
                         font=(FONT, 7, "bold"),
                         bg=C["badge"], fg=C["accent_b"], padx=6, pady=2)
        badge.place(x=10, y=CARD_IMG_H - 16)
        card._badge = badge

        # Name
        cached = self._name_cache.get(aid, "")
        name_lbl = tk.Label(card, text=cached or f"Game #{aid}",
                            font=(FONT, 10, "bold"), bg=C["card"],
                            fg=C["tx_b"], anchor="w",
                            wraplength=CARD_W - 16)
        name_lbl.pack(padx=10, pady=(10, 4), anchor="w")
        card._name_lbl = name_lbl

        # ── Action buttons (Update / Remove) ──
        btn_row = tk.Frame(card, bg=C["card"])
        btn_row.pack(fill="x", padx=8, pady=(2, 10))
        card._btn_row = btn_row

        btn_upd = tk.Label(
            btn_row, text="🔄 Update", font=(FONT, 8, "bold"),
            bg="#1e2633", fg=C["accent"], cursor="hand2",
            padx=8, pady=4)
        btn_upd.pack(side="left", padx=(0, 4))
        card._btn_upd = btn_upd

        btn_del = tk.Label(
            btn_row, text="🗑 Remove", font=(FONT, 8, "bold"),
            bg="#1e2633", fg="#e06060", cursor="hand2",
            padx=8, pady=4)
        btn_del.pack(side="left")
        card._btn_del = btn_del

        # Button hover effects
        def _btn_enter(e, lbl, fg_h):
            lbl.configure(bg=C["accent_d"])
        def _btn_leave(e, lbl, bg_n="#1e2633"):
            lbl.configure(bg=bg_n)

        btn_upd.bind("<Enter>", lambda e, l=btn_upd: _btn_enter(e, l, C["accent"]))
        btn_upd.bind("<Leave>", lambda e, l=btn_upd: _btn_leave(e, l))
        btn_del.bind("<Enter>", lambda e, l=btn_del: _btn_enter(e, l, "#e06060"))
        btn_del.bind("<Leave>", lambda e, l=btn_del: _btn_leave(e, l))

        btn_upd.bind("<Button-1>", lambda e, a=aid: self._do_update(a))
        btn_del.bind("<Button-1>", lambda e, a=aid, c=card: self._do_remove(a, c))

        # Hover – card highlight
        skip_widgets = (badge, btn_upd, btn_del)
        def _enter(_e, c=card, skip=skip_widgets):
            c.configure(bg=C["card_h"], highlightbackground=C["accent_d"])
            for ch in c.winfo_children():
                try:
                    if ch not in skip:
                        ch.configure(bg=C["card_h"])
                except tk.TclError:
                    pass

        def _leave(_e, c=card, skip=skip_widgets):
            c.configure(bg=C["card"], highlightbackground=C["card"])
            for ch in c.winfo_children():
                try:
                    if ch not in skip:
                        ch.configure(bg=C["card"])
                except tk.TclError:
                    pass

        for w in (card, img_lbl, name_lbl):
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)

        # Lazy load
        if not cached:
            threading.Thread(target=self._fetch_name,
                             args=(aid, name_lbl), daemon=True).start()
        if aid not in self._img_cache:
            threading.Thread(target=self._fetch_img,
                             args=(aid, img_lbl), daemon=True).start()
        else:
            img_lbl.configure(image=self._img_cache[aid])

        return card

    # ─── grid reflow ────────────────────────────────────
    def _reflow_grid(self, q=""):
        cw = self.cv.winfo_width()
        if cw < 100:
            cw = 800
        cols = max(1, (cw - 30) // (CARD_W + CARD_GAP + 8))
        for c, _ in self._card_widgets:
            c.grid_forget()
        idx = 0
        for card, g in self._card_widgets:
            aid = g["app_id"]
            name = self._name_cache.get(aid, "").lower()
            if q and q not in name and q not in aid:
                continue
            card.grid(row=idx // cols, column=idx % cols,
                      padx=CARD_GAP // 2, pady=CARD_GAP // 2, sticky="n")
            idx += 1

    # ═══════════════════════════════════════════════════════════════
    # IMAGE / NAME FETCHING
    # ═══════════════════════════════════════════════════════════════
    def _fetch_img(self, aid, lbl):
        try:
            img = None
            resp = requests.get(CAPSULE_URL.format(aid), timeout=6)
            if resp.status_code == 200:
                try:
                    img = Image.open(io.BytesIO(resp.content))
                except Exception:
                    img = None
            if img is None:
                resp = requests.get(HEADER_URL.format(aid), timeout=6)
                if resp.status_code != 200:
                    return
                img = Image.open(io.BytesIO(resp.content))

            # Smart crop
            w, h = img.size
            tr = CARD_W / CARD_IMG_H
            if w / h > tr * 1.1:
                nw = int(h * tr)
                l = (w - nw) // 2
                img = img.crop((l, 0, l + nw, h))
            elif w / h < tr * 0.9:
                nh = int(w / tr)
                img = img.crop((0, 0, w, nh))

            img = img.resize((CARD_W, CARD_IMG_H), Image.LANCZOS)
            img = self._gradient(img)

            photo = ImageTk.PhotoImage(img)
            self._img_cache[aid] = photo
            self.root.after(
                0, lambda: lbl.configure(image=photo) if lbl.winfo_exists() else None)
        except Exception:
            pass

    def _gradient(self, img):
        """Add subtle dark gradient at bottom for badge readability."""
        rgba = img.convert("RGBA")
        ov = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(ov)
        h = rgba.size[1]
        start = int(h * 0.6)
        for y in range(start, h):
            a = int(160 * ((y - start) / (h - start)))
            draw.line([(0, y), (rgba.size[0], y)], fill=(15, 20, 30, a))
        return Image.alpha_composite(rgba, ov).convert("RGB")

    def _fetch_name(self, aid, lbl):
        name = get_game_name_from_steam(aid)
        if name:
            self._name_cache[aid] = name
            self.root.after(
                0, lambda: lbl.configure(text=name) if lbl.winfo_exists() else None)

    # ═══════════════════════════════════════════════════════════════
    # TOAST NOTIFICATIONS
    # ═══════════════════════════════════════════════════════════════
    def _toast(self, kind, title, msg, app_id=None, duration=5000):
        self._toast_dismiss()
        colors = {
            "success": (C["green"],  C["green_bg"],  "✅"),
            "error":   (C["red"],    C["red_bg"],    "❌"),
            "warning": (C["yellow"], C["yellow_bg"], "⚠️"),
            "info":    (C["accent"], C["toast"],     "ℹ️"),
        }
        acc, bg, ico = colors.get(kind, colors["info"])

        toast = tk.Frame(self.root, bg=bg,
                         highlightbackground=acc, highlightthickness=2)
        toast.place(relx=0.5, rely=0, anchor="n", relwidth=0.72)
        self._toast_ref = toast

        inner = tk.Frame(toast, bg=bg)
        inner.pack(fill="x", padx=14, pady=12)

        if app_id:
            ih = tk.Label(inner, bg=C["card"],
                          width=TOAST_IMG_SZ[0], height=TOAST_IMG_SZ[1])
            ih.pack(side="left", padx=(0, 14))
            threading.Thread(target=self._fetch_toast_img,
                             args=(app_id, ih), daemon=True).start()

        tf = tk.Frame(inner, bg=bg)
        tf.pack(side="left", fill="both", expand=True)
        hdr = tk.Frame(tf, bg=bg)
        hdr.pack(fill="x")
        tk.Label(hdr, text=ico, font=(FONT_E, 14), bg=bg, fg=acc).pack(side="left")
        tk.Label(hdr, text=title, font=(FONT, 13, "bold"),
                 bg=bg, fg=C["tx_b"], anchor="w").pack(side="left", padx=(8, 0))
        tk.Label(tf, text=msg, font=(FONT, 9), bg=bg, fg=C["tx"],
                 anchor="w", justify="left",
                 wraplength=400).pack(anchor="w", pady=(4, 0))

        cl = tk.Label(inner, text="✕", font=(FONT, 14, "bold"),
                      bg=bg, fg=C["tx_d"], cursor="hand2")
        cl.pack(side="right", anchor="ne")
        cl.bind("<Enter>", lambda _: cl.configure(fg=C["tx_b"]))
        cl.bind("<Leave>", lambda _: cl.configure(fg=C["tx_d"]))
        cl.bind("<Button-1>", lambda _: self._toast_dismiss())

        bar = tk.Canvas(toast, height=3, bg=bg, highlightthickness=0)
        bar.pack(fill="x", side="bottom")
        self._toast_cd(bar, acc, duration, time.time())

    def _toast_cd(self, bar, acc, dur, t0):
        if self._toast_ref is None:
            return
        el = (time.time() - t0) * 1000
        if el >= dur:
            self._toast_dismiss()
            return
        r = 1.0 - el / dur
        w = bar.winfo_width() or 500
        bar.delete("all")
        bar.create_rectangle(0, 0, int(w * r), 3, fill=acc, outline="")
        self.root.after(30, lambda: self._toast_cd(bar, acc, dur, t0))

    def _toast_dismiss(self):
        if self._toast_after:
            self.root.after_cancel(self._toast_after)
            self._toast_after = None
        if self._toast_ref and self._toast_ref.winfo_exists():
            self._toast_ref.destroy()
        self._toast_ref = None
        self._toast_img_ref = None

    def _fetch_toast_img(self, aid, lbl):
        try:
            resp = requests.get(HEADER_URL.format(aid), timeout=5)
            if resp.status_code != 200:
                return
            img = Image.open(io.BytesIO(resp.content))
            img = img.resize(TOAST_IMG_SZ, Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._toast_img_ref = photo
            self.root.after(
                0, lambda: lbl.configure(image=photo) if lbl.winfo_exists() else None)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════
    # SYSTEM CHECK
    # ═══════════════════════════════════════════════════════════════
    def _check_system(self):
        ok, msg = check_stplugin_system()
        if ok:
            self.sys_icon.configure(text="✅", fg=C["green"])
            self.sys_label.configure(text="System active", fg=C["green"])
            self.stat_steam.configure(text="🎮  STEAM STATUS: CONNECTED", fg=C["green"])
        else:
            self.sys_icon.configure(text="⚠️", fg=C["yellow"])
            self.sys_label.configure(text="DLL missing", fg=C["yellow"])
            self.stat_steam.configure(text="⚠️  STEAM: CHECK DLL", fg=C["yellow"])

    # ═══════════════════════════════════════════════════════════════
    # ADD GAME
    # ═══════════════════════════════════════════════════════════════
    def _do_add(self):
        app_id = self.inp_id.get().strip()
        name = self.inp_name.get().strip()
        if not app_id:
            self._toast("warning", "App ID Required", "Please enter a Steam App ID.")
            return
        if not app_id.isdigit():
            self._toast("warning", "Invalid App ID", "App ID must be a number.")
            return
        if not name:
            name = f"Game_{app_id}"
        self._set_busy(True, "Adding game...")
        threading.Thread(target=self._worker_add,
                         args=(app_id, name), daemon=True).start()

    def _worker_add(self, app_id, name):
        def _p(pct, msg):
            self.root.after(0, lambda: self._set_progress(pct, msg))
        try:
            ok, msg = add_shortcut_from_manifest(app_id, name, on_progress=_p)
            self.root.after(0, lambda: self._set_progress(1.0, "Done!"))
            time.sleep(0.5)
        except Exception as e:
            ok, msg = False, str(e)
        self.root.after(0, lambda: self._done_add(ok, msg, app_id, name))

    def _done_add(self, ok, msg, app_id, name):
        self._set_busy(False)
        self._check_system()
        if ok:
            self._show_status("✅", "Added successfully!", C["green"])
            self._toast("success", f"{name} Added!", msg, app_id=app_id, duration=6000)
        else:
            self._show_status("❌", "Failed to add", C["red"])
            self._toast("error", "Failed to Add", msg, app_id=app_id, duration=7000)

    # ─── update ─────────────────────────────────────────
    def _do_update(self, aid):
        if self._busy:
            self._toast("warning", "Busy", "Please wait for current task.")
            return
        name = self._name_cache.get(aid, f"AppID {aid}")
        self._busy = True
        self.stat_steam.configure(text=f"🔄  Updating {name}...", fg=C["accent"])

        def _w():
            try:
                ok, msg = update_game(aid)
            except Exception as e:
                ok, msg = False, str(e)
            self.root.after(0, lambda: self._done_update(ok, msg, aid, name))

        threading.Thread(target=_w, daemon=True).start()

    def _done_update(self, ok, msg, aid, name):
        self._busy = False
        if ok:
            self.stat_steam.configure(text=f"✅  {name} updated", fg=C["green"])
            self._load_games()
            self._toast("success", f"{name} Updated!", msg, app_id=aid)
        else:
            self.stat_steam.configure(text="❌  Update failed", fg=C["red"])
            self._toast("error", "Update Failed", msg, app_id=aid)

    # ─── remove ─────────────────────────────────────────
    def _do_remove(self, aid, card):
        name = self._name_cache.get(aid, f"AppID {aid}")

        dlg = tk.Toplevel(self.root)
        dlg.title("")
        dlg.geometry("420x190")
        dlg.resizable(False, False)
        dlg.configure(bg=C["card"])
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.overrideredirect(True)
        dlg.configure(highlightbackground=C["red"], highlightthickness=2)

        dlg.update_idletasks()
        cx = self.root.winfo_x() + self.root.winfo_width() // 2 - 210
        cy = self.root.winfo_y() + self.root.winfo_height() // 2 - 95
        dlg.geometry(f"+{cx}+{cy}")

        tk.Label(dlg, text="🗑️  Remove Game", font=(FONT, 15, "bold"),
                 bg=C["card"], fg=C["tx_b"]).pack(pady=(22, 8))
        tk.Label(dlg, text=f"Remove '{name}'?\nLua and manifest files will be deleted.",
                 font=(FONT, 9), bg=C["card"], fg=C["tx"],
                 justify="center").pack(pady=(0, 20))

        btn_row = tk.Frame(dlg, bg=C["card"])
        btn_row.pack()

        def _yes():
            dlg.destroy()
            ok, msg = remove_game(aid)
            if ok:
                card.destroy()
                self._img_cache.pop(aid, None)
                self._card_widgets = [
                    (c, g) for c, g in self._card_widgets if g["app_id"] != aid
                ]
                n = len(self._card_widgets)
                self.lib_count_lbl.configure(text=f"({n})")
                self.stat_total.configure(text=f"●  TOTAL GAMES: {n}")
                self._toast("info", f"{name} Removed", "Files deleted.", duration=3000)
                if n == 0:
                    self._load_games()
            else:
                self._toast("error", "Remove Failed", msg)

        SoftButton(btn_row, text="  Remove  ", command=_yes,
                   bg=C["red"], fg="#fff", hover=C["red_h"],
                   width=120, height=40, radius=10,
                   font_spec=(FONT, 10, "bold"),
                   parent_bg=C["card"]).pack(side="left", padx=(0, 12))

        SoftButton(btn_row, text="  Cancel  ", command=dlg.destroy,
                   bg=C["card_h"], fg=C["tx"], hover=C["border"],
                   width=120, height=40, radius=10,
                   font_spec=(FONT, 10),
                   parent_bg=C["card"]).pack(side="left")

    # ═══════════════════════════════════════════════════════════════
    # PROGRESS / BUSY
    # ═══════════════════════════════════════════════════════════════
    def _set_busy(self, busy, msg=""):
        self._busy = busy
        if busy:
            self._progress = 0.0
            self._prog_target = 0.05
            self.btn_add.set_state(True, "⏳  Processing...")
            self._show_status("⏳", msg, C["accent"])
            self.status_pct.configure(text="%0", fg=C["accent"])
            self.prog.pack(fill="x", pady=(10, 0))
            self.stat_steam.configure(text="⚡  PROCESSING...", fg=C["accent"])
            self._anim()
        else:
            self.btn_add.set_state(False, "⚡  Add Game")
            self.prog.pack_forget()
            self.status_pct.configure(text="")
            self._check_system()

    def _set_progress(self, target, msg=""):
        self._prog_target = min(target, 1.0)
        if msg:
            self.status_text.configure(text=msg)

    def _show_status(self, icon, text, color):
        self.status_frame.pack(fill="x", pady=(16, 0))
        self.status_icon.configure(text=icon, fg=color)
        self.status_text.configure(text=text, fg=color)

    def _anim(self):
        if not self._busy:
            return

        diff = self._prog_target - self._progress
        if diff > 0.001:
            self._progress += diff * 0.08
        else:
            self._progress = self._prog_target

        if self._prog_target < 0.90 and self._progress >= self._prog_target * 0.98:
            self._prog_target = min(self._prog_target + 0.002, 0.90)

        pct = int(self._progress * 100)
        self.status_pct.configure(text=f"%{pct}")
        self.stat_steam.configure(text=f"⚡  PROCESSING... {pct}%", fg=C["accent"])

        c = self.prog
        w = c.winfo_width() or 400
        c.delete("all")
        _rrect(c, 0, 0, w, 8, 4, fill=C["bg"], outline="")
        fw = int(w * self._progress)
        if fw > 8:
            _rrect(c, 0, 0, fw, 8, 4, fill=C["accent"], outline="")
            if fw > 14:
                _rrect(c, fw - 10, 0, fw, 8, 4, fill=C["accent_h"], outline="")

        self.root.after(30, self._anim)

    # ═══════════════════════════════════════════════════════════════
    # AUTO UPDATE
    # ═══════════════════════════════════════════════════════════════
    def _check_updates_bg(self):
        """Arka planda güncelleme kontrolü (uygulama açılışında)."""
        threading.Thread(target=self._worker_check_update, daemon=True).start()

    def _worker_check_update(self):
        info = check_for_update()
        if info:
            self.root.after(0, lambda: self._show_update_available(info))

    def _show_update_available(self, info):
        """Güncelleme mevcut — sidebar'da buton göster + toast bildirim."""
        self._update_info = info
        ver = info["version"]
        size_mb = info["size"] / (1024 * 1024)

        # Sidebar update butonu göster
        self.update_frame.pack(fill="x", padx=20, pady=(0, 8),
                               before=self.update_frame.master.winfo_children()[-1])
        self.update_label.configure(text=f"Update to v{ver}")

        # Buton tıklama
        for w in (self.update_btn, self.update_icon, self.update_label):
            w.bind("<Button-1>", lambda _: self._do_update_app())
            w.bind("<Enter>", lambda _: (
                self.update_btn.configure(bg=C["accent_sub"]),
                self.update_icon.configure(bg=C["accent_sub"]),
                self.update_label.configure(bg=C["accent_sub"]),
            ))
            w.bind("<Leave>", lambda _: (
                self.update_btn.configure(bg=C["accent_d"]),
                self.update_icon.configure(bg=C["accent_d"]),
                self.update_label.configure(bg=C["accent_d"]),
            ))

        # Version label güncelle
        self.ver_label.configure(text=f"v{CURRENT_VERSION}  ⬆ v{ver}", fg=C["yellow"])

        # Toast bildirimi
        self._toast(
            "info",
            f"Update Available — v{ver}",
            f"New version ready! ({size_mb:.1f} MB)\nClick the update button in the sidebar to install.",
            duration=8000,
        )

    def _do_update_app(self):
        """Güncellemeyi indir ve kur."""
        if not self._update_info or self._busy:
            return

        info = self._update_info
        ver = info["version"]
        url = info["download_url"]

        # UI güncelle — indirme başladı
        self.update_icon.configure(text="⏳")
        self.update_label.configure(text="Downloading...")
        for w in (self.update_btn, self.update_icon, self.update_label):
            w.configure(cursor="wait")
            w.unbind("<Button-1>")

        self.stat_steam.configure(text=f"⬇  Downloading v{ver}...", fg=C["accent"])

        # Settings sayfası progress
        self.btn_check_update.set_state(True, "⬇  Downloading...")
        self.btn_install_update.pack_forget()
        self.set_update_prog.pack(fill="x", pady=(0, 14))
        self.set_update_status.configure(
            text=f"⬇ Downloading v{ver}...", fg=C["accent"])

        def _progress(downloaded, total):
            pct = int(downloaded / total * 100) if total > 0 else 0
            dl_mb = downloaded / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            self.root.after(0, lambda: self._update_dl_progress(
                pct, dl_mb, tot_mb, ver))

        def _worker():
            filepath = download_update(url, on_progress=_progress)
            self.root.after(0, lambda: self._done_download(filepath, ver))

        threading.Thread(target=_worker, daemon=True).start()

    def _update_dl_progress(self, pct, dl_mb, tot_mb, ver):
        """İndirme progress'ini tüm UI'larda güncelle."""
        self.update_label.configure(text=f"Downloading... {pct}%")
        self.stat_steam.configure(
            text=f"⬇  {dl_mb:.1f}/{tot_mb:.1f} MB ({pct}%)", fg=C["accent"])
        self.set_update_status.configure(
            text=f"⬇ Downloading v{ver}... {pct}%  ({dl_mb:.1f}/{tot_mb:.1f} MB)",
            fg=C["accent"])
        # Settings progress bar
        c = self.set_update_prog
        w = c.winfo_width() or 400
        c.delete("all")
        _rrect(c, 0, 0, w, 8, 4, fill=C["bg"], outline="")
        fw = int(w * pct / 100)
        if fw > 8:
            _rrect(c, 0, 0, fw, 8, 4, fill=C["accent"], outline="")

    def _done_download(self, filepath, ver):
        """İndirme tamamlandı — installer'ı çalıştır."""
        if not filepath:
            self.update_icon.configure(text="❌")
            self.update_label.configure(text="Download failed")
            self.stat_steam.configure(text="❌  Update failed", fg=C["red"])
            self.set_update_status.configure(
                text="❌ Download failed. Please try again.", fg=C["red"])
            self.set_update_prog.pack_forget()
            self.btn_check_update.set_state(False, "🔍  Check for Updates")
            self._toast("error", "Update Failed",
                        "Could not download the update. Please try again later.",
                        duration=5000)
            self.root.after(3000, lambda: self._show_update_available(self._update_info))
            return

        # Başarılı — kurulum başlat
        self.update_icon.configure(text="✅")
        self.update_label.configure(text="Installing...")
        self.stat_steam.configure(text=f"🚀  Installing v{ver}...", fg=C["green"])
        self.set_update_status.configure(
            text=f"🚀 Installing v{ver}... App will restart.", fg=C["green"])
        self.set_update_prog.pack_forget()

        self._toast(
            "success",
            f"Installing v{ver}",
            "The installer will open now. The app will close automatically.",
            duration=4000,
        )

        # 2 saniye bekle (kullanıcı toast'u görsün) sonra installer'ı aç
        self.root.after(2000, lambda: apply_update(filepath))


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════
def main():
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    GameInSteamApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
