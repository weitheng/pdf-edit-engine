"""System fonts for the subsets pdfmake writes: Roboto and Noto Sans CJK.

pdfmake 0.3.11 (pdfkit) embeds its bundled Roboto as cmap-less TrueType
subsets named Roboto-Regular, Roboto-Medium (bold), Roboto-Italic and
Roboto-MediumItalic, and a Noto Sans CJK face (NotoSansCJKsc-Regular,
NotoSansCJKsc-Bold) as a bare CID-keyed CFF that keeps one FontDict per glyph
class its glyphs use. A letter such a PDF lacks is injected from the full font
of that PostScript name, here laid out as on Debian: Roboto files under
/usr/share/fonts/truetype/roboto and fonts-noto-cjk's collections under
/usr/share/fonts/opentype/noto, in which the SC face is not face 0.

tests/corpus/pdfmake_noto_cjk.pdf was written with pdfmake 0.3.11, its bundled
Roboto and NotoSansCJKsc-Regular.otf 2.004, which also set its bold CJK text:
/F1 is Roboto-Medium, /F2 NotoSansCJKsc-Regular and /F3 Roboto-Regular. The
tests that inject from the real fonts take them from
PDF_EDIT_ENGINE_TEST_CJK_FONT (a Noto Sans CJK .otf or .ttc with a
NotoSansCJKsc-Regular face) and PDF_EDIT_ENGINE_TEST_ROBOTO_DIR (pdfmake's
fonts/Roboto), else from where Debian installs them, and skip without them.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pikepdf
import pytest
from fontTools.cffLib import CFFFontSet
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.basePen import BasePen
from fontTools.pens.recordingPen import DecomposingRecordingPen, RecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.ttCollection import TTCollection

import pdf_edit_engine.system_fonts as sf
from pdf_edit_engine.fonts import _parse_existing_tounicode, extend_subset
from pdf_edit_engine.locator import find, get_text
from pdf_edit_engine.surgeon import replace_all
from tests.corpus_builders.cff_cid_injection import (
    _assemble_cid_cff_pdf,
    _bare_cff_from_ttfont,
    _build_cid_keyed_cff_ttfont,
)
from tests.harness.diff_render import render_page, requires_render

CORPUS = Path(__file__).parent / "corpus"
PDFMAKE_CJK_PDF = CORPUS / "pdfmake_noto_cjk.pdf"
PDFMAKE_ROBOTO_PDF = CORPUS / "pdfmake_roboto.pdf"
CJK_FACE = "NotoSansCJKsc-Regular"

ORIGINAL_LINES = [
    "Site Visit Report 现场",
    "Document ID: TXE-2026-114",
    "The inspection team visited the Istanbul office on Monday.",
    "Konyaaltı şubesi için güncel fiyat listesi hazırlandı.",
    "上海办事处的价格表已更新。北京团队明天到达。",
    "Item Quantity City",
    "Cement bags 120 İzmir",
    "Steel rebar 45 Muğla",
]

IMAGE_FONT_FILES = {
    "Roboto-Regular": "truetype/roboto/Roboto-Regular.ttf",
    "Roboto-Medium": "truetype/roboto/Roboto-Medium.ttf",
    "Roboto-Italic": "truetype/roboto/Roboto-Italic.ttf",
    "Roboto-MediumItalic": "truetype/roboto/Roboto-MediumItalic.ttf",
    "NotoSansCJKsc-Regular": "opentype/noto/NotoSansCJK-Regular.ttc",
    "NotoSansCJKsc-Bold": "opentype/noto/NotoSansCJK-Bold.ttc",
}


def _face_names(path: Path) -> list[str]:
    if path.suffix.lower() == ".ttc":
        collection = TTCollection(str(path), lazy=True)
        try:
            return [face["name"].getDebugName(6) for face in collection.fonts]
        finally:
            collection.close()
    font = TTFont(str(path), lazy=True)
    try:
        return [font["name"].getDebugName(6)]
    finally:
        font.close()


def _find_cjk_font() -> Path | None:
    candidates = [
        os.environ.get("PDF_EDIT_ENGINE_TEST_CJK_FONT", ""),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/google-noto-sans-cjk-fonts/NotoSansCJK-Regular.ttc",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if candidate and path.is_file() and CJK_FACE in _face_names(path):
            return path
    return None


def _find_roboto_dir() -> Path | None:
    candidates = [
        os.environ.get("PDF_EDIT_ENGINE_TEST_ROBOTO_DIR", ""),
        "/usr/share/fonts/truetype/roboto",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if candidate and all(
            next(path.glob(f"**/Roboto-{style}.ttf"), None) for style in ("Regular", "Medium")
        ):
            return path
    return None


CJK_FONT = _find_cjk_font()
ROBOTO_DIR = _find_roboto_dir()
needs_cjk_font = pytest.mark.skipif(
    CJK_FONT is None,
    reason="no Noto Sans CJK SC font; set PDF_EDIT_ENGINE_TEST_CJK_FONT",
)
needs_roboto = pytest.mark.skipif(
    ROBOTO_DIR is None,
    reason="no Roboto-Regular.ttf and Roboto-Medium.ttf; set PDF_EDIT_ENGINE_TEST_ROBOTO_DIR",
)


def _use_font_directories(monkeypatch: pytest.MonkeyPatch, *dirs: Path) -> None:
    monkeypatch.setattr(sf, "_font_directories", lambda: list(dirs))
    monkeypatch.setattr(sf, "_FONT_CACHE", None)


def _system_font(postscript_name: str) -> Path:
    path = sf.find_font(postscript_name)
    assert path is not None, f"no {postscript_name} in the font directories"
    return Path(path)


def _z_font(postscript_name: str, stem: int) -> TTFont:
    """A 2048-unit TrueType font whose 'Z' is a bar ``stem`` units wide."""
    pen = TTGlyphPen(None)
    pen.moveTo((100, 0))
    pen.lineTo((100, 1456))
    pen.lineTo((100 + stem, 1456))
    pen.lineTo((100 + stem, 0))
    pen.closePath()
    builder = FontBuilder(2048, isTTF=True)
    builder.setupGlyphOrder([".notdef", "Z"])
    builder.setupCharacterMap({ord("Z"): "Z"})
    builder.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "Z": pen.glyph()})
    builder.setupHorizontalMetrics({".notdef": (1000, 0), "Z": (1200, 100)})
    builder.setupHorizontalHeader(ascent=1900, descent=-500)
    builder.setupNameTable(
        {"familyName": postscript_name, "styleName": "Regular", "psName": postscript_name}
    )
    builder.setupOS2()
    builder.setupPost()
    return builder.font


@pytest.fixture
def image_fonts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fonts named like the full fonts of pdfmake's subsets, laid out as on Debian.

    Each Roboto style's 'Z' has its own width; in each collection face 0 is the
    JP face, whose 'C' is a box, and face 1 the SC face, whose 'C' is a triangle.
    """
    root = tmp_path / "usr" / "share" / "fonts"
    for index, style in enumerate(["Regular", "Medium", "Italic", "MediumItalic"]):
        path = root / IMAGE_FONT_FILES[f"Roboto-{style}"]
        path.parent.mkdir(parents=True, exist_ok=True)
        _z_font(f"Roboto-{style}", 100 * (index + 1)).save(str(path))
    for weight in ("Regular", "Bold"):
        collection = TTCollection()
        collection.fonts = [
            _build_cid_keyed_cff_ttfont(["C"], f"NotoSansCJKjp-{weight}"),
            _build_cid_keyed_cff_ttfont(["C"], f"NotoSansCJKsc-{weight}", distinct_outline=True),
        ]
        path = root / IMAGE_FONT_FILES[f"NotoSansCJKsc-{weight}"]
        path.parent.mkdir(parents=True, exist_ok=True)
        collection.save(str(path))
    _use_font_directories(monkeypatch, root)
    return root


