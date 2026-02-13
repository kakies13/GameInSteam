# 🎮 GameInSteam

**Steam Library Manager** — Add any game to your Steam library with one click.

![Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-blue?logo=windows)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow?logo=python)
![Version](https://img.shields.io/badge/Version-2.3-green)
![License](https://img.shields.io/badge/License-GPL--2.0-red)

---

## 📥 Installation

### Option 1: Installer (Recommended)
1. Download **`GameInSteam_Setup_v2.3.exe`** from [Releases](../../releases)
2. Run the installer
3. Click **Next → Next → Install → Finish**
4. The installer will automatically:
   - Install GameInSteam to Program Files
   - Place `xinput1_4.dll` in your Steam directory
   - Create desktop & start menu shortcuts
5. **Restart Steam** and launch GameInSteam

### Option 2: Portable EXE
1. Download **`GameInSteam.exe`** from [Releases](../../releases)
2. Place it anywhere on your computer
3. Double-click to run — no installation needed
4. ⚠️ You must manually place `xinput1_4.dll` in your Steam directory

---

## ⚙️ Requirements

| Requirement | Details |
|---|---|
| **OS** | Windows 10 / 11 (64-bit) |
| **Steam** | Installed at default location |
| **Chrome** | Required for game file downloads |
| **xinput1_4.dll** | Auto-installed by Setup, or manual placement |

---

## 🚀 How to Use

### Adding a Game
1. Open GameInSteam
2. Navigate to **"➕ Add Game"**
3. Enter the **Steam App ID** (found in the Steam store URL, e.g. `store.steampowered.com/app/730`)
4. Click **"⚡ Add Game"**
5. Wait for the progress bar to reach 100%
6. Steam restarts automatically — the game appears in your library

### Managing Your Library
- **📚 Library** — View all added games with cover art
- **🔄 Update** — Re-download latest files for a game
- **🗑️ Remove** — Delete a game's added files

---

## 🏗️ Building from Source

### Prerequisites
```
pip install -r requirements.txt
```

### Build EXE
Double-click **`build.bat`** — the EXE and installer are created automatically.

Or manually:
```bash
pyinstaller --noconfirm --onefile --windowed --name "GameInSteam" ^
    --add-data "steam_handler.py;." --add-data "ui.py;." ^
    --hidden-import=requests --hidden-import=PIL --hidden-import=PIL.Image ^
    --hidden-import=PIL.ImageTk --hidden-import=selenium ^
    --hidden-import=webdriver_manager main.py
```

### Build Installer
1. Install [Inno Setup 6](https://jrsoftware.org/isdl.php)
2. Build the EXE first with `build.bat`
3. The installer is automatically compiled if Inno Setup is detected
4. Output: `Output/GameInSteam_Setup_v2.3.exe`

---

## 🔧 How It Works

```
App ID → Fetch Game Files → Place in Steam Directories → Restart Steam → Done!
```

1. **Enter** a Steam App ID
2. **Download** — Game files are fetched automatically in the background
3. **Place** — Lua configs go to `Steam/config/stplug-in/`, manifests to `Steam/config/depotcache/`
4. **Restart** — Steam restarts and the game appears in your library

---

## 📁 Project Structure

```
GameInSteam/
├── main.py              # Entry point
├── ui.py                # Premium dark UI (Tkinter)
├── steam_handler.py     # Steam integration & file management
├── build.bat            # Automated build script
├── installer.iss        # Inno Setup installer script
├── xinput1_4.dll        # Proxy DLL for Steam
├── requirements.txt     # Python dependencies
├── website/             # Landing page (EN/DE/TR)
│   └── index.html
├── LICENSE
└── README.md
```

---

## 🌍 Languages

| Component | Languages |
|---|---|
| **Application** | English UI |
| **Installer** | 🇬🇧 English, 🇩🇪 Deutsch, 🇹🇷 Türkçe |
| **Website** | 🇬🇧 English, 🇩🇪 Deutsch, 🇹🇷 Türkçe |

---

## ⚠️ Disclaimer

This software is provided for educational purposes only. Use at your own risk.
GameInSteam is not affiliated with Valve Corporation or Steam.

---

## 📄 License

This project is licensed under the [GNU General Public License v2.0](LICENSE).
