# 🎮 GameInSteam

**Steam Library Manager** — Add any game to your Steam library with one click.

![Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-blue?logo=windows)
![Version](https://img.shields.io/badge/Version-2.3-green)

---

## ✨ Features

- **One-Click Game Adding** — Enter a Steam App ID and the game is in your library
- **Auto File Placement** — All files are placed in the correct Steam directories automatically
- **Smart Download** — Fetches game files in the background, no manual work needed
- **Game Management** — Update or remove games from your library with ease
- **Live Cover Art** — See your games with Steam cover images
- **Progress Tracking** — Real-time progress bar while adding games
- **Auto Steam Restart** — Steam restarts automatically after adding a game
- **Modern Dark UI** — Premium soft-dark interface with smooth animations
- **Multi-Language Installer** — English, German, Turkish setup wizard

---

## 📥 Download & Install

### Option 1: Installer (Recommended)
1. Download **`GameInSteam_Setup_v2.3.exe`** from [Releases](../../releases/latest)
2. Run the installer → **Next → Next → Install → Finish**
3. The installer automatically:
   - ✅ Installs GameInSteam
   - ✅ Places `xinput1_4.dll` in your Steam directory
   - ✅ Creates desktop & start menu shortcuts
4. **Restart Steam** and you're ready!

### Option 2: Portable EXE
1. Download **`GameInSteam.exe`** from [Releases](../../releases/latest)
2. Place it anywhere and double-click to run
3. ⚠️ You must manually place `xinput1_4.dll` in your Steam directory

---

## ⚙️ Requirements

| Requirement | Details |
|---|---|
| **OS** | Windows 10 / 11 (64-bit) |
| **Steam** | Installed at default location |
| **Chrome** | Required for game file downloads |

> 💡 No Python or other dependencies needed — everything is bundled in the EXE!

---

## 🚀 How to Use

### Adding a Game
1. Open **GameInSteam**
2. Go to **"➕ Add Game"**
3. Enter the **Steam App ID** (e.g. `730` from `store.steampowered.com/app/730`)
4. Click **"⚡ Add Game"**
5. Wait for 100% — Steam restarts and the game appears!

### Managing Your Library
| Action | Description |
|---|---|
| 📚 **Library** | View all added games with cover art |
| 🔄 **Update** | Re-download latest files for a game |
| 🗑️ **Remove** | Delete a game's added files |

---

## 🖼️ Screenshots

| Library View | Add Game |
|---|---|
| Dark themed game grid with cover art | Simple App ID input with progress bar |

---

## 🌍 Languages

| Component | Supported Languages |
|---|---|
| **Installer** | 🇬🇧 English · 🇩🇪 Deutsch · 🇹🇷 Türkçe |
| **Website** | 🇬🇧 English · 🇩🇪 Deutsch · 🇹🇷 Türkçe |

---

## ❓ FAQ

**Q: Do I need Python installed?**
> No! Everything is bundled in the EXE file.

**Q: Why does Windows Defender warn me?**
> PyInstaller-built EXE files sometimes trigger false positives. Click "More info" → "Run anyway".

**Q: The game doesn't appear after adding?**
> Make sure Steam is fully restarted. Try closing and reopening Steam manually.

**Q: Which games are supported?**
> Any game available on the Steam Store with a valid App ID.

---

## ⚠️ Disclaimer

This software is provided for educational purposes only. Use at your own risk.
GameInSteam is not affiliated with Valve Corporation or Steam.

---

## 📄 License

This project is licensed under the [GNU General Public License v2.0](LICENSE).