@pytest.mark.parametrize(
    "embedded_name",
    [
        "BZZZZZ+Roboto-Medium",
        "CZZZZZ+Roboto-Regular",
        "DZZZZZ+Roboto-Italic",
        "EZZZZZ+Roboto-MediumItalic",
        "FZZZZZ+NotoSansCJKsc-Regular",
        "GZZZZZ+NotoSansCJKsc-Bold",
    ],
)
def test_find_font_resolves_the_names_pdfmake_embeds(image_fonts: Path, embedded_name: str) -> None:
    expected = image_fonts / IMAGE_FONT_FILES[embedded_name.split("+")[1]]

    found = sf._find_font_with_origin(embedded_name)

    assert found is not None
    path, origin, substituted = found
    assert Path(path).samefile(expected)
    assert (origin, substituted) == ("system", None)
    font_path = sf.find_font(embedded_name)
    assert font_path is not None
    assert Path(font_path).samefile(expected)


def _outline(charstring: object) -> list[tuple[str, tuple[object, ...]]]:
    pen = RecordingPen()
    charstring.draw(pen)  # type: ignore[attr-defined]
    return pen.value


def _cff_outline_of_cid(font_file3: bytes, cid: int) -> list[tuple[str, tuple[object, ...]]]:
    cff = CFFFontSet()
    cff.decompile(io.BytesIO(font_file3), None)
    top = cff[cff.fontNames[0]]
    assert top.charset[cid] == f"cid{cid:05d}"
    return _outline(top.CharStrings[f"cid{cid:05d}"])


