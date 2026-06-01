# Jednoduchy postup

Tento skript doplni do Calibre metadata z Databaze knih.

## Desktop appka

Aktualni verze: `0.0.17`

Nejjednodussi pouziti:

```text
CalibreMetaEdit.bat
```

Otevre se normalni okno.
CMD okno se po spusteni hned zavre.
Konzolova okna pomocnych prikazu se appka snazi schovat.

V appce:

- pri startu se samo nacte `matches.csv`
- pri startu automaticky nacte nove knihy bez dotazu
- pole `Knihovna` dole pod stavem ukazuje, s jakou Calibre knihovnou appka pracuje
- `Zmenit` dole vybere jinou Calibre knihovnu a ulozi ji do `settings.json`
- `Pouzit z Calibre` dole vezme aktualni knihovnu z Calibre configu
- `Nacist nove knihy` - doplni do `matches.csv` jen nove knihy
- `Rebuild CSV` dole - zalohuje stary `matches.csv` a vytvori ho znovu od nuly
- `Rollback` dole - obnovi Calibre databazi `metadata.db` z vybrane zalohy
- klik na hlavicku sloupce seradi tabulku
- v tabulce vyber jednu nebo vic knih
- horni `Approve`, `Review`, `Skip` zmeni status vsem vybranym kniham
- druhy horni radek `Odkaz` a `Pouzit odkaz` upravuje odkaz u jedne vybrane knihy
- `Ulozit CSV`
- `Zapsat do Calibre`

`Zapsat do Calibre` udela:

1. ulozi `matches.csv`
2. pokusi se normalne zavrit Calibre
3. vytvori zalohu `metadata.db`
4. u `approve` radku stahne prehled a zalozku `Vydani` z Databaze knih
5. prepise komentar na odkaz, bold hodnoceni a text O knize
6. prepise `vydano`, `vydavatel` a `stitky`
7. do `vydano` posila datum jako `ROK-00-00`, aby Calibre ulozilo `ROK-01-01`
8. do stitku da nejdriv zanry z Databaze knih, potom spodni stitky knihy
9. hotove `approve` radky zmeni na `skip`
10. po zapisu nacte nove knihy
11. znovu nacte `matches.csv` do tabulky

V potvrzeni zapisu je zaskrtavatko pro vynucene zavreni `/F`.
Je zapnute automaticky. Vypni ho, kdyz v Calibre mas neulozenou praci.

Kdyz pri zapisu neco selze, appka vypise `Failed zapisy` ve spodnim vystupu.
Kdyz nejde stahnout detail knihy z Databaze knih, kniha se nezapise a zustane `approve`.

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
