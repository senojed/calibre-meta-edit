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
from typing import Any, Callable, Sequence

import calibre_meta_app as shared
import calibre_meta_edit as cme


APP_DIR = Path(__file__).resolve().parent
APP_VERSION = "0.2.8"
PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None
ICON_PATH = APP_DIR / "app_icon.svg"
ICON_DIR = APP_DIR / "icons"
TABLE_COLUMNS = ("ID", "Kniha", "Autor", "Status", "Zdroj", "Typ", "Odkaz", "Duvod")
REQUIRED_COLUMN_INDEXES = {0, 1, 2}
MIN_COLUMN_WIDTH = 36
STATUS_FILTER_VALUES = ("approve", "review", "skip")
SOURCE_FILTER_VALUES = ("databazeknih", "legie")
TYPE_FILTER_VALUES = ("", "povidka")
THEME_VALUES = ("system", "light", "dark")
AUTO_SETTING_DEFAULTS = {
    "startup_preview": True,
    "auto_link_audit": True,
    "auto_cover_audit": True,
}


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
    csv_text = "matches.csv nacteno" if csv_loaded else "matches.csv nenacteno"
    return f"{status} | {csv_text} | {APP_VERSION}"


def filter_label(value: str) -> str:
    """Zobrazi prazdnou hodnotu filtru lidsky."""
    return value or "bez typu"


def selection_title(rows: Sequence[cme.MatchRow]) -> str:
    """Vrati text nad status tlacitka podle vyberu."""
    if not rows:
        return "Bez vyberu"
    if len(rows) == 1:
        row = rows[0]
        return f"{row.book_id} - {row.title}"
    return f"Vybrano {len(rows)} polozek"


def selection_link_text(rows: Sequence[cme.MatchRow]) -> str:
    """Vrati odkaz pro vyber; pri ruznych adresach vrati informacni text."""
    urls = {row.chosen_url.strip() for row in rows}
    if not rows:
        return ""
    if len(urls) == 1:
        return next(iter(urls))
    return "Ruzne adresy"


def selection_link_actions_enabled(rows: Sequence[cme.MatchRow]) -> bool:
    """Link tlacitka maji smysl jen pro jeden odkaz."""
    return bool(rows) and selection_link_text(rows) != "Ruzne adresy"


def use_link_enabled(rows: Sequence[cme.MatchRow], link_text: str) -> bool:
    """Pouzit odkaz jde i pro prazdny text, ale ne pro informacni text."""
    return bool(rows) and link_text.strip() != "Ruzne adresy"


def open_link_enabled(rows: Sequence[cme.MatchRow], link_text: str) -> bool:
    """Otevrit odkaz jde jen kdyz existuje jeden konkretni odkaz."""
    return use_link_enabled(rows, link_text) and bool(link_text.strip())


def is_calibre_running(runner: Callable[[Sequence[str]], cme.CommandResult] = cme.run_command) -> bool:
    """Zjisti, jestli bezi Calibre GUI."""
    result = runner(["tasklist", "/FI", "IMAGENAME eq calibre.exe"])
    text = (result.stdout + result.stderr).lower()
    return result.returncode == 0 and "calibre.exe" in text


def normalize_theme(value: str) -> str:
    """Vrati platny nazev vzhledu."""
    normalized = value.strip().casefold()
    return normalized if normalized in THEME_VALUES else "system"


def normalize_auto_settings(raw: Any) -> dict[str, bool]:
    """Vrati nastaveni automatickych akci s rozumnymi vychozimi hodnotami."""
    if not isinstance(raw, dict):
        raw = {}
    return {
        key: raw.get(key) if isinstance(raw.get(key), bool) else default
        for key, default in AUTO_SETTING_DEFAULTS.items()
    }


def auto_workflow_title(auto_settings: dict[str, bool]) -> str:
    """Slozi titulek background akce podle zapnutych automatickych kroku."""
    parts = ["Nacitani novych knih"]
    if auto_settings.get("auto_link_audit", True):
        parts.append("Audit odkazu")
    if auto_settings.get("auto_cover_audit", True):
        parts.append("Audit obalek")
    return " + ".join(parts)


def read_app_settings(settings_path: Path | None = None) -> dict[str, Any]:
    """Precte nase nastaveni a ignoruje rozbite hodnoty."""
    settings_path = settings_path or shared.SETTINGS_PATH
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items()}


