# PyInstaller spec: onedir Windows build of the Qt app.
# Build: pyinstaller calibre-meta-edit.spec  -> dist/CalibreMetaEdit/
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ["calibre_meta_qt.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("assets/icons/*", "assets/icons"),
        ("icons/*", "icons"),
        ("app_icon.svg", "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CalibreMetaEdit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=None,  # .svg neni .ico; realny .ico se doplni pozdeji
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CalibreMetaEdit",
)
