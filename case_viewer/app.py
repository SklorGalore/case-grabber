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


class EquivalentCircuit(QWidget):
    """Detailed line and transformer steady-state equivalent circuits."""

    SUPPORTED_SECTIONS = {"BRANCH", "TRANSFORMER"}

    def __init__(self):
        super().__init__()
        self.record: Record | None = None
        self.buses: dict[str, Record] = {}
        self.system_base = 100.0
        self.setMinimumHeight(360)

    def set_record(self, record: Record | None, buses: dict[str, Record] | None = None, system_base: float = 100.0) -> None:
        self.record = record
        self.buses = buses or {}
        self.system_base = system_base
        self.update()

    @staticmethod
    def _float(value: str, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _fmt(value: float) -> str:
        if abs(value) < 1e-12:
            return "0"
        magnitude = abs(value)
        return f"{value:.6g}" if 1e-3 <= magnitude < 1e4 else f"{value:.4e}"

    def _complex(self, real: float, imag: float) -> str:
        sign = "+" if imag >= 0 else "−"
        return f"{self._fmt(real)} {sign} j{self._fmt(abs(imag))}"

    def _bus_label(self, number: str) -> str:
        bus = self.buses.get(number)
        if bus is None:
            return f"BUS {number}"
        name = bus.value("NAME").strip(" '\"")[:14]
        base = bus.value("BASKV")
        details = " · ".join(value for value in (name, f"{base} kV" if base else "") if value)
        return f"BUS {number}" + (f"\n{details}" if details else "")

    def _active(self, record: Record) -> bool:
        status = record.value("STAT") or record.value("STATUS") or record.value("ST")
        return self._float(status, 1.0) != 0

    def _draw_header(self, painter: QPainter, record: Record, width: int) -> None:
        painter.setPen(QColor("#64748b"))
        small = QFont()
        small.setPointSize(8)
        small.setBold(True)
        painter.setFont(small)
        subtype = "π-EQUIVALENT LINE MODEL" if record.section == "BRANCH" else "TRANSFORMER EQUIVALENT MODEL"
        painter.drawText(QRect(18, 10, width - 160, 18), Qt.AlignmentFlag.AlignLeft, subtype)
        painter.setPen(QColor("#172033"))
        title = QFont()
        title.setPointSize(12)
        title.setBold(True)
        painter.setFont(title)
        painter.drawText(QRect(18, 29, width - 160, 28), Qt.AlignmentFlag.AlignLeft, record.identity)
        active = self._active(record)
        badge = QRect(max(18, width - 132), 18, 112, 28)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#dcfce7") if active else QColor("#f1f5f9"))
        painter.drawRoundedRect(badge, 4, 4)
        painter.setPen(QColor("#166534") if active else QColor("#64748b"))
        badge_font = QFont()
        badge_font.setPointSize(7)
        badge_font.setBold(True)
        painter.setFont(badge_font)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "IN SERVICE" if active else "OUT OF SERVICE")
        painter.setPen(QPen(QColor("#e2e8f0"), 1))
        painter.drawLine(0, 64, width, 64)

    def _draw_bus(self, painter: QPainter, x: int, y: int, number: str, horizontal: bool = False) -> None:
        painter.setPen(QPen(QColor("#172033"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
        if horizontal:
            painter.drawLine(x - 38, y, x + 38, y)
            label_y = y + 10
        else:
            painter.drawLine(x, y - 31, x, y + 31)
            label_y = y - 82
        label_x = max(4, min(x - 68, self.width() - 140))
        label = QRect(label_x, label_y, 136, 45)
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(QColor("#334155"))
        painter.drawText(label, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._bus_label(number))

    def _draw_ground(self, painter: QPainter, x: int, y: int) -> None:
        painter.drawLine(x - 12, y, x + 12, y)
        painter.drawLine(x - 8, y + 5, x + 8, y + 5)
        painter.drawLine(x - 4, y + 10, x + 4, y + 10)

    def _draw_resistor(self, painter: QPainter, x1: int, x2: int, y: int) -> None:
        lead = max(5, (x2 - x1) // 8)
        painter.drawLine(x1, y, x1 + lead, y)
        points = [(x1 + lead, y)]
        usable = x2 - x1 - 2 * lead
        for index in range(1, 8):
            x = x1 + lead + round(usable * index / 8)
            points.append((x, y + (-7 if index % 2 else 7)))
        points.append((x2 - lead, y))
        for start, end in zip(points, points[1:]):
            painter.drawLine(start[0], start[1], end[0], end[1])
        painter.drawLine(x2 - lead, y, x2, y)

    def _draw_inductor(self, painter: QPainter, x1: int, x2: int, y: int) -> None:
        painter.drawLine(x1, y, x1 + 5, y)
        width = max(8, (x2 - x1 - 10) // 4)
        start = x1 + 5
        for index in range(4):
            painter.drawArc(QRect(start + index * width, y - 8, width + 2, 16), 0, 180 * 16)
        painter.drawLine(start + 4 * width, y, x2, y)

    def _draw_vertical_resistor(self, painter: QPainter, x: int, y1: int, y2: int) -> None:
        lead = max(4, (y2 - y1) // 8)
        painter.drawLine(x, y1, x, y1 + lead)
        points = [(x, y1 + lead)]
        usable = y2 - y1 - 2 * lead
        for index in range(1, 8):
            y = y1 + lead + round(usable * index / 8)
            points.append((x + (-6 if index % 2 else 6), y))
        points.append((x, y2 - lead))
        for start, end in zip(points, points[1:]):
            painter.drawLine(start[0], start[1], end[0], end[1])
        painter.drawLine(x, y2 - lead, x, y2)

    def _draw_vertical_inductor(self, painter: QPainter, x: int, y1: int, y2: int) -> None:
        painter.drawLine(x, y1, x, y1 + 5)
        height = max(8, (y2 - y1 - 10) // 4)
        start = y1 + 5
        for index in range(4):
            painter.drawArc(QRect(x - 8, start + index * height, 16, height + 2), 90 * 16, -180 * 16)
        painter.drawLine(x, start + 4 * height, x, y2)

    def _draw_shunt(self, painter: QPainter, x: int, y1: int, y2: int, reactor: bool = False) -> None:
        plate_y = y1 + (y2 - y1) // 2
        if reactor:
            self._draw_vertical_inductor(painter, x, y1, y2)
        else:
            painter.drawLine(x, y1, x, plate_y - 6)
            painter.drawLine(x - 12, plate_y - 6, x + 12, plate_y - 6)
            painter.drawLine(x - 12, plate_y + 3, x + 12, plate_y + 3)
            painter.drawLine(x, plate_y + 3, x, y2)
        self._draw_ground(painter, x, y2)

    def _draw_note(self, painter: QPainter, rect: QRect, title: str, value: str) -> None:
        painter.setPen(QPen(QColor("#d8e0e8"), 1))
        painter.setBrush(QColor("#f8fafc"))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor("#64748b"))
        title_font = QFont()
        title_font.setPointSize(7)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(QRect(rect.x() + 7, rect.y() + 5, rect.width() - 14, 13), Qt.AlignmentFlag.AlignLeft, title)
        painter.setPen(QColor("#172033"))
        value_font = QFont()
        value_font.setPointSize(8)
        painter.setFont(value_font)
        painter.drawText(QRect(rect.x() + 7, rect.y() + 18, rect.width() - 14, rect.height() - 21), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, value)

    def _draw_branch(self, painter: QPainter, record: Record, width: int, height: int) -> None:
        first = record.groups[0] if record.groups else []
        bus_i = first[0] if first else "I"
        bus_j = first[1] if len(first) > 1 else "J"
        r = self._float(record.value("R"))
        x = self._float(record.value("X"))
        b = self._float(record.value("B"))
        gi, bi = self._float(record.value("GI")), self._float(record.value("BI"))
        gj, bj = self._float(record.value("GJ")), self._float(record.value("BJ"))
        y = max(145, min(190, height // 3))
        left, right = 38, width - 38
        span = right - left
        r1, r2 = left + round(span * .17), left + round(span * .39)
        x1, x2 = left + round(span * .55), left + round(span * .78)
        pen = QPen(QColor("#0f4c81") if self._active(record) else QColor("#94a3b8"), 2)
        if not self._active(record):
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(left, y, r1, y)
        self._draw_resistor(painter, r1, r2, y)
        painter.drawLine(r2, y, x1, y)
        self._draw_inductor(painter, x1, x2, y)
        painter.drawLine(x2, y, right, y)
        painter.setPen(QColor("#334155"))
        label_font = QFont()
        label_font.setPointSize(8)
        label_font.setBold(True)
        painter.setFont(label_font)
        painter.drawText(QRect(r1 - 15, y - 36, r2 - r1 + 30, 22), Qt.AlignmentFlag.AlignCenter, f"R = {self._fmt(r)} pu")
        painter.drawText(QRect(x1 - 15, y - 36, x2 - x1 + 30, 22), Qt.AlignmentFlag.AlignCenter, f"X = {self._fmt(x)} pu")
        shunt_bottom = min(height - 112, y + 128)
        shunt_i, shunt_j = left + round(span * .10), right - round(span * .10)
        painter.setPen(QPen(QColor("#0f4c81"), 1.7))
        self._draw_shunt(painter, shunt_i, y, shunt_bottom, b / 2 + bi < 0)
        self._draw_shunt(painter, shunt_j, y, shunt_bottom, b / 2 + bj < 0)
        self._draw_bus(painter, left, y, bus_i)
        self._draw_bus(painter, right, y, bus_j)
        note_y = min(height - 84, shunt_bottom + 20)
        half = max(120, width // 2 - 18)
        self._draw_note(painter, QRect(10, note_y, half, 58), "FROM-END SHUNT ADMITTANCE", f"Yᵢ = {self._complex(gi, b / 2 + bi)} pu")
        self._draw_note(painter, QRect(width - half - 10, note_y, half, 58), "TO-END SHUNT ADMITTANCE", f"Yⱼ = {self._complex(gj, b / 2 + bj)} pu")
        rate = record.value("RATE1") or "—"
        length = record.value("LEN") or "—"
        painter.setPen(QColor("#64748b"))
        footer = f"Z = {self._complex(r, x)} pu    |    Total charging B = {self._fmt(b)} pu    |    Rate A = {rate} MVA    |    Length = {length}"
        painter.drawText(QRect(14, height - 35, width - 28, 24), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, footer)

    def _transformer_star_impedances(self, record: Record) -> list[complex] | None:
        pairs = []
        for suffix in ("1-2", "2-3", "3-1"):
            r_value = record.value(f"R{suffix}")
            x_value = record.value(f"X{suffix}")
            if not r_value or not x_value:
                return None
            impedance = complex(self._float(r_value), self._float(x_value))
            if record.value("CZ") == "2":
                pair_base = self._float(record.value(f"SBASE{suffix}"), self.system_base)
                if pair_base == 0:
                    return None
                impedance *= self.system_base / pair_base
            elif record.value("CZ") not in {"", "1"}:
                return None
            pairs.append(impedance)
        z12, z23, z31 = pairs
        return [(z12 + z31 - z23) / 2, (z12 + z23 - z31) / 2, (z23 + z31 - z12) / 2]

    def _draw_transformer(self, painter: QPainter, record: Record, width: int, height: int) -> None:
        terminals = [value for value in (record.value("I"), record.value("J"), record.value("K")) if value and value != "0"]
        if len(terminals) == 3:
            self._draw_three_winding_transformer(painter, record, terminals, width, height)
            return
        bus_i = terminals[0] if terminals else "I"
        bus_j = terminals[1] if len(terminals) > 1 else "J"
        r = self._float(record.value("R1-2"))
        x = self._float(record.value("X1-2"))
        mag_g = self._float(record.value("MAG1"))
        mag_b = self._float(record.value("MAG2"))
        y = max(150, min(190, height // 3))
        left, right = 36, width - 36
        span = right - left
        r1, r2 = left + round(span * .18), left + round(span * .34)
        x1, x2 = left + round(span * .39), left + round(span * .55)
        tx = left + round(span * .73)
        painter.setPen(QPen(QColor("#0f4c81"), 2))
        painter.drawLine(left, y, r1, y)
        self._draw_resistor(painter, r1, r2, y)
        painter.drawLine(r2, y, x1, y)
        self._draw_inductor(painter, x1, x2, y)
        painter.drawLine(x2, y, tx - 24, y)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRect(tx - 25, y - 24, 38, 48))
        painter.drawEllipse(QRect(tx - 4, y - 24, 38, 48))
        painter.drawLine(tx + 34, y, right, y)
        mag_x = left + round(span * .08)
        mag_bottom = min(height - 160, y + 75)
        branch_top, branch_bottom = y + 14, mag_bottom - 8
        painter.drawLine(mag_x, y, mag_x, branch_top)
        painter.drawLine(mag_x - 13, branch_top, mag_x + 13, branch_top)
        self._draw_vertical_resistor(painter, mag_x - 13, branch_top, branch_bottom)
        self._draw_vertical_inductor(painter, mag_x + 13, branch_top, branch_bottom)
        painter.drawLine(mag_x - 13, branch_bottom, mag_x + 13, branch_bottom)
        painter.drawLine(mag_x, branch_bottom, mag_x, mag_bottom)
        self._draw_ground(painter, mag_x, mag_bottom)
        self._draw_bus(painter, left, y, bus_i)
        self._draw_bus(painter, right, y, bus_j)
        painter.setPen(QColor("#334155"))
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRect(r1 - 4, y - 38, r2 - r1 + 8, 22), Qt.AlignmentFlag.AlignCenter, f"R  {self._fmt(r)}")
        painter.drawText(QRect(x1 - 4, y - 38, x2 - x1 + 8, 22), Qt.AlignmentFlag.AlignCenter, f"X  {self._fmt(x)}")
        wind1 = self._float(record.value("WINDV1"), 1.0)
        wind2 = self._float(record.value("WINDV2"), 1.0)
        angle = self._float(record.value("ANG1"))
        painter.drawText(QRect(tx - 68, y - 58, 136, 22), Qt.AlignmentFlag.AlignCenter, f"a = {self._fmt(wind1)}:{self._fmt(wind2)}  ∠{self._fmt(angle)}°")
        nom1, nom2 = record.value("NOMV1"), record.value("NOMV2")
        base = record.value("SBASE1-2") or self._fmt(self.system_base)
        note_y = min(height - 118, y + 104)
        cm = record.value("CM") or "1"
        magnetizing = f"Yₘ = {self._complex(mag_g, mag_b)} pu" if cm == "1" else f"MAG1 = {record.value('MAG1') or '—'}, MAG2 = {record.value('MAG2') or '—'} (CM={cm})"
        details = f"{magnetizing}    |    Z₁₂ = {self._complex(r, x)} pu on {base} MVA    |    Nominal {nom1 or '—'} / {nom2 or '—'} kV"
        self._draw_note(painter, QRect(10, note_y, width - 20, 66), "TRANSFORMER PARAMETERS", details)

    def _draw_three_winding_transformer(self, painter: QPainter, record: Record, terminals: list[str], width: int, height: int) -> None:
        cx, cy = width // 2, max(175, min(220, height // 3 + 20))
        left, right = 38, width - 38
        bottom_y = min(height - 118, cy + 150)
        star = self._transformer_star_impedances(record)
        painter.setPen(QPen(QColor("#0f4c81"), 2))
        painter.drawLine(left, cy, cx, cy)
        painter.drawLine(cx, cy, right, cy)
        painter.drawLine(cx, cy, cx, bottom_y)
        painter.setBrush(QColor("#0f4c81"))
        painter.drawEllipse(QRect(cx - 3, cy - 3, 6, 6))
        self._draw_bus(painter, left, cy, terminals[0])
        self._draw_bus(painter, right, cy, terminals[1])
        self._draw_bus(painter, cx, bottom_y, terminals[2], horizontal=True)
        if star:
            values = [self._complex(value.real, value.imag) + " pu" for value in star]
            self._draw_note(painter, QRect(left + 14, cy + 18, max(92, cx - left - 38), 48), "WINDING 1 LEAKAGE", f"Z₁ = {values[0]}")
            self._draw_note(painter, QRect(cx + 24, cy + 18, max(92, right - cx - 38), 48), "WINDING 2 LEAKAGE", f"Z₂ = {values[1]}")
            self._draw_note(painter, QRect(cx + 18, cy + 78, min(150, width - cx - 28), 48), "WINDING 3 LEAKAGE", f"Z₃ = {values[2]}")
            basis = f"Star values converted to {self._fmt(self.system_base)} MVA system base (CZ={record.value('CZ') or '1'})."
        else:
            pairwise = []
            for suffix in ("1-2", "2-3", "3-1"):
                pairwise.append(f"Z{suffix} = {record.value(f'R{suffix}') or '—'} + j{record.value(f'X{suffix}') or '—'}")
            basis = "Pairwise inputs: " + "   |   ".join(pairwise) + f"   |   Star conversion unavailable for CZ={record.value('CZ') or '—'}."
        painter.setPen(QColor("#64748b"))
        painter.drawText(QRect(12, height - 52, width - 24, 40), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, basis)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        record = self.record
        if record is None or record.section not in self.SUPPORTED_SECTIONS:
            painter.setPen(QColor("#64748b"))
            message = "Select an AC line or transformer to inspect its equivalent circuit."
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, message)
            return
        for x in range(16, self.width(), 24):
            for y in range(76, max(76, self.height() - 60), 24):
                painter.setPen(QColor("#edf1f5"))
                painter.drawPoint(x, y)
        self._draw_header(painter, record, self.width())
        if record.section == "BRANCH":
            self._draw_branch(painter, record, self.width(), self.height())
        else:
            self._draw_transformer(painter, record, self.width(), self.height())


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
        self.tabs.setMinimumWidth(440)
        self.fields = QTableView()
        self.fields.setAlternatingRowColors(True)
        self.fields.setShowGrid(False)
        self.fields.verticalHeader().setDefaultSectionSize(28)
        self.tabs.addTab(self.fields, "Fields")
        self.diagram = EquipmentDiagram()
        self.diagram.bus_clicked.connect(self.go_to_bus)
        self.tabs.addTab(self.diagram, "Diagram")
        self.equivalent = EquivalentCircuit()
        self.equivalent_tab = self.tabs.addTab(self.equivalent, "Circuit")
        self.tabs.setTabToolTip(self.equivalent_tab, "Detailed line or transformer equivalent circuit")
        self.source = QPlainTextEdit()
        self.source.setReadOnly(True)
        self.tabs.addTab(self.source, "Source")
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.tabs.addTab(self.diagnostics, "Diagnostics")
        inspector_layout.addWidget(self.tabs, 1)
        split.addWidget(inspector)
        split.setSizes([230, 760, 500])
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
        system_base = 100.0
        if self.case and self.case.records("CASE HEADER"):
            try:
                system_base = float(self.case.records("CASE HEADER")[0].value("SBASE"))
            except ValueError:
                pass
        self.equivalent.set_record(record, self.case.buses if self.case else None, system_base)
        self.tabs.setTabEnabled(self.equivalent_tab, bool(record and record.section in EquivalentCircuit.SUPPORTED_SECTIONS))
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
