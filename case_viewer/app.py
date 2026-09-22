"""PySide6 desktop application for browsing revision 35 RAW files."""

from __future__ import annotations

import csv
from pathlib import Path
import sys

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QRect, QSortFilterProxyModel, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QSplitter,
    QTabWidget, QTableView, QVBoxLayout, QWidget, QLineEdit,
    QComboBox, QProgressBar,
)

from .raw import Case, Record, parse_file


class RecordTable(QAbstractTableModel):
    def __init__(self, records: list[Record], parent: QObject | None = None):
        super().__init__(parent)
        self.records = records
        self.columns = ["Record", "Line"]
        seen = set(self.columns)
        for record in records:
            for name, _ in record.fields:
                if name not in seen:
                    self.columns.append(name)
                    seen.add(name)
        self.lookup = [{name: value for name, value in record.fields} for record in records]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section] if orientation == Qt.Orientation.Horizontal else section + 1
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.UserRole, Qt.ItemDataRole.ToolTipRole):
            return None
        row, col = index.row(), index.column()
        if col == 0:
            return self.records[row].identity
        if col == 1:
            return self.records[row].line
        return self.lookup[row].get(self.columns[col], "")


class SearchProxy(QSortFilterProxyModel):
    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.query = ""
        self.field = -1

    def set_search(self, query: str, field: int) -> None:
        modern_filter_api = hasattr(self, "beginFilterChange")
        if modern_filter_api:
            self.beginFilterChange()
        self.query = query.casefold().strip()
        self.field = field
        if modern_filter_api:
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self.query:
            return True
        model = self.sourceModel()
        columns = range(model.columnCount()) if self.field < 0 else (self.field,)
        return any(self.query in str(model.data(model.index(source_row, col))).casefold() for col in columns)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        a = str(self.sourceModel().data(left) or "")
        b = str(self.sourceModel().data(right) or "")
        try:
            return float(a) < float(b)
        except ValueError:
            return a.casefold() < b.casefold()


