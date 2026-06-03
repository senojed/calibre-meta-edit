# Qt desktop appka pro pohodlne schvalovani metadat v modernim Windows okne.

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import threading
import webbrowser
from pathlib import Path
from typing import Callable, Sequence

import calibre_meta_app as shared
import calibre_meta_edit as cme


APP_DIR = Path(__file__).resolve().parent
APP_VERSION = "0.1.2"
PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None
ICON_PATH = APP_DIR / "app_icon.svg"
TABLE_COLUMNS = ("ID", "Kniha", "Autor", "Status", "Zdroj", "Typ", "Odkaz", "Duvod")
STATUS_FILTER_VALUES = ("approve", "review", "skip")
SOURCE_FILTER_VALUES = ("databazeknih", "legie")
TYPE_FILTER_VALUES = ("povidka",)
THEME_VALUES = ("system", "light", "dark")


def app_title() -> str:
    """Vrati titulek hlavniho okna vcetne verze."""
    return f"Calibre Meta Edit {APP_VERSION}"


def filter_rows(
    rows: Sequence[cme.MatchRow],
    title: str = "",
    author: str = "",
    statuses: set[str] | None = None,
    sources: set[str] | None = None,
    work_types: set[str] | None = None,
) -> list[cme.MatchRow]:
    """Vrati jen radky, ktere odpovidaji filtrum v horni liste."""
    title_query = cme.normalize_text(title)
    author_query = cme.normalize_text(author)
    result: list[cme.MatchRow] = []
    for row in rows:
        if title_query and title_query not in cme.normalize_text(row.title):
            continue
        if author_query and author_query not in cme.normalize_text(row.authors):
            continue
        if statuses is not None and row.status not in statuses:
            continue
        if sources is not None and row.source not in sources:
            continue
        if work_types is not None and row.work_type not in work_types:
            continue
        result.append(row)
    return result


def statusbar_text(status: str, calibre_running: bool, csv_loaded: bool) -> str:
    """Slozi kratky text do spodni status listy."""
    calibre_text = "Calibre zapnuto" if calibre_running else "Calibre vypnuto"
    csv_text = "matches.csv nacteno" if csv_loaded else "matches.csv nenacteno"
    return f"{status} | {calibre_text} | {csv_text} | {APP_VERSION}"


def is_calibre_running(runner: Callable[[Sequence[str]], cme.CommandResult] = cme.run_command) -> bool:
    """Zjisti, jestli bezi Calibre GUI."""
    result = runner(["tasklist", "/FI", "IMAGENAME eq calibre.exe"])
    text = (result.stdout + result.stderr).lower()
    return result.returncode == 0 and "calibre.exe" in text


def normalize_theme(value: str) -> str:
    """Vrati platny nazev vzhledu."""
    normalized = value.strip().casefold()
    return normalized if normalized in THEME_VALUES else "system"


def read_app_settings(settings_path: Path = shared.SETTINGS_PATH) -> dict[str, str]:
    """Precte nase nastaveni a ignoruje rozbite hodnoty."""
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items() if isinstance(value, str)}


