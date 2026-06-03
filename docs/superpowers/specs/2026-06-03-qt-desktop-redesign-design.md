# Qt desktop redesign design

## Goal

Vytvorit novou Qt/PySide6 desktop appku `Calibre Meta Edit 0.1.0`, ktera vypada jako profesionalni Windows nastroj, ale pouziva stavajici backend `calibre_meta_edit.py`.

## Non-goals

- Nedelat EXE v teto fazi.
- Neprepisovat scraping ani zapis do Calibre.
- Nemazat Tkinter appku; zustane fallback.

## Architecture

- `calibre_meta_edit.py` zustava backend pro CSV, preview, audit a zapis.
- `calibre_meta_qt.py` bude novy Qt frontend.
- `calibre_meta_app.py` zustava stary Tkinter frontend.
- Verze appky bude `0.1.0`.

## UI

- Hlavni okno: native Qt/PySide6 Windows vzhled.
- Horni toolbar: ctvercova tlacitka pro hlavni akce.
- Filtry budou v horni liste, ne v bocnim panelu:
  - `Kniha`
  - `Autor`
  - `Status`
  - `Zdroj`
  - `Typ`
- Hlavni cast: velka sortable tabulka.
- Pravy panel: detail vybrane knihy.
  - nazev
  - autor
  - status tlacitka
  - odkaz
  - nahled logu/komentare
- Spodni statusbar:
  - `Ready`
  - `Calibre vypnuto` nebo `Calibre zapnuto`
  - stav `matches.csv`
  - verze `0.1.0`
- Nastaveni knihovny, `Rebuild CSV` a `Rollback` se presunou do `Preferences`.

## Behavior

- Pri startu appka nacte `matches.csv`.
- Akce pouziji stavajici backend funkce.
- Vyber vice radku musi zustat podporovany.
- Zmena statusu a pouziti odkazu musi menit data stejne jako Tk appka.
- Filtry meni jen zobrazeni, ne obsah CSV.
- Tkinter appka zustane funkcni pro navrat, kdyby Qt verze zlobila.

## Risks

- PySide6 je nova dependency.
- EXE pozdeji bude vetsi a bude chtit zvlast test.
- Nejrizikovejsi cast je synchronizace filtr + vyber radku + zapis + reload CSV.

## Test strategy

- Pridat testy pro ciste model/helper funkce, ktere nejsou zavisle na Qt event loop.
- Zachovat existujici testy backendu a Tk appky.
- Spustit `python -m unittest discover -s tests`.
- Rucne spustit Qt appku az po zakladni implementaci.
