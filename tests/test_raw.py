from pathlib import Path

import pytest

from case_viewer.raw import parse_file, parse_text, split_fields


ROOT = Path(__file__).resolve().parents[1]


def test_quoted_fields_and_comments():
    fields, note = split_fields("12,'Name, with / slash','O''Brien',1 / operator note")
    assert fields == ["12", "Name, with / slash", "O'Brien", "1"]
    assert note == "operator note"


def test_multiline_and_empty_sections():
    text = """@!IC,SBASE,REV,XFRRAT,NXFRAT,BASFRQ
0,100,35,0,0,60
0 / END OF SYSTEM-WIDE DATA, BEGIN BUS DATA
@!I,NAME,BASKV
1,'A, station',115
2,'B',230
3,'C',69
0 / END OF BUS DATA, BEGIN LOAD DATA
@!I,ID,PL
1,'A',24
0 / END OF LOAD DATA, BEGIN TRANSFORMER DATA
@!I,J,K,CKT
@!R12,X12,SBASE12
@!WINDV1,NOMV1
@!WINDV2,NOMV2
@!WINDV3,NOMV3
1,2,3,'1'
0.1,0.2,100
1.0,115
1.0,230
1.0,69
0 / END OF TRANSFORMER DATA, BEGIN SWITCHED SHUNT DATA
0 / END OF SWITCHED SHUNT DATA
@!NAME,MODEL,NTERM,BUS1,NREAL,NINTG,NCHAR
@!ST,OWNER,NMETR
@!REAL1
@!INTG1
@!CHAR1
'Dev','Model',1,1,1,1,1
1,1,1
3.5
7
'abc'
0 / END OF GEN DEVICE DATA, BEGIN INDUCTION MACHINE DATA
0 / END OF INDUCTION MACHINE DATA
Q
"""
    case = parse_text(text)
    assert case.buses["1"].value("NAME") == "A, station"
    assert len(case.records("TRANSFORMER")) == 1
    assert len(case.records("TRANSFORMER")[0].groups) == 5
    assert len(case.records("GEN DEVICE")) == 1
    assert len(case.records("GEN DEVICE")[0].groups) == 5
    assert case.records("SWITCHED SHUNT") == []
    assert case.diagnostics == []


def test_dc_record_shapes_and_unknown_extension():
    text = """0,100,35,0,0,60
0 / END OF SYSTEM-WIDE DATA, BEGIN TWO-TERMINAL DC DATA
@!NAME,MDC,RDC
@!IPR,NBR
@!IPI,NBI
'DC One',1,0.01
1,6
2,6
0 / END OF TWO-TERMINAL DC DATA, BEGIN VSC DC LINE DATA
@!NAME,MDC,RDC
@!IBUS,TYPE
@!IBUS,TYPE
'VSC One',1,0.02
1,1
2,2
0 / END OF VSC DC LINE DATA, BEGIN MULTI-TERMINAL DC DATA
@!NAME,NCONV,NDCBS,NDCLN
'DC Grid',1,1,1
1,6
101,1
101,102,'1'
0 / END OF MULTI-TERMINAL DC DATA, BEGIN VENDOR EXTRA DATA
@!KEY,VALUE
ABC,'has, comma',12
0 / END OF VENDOR EXTRA DATA
Q
"""
    case = parse_text(text)
    assert len(case.records("TWO-TERMINAL DC")[0].groups) == 3
    assert len(case.records("VSC DC LINE")[0].groups) == 3
    assert len(case.records("MULTI-TERMINAL DC")[0].groups) == 4
    assert case.records("VENDOR EXTRA")[0].fields[-1] == ("Field 3", "12")


def test_partial_file_reports_incomplete_record():
    text = """0,100,35,0,0,60
0 / END OF SYSTEM-WIDE DATA, BEGIN TRANSFORMER DATA
1,2,0,'1'
0.1,0.2,100
0 / END OF TRANSFORMER DATA
Q
"""
    case = parse_text(text)
    assert len(case.records("TRANSFORMER")) == 1
    assert len(case.records("TRANSFORMER")[0].raw_lines) == 2
    assert "Incomplete" in case.diagnostics[0].message
    assert case.diagnostics[0].line == 3


def test_malformed_single_line_is_retained():
    case = parse_text("0,100,35,0,0,60\n0 / END OF SYSTEM-WIDE DATA, BEGIN BUS DATA\n1,'Bad bus\n0 / END OF BUS DATA\nQ\n")
    assert len(case.records("BUS")) == 1
    assert {d.message for d in case.diagnostics} >= {"Unclosed quoted field", "BUS record has too few fields"}


def test_revision_is_explicit():
    with pytest.raises(ValueError, match="revision 34 is unsupported"):
        parse_text("0,100,34,0,0,60\nQ\n")


@pytest.mark.parametrize("name,expected", [
    ("Texas2k_series25_case1_summerpeak.RAW", {"BUS": 2751, "BRANCH": 3993, "TRANSFORMER": 1351}),
    ("MemphisCase2026_Mar7.RAW", {"BUS": 993, "BRANCH": 975, "TRANSFORMER": 407}),
])
def test_reference_cases(name, expected):
    case = parse_file(ROOT / "_ref" / name)
    assert case.revision == 35
    assert case.diagnostics == []
    for section, count in expected.items():
        assert len(case.records(section)) == count
    assert all(len(record.groups) in {4, 5} for record in case.records("TRANSFORMER"))
    assert len(case.buses) == expected["BUS"]
    shunt = case.records("SWITCHED SHUNT")[0]
    assert shunt.fields[1][0] == "ID"
    assert shunt.value("VSWHI").startswith("1.")
    source_lines = (ROOT / "_ref" / name).read_text(encoding=case.encoding).splitlines()
    data_lines = {line for records in case.sections.values() for record in records for line in range(record.line, record.line + len(record.raw_lines))}
    ignored = {i for i, line in enumerate(source_lines, 1) if not line.strip() or line.lstrip().startswith("@!") or line.strip() == "Q" or line.lstrip().startswith("0 / END OF")}
    assert data_lines | ignored == set(range(1, len(source_lines) + 1))


def test_cp1252_file(tmp_path):
    source = tmp_path / "accent.raw"
    source.write_bytes("0,100,35,0,0,60\nCaf\xe9\n0 / END OF SYSTEM-WIDE DATA\nQ\n".encode("cp1252"))
    case = parse_file(source)
    assert case.encoding == "cp1252"
    assert case.records("SYSTEM-WIDE")[0].groups[0] == ["Café"]
