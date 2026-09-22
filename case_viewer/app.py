"""PySide6 desktop application for browsing revision 35 RAW files."""

from __future__ import annotations

import csv
from pathlib import Path
import re
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
        self.buses: dict[str, Record] = {}
        self.bus_boxes: list[tuple[QRect, str]] = []
        self.setMinimumHeight(320)
        self.setMouseTracking(True)

    def set_record(self, record: Record | None, buses: dict[str, Record] | None = None) -> None:
        self.record = record
        self.buses = buses or {}
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

    def _status(self, record: Record) -> tuple[str, bool]:
        for name in ("STAT", "STATUS", "ST"):
            value = record.value(name)
            if value:
                try:
                    numeric_status = int(float(value))
                except ValueError:
                    numeric_status = None
                if numeric_status == 0:
                    return "OUT OF SERVICE", False
                if numeric_status == 1:
                    return "IN SERVICE", True
                return f"STATUS {value}", True
        if record.section == "BUS":
            return "NETWORK NODE", True
        return "DATA RECORD", True

    def _shunt_susceptance(self, record: Record) -> float | None:
        if record.section == "FIXED SHUNT":
            candidates = (record.value("BL"),)
        elif record.section == "SWITCHED SHUNT":
            # Some revision 35 headers omit ID/NREG even when those fields are
            # present. N1 is therefore a useful fallback for the shifted BINIT.
            candidates = (record.value("BINIT"), record.value("N1"))
        else:
            return None
        for value in candidates:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _is_shunt_reactor(self, record: Record) -> bool:
        susceptance = self._shunt_susceptance(record)
        if susceptance is not None and susceptance != 0:
            return susceptance < 0
        steps = []
        for index in range(1, 9):
            try:
                steps.append(float(record.value(f"B{index}")))
            except (TypeError, ValueError):
                continue
        nonzero_steps = [value for value in steps if value]
        return bool(nonzero_steps) and max(nonzero_steps) < 0

    def _vector_connections(self, record: Record) -> list[tuple[str, bool]]:
        value = record.value("VECGRP").strip(" '\"")
        return [(kind.upper(), bool(neutral)) for kind, neutral in re.findall(r"([YyDd])([Nn]?)", value)]

    def _draw_vector_connections(self, painter: QPainter, record: Record, cx: int, cy: int, terminal_count: int) -> None:
        connections = self._vector_connections(record)
        if not connections:
            return
        connections = connections[:max(2, terminal_count)]
        spacing = 42
        group_width = len(connections) * spacing
        group_left = cx - group_width // 2
        start_x = group_left + spacing // 2
        symbol_y = cy - 54 if terminal_count == 3 else cy + 43
        background = QRect(group_left - 5, symbol_y - 14, group_width + 10, 28)
        painter.fillRect(background, QColor("#ffffff"))
        painter.setPen(QPen(QColor("#0f4c81"), 1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for index, (kind, neutral) in enumerate(connections):
            x = start_x + index * spacing
            if kind == "D":
                painter.drawLine(x, symbol_y - 10, x - 10, symbol_y + 8)
                painter.drawLine(x - 10, symbol_y + 8, x + 10, symbol_y + 8)
                painter.drawLine(x + 10, symbol_y + 8, x, symbol_y - 10)
            else:
                painter.drawLine(x, symbol_y, x - 10, symbol_y - 9)
                painter.drawLine(x, symbol_y, x + 10, symbol_y - 9)
                painter.drawLine(x, symbol_y, x, symbol_y + 11)
                if neutral:
                    painter.drawLine(x, symbol_y, x + 14, symbol_y)
                    painter.drawEllipse(QRect(x + 12, symbol_y - 2, 4, 4))

    def _summary(self, record: Record) -> str:
        specifications = {
            "BUS": (("BASKV", "Base", "kV"), ("VM", "V", "pu"), ("VA", "Angle", "deg")),
            "LOAD": (("PL", "P", "MW"), ("QL", "Q", "Mvar")),
            "GENERATOR": (("PG", "P", "MW"), ("QG", "Q", "Mvar"), ("MBASE", "Base", "MVA")),
            "BRANCH": (("R", "R", "pu"), ("X", "X", "pu"), ("RATE1", "Rate A", "MVA")),
            "TRANSFORMER": (("R1-2", "R1-2", "pu"), ("X1-2", "X1-2", "pu"), ("SBASE1-2", "Base", "MVA")),
            "SYSTEM SWITCHING DEVICE": (("X", "X", "pu"), ("RATE1", "Rate A", "MVA")),
            "FIXED SHUNT": (("GL", "G", "MW"), ("BL", "B", "Mvar")),
            "SWITCHED SHUNT": (("BINIT", "B init", "Mvar"),),
            "INDUCTION MACHINE": (("PSET", "P", "MW"), ("MBASE", "Base", "MVA")),
            "FACTS DEVICE": (("PDES", "P set", "MW"), ("QDES", "Q set", "Mvar"), ("MODE", "Mode", "")),
        }.get(record.section, (("MDC", "Mode", ""), ("RATE1", "Rate A", "MVA")))
        values = []
        if record.section in {"FIXED SHUNT", "SWITCHED SHUNT"}:
            values.append("Shunt reactor" if self._is_shunt_reactor(record) else "Shunt capacitor")
        for field, label, unit in specifications:
            value = record.value(field)
            if value:
                values.append(f"{label} {value}{f' {unit}' if unit else ''}")
        return "    |    ".join(values[:4]) or "No operating values reported"

    def _bus_detail(self, number: str) -> tuple[str, str]:
        bus = self.buses.get(number)
        if bus is None:
            return "", ""
        return bus.value("NAME").strip(" '\"")[:16], bus.value("BASKV")

    def _draw_bus(self, painter: QPainter, x: int, y: int, number: str, orientation: str) -> None:
        name, base_kv = self._bus_detail(number)
        painter.setPen(QPen(QColor("#172033"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
        if orientation.startswith("horizontal"):
            painter.drawLine(x - 46, y, x + 46, y)
            if orientation == "horizontal-below":
                label_rect = QRect(x - 72, y + 10, 144, 56)
                hit_box = QRect(x - 74, y - 10, 148, 78)
            else:
                label_rect = QRect(x - 72, y - 66, 144, 56)
                hit_box = QRect(x - 74, y - 68, 148, 78)
        else:
            painter.drawLine(x, y - 34, x, y + 34)
            label_rect = QRect(x - 69, y + 40, 138, 58)
            hit_box = QRect(x - 72, y - 38, 144, 138)
        painter.setPen(QColor("#334155"))
        label_font = QFont()
        label_font.setPointSize(8)
        painter.setFont(label_font)
        label = f"BUS {number}"
        if name:
            label += f"\n{name}"
        if base_kv:
            label += f"\n{base_kv} kV"
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, label)
        self.bus_boxes.append((hit_box, number))

    def _draw_symbol(self, painter: QPainter, record: Record, cx: int, cy: int, active: bool) -> None:
        kind = record.section
        symbol = QColor("#0f4c81") if active else QColor("#94a3b8")
        painter.setPen(QPen(symbol, 2.4))
        painter.setBrush(QColor("#ffffff"))
        if kind in {"GENERATOR", "INDUCTION MACHINE"}:
            painter.drawEllipse(QRect(cx - 29, cy - 29, 58, 58))
            font = painter.font()
            font.setPointSize(13)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(QRect(cx - 24, cy - 23, 48, 46), Qt.AlignmentFlag.AlignCenter, "G" if kind == "GENERATOR" else "M")
        elif kind == "TRANSFORMER":
            painter.fillRect(QRect(cx - 40, cy - 29, 80, 82 if len(self._terminals(record)) == 3 else 58), QColor("#ffffff"))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRect(cx - 34, cy - 25, 43, 50))
            painter.drawEllipse(QRect(cx - 9, cy - 25, 43, 50))
            if len(self._terminals(record)) == 3:
                painter.drawEllipse(QRect(cx - 21, cy + 1, 42, 48))
        elif kind in {"BRANCH", "MULTI-SECTION LINE", "BUS"}:
            return
        elif kind == "SYSTEM SWITCHING DEVICE":
            painter.setBrush(symbol)
            painter.drawEllipse(QRect(cx - 31, cy - 4, 8, 8))
            painter.drawEllipse(QRect(cx + 23, cy - 4, 8, 8))
            painter.drawLine(cx - 23, cy, cx + 23, cy if active else cy - 18)
        elif kind in {"FIXED SHUNT", "SWITCHED SHUNT"}:
            painter.fillRect(QRect(cx - 22, cy - 31, 44, 65), QColor("#ffffff"))
            if self._is_shunt_reactor(record):
                painter.drawLine(cx, cy - 30, cx, cy - 21)
                for offset in (-21, -11, -1, 9):
                    painter.drawArc(QRect(cx - 8, cy + offset, 16, 12), 90 * 16, -180 * 16)
                painter.drawLine(cx, cy + 21, cx, cy + 23)
            else:
                painter.drawLine(cx - 19, cy - 7, cx + 19, cy - 7)
                painter.drawLine(cx - 19, cy + 4, cx + 19, cy + 4)
                painter.drawLine(cx, cy - 30, cx, cy - 7)
                painter.drawLine(cx, cy + 4, cx, cy + 23)
            painter.drawLine(cx - 13, cy + 23, cx + 13, cy + 23)
            painter.drawLine(cx - 8, cy + 29, cx + 8, cy + 29)
        elif kind == "LOAD":
            painter.drawLine(cx, cy - 30, cx, cy + 10)
            painter.drawLine(cx, cy + 10, cx - 12, cy - 3)
            painter.drawLine(cx, cy + 10, cx + 12, cy - 3)
        elif kind in {"TWO-TERMINAL DC", "VSC DC LINE", "MULTI-TERMINAL DC"}:
            device = QRect(cx - 30, cy - 22, 60, 44)
            painter.drawRoundedRect(device, 3, 3)
            painter.drawText(device, Qt.AlignmentFlag.AlignCenter, "DC")
        elif kind == "FACTS DEVICE":
            device = QRect(cx - 38, cy - 23, 76, 46)
            painter.drawRoundedRect(device, 3, 3)
            painter.drawText(device, Qt.AlignmentFlag.AlignCenter, "FACTS")
        else:
            device = QRect(cx - 45, cy - 25, 90, 50)
            painter.drawRoundedRect(device, 4, 4)
            painter.drawText(device, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, kind.replace(" DEVICE", ""))

    def _symbol_anchor(self, record: Record, cx: int, cy: int, terminal_x: int, terminal_y: int) -> tuple[int, int]:
        kind = record.section
        if kind == "TRANSFORMER":
            if terminal_y > cy + 25:
                return cx, cy + 49
            return (cx - 35, cy) if terminal_x < cx else (cx + 35, cy)
        if kind in {"GENERATOR", "INDUCTION MACHINE"}:
            return cx, cy - 30
        if kind in {"LOAD", "FIXED SHUNT", "SWITCHED SHUNT"}:
            return cx, cy - 31
        if kind == "SYSTEM SWITCHING DEVICE":
            return (cx - 31, cy) if terminal_x < cx else (cx + 31, cy)
        if kind in {"TWO-TERMINAL DC", "VSC DC LINE", "MULTI-TERMINAL DC"}:
            if terminal_y > cy + 25:
                return cx, cy + 23
            return (cx - 31, cy) if terminal_x < cx else (cx + 31, cy)
        if kind == "FACTS DEVICE":
            return (cx - 39, cy) if terminal_x < cx else (cx + 39, cy)
        if kind not in {"BRANCH", "MULTI-SECTION LINE", "BUS"}:
            if terminal_y < cy:
                return cx, cy - 26
            if terminal_y > cy:
                return cx, cy + 26
            return (cx - 46, cy) if terminal_x < cx else (cx + 46, cy)
        return cx, cy

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        self.bus_boxes.clear()
        record = self.record
        if record is None:
            painter.setPen(QColor("#64748b"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Select a record to inspect its single-line representation")
            return
        w, h = self.width(), self.height()
        for x in range(16, w, 24):
            for y in range(76, max(76, h - 60), 24):
                painter.setPen(QColor("#edf1f5"))
                painter.drawPoint(x, y)

        painter.setPen(QColor("#64748b"))
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRect(18, 10, w - 150, 18), Qt.AlignmentFlag.AlignLeft, record.section.upper())
        painter.setPen(QColor("#172033"))
        font.setPointSize(12)
        painter.setFont(font)
        painter.drawText(QRect(18, 29, w - 150, 28), Qt.AlignmentFlag.AlignLeft, record.identity)
        status, active = self._status(record)
        badge = QRect(max(18, w - 132), 18, 112, 28)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#dcfce7") if active else QColor("#f1f5f9"))
        painter.drawRoundedRect(badge, 4, 4)
        painter.setPen(QColor("#166534") if active else QColor("#64748b"))
        status_font = QFont()
        status_font.setPointSize(7)
        status_font.setBold(True)
        painter.setFont(status_font)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, status)
        painter.setPen(QPen(QColor("#e2e8f0"), 1))
        painter.drawLine(0, 64, w, 64)

        terminals = self._terminals(record)
        if not terminals:
            painter.setFont(QFont())
            painter.setPen(QColor("#64748b"))
            painter.drawText(QRect(24, 76, w - 48, h - 142), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "No bus terminals are defined for this record.\nReview the Fields and Source tabs for its complete data.")
            self._draw_footer(painter, record, w, h)
            return

        cy = max(150, (64 + h - 58) // 2)
        cx = w // 2
        terminals_layout: list[tuple[int, int, str]] = []
        if len(terminals) == 1:
            if record.section == "BUS":
                terminals_layout = [(cx, cy, "horizontal")]
            else:
                terminals_layout = [(cx, cy - 74, "horizontal")]
        elif len(terminals) == 2:
            terminals_layout = [(max(74, cx - 142), cy, "vertical"), (min(w - 74, cx + 142), cy, "vertical")]
        elif len(terminals) == 3:
            terminals_layout = [(max(74, cx - 142), cy - 18, "vertical"), (min(w - 74, cx + 142), cy - 18, "vertical"), (cx, min(h - 128, cy + 98), "horizontal-below")]
        else:
            radius = min(142, max(88, w // 3))
            terminals_layout = [(cx - radius, cy, "vertical"), (cx + radius, cy, "vertical")]
            terminals_layout.extend((cx + (i % 3 - 1) * 100, min(h - 128, cy + 96 + (i // 3) * 58), "horizontal-below") for i in range(len(terminals) - 2))

        line_color = QColor("#475569") if active else QColor("#94a3b8")
        line_style = Qt.PenStyle.SolidLine if active else Qt.PenStyle.DashLine
        painter.setPen(QPen(line_color, 2, line_style))
        if record.section != "BUS":
            for x, y, orientation in terminals_layout:
                anchor_x, anchor_y = self._symbol_anchor(record, cx, cy, x, y)
                if orientation == "vertical":
                    painter.drawLine(anchor_x, anchor_y, x, y)
                else:
                    painter.drawLine(anchor_x, anchor_y, x, y)

        self._draw_symbol(painter, record, cx, cy, active)
        if record.section == "TRANSFORMER":
            self._draw_vector_connections(painter, record, cx, cy, len(terminals))
        painter.setFont(QFont())
        for (x, y, orientation), bus in zip(terminals_layout, terminals):
            self._draw_bus(painter, x, y, bus, orientation)
        if record.section in {"BRANCH", "MULTI-SECTION LINE"}:
            painter.setPen(QColor("#64748b"))
            painter.drawText(QRect(cx - 55, cy - 30, 110, 20), Qt.AlignmentFlag.AlignCenter, "AC LINE")
        self._draw_footer(painter, record, w, h)

    def _draw_footer(self, painter: QPainter, record: Record, w: int, h: int) -> None:
        footer = QRect(0, h - 54, w, 54)
        painter.setPen(QPen(QColor("#e2e8f0"), 1))
        painter.setBrush(QColor("#f8fafc"))
        painter.drawRect(footer)
        painter.setPen(QColor("#334155"))
        footer_font = QFont()
        footer_font.setPointSize(8)
        painter.setFont(footer_font)
        painter.drawText(QRect(16, h - 43, w - 32, 30), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._summary(record))

    def mousePressEvent(self, event) -> None:
        for box, bus in self.bus_boxes:
            if box.contains(event.position().toPoint()):
                self.bus_clicked.emit(bus)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        over_bus = any(box.contains(event.position().toPoint()) for box, _ in self.bus_boxes)
        self.setCursor(Qt.CursorShape.PointingHandCursor if over_bus else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)


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
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)
        eyebrow = QLabel("POWER SYSTEM DATA WORKBENCH")
        eyebrow.setObjectName("eyebrow")
        outer.addWidget(eyebrow)
        self.heading = QLabel("Open a revision 35 RAW case to begin")
        self.heading.setObjectName("pageTitle")
        outer.addWidget(self.heading)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        outer.addWidget(self.progress)
        split = QSplitter()
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)

        section_panel = QWidget()
        section_panel.setObjectName("panel")
        section_layout = QVBoxLayout(section_panel)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(0)
        section_label = QLabel("CASE SECTIONS")
        section_label.setObjectName("panelTitle")
        section_layout.addWidget(section_label)
        self.sections = QListWidget()
        self.sections.setMinimumWidth(220)
        self.sections.setSpacing(1)
        self.sections.currentRowChanged.connect(self.select_section)
        section_layout.addWidget(self.sections, 1)
        split.addWidget(section_panel)

        center = QWidget()
        center.setObjectName("panel")
        middle = QVBoxLayout(center)
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        records_label = QLabel("RECORDS")
        records_label.setObjectName("panelTitle")
        middle.addWidget(records_label)
        controls_widget = QWidget()
        controls_widget.setObjectName("toolbar")
        controls = QHBoxLayout()
        controls_widget.setLayout(controls)
        controls.setContentsMargins(10, 8, 10, 8)
        controls.setSpacing(8)
        self.field_filter = QComboBox()
        self.field_filter.setMinimumWidth(145)
        self.field_filter.addItem("All fields")
        self.field_filter.currentIndexChanged.connect(self.apply_search)
        controls.addWidget(self.field_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search records…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_search)
        controls.addWidget(self.search, 1)
        middle.addWidget(controls_widget)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(115)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(29)
        self.table.selectionModel().currentRowChanged.connect(self.select_record)
        middle.addWidget(self.table, 1)
        split.addWidget(center)

        inspector = QWidget()
        inspector.setObjectName("panel")
        inspector_layout = QVBoxLayout(inspector)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setSpacing(0)
        inspector_label = QLabel("RECORD INSPECTOR")
        inspector_label.setObjectName("panelTitle")
        inspector_layout.addWidget(inspector_label)
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(330)
        self.fields = QTableView()
        self.fields.setAlternatingRowColors(True)
        self.fields.setShowGrid(False)
        self.fields.verticalHeader().setDefaultSectionSize(28)
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
        inspector_layout.addWidget(self.tabs, 1)
        split.addWidget(inspector)
        split.setSizes([240, 850, 410])
        self.statusBar().showMessage("Ready")
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #eef2f6;
                color: #172033;
                font-family: "Segoe UI", "Inter", sans-serif;
                font-size: 10pt;
            }
            QLabel#eyebrow {
                color: #0f4c81;
                font-size: 8pt;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#pageTitle {
                color: #172033;
                font-size: 17pt;
                font-weight: 600;
                padding-bottom: 2px;
            }
            QWidget#panel {
                background: #ffffff;
                border: 1px solid #d8e0e8;
                border-radius: 6px;
            }
            QLabel#panelTitle {
                background: #f7f9fb;
                color: #536174;
                border: none;
                border-bottom: 1px solid #d8e0e8;
                padding: 10px 12px 8px 12px;
                font-size: 8pt;
                font-weight: 700;
                letter-spacing: 0.7px;
            }
            QWidget#toolbar {
                background: #ffffff;
                border: none;
                border-bottom: 1px solid #e5eaf0;
            }
            QTableView, QListWidget, QPlainTextEdit {
                background: #ffffff;
                color: #172033;
                border: none;
                outline: none;
                selection-background-color: #dbeafe;
                selection-color: #172033;
            }
            QTableView { gridline-color: #e8edf2; }
            QTableView::item {
                color: #172033;
                padding: 4px 7px;
                border-bottom: 1px solid #edf1f5;
            }
            QTableView::item:alternate { background: #f8fafc; }
            QTableView::item:selected, QListWidget::item:selected {
                background: #dbeafe;
                color: #12345b;
            }
            QListWidget::item {
                padding: 8px 11px;
                border-left: 3px solid transparent;
            }
            QListWidget::item:hover { background: #f1f5f9; }
            QListWidget::item:selected {
                border-left: 3px solid #0f6cbd;
                font-weight: 600;
            }
            QHeaderView::section {
                background: #f7f9fb;
                color: #536174;
                border: none;
                border-right: 1px solid #e2e8f0;
                border-bottom: 1px solid #d8e0e8;
                padding: 7px;
                font-size: 8pt;
                font-weight: 700;
            }
            QLineEdit, QComboBox {
                background: #ffffff;
                color: #172033;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 6px 8px;
                min-height: 18px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #0f6cbd;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QTabWidget::pane {
                background: #ffffff;
                border: none;
                border-top: 1px solid #d8e0e8;
            }
            QTabBar::tab {
                background: #f7f9fb;
                color: #536174;
                border: none;
                border-bottom: 2px solid transparent;
                padding: 9px 13px;
                font-weight: 600;
            }
            QTabBar::tab:hover { color: #0f4c81; }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #0f4c81;
                border-bottom: 2px solid #0f6cbd;
            }
            QMenuBar {
                background: #ffffff;
                color: #172033;
                border-bottom: 1px solid #d8e0e8;
            }
            QMenuBar::item { padding: 6px 10px; }
            QMenuBar::item:selected, QMenu::item:selected { background: #dbeafe; }
            QMenu { background: #ffffff; color: #172033; border: 1px solid #cbd5e1; }
            QMenu::item { padding: 6px 28px 6px 12px; }
            QStatusBar {
                background: #ffffff;
                color: #536174;
                border-top: 1px solid #d8e0e8;
            }
            QSplitter::handle { background: #d8e0e8; margin: 0 4px; }
            QSplitter::handle:horizontal { width: 1px; }
            QProgressBar {
                background: #dbe3eb;
                border: none;
                border-radius: 2px;
                height: 4px;
                text-align: center;
            }
            QProgressBar::chunk { background: #0f6cbd; border-radius: 2px; }
            QScrollBar:vertical { background: #f7f9fb; width: 11px; margin: 0; }
            QScrollBar::handle:vertical { background: #c5cfda; border-radius: 4px; min-height: 28px; margin: 2px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
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
        self.diagram.set_record(record, self.case.buses if self.case else None)
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
