# Calibre Databaze Knih Linker

## Summary

- Vytvorit maly Python skript v `C:\Users\Honza\Nextcloud\Jan\PROJECTS\calibre-meta-edit`.
- Cil: ke kniham v Calibre knihovne z Databaze knih doplnit odkaz, hodnoceni, text O knize a vybrana metadata.
- Bezpecny rezim: nejdriv nahled do CSV, zapis az druhym prikazem.
- Pred kazdym zapisem se vytvori zaloha databaze `metadata.db`.
- Pouzit jen Python standard library; zadne externi balicky.
- Testy psat pres `unittest` ze standard library.

## Update 0.0.10 - metadata z detailu knihy

- `apply` pro kazdy `approve` radek stahne detail knihy z `https://www.databazeknih.cz/prehled-knihy/...`.
- Parser detailu bere:
  - `datePublished` ze schema.org JSON-LD -> Calibre `pubdate`, jen rok
  - `publisher` ze schema.org JSON-LD -> Calibre `publisher`
  - `genre` ze schema.org JSON-LD -> prvni cast Calibre `tags`
  - pravy box `Stitky knihy` -> prida za zanry do Calibre `tags`
  - viditelne hodnoceni z `.ratValue` -> komentar jako samostatny bold radek
  - sekci `O knize` z prehledu -> komentar pod hodnoceni
- Duplicitni tagy se zahodi podle normalizovaneho textu, poradi zustane: zanry, potom spodní stitky.
- Komentar se pri zapisu kompletne prepise. Novy format:
  - odkaz na Databazi knih
  - prazdny odstup
  - bold hodnoceni, napr. `89 %`
  - prazdny odstup
  - text `O knize`
- Kdyz detail nejde stahnout, kniha se nezapise, vysledek bude `failed` a radek zustane `approve`.

## Update 0.0.11 - oprava roku vydani

- Nektere stranky Databaze knih maji ve schema.org JSON-LD `datePublished` jako `0101-01-01`.
- Parser proto preferuje viditelny rok z hlavniho detailu knihy u vydavatele, napr. `1992, AF 167`.
- JSON-LD rok se pouzije jen jako fallback, pokud je v rozsahu `1000-2099`.

## Update 0.0.12 - nejstarsi dostupne vydani

- `apply` z prehledu knihy najde odkaz na `dalsi-vydani`.
- Pokud seznam vydani existuje, skript vezme nejstarsi dostupne vydani a jeho vydavatele.
- Komentar i `matches.csv` po uspesnem zapisu pouziji odkaz na vydani, ze ktereho se metadata opravdu zapsala.
- Kdyz seznam vydani nejde precist, zapis knihy skonci jako `failed`, aby se nezapsala nahodna novejsi edice.

## Update 0.0.13 - prisne pouziti zalozky Vydani

- Pokud prehled knihy obsahuje zalozku `Vydani`, `apply` musi vzit rok a vydavatele prave z teto zalozky.
- Kdyz zalozka `Vydani` existuje, ale parser z ni nenajde zadne vydani, kniha skonci jako `failed` a nic se nezapise.

## Update 0.0.14 - start bez dotazu a datum vydani

- Appka po startu automaticky nacte nove knihy bez dotazovaciho dialogu.
- Potvrzeni `Zapsat do Calibre` popisuje aktualni workflow vcetne zalohy, zalozky `Vydani` a nacteni novych knih.
- `pubdate` se do Calibre posila jako `ROK-01-01`, napr. `1991-01-01`, aby Calibre nevytvarelo datum `ROK-06-15`.

## Update 0.0.15 - pubdate prvni leden

- Calibre pri vstupu `ROK-01-01` realne ulozi `ROK-01-02`.
- Skript proto posila `ROK-00-00`; Calibre z toho ulozi `ROK-01-01`.

## Update 0.0.16 - navrh podpory Legie

- Pridan design dokument pro auditni podporu povidek z Legie.
- Legie ma byt druhy zdroj pro povidky a nejiste shody, ne automaticka nahrada Databaze knih.
- Prvni implementace ma davat Legie kandidaty do `review` a zapisovat je az po rucnim schvaleni.

## Update 0.0.17 - implementacni plan Legie

- Pridan implementacni plan pro CSV schema, Legie parser, audit, apply a app UI.
- Plan drzi konzervativni pravidlo: Legie kandidat vzdy zacina jako `review`.

