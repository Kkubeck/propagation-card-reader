"""Tests for replicate_parser — multi-replicate card detection and parsing.

Uses patterns observed in real UBCBG cards (VLM-transcribed text).
"""
from replicate_parser import (
    is_multi_replicate, parse_replicates, Replicate, ReplicateResult,
)


# --- Circled number format (id=28 pattern) ---

CIRCLED_ABIES = """\
① natural CS, water pit NOV 09 2022
② Artificial CS, good CS, fridge. NOV 09 2022 (Sown)
Excess seed stored
③ G. Feb 16, 2023 (2) seedlings"""


def test_circled_detection():
    assert is_multi_replicate(CIRCLED_ABIES) is True


def test_circled_parse():
    result = parse_replicates(CIRCLED_ABIES)
    assert result.format == "circled_numbers"
    assert len(result.replicates) >= 2
    r1 = result.replicates[0]
    assert r1.replicate_id == 1
    assert "natural" in (r1.treatment or "").lower()
    r2 = result.replicates[1]
    assert r2.replicate_id == 2
    assert "fridge" in (r2.treatment or "").lower()


# --- Pot declaration format (id=153 pattern) ---

POT_ACER = """\
JAN 17 2011 1 Seed pot (30 seeds) - PSH
1 Seed pot (30 seeds) - 90 CS in fridge (6)
JAN 21 2011 (30 seeds) - Mixed with moist sphagnum @ 15° temp
MAR 21 2011 - Penizars split, seed moist
MAY 31 2011 (20) seedlings transplanted - 3 1/4" pots"""


def test_pot_detection():
    assert is_multi_replicate(POT_ACER) is True


def test_pot_parse():
    result = parse_replicates(POT_ACER)
    assert result.format == "pot_declarations"
    assert len(result.replicates) == 2
    r1 = result.replicates[0]
    assert r1.location == "PSH"
    assert r1.qty_sown == "30"
    r2 = result.replicates[1]
    assert "fridge" in (r2.treatment or "").lower()
    assert r2.qty_sown == "30"


# --- Pot declaration with location codes (id=150) ---

POT_PSA = """\
JAN 17 2011
1 pot (220 seeds) - PSA (7)
1 pot (30 seeds) - qd cs in fridge"""


def test_pot_psa_fridge():
    result = parse_replicates(POT_PSA)
    assert result.format == "pot_declarations"
    assert len(result.replicates) == 2
    assert result.replicates[0].location == "PSA"
    assert result.replicates[0].qty_sown == "220"
    assert result.replicates[1].qty_sown == "30"


# --- Tray numbered format (id=230 pattern) ---

TRAY_ACONITUM = """\
14a freeze, Cold Sheet (winter), Nov 28 2023 Sown
Tray #1 G Feb. 24 2024 (3 seedlings)
Tray #2 G March 7, 2024 (2 seedlings)
May 7, 2024 (5) 2 3/8 x 3 3/4 band"""


def test_tray_detection():
    assert is_multi_replicate(TRAY_ACONITUM) is True


def test_tray_parse():
    result = parse_replicates(TRAY_ACONITUM)
    assert result.format == "tray_numbered"
    assert len(result.replicates) == 2
    assert result.replicates[0].replicate_id == 1
    assert result.replicates[1].replicate_id == 2
    assert result.replicates[0].qty_germ == "3"
    assert result.replicates[1].qty_germ == "2"


# --- Negative cases ---

def test_not_replicate_single_fridge():
    text = "WWS 48 HRS.\n3 MONTH CS (IN FRIDGE MARCH 23-01)\nMOVE TO PSH JUNE 15-01"
    assert is_multi_replicate(text) is False


def test_not_replicate_simple():
    text = "SOWN - GREENHOUSE FEB 01 2002\nG. APR 15 2002 (12) seedlings"
    assert is_multi_replicate(text) is False


def test_empty():
    result = parse_replicates("")
    assert len(result.replicates) == 0


def test_none():
    result = parse_replicates(None)
    assert len(result.replicates) == 0


# --- Serialization ---

def test_to_dict():
    result = parse_replicates(CIRCLED_ABIES)
    d = result.to_dict()
    assert d["replicate_count"] >= 2
    assert d["format"] == "circled_numbers"
    assert isinstance(d["replicates"], list)
    assert "raw_text" in d["replicates"][0]


def test_replicate_has_data():
    empty = Replicate()
    assert empty.has_data() is False
    with_treatment = Replicate(treatment="PSH cold strat")
    assert with_treatment.has_data() is True


# --- Pot format with inline germ results (id=103 pattern) ---

POT_INLINE_GERM = """\
JAN 17 2011 1 Seed pot (30 seeds) - PSHT G. Feb 28, 2012 (24)
1 Seed pot (30 seeds) - 90 d CS in fridge"""


def test_pot_with_inline_germ():
    result = parse_replicates(POT_INLINE_GERM)
    assert len(result.replicates) == 2
    r1 = result.replicates[0]
    assert r1.location == "PSHT"
    assert r1.date_germ is not None
    assert r1.qty_germ == "24"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("\nAll replicate parser tests passed.")
