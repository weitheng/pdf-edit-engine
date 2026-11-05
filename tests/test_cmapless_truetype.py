"""Tests for TrueType subsets embedded without a cmap table.

tests/corpus/pdfmake_roboto.pdf was written by pdfmake 0.3.11 (pdfkit) with
its bundled Roboto. Both fonts are Type0 / Identity-H with an Identity
/CIDToGIDMap, a correct /ToUnicode, and a /FontFile2 subset that has no
cmap table: /F1 is Roboto-Medium (bold), /F2 is Roboto-Regular.
"""

from __future__ import annotations

import io
from pathlib import Path

import pikepdf
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

import pdf_edit_engine.system_fonts as sf
from pdf_edit_engine import locator
from pdf_edit_engine.errors import FontNotFoundError
from pdf_edit_engine.fonts import (
    analyze_subset,
    can_render,
    extend_subset,
    font_has_codepoint,
    recover_cid_to_unicode_from_fontfile2,
    reverse_embedded_cmap,
)
from pdf_edit_engine.locator import find, get_text
from pdf_edit_engine.surgeon import replace_all
from tests._identity_h_fixture import _find_ttf_for_cidfont, _no_ttf
from tests._simple_font_fixture import _build_simple_winansi_pdf, _no_ttf_simple

PDFMAKE_PDF = Path(__file__).parent / "corpus" / "pdfmake_roboto.pdf"

ORIGINAL_LINES = [
    "Site Visit Report",
    "Document ID: TXE-2026-114",
    "The inspection team visited the Ankara office on Monday.",
    "Konyaaltı şubesi için güncel fiyat listesi hazırlandı.",
    "Status: Approved by the regional manager.",
    "Item Quantity City",
    "Cement bags 120 İzmir",
    "Steel rebar 45 Muğla",
]


def _get_best_cmap_without_cmap_tolerance(self: TTFont, *args: object, **kwargs: object) -> object:
    return self["cmap"].getBestCmap(*args, **kwargs)