## Update 0.0.24 - audit povidek pres Legii

- Pridan konzervativni Legie audit nad `matches.csv`.
- Legie kandidati jsou vzdy `review` a `approve` radky audit nemeni.
- Zapis Legie radku uklada komentar, tag `povidka` a identifikator `legie:ID`.

## Update 0.0.25 - rucni povidkove odkazy

- Rucne vlozeny Legie odkaz se pozna podle URL, i kdyz mel radek stary zdroj `databazeknih`.
- Rucne vlozene odkazy `databazeknih.cz/povidky/...` se zapisuji jako link-only komentar bez stahovani metadat.
- `Audit Legie` umi zvednout na `review` i stare `already-linked` radky, ale `approve` radky porad nemeni.

## Update 0.0.26 - automaticky Audit Legie

- Po startu appky a po `Nacist nove knihy` se nejdriv spusti preview a hned potom `Audit Legie`.
- Po uspesnem `Zapsat do Calibre` se znovu nactou nove knihy a hned potom se spusti `Audit Legie`.
- Tlacitko `Audit Legie` zustava jako rucni opakovani auditu.

## Update 0.0.27 - prisnejsi slabe shody

- Parser Databaze knih pouzije text odkazu jako nazev kandidata, kdyz HTML nema titulek v obrazku.
- Prazdny nazev kandidata ani jedno spolecne slovo uz nevytvori `partial-title`.
- Odkazy Legie typu `legie.info//povidka/...` se normalizuji na `legie.info/povidka/...`.
- `Audit Legie` muze vratit schvalenou slabou Databaze shodu na `review`, kdyz najde lepsi povidku na Legii.
- Presne schvalene radky `exact-title-author` audit porad nemeni.

## Update 0.0.28 - rozsah Audit Legie

- Automaticky audit po startu, po `Nacist nove knihy` a po `Zapsat do Calibre` audituje jen nove pridane radky.
- Rucni tlacitko `Audit Legie` audituje jen vybrane radky, pokud je neco vybrane.
- Kdyz v tabulce neni nic vybrane, rucni `Audit Legie` projede cele `matches.csv`.
- Backend `run_legie_audit` umi vybrat vice knih pres `book_ids`.

## Update 0.0.29 - Legie title-only fallback

- Legie audit nejdriv hleda podle `nazev + autor`.
- Kdyz nic nenajde, zkusi jeste hledat jen podle nazvu knihy/povidky.
- Fallback resi pripady, kdy Legie autora ve vyhledavani nenajde kvuli jinemu zapisu jmena.

## Update 0.0.30 - opravena Legie search URL

- Legie vyhledavani pouziva skutecny formular `index.php?search_text=...`.
- Parser Legie umi rozpoznat i situaci, kdy vyhledavani rovnou otevre detail povidky.
- Detail povidky se prevede na kandidata `https://www.legie.info/povidka/ID`.

## Key Changes

- Vychozi knihovna je `\\192.168.0.101\data\books`; skript z ni bude cist `metadata.db`.
- Pred implementaci otestovat, ze `calibredb --with-library "\\192.168.0.101\data\books"` umi knihovnu precist.
- SQLite pro `preview` se musi otevirat read-only pres URI `mode=ro`.
- Otestovana UNC URI varianta pro Windows/Python: `file:////192.168.0.101/data/books/metadata.db?mode=ro`.
- Varianta `file://192.168.0.101/data/books/metadata.db?mode=ro` v Python SQLite nefunguje, konci `invalid uri authority`.
- `calibredb` se najde pres `shutil.which("calibredb")`; kdyz neni v `PATH`, pouzije se fallback `C:\Program Files\Calibre2\calibredb.exe`.
- Pokud `calibredb` nejde najit, `apply` skonci bez zapisu.
- Pokud UNC cesta v `calibredb` selze, skript zustane u cteni SQLite pro preview a zapis pres `apply` skonci s instrukci pouzit lokalne namapovanou cestu.
- Content Server neni ve v1 podporovany pro `apply`, protoze plan vyzaduje lokalni zalohu `metadata.db` pred zapisem.
- Pro kazdou vybranou knihu:
  - kdyz komentar uz obsahuje `databazeknih.cz`, zapise do CSV `status=skip`, `reason=already-linked` a `chosen_url` nastavi na existujici odkaz
  - jinak vezme `title + authors`
  - query postavi pres `urllib.parse.quote_plus(title + " " + " ".join(authors))`
  - vyhleda na `https://www.databazeknih.cz/vyhledavani/knihy?q=...`
  - najde kandidaty typu `/prehled-knihy/...`
  - ulozi odkaz ve stylu vzoru jako `/knihy/...`