def _face_outline(path: Path, face: int, char: str) -> list[tuple[str, tuple[object, ...]]]:
    font = TTFont(str(path), fontNumber=face)
    try:
        glyph_set = font.getGlyphSet()
        pen = RecordingPen()
        glyph_set[font.getBestCmap()[ord(char)]].draw(pen)
        return pen.value
    finally:
        font.close()


def test_tier_15_injects_from_the_sc_face_of_the_collection(
    image_fonts: Path, tmp_path: Path
) -> None:
    sc_font = _build_cid_keyed_cff_ttfont(["A", "B"], CJK_FACE)
    src = tmp_path / "cjk.pdf"
    _assemble_cid_cff_pdf(
        _bare_cff_from_ttfont(sc_font),
        subtype="/Type1C",
        ps_name=f"FZZZZZ+{CJK_FACE}",
        cid_to_unicode={1: ord("A"), 2: ord("B")},
        content_cids=[1, 2],
        out_path=src,
    )
    collection = image_fonts / IMAGE_FONT_FILES[CJK_FACE]

    with pikepdf.Pdf.open(str(src)) as pdf:
        assert extend_subset(pdf, pdf.pages[0], "F1", "C") == "full_extension"
        fd = pdf.pages[0]["/Resources"]["/Font"]["/F1"]["/DescendantFonts"][0]["/FontDescriptor"]
        injected = _cff_outline_of_cid(bytes(fd["/FontFile3"].read_bytes()), 3)

    assert injected == _face_outline(collection, 1, "C"), "the 'C' must be the SC face's"
    assert injected != _face_outline(collection, 0, "C")


