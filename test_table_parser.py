"""Tests for table_parser — duplex card-back table extraction.

Runnable directly (`python3 test_table_parser.py`) or under pytest.
Uses synthetic VLM-like output matching real card back formats.
"""
from table_parser import parse_table_text, is_table_text, TableRow


# --- Pipe-delimited with headers (most structured VLM output) ---

PIPE_WITH_HEADERS = """\
OTHER | QTY | SOWN | TREATMENT | GERM | QTY
040938-0779 | | Jan 12, 2012 | light cover, just out, 30d cold strat | Apr 5, 2012 | 12
 | | | PSH | Mar 5, 2012 | 17"""


def test_pipe_delimited_with_headers():
    result = parse_table_text(PIPE_WITH_HEADERS)
    assert result.format == "pipe_delimited"
    assert len(result.rows) == 2
    assert result.rows[0].accession == "040938-0779"
    assert result.rows[0].date_sown == "Jan 12, 2012"
    assert result.rows[0].treatment == "light cover, just out, 30d cold strat"
    assert result.rows[0].date_germ == "Apr 5, 2012"
    assert result.rows[0].qty_germ == "12"
    assert result.rows[1].date_germ == "Mar 5, 2012"
    assert result.rows[1].qty_germ == "17"


# --- Pipe-delimited without headers (VLM skips headers) ---

PIPE_NO_HEADERS = """\
24183-548-03 | 05 | Mar 01, 2020 | Greenhouse | Germ. Feb 0 | (1)
24053-518-2001 | 55 | Mar 01, 2000 | Greenhouse | Apr 14, 2000 | ?"""


def test_pipe_no_headers():
    result = parse_table_text(PIPE_NO_HEADERS)
    assert len(result.rows) == 2
    assert result.rows[0].accession == "24183-548-03"
    assert result.rows[1].accession == "24053-518-2001"


# --- Space-aligned columns (no pipes, 2+ spaces between columns) ---

SPACE_ALIGNED = """\
OTHER       QTY    SOWN           TREATMENT         GERM           QTY
31748-167-94  25   Nov 8 1987     coldframe         Feb 29/88       10
31748-168-94  30   Nov 8 1987     coldframe         Mar 15/88        7"""


def test_space_aligned():
    result = parse_table_text(SPACE_ALIGNED)
    assert result.format == "space_aligned"
    assert len(result.rows) == 2
    assert result.rows[0].accession == "31748-167-94"
    assert result.rows[1].accession == "31748-168-94"


# --- Free-form rows (no clear headers or delimiters) ---

FREEFORM = """\
040938-0779   Jan 12, 2012   light cover   Apr 5, 2012   12
040938-0780   Feb 1, 2012    PSH cold strat   Mar 20, 2012   8"""


def test_freeform_heuristic():
    result = parse_table_text(FREEFORM)
    assert len(result.rows) == 2
    assert result.rows[0].accession == "040938-0779"
    assert result.rows[0].date_sown == "Jan 12, 2012"
    assert result.rows[0].date_germ == "Apr 5, 2012"


# --- is_table_text detection ---

def test_is_table_positive():
    assert is_table_text(PIPE_WITH_HEADERS) is True
    assert is_table_text(PIPE_NO_HEADERS) is True
    assert is_table_text(SPACE_ALIGNED) is True
    assert is_table_text(FREEFORM) is True


def test_is_table_negative():
    assert is_table_text("") is False
    assert is_table_text("SOWN - GREENHOUSE FEB 01 2002") is False
    assert is_table_text(None) is False


# --- Edge cases ---

def test_empty_input():
    result = parse_table_text("")
    assert len(result.rows) == 0


def test_separator_lines_skipped():
    text = """\
OTHER | SOWN | GERM
------|------|------
040938-0779 | Jan 12, 2012 | Apr 5, 2012"""
    result = parse_table_text(text)
    assert len(result.rows) == 1
    assert result.rows[0].accession == "040938-0779"


def test_row_has_data():
    empty = TableRow()
    assert empty.has_data() is False
    with_acc = TableRow(accession="040938-0779")
    assert with_acc.has_data() is True


def test_to_dict():
    row = TableRow(accession="040938-0779", date_sown="Jan 12, 2012")
    d = row.to_dict()
    assert d["accession"] == "040938-0779"
    assert d["date_sown"] == "Jan 12, 2012"
    assert d["date_germ"] is None


def test_parse_result_to_dict():
    result = parse_table_text(PIPE_WITH_HEADERS)
    d = result.to_dict()
    assert d["row_count"] == 2
    assert d["format"] == "pipe_delimited"
    assert len(d["rows"]) == 2


# --- Location detection ---

PIPE_WITH_LOCATION = """\
OTHER | SOWN | TREATMENT | GERM | QTY
040938-0779 | Jan 12, 2012 | PSH | Apr 5, 2012 | 12"""


def test_location_in_treatment_column():
    result = parse_table_text(PIPE_WITH_LOCATION)
    assert len(result.rows) == 1
    r = result.rows[0]
    assert r.treatment == "PSH"


# --- Modern accession format ---

MODERN_ACCESSIONS = """\
OTHER | SOWN | GERM | QTY
2015-00634 | Nov 1, 2015 | Feb 3, 2016 | 15
2018-01234 | Dec 5, 2018 | Mar 10, 2019 | 8"""


def test_modern_accessions():
    result = parse_table_text(MODERN_ACCESSIONS)
    assert len(result.rows) == 2
    assert result.rows[0].accession == "2015-00634"
    assert result.rows[1].accession == "2018-01234"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("\nAll table parser tests passed.")