@pytest.fixture(autouse=True, params=["installed", "keyerror_on_missing_cmap"])
def fonttools_get_best_cmap(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Run every test with the installed fontTools and with one whose
    ``getBestCmap()`` raises ``KeyError`` on a cmap-less font, as the
    releases the ``fonttools>=4.60.2`` floor admits do."""
    monkeypatch.setattr(locator, "_cached_path", None)
    monkeypatch.setattr(locator, "_cached_elements", {})
    if request.param == "keyerror_on_missing_cmap":
        monkeypatch.setattr(TTFont, "getBestCmap", _get_best_cmap_without_cmap_tolerance)
    return str(request.param)


def _embedded_regular_font_bytes() -> bytes:
    with pikepdf.Pdf.open(str(PDFMAKE_PDF)) as pdf:
        font = pdf.pages[0]["/Resources"]["/Font"]["/F2"]
        return bytes(font["/DescendantFonts"][0]["/FontDescriptor"]["/FontFile2"].read_bytes())


def test_fixture_fonts_have_no_cmap_table() -> None:
    tt = TTFont(io.BytesIO(_embedded_regular_font_bytes()))
    try:
        assert "cmap" not in tt
        assert "glyf" in tt
    finally:
        tt.close()


def test_get_text_reads_every_line() -> None:
    assert get_text(str(PDFMAKE_PDF)).splitlines() == ORIGINAL_LINES


@pytest.mark.parametrize(
    "word",
    ["Ankara", "Konyaaltı", "şubesi", "hazırlandı", "Approved", "Quantity", "İzmir", "Muğla"],
)
def test_find_latin_turkish_bold_and_table_words(word: str) -> None:
    matches = find(str(PDFMAKE_PDF), word)
    assert [m.matched_text for m in matches] == [word]


def test_reverse_embedded_cmap_of_cmapless_font_is_empty() -> None:
    tt = TTFont(io.BytesIO(_embedded_regular_font_bytes()))
    try:
        assert reverse_embedded_cmap(tt) == {}
    finally:
        tt.close()


def test_recover_cid_to_unicode_from_cmapless_fontfile2_is_empty() -> None:
    assert recover_cid_to_unicode_from_fontfile2(_embedded_regular_font_bytes()) == {}


def test_font_has_codepoint_answers_from_tounicode_when_font_has_no_cmap() -> None:
    with pikepdf.Pdf.open(str(PDFMAKE_PDF)) as pdf:
        font = pdf.pages[0]["/Resources"]["/Font"]["/F2"]
        assert font_has_codepoint(font, ord("k"))
        assert font_has_codepoint(font, ord("ş"))
        assert not font_has_codepoint(font, ord("Z"))
        assert not font_has_codepoint(font, ord("Q")), "Q is only in the bold font"


def test_font_has_codepoint_reads_empty_cmap_without_identity_cid_to_gid_map() -> None:
    with pikepdf.Pdf.open(str(PDFMAKE_PDF)) as pdf:
        font = pdf.pages[0]["/Resources"]["/Font"]["/F2"]
        font["/DescendantFonts"][0]["/CIDToGIDMap"] = pdf.make_stream(bytes(512))
        assert not font_has_codepoint(font, ord("k"))
        assert not font_has_codepoint(font, ord("Z"))


def test_analyze_subset_coverage_comes_from_tounicode() -> None:
    info = analyze_subset(str(PDFMAKE_PDF), "F2")
    assert info.font_cmap is not None
    assert ord("ı") in info.font_cmap
    assert can_render(info, "Konya") == (True, [])
    assert can_render(info, "Zagreb") == (False, ["Z"])


def test_replace_with_letters_in_subset_round_trips(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    results = replace_all(str(PDFMAKE_PDF), "Ankara", "Konya", str(out))
    assert [r.success for r in results] == [True]

    assert find(str(out), "Ankara") == []
    assert get_text(str(out)).splitlines() == [
        line.replace("Ankara", "Konya") for line in ORIGINAL_LINES
    ]


@_no_ttf
def test_replace_with_new_letter_injects_glyph_from_full_font(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    donor = _find_ttf_for_cidfont()
    assert donor is not None
    monkeypatch.setattr(sf, "_find_font_with_origin", lambda _name: (str(donor), "system", None))
    out = tmp_path / "out.pdf"

    results = replace_all(str(PDFMAKE_PDF), "Ankara", "Zagreb", str(out))

    assert [r.success for r in results] == [True]
    assert [m.matched_text for m in find(str(out), "Zagreb")] == ["Zagreb"]
    assert find(str(out), "Ankara") == []
    assert get_text(str(out)).splitlines() == [
        line.replace("Ankara", "Zagreb") for line in ORIGINAL_LINES
    ]
    with pikepdf.Pdf.open(str(out)) as pdf:
        assert font_has_codepoint(pdf.pages[0]["/Resources"]["/Font"]["/F2"], ord("Z"))


@_no_ttf
def test_extend_subset_with_full_font_path_injects_new_letter() -> None:
    donor = _find_ttf_for_cidfont()
    assert donor is not None
    with pikepdf.Pdf.open(str(PDFMAKE_PDF)) as pdf:
        page = pdf.pages[0]
        assert extend_subset(pdf, page, "F2", "Z", full_font_path=donor) == "full_extension"
        assert font_has_codepoint(page["/Resources"]["/Font"]["/F2"], ord("Z"))


def test_replace_with_new_letter_and_no_full_font_fails_honestly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sf, "_find_font_with_origin", lambda _name: None)
    out = tmp_path / "out.pdf"

    results = replace_all(str(PDFMAKE_PDF), "Ankara", "Zagreb", str(out))

    assert [r.success for r in results] == [False]
    kinds = [d.kind for d in results[0].fidelity_report.degradations]
    assert "font_extension_failed" in kinds


def test_extend_subset_with_no_full_font_raises_font_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sf, "_find_font_with_origin", lambda _name: None)
    with (
        pikepdf.Pdf.open(str(PDFMAKE_PDF)) as pdf,
        pytest.raises(FontNotFoundError, match="System font not found"),
    ):
        extend_subset(pdf, pdf.pages[0], "F2", "Z")


def _strip_simple_font_cmap(pdf: pikepdf.Pdf) -> None:
    fd = pdf.pages[0]["/Resources"]["/Font"]["/F1"]["/FontDescriptor"]
    tt = TTFont(io.BytesIO(bytes(fd["/FontFile2"].read_bytes())))
    del tt["cmap"]
    buf = io.BytesIO()
    tt.save(buf)
    tt.close()
    fd["/FontFile2"] = pdf.make_stream(buf.getvalue())


@_no_ttf_simple
def test_simple_font_without_cmap_refuses_glyph_injection(tmp_path: Path) -> None:
    src = tmp_path / "simple.pdf"
    assert _build_simple_winansi_pdf(src, body_text="Hello")
    donor = _find_ttf_for_cidfont()
    assert donor is not None
    with pikepdf.Pdf.open(str(src)) as pdf:
        _strip_simple_font_cmap(pdf)

        with pytest.raises(FontNotFoundError, match="no cmap table"):
            extend_subset(pdf, pdf.pages[0], "F1", "Z", full_font_path=donor)


@_no_ttf_simple
@pytest.mark.parametrize("with_donor", [True, False], ids=["donor", "no_donor"])
def test_replace_in_simple_font_without_cmap_fails_honestly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_donor: bool
) -> None:
    src = tmp_path / "simple.pdf"
    assert _build_simple_winansi_pdf(src, body_text="Hello")
    with pikepdf.Pdf.open(str(src), allow_overwriting_input=True) as pdf:
        _strip_simple_font_cmap(pdf)
        pdf.save(str(src))
    donor = _find_ttf_for_cidfont()
    assert donor is not None
    found = (str(donor), "system", None) if with_donor else None
    monkeypatch.setattr(sf, "_find_font_with_origin", lambda _name: found)
    out = tmp_path / "out.pdf"

    results = replace_all(str(src), "Hello", "Zello", str(out))

    assert [r.success for r in results] == [False]
    assert "Z" in results[0].fidelity_report.glyphs_missing
    kinds = [d.kind for d in results[0].fidelity_report.degradations]
    assert "font_extension_failed" in kinds
    assert not out.exists()


def _write_post3_donor(path: Path, units_per_em: int) -> list[tuple[int, int]]:
    """Write a TrueType donor whose post table stores no glyph names.

    Its ``onehalf`` is a composite of the unmapped ``bar``, which fontTools
    reads back as ``glyph00001``, the same name it gives GID 1 of any subset
    without post names. Returns ``bar``'s outline coordinates.
    """
    bar_pen = TTGlyphPen(None)
    bar_pen.moveTo((100, 0))
    bar_pen.lineTo((100, 700))
    bar_pen.lineTo((180, 700))
    bar_pen.lineTo((180, 0))
    bar_pen.closePath()
    bar = bar_pen.glyph()
    half_pen = TTGlyphPen({"bar": bar})
    half_pen.addComponent("bar", (1, 0, 0, 1, 0, 0))
    half_pen.addComponent("bar", (1, 0, 0, 1, 300, 0))

    fb = FontBuilder(units_per_em, isTTF=True)
    fb.setupGlyphOrder([".notdef", "bar", "onehalf"])
    fb.setupCharacterMap({0x00BD: "onehalf"})
    fb.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "bar": bar, "onehalf": half_pen.glyph()})
    fb.setupHorizontalMetrics({".notdef": (600, 0), "bar": (300, 100), "onehalf": (600, 100)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Post3Donor", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost(keepGlyphNames=False)
    fb.save(str(path))
    return list(bar.coordinates)


def test_injected_composite_gets_its_own_components_when_names_are_made_up(
    tmp_path: Path,
) -> None:
    with pikepdf.Pdf.open(str(PDFMAKE_PDF)) as pdf:
        embedded = TTFont(io.BytesIO(_embedded_regular_font_bytes()))
        try:
            upem = embedded["head"].unitsPerEm
            subset_glyph_one = list(embedded["glyf"][embedded.getGlyphName(1)].coordinates)
            glyph_count = len(embedded.getGlyphOrder())
        finally:
            embedded.close()
        donor = tmp_path / "post3.ttf"
        bar_coordinates = _write_post3_donor(donor, upem)

        page = pdf.pages[0]
        assert extend_subset(pdf, page, "F2", "½", full_font_path=donor) == "full_extension"

        fd = page["/Resources"]["/Font"]["/F2"]["/DescendantFonts"][0]["/FontDescriptor"]
        out = TTFont(io.BytesIO(bytes(fd["/FontFile2"].read_bytes())))
        try:
            order = out.getGlyphOrder()
            assert len(order) == glyph_count + 2
            half = out["glyf"][order[-1]]
            assert half.isComposite()
            for component in half.components:
                assert out.getGlyphID(component.glyphName) == glyph_count
                assert list(out["glyf"][component.glyphName].coordinates) == bar_coordinates
            assert list(out["glyf"][out.getGlyphName(1)].coordinates) == subset_glyph_one
        finally:
            out.close()