def _cjk_pdf_with_ligatures_in_its_tounicode(path: Path) -> Path:
    """A CID CFF subset whose /ToUnicode maps CID 3 to '——' and CID 4 to 'fi'.

    fontkit writes such entries when Noto Sans CJK's ccmp and liga lookups
    join "——" or "fi" in a CJK run.
    """
    _assemble_cid_cff_pdf(
        _bare_cff_from_ttfont(_build_cid_keyed_cff_ttfont(["A", "B", "D", "E"], CJK_FACE)),
        subtype="/Type1C",
        ps_name=f"FZZZZZ+{CJK_FACE}",
        cid_to_unicode={1: ord("A"), 2: ord("B"), 3: ord("D"), 4: ord("E")},
        content_cids=[1, 2, 3, 4],
        out_path=path,
    )
    with pikepdf.Pdf.open(str(path), allow_overwriting_input=True) as pdf:
        font = pdf.pages[0]["/Resources"]["/Font"]["/F1"]
        cmap = bytes(font["/ToUnicode"].read_bytes())
        cmap = cmap.replace(b"<0003> <0044>", b"<0003> <20142014>")
        cmap = cmap.replace(b"<0004> <0045>", b"<0004> <00660069>")
        font["/ToUnicode"] = pikepdf.Stream(pdf, cmap)
        pdf.save(str(path))
    return path


def test_tier_15_injects_beside_ligatures_in_the_tounicode(
    image_fonts: Path, tmp_path: Path
) -> None:
    src = _cjk_pdf_with_ligatures_in_its_tounicode(tmp_path / "cjk.pdf")
    out = tmp_path / "out.pdf"
    assert get_text(str(src)) == "AB——fi"

    results = replace_all(str(src), "AB", "CB", str(out))

    assert [r.success for r in results] == [True]
    assert get_text(str(out)) == "CB——fi"
    with pikepdf.Pdf.open(str(out)) as pdf:
        tounicode = _parse_existing_tounicode(pdf.pages[0]["/Resources"]["/Font"]["/F1"])
    assert (tounicode[3], tounicode[4]) == ("——", "fi")


def test_new_letter_beside_ligatures_without_a_donor_fails_honestly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sf, "_find_font_with_origin", lambda _name: None)
    src = _cjk_pdf_with_ligatures_in_its_tounicode(tmp_path / "cjk.pdf")
    out = tmp_path / "out.pdf"

    results = replace_all(str(src), "AB", "CB", str(out))

    assert [r.success for r in results] == [False]
    assert "font_extension_failed" in [d.kind for d in results[0].fidelity_report.degradations]
    assert not out.exists()


def _truetype_outline(font: TTFont, glyph_name: str) -> list[tuple[str, tuple[object, ...]]]:
    glyph_set = font.getGlyphSet()
    pen = DecomposingRecordingPen(glyph_set)
    glyph_set[glyph_name].draw(pen)
    return pen.value


@pytest.mark.parametrize(("resource", "style"), [("/F2", "Regular"), ("/F1", "Medium")])
def test_tier_15_injects_from_the_roboto_file_of_the_style(
    image_fonts: Path, resource: str, style: str
) -> None:
    donor = TTFont(str(image_fonts / IMAGE_FONT_FILES[f"Roboto-{style}"]))
    try:
        expected = _truetype_outline(donor, "Z")
    finally:
        donor.close()

    with pikepdf.Pdf.open(str(PDFMAKE_ROBOTO_PDF)) as pdf:
        font = pdf.pages[0]["/Resources"]["/Font"][resource]
        assert str(font["/BaseFont"]).endswith(f"+Roboto-{style}")
        assert extend_subset(pdf, pdf.pages[0], resource.lstrip("/"), "Z") == "full_extension"
        cid = {u: c for c, u in _parse_existing_tounicode(font).items()}["Z"]
        fd = font["/DescendantFonts"][0]["/FontDescriptor"]
        embedded = TTFont(io.BytesIO(bytes(fd["/FontFile2"].read_bytes())))
        try:
            assert _truetype_outline(embedded, embedded.getGlyphName(cid)) == expected
        finally:
            embedded.close()


def test_get_text_reads_every_line() -> None:
    assert get_text(str(PDFMAKE_CJK_PDF)).splitlines() == ORIGINAL_LINES


