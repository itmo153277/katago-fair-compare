# -*- mode: python ; coding: utf-8 -*-

import platform
import importlib
import os


SYSTEM = platform.system()
IS_WINDOWS = SYSTEM == "Windows"
IS_MAC = SYSTEM == "Darwin"
IS_LINUX = SYSTEM == "Linux"

if not IS_WINDOWS and not IS_MAC and not IS_LINUX:
    raise RuntimeError(f"Unknown platform: {SYSTEM}")


def get_lib_file(pkg_name: str) -> str:
    pkg_imp = importlib.import_module(pkg_name)
    return os.path.abspath(os.path.realpath(pkg_imp.__file__))


def get_lib_path(pkg_name: str) -> str:
    return os.path.dirname(get_lib_file(pkg_name))


WX_PATH = get_lib_path("wx")

for lang in ["ru", "ja"]:
    target_dir = os.path.join(workpath, "locale", lang, "LC_MESSAGES")
    os.makedirs(target_dir, exist_ok=True)
    os.system(f"msgfmt -o {target_dir}/KatagoFairCompare.mo "
              f"locale/{lang}/LC_MESSAGES/KatagoFairCompare.po")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("resources", "resources"),
        (f"{workpath}/locale", "locale"),
        (f"{WX_PATH}/locale/ru", "wx/locale/ru"),
        (f"{WX_PATH}/locale/ja", "wx/locale/ja"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["wx.adv", "wx.html", "wx.msw"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if IS_WINDOWS or IS_MAC:
    icon_resource = os.path.join("resources", "icon.png")
    datas = [x for x in a.datas
             if x[0] != icon_resource]
else:
    datas = a.datas

binaries = []
if IS_LINUX or IS_MAC:
    for bin in a.binaries:
        if bin[0].startswith("libpython"):
            pass
        elif bin[0].startswith("python"):
            for mod in ["struct",
                        "binascii",
                        "posixsubprocess",
                        "select",
                        "math",
                        "zlib"]:
                if mod in bin[0]:
                    break
            else:
                continue
        elif bin[0].startswith("lib"):
            continue
        binaries.append(bin)
elif IS_WINDOWS:
    for bin in a.binaries:
        if bin[0].lower().startswith("python"):
            pass
        elif bin[0].startswith("wx"):
            pass
        else:
            continue
        binaries.append(bin)

if IS_WINDOWS:
    icon = "windows/icon.ico"
elif IS_MAC:
    icon = "macos/AppIcon.icns"
else:
    icon = "resources/icon.png"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="katago-fair-compare",
    debug=False,
    bootloader_ignore_signals=False,
    strip=IS_LINUX,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[icon],
    manifest="windows/manifest.xml" if IS_WINDOWS else None,
)
coll = COLLECT(
    exe,
    binaries,
    datas,
    strip=IS_LINUX,
    upx=False,
    upx_exclude=[],
    name="katago-fair-compare",
)
if IS_MAC:
    app = BUNDLE(
        coll,
        name="KataGo Fair Compare.app",
        icon=icon,
        bundle_identifier="ru.viktprog.katago-fair-compare",
        version="0.1.0",
        info_plist={
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": True,
            "CFBundleName": "KataGo Fair Compare",
            "CFBundleDisplayName": "KataGo Fair Compare",
        }
    )
