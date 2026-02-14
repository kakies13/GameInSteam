import io
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
        update_game,
    )
except ImportError:
    # Eğer dosya ismi farklıysa burayı düzeltmen gerekebilir
    print("Hata: steam_handler.py bulunamadı veya fonksiyonlar eksik!")

# Görsel boyutu (px)
IMG_W, IMG_H = 136, 64

# Steam CDN
HEADER_URL = "https://cdn.akamai.steamstatic.com/steam/apps/{}/header.jpg"


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
        self.root.title("GameInSteam v2.1")
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
        
        self._build_ui()
        self._check_system()
        self._create_placeholder()

    def _create_placeholder(self):
        """Oyun görseli yüklenene kadar gösterilecek gri placeholder."""
        img = Image.new("RGB", (IMG_W, IMG_H), color=(42, 71, 94))
        self._placeholder = ImageTk.PhotoImage(img)

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

        tk.Frame(self.root, bg=C["accent"], height=2).pack(fill="x")

        # ─── TAB İÇERİK ALANI ───
        self.body = tk.Frame(self.root, bg=C["bg_dark"])
        self.body.pack(fill="both", expand=True)

        self._build_add_page()
        self._build_lib_page()

        # ─── FOOTER ───
        ft = tk.Frame(self.root, bg=C["bg_main"], height=28)
        ft.pack(fill="x", side="bottom")
        ft.pack_propagate(False)
        tk.Label(ft, text="v2.1", font=("Segoe UI", 7),
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

        tk.Label(inner, text="💡 Steam mağaza URL'sindeki sayıyı girin (örn: 730)",
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

    # ─────────────────────────────────────────────────────────
    # LOJİK & EVENTLER
    # ─────────────────────────────────────────────────────────
    def _tab(self, t):
        if t == "add":
            self.tab_add.configure(bg=C["tab_on"], fg=C["accent"])
            self.tab_lib.configure(bg=C["tab_off"], fg=C["text_dim"])
            self.pg_lib.pack_forget()
            self.pg_add.pack(in_=self.body, fill="both", expand=True)
        else:
            self.tab_add.configure(bg=C["tab_off"], fg=C["text_dim"])
            self.tab_lib.configure(bg=C["tab_on"], fg=C["accent"])
            self.pg_add.pack_forget()
            self.pg_lib.pack(in_=self.body, fill="both", expand=True)
            self._load_games()

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
        app_id = self.inp_id.get().strip()
        name = self.inp_name.get().strip()
        if not app_id or not app_id.isdigit():
            messagebox.showerror("Hata", "Geçerli bir App ID girin.")
            return
        if not name: name = f"Game_{app_id}"

        self._set_busy(True, "Oyun ekleniyor...")
        threading.Thread(target=self._worker_add, args=(app_id, name), daemon=True).start()

    def _worker_add(self, app_id, name):
        try:
            ok, msg = add_shortcut_from_manifest(app_id, name)
        except Exception as e:
            ok, msg = False, str(e)
        self.root.after(0, lambda: self._done_add(ok, msg))

    def _done_add(self, ok, msg):
        self._set_busy(False)
        self._check_system()
        if ok:
            self._show_status("✅", "Başarıyla eklendi!", C["green"])
            messagebox.showinfo("Başarılı", msg)
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
        self.root.after(0, lambda: [self._set_busy(False), self._load_games(), messagebox.showinfo("Bilgi", msg)])

    def _do_remove(self, aid, card):
        if messagebox.askyesno("Onay", "Bu oyunu kaldırmak istediğine emin misin?"):
            ok, msg = remove_game(aid)
            if ok: card.destroy()
            else: messagebox.showerror("Hata", msg)

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