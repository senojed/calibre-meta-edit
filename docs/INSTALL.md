# Instalace (Windows)

1. Nainstaluj **Calibre**: https://calibre-ebook.com/download  (appka volá `calibredb`).
2. AI (jedno z):
   - **Ollama** (lokální, doporučeno): https://ollama.com/download , pak v příkazovém
     řádku `ollama pull llama3.1:8b`.
   - **Cloud**: vytvoř soubor `.env` vedle `CalibreMetaEdit.exe` s řádkem
     `ANTHROPIC_API_KEY=...` nebo `OPENAI_API_KEY=...`.
3. Rozbal `CalibreMetaEdit-*.zip` (ideálně do Dokumentů, ne do Program Files).
4. Spusť `CalibreMetaEdit.exe`. Když Windows ukáže modrou ceduli SmartScreen:
   **Další informace → Přesto spustit** (appka není podepsaná).
5. Po startu appka sama zkontroluje, co chybí, a napoví.
