"""Lossless-enough, fault-tolerant reader for revision 35 text RAW files.

Every nonempty data line belongs to one displayed record. Multiline equipment is
grouped without discarding its individual lines or surplus fields. The parser does
not apply electrical defaults or solve the case.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from math import ceil
from pathlib import Path
import re


TRANSITION = re.compile(r"^\s*0\s*/\s*END OF\s+(.+?)\s+DATA(?:,\s*BEGIN\s+(.+?)\s+DATA)?\s*$", re.I)
END_MARK = re.compile(r"^\s*Q\s*$", re.I)
MIN_FIELDS = {"BUS": 4, "LOAD": 2, "FIXED SHUNT": 2, "GENERATOR": 2, "BRANCH": 5,
              "SYSTEM SWITCHING DEVICE": 3, "TRANSFORMER": 4, "SWITCHED SHUNT": 2,
              "INDUCTION MACHINE": 2}


@dataclass(slots=True)
class Diagnostic:
    line: int
    message: str
    severity: str = "warning"


@dataclass(slots=True)
class Record:
    section: str
    line: int
    raw_lines: list[str]
    groups: list[list[str]]
    names: list[list[str]]
    note: str = ""

    @property
    def fields(self) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for group_number, group in enumerate(self.groups, 1):
            labels = self.names[group_number - 1] if group_number <= len(self.names) else []
            for index, value in enumerate(group):
                name = labels[index] if index < len(labels) and labels[index] else f"Field {index + 1}"
                if len(self.groups) > 1:
                    name = f"Line {group_number} · {name}"
                result.append((name, value))
        return result

    def value(self, name: str, default: str = "") -> str:
        for label, value in self.fields:
            if label == name or label.endswith(" · " + name):
                return value
        return default

    @property
    def identity(self) -> str:
        first = self.groups[0] if self.groups else []
        section = self.section.upper()
        if section in {"BRANCH", "SYSTEM SWITCHING DEVICE", "TRANSFORMER", "MULTI-SECTION LINE"}:
            return "–".join(first[:2]) + (f" [{first[3] if section == 'TRANSFORMER' else first[2]}]" if len(first) > 3 or len(first) > 2 else "")
        if section in {"TWO-TERMINAL DC", "VSC DC LINE", "MULTI-TERMINAL DC", "FACTS DEVICE", "GEN DEVICE"}:
            return first[0] if first else ""
        return first[0] + (f" [{first[1]}]" if section in {"LOAD", "FIXED SHUNT", "GENERATOR", "SWITCHED SHUNT", "INDUCTION MACHINE"} and len(first) > 1 else "") if first else ""


@dataclass(slots=True)
class Case:
    path: str
    revision: int
    encoding: str
    sections: OrderedDict[str, list[Record]] = field(default_factory=OrderedDict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    buses: dict[str, Record] = field(default_factory=dict)

    def records(self, section: str) -> list[Record]:
        return self.sections.get(section, [])


def split_fields(line: str) -> tuple[list[str], str]:
    """Split CSV-like RAW syntax; slash comments and commas inside quotes are safe."""
    fields: list[str] = []
    token: list[str] = []
    quote: str | None = None
    comment = ""
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            if char == quote:
                if index + 1 < len(line) and line[index + 1] == quote:
                    token.append(char)
                    index += 1
                else:
                    quote = None
            else:
                token.append(char)
        elif char in "'\"":
            quote = char
        elif char == ",":
            fields.append("".join(token).strip())
            token.clear()
        elif char == "/" and (not token or token[-1].isspace()):
            comment = line[index + 1 :].strip()
            break
        else:
            token.append(char)
        index += 1
    fields.append("".join(token).strip())
    return fields, comment


def _unclosed_quote(line: str) -> bool:
    quote: str | None = None
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            if char == quote:
                if index + 1 < len(line) and line[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif char in "'\"":
            quote = char
        elif char == "/" and (index == 0 or line[index - 1].isspace()):
            break
        index += 1
    return quote is not None


def _names(header: str) -> list[str]:
    result, _ = split_fields(header.removeprefix("@!"))
    return [part.strip() for part in result]


def _canonical(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().upper())


def _record(section: str, block: list[tuple[int, str]], headers: list[list[str]]) -> Record:
    groups: list[list[str]] = []
    notes: list[str] = []
    for _, text in block:
        fields, note = split_fields(text)
        groups.append(fields)
        if note:
            notes.append(note)
    names = [headers[min(i, len(headers) - 1)].copy() if headers else [] for i in range(len(groups))]
    if section == "SWITCHED SHUNT" and names and len(names[0]) > 1 and names[0][1] != "ID":
        if re.match(r"^\s*[-+]?\d+\s*,\s*['\"]", block[0][1]):
            names[0].insert(1, "ID")
    if section == "GEN DEVICE" and groups:
        first = groups[0]
        try:
            nterm = int(float(first[2]))
            counts = [int(float(v)) for v in first[3 + nterm : 6 + nterm]]
            names[0] = ["NAME", "MODEL", "NTERM"] + [f"BUS{i + 1}" for i in range(nterm)] + ["NREAL", "NINTG", "NCHAR"]
            group_index = 2
            for prefix, count in zip(("REAL", "INTG", "CHAR"), counts):
                for start in range(0, count, 10):
                    if group_index < len(names):
                        names[group_index] = [f"{prefix}{n}" for n in range(start + 1, min(count, start + 10) + 1)]
                    group_index += 1
        except (IndexError, ValueError):
            pass
    return Record(section, block[0][0], [line for _, line in block], groups, names, " | ".join(notes))


def _group_length(section: str, first: list[str]) -> int:
    if section == "TRANSFORMER":
        return 5 if len(first) > 2 and first[2] not in {"", "0"} else 4
    if section in {"TWO-TERMINAL DC", "VSC DC LINE"}:
        return 3
    if section == "MULTI-TERMINAL DC" and len(first) >= 4:
        try:
            return 1 + sum(max(0, int(float(v))) for v in first[1:4])
        except ValueError:
            return 1
    if section == "GEN DEVICE" and len(first) >= 6:
        try:
            nterm = int(float(first[2]))
            offset = 3 + nterm
            nreal, nintg, nchar = (int(float(v)) for v in first[offset : offset + 3])
            return 2 + ceil(nreal / 10) + ceil(nintg / 10) + ceil(nchar / 10)
        except (ValueError, IndexError):
            return 1
    return 1


def parse_text(text: str, path: str = "<memory>", encoding: str = "unicode") -> Case:
    lines = text.splitlines()
    if not lines:
        raise ValueError("The RAW file is empty")
    header_line = next((i for i, line in enumerate(lines) if line.strip() and not line.startswith("@!")), None)
    if header_line is None:
        raise ValueError("The RAW file has no case header")
    values, _ = split_fields(lines[header_line])
    try:
        revision = int(values[2])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"Cannot read RAW revision at line {header_line + 1}") from exc
    if revision != 35:
        raise ValueError(f"RAW revision {revision} is unsupported; this viewer supports revision 35")
    case = Case(path, revision, encoding)
    header_names = _names(lines[0]) if lines[0].startswith("@!") else ["IC", "SBASE", "REV", "XFRRAT", "NXFRAT", "BASFRQ"]
    case.sections["CASE HEADER"] = [_record("CASE HEADER", [(header_line + 1, lines[header_line])], [header_names])]
    section = "SYSTEM-WIDE"
    case.sections[section] = []
    section_headers: list[list[str]] = []
    pending: list[tuple[int, str]] = []
    expected = 0

    def flush(incomplete: bool = False) -> None:
        nonlocal pending, expected
        if pending:
            record = _record(section, pending, section_headers)
            case.sections.setdefault(section, []).append(record)
            if incomplete:
                case.diagnostics.append(Diagnostic(record.line, f"Incomplete {section} record: expected {expected} lines, found {len(pending)}"))
            required = min(MIN_FIELDS.get(section, 1), len(section_headers[0]) if section_headers else MIN_FIELDS.get(section, 1))
            if record.groups and len(record.groups[0]) < required:
                case.diagnostics.append(Diagnostic(record.line, f"{section} record has too few fields"))
            if record.groups and not record.groups[0][0]:
                case.diagnostics.append(Diagnostic(record.line, f"{section} record has no identifier"))
            pending = []
            expected = 0

    for number, line in enumerate(lines[header_line + 1 :], header_line + 2):
        stripped = line.strip()
        if not stripped:
            continue
        if END_MARK.fullmatch(stripped):
            flush(bool(pending and len(pending) < expected))
            break
        transition = TRANSITION.match(line)
        if transition:
            flush(bool(pending and len(pending) < expected))
            ended, begun = (_canonical(v) if v else "" for v in transition.groups())
            if ended != section:
                case.diagnostics.append(Diagnostic(number, f"Section boundary says {ended}, current section is {section}"))
            section = begun or ("GEN DEVICE" if ended == "SWITCHED SHUNT" else "END")
            section_headers = []
            if section != "END":
                case.sections.setdefault(section, [])
            continue
        if line.lstrip().startswith("@!"):
            if section == "END":
                section = "GEN DEVICE"
                case.sections.setdefault(section, [])
            section_headers.append(_names(line.lstrip()))
            continue
        if section == "END":
            case.diagnostics.append(Diagnostic(number, "Data after final section boundary"))
            section = "UNCLASSIFIED"
            case.sections.setdefault(section, [])
        if _unclosed_quote(line):
            case.diagnostics.append(Diagnostic(number, "Unclosed quoted field"))
        if not pending:
            first, _ = split_fields(line)
            expected = max(1, _group_length(section, first))
        pending.append((number, line))
        if len(pending) >= expected:
            flush()
    flush(bool(pending and len(pending) < expected))
    case.buses = {r.groups[0][0]: r for r in case.records("BUS") if r.groups and r.groups[0]}
    return case


def parse_file(path: str | Path) -> Case:
    source = Path(path)
    raw = source.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            return parse_text(text, str(source), encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Unable to decode RAW file")