def save_app_settings(library: str, theme: str, settings_path: Path = shared.SETTINGS_PATH) -> None:
    """Ulozi knihovnu i vzhled do jednoho settings.json."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({"library_path": library, "theme": normalize_theme(theme)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if PYSIDE6_AVAILABLE:
    from PySide6.QtCore import QObject, Qt, Signal
    from PySide6.QtGui import QColor, QFont, QIcon
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QFileDialog,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QStyleFactory,
        QPushButton,
        QSizePolicy,
        QSplitter,
        QStatusBar,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    class WorkerBridge(QObject):
        """Signalovy most z background threadu zpet do Qt event loopu."""

        finished = Signal(str, int, str, bool)

    class PreferencesDialog(QDialog):
        """Dialog pro knihovnu a rizikove servisni akce."""

        def __init__(self, parent: "CalibreMetaQtWindow") -> None:
            super().__init__(parent)
            self.parent_window = parent
            self.setWindowTitle("Preferences")
            self.setMinimumWidth(720)
            self._build_ui()

        def _build_ui(self) -> None:
            layout = QVBoxLayout(self)
            form = QGridLayout()
            form.addWidget(QLabel("Knihovna"), 0, 0)
            self.library_edit = QLineEdit(self.parent_window.library_path)
            form.addWidget(self.library_edit, 0, 1)
            browse = QPushButton("Zmenit")
            browse.clicked.connect(self.choose_library)
            form.addWidget(browse, 0, 2)
            use_calibre = QPushButton("Pouzit z Calibre")
            use_calibre.clicked.connect(self.use_calibre_library)
            form.addWidget(use_calibre, 0, 3)
            form.addWidget(QLabel("Vzhled"), 1, 0)
            self.theme_combo = QComboBox()
            self.theme_combo.addItems(THEME_VALUES)
            self.theme_combo.setCurrentText(self.parent_window.theme)
            form.addWidget(self.theme_combo, 1, 1)
            layout.addLayout(form)

            buttons = QHBoxLayout()
            rebuild = QPushButton("Rebuild CSV")
            rebuild.setObjectName("dangerButton")
            rebuild.clicked.connect(self.run_rebuild)
            rollback = QPushButton("Rollback")
            rollback.setObjectName("dangerButton")
            rollback.clicked.connect(self.run_rollback)
            save = QPushButton("Ulozit")
            save.clicked.connect(self.save_library)
            close = QPushButton("Zavrit")
            close.clicked.connect(self.accept)
            buttons.addWidget(rebuild)
            buttons.addWidget(rollback)
            buttons.addStretch(1)
            buttons.addWidget(save)
            buttons.addWidget(close)
            layout.addLayout(buttons)

        def choose_library(self) -> None:
            selected = QFileDialog.getExistingDirectory(self, "Vyber Calibre knihovnu", self.library_edit.text())
            if selected:
                self.library_edit.setText(selected)

        def use_calibre_library(self) -> None:
            library = shared.read_calibre_library_path()
            if not library:
                QMessageBox.information(self, "Calibre", "Calibre knihovna nenalezena.")
                return
            self.library_edit.setText(library)

        def save_library(self) -> None:
            library = self.library_edit.text().strip()
            if not library:
                QMessageBox.warning(self, "Knihovna", "Zadej cestu ke knihovne.")
                return
            save_app_settings(library, self.theme_combo.currentText())
            self.parent_window.library_path = library
            self.parent_window.theme = normalize_theme(self.theme_combo.currentText())
            self.parent_window.apply_theme()
            self.parent_window.set_status("Knihovna ulozena")

        def run_rebuild(self) -> None:
            self.save_library()
            self.parent_window.run_rebuild()

        def run_rollback(self) -> None:
            self.save_library()
            self.parent_window.run_rollback()

    class CalibreMetaQtWindow(QMainWindow):
        """Hlavni Qt okno. Drzi tabulku, filtry, detail a statusbar."""

        def __init__(self) -> None:
            super().__init__()
            self.matches_path = cme.MATCHES_PATH
            self.library_path = shared.initial_library_path()
            self.theme = normalize_theme(read_app_settings().get("theme", "system"))
            self.rows: list[cme.MatchRow] = []
            self.filtered_rows: list[cme.MatchRow] = []
            self.worker_running = False
            self.csv_loaded = False
            self.calibre_running = False
            self.bridge = WorkerBridge()
            self.bridge.finished.connect(self.finish_background)
            self.setWindowTitle(app_title())
            if ICON_PATH.exists():
                self.setWindowIcon(QIcon(str(ICON_PATH)))
            self.resize(1320, 780)
            self._build_ui()
            self.load_csv(show_message=False)

        def _build_ui(self) -> None:
            root = QWidget()
            layout = QVBoxLayout(root)
            layout.setContentsMargins(10, 10, 10, 6)
            layout.setSpacing(8)
            layout.addLayout(self._build_toolbar())
            layout.addLayout(self._build_filterbar())
            layout.addWidget(self._build_main_area(), stretch=1)
            self.setCentralWidget(root)
            self.setStatusBar(QStatusBar())
            self.set_status("Ready")
            self.apply_theme()

        def _build_toolbar(self) -> QHBoxLayout:
            toolbar = QHBoxLayout()
            toolbar.setSpacing(6)
            self.buttons: list[QPushButton] = []

            self._add_button(toolbar, "Nacist CSV", self.load_csv)
            self._add_button(toolbar, "Ulozit CSV", self.save_csv)
            self._add_button(toolbar, "Audit odkazu", self.run_audit)
            self._add_button(toolbar, "Update vybrane", self.run_update_selected, "updateButton")
            toolbar.addStretch(1)
            self._add_button(toolbar, "Preferences", self.open_preferences)
            self._add_button(toolbar, "Zapsat", self.run_apply, "applyButton")
            return toolbar

        def _add_button(
            self,
            layout: QHBoxLayout,
            text: str,
            callback: Callable[[], None],
            object_name: str = "",
        ) -> QPushButton:
            button = QPushButton(text)
            if object_name:
                button.setObjectName(object_name)
            button.clicked.connect(callback)
            layout.addWidget(button)
            self.buttons.append(button)
            return button

        def _build_filterbar(self) -> QHBoxLayout:
            bar = QHBoxLayout()
            bar.setSpacing(6)
            self.title_filter = self._filter_edit("Kniha", bar)
            self.author_filter = self._filter_edit("Autor", bar)
            self.status_checks = self._filter_checks("Status", STATUS_FILTER_VALUES, bar)
            self.source_checks = self._filter_checks("Zdroj", SOURCE_FILTER_VALUES, bar)
            self.type_checks = self._filter_checks("Typ", TYPE_FILTER_VALUES, bar)
            return bar

        def _filter_edit(self, label: str, layout: QHBoxLayout) -> QLineEdit:
            layout.addWidget(QLabel(label))
            field = QLineEdit()
            field.setClearButtonEnabled(True)
            field.textChanged.connect(self.refresh_table)
            layout.addWidget(field, stretch=1)
            return field

        def _filter_checks(self, label: str, values: Sequence[str], layout: QHBoxLayout) -> dict[str, QCheckBox]:
            frame = QFrame()
            row = QHBoxLayout(frame)
            row.setContentsMargins(8, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(QLabel(label))
            checks: dict[str, QCheckBox] = {}
            for value in values:
                check = QCheckBox(value)
                check.setChecked(True)
                check.stateChanged.connect(self.refresh_table)
                row.addWidget(check)
                checks[value] = check
            layout.addWidget(frame)
            return checks

        def _build_main_area(self) -> QSplitter:
            splitter = QSplitter(Qt.Orientation.Horizontal)
            self.table = QTableWidget(0, len(TABLE_COLUMNS))
            self.table.setHorizontalHeaderLabels(TABLE_COLUMNS)
            self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self.table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
            self.table.setSortingEnabled(True)
            self.table.verticalHeader().setVisible(False)
            self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            self.table.horizontalHeader().setStretchLastSection(True)
            self.table.itemSelectionChanged.connect(self.on_selection_changed)
            splitter.addWidget(self.table)
            splitter.addWidget(self._build_detail_panel())
            splitter.setSizes([900, 360])
            return splitter

        def _build_detail_panel(self) -> QWidget:
            panel = QWidget()
            panel.setMinimumWidth(320)
            panel.setMaximumWidth(460)
            layout = QVBoxLayout(panel)
            self.detail_title = QLabel("Bez vyberu")
            self.detail_title.setWordWrap(True)
            self.detail_author = QLabel("")
            self.detail_author.setWordWrap(True)
            layout.addWidget(self.detail_title)
            layout.addWidget(self.detail_author)

            status_buttons = QHBoxLayout()
            self._add_button(status_buttons, "Approve", lambda: self.set_selected_status("approve"), "approveButton")
            self._add_button(status_buttons, "Review", lambda: self.set_selected_status("review"), "reviewButton")
            self._add_button(status_buttons, "Skip", lambda: self.set_selected_status("skip"), "skipButton")
            self._add_button(status_buttons, "Povidka", self.mark_selected_story, "storyButton")
            layout.addLayout(status_buttons)

            layout.addWidget(QLabel("Odkaz"))
            self.url_edit = QLineEdit()
            self.url_edit.setClearButtonEnabled(True)
            layout.addWidget(self.url_edit)
            url_buttons = QHBoxLayout()
            self._add_button(url_buttons, "Pouzit odkaz", self.apply_selected_url)
            self._add_button(url_buttons, "Otevrit odkaz", self.open_selected_url)
            layout.addLayout(url_buttons)

            layout.addWidget(QLabel("Log / nahled"))
            self.output = QTextEdit()
            self.output.setReadOnly(True)
            self.output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            layout.addWidget(self.output, stretch=1)
            return panel

        def load_csv(self, show_message: bool = True) -> None:
            if not self.matches_path.exists():
                self.rows = []
                self.csv_loaded = False
                self.refresh_table()
                self.set_status(f"Soubor nenalezen: {self.matches_path}")
                return
            try:
                self.rows = cme.read_matches_csv(self.matches_path)
            except Exception as exc:
                QMessageBox.critical(self, "Chyba", f"CSV nejde nacist:\n{exc}")
                return
            self.csv_loaded = True
            self.refresh_table()
            self.set_status(shared.status_summary(self.rows))
            if show_message:
                self.write_output(f"Nacteno: {self.matches_path}\n{shared.status_summary(self.rows)}")

        def save_csv(self, show_message: bool = True) -> bool:
            try:
                cme.write_matches_csv(self.matches_path, self.rows, overwrite=True)
            except Exception as exc:
                QMessageBox.critical(self, "Chyba", f"CSV nejde ulozit:\n{exc}")
                return False
            self.csv_loaded = True
            self.set_status(f"Ulozeno. {shared.status_summary(self.rows)}")
            if show_message:
                self.write_output(f"Ulozeno: {self.matches_path}")
            return True

        def refresh_table(self) -> None:
            selected_ids = self.selected_book_ids()
            self.filtered_rows = filter_rows(
                self.rows,
                title=self.title_filter.text(),
                author=self.author_filter.text(),
                statuses=self.checked_values(self.status_checks),
                sources=self.checked_values(self.source_checks),
                work_types=self.checked_values(self.type_checks),
            )
            self.table.setSortingEnabled(False)
            self.table.setRowCount(len(self.filtered_rows))
            for row_index, row in enumerate(self.filtered_rows):
                values = (
                    str(row.book_id),
                    row.title,
                    row.authors,
                    row.status,
                    row.source,
                    row.work_type,
                    row.chosen_url,
                    row.reason,
                )
                for col_index, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, row.book_id)
                    if col_index == 0:
                        item.setData(Qt.ItemDataRole.DisplayRole, row.book_id)
                    item.setBackground(status_color(row.status))
                    item.setForeground(QColor("#111111"))
                    self.table.setItem(row_index, col_index, item)
            self.table.setSortingEnabled(True)
            self.restore_selection(selected_ids)

        def checked_values(self, checks: dict[str, QCheckBox]) -> set[str] | None:
            """Vrati vybrane hodnoty; vse vybrane znamena bez filtru."""
            selected = {value for value, check in checks.items() if check.isChecked()}
            if len(selected) == len(checks):
                return None
            return selected

        def restore_selection(self, book_ids: set[int]) -> None:
            if not book_ids:
                self.on_selection_changed()
                return
            self.table.clearSelection()
            for row_index, row in enumerate(self.filtered_rows):
                if row.book_id in book_ids:
                    self.table.selectRow(row_index)
            self.on_selection_changed()

        def selected_book_ids(self) -> set[int]:
            selected: set[int] = set()
            for item in self.table.selectedItems():
                book_id = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(book_id, int):
                    selected.add(book_id)
            return selected

        def selected_row(self) -> cme.MatchRow | None:
            selected = sorted(self.selected_book_ids())
            if not selected:
                return None
            index = shared.find_row_index(self.rows, selected[0])
            return self.rows[index] if index is not None else None

        def on_selection_changed(self) -> None:
            row = self.selected_row()
            if row is None:
                self.detail_title.setText("Bez vyberu")
                self.detail_author.setText("")
                self.url_edit.setText("")
                return
            self.detail_title.setText(f"{row.book_id} - {row.title}")
            self.detail_author.setText(row.authors)
            if self.url_edit.text() != row.chosen_url:
                self.url_edit.setText(row.chosen_url)

        def set_selected_status(self, status: str) -> None:
            selected = self.selected_book_ids()
            if not selected:
                QMessageBox.information(self, "Vyber radek", "Nejdriv vyber knihu v tabulce.")
                return
            self.rows = shared.update_rows_status(self.rows, selected, status)
            self.refresh_table()
            self.set_status(shared.status_summary(self.rows))

        def mark_selected_story(self) -> None:
            selected = self.selected_book_ids()
            if not selected:
                QMessageBox.information(self, "Vyber radek", "Nejdriv vyber knihu v tabulce.")
                return
            self.rows = shared.mark_rows_as_story(self.rows, selected)
            self.refresh_table()
            self.set_status(shared.status_summary(self.rows))

        def apply_selected_url(self) -> None:
            selected = self.selected_book_ids()
            if not selected:
                QMessageBox.information(self, "Vyber radek", "Nejdriv vyber knihu v tabulce.")
                return
            self.rows = shared.update_rows_url(self.rows, selected, self.url_edit.text())
            self.refresh_table()
            self.set_status(shared.status_summary(self.rows))

        def open_selected_url(self) -> None:
            row = self.selected_row()
            if row is None:
                QMessageBox.information(self, "Vyber radek", "Nejdriv vyber knihu v tabulce.")
                return
            url = self.url_edit.text().strip() or row.chosen_url.strip()
            if not url:
                QMessageBox.information(self, "Bez odkazu", "Vybrany radek nema odkaz.")
                return
            webbrowser.open_new(url)

        def run_preview(self) -> None:
            if not self.save_csv(show_message=False):
                return
            args = shared.make_script_args(self.library_path)
            action = shared.make_preview_with_legie_audit_action(args, matches_path=self.matches_path)
            self.run_background("Nacitani novych knih + Audit odkazu", action, reload_after=True)

        def run_update_selected(self) -> None:
            selected = self.selected_book_ids()
            if not selected:
                QMessageBox.information(self, "Vyber radek", "Nejdriv vyber knihu v tabulce.")
                return
            if not self.save_csv(show_message=False):
                return
            args = shared.make_script_args(self.library_path)
            args.book_ids = sorted(selected)
            action = shared.make_preview_with_legie_audit_action(args, matches_path=self.matches_path)
            self.run_background("Update vybranych + Audit odkazu", action, reload_after=True)

        def run_audit(self) -> None:
            selected = self.selected_book_ids()
            self.rows = shared.sync_single_selected_url(self.rows, selected, self.url_edit.text())
            self.refresh_table()
            if not self.save_csv(show_message=False):
                return
            args = shared.make_legie_audit_args(self.library_path, selected if selected else None)
            action = shared.make_legie_audit_action(args)
            self.run_background("Audit odkazu", action, reload_after=True)

        def run_apply(self) -> None:
            confirmed, allow_force = self.ask_apply_confirmation()
            if not confirmed:
                return
            if not self.save_csv(show_message=False):
                return
            args = shared.make_script_args(self.library_path)
            action = shared.make_apply_action(args=args, allow_force=allow_force, matches_path=self.matches_path)
            self.run_background("Zapis do Calibre", action, reload_after=True)

        def run_rebuild(self) -> None:
            message = (
                "Rebuild prepise matches.csv.\n"
                "Stary matches.csv ulozim do backups\\matches.\n"
                "Knihy s existujicim odkazem nebudu hledat znovu.\n"
                "Pokracovat?"
            )
            choice = QMessageBox.question(
                self,
                "Rebuild CSV",
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
            args = shared.make_script_args(self.library_path, overwrite=True)
            action = shared.make_rebuild_action(args, self.matches_path)
            self.run_background("Rebuild CSV", action, reload_after=True)

        def run_rollback(self) -> None:
            backup_path, _filter = QFileDialog.getOpenFileName(
                self,
                "Vyber zalohu metadata.db",
                str(shared.BACKUPS_DIR),
                "Calibre metadata zalohy (metadata*.db);;SQLite DB (*.db);;Vsechny soubory (*.*)",
            )
            if not backup_path:
                return
            confirmed, allow_force = self.ask_rollback_confirmation(Path(backup_path))
            if not confirmed:
                return
            action = shared.make_rollback_action(self.library_path, Path(backup_path), allow_force=allow_force)
            self.run_background("Rollback zalohy", action, reload_after=False)

        def ask_apply_confirmation(self) -> tuple[bool, bool]:
            box = QMessageBox(self)
            box.setWindowTitle("Zapsat do Calibre")
            box.setText(shared.apply_confirmation_message())
            force = QCheckBox("Kdyz to nepujde normalne, vynutit zavreni Calibre pres /F")
            force.setChecked(True)
            box.setCheckBox(force)
            box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(QMessageBox.StandardButton.Ok)
            result = box.exec() == QMessageBox.StandardButton.Ok
            return result, force.isChecked()

        def ask_rollback_confirmation(self, backup_path: Path) -> tuple[bool, bool]:
            box = QMessageBox(self)
            box.setWindowTitle("Rollback zalohy")
            box.setText(
                "Appka udela:\n"
                "1. pokusi se zavrit Calibre\n"
                "2. ulozi aktualni metadata.db jako nouzovou zalohu\n"
                "3. obnovi vybranou zalohu:\n"
                f"{backup_path}"
            )
            force = QCheckBox("Kdyz to nepujde normalne, vynutit zavreni Calibre pres /F")
            force.setChecked(True)
            box.setCheckBox(force)
            box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            result = box.exec() == QMessageBox.StandardButton.Ok
            return result, force.isChecked()

        def run_background(self, title: str, action: Callable[[], int], reload_after: bool) -> None:
            if self.worker_running:
                QMessageBox.information(self, "Bezi akce", "Pockej, az skonci aktualni akce.")
                return
            self.worker_running = True
            self.set_buttons_enabled(False)
            self.write_output(f"{title}...")
            self.set_status(title)

            def worker() -> None:
                buffer = io.StringIO()
                try:
                    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                        result = action()
                    text = buffer.getvalue().strip()
                except Exception as exc:
                    result = 1
                    text = f"Chyba: {exc}"
                self.bridge.finished.emit(title, result, text, reload_after)

            threading.Thread(target=worker, daemon=True).start()

        def finish_background(self, title: str, result: int, text: str, reload_after: bool) -> None:
            self.worker_running = False
            self.set_buttons_enabled(True)
            if reload_after and result == 0:
                self.load_csv(show_message=False)
            suffix = "OK" if result == 0 else "CHYBA"
            self.write_output(f"{title}: {suffix}\n\n{text or '(bez vystupu)'}")
            self.set_status(f"{title}: {suffix}. {shared.status_summary(self.rows)}")

        def apply_theme(self) -> None:
            """Pouzije zvoleny vzhled bez restartu appky."""
            app = QApplication.instance()
            if app is not None:
                app.setStyle(QStyleFactory.create("Fusion"))
            base = """
                * { font-family: "Segoe UI"; }
                QPushButton { min-height: 30px; padding: 4px 10px; border-radius: 3px; }
                QPushButton#approveButton { background: #2e7d32; color: white; }
                QPushButton#reviewButton { background: #ef6c00; color: white; }
                QPushButton#skipButton { background: #757575; color: white; }
                QPushButton#storyButton, QPushButton#updateButton { background: #1565c0; color: white; }
                QPushButton#applyButton, QPushButton#dangerButton { background: #c62828; color: white; }
                QLineEdit, QComboBox { min-height: 28px; }
                QTableWidget { gridline-color: #b8b8b8; alternate-background-color: #f3f3f3; color: #111111; }
                QTableWidget::item { color: #111111; }
                QTextEdit { font-family: Consolas; font-size: 10pt; }
            """
            if self.theme == "dark":
                self.setStyleSheet(
                    base
                    + """
                    QMainWindow, QWidget { background: #202124; color: #f2f2f2; }
                    QLineEdit, QComboBox, QTextEdit { background: #2d2f33; color: #f2f2f2; border: 1px solid #4b4d52; }
                    QHeaderView::section { background: #3a3a3a; color: #ffffff; padding: 4px; }
                    """
                )
            elif self.theme == "light":
                self.setStyleSheet(
                    base
                    + """
                    QMainWindow, QWidget { background: #f5f5f5; color: #111111; }
                    QLineEdit, QComboBox, QTextEdit { background: #ffffff; color: #111111; border: 1px solid #c7c7c7; }
                    QHeaderView::section { background: #e8e8e8; color: #111111; padding: 4px; }
                    """
                )
            else:
                self.setStyleSheet(base)

        def open_preferences(self) -> None:
            PreferencesDialog(self).exec()

        def set_buttons_enabled(self, enabled: bool) -> None:
            for button in self.buttons:
                button.setEnabled(enabled)

        def write_output(self, text: str) -> None:
            self.output.setPlainText(text)

        def set_status(self, text: str) -> None:
            self.calibre_running = is_calibre_running()
            self.statusBar().showMessage(statusbar_text(text, self.calibre_running, self.csv_loaded))

    def status_color(status: str) -> QColor:
        """Vrati jemnou barvu radku podle statusu."""
        if status == "approve":
            return QColor("#e8f5e9")
        if status == "review":
            return QColor("#fff3e0")
        if status == "skip":
            return QColor("#f5f5f5")
        return QColor("#ffffff")

else:

    class CalibreMetaQtWindow:  # type: ignore[no-redef]
        """Placeholder, kdyz PySide6 jeste neni nainstalovane."""

        def __init__(self) -> None:
            raise RuntimeError("PySide6 neni nainstalovane")


def main() -> int:
    """Spusti Qt appku."""
    if not PYSIDE6_AVAILABLE:
        raise RuntimeError("PySide6 neni nainstalovane. Spust: python -m pip install PySide6")
    os.chdir(APP_DIR)
    app = QApplication([])
    app.setFont(QFont("Segoe UI", 9))
    window = CalibreMetaQtWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
