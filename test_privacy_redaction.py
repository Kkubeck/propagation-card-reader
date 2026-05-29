"""Tests for privacy_redaction.

Two goals:
1. Confirm we catch the obvious donor-PII shapes.
2. Confirm we do NOT redact botanical authority strings, accession numbers,
   institutional sources, or other legitimate card content.

Run with:  python -m pytest test_privacy_redaction.py -v
or simply: python test_privacy_redaction.py
"""

from __future__ import annotations

from privacy_redaction import find_pii, redact


# -- True-positive cases ------------------------------------------------------

def test_titled_name_with_period():
    matches = find_pii("Received from Mrs. Jane Smith of Vancouver.")
    cats = [m.category for m in matches]
    assert "titled_name" in cats
    assert any("Jane Smith" in m.original for m in matches)


def test_titled_name_without_period():
    matches = find_pii("Donor: Dr Watson, BC")
    assert any(m.category == "titled_name" and "Watson" in m.original for m in matches)


def test_titled_name_with_initials():
    matches = find_pii("Prof. A. B. Hutchinson, Royal Holloway")
    assert any(m.category == "titled_name" and "Hutchinson" in m.original for m in matches)


def test_email():
    matches = find_pii("Contact: jane.smith@example.org for details")
    assert any(m.category == "email" for m in matches)


def test_phone_na():
    matches = find_pii("Phone 604-822-4208 for info")
    assert any(m.category == "phone" for m in matches)


def test_phone_na_parens():
    matches = find_pii("(604) 822-4208")
    assert any(m.category == "phone" for m in matches)


def test_phone_intl():
    matches = find_pii("Ring +44 20 7942 5000 between 9 and 5")
    assert any(m.category == "phone" for m in matches)


def test_care_of():
    matches = find_pii("Send to c/o Jane Smith at the office")
    assert any(m.category == "care_of" for m in matches)


def test_street_address():
    matches = find_pii("Mailed from 123 Oak Street, Vancouver")
    assert any(m.category == "address" for m in matches)


def test_postal_code_ca():
    matches = find_pii("V6T 1Z4 is UBC")
    assert any(m.category == "postal_code" for m in matches)


def test_redact_replaces_with_categorised_token():
    out, matches = redact("Received from Mrs. Jane Smith")
    assert "Mrs. Jane Smith" not in out
    assert "[REDACTED:TITLED_NAME]" in out
    assert len(matches) == 1


def test_multiple_matches_in_one_field():
    out, matches = redact(
        "Mrs. Jane Smith, 123 Oak St, c/o John Brown, +1 604-555-1234"
    )
    cats = sorted({m.category for m in matches})
    assert "titled_name" in cats
    assert "address" in cats
    assert "care_of" in cats
    assert "phone" in cats


# -- True-negative cases (must NOT trip) --------------------------------------

def test_botanical_authority_not_redacted():
    # "L." after a binomial is Linnaean authority, not a titled name.
    out, matches = redact("Rhododendron ponticum L.")
    assert out == "Rhododendron ponticum L."
    assert matches == []


def test_complex_authority_not_redacted():
    out, matches = redact("Quercus garryana Douglas ex Hook.")
    assert out == "Quercus garryana Douglas ex Hook."
    assert matches == []


def test_legacy_accession_not_redacted_as_phone():
    out, matches = redact("Accession 39149-077-08 sown 1989")
    assert "39149-077-08" in out
    assert not any(m.category == "phone" for m in matches)


def test_modern_accession_not_redacted():
    out, matches = redact("Accession 2024-01234")
    assert out == "Accession 2024-01234"
    assert matches == []


def test_institutional_source_not_redacted():
    out, matches = redact("Received from Royal Botanic Gardens, Kew")
    # "Royal" is capitalised but has no title prefix; should pass through.
    assert "Royal Botanic Gardens, Kew" in out
    assert matches == []


def test_seed_exchange_not_redacted():
    out, matches = redact("Source: Index Seminum, Berlin-Dahlem")
    assert "Index Seminum, Berlin-Dahlem" in out
    assert matches == []


def test_quantity_not_redacted_as_phone():
    out, matches = redact("Sowed +200 seeds in flat A")
    # "+200" is not a valid phone match (needs country code + 7 more digits).
    assert "200 seeds" in out
    assert not any(m.category == "phone" for m in matches)


def test_empty_input():
    assert find_pii("") == []
    assert find_pii(None) == []  # type: ignore[arg-type]
    out, matches = redact("")
    assert out == ""
    assert matches == []


# -- Run as script ------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import traceback

    tests = [(name, obj) for name, obj in globals().items()
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError:
            failed += 1
            print(f"  FAIL {name}")
            traceback.print_exc()
    total = len(tests)
    print(f"\n{total - failed}/{total} passed")
    sys.exit(0 if failed == 0 else 1)
