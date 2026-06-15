# EPUB Import Design

## Cil

Pridat do Calibre Meta Edit prvni verzi importu knih. Verze `0.4.0` bude umet importovat jednu knihu ve formatu EPUB, pred zapisem ukazat nahled, povolit rucni upravy a zapsat knihu do Calibre az po potvrzeni uzivatelem.

Import musi fungovat bez AI. AI vrstva bude volitelna pomoc pro vyber kandidata, ne autorita pro zapis.

## Rozsah 0.4.0

Soucast prvni verze:

- import jednoho EPUB souboru
- vstup pres tlacitko `Import EPUB`
- samostatne modalni importni okno
- analyza EPUB metadat a zacatku obsahu
- analyza nazvu souboru a slozek jako slabsi signal
- online dohledani kandidatu
- kontrola duplicit v Calibre
- navrh serie a cisla dilu
- editovatelny nahled metadat
- vyber obalky
- backup `metadata.db` pred zapisem
- zapis pres `calibredb add` a nasledne `calibredb set_metadata`
- pridani nove knihy do `matches.db` jako `skip`
- refresh hlavni tabulky a vyber nove knihy

Mimo rozsah 0.4.0:

- hromadny import
- drag and drop
- presun puvodnich souboru po importu
- PDF, MOBI, AZW3, PDB
- OCR
- CLI import
- cloud AI provideri

Budouci rozsireni:

- davkovy import
- drag and drop jednoho nebo vice souboru
- volitelny presun puvodniho souboru do `imported`, `done`, nebo vlastni slozky
- dalsi formaty
- OpenAI API, Anthropic API, Claude Code CLI jako AI provideri

## Identifikace knihy

Import nejdriv nic nezapisuje. Nasbira signaly a vzajemne je porovna.

Signaly:

- EPUB metadata: title, creator, language, publisher, date
- EPUB obsah: titulni stranka, copyright/tiraz, zacatek knihy
- nazev souboru
- nazvy slozek
- online kandidati

Normalizace:

- porovnani s diakritikou i bez diakritiky
- podtrzitka jako mezery
- caste chyby kodovani v nazvu souboru
- autor ve tvaru `Prijmeni Jmeno`
- cisla serie v nazvu souboru nebo slozce
- odstraneni beznych technickych casti nazvu souboru

Skorovani:

- stejny nebo silne podobny nazev ve vice signalech zvysi jistotu
- stejny nebo silne podobny autor ve vice signalech zvysi jistotu
- online kandidat potvrzeny nazvem i autorem ma vysokou vahu
- shoda jen jednoho slova v nazvu ma velmi nizkou vahu
- nesedici autor znamena review nebo stop, ne automaticky vyber
- vice podobnych kandidatu znamena rucni vyber

Vysledek analyzy:

- doporuceny kandidat
- dalsi kandidati
- duvody rozhodnuti
- informace, zda je vysledek dostatecne jisty, nebo vyzaduje review

## Online zdroje

Volba zdroju podle jazyka/signalu:

- cesky kandidat: Databaze knih a Legie
- anglicky kandidat: Google Books a Open Library
- nejasny jazyk: vsechny zdroje

Uzivatel muze v importnim okne rucne vybrat jiny online kandidat. Po vyberu se prepocitaji metadata, komentar, obalky, serie a duplicity.

Scraping Databaze knih a Legie musi pouzivat stavajici opatrny styl:

- User-Agent
- rozumny timeout
- rate limit
- zadne agresivni paralelni dotazy v prvni verzi

## AI Vrstva

AI je volitelna.

Preferences:

- provider `Vypnuto`
- provider `Ollama`
- model
- test pripojeni
- limit textu z EPUB

Prvni implementace:

- `Vypnuto`
- `Ollama`

Budouci provideri jen v architekture:

- OpenAI API
- Anthropic API
- Claude Code CLI

Chovani AI:

- import bez AI musi fungovat normalne
- kdyz Ollama neni dostupna, import pokracuje bez AI a ukaze varovani
- AI dostane jen kratke signaly a seznam kandidatu, ne celou knihu
- AI vraci strukturovany navrh: kandidat, confidence, duvod, zda vyzaduje review
- AI nikdy nezapisuje do Calibre
- uzivatel vzdy potvrzuje finalni import

## Importni Okno

Okno bude samostatne modalni okno. Rozlozeni ma byt siroke, aby bylo minimum scrollovani.

Navrh rozlozeni:

- levy panel: soubor, signaly, kandidati, duplicity
- pravy panel: editovatelna metadata, komentar, obalka
- spodni lista: stav, `Importovat`, `Zrusit`
- scroll jen uvnitr dlouhych textu, ne cele okno

Sekce `Soubor`:

- cesta k EPUB
- metadata ze souboru
- signaly z obsahu
- signaly z nazvu souboru a slozek
- kratke vysvetleni, proc vznikl navrh

Sekce `Kandidati`:

- zdroj
- nazev
- autor
- skore
- duvod
- odkaz

Klik na kandidata:

- vyplni odkaz
- nacte metadata
- prepocita komentar
- nacte obalky
- prepocita serii
- znovu zkontroluje duplicity

Sekce `Metadata k zapisu`:

- nazev
- autor/autori jako jedno textove pole, vice autoru oddeleno `&`
- serie
- cislo serie
- rok vydani
- vydavatel
- tagy
- odkaz
- hodnoceni
- originalni nazev
- originalne vyslo
- originalni vydavatel
- komentar