@pytest.mark.parametrize(
    "phrase",
    ["上海办事处", "北京团队", "现场", "Konyaaltı", "şubesi", "İzmir", "Muğla", "Istanbul"],
)
def test_find_chinese_and_turkish_text(phrase: str) -> None:
    assert [m.matched_text for m in find(str(PDFMAKE_CJK_PDF), phrase)] == [phrase]


def test_cjk_font_is_a_bare_cid_keyed_cff_with_several_fontdicts() -> None:
    with pikepdf.Pdf.open(str(PDFMAKE_CJK_PDF)) as pdf:
        font = pdf.pages[0]["/Resources"]["/Font"]["/F2"]
        assert str(font["/BaseFont"]).endswith(f"+{CJK_FACE}")
        cid_font = font["/DescendantFonts"][0]
        assert cid_font["/Subtype"] == pikepdf.Name("/CIDFontType0")
        assert "/CIDToGIDMap" not in cid_font
        font_file = cid_font["/FontDescriptor"]["/FontFile3"]
        assert font_file["/Subtype"] == pikepdf.Name("/CIDFontType0C")
        data = bytes(font_file.read_bytes())
    cff = CFFFontSet()
    cff.decompile(io.BytesIO(data), None)
    top = cff[cff.fontNames[0]]
    assert tuple(top.ROS) == ("Adobe", "Identity", 0)
    assert len(top.FDArray) > 1


def test_replace_with_chinese_characters_in_the_subset_round_trips(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"

    results = replace_all(str(PDFMAKE_CJK_PDF), "上海办事处", "北京办事处", str(out))

    assert [r.success for r in results] == [True]
    assert get_text(str(out)).splitlines() == [
        line.replace("上海办事处", "北京办事处") for line in ORIGINAL_LINES
    ]


def test_new_chinese_character_without_a_cjk_font_fails_honestly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sf, "_find_font_with_origin", lambda _name: None)
    out = tmp_path / "out.pdf"

    results = replace_all(str(PDFMAKE_CJK_PDF), "上海", "广州", str(out))

    assert [r.success for r in results] == [False]
    assert "font_extension_failed" in [d.kind for d in results[0].fidelity_report.degradations]
    assert not out.exists()


class _PdfPathPen(BasePen):
    """Draws a glyph outline as PDF path operators at ``scale`` from ``origin``."""

    def __init__(self, glyph_set: object, scale: float, origin: tuple[float, float]) -> None:
        super().__init__(glyph_set)
        self.scale = scale
        self.origin = origin
        self.ops: list[str] = []

    def _point(self, point: tuple[float, float]) -> str:
        x = self.origin[0] + point[0] * self.scale
        y = self.origin[1] + point[1] * self.scale
        return f"{x:.3f} {y:.3f}"

    def _moveTo(self, pt: tuple[float, float]) -> None:
        self.ops.append(f"{self._point(pt)} m")

    def _lineTo(self, pt: tuple[float, float]) -> None:
        self.ops.append(f"{self._point(pt)} l")

    def _curveToOne(
        self, pt1: tuple[float, float], pt2: tuple[float, float], pt3: tuple[float, float]
    ) -> None:
        self.ops.append(f"{self._point(pt1)} {self._point(pt2)} {self._point(pt3)} c")

    def _closePath(self) -> None:
        self.ops.append("h")


def _outline_reference_pdf(path: Path, donor: Path, face: int, text: str) -> Path:
    """A page drawing ``text`` as filled paths of the donor's outlines at 12 pt."""
    font = TTFont(str(donor), fontNumber=face)
    try:
        glyph_set = font.getGlyphSet()
        cmap = font.getBestCmap()
        scale = 12.0 / font["head"].unitsPerEm
        x = 72.0
        ops: list[str] = []
        for char in text:
            name = cmap[ord(char)]
            pen = _PdfPathPen(glyph_set, scale, (x, 400.0))
            glyph_set[name].draw(pen)
            ops.extend(pen.ops)
            x += font["hmtx"][name][0] * scale
    finally:
        font.close()
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    pdf.pages[0].Contents = pdf.make_stream(("0 g\n" + "\n".join(ops) + "\nf\n").encode("ascii"))
    pdf.save(str(path))
    return path