- Nahledovy soubor: `matches.csv`
  - sloupce: `book_id,title,authors,status,chosen_url,candidate_urls,confidence,reason`
  - `status=approve` jen u jistych shod
  - nejasne shody budou `review` nebo `skip`
  - uzivatel muze rucne zmenit `review` na `approve`, ale `apply` musi znovu validovat `chosen_url`
  - `candidate_urls` bude pipe-separated seznam prevedenych `/knihy/...` URL, maximalne 5 kandidatu; kdyz nejsou kandidati, bude prazdny
  - `reason` bude kratky kod, napr. `exact-title-author`, `title-only`, `multiple-title-matches`, `partial-title`, `no-candidates`, `parser-failed`, `http-error`, `robots-blocked`, `already-linked`
  - CSV bude `utf-8-sig`, aby ho Excel ve Windows otevrel s diakritikou
  - opakovany `preview` bez `--overwrite` pouzije existujici `matches.csv` jako cache a doplni jen nove `book_id`
  - existujici radky v `matches.csv` zustanou zachovane, vcetne rucnich uprav `status`
- Zapis komentaru:
  - jen radky `status=approve`
  - `apply` stahne detail Databaze knih a prepise komentar novym formatem
  - puvodni komentar se nezachovava
  - zapisuje se i kdyz aktualni komentar uz obsahuje `databazeknih.cz`
  - HTML format bude jako u `Lod osudu`:

```html
<div>
<p><a href="https://www.databazeknih.cz/knihy/zive-lode-lod-osudu-152421"><span style="color: #6cb4ee">https://www.databazeknih.cz/knihy/zive-lode-lod-osudu-152421</span></a></p></div>
```

## Matching Rules

- Normalizace pro porovnani:
  - mala pismena
  - bez diakritiky
  - odstraneni zavorek s cislem serie, napr. `(9)`
  - sjednoceni vice mezer
- `approve`:
  - normalizovany nazev kandidata se rovna normalizovanemu nazvu knihy
  - a alespon jeden autor z Calibre je nalezen v textu vysledku
  - a je nalezen prave jeden takovy kandidat
  - `confidence` bude `exact-title-author`
- `review`:
  - shoda nazvu bez autora
  - vice kandidatu se stejnym nazvem
  - castecna shoda nazvu
  - `confidence` bude `title-only`, `multiple-title-matches` nebo `partial-title`
- `skip`:
  - nenalezen zadny kandidat
  - parser nerozpoznal vysledky
  - HTTP chyba, timeout nebo blokace webu
  - `confidence` bude `none`

## Scraping Safety

- Skript bude posilat vlastni `User-Agent`, napr. `calibre-meta-edit/1.0`.
- HTML se bude parsovat pres `html.parser.HTMLParser`, ne pres regex.
- Parser bude cilit jen na vysledky vyhledavani s odkazy `/prehled-knihy/...`; pokud strukturu nerozezna, vrati `skip`.
- Mezi pozadavky bude pauza podle `--sleep`, vychozi `1.0` sekundy.
- Nacteni `robots.txt` se pocita jako HTTP pozadavek; prvni hledani musi respektovat stejnou pauzu.
- Pred prvnim hledanim skript precte a vyhodnoti `https://www.databazeknih.cz/robots.txt` pres `urllib.robotparser`.
- Pokud scraping vyhledavani nebude povoleny nebo `robots.txt` nepujde overit, preview skonci bez dotazu na knihy.
- Parser bude mit testovaci HTML fixture ulozenou v repozitari, aby testy nezavisely na siti.
- Kdyz se HTML Databaze knih zmeni, parser vrati `skip` s duvodem misto odhadu.

## Backup

