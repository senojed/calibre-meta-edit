# Jednoduchy postup

Tento skript doplni do Calibre metadata z Databaze knih.

## Desktop appka

Aktualni verze: `0.2.17`

Spusteni nove Qt appky:

```text
python -m pip install -r requirements.txt
CalibreMetaEditQt.bat
```

Stara Tkinter appka zustava jako zaloha, kdyby Qt zlobilo:

```text
CalibreMetaEdit.bat
```

EXE se zatim nedela.

V appce:

- pri startu se samo nacte `matches.csv`
- pri startu automaticky nacte nove knihy bez dotazu, spusti `Audit odkazu` a potom pripravi kandidatni obalky
- `Preferences` obsahuje knihovnu, vzhled, automaticke akce, `Rebuild CSV` a `Rollback`
- pravy panel ma zalozky `Aktualni data`, `Review` a `Log`
- kdyz appka pracuje, prepne se na `Log` a ovladani se docasne vypne
- statusbar ukazuje stav, jestli bezi Calibre, jestli je nactene `matches.csv`, a verzi
- `Nacist z Calibre` znovu nacte z Calibre jen vybrane knihy v tabulce, pusti audit odkazu a pripravi kandidatni obalky
- `Nacist nove knihy` - doplni do `matches.csv` jen nove knihy, pusti `Audit odkazu` a pripravi kandidatni obalky
- `Najit / overit odkaz` - kdyz mas vybrane radky, audituje jen je; bez vyberu audituje cele `matches.csv`
- `Najit / overit odkaz` zkusi nejdriv Databazi knih, potom Legii
- kdyz prvni hledani na Databazi knih neni dost jiste, zkusi jeste dotaz bez diakritiky a interpunkce
- knihy, ktere uz v Calibre obalku maji, se pri hledani obalek preskoci
- kdyz u jednoho vybraneho radku upravis pole `Odkaz`, `Audit odkazu` ho pred hledanim rovnou pouzije
- kdyz Legie nic nenajde pres nazev + autora, zkusi jeste hledat jen podle nazvu a pak kratky zacatek dlouheho nazvu
- kdyz Legie vyhledavani rovnou otevre detail povidky, appka ho pozna jako vysledek
- slaba shoda z Databaze knih se stejnym jednim slovem v nazvu zustane bez odkazu, pokud Legie nic nenajde
- `Rebuild CSV` dole - zalohuje stary `matches.csv` a vytvori ho znovu od nuly
- `Rollback` dole - obnovi Calibre databazi `metadata.db` z vybrane zalohy
- klik na hlavicku sloupce seradi tabulku
- `Filter knih` a `Filter autoru` jen zmensi zobrazeny seznam, `matches.csv` zustava cele
- male `X` u poli `Odkaz`, `Filter knih` a `Filter autoru` hned smaze cele pole
- v tabulce vyber jednu nebo vic knih
- horni `Approve`, `Review`, `Skip` zmeni status vsem vybranym kniham
- druhy horni radek `Odkaz` a `Pouzit odkaz` upravuje odkaz u vsech vybranych knih a oznaci ho jako `manual`
- `Aktualni data` ukazuje obalku, ktera uz je v Calibre
- `Aktualni data` ukazuje Calibre rok vydani, vydavatele, tagy a HTML nahled komentare
- `Review` ukazuje kandidatni obalky jen kdyz je nova obalka na vyber
- kdyz je kandidatnich obalek vic, vyber jednu kliknutim na maly nahled; bez vyberu nejde dat `Approve`
- `Ulozit CSV`
- `Zapsat do Calibre`
- `approve` radek s prazdnym odkazem vymaze komentar knihy v Calibre

Automaticky audit obalek udela:

1. vezme nove nebo vybrane radky podle akce
2. preskoci knihy, ktere uz v Calibre obalku maji
3. preskoci radky bez odkazu na Databazi knih nebo Legii
4. najde kandidatni obalky a ulozi je do `matches.csv`
5. kdyz najde jednu obalku, predvybere ji
6. kdyz najde vice obalek, da radek na `review`
7. nic nezapisuje do Calibre

`Zapsat do Calibre` udela:

1. ulozi `matches.csv`
2. pokusi se normalne zavrit Calibre
3. vytvori zalohu `metadata.db`
4. u `approve` radku knih z Databaze knih stahne prehled a zalozku `Vydani`
5. prepise komentar na odkaz, bold hodnoceni a text O knize
6. prepise `vydano`, `vydavatel` a `stitky`
7. do `vydano` posila datum jako `ROK-00-00`, aby Calibre ulozilo `ROK-01-01`
8. do stitku da nejdriv zanry z Databaze knih, potom spodni stitky knihy
9. rucni `manual` odkazy mimo podporovane zdroje, treba Goodreads, zapise jen jako odkaz do komentare
10. pokud ma radek vybranou kandidatni obalku, zapise ji spolu s metadaty
11. hotove `approve` radky zmeni na `skip`
12. po zapisu nacte nove knihy, spusti `Audit odkazu` a pripravi kandidatni obalky
13. znovu nacte `matches.csv` do tabulky