Pravidla originalnich poli:

- u ceskeho prekladu bezne pole znamena ceske vydani a originalni pole znamena original
- u anglicke knihy s anglickym originalem se originalni pole zbytecne neduplikuji
- u cizojazycne knihy, ktera neni v puvodnim jazyce, se originalni pole pouziji jen pokud je doda online zdroj
- skript nema hadat puvodni jazyk bez spolehliveho zdroje

Sekce `Obalka`:

- obalka z EPUB jako kandidat
- online obalky jako kandidati
- jedna obalka se predvybere
- vice obalek vyzaduje rucni vyber, pokud se ma obalka zapsat
- zadna obalka nezablokuje import

Sekce `Duplicity`:

- mozne existujici knihy v Calibre
- ID
- nazev
- autor
- serie
- podobnost
- duvod shody

## Duplicity

Kontrola duplicit pouzije Calibre `metadata.db` read-only.

Pravidla:

- autor sam o sobe duplicita neni
- stejny nebo silne podobny nazev a stejny nebo silne podobny autor je silna duplicita
- podobny nazev a podobny autor je mozna duplicita
- stejny autor a jiny nazev se ignoruje
- stejny nazev a jiny autor je varovani/review

Chovani:

- silna duplicita blokuje import, dokud uzivatel nepotvrdi `importovat i tak`
- mozna duplicita ukaze varovani
- bez nazvu nebo autora se import nepovoli

## Serie

Zdroje serie:

- online zdroje
- EPUB metadata, pokud existuji
- nazev souboru a slozek jako slaby signal
- existujici serie v Calibre

Importni okno nabidne:

- bez serie
- pouzit existujici podobnou serii v Calibre
- zalozit novou serii

Cislo serie je editovatelne. Pokud neni jistota, serie se automaticky nevyplni bez kontroly.

## Zapis Do Calibre

Po kliknuti `Importovat`:

1. overit nazev a autora
2. pokud je silna duplicita, vyzadat extra potvrzeni
3. zavrit Calibre stejnym mechanismem jako dnes
4. udelat backup `metadata.db`
5. nacist existujici ID knih v Calibre
6. spustit `calibredb add <epub>`
7. znovu nacist ID knih
8. urcit nove `book_id` jako rozdil pred/po
9. pokud `book_id` nejde jednoznacne urcit, zastavit a ukazat chybu
10. spustit `calibredb set_metadata`
11. zapsat metadata, komentar, serii, tagy a obalku
12. pridat novy radek do `matches.db` jako `skip`
13. refreshnout hlavni tabulku
14. vybrat novou knihu
15. ukazat zalozku `Aktualni data`

Puvodni EPUB:

- nemenit
- nepresouvat
- Calibre si vytvori vlastni kopii

Chyby:

- chyba pred `calibredb add` nezmeni knihovnu
- chyba po `calibredb add` musi ukazat nove `book_id`, pokud je znamo
- automaticky rollback se v prvni verzi nedela
- uzivatel muze pouzit existujici backup/rollback mechanismus

## Backend Navrh

Backend ma byt testovatelny bez GUI.

Navrzene jednotky:

- `ImportSourceSignal`: jeden signal z EPUB/metadat/souboru/slozky
- `ImportCandidate`: online nebo lokalni kandidat
- `ImportAnalysis`: finalni analyza pro importni okno
- `ImportPreview`: editovatelna data pred zapisem
- `DuplicateCandidate`: nalezena mozna duplicita
- `AIResolver`: rozhrani pro volitelnou AI vrstvu
- `DisabledAIResolver`: default
- `OllamaAIResolver`: prvni realny provider

Hlavni funkce:

- `analyze_epub_for_import(path, library, settings)`
- `read_epub_metadata(path)`
- `extract_epub_start_text(path, limit)`
- `build_import_candidates(signals)`
- `score_import_candidates(signals, candidates)`
- `find_calibre_duplicates(library, preview)`
- `apply_import_preview(preview, library)`

## Testy

Backend testy:

- EPUB metadata parsing
- EPUB text extraction
- normalizace nazvu souboru
- rozbita diakritika v nazvu souboru
- autor `Prijmeni Jmeno`
- cross-check skorovani
- slaba shoda jen jednim slovem se nevybere
- duplicita: stejny nazev + stejny autor
- duplicita: stejny autor + jiny nazev se ignoruje
- serie match na existujici Calibre serii
- import preview bez nazvu/autora je neplatny
- AI vypnuta
- Ollama nedostupna nezastavi import

GUI testy/helper testy:

- import tlacitko existuje
- importni okno validuje nazev/autora
- vyber kandidata prepocita metadata
- silna duplicita vyzaduje extra potvrzeni
- po uspechu se novy radek prida jako `skip`

Manualni smoke test:

1. vybrat EPUB s dobrymi metadaty
2. vybrat EPUB s bordelem v nazvu souboru
3. vybrat EPUB, ktery uz v Calibre existuje
4. vybrat EPUB bez online shody a rucne vyplnit nazev/autora
5. overit backup `metadata.db`
6. overit, ze puvodni EPUB zustal na miste

## Bezpecnost Dat

- zadny zapis pred potvrzenim
- backup `metadata.db` pred kazdym importem
- puvodni EPUB se nemeni
- primy zapis do Calibre SQLite se nepouzije
- zapis do Calibre jen pres `calibredb`
- `matches.db` se aktualizuje az po uspesnem importu