class ParseWorker(QObject):
    loaded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    @Slot()
    def run(self) -> None:
        try:
            self.loaded.emit(parse_file(self.path))
        except (OSError, ValueError) as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class EquipmentDiagram(QWidget):
    bus_clicked = Signal(str)

    def __init__(self):
        super().__init__()
        self.record: Record | None = None
        self.bus_boxes: list[tuple[QRect, str]] = []
        self.setMinimumHeight(270)
        self.setMouseTracking(True)

    def set_record(self, record: Record | None) -> None:
        self.record = record
        self.update()

    def _terminals(self, record: Record) -> list[str]:
        first = record.groups[0] if record.groups else []
        kind = record.section
        if kind in {"BRANCH", "SYSTEM SWITCHING DEVICE", "MULTI-SECTION LINE", "TRANSFORMER"}:
            count = 3 if kind == "TRANSFORMER" and len(first) > 2 and first[2] not in {"", "0"} else 2
            return [v for v in first[:count] if v and v != "0"]
        if kind in {"BUS", "LOAD", "FIXED SHUNT", "GENERATOR", "SWITCHED SHUNT", "INDUCTION MACHINE"}:
            return first[:1]
        if kind == "FACTS DEVICE":
            return [v for v in first[1:3] if v and v != "0"]
        if kind == "TWO-TERMINAL DC" and len(record.groups) >= 3:
            return [record.groups[i][0] for i in (1, 2) if record.groups[i]]
        if kind == "VSC DC LINE" and len(record.groups) >= 3:
            return [record.groups[i][0] for i in (1, 2) if record.groups[i]]
        if kind == "GEN DEVICE":
            try:
                count = int(first[2])
                return first[3 : 3 + count]
            except (IndexError, ValueError):
                return []
        if kind == "MULTI-TERMINAL DC":
            try:
                count = int(first[1])
                return [group[0] for group in record.groups[1 : 1 + count] if group]
            except (IndexError, ValueError):
                return []
        return []

    def _summary(self, record: Record) -> str:
        fields = {
            "BUS": ("BASKV", "VM", "VA", "IDE"),
            "LOAD": ("PL", "QL", "STAT"),
            "GENERATOR": ("PG", "QG", "STAT"),
            "BRANCH": ("R", "X", "RATE1", "STAT"),
            "TRANSFORMER": ("R1-2", "X1-2", "STAT"),
            "SYSTEM SWITCHING DEVICE": ("X", "RATE1", "STAT"),
            "FIXED SHUNT": ("GL", "BL", "STATUS"),
            "SWITCHED SHUNT": ("BINIT", "ST"),
            "INDUCTION MACHINE": ("MBASE", "PSET", "ST"),
            "FACTS DEVICE": ("PDES", "QDES", "MODE"),
        }.get(record.section, ("MDC", "STAT", "ST", "RATE1"))
        values = [f"{name} {value}" for name in fields if (value := record.value(name))]
        return "   ·   ".join(values[:4])

    def _draw_symbol(self, painter: QPainter, record: Record, cx: int, cy: int) -> None:
        kind = record.section
        painter.setPen(QPen(QColor("#0f766e"), 2))
        painter.setBrush(QColor("#ccfbf1"))
        if kind in {"GENERATOR", "INDUCTION MACHINE"}:
            painter.drawEllipse(QRect(cx - 31, cy - 31, 62, 62))
            painter.drawText(QRect(cx - 25, cy - 23, 50, 46), Qt.AlignmentFlag.AlignCenter, "G" if kind == "GENERATOR" else "M")
        elif kind == "TRANSFORMER":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRect(cx - 37, cy - 25, 45, 50))
            painter.drawEllipse(QRect(cx - 8, cy - 25, 45, 50))
        elif kind in {"BRANCH", "MULTI-SECTION LINE"}:
            painter.drawLine(cx - 48, cy, cx + 48, cy)
            painter.drawEllipse(QRect(cx - 5, cy - 5, 10, 10))
        elif kind == "SYSTEM SWITCHING DEVICE":
            painter.drawEllipse(QRect(cx - 34, cy - 5, 10, 10))
            painter.drawEllipse(QRect(cx + 24, cy - 5, 10, 10))
            painter.drawLine(cx - 24, cy - 2, cx + 20, cy - 20)
        elif kind in {"FIXED SHUNT", "SWITCHED SHUNT"}:
            painter.drawLine(cx - 20, cy - 10, cx + 20, cy - 10)
            painter.drawLine(cx - 20, cy + 1, cx + 20, cy + 1)
            painter.drawLine(cx, cy - 29, cx, cy - 10)
            painter.drawLine(cx, cy + 1, cx, cy + 24)
        elif kind == "LOAD":
            painter.drawLine(cx, cy - 30, cx, cy + 15)
            painter.drawLine(cx - 13, cy + 3, cx, cy + 19)
            painter.drawLine(cx + 13, cy + 3, cx, cy + 19)
        else:
            device = QRect(cx - 51, cy - 32, 102, 64)
            painter.drawRoundedRect(device, 9, 9)
            painter.setPen(QColor("#134e4a"))
            painter.drawText(device, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, kind.replace(" DEVICE", "").title())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f8fafc"))
        self.bus_boxes.clear()
        record = self.record
        if record is None:
            painter.setPen(QColor("#64748b"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Select a record")
            return
        w, h = self.width(), self.height()
        painter.setPen(QColor("#334155"))
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRect(16, 12, w - 32, 26), Qt.AlignmentFlag.AlignLeft, record.section.title())
        terminals = self._terminals(record)
        if not terminals:
            painter.setFont(QFont())
            painter.setPen(QColor("#64748b"))
            painter.drawText(QRect(16, 50, w - 32, h - 60), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "This record has no bus terminals to draw. Its full data is available on the Fields tab.")
            return
        cy = max(120, h // 2)
        cx = w // 2
        centers: list[tuple[int, int]] = []
        if len(terminals) == 1:
            centers = [(cx, cy + 75)]
        elif len(terminals) == 2:
            centers = [(max(62, cx - 130), cy), (min(w - 62, cx + 130), cy)]
        else:
            radius = min(130, max(72, w // 3))
            centers = [(cx - radius, cy), (cx + radius, cy)]
            centers.extend((cx + (i % 3 - 1) * 95, cy + 90 + (i // 3) * 54) for i in range(len(terminals) - 2))
        painter.setPen(QPen(QColor("#64748b"), 2))
        for x, y in centers:
            painter.drawLine(cx, cy, x, y)
        self._draw_symbol(painter, record, cx, cy)
        painter.setFont(QFont())
        for (x, y), bus in zip(centers, terminals):
            box = QRect(x - 47, y - 19, 94, 38)
            painter.setPen(QPen(QColor("#2563eb"), 1))
            painter.setBrush(QColor("#dbeafe"))
            painter.drawRoundedRect(box, 5, 5)
            painter.setPen(QColor("#1e3a8a"))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, f"Bus {bus}")
            self.bus_boxes.append((box, bus))
        painter.setPen(QColor("#475569"))
        summary = self._summary(record) or record.identity
        painter.drawText(QRect(16, h - 39, w - 32, 27), Qt.AlignmentFlag.AlignCenter, summary[:100])

    def mousePressEvent(self, event) -> None:
        for box, bus in self.bus_boxes:
            if box.contains(event.position().toPoint()):
                self.bus_clicked.emit(bus)
                return
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RAW Case Viewer")
        self.resize(1500, 850)
        self.setAcceptDrops(True)
        self.case: Case | None = None
        self.section = ""
        self.thread: QThread | None = None
        self.worker: ParseWorker | None = None
        self.table_model: RecordTable | None = None
        self.proxy = SearchProxy(self)
        self._build_ui()

    def _build_ui(self) -> None:
        menu = self.menuBar().addMenu("File")
        open_action = QAction("Open RAW…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.choose_file)
        menu.addAction(open_action)
        export_action = QAction("Export visible rows to CSV…", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.export_csv)
        menu.addAction(export_action)
        copy_action = QAction("Copy selected cells", self)
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        copy_action.triggered.connect(self.copy_selection)
        self.addAction(copy_action)
        menu.addAction(copy_action)
        menu.addSeparator()
        exit_action = QAction("Quit", self)
        exit_action.triggered.connect(self.close)
        menu.addAction(exit_action)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)
        self.heading = QLabel("Open a revision 35 RAW case to begin")
        self.heading.setStyleSheet("font-size: 17px; font-weight: 600; color: #0f172a; padding: 4px")
        outer.addWidget(self.heading)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        outer.addWidget(self.progress)
        split = QSplitter()
        outer.addWidget(split, 1)
        self.sections = QListWidget()
        self.sections.setMinimumWidth(220)
        self.sections.currentRowChanged.connect(self.select_section)
        split.addWidget(self.sections)

        center = QWidget()
        middle = QVBoxLayout(center)
        middle.setContentsMargins(4, 0, 4, 0)
        controls = QHBoxLayout()
        self.field_filter = QComboBox()
        self.field_filter.addItem("All fields")
        self.field_filter.currentIndexChanged.connect(self.apply_search)
        controls.addWidget(self.field_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search records…")
        self.search.textChanged.connect(self.apply_search)
        controls.addWidget(self.search, 1)
        middle.addLayout(controls)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(115)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.verticalHeader().setVisible(False)
        self.table.selectionModel().currentRowChanged.connect(self.select_record)
        middle.addWidget(self.table, 1)
        split.addWidget(center)

        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(330)
        self.fields = QTableView()
        self.fields.setAlternatingRowColors(True)
        self.tabs.addTab(self.fields, "Fields")
        self.diagram = EquipmentDiagram()
        self.diagram.bus_clicked.connect(self.go_to_bus)
        self.tabs.addTab(self.diagram, "Diagram")
        self.source = QPlainTextEdit()
        self.source.setReadOnly(True)
        self.tabs.addTab(self.source, "Source")
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.tabs.addTab(self.diagnostics, "Diagnostics")
        split.addWidget(self.tabs)
        split.setSizes([240, 850, 410])
        self.statusBar().showMessage("Ready")
        self.setStyleSheet("""
            QMainWindow { background: #f1f5f9; color: #0f172a; }
            QWidget { color: #0f172a; }
            QTableView, QListWidget, QPlainTextEdit, QLineEdit, QComboBox {
                background: #ffffff;
                color: #0f172a;
            }
            QTableView::item { color: #0f172a; }
            QTableView::item:alternate { background: #f8fafc; }
            QTableView::item:selected, QListWidget::item:selected {
                background: #bfdbfe;
                color: #0f172a;
            }
            QHeaderView::section {
                background: #e2e8f0;
                color: #0f172a;
                padding: 4px;
            }
            QMenuBar, QMenu, QStatusBar, QTabBar::tab {
                color: #0f172a;
            }
            QMenu { background: #ffffff; }
            QTabBar::tab { background: #e2e8f0; padding: 6px 10px; }
            QTabBar::tab:selected { background: #ffffff; }
        """)

    @Slot()
    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open RAW case", "", "RAW files (*.raw *.RAW);;All files (*)")
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> None:
        if self.thread is not None:
            return
        self.heading.setText(f"Loading {Path(path).name}…")
        self.progress.show()
        self.thread = QThread(self)
        self.worker = ParseWorker(path)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.loaded.connect(self._loaded)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._thread_done)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    @Slot()
    def _thread_done(self) -> None:
        self.thread = None
        self.worker = None
        self.progress.hide()

    @Slot(object)
    def _loaded(self, case: Case) -> None:
        self.case = case
        self.heading.setText(f"{Path(case.path).name}  ·  RAW {case.revision}  ·  {sum(map(len, case.sections.values())):,} records")
        self.sections.clear()
        for section, records in case.sections.items():
            self.sections.addItem(f"{section.title()}  ({len(records):,})")
        self.diagnostics.setPlainText("\n".join(f"Line {d.line}: {d.message}" for d in case.diagnostics) or "No parsing diagnostics.")
        self.sections.setCurrentRow(1 if len(case.sections) > 1 else 0)
        self.statusBar().showMessage(f"Opened {case.path}  ·  {len(case.diagnostics)} diagnostics")

    @Slot(str)
    def _failed(self, message: str) -> None:
        self.heading.setText("Open a revision 35 RAW case to begin" if not self.case else Path(self.case.path).name)
        QMessageBox.warning(self, "Could not open case", message)
        self.statusBar().showMessage(message)

    @Slot(int)
    def select_section(self, row: int) -> None:
        if self.case is None or row < 0:
            return
        self.section = list(self.case.sections)[row]
        old_model = self.table_model
        self.table_model = RecordTable(self.case.records(self.section), self)
        self.proxy.setSourceModel(self.table_model)
        if old_model is not None:
            old_model.deleteLater()
        self.field_filter.blockSignals(True)
        self.field_filter.clear()
        self.field_filter.addItem("All fields")
        self.field_filter.addItems(self.table_model.columns)
        self.field_filter.blockSignals(False)
        self.search.clear()
        self.table.resizeColumnToContents(0)
        if self.proxy.rowCount():
            self.table.selectRow(0)
            self.select_record(self.proxy.index(0, 0), QModelIndex())
        else:
            self._show_record(None)
        self.statusBar().showMessage(f"{self.section.title()}: {len(self.table_model.records):,} records")

    @Slot()
    def apply_search(self) -> None:
        self.proxy.set_search(self.search.text(), self.field_filter.currentIndex() - 1)
        self.statusBar().showMessage(f"{self.proxy.rowCount():,} of {self.table_model.rowCount() if self.table_model else 0:,} records shown")

    @Slot(QModelIndex, QModelIndex)
    def select_record(self, current: QModelIndex, previous: QModelIndex) -> None:
        if not current.isValid() or self.table_model is None:
            self._show_record(None)
            return
        source = self.proxy.mapToSource(current)
        self._show_record(self.table_model.records[source.row()])

    def _show_record(self, record: Record | None) -> None:
        self.diagram.set_record(record)
        old_model = self.fields.model()
        self.fields.setModel(FieldsTable(record, self))
        if old_model is not None:
            old_model.deleteLater()
        self.fields.horizontalHeader().setStretchLastSection(True)
        self.fields.resizeColumnToContents(0)
        self.source.setPlainText("\n".join(f"{record.line + i}: {line}" for i, line in enumerate(record.raw_lines)) if record else "")

    @Slot(str)
    def go_to_bus(self, number: str) -> None:
        if self.case is None:
            return
        bus = self.case.buses.get(number)
        if bus is None:
            self.statusBar().showMessage(f"Bus {number} is not present in this case")
            return
        section_index = list(self.case.sections).index("BUS")
        self.sections.setCurrentRow(section_index)
        row = self.case.records("BUS").index(bus)
        index = self.proxy.mapFromSource(self.table_model.index(row, 0))
        self.table.setCurrentIndex(index)
        self.table.scrollTo(index)

    @Slot()
    def export_csv(self) -> None:
        if self.table_model is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export visible rows", f"{self.section.lower().replace(' ', '_')}.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(self.table_model.columns)
                for row in range(self.proxy.rowCount()):
                    writer.writerow([self.proxy.data(self.proxy.index(row, col)) for col in range(self.proxy.columnCount())])
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self.statusBar().showMessage(f"Exported {self.proxy.rowCount():,} rows to {path}")

    @Slot()
    def copy_selection(self) -> None:
        view = self.fields if self.fields.hasFocus() else self.table
        indexes = view.selectedIndexes()
        if not indexes:
            return
        selected = {(index.row(), index.column()): str(index.data() or "") for index in indexes}
        rows = sorted({row for row, _ in selected})
        cols = sorted({col for _, col in selected})
        text = "\n".join("\t".join(selected.get((row, col), "") for col in cols) for row in rows)
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"Copied {len(rows)} row(s)")

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.open_file(paths[0])
            event.acceptProposedAction()

    def closeEvent(self, event) -> None:
        if self.thread is not None and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()
        super().closeEvent(event)


class FieldsTable(QAbstractTableModel):
    def __init__(self, record: Record | None, parent: QObject | None = None):
        super().__init__(parent)
        self.rows = record.fields if record else []
        if record and record.note:
            self.rows.append(("Comment", record.note))

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 2

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return ("Field", "Value")[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return self.rows[index.row()][index.column()]
        return None


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("RAW Case Viewer")
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        window.open_file(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
