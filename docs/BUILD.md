# Build exe (Windows)

Předpoklady: Python 3, `pip install pyinstaller pyside6`.

Postavit onedir build:

```powershell
pyinstaller calibre-meta-edit.spec
```

Výsledek: `dist/CalibreMetaEdit/` (složka s `CalibreMetaEdit.exe`).

Zabalit:

```powershell
Compress-Archive -Path dist/CalibreMetaEdit/* -DestinationPath CalibreMetaEdit-0.4.11-win64.zip
```

Nahrát na GitHub Releases jako draft (koncept, nic není veřejné, dokud release na
GitHubu ručně nepublikuješ):

```powershell
gh release create v0.4.11 CalibreMetaEdit-0.4.11-win64.zip --draft --title "Calibre Meta Edit 0.4.11" --notes "Portable Windows build. Viz docs/INSTALL.md."
```

## Poznámky

- `calibredb` (Calibre) se do exe nebalí; cílový počítač ho musí mít nainstalovaný.
- Cloud API klíč se nebalí; uživatel si dá `.env` vedle exe (viz docs/INSTALL.md).
- Zapisovatelná data (settings.json, backups/, matches, .env) appka drží **vedle
  exe** (frozen-path `app_data_dir`), ne uvnitř balíku.
- Bez code signingu → Windows SmartScreen ukáže varování; popsáno v docs/INSTALL.md.
