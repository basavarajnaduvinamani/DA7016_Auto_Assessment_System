"""Indian-language rubrics and red ink: fonts per script and reasons in the rubric's language."""

from PIL import Image

from autoassess import annotate
from autoassess.advocate import build_advocate_prompt
from autoassess.grader import build_prompt, reason_language_note
from autoassess.schemas import Question, RubricCriterion


def _question(text: str, criterion: str) -> Question:
    return Question(
        id="Q1", text=text, max_marks=1, criteria=[RubricCriterion(id="Q1.c1", description=criterion, marks=1)]
    )


def test_every_supported_script_has_glyphs():
    for sample, expected in (
        ("सही उत्तर", "Kalam"),
        ("ಸರಿಯಾದ ಉತ್ತರ", "BalooTamma2.ttf"),
        ("சரியான பதில்", "NotoSansTamil.ttf"),
        ("సరైన సమాధానం", "NotoSansTelugu.ttf"),
    ):
        assert annotate._script_font(sample, ink=True) == expected
        font = annotate._student_font(30, sample)
        assert font.getmask(sample).getbbox() is not None
    assert annotate._script_font("plain English", ink=True) is None


def test_ink_text_draws_tamil_and_telugu():
    img = Image.new("RGBA", (900, 120), (255, 255, 255, 255))
    assert annotate._ink_text(img, (10, 10), "சரியான பதில்: softmax", 36) > 100
    assert annotate._ink_text(img, (10, 60), "సరైన సమాధానం", 36) > 100


def test_typed_indic_lines_stay_inside_the_margin():
    text = "அட்டென்ஷன் ஒவ்வொரு டோக்கனுக்கும் வினவல், விசை மற்றும் மதிப்பு திசையன்களை உருவாக்குகிறது " * 4
    width = annotate.PAGE_W - annotate.LEFT - annotate.RIGHT_MARGIN - annotate.TICK_GUTTER
    from PIL import ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font = annotate._student_font(30, text)
    assert all(draw.textlength(line, font=font) <= width for line in annotate._wrap_to_width(text, width))


def test_reasons_follow_the_rubric_language():
    english = _question("Explain attention.", "Mentions softmax.")
    hindi = _question("अटेंशन समझाइए।", "सॉफ्टमैक्स का उल्लेख करता है।")
    assert reason_language_note(english) == "" and "same language" not in build_prompt(english, "x")
    assert "same language" in build_prompt(hindi, "x")
    assert "same language" in build_advocate_prompt(hindi, "x", [])


def test_translated_remark_is_labelled_in_its_language():
    from autoassess.schemas import Remark

    assert Remark(strength="Clear", next_step="Add an example").lines() == [
        "Well done: Clear",
        "Next time: Add an example",
    ]
    tamil = Remark(strength="தெளிவு", next_step="உதாரணம்", language="Tamil").lines()
    assert tamil == ["நன்று: தெளிவு", "அடுத்த முறை: உதாரணம்"]