- Pri `apply` skript nejdriv zkontroluje vedlejsi SQLite soubory.
- Pokud v knihovne existuje `metadata.db-wal`, `metadata.db-shm` nebo `metadata.db-journal`, skript skonci bez zapisu a vypise, ze Calibre nebo jina aplikace pravdepodobne drzi databazi otevrenou.
- Potom overi pristup pres `calibredb list --with-library ... --limit 1`.
- Potom nacte `matches.csv`, vyfiltruje radky k zapisu a znovu zvaliduje `status` + `chosen_url`.
- Pokud neni zadny radek k zapisu, skript nevytvori zalohu, nic nezapise a vypise souhrn `updated=0`.
- Az pred prvnim skutecnym zapisem zkopiruje:
  - z `<library>\metadata.db`, kde `<library>` je vychozi knihovna nebo hodnota `--library`
  - do `C:\Users\Honza\Nextcloud\Jan\PROJECTS\calibre-meta-edit\backups\metadata-YYYYMMDD-HHMMSS.db`
- Kdyz zaloha selze, zapis se vubec nespusti.
- Zaloha bude obycejna kopie SQLite DB pred zmenou.
- Slozka `backups` se pred kopirovanim vytvori pres `Path.mkdir(parents=True, exist_ok=True)`.
- Skript vypise presnou cestu zalohy.
- Obnova je rucni: zavrit Calibre, nahradit `<library>\metadata.db` souborem ze slozky `backups`.

## Interface

- Soubor `calibre_meta_edit.py` zacne kratkym komentarem, co skript dela a k cemu slouzi.
- `python calibre_meta_edit.py preview`
  - vytvori `matches.csv`, pokud jeste neexistuje
  - pokud `matches.csv` existuje, doplni jen knihy, ktere v nem jeste nejsou
  - nic nezapisuje do Calibre
- `python calibre_meta_edit.py preview --overwrite`
  - prepise existujici `matches.csv`
- `python calibre_meta_edit.py apply`
  - nejdriv overi stav SQLite souboru a pristup ke knihovne
  - nacte `matches.csv`
  - kdyz existuje aspon jeden validni radek k zapisu, vytvori zalohu databaze
  - zapise jen schvalene odkazy
  - vytvori vysledkovy soubor `apply-results-YYYYMMDD-HHMMSS.csv`
  - vysledkovy soubor bude mit sloupce `book_id,title,status,chosen_url,error`
- `python calibre_meta_edit.py apply --book-id 309`
  - zapise jen schvaleny radek pro danou knihu z `matches.csv`
  - pokud je radek validni k zapisu, vytvori zalohu databaze pred zapisem
  - porad vytvori vlastni vysledkovy soubor
- Volitelne parametry:
  - `--library "\\192.168.0.101\data\books"`
  - `--limit 20`
  - `--book-id 309`
  - `--sleep 1.0`
  - `--overwrite`

## Write Safety

- Zapis nepujde primo pres SQLite.
- Zapis pujde pres `calibredb set_metadata --field comments:...`.
- Pred zapisem skript provede read-only smoke test pres `calibredb list --with-library ... --limit 1`.
- Volani `calibredb` musi jit pres `subprocess.run([...])` bez shellu, aby HTML komentare s `<`, `>`, uvozovkami a diakritikou nerozbilo Windows shell quotovani.
- `apply` zapise jen radky, kde `status=approve` a `chosen_url` zacina presne `https://www.databazeknih.cz/knihy/`.
- Pred kazdym zapisem `apply` stahne aktualni detail knihy z Databaze knih.
- Kdyz stazeni detailu selze, radek oznaci jako `failed` a knihu nezapise.
- `--book-id` plati pro `preview` i `apply`; v `preview` filtruje knihy z databaze, v `apply` filtruje radky z `matches.csv`.
- Kdyz jsou zadane `--book-id` i `--limit`, `--book-id` ma prednost a `--limit` se ignoruje.
- Kazdy zapis knihy je samostatne volani `calibredb set_metadata`.
- `apply-results` status hodnoty budou `updated`, `skipped`, `failed`; pri uspechu bude `error` prazdny.
- Kdyz selze zapis jedne knihy, skript zapise chybu do `apply-results-YYYYMMDD-HHMMSS.csv`, pokracuje dalsi knihou a na konci vypise souhrn `updated/skipped/failed`.
- Kdyz chyba vypada jako globalni problem knihovny, napr. lock, nedostupna cesta nebo selhani smoke testu, skript ukonci zbytek batch bez dalsich zapisu.
- Kdyz je Calibre spustene a `calibredb` odmitne pristup kvuli locku, skript skonci s jasnou hlaskou: zavrit Calibre GUI/server zapisujici do knihovny a spustit `apply` znovu.
- Komentar se prepisuje zamerne. Zaloha `metadata.db` pred zapisem je povinna.