def _ink(pdf_path: Path, bbox: tuple[float, float, float, float] | None = None) -> object:
    """The page's ink, cropped to ``bbox`` and then to the ink itself.

    A match's box is one font size high from the descender, and ideographs
    reach above it, so the crop takes a third of that height above and below.
    """
    import numpy as np

    scale = 6.0
    image = np.asarray(render_page(pdf_path, 0, scale=scale).convert("L"), dtype=np.float64)
    ink = 1.0 - image / 255.0
    if bbox is not None:
        x0, y0, x1, y1 = bbox
        page_height = ink.shape[0] / scale
        margin = (y1 - y0) / 3
        top = int((page_height - y1 - margin) * scale)
        bottom = int((page_height - y0 + margin) * scale)
        ink = ink[top:bottom, int(x0 * scale) : int(x1 * scale)]
    rows = np.where(ink.max(axis=1) > 0.25)[0]
    cols = np.where(ink.max(axis=0) > 0.25)[0]
    return ink[rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1]


def _correlation(reference: object, ink: object) -> float:
    """Pearson correlation of two ink crops, ``ink`` resampled to ``reference``'s shape."""
    import numpy as np

    ref = np.asarray(reference)
    src = np.asarray(ink)
    rows = np.linspace(0, src.shape[0] - 1, ref.shape[0]).round().astype(int)
    cols = np.linspace(0, src.shape[1] - 1, ref.shape[1]).round().astype(int)
    resampled = src[rows][:, cols]
    a = ref - ref.mean()
    b = resampled - resampled.mean()
    return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum()))


def _donor_face(donor: Path, postscript_name: str) -> int:
    return _face_names(donor).index(postscript_name)


def _assert_new_text_renders_as_the_donor_outlines(
    out: Path, old: str, new: str, donor: Path, postscript_name: str, tmp_path: Path
) -> None:
    face = _donor_face(donor, postscript_name)
    reference = _ink(_outline_reference_pdf(tmp_path / "reference.pdf", donor, face, new))
    edited = _ink(out, find(str(out), new)[0].bounding_box)
    before = _ink(PDFMAKE_CJK_PDF, find(str(PDFMAKE_CJK_PDF), old)[0].bounding_box)
    assert _correlation(reference, edited) > 0.9, f"{new!r} does not render as the donor's glyphs"
    assert _correlation(reference, before) < 0.6, "the render comparison does not tell glyphs apart"


def _letters_the_subset_lacks(resource: str, text: str) -> str:
    with pikepdf.Pdf.open(str(PDFMAKE_CJK_PDF)) as pdf:
        font = pdf.pages[0]["/Resources"]["/Font"][resource]
        covered = set(_parse_existing_tounicode(font).values())
    return "".join(sorted(set(text) - covered))


def _injected_outlines_match_the_donor(
    out: Path, resource: str, chars: str, donor: Path, postscript_name: str
) -> None:
    assert chars, "the replacement must need a letter the subset lacks"
    face = _donor_face(donor, postscript_name)
    with pikepdf.Pdf.open(str(out)) as pdf:
        font = pdf.pages[0]["/Resources"]["/Font"][resource]
        cid_of = {u: c for c, u in _parse_existing_tounicode(font).items()}
        descriptor = font["/DescendantFonts"][0]["/FontDescriptor"]
        for char in chars:
            cid = cid_of[char]
            if "/FontFile3" in descriptor:
                injected = _cff_outline_of_cid(bytes(descriptor["/FontFile3"].read_bytes()), cid)
                expected = _face_outline(donor, face, char)
            else:
                embedded = TTFont(io.BytesIO(bytes(descriptor["/FontFile2"].read_bytes())))
                full = TTFont(str(donor))
                try:
                    injected = _truetype_outline(embedded, embedded.getGlyphName(cid))
                    expected = _truetype_outline(full, full.getBestCmap()[ord(char)])
                finally:
                    embedded.close()
                    full.close()
            assert injected == expected, f"the injected {char!r} is not the donor's"