def save_app_settings(library: str, theme: str, settings_path: Path | None = None) -> None:
    """Ulozi knihovnu a vzhled, ale zachova dalsi nastaveni appky."""
    settings_path = settings_path or shared.SETTINGS_PATH
    settings = read_app_settings(settings_path)
    settings["library_path"] = library
    settings["theme"] = normalize_theme(theme)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalize_column_settings(raw: Any) -> dict[str, dict[str, bool | int]]:
    """Vybere jen platne nastaveni sloupcu podle aktualni tabulky."""
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, bool | int]] = {}
    for column in TABLE_COLUMNS:
        value = raw.get(column)
        if not isinstance(value, dict):
            continue
        column_settings: dict[str, bool | int] = {}
        if isinstance(value.get("visible"), bool):
            column_settings["visible"] = value["visible"]
        if isinstance(value.get("width"), int) and value["width"] >= MIN_COLUMN_WIDTH:
            column_settings["width"] = value["width"]
        if column_settings:
            normalized[column] = column_settings
    return normalized


if PYSIDE6_AVAILABLE:
    from PySide6.QtCore import QObject, QPoint, QSize, Qt, QTimer, Signal
    from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPixmap
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
        QMenu,
        QMessageBox,
        QStyleFactory,
        QPushButton,
        QSizePolicy,
        QSplitter,
        QStatusBar,
        QStyle,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextEdit,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )

    def schedule_qt_startup_preview(preview_func: Callable[[], object]) -> None:
        """Po startu Qt event loopu automaticky spusti nacitani novych knih."""
        QTimer.singleShot(250, preview_func)


    class WorkerBridge(QObject):
        """Signalovy most z background threadu zpet do Qt event loopu."""

        finished = Signal(str, int, str, bool)
        cover_ready = Signal(int, str, str, str, bytes)

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
            browse.setObjectName("neutralButton")
            browse.clicked.connect(self.choose_library)
            form.addWidget(browse, 0, 2)
            use_calibre = QPushButton("Pouzit z Calibre")
            use_calibre.setObjectName("neutralButton")
            use_calibre.clicked.connect(self.use_calibre_library)
            form.addWidget(use_calibre, 0, 3)
            form.addWidget(QLabel("Vzhled"), 1, 0)
            self.theme_combo = QComboBox()
            self.theme_combo.addItems(THEME_VALUES)
            self.theme_combo.setCurrentText(self.parent_window.theme)
            form.addWidget(self.theme_combo, 1, 1)
            auto_settings = normalize_auto_settings(read_app_settings())
            self.startup_preview_check = QCheckBox("Po startu nacist nove knihy")
            self.startup_preview_check.setChecked(auto_settings["startup_preview"])
            self.auto_link_audit_check = QCheckBox("Po nacteni spustit audit odkazu")
            self.auto_link_audit_check.setChecked(auto_settings["auto_link_audit"])
            self.auto_cover_audit_check = QCheckBox("Po auditu pripravit obalky")
            self.auto_cover_audit_check.setChecked(auto_settings["auto_cover_audit"])
            form.addWidget(self.startup_preview_check, 2, 1, 1, 3)
            form.addWidget(self.auto_link_audit_check, 3, 1, 1, 3)
            form.addWidget(self.auto_cover_audit_check, 4, 1, 1, 3)
            layout.addLayout(form)

            buttons = QHBoxLayout()
            rebuild = QPushButton("Rebuild CSV")
            rebuild.setObjectName("dangerButton")
            rebuild.clicked.connect(self.run_rebuild)
            rollback = QPushButton("Rollback")
            rollback.setObjectName("dangerButton")
            rollback.clicked.connect(self.run_rollback)
            save = QPushButton("Ulozit")
            save.setObjectName("neutralButton")
            save.clicked.connect(self.save_library)
            close = QPushButton("Zavrit")
            close.setObjectName("neutralButton")
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
            settings = read_app_settings()
            settings["startup_preview"] = self.startup_preview_check.isChecked()
            settings["auto_link_audit"] = self.auto_link_audit_check.isChecked()
            settings["auto_cover_audit"] = self.auto_cover_audit_check.isChecked()
            shared.SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
            self.parent_window.library_path = library
            self.parent_window.theme = normalize_theme(self.theme_combo.currentText())
            self.parent_window.auto_settings = normalize_auto_settings(settings)
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
            settings = read_app_settings()
            theme_setting = settings.get("theme", "system")
            self.theme = normalize_theme(theme_setting if isinstance(theme_setting, str) else "system")
            self.auto_settings = normalize_auto_settings(settings)
            self.rows: list[cme.MatchRow] = []
            self.filtered_rows: list[cme.MatchRow] = []
            self.worker_running = False
            self.csv_loaded = False
            self.calibre_running = False
            self.bridge = WorkerBridge()
            self.bridge.finished.connect(self.finish_background)
            self.bridge.cover_ready.connect(self.finish_cover_preview)
            self.cover_preview_request_id = 0
            self.cover_preview_cache: dict[str, tuple[str, bytes]] = {}
            self.cover_option_buttons: dict[str, QToolButton] = {}
            self.setWindowTitle(app_title())
            if ICON_PATH.exists():
                self.setWindowIcon(QIcon(str(ICON_PATH)))
            self.resize(1320, 780)
            self._build_ui()
            self.calibre_timer = QTimer(self)
            self.calibre_timer.timeout.connect(self.refresh_calibre_indicator)
            self.calibre_timer.start(5000)
            self.load_csv(show_message=False)
            if self.auto_settings["startup_preview"]:
                schedule_qt_startup_preview(self.run_preview)

        def _build_ui(self) -> None:
            root = QWidget()
            layout = QVBoxLayout(root)
            layout.setContentsMargins(10, 10, 10, 6)
            layout.setSpacing(8)
            layout.addLayout(self._build_toolbar())
            layout.addWidget(self._build_main_area(), stretch=1)
            self.setCentralWidget(root)
            self.setStatusBar(QStatusBar())
            self.calibre_indicator = QLabel()
            self.statusBar().addPermanentWidget(self.calibre_indicator)
            self.set_status("Ready")
            self.apply_theme()

        def _build_toolbar(self) -> QHBoxLayout:
            toolbar = QHBoxLayout()
            toolbar.setSpacing(6)
            self.buttons: list[QToolButton] = []

            self._add_button(toolbar, "Nacist CSV", self.load_csv, "neutralButton", "open", show_text=False)
            self._add_button(toolbar, "Ulozit CSV", self.save_csv, "neutralButton", "save", show_text=False)
            self._add_button(toolbar, "Audit odkazu", self.run_audit, "neutralButton", "chain", show_text=False)
            self._add_button(toolbar, "Update vybrane", self.run_update_selected, "updateButton", "recycle", show_text=False)
            self._add_button(toolbar, "Obalky", self.run_covers, "neutralButton", "cover", show_text=False)
            toolbar.addSpacing(10)
            self._build_filterbar(toolbar)
            toolbar.addSpacing(10)
            self._add_button(toolbar, "Preferences", self.open_preferences, "neutralButton", "gear", show_text=False)
            self._add_button(toolbar, "Zapsat", self.run_apply, "applyButton", "apply", show_text=False)
            return toolbar

        def _add_button(
            self,
            layout: QHBoxLayout,
            text: str,
            callback: Callable[[], None],
            object_name: str = "",
            icon: str = "",
            show_text: bool = True,
        ) -> QToolButton:
            button = QToolButton()
            button.setText(text if show_text else "")
            button.setToolTip(text)
            button.setIconSize(QSize(32, 32))
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextUnderIcon if show_text else Qt.ToolButtonStyle.ToolButtonIconOnly
            )
            if not show_text:
                button.setProperty("iconOnly", True)
                button.setFixedSize(42, 42)
            if icon:
                button.setIcon(self.icon_for(icon))
            if object_name:
                button.setObjectName(object_name)
            button.clicked.connect(callback)
            layout.addWidget(button)
            self.buttons.append(button)
            return button

        def icon_for(self, name: str) -> QIcon:
            """Vrati vlastni SVG ikonu, nebo Qt fallback."""
            path = ICON_DIR / f"{name}.svg"
            if path.exists():
                return QIcon(str(path))
            fallback = {
                "open": QStyle.StandardPixmap.SP_DialogOpenButton,
                "save": QStyle.StandardPixmap.SP_DialogSaveButton,
                "apply": QStyle.StandardPixmap.SP_DialogApplyButton,
            }.get(name, QStyle.StandardPixmap.SP_FileIcon)
            return self.style().standardIcon(fallback)

        def _build_filterbar(self, bar: QHBoxLayout) -> None:
            self.title_filter = self._filter_edit("Kniha", bar)
            self.author_filter = self._filter_edit("Autor", bar)
            self.status_checks = self._filter_checks(STATUS_FILTER_VALUES, bar)
            self.source_checks = self._filter_checks(SOURCE_FILTER_VALUES, bar)
            self.type_checks = self._filter_checks(TYPE_FILTER_VALUES, bar)

        def _filter_edit(self, label: str, layout: QHBoxLayout) -> QLineEdit:
            layout.addWidget(QLabel(label))
            field = QLineEdit()
            field.setClearButtonEnabled(True)
            field.setMinimumWidth(130)
            field.textChanged.connect(self.refresh_table)
            layout.addWidget(field, stretch=2)
            return field

        def _filter_checks(self, values: Sequence[str], layout: QHBoxLayout) -> dict[str, QCheckBox]:
            frame = QFrame()
            row = QHBoxLayout(frame)
            row.setContentsMargins(20, 0, 0, 0)
            row.setSpacing(8)
            checks: dict[str, QCheckBox] = {}
            for value in values:
                check = QCheckBox(filter_label(value))
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
            self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
            self.table.setSortingEnabled(True)
            self.table.setAlternatingRowColors(True)
            self.table.verticalHeader().setVisible(False)
            self.table.verticalHeader().setDefaultSectionSize(22)
            self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            self.table.horizontalHeader().setStretchLastSection(False)
            self.table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.table.horizontalHeader().customContextMenuRequested.connect(self.show_column_menu)
            self.table.itemSelectionChanged.connect(self.on_selection_changed)
            self.apply_column_settings()
            splitter.addWidget(self.table)
            splitter.addWidget(self._build_detail_panel())
            splitter.setSizes([900, 360])
            return splitter

        def apply_column_settings(self) -> None:
            """Pri startu obnovi sirky a viditelnost sloupcu ze settings.json."""
            settings = normalize_column_settings(read_app_settings().get("columns"))
            for index, column in enumerate(TABLE_COLUMNS):
                column_settings = settings.get(column, {})
                width = column_settings.get("width")
                if isinstance(width, int):
                    self.table.setColumnWidth(index, width)
                visible = column_settings.get("visible")
                if index in REQUIRED_COLUMN_INDEXES:
                    self.table.setColumnHidden(index, False)
                elif isinstance(visible, bool):
                    self.table.setColumnHidden(index, not visible)

        def save_column_settings(self, width_overrides: dict[int, int] | None = None) -> None:
            """Ulozi aktualni sirky a viditelnost sloupcu do settings.json."""
            width_overrides = width_overrides or {}
            settings = read_app_settings()
            previous_columns = normalize_column_settings(settings.get("columns"))
            columns: dict[str, dict[str, bool | int]] = {}
            for index, column in enumerate(TABLE_COLUMNS):
                previous_width = previous_columns.get(column, {}).get("width")
                if index in width_overrides:
                    width = width_overrides[index]
                elif self.table.isColumnHidden(index) and isinstance(previous_width, int):
                    width = previous_width
                else:
                    width = self.table.columnWidth(index)
                columns[column] = {
                    "visible": False if index in REQUIRED_COLUMN_INDEXES else not self.table.isColumnHidden(index),
                    "width": max(MIN_COLUMN_WIDTH, width),
                }
            settings["columns"] = {
                column: values for column, values in columns.items()
            }
            for index in REQUIRED_COLUMN_INDEXES:
                settings["columns"][TABLE_COLUMNS[index]]["visible"] = True
            shared.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            shared.SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

        def show_column_menu(self, pos: QPoint) -> None:
            """Prave kliknuti na hlavicku sloupcu ukaze volbu viditelnosti."""
            menu = QMenu(self)
            header = self.table.horizontalHeader()
            for index, column in enumerate(TABLE_COLUMNS):
                action = QAction(column, menu)
                action.setCheckable(True)
                action.setChecked(not self.table.isColumnHidden(index))
                if index < 3:
                    action.setEnabled(False)
                else:
                    action.toggled.connect(lambda checked, col=index: self.set_column_visible(col, checked))
                menu.addAction(action)
            menu.exec(header.mapToGlobal(pos))

        def set_column_visible(self, column: int, visible: bool) -> None:
            """Zmeni viditelnost sloupce a hned ji ulozi."""
            if column in REQUIRED_COLUMN_INDEXES:
                return
            column_settings = normalize_column_settings(read_app_settings().get("columns")).get(TABLE_COLUMNS[column], {})
            previous_width = column_settings.get("width")
            if visible:
                self.table.setColumnHidden(column, False)
                if isinstance(previous_width, int):
                    self.table.setColumnWidth(column, previous_width)
                self.save_column_settings()
                return
            width = self.table.columnWidth(column)
            self.table.setColumnHidden(column, True)
            self.save_column_settings({column: width})

        def closeEvent(self, event: Any) -> None:
            """Pred zavrenim ulozi rozlozeni sloupcu."""
            self.save_column_settings()
            super().closeEvent(event)

        def _build_detail_panel(self) -> QWidget:
            panel = QWidget()
            panel.setMinimumWidth(320)
            panel.setMaximumWidth(460)
            layout = QVBoxLayout(panel)
            self.detail_tabs = QTabWidget()
            layout.addWidget(self.detail_tabs)

            current_tab = QWidget()
            current_layout = QVBoxLayout(current_tab)
            self.detail_title = QLabel("Bez vyberu")
            self.detail_title.setWordWrap(True)
            self.detail_author = QLabel("")
            self.detail_author.setWordWrap(True)
            current_layout.addWidget(self.detail_title)
            current_layout.addWidget(self.detail_author)
            current_layout.addStretch(1)
            self.detail_tabs.addTab(current_tab, "Aktualni data")

            review_tab = QWidget()
            review_layout = QVBoxLayout(review_tab)
            status_buttons = QHBoxLayout()
            self.approve_button = self._add_button(
                status_buttons, "Approve", lambda: self.set_selected_status("approve"), "approveButton"
            )
            self.review_button = self._add_button(
                status_buttons, "Review", lambda: self.set_selected_status("review"), "reviewButton"
            )
            self.skip_button = self._add_button(status_buttons, "Skip", lambda: self.set_selected_status("skip"), "skipButton")
            self.story_button = self._add_button(status_buttons, "Povidka", self.mark_selected_story, "storyButton")
            for index, button in enumerate((self.approve_button, self.review_button, self.skip_button, self.story_button)):
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                status_buttons.setStretch(index, 1)
            review_layout.addLayout(status_buttons)

            review_layout.addWidget(QLabel("Odkaz"))
            self.url_edit = QLineEdit()
            self.url_edit.setClearButtonEnabled(True)
            self.url_edit.textChanged.connect(self.update_link_buttons)
            review_layout.addWidget(self.url_edit)
            url_buttons = QHBoxLayout()
            self.use_link_button = self._add_button(url_buttons, "Pouzit odkaz", self.apply_selected_url, "neutralButton")
            self.open_link_button = self._add_button(url_buttons, "Otevrit odkaz", self.open_selected_url, "neutralButton")
            self.use_link_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.open_link_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            url_buttons.setStretch(0, 1)
            url_buttons.setStretch(1, 1)
            review_layout.addLayout(url_buttons)

            self.cover_status = QLabel("Bez obalky")
            self.cover_status.setObjectName("coverStatus")
            self.cover_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cover_image = QLabel("")
            self.cover_image.setObjectName("coverImage")
            self.cover_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cover_image.setFixedSize(150, 220)
            self.cover_image.setScaledContents(False)
            self.cover_source = QLabel("")
            self.cover_source.setWordWrap(True)
            self.cover_options_widget = QWidget()
            self.cover_options_layout = QGridLayout(self.cover_options_widget)
            self.cover_options_layout.setContentsMargins(0, 0, 0, 0)
            self.cover_options_layout.setHorizontalSpacing(6)
            self.cover_options_layout.setVerticalSpacing(6)
            review_layout.addWidget(self.cover_status)
            review_layout.addWidget(self.cover_image, alignment=Qt.AlignmentFlag.AlignHCenter)
            review_layout.addWidget(self.cover_source)
            review_layout.addWidget(self.cover_options_widget)
            review_layout.addStretch(1)
            self.detail_tabs.addTab(review_tab, "Review")

            self.log_tab = QWidget()
            log_layout = QVBoxLayout(self.log_tab)
            self.output = QTextEdit()
            self.output.setReadOnly(True)
            self.output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            log_layout.addWidget(self.output, stretch=1)
            self.detail_tabs.addTab(self.log_tab, "Log")
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

        def selected_rows(self) -> list[cme.MatchRow]:
            """Vrati vsechny vybrane radky v poradi podle ID."""
            rows: list[cme.MatchRow] = []
            for book_id in sorted(self.selected_book_ids()):
                index = shared.find_row_index(self.rows, book_id)
                if index is not None:
                    rows.append(self.rows[index])
            return rows

        def on_selection_changed(self) -> None:
            rows = self.selected_rows()
            self.detail_title.setText(selection_title(rows))
            self.detail_author.setText(rows[0].authors if len(rows) == 1 else "")
            link_text = selection_link_text(rows)
            if self.url_edit.text() != link_text:
                self.url_edit.setText(link_text)
            self.update_link_buttons()
            self.update_cover_preview(rows)

        def set_cover_placeholder(self, status: str, source: str = "") -> None:
            """Nastavi textovy stav nahledu obalky."""
            self.cover_status.setText(status)
            self.cover_source.setText(source)
            self.cover_image.clear()
            self.cover_image.setText("Bez nahledu")
            self.clear_cover_options()

        def set_cover_pixmap(self, status: str, image_bytes: bytes, source: str = "") -> None:
            """Zobrazi obrazek obalky v detailu."""
            pixmap = QPixmap()
            if not pixmap.loadFromData(image_bytes):
                self.set_cover_placeholder("Obalku nejde zobrazit", source)
                return
            scaled = pixmap.scaled(
                self.cover_image.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.cover_status.setText(status)
            self.cover_source.setText(source)
            self.cover_image.setText("")
            self.cover_image.setPixmap(scaled)

        def clear_cover_options(self) -> None:
            """Smaze mala tlacitka kandidatnich obalek."""
            self.cover_option_buttons = {}
            while self.cover_options_layout.count():
                item = self.cover_options_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        def cover_button_style(self, selected: bool) -> str:
            """Vrati jednoduchy ramecek pro vybranou obalku."""
            if selected:
                return "QToolButton { border: 2px solid #1565c0; background: #e3f2fd; }"
            return "QToolButton { border: 1px solid #bdbdbd; background: #eeeeee; }"

        def set_cover_button_image(self, button: QToolButton, image_bytes: bytes) -> bool:
            """Nastavi nahled do maleho tlacitka obalky."""
            pixmap = QPixmap()
            if not pixmap.loadFromData(image_bytes):
                return False
            button.setIcon(QIcon(pixmap))
            button.setIconSize(QSize(58, 82))
            button.setText("")
            return True

        def select_cover_candidate(self, book_id: int, cover_url: str) -> None:
            """Ulozi vybranou kandidatni obalku do CSV radku."""
            try:
                self.rows = shared.update_rows_selected_cover(self.rows, book_id, cover_url)
            except ValueError as exc:
                QMessageBox.warning(self, "Obalka", str(exc))
                return
            self.save_csv(show_message=False)
            self.refresh_table()
            self.update_cover_preview(self.selected_rows())

        def show_cover_options(self, row: cme.MatchRow, cover_urls: Sequence[str]) -> None:
            """Zobrazi grid kandidatnich obalek z matches.csv."""
            self.clear_cover_options()
            selected_url = row.selected_cover_url.strip()
            for index, cover_url in enumerate(cover_urls):
                button = QToolButton()
                button.setToolTip(cover_url)
                button.setText(str(index + 1))
                button.setFixedSize(70, 96)
                button.setStyleSheet(self.cover_button_style(cover_url == selected_url))
                button.clicked.connect(lambda _checked=False, url=cover_url, book_id=row.book_id: self.select_cover_candidate(book_id, url))
                self.cover_option_buttons[cover_url] = button
                self.cover_options_layout.addWidget(button, index // 3, index % 3)
                cached = self.cover_preview_cache.get(cover_url)
                if cached:
                    self.set_cover_button_image(button, cached[1])
                else:
                    self.load_cover_url(cover_url)

        def load_cover_url(self, cover_url: str) -> None:
            """Stahne obrazek kandidata na pozadi."""
            request_id = self.cover_preview_request_id

            def worker() -> None:
                try:
                    image_bytes = cme.fetch_binary(cover_url)
                    self.bridge.cover_ready.emit(request_id, "Kandidat obalky", cover_url, cover_url, image_bytes)
                except Exception as exc:
                    self.bridge.cover_ready.emit(request_id, "Obalku nejde nacist", cover_url, str(exc), b"")

            threading.Thread(target=worker, daemon=True).start()

        def update_cover_preview(self, rows: Sequence[cme.MatchRow]) -> None:
            """Ukaze lokalni obalku, nebo kandidatni obalky z matches.csv."""
            self.cover_preview_request_id += 1
            self.clear_cover_options()
            if not rows:
                self.set_cover_placeholder("Bez vyberu")
                return
            if len(rows) > 1:
                self.set_cover_placeholder(f"Vybrano {len(rows)} knih")
                return
            row = rows[0]
            try:
                local_cover = cme.get_local_cover_path(self.library_path, row.book_id)
            except Exception as exc:
                self.set_cover_placeholder("Obalku nejde nacist", str(exc))
                return
            if local_cover is not None:
                try:
                    self.set_cover_pixmap("Obalka v Calibre", local_cover.read_bytes(), str(local_cover))
                except OSError as exc:
                    self.set_cover_placeholder("Obalku nejde nacist", str(exc))
                return
            cover_urls = shared.cover_urls_from_row(row)
            if not cover_urls:
                self.set_cover_placeholder("Bez obalky")
                return
            selected_url = row.selected_cover_url.strip()
            preview_url = selected_url or cover_urls[0]
            status = "Vybrana kandidatni obalka" if selected_url else "Kandidatni obalky - vyber jednu"
            cached = self.cover_preview_cache.get(preview_url)
            if cached:
                self.set_cover_pixmap(status, cached[1], preview_url)
            else:
                self.cover_status.setText(status + " - nacitam")
                self.cover_source.setText(preview_url)
                self.cover_image.clear()
                self.cover_image.setText("Nacitam")
                self.load_cover_url(preview_url)
            self.show_cover_options(row, cover_urls)

        def finish_cover_preview(self, request_id: int, label: str, cache_key: str, source: str, image_bytes: bytes) -> None:
            """Prevezme nahled obalky z background threadu."""
            if request_id != self.cover_preview_request_id:
                return
            if not image_bytes:
                button = self.cover_option_buttons.get(cache_key)
                if button is not None:
                    button.setText("!")
                    button.setToolTip(source)
                    return
                self.set_cover_placeholder("Bez obalky", source)
                return
            self.cover_preview_cache[cache_key] = (source, image_bytes)
            button = self.cover_option_buttons.get(cache_key)
            if button is not None:
                self.set_cover_button_image(button, image_bytes)
            rows = self.selected_rows()
            if len(rows) == 1:
                cover_urls = shared.cover_urls_from_row(rows[0])
                selected_url = rows[0].selected_cover_url.strip() or (cover_urls[0] if cover_urls else "")
                if selected_url == cache_key:
                    self.set_cover_pixmap(label, image_bytes, source)

        def update_link_buttons(self) -> None:
            """Zapne link tlacitka podle vyberu a textu v poli Odkaz."""
            rows = self.selected_rows()
            link_text = self.url_edit.text()
            self.use_link_button.setEnabled(use_link_enabled(rows, link_text))
            self.open_link_button.setEnabled(open_link_enabled(rows, link_text))

        def set_selected_status(self, status: str) -> None:
            selected = self.selected_book_ids()
            if not selected:
                QMessageBox.information(self, "Vyber radek", "Nejdriv vyber knihu v tabulce.")
                return
            missing_cover = shared.rows_missing_cover_choice(self.rows, selected) if status == "approve" else []
            if missing_cover:
                titles = "\n".join(f"- {row.book_id} {row.title}" for row in missing_cover[:8])
                QMessageBox.information(self, "Vyber obalku", "Nejdriv vyber jednu obalku:\n" + titles)
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
            if self.url_edit.text().strip() == "Ruzne adresy":
                QMessageBox.information(self, "Odkaz", "Smaz text Ruzne adresy, nebo zadej konkretni odkaz.")
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
            action = self.make_preview_action(args)
            self.run_background(auto_workflow_title(self.auto_settings), action, reload_after=True)

        def run_update_selected(self) -> None:
            selected = self.selected_book_ids()
            if not selected:
                QMessageBox.information(self, "Vyber radek", "Nejdriv vyber knihu v tabulce.")
                return
            if not self.save_csv(show_message=False):
                return
            args = shared.make_script_args(self.library_path)
            args.book_ids = sorted(selected)
            action = self.make_preview_action(args)
            self.run_background("Update vybranych + " + auto_workflow_title(self.auto_settings), action, reload_after=True)

        def make_preview_action(self, args: Any) -> Callable[[], int]:
            """Sestavi preview workflow podle nastaveni automatickych auditu."""
            if self.auto_settings["auto_link_audit"] and self.auto_settings["auto_cover_audit"]:
                return shared.make_preview_with_audits_action(args, matches_path=self.matches_path)
            if self.auto_settings["auto_link_audit"]:
                return shared.make_preview_with_legie_audit_action(args, matches_path=self.matches_path)
            preview_action = lambda: cme.run_preview(args)
            if not self.auto_settings["auto_cover_audit"]:
                return preview_action
            cover_action = shared.make_cover_audit_action(args, matches_path=self.matches_path)
            return lambda: shared.run_preview_audit_then_cover_audit(
                preview_func=preview_action,
                link_audit_func=lambda: 0,
                cover_audit_func=cover_action,
            )

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

        def run_covers(self) -> None:
            selected = self.selected_book_ids()
            try:
                candidates = cme.cover_candidate_rows(self.rows, self.library_path, selected if selected else None)
            except Exception as exc:
                QMessageBox.warning(self, "Obalky", f"Nepodarilo se nacist stav obalek:\n{exc}")
                return
            confirmed, allow_force = self.ask_cover_confirmation(candidates, bool(selected))
            if not confirmed:
                return
            if not self.save_csv(show_message=False):
                return
            args = shared.make_cover_args(self.library_path, selected if selected else None)
            action = shared.make_cover_action(args=args, allow_force=allow_force)
            self.run_background("Doplneni obalek", action, reload_after=True)

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

        def ask_cover_confirmation(self, candidates: Sequence[cme.CoverCandidate], selected_only: bool) -> tuple[bool, bool]:
            if not candidates:
                QMessageBox.information(
                    self,
                    "Obalky",
                    "Neni co doplnovat.\nBeru jen knihy bez obalky, s odkazem na Databazi knih nebo Legii a mimo status review.",
                )
                return False, False
            shown = "\n".join(f"- {candidate.book_id} {candidate.title}" for candidate in candidates[:25])
            more = "" if len(candidates) <= 25 else f"\n... a dalsich {len(candidates) - 25}"
            scope = "vybranych knih" if selected_only else "celeho seznamu"
            box = QMessageBox(self)
            box.setWindowTitle("Doplnit obalky")
            box.setText(
                f"Appka doplni obalky pro {len(candidates)} knih z {scope}.\n"
                "Pouze tam, kde Calibre hlasi, ze obalka chybi.\n"
                "Pred zapisem vytvori zalohu metadata.db.\n\n"
                f"{shown}{more}"
            )
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
            self.set_ui_enabled(False)
            self.detail_tabs.setCurrentWidget(self.log_tab)
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
            self.set_ui_enabled(True)
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
                QPushButton, QToolButton { min-height: 30px; padding: 4px 8px; border-radius: 3px; }
                QToolButton { font-size: 8pt; }
                QToolButton[iconOnly="true"] {
                    min-width: 42px;
                    max-width: 42px;
                    min-height: 42px;
                    max-height: 42px;
                    padding: 0;
                }
                QPushButton#approveButton, QToolButton#approveButton { background: #2e7d32; color: white; }
                QPushButton#reviewButton, QToolButton#reviewButton { background: #ef6c00; color: white; }
                QPushButton#skipButton, QPushButton#neutralButton, QToolButton#skipButton, QToolButton#neutralButton { background: #757575; color: white; }
                QPushButton#storyButton, QPushButton#updateButton, QToolButton#storyButton, QToolButton#updateButton { background: #1565c0; color: white; }
                QPushButton#applyButton, QPushButton#dangerButton, QToolButton#applyButton, QToolButton#dangerButton { background: #c62828; color: white; }
                QPushButton:disabled, QToolButton:disabled { background: #bdbdbd; color: #eeeeee; }
                QLineEdit, QComboBox { min-height: 28px; }
                QLineEdit::clear-button { width: 22px; height: 22px; subcontrol-position: center right; }
                QLineEdit QToolButton {
                    color: #111111;
                    font-size: 15pt;
                    font-weight: 700;
                    min-width: 22px;
                    min-height: 22px;
                    padding: 0;
                    margin: 0 3px 0 0;
                }
                QLabel#coverStatus { font-weight: 700; padding: 4px; border-radius: 3px; background: #eeeeee; color: #111111; }
                QLabel#coverImage { border: 1px solid #b8b8b8; background: #fafafa; color: #777777; }
                QTableWidget { gridline-color: #b8b8b8; alternate-background-color: #f3f3f3; color: #111111; }
                QTableWidget::item { color: #111111; }
                QTableWidget::item:selected, QTableWidget::item:selected:!active {
                    background: #0d6efd;
                    color: #ffffff;
                }
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

        def set_ui_enabled(self, enabled: bool) -> None:
            """Pri background akci vypne ovladani, log zustava citelny."""
            self.table.setEnabled(enabled)
            self.title_filter.setEnabled(enabled)
            self.author_filter.setEnabled(enabled)
            for check in list(self.status_checks.values()) + list(self.source_checks.values()) + list(self.type_checks.values()):
                check.setEnabled(enabled)
            self.url_edit.setEnabled(enabled)
            self.detail_tabs.setTabEnabled(0, enabled)
            self.detail_tabs.setTabEnabled(1, enabled)
            self.detail_tabs.setTabEnabled(2, True)
            for button in self.buttons:
                button.setEnabled(enabled)
            for button in (self.approve_button, self.review_button, self.skip_button, self.story_button, self.use_link_button, self.open_link_button):
                button.setEnabled(enabled)
            if enabled:
                self.on_selection_changed()

        def write_output(self, text: str) -> None:
            self.output.setPlainText(text)

        def set_status(self, text: str) -> None:
            self.calibre_running = is_calibre_running()
            self.statusBar().showMessage(statusbar_text(text, self.calibre_running, self.csv_loaded))
            self.update_calibre_indicator()

        def refresh_calibre_indicator(self) -> None:
            """Timerem hlida, jestli se mezitim Calibre zapnulo nebo vypnulo."""
            self.calibre_running = is_calibre_running()
            self.update_calibre_indicator()

        def update_calibre_indicator(self) -> None:
            """Prekresli puntik Calibre ve statusbaru."""
            color = "#2e7d32" if self.calibre_running else "#c62828"
            label = "Calibre zapnuto" if self.calibre_running else "Calibre vypnuto"
            self.calibre_indicator.setText(f"<span style='color:{color}; font-size:16px;'>●</span> {label}")

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