## Test Plan

- Unit test normalizace nazvu/autora: diakritika, zavorky typu `(9)`, mezery.
- Unit test prevodu URL: `/prehled-knihy/foo-123` -> `/knihy/foo-123`.
- Unit test URL query:
  - pouziva `urllib.parse.quote_plus`
  - zachova ceskou diakritiku pres spravne URL encoding
  - pro vice autoru pouzije vsechny autory spojene mezerou
- Unit test pravidel matchingu:
  - presny nazev + autor => `approve`
  - presny nazev bez autora => `review`
  - vice kandidatu => `review`
  - parser selze => `skip`
- Unit test parseru proti ulozene HTML fixture bez site.
- Unit test UNC read-only URI builderu:
  - UNC cesta se prevede na `file:////server/share/path/metadata.db?mode=ro`
- Unit test detailu knihy:
  - parser vytahne rok, vydavatele, zanry, spodní stitky, hodnoceni a O knize
  - komentare se skladaji jako odkaz + bold hodnoceni + O knize
  - `apply` posila do `calibredb` pole `comments`, `pubdate`, `publisher`, `tags`
  - pri chybe stazeni detailu se nezavola `calibredb`
- Unit test nalezeni `calibredb`:
  - preferuje `PATH`
  - pouzije fallback `C:\Program Files\Calibre2\calibredb.exe`
  - bez nalezeneho `calibredb` apply skonci bez zapisu
- Unit test CSV:
  - soubor se pise jako `utf-8-sig`
  - existujici CSV se bez `--overwrite` pouzije jako cache pro inkrementalni preview
  - inkrementalni preview preskoci knihy, jejichz `book_id` uz v `matches.csv` existuje
  - `matches.csv` pouziva kratke `reason` kody
  - `candidate_urls` obsahuje maximalne 5 URL oddelenych znakem `|`
  - kniha s existujicim odkazem ma `status=skip`, `reason=already-linked` a `chosen_url` s existujicim odkazem
  - `apply-results-*.csv` ma sloupce `book_id,title,status,chosen_url,error`
  - `apply-results` pouziva status hodnoty `updated`, `skipped`, `failed`
  - `apply` odmitne `approve` radek s URL mimo `https://www.databazeknih.cz/knihy/`
  - `apply --book-id 309` zpracuje jen radek s `book_id=309`
  - pri `--book-id` a `--limit` ma prednost `--book-id`
- Unit test apply flow:
  - per-book chyba se zapise do timestampovaneho `apply-results-*.csv` a dalsi kniha pokracuje
  - globalni chyba knihovny zastavi zbytek batch
- Unit test zalohy:
  - vytvori cilovy backup soubor
  - vytvori slozku `backups`, pokud neexistuje
  - kdyz neni zadny radek k zapisu, zaloha se nevytvori
  - pri selhani zalohy se zapis nespusti
- Rucni smoke test:
  - `calibredb list --with-library "\\192.168.0.101\data\books" --limit 1` musi projit pred zapisem
  - `preview --book-id 309` musi vypsat `Lod osudu` jako `status=skip`, `reason=already-linked`
  - `preview --limit 5` vytvori CSV bez zapisu
  - `apply` na jedne schvalene testovaci knize nejdriv vytvori backup, pak zapise odkaz nahoru

## Update 0.0.32 - Audit odkazu

- Tlacitko se jmenuje `Audit odkazu`, protoze uz nehleda jen Legii.
- U nejistych nebo prazdnych radku zkusi nejdriv Databazi knih.
- Kdyz Databaze knih najde `/povidky/...`, radek dostane `source=databazeknih` a `work_type=povidka`.
- Kdyz Databaze knih nenajde jistou shodu, audit pokracuje hledanim na Legii.
- To resi stare radky jako `Samuela`, ktere vznikly pred podporou DK povidek.

## Update 0.0.33 - Legie autor v obracenem poradi

- Legie nekdy pise autora jako `Prijmeni, Jmeno`.
- Porovnani autora proto pouziva slova bez ohledu na poradi.
- `Samuela` se diky tomu najde jako Legie povidka `393`.
- Backend hlaska se sjednotila na `Audit odkazu`.

