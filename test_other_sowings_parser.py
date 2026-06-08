"""Tests for other_sowings_parser — front-card multi-sowing table extraction.

Uses patterns from real UBCBG card transcriptions (full corpus).
"""
from other_sowings_parser import (
    has_other_sowings, parse_other_sowings, SowingRecord,
)


# --- Detection ---

def test_detect_other_sowings():
    assert has_other_sowings("SOWN FEB 01\nOTHER SOWINGS SOWN 22163-011-83 MAR. 7-83") is True


def test_detect_other_sown_germ():
    assert has_other_sowings("stuff\nOTHER SOWN GERM\n38272-0125-2006 NOV.18-05 GH") is True


def test_detect_other_pipe():
    assert has_other_sowings("stuff\nOTHER | QTY | SOWN | GERM\n123-456-78 | 10 |") is True


def test_detect_negative():
    assert has_other_sowings("SOWN - GREENHOUSE FEB 01 2002\nG. APR 15 2002") is False


def test_detect_empty():
    assert has_other_sowings("") is False
    assert has_other_sowings(None) is False


# --- Pipe-delimited format ---

PIPE_TABLE = """\
stuff before
OTHER | QTY. | SOWN | WHERE | GERM | QTY
32578-167-94 (24 HOUR HWS) | (19) | NOV 23-94 | PSH | APR 28-95 | 1
2016-0353 | 40 | NOV 15 2016 | 5min(100C) H2O soak | May 1 2017 | 5"""


def test_pipe_parse():
    result = parse_other_sowings(PIPE_TABLE)
    assert result.format == "pipe_delimited"
    assert len(result.records) == 2
    r1 = result.records[0]
    assert "32578-167-94" in r1.accession
    assert r1.date_sown == "NOV 23-94"
    assert r1.treatment == "PSH"
    r2 = result.records[1]
    assert r2.accession == "2016-0353"
    assert r2.qty_sown == "40"


PIPE_WITH_SEPARATOR = """\
OTHER | SOWN | GERM | QTY |
| --- | --- | --- | --- |
| 1549-212-94 | NOV 23-94 | PSH | MAR 8-94 | 78 |"""


def test_pipe_with_separator():
    result = parse_other_sowings(PIPE_WITH_SEPARATOR)
    assert result.format == "pipe_delimited"
    assert len(result.records) >= 1


# --- Freeform format (multiline) ---

FREEFORM_MULTI = """\
SOWN FEB 01 2002
OTHER SOWN (70) GERM
38272-0125-2006 NOV.18-05 GH May.1-06(5)
038213-0694-2006 Oct.4-05 (GH) May.18-06(10)"""


def test_freeform_multiline():
    result = parse_other_sowings(FREEFORM_MULTI)
    assert result.format == "freeform"
    assert len(result.records) == 2
    r1 = result.records[0]
    assert r1.accession == "38272-0125-2006"
    assert r1.location == "GH"
    r2 = result.records[1]
    assert r2.accession == "038213-0694-2006"


# --- Freeform format (inline single-row) ---

FREEFORM_INLINE = """\
SOWN JUN 6 1983 COLDFRAME
G. 12-9-83
OTHER SOWINGS SOWN 22163-011-83 MAR. 7-83 COLDFRAME GERM. APRIL 25-83"""


def test_freeform_inline():
    result = parse_other_sowings(FREEFORM_INLINE)
    assert len(result.records) >= 1
    r = result.records[0]
    assert r.accession == "22163-011-83"


# --- Freeform with failure outcome ---

FREEFORM_FAIL = """\
stuff
OTHER SOWN
Fail to Germ Jan 31 - 2001 (12) PSH"""


def test_freeform_failure():
    result = parse_other_sowings(FREEFORM_FAIL)
    assert len(result.records) == 1
    r = result.records[0]
    assert r.outcome is not None
    assert "fail" in r.outcome.lower()
    assert r.location == "PSH"


# --- Multiple accessions on one line ---

MULTI_ACC_LINE = """\
OTHER SOWN GERM QTY
ARDSA (50) NOV 16-89 PSH APR 6-90 3 90
ARDS17 (50) FEB 9-90 GLHSE MAR 12-90 3
28676-552-96 JAN 5-90 PSH MAY 11-90 1"""


def test_freeform_multi_rows():
    result = parse_other_sowings(MULTI_ACC_LINE)
    assert len(result.records) == 3
    assert result.records[2].accession == "28676-552-96"


# --- Detailed pipe format ---

DETAILED_PIPE = """\
OTHER | QTY | DATE SOWN | TREATMENTS | GERM | QTY.
039111-5674-2008 | 28 | May 3 2007 | PSH | May 12 2008 | 3
42314-5664-2014 | 26 | Mar 3 2014 | 90d WS->30d CS PSH | April 2015 | 5"""


def test_detailed_pipe():
    result = parse_other_sowings(DETAILED_PIPE)
    assert result.format == "pipe_delimited"
    assert len(result.records) == 2
    r1 = result.records[0]
    assert r1.accession == "039111-5674-2008"
    assert r1.qty_sown == "28"
    assert r1.date_sown == "May 3 2007"
    assert r1.treatment == "PSH"
    assert r1.qty_germ == "3"


# --- Serialization ---

def test_to_dict():
    result = parse_other_sowings(PIPE_TABLE)
    d = result.to_dict()
    assert d["record_count"] == 2
    assert d["format"] == "pipe_delimited"


def test_record_has_data():
    empty = SowingRecord()
    assert empty.has_data() is False
    with_acc = SowingRecord(accession="32578-167-94")
    assert with_acc.has_data() is True


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("\nAll other sowings parser tests passed.")
