import os
import subprocess
import sys

def build():
    print("Building GameInSteam Standalone EXE...")
    
    # PyInstaller parametreleri
    params = [
        'pyinstaller',
        '--noconfirm',
        '--onefile',
        '--windowed', # Konsol penceresini gizle
        '--name', 'GameInSteam',
        '--add-data', 'VERSION.txt;.', # Versiyon dosyasını ekle
        # steam kütüphanesi gevent kullandığı için bazen ek parametre gerekebilir
        # ancak genellikle PyInstaller otomatik çözer.
        'main.py'
    ]
    
    try:
        subprocess.run(params, check=True)
        print("\nSUCCESS: GameInSteam.exe created in 'dist' folder!")
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: Build failed with exit code {e.returncode}")
        sys.exit(1)

if __name__ == "__main__":
    build()