## Update 0.0.34 - vydani s ikonou formatu

- Databaze knih u nekterych vydani vklada ikonu formatu jako neuzavrene `<img>`.
- Parser vydani uz bere HTML void tagy jako bez vnoreni.
- Odkaz vydani bere i z bezneho `/prehled-knihy/...` odkazu bez `class=bigger`.
- `Abaddonova brana` se diky tomu parsuje jako `2014`, `Triton`.

## Update 0.0.35 - Audit odkazu pro smazany odkaz

- Kdyz je vybran jeden radek, `Audit odkazu` pred hledanim pouzije aktualni text z pole `Odkaz`.
- Rucni smazani odkazu proto neni potreba potvrzovat tlacitkem `Pouzit odkaz`.
- Matching umi opatrne vzit jednoslovny nazev jako prefix s presnym autorem.
- `Sapiens` se diky tomu najde jako `Sapiens: Od zvirete k bozskemu jedinci` a zustane na `review`.

## Update 0.0.36 - prazdny approve maze komentar

- `approve` radek s prazdnym odkazem je zapisovatelny.
- Pri zapisu posle do Calibre `comments:` a tim vymaze komentar knihy.
- Slouzi pro opravu spatne zapsanych starych odkazu.

## Update 0.0.37 - update vybranych radku a kratsi Legie dotaz

- Legie pri dlouhem nazvu zkusi po plnem dotazu jeste kratky zacatek nazvu.
- To resi povidky, ktere Legie nenajde na presny dlouhy nazev, napr. `A opice si myslely, ze je to vsechno jen legrace`.
- `preview` umi pres interni `book_ids` znovu nacist a nahradit existujici radky v `matches.csv`.
- Desktop appka ma dole tlacitko `Update vybrane`.
- `Update vybrane` znovu nacte z Calibre jen vybrane knihy, nahradi jen jejich radky v `matches.csv` a potom na ne spusti `Audit odkazu`.

## Update 0.0.38 - filtry a hromadny odkaz

- Desktop appka ma pole `Filter knih` a `Filter autoru`.
- Filtry meni jen zobrazeni tabulky, neobsah `matches.csv`.
- `Pouzit odkaz` umi pouzit aktualni pole `Odkaz` pro vice vybranych knih najednou.
- Tlacitka `Povidka` a `Update vybrane` jsou modra.

## Update 0.0.39 - mazani poli a mezery tlacitek

- Pole `Odkaz`, `Filter knih` a `Filter autoru` maji male tlacitko `X` pro okamzite smazani.
- Mezera mezi `Skip` a `Povidka` je stejna jako mezera pred `Approve`.
- Mezera mezi `Update vybrane` a `Rebuild CSV` je stejna jako mezera pred `Update vybrane`.

## Update 0.0.40 - Audit odkazu cisti nepotvrzene stare odkazy

- `Audit odkazu` u radku `reason=already-linked` zkusi odkaz znovu overit pres hledani podle aktualniho nazvu a autora.
- Kdyz najde dobrou nahradu, radek aktualizuje.
- Kdyz zadnou dobrou nahradu nenajde a nejde o HTTP chybu, smaze `chosen_url` v `matches.csv`, nastavi `status=review` a `reason=stale-already-linked`.
- Audit porad nic nezapisuje do Calibre; smazani komentare vyzaduje rucni `approve` a potom `Zapsat do Calibre`.

## Update 0.0.41 - manual odkazy audit nemaze

- Kdyz uzivatel zmeni odkaz pres pole `Odkaz` a `Pouzit odkaz`, radek dostane `confidence=manual` a `reason=manual`.
- `Audit odkazu` radky `manual` znovu nehleda a nesmaze jim `chosen_url`.
- To chrani rucne vlozene odkazy, vcetne pripadnych Goodreads URL.

## Update 0.0.42 - manual externi odkazy se zapisuji jako link

- `approve` radek `reason=manual` s libovolnym `http(s)` odkazem je zapisovatelny.
- Externi rucni odkazy mimo Databazi knih a Legii, napr. Goodreads, se zapisi jen jako HTML odkaz do komentare.
- Rucni Databaze knih `prehled-knihy` odkaz porad pouzije obohaceny zapis metadat.

## Update 0.0.43 - vydani bez vydavatele

