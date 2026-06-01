# Legie Story Support Design

## Cil

Podporit povidky, ktere nejsou samostatne na Databazi knih, ale maji zaznam na Legii.
Typicky priklad je `A opice si myslely, ze je to vsechno jen legrace`, kde Databaze knih vratila jinou knihu a spravny zaznam je Legie povidka.

Hlavni cil je audit bez bordelu: najit podezrele povidky, ukazat je v appce jako `review`, a zapisovat je az po rucnim schvaleni.

## Zasady

- Databaze knih zustane hlavni zdroj pro knihy.
- Legie se pouzije jako druhy zdroj pro povidky a nejasne shody.
- Existujici spravne odkazy na Databazi knih se automaticky neprepisuji.
- Legie kandidat nikdy nejde rovnou do `approve`; vzdy zacina jako `review`.
- Zapis do Calibre zustane pres `calibredb` a pred zapisem zustane zaloha `metadata.db`.

## Kdy hledat na Legii

Preview zkusi Legii jen v techto pripadech:

- Databaze knih nenasla zadneho kandidata.
- Databaze knih vratila jen `title-only`, `multiple-title-matches`, `partial-title` nebo jiny nejisty vysledek.
- Rucne spusteny audit povidek pozdeji projede existujici `review` a podezrele `skip` radky.

Preview nebude automaticky prekopavat radky, ktere uz maji jistou shodu z Databaze knih.

## CSV

Pridaji se sloupce:

- `source`: `databazeknih` nebo `legie`
- `work_type`: prazdne pro beznou knihu, `povidka` pro Legii povidku

Stare CSV se musi nacist i bez techto sloupcu. Pri ulozeni se doplni nove sloupce.

Legie kandidat bude mit:

- `status=review`
- `source=legie`
- `work_type=povidka`
- `chosen_url=https://www.legie.info/povidka/...`
- `reason=legie-story-candidate`

## Metadata z Legie

Parser Legie povidky vytahne:

- autor
- nazev
- kategorie jako stitek, napr. `sci-fi`
- hodnoceni procentem, napr. `80 %`
- pocet hodnoceni, pokud je dostupny
- originalni nazev
- originalni vydani, napr. `05/1979`
- kde povidka vysla cesky, napr. `Ikarie 1995/05`
- prekladatel, pokud je dostupny
- anotace/informace

Do Calibre:

- `comments`: odkaz na Legii, hodnoceni, originalni vydani, ceske vydani a anotace
- `tags`: stavajici tagy ze zdroje plus `povidka`
- `identifiers`: `legie:7347`
- `publisher` a `pubdate`: jen pokud parser dokaze bezpecne urcit ceske vydani z navazane knihy/casopisu; jinak nezapisovat

## Appka

Tabulka musi ukazat aspon `source` a `work_type`, aby bylo jasne, odkud navrh prisel.

Uzivatel muze:

- ponechat Legie povidku jako `review`
- zmenit ji na `approve`
- zmenit ji na `skip`
- rucne prepsat odkaz

`Zapsat do Calibre` zapise Legii jen u radku `status=approve`.

## Rizika

- Legie nema stejnou strukturu jako Databaze knih a HTML se muze menit.
- Nazvy povidek maji caste varianty, preklady a zkraceni.
- Nektere Calibre zaznamy mohou byt kapitoly, clanky nebo casti antologii, ne samostatne povidky.

Kvuli tomu bude prvni verze Legie podpory auditni a konzervativni.

## Testy

- Parser Legie povidky nad fixture HTML pro ukazkovou povidku.
- Matching: nejista Databaze knih shoda vyvola Legii search a vysledek bude `review`.
- CSV umi nacist stare radky bez `source` a `work_type`.
- Apply Legie radku zapise `comments`, `tags:povidka` a `identifiers:legie:ID`.
- Apply Legie radku nezapise `pubdate/publisher`, pokud nejsou bezpecne urcene.

## Mimo rozsah prvni implementace

- Automaticke prepisovani existujicich Databaze knih odkazu na Legii.
- Hromadne automaticke `approve` povidek.
- Presne skladani vydani z navazanych Legie knih/casopisu, pokud parser nebude stabilni.