V potvrzeni zapisu je zaskrtavatko pro vynucene zavreni `/F`.
Je zapnute automaticky. Vypni ho, kdyz v Calibre mas neulozenou praci.

Kdyz pri zapisu neco selze, appka vypise `Failed zapisy` ve spodnim vystupu.
Kdyz nejde stahnout detail knihy z Databaze knih, kniha se nezapise a zustane `approve`.

`Najit / overit odkaz` udela:

1. ulozi aktualni `matches.csv`
2. zalohuje `matches.csv` do `backups\matches\`
3. projde vybrane radky, nebo cele `matches.csv`, kdyz nic nevyberes
4. u nejistych radku zkusi nejdriv Databazi knih
5. kdyz Databaze knih nenajde jistou shodu, hleda mozne povidky na Legii
6. nalezene povidky nastavi na `review`, zdroj `legie`, typ `povidka`
7. presne schvalene `approve` radky nemeni
8. schvalene slabe shody muze vratit na `review`, kdyz najde lepsi povidku na Legii
9. u stareho `already-linked` odkazu, ktery uz nejde potvrdit hledanim, smaze URL v `matches.csv` a da radek na `review`
10. rucne zadane odkazy `manual` nemaze ani znovu nehleda
11. nic nezapisuje do Calibre

`Nacist z Calibre` udela:

1. ulozi aktualni `matches.csv`
2. z Calibre databaze znovu nacte jen vybrane knihy
3. v `matches.csv` nahradi jen tyto vybrane radky
4. na vybrane radky spusti `Audit odkazu`
5. pripravi kandidatni obalky pro vybrane radky
6. nic nezapisuje do Calibre

Legie radky zapisuj az po rucnim prepnuti na `approve`.
Pri zapisu Legie se do Calibre ulozi komentar, tag `povidka` a identifikator `legie:ID`.
Rucne vlozeny odkaz `databazeknih.cz/povidky/...` se zapise jen jako odkaz do komentare, bez metadat.
Tlacitko `Povidka` oznaci vybrane radky jako typ `povidka` a da je na `review`.

`Rebuild CSV` udela:

1. zkopiruje stary `matches.csv` do `backups\matches\`
2. vytvori novy `matches.csv`
3. knihy, ktere uz maji v komentari odkaz na Databazi knih, znovu nehleda

`Rollback` udela:

1. zepta se na soubor zalohy, treba `backups\metadata-20260527-143012.db`
2. pokusi se zavrit Calibre
3. ulozi aktualni `metadata.db` jako nouzovou zalohu `metadata-before-restore-YYYYMMDD-HHMMSS.db`
4. obnovi vybranou zalohu do Calibre knihovny

## 1. Otevri PowerShell

Prejdi do slozky projektu:

```powershell
cd C:\Users\Honza\Nextcloud\Jan\PROJECTS\calibre-meta-edit
```

## 2. Vytvor nahled

```powershell
python calibre_meta_edit.py preview
```

Vznikne soubor:

```text
matches.csv
```

Kdyz uz `matches.csv` existuje, skript ho pouzije jako cache.

To znamena:

- stare radky necha byt
- rucni upravy ve `status` zachova
- zpracuje jen nove knihy, ktere v `matches.csv` jeste nejsou

Kdyz chces vse zahodit a vytvorit `matches.csv` znovu od nuly:

```powershell
python calibre_meta_edit.py preview --overwrite
```

## 3. Zkontroluj matches.csv

Otevri `matches.csv` v Excelu.

Dulezite sloupce:

- `status` - co se s knihou stane
- `chosen_url` - odkaz, ktery se zapise
- `reason` - proc skript rozhodl takhle

Hodnoty ve `status`:

- `approve` - zapise se
- `review` - zkontroluj rucne
- `skip` - preskoci se

Kdyz chces rucne schvalit radek, zmen `review` na `approve`.

## 4. Zavri Calibre

Pred zapisem zavri Calibre.

Kdyz Calibre bezi, zapis se vetsinou nepovede.

## 5. Zapis do Calibre

```powershell
python calibre_meta_edit.py apply
```

Skript zapise jen radky, kde je:

```text
status=approve
```

## 6. Kde je zaloha databaze

Pred zapisem se vytvori zaloha tady:

```text
C:\Users\Honza\Nextcloud\Jan\PROJECTS\calibre-meta-edit\backups\
```

Jmeno bude vypadat treba takhle:

```text
metadata-20260527-143012.db
```

To je zaloha Calibre databaze `metadata.db`.

## 7. Vysledek zapisu

Po zapisu vznikne soubor:

```text
apply-results\apply-results-YYYYMMDD-HHMMSS.csv
```

Hodnoty ve sloupci `status`:

- `updated` - zapsano
- `skipped` - preskoceno
- `failed` - chyba

## Test jedne knihy

Nahled jedne knihy:

```powershell
python calibre_meta_edit.py preview --book-id 309
```

Zapis jedne knihy:

```powershell
python calibre_meta_edit.py apply --book-id 309
```

## Test maleho vzorku

Nahled prvnich 5 knih:

```powershell
python calibre_meta_edit.py preview --limit 5
```