- Parser vydani z Databaze knih uz bere i vydani, kde web ukazuje jen rok a nema vydavatele.
- To opravuje zapis knih jako `Kat`, kde existuje rok `2004`, ale vydavatel na strance vydani chybi.
- Vydavatel se v takovem pripade neprepise, rok se zapise.

## Update 0.1.0 - Qt desktop appka

- Pridana nova PySide6/Qt appka `calibre_meta_qt.py`.
- Spusteni bez EXE: `python calibre_meta_qt.py`.
- Stara Tkinter appka zustava jako fallback.
- Qt UI ma horni toolbar, filtry v liste, sortable tabulku, pravy detail panel a statusbar.
- Knihovna, `Rebuild CSV` a `Rollback` jsou v `Preferences`.
- Statusbar ukazuje stav, jestli bezi Calibre, stav `matches.csv` a verzi.

## Update 0.1.1 - Qt BAT launcher

- Pridan `CalibreMetaEditQt.bat`.
- Spousti novou Qt appku pres `pythonw.exe`, kdyz je dostupny.
- Kdyz `pythonw.exe` neni dostupny, zkusi `python.exe`.

## Update 0.1.2 - Qt UI polish

- Pridana ikona okna Qt appky.
- Tabulka ma citelny text i pri systemovem dark vzhledu.
- Tabulka pouziva multi vyber bez nutnosti drzet Ctrl.
- Horni status tlacitka `Approve`, `Review`, `Skip`, `Povidka` odstranena; zustavaji v detailu.
- `Ulozit CSV` je hned vedle `Nacist CSV`.
- `Nacist nove knihy` odstraneno z hlavni listy.
- Status, zdroj a typ filtry jsou checkboxy a jde vybrat vice hodnot.
- `Preferences` ma volbu vzhledu `system`, `light`, `dark`.

## Update 0.1.3 - Qt table behavior

- Vyber radku v Qt tabulce je jako ve Windows: klik vybere jeden, Ctrl/Shift vybere vice.
- Prave kliknuti na hlavicky sloupcu ukaze menu pro zapnuti/vypnuti sloupcu.
- Sloupce `ID`, `Kniha`, `Autor` nejdou vypnout.
- Filtr `Typ` ma volbu `bez typu`, takze jde zobrazit radky bez hodnoty.
- Stav Calibre je vpravo ve statusbaru jako zeleny/cerveny puntik s textem.
- Radky tabulky jsou kompaktnejsi.

## Update 0.1.4 - Qt detail and toolbar polish

- Stav Calibre se kontroluje prubezne timerem.
- Filtry jsou v hlavni liste mezi `Update vybrane` a `Preferences`.
- U vyberu vice radku detail ukazuje pocet vybranych polozek.
- Pokud ma vic vybranych radku ruzne odkazy, pole ukaze `Ruzne adresy` a link tlacitka se vypnou.
- Do detailu pridan rychly `Nahled komentare` nad logem.
- Nebarevna tlacitka jsou seda a tlacitka maji standardni Qt ikony.
- Z filtru odstraneny popisky `Status`, `Zdroj`, `Typ`.

## Update 0.1.5 - Qt icons and link clearing

- Toolbar a detail pouzivaji `QToolButton` s ikonou a malym textem pod ikonou.
- `Preferences`, `Audit odkazu`, `Update vybrane` a `Otevrit odkaz` maji vlastni SVG ikony.
- `Nahled komentare` odstraneny z detailu.
- Kdyz vice vybranych radku ma ruzne odkazy, lze text `Ruzne adresy` smazat a pouzit prazdny odkaz pro vsechny vybrane.

## Update 0.1.6 - Qt icon-only toolbar

- Hlavni lista ma jen ikony bez textu; text zustava v tooltipu po najeti mysi.
- Detail vybrane polozky ma status/link tlacitka bez ikon.
- Vybrane radky v tabulce zustavaji modre i kdyz tabulka ztrati focus.

## Assumptions

- Knihovna je `\\192.168.0.101\data\books`.
- Stare komentare se pri zapisu prepisuji novym formatem z Databaze knih.
- Chces stejny styl odkazu jako vzorova `Lod osudu`.
- Nejasne shody se nebudou zapisovat automaticky.
- Pred kazdym zapisem chces lokalni zalohu `metadata.db`.