@needs_cjk_font
@requires_render
@pytest.mark.render
def test_new_chinese_characters_come_from_the_cjk_font(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert CJK_FONT is not None
    _use_font_directories(monkeypatch, CJK_FONT.parent)
    donor = _system_font(CJK_FACE)
    out = tmp_path / "out.pdf"

    results = replace_all(str(PDFMAKE_CJK_PDF), "上海", "广州", str(out))

    assert [r.success for r in results] == [True]
    assert get_text(str(out)).splitlines() == [
        line.replace("上海", "广州") for line in ORIGINAL_LINES
    ]
    assert [m.matched_text for m in find(str(out), "广州")] == ["广州"]
    assert set(_letters_the_subset_lacks("/F2", "广州")) == set("广州")
    _injected_outlines_match_the_donor(out, "/F2", "广州", donor, CJK_FACE)
    _assert_new_text_renders_as_the_donor_outlines(out, "上海", "广州", donor, CJK_FACE, tmp_path)


@needs_cjk_font
def test_new_chinese_characters_decode_to_the_donor_advance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert CJK_FONT is not None
    _use_font_directories(monkeypatch, CJK_FONT.parent)
    donor_path = _system_font(CJK_FACE)
    donor = TTFont(str(donor_path), fontNumber=_donor_face(donor_path, CJK_FACE))
    try:
        advances = {char: donor["hmtx"][donor.getBestCmap()[ord(char)]][0] for char in "工地"}
    finally:
        donor.close()
    out = tmp_path / "out.pdf"

    assert [r.success for r in replace_all(str(PDFMAKE_CJK_PDF), "现场", "工地", str(out))] == [
        True
    ]

    with pikepdf.Pdf.open(str(out)) as pdf:
        font = pdf.pages[0]["/Resources"]["/Font"]["/F2"]
        cid_of = {u: c for c, u in _parse_existing_tounicode(font).items()}
        data = bytes(font["/DescendantFonts"][0]["/FontDescriptor"]["/FontFile3"].read_bytes())
    cff = CFFFontSet()
    cff.decompile(io.BytesIO(data), None)
    top = cff[cff.fontNames[0]]
    for char, advance in advances.items():
        charstring = top.CharStrings[f"cid{cid_of[char]:05d}"]
        charstring.draw(RecordingPen())
        assert charstring.width == advance, f"{char!r} decodes to width {charstring.width}"


@needs_roboto
@requires_render
@pytest.mark.render
@pytest.mark.parametrize(
    ("old", "new", "resource", "postscript_name"),
    [
        ("Istanbul", "Ankara", "/F3", "Roboto-Regular"),
        ("Report", "Review", "/F1", "Roboto-Medium"),
    ],
    ids=["regular", "bold"],
)
def test_new_latin_letters_come_from_roboto(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    old: str,
    new: str,
    resource: str,
    postscript_name: str,
) -> None:
    assert ROBOTO_DIR is not None
    _use_font_directories(monkeypatch, ROBOTO_DIR)
    donor = _system_font(postscript_name)
    out = tmp_path / "out.pdf"

    results = replace_all(str(PDFMAKE_CJK_PDF), old, new, str(out))

    assert [r.success for r in results] == [True]
    assert get_text(str(out)).splitlines() == [line.replace(old, new) for line in ORIGINAL_LINES]
    assert [m.matched_text for m in find(str(out), new)] == [new]
    new_letters = _letters_the_subset_lacks(resource, new)
    _injected_outlines_match_the_donor(out, resource, new_letters, donor, postscript_name)
    _assert_new_text_renders_as_the_donor_outlines(out, old, new, donor, postscript_name, tmp_path)
