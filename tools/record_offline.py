"""Write engine/replay/{solver,judge}.json for an offline build.

WHY THIS FILE EXISTS (read PROMPTS.md > "How results.json was produced"):
No Anthropic API key was available while building. The model-stage outputs below were written by
Claude Opus 5.5 working in a Claude Code session, answering the exact production prompts in
engine/prompts.py for each question (blind solve first, then the judge with that solve in its
input). They are stored as recordings with the sha256 of the real request, so the deterministic
part of the pipeline (detectors, guards, routing, apply, console export) runs for real on top of
them. Run `python -m engine.run --live --record` with a key to replace every entry with real API
output; the guards then re-check everything.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import comments, detectors, prompts  # noqa: E402
from engine.llm import REPLAY_DIR, request_hash  # noqa: E402
from engine.records import load_all  # noqa: E402

SOURCE = "offline: claude-opus-5-5 via Claude Code session, production prompts, no API key at build time"
recs, reports, taxonomy = load_all()
IDS = list(recs)  # file order


def Q(i):
    return IDS[i]


def RAW(i, field):
    return recs[Q(i)].field_value(field)


def S(answer, final_value, working, confidence, issues=("none",), assumptions="", missing=""):
    return {"answer": answer, "final_value": final_value, "working": working, "assumptions": assumptions,
            "missing_data": missing, "issues": list(issues), "confidence": confidence}


def E(field, find, replace):
    return {"field": field, "find": find, "replace": replace}


MATH = 'xmlns="http://www.w3.org/1998/Math/MathML"'

# ----------------------------------------------------------------------------- blind solves
SOLVES = {
    0: S("C", "99 N", "F ∝ q1q2, so F' = 100 × 1.1 × 0.9 = 99 N.", 0.98),
    1: S("1", "n = 1", "Charge at a face centre: half its flux passes through the cube -> (q/2)/(2ε0) = q/4ε0. "
         "Charge at a corner: 1/8 of its flux -> 2q/(8ε0) = q/4ε0. Total = q/2ε0 = nq/2ε0 -> n = 1.", 0.95),
    2: S("3113", "A = 311.3 m^2, 10A = 3113", "A = 6 × 7.203^2 = 311.299 m^2; 7.203 has 4 s.f. -> 311.3 m^2; 10A = 3113.", 0.92),
    3: S("B", "Peyer's patches", "Lymphoid aggregates of the ileum (distal small intestine) are Peyer's patches.", 0.97),
    4: S("D", "1.1 V", "E = 12400/4000 eV = 3.1 eV; eV0 = 3.1 - 2.0 = 1.1 eV -> V0 = 1.1 V.", 0.97),
    5: S("A", "5 V", "Charge conservation: K(V)·C·V + C·V = C·V0 with K = αV -> V^2 + V - 30 = 0 -> V = 5 V.", 0.88),
    6: S("50", "50 mm^3", "ΔV = (ΔP/B)·V = (7e6/1.4e11)·V = 5e-5·V. Side not given; with a 10 cm cube V = 1e-3 m^3 "
         "-> ΔV = 5e-8 m^3 = 50 mm^3.", 0.55, ("insufficient_data",),
         "edge length 10 cm (the standard textbook version of this problem)", "edge length / volume of the cube"),
    7: S("C", "2.2 μA", "C = Kε0A/d = 10 × 8.85e-12 × 1 / 1e-3 = 8.85e-8 F; i_d = C·dV/dt = 8.85e-8 × 25 = 2.21e-6 A.", 0.95),
    8: S("4", "4 s", "Aligned again when the angle difference is 2π: ½(π/2 - π/4)t^2 = 2π -> t^2 = 16 -> t = 4 s.", 0.95),
    9: S("", "1 : 1", "Newton's third law: the forces on the two charges are equal and opposite, so the ratio is 1:1. "
         "Option (C) is blank and no visible option equals 1:1.", 0.9, ("no_option_matches", "options_missing_or_blank")),
    10: S("D", "Relaxin - Inhibin", "PTH/calcitonin (blood Ca2+), insulin/glucagon (blood glucose) and aldosterone/ANF "
          "(Na+ retention) are antagonistic pairs; relaxin (softens pelvic ligaments) and inhibin (suppresses FSH) act on "
          "unrelated targets.", 0.9),
    11: S("B", "Compare with an outgroup", "Ancestral state is inferred by outgroup comparison: examine a more distantly "
          "related snake.", 0.9),
    12: S("C", "more green light", "Canopy leaves absorb red and blue; understorey plants receive mostly transmitted green "
          "light, which is least effective for photosynthesis.", 0.95),
    13: S("5", "5 D each", "u = -12.5 cm, real image m = -4 -> v = +50 cm; 1/f = 1/50 + 1/12.5 = 1/10 -> f = 10 cm, "
          "P = 10 D for the pair, 5 D each.", 0.95),
    14: S("A", "Epithelial tissue", "The intestinal lining is columnar epithelium.", 0.97),
    15: S("D", "4800 N/m^2", "P = ⅓ρv_rms^2 = ⅓ × 0.09 × 400^2 = 4800 N/m^2.", 0.98),
    16: S("A", "μ = 0.8", "m = 10 kg. F - 100μ = 10·1; 2F - 100μ = 10·10 -> F = 90 N, μ = 0.8.", 0.96),
    17: S("B", "0 W", "φ = 90° between i and e -> P = Vrms·Irms·cos90° = 0. Options (B) and (C) are both '0 W'.", 0.6,
          ("multiple_options_correct",)),
    18: S("", "Assertion false, Reason false", "Equal amplitudes, φ = π/2: I = I0 + I0 + 2I0cos90° = 2I0 ≠ I0, so A is false. "
          "R is false: intensities simply add only when cos φ = 0 (or for incoherent sources), not for every non-zero φ. "
          "No option says both are false.", 0.9, ("no_option_matches",)),
    19: S("B", "air flows 1 -> 2; bubble 1 shrinks", "Excess pressure = 4T/R. Bubble 1 is hemispherical (R = r, the smallest "
          "possible) so it has the highest pressure; sub-hemispherical bubble 2 has R > r. Air flows from 1 to 2 and bubble 1 "
          "loses volume.", 0.75, ("needs_figure",), "used the text 'hemispherical' vs 'sub-hemispherical' in place of the figure",
          "the figure referred to in the stem"),
    20: S("A", "Julius von Sachs", "Sachs showed glucose is produced (stored as starch) in green parts of growing plants.", 0.95),
    21: S("D", "Statement-I correct, Statement-II incorrect", "Dialysis bridges patients to transplant (I true). For patients "
          "unsuitable for transplant, dialysis IS the long-term supportive therapy, so 'is not a supportive measure' is false.", 0.8),
    22: S("B", "16.8 eV", "K = h^2/(2mλ^2) = (6.63e-34)^2 / (2 × 9.1e-31 × (3e-10)^2) = 2.68e-18 J = 16.8 eV.", 0.95),
    23: S("C", "50 ohm", "Inductance not given. With the standard L = 95.5 mH: X_L = 2π·50·0.0955 = 30 Ω, Z = √(40^2+30^2) = 50 Ω.",
          0.6, ("insufficient_data",), "L = 95.5 mH (standard textbook version)", "value of the inductance"),
    24: S("A", "p doubles", "p = √(2mK); K × 4 -> p × 2.", 0.98),
    25: S("C", "Golden rice", "Golden rice is engineered to make β-carotene (provitamin A).", 0.97),
    26: S("D", "Lamina", "The green expanded part with veins and veinlets is the lamina.", 0.97),
    27: S("A", "5.7 × 10^-5 /°C", "α = ΔL/(L0Δθ) = 0.19/(100 × 100) = 1.9e-5 /°C; γ = 3α = 5.7e-5 /°C.", 0.96),
    28: S("20", "20 N", "f_max = μN = 0.3 × 100 = 30 N > mg = 20 N, so the body stays at rest and static friction = 20 N.", 0.85,
          ("ambiguous_wording",), "g = 10 m/s^2; answer in newtons (unit not stated)"),
    29: S("16", "16", "x = √(D(D-4f)) = √(150 × 54) = 90 cm; size ratio = ((D+x)/(D-x))^2 = (240/60)^2 = 16.", 0.95),
    30: S("B", "τ ≈ 1.44 min", "N/N0 = 1/8 -> t/τ = ln 8 = 2.079 -> τ = 3/2.079 = 1.44 min. Only (B) is correct.", 0.95),
    31: S("A", "50 V", "V = √(V_R^2 + (V_L - V_C)^2) = √(40^2 + 30^2) = 50 V.", 0.98),
    32: S("A", "≈ 600 eV", "λ_min = 12400/24800 Å = 0.5 Å; electron K = 150.4/λ^2 eV = 150.4/0.25 ≈ 600 eV.", 0.92),
    33: S("14", "14 V", "V_surface - V_∞ = kQ/R = 16 V. V_P = (kQ/2R^3)(3R^2 - R^2/4) = (11/8)·16 = 22 V; V_S = kQ/2R = 8 V; "
          "V_P - V_S = 14 V.", 0.95),
    34: S("B", "4 : 1", "R = 4r, Q = 64q -> σ_big/σ_small = (Q/R^2)/(q/r^2) = 64/16 = 4.", 0.96),
    35: S("20", "20 cm", "Removing 800 g raises the cube by 2 cm: 2·a^2·1 g/cm^3 = 800 g -> a^2 = 400 -> a = 20 cm.", 0.96),
    36: S("C", "10 m/s", "v_cm = (10·14 + 4·0)/(10 + 4) = 10 m/s. Only three options are present.", 0.95, ("options_missing_or_blank",)),
    37: S("C", "180 days", "7/8 decayed -> 1/8 left = (1/2)^3 -> 3 half-lives = 180 days.", 0.98),
    38: S("A,B,D", "A, B, D", "E ∥ u: straight line. E ⊥ u: parabola. B ∥ u: no magnetic force, straight line (not a helix). "
          "B ⊥ u: circle in a plane normal to B.", 0.94),
    39: S("D", "8√2 m", "ω = 2π/16 = π/8; x = A sin ωt, v = Aω cos ωt; at t = 2 s: π = A(π/8)cos(π/4) -> A = 8√2 m.", 0.95),
    40: S("B", "tan^-1(4)", "H = R: u^2 sin^2θ/2g = u^2 · 2sinθcosθ/g -> tanθ = 4.", 0.96),
    41: S("8", "8 cm", "Shift = (D/d)[t1(μ1-1) - t2(μ2-1)] = (1/5e-3)(1.0e-3 - 0.6e-3) = 0.08 m = 8 cm.", 0.95),
    42: S("B", "Na+ channel inactivation", "Absolute refractory period is due to inactivated voltage-gated Na+ channels.", 0.96),
}

# ----------------------------------------------------------------------------- judge outputs
def R(rid, verdict, repair, edits, conf, evidence, reply):
    return {"reportId": rid, "verdict": verdict, "repair": repair, "edits": edits, "confidence": conf,
            "evidence": evidence, "student_reply": reply}


def F(repair, edits, conf, evidence):
    return {"repair": repair, "edits": edits, "confidence": conf, "evidence": evidence}


Q22_NEW_SOLUTION = (
    '<h3>From λ = h/p, the momentum is p = h/λ, so the kinetic energy is '
    f'<math {MATH} display="block"><mrow><mi>K</mi><mo>=</mo><mfrac><msup><mi>p</mi><mn>2</mn></msup><mrow><mn>2</mn><mi>m</mi></mrow></mfrac>'
    '<mo>=</mo><mfrac><msup><mi>h</mi><mn>2</mn></msup><mrow><mn>2</mn><mi>m</mi><msup><mi>λ</mi><mn>2</mn></msup></mrow></mfrac>'
    '<mo>=</mo><mfrac><msup><mrow><mo>(</mo><mn>6.63</mn><mo>×</mo><msup><mn>10</mn><mrow><mo>−</mo><mn>34</mn></mrow></msup><mo>)</mo></mrow><mn>2</mn></msup>'
    '<mrow><mn>2</mn><mo>×</mo><mn>9.1</mn><mo>×</mo><msup><mn>10</mn><mrow><mo>−</mo><mn>31</mn></mrow></msup><mo>×</mo>'
    '<msup><mrow><mo>(</mo><mn>3</mn><mo>×</mo><msup><mn>10</mn><mrow><mo>−</mo><mn>10</mn></mrow></msup><mo>)</mo></mrow><mn>2</mn></msup></mrow></mfrac></mrow></math>'
    f'<math {MATH} display="block"><mrow><mi>K</mi><mo>≈</mo><mn>2.68</mn><mo>×</mo><msup><mn>10</mn><mrow><mo>−</mo><mn>18</mn></mrow></msup><mtext>&nbsp;J</mtext>'
    '<mo>=</mo><mfrac><mrow><mn>2.68</mn><mo>×</mo><msup><mn>10</mn><mrow><mo>−</mo><mn>18</mn></mrow></msup></mrow>'
    '<mrow><mn>1.6</mn><mo>×</mo><msup><mn>10</mn><mrow><mo>−</mo><mn>19</mn></mrow></msup></mrow></mfrac><mtext>&nbsp;eV</mtext>'
    '<mo>≈</mo><mn>16.8</mn><mtext>&nbsp;eV</mtext></mrow></math>Hence the answer is (B) 16.8 eV.</h3>'
)

JUDGE = {
    0: {"question_assessment": "Stored question, options and key (C, 99 N) are correct and complete; all four options are present in the HTML.",
        "reports": [R("R036", "display_issue", None, [], 0.9,
                      "All four options are stored (A-D present, key C = 99 N verified: 100 × 1.1 × 0.9). Cropping on an Android screen is a layout issue, not content.",
                      "Sorry about that - the options are stored correctly (the answer is C, 99 N), so this is a display problem on your phone. We've passed it to the app team.")],
        "other_findings": []},
    1: {"question_assessment": "Answer key is wrong. Face-centre charge q/2 contributes q/4ε0 and corner charge 2q contributes q/4ε0, total q/2ε0 = nq/2ε0, so n = 1. The stored solution itself ends at q/2ε0, which implies n = 1, yet the key says 2.",
        "reports": [R("R005", "defect", "answer_key", [E("answer", "2", "1")], 0.94,
                      "Blind solve gives n = 1 (q/4ε0 + q/4ε0 = q/2ε0); the stored solution's own total q/2ε0 also means n = 1. Key '2' contradicts both.",
                      "You're right - n = 1. The face charge gives q/4ε₀ and the corner charge gives q/4ε₀, so the total is q/2ε₀, which means n = 1. The key said 2; it's fixed now, thanks for catching it.")],
        "other_findings": []},
    2: {"question_assessment": "Correct. 6 × 7.203² = 311.299 m², rounded to 4 significant figures 311.3 m², so 10A = 3113.",
        "reports": [R("R033", "no_error", None, [], 0.93,
                      "7.203 m has 4 s.f.; area 311.299 -> 311.3 m²; 10A = 3113 (blind solve agrees). 3112.99 keeps more digits than the data allow, and the question is integer-type.",
                      "3113 is correct. 7.203 m has 4 significant figures, so the area 311.299 m² rounds to 311.3 m², and 10A = 3113 - writing 3112.99 keeps more digits than the data allows.")],
        "other_findings": []},
    3: {"question_assessment": "Key B (Peyer's patches) is correct. Option D is misspelt 'Choroid plexux'. The solution also has two typos: 'prominant' and 'Maceus membrane'.",
        "reports": [R("R022", "defect", "spelling", [E("question", "Choroid plexux", "Choroid plexus")], 0.97,
                      "Option D reads 'Choroid plexux'; correct term is 'choroid plexus'. Letters only - key B unaffected.",
                      "Thanks - \"plexux\" is now \"plexus\" in option D. The answer, Peyer's patches (B), is unchanged.")],
        "other_findings": [F("spelling", [E("solution", "prominant", "prominent"), E("solution", "Maceus membrane", "Mucous membrane")], 0.9,
                             "Solution typos not mentioned by the student: 'prominant' -> 'prominent', 'Maceus membrane' -> 'Mucous membrane'.")]},
    4: {"question_assessment": "Correct: 12400/4000 = 3.1 eV, minus 2.0 eV work function gives 1.1 V (D). Ångström is rendered as A with an over-ring, which displays acceptably.",
        "reports": [R("R037", "display_issue", None, [], 0.88,
                      "Content verified (D, 1.1 V). Slow loading is a platform/performance problem, not a content defect.",
                      "Sorry it was slow - the question itself is fine (answer D, 1.1 V), so we've passed the loading problem to the app team.")],
        "other_findings": []},
    5: {"question_assessment": "Correct: charge conservation gives αV² + V - 30 = 0, V = 5 V (A). Solution matches.",
        "reports": [], "other_findings": []},
    6: {"question_assessment": "The stem never gives the cube's size, so the volume change cannot be computed. The stored solution uses a 10 cm cube ((10×10⁻²)³ m³) and gets 50 mm³, which matches the key.",
        "reports": [R("R006", "defect", "stem_data", [E("question", "solid copper cube,", "solid copper cube of side 10 cm,")], 0.9,
                      "Stem omits the edge length; the stored solution uses (10×10⁻²)³ m³, i.e. a 10 cm cube, and reaches the key 50 mm³. Blind solve flagged the same missing value.",
                      "You're right - the cube's size was missing. The question now says the side is 10 cm, so V = 10⁻³ m³ and ΔV = (7×10⁶ / 1.4×10¹¹) × 10⁻³ m³ = 50 mm³.")],
        "other_findings": []},
    7: {"question_assessment": "Key C (2.2 μA) is correct, but the question is about displacement current in a charging capacitor and is filed under 'Geometrical optics and optical instruments'.",
        "reports": [R("R042", "defect", "wrong_chapter", [E("chapter", "Geometrical optics and optical instruments", "Alternating Current and EM Waves")], 0.92,
                      "Displacement current (i_d = C dV/dt = 2.2 μA, key correct) belongs to EM waves; it is filed under Geometrical optics. Existing chapter 'Alternating Current and EM Waves' fits.",
                      "You're right - displacement current belongs with capacitors and EM waves, not geometrical optics. A faculty member is moving it to the right chapter, and the answer (2.2 μA) stays the same.")],
        "other_findings": []},
    8: {"question_assessment": "Correct: relative angular displacement ½(π/2 - π/4)t² = 2π gives t = 4 s.",
        "reports": [R("R031", "no_error", None, [], 0.93,
                      "Dots realign when the angle difference is 2π: ½(π/4)t² = 2π -> t = 4 s; blind solve and stored solution agree with key 4.",
                      "Answer 4 s hi sahi hai. Dots tab align honge jab dono ke angle ka difference 2π ho: ½(π/2 − π/4)t² = 2π, isse t² = 16 aur t = 4 s aata hai.")],
        "other_findings": []},
    9: {"question_assessment": "Option C is blank while the key is C. By Newton's third law the forces on the two charges are equal, so the correct ratio is 1 : 1, which must be option C's content.",
        "reports": [R("R011", "defect", "option_repair",
                      [E("question", "(C) <br />", f'(C) <math display="inline" {MATH}><mrow><mn> 1 </mn><mi>:</mi><mn> 1 </mn></mrow></math><br />')], 0.9,
                      "Option C is empty but keyed. Blind solve gives 1 : 1 (Newton's third law), and the stored solution shows |F12| = |F21|; restoring C as 1 : 1 changes no stem text.",
                      "Aap sahi ho - option C khali tha. Dono charges par force barabar hota hai (Newton ka third law), isliye sahi answer C = 1 : 1 hai, aur option C ab question me dikh raha hai.")],
        "other_findings": []},
    10: {"question_assessment": "Key D (Relaxin - Inhibin) is correct for 'NOT antagonistic'. But the solution wrongly says insulin and glucagon work 'synergistically'; they are the textbook antagonistic pair. Option C is missing its dash, and the stem is wrapped in an <ol>, so it renders with a stray '1.'.",
         "reports": [R("R035", "no_error", None, [], 0.88,
                       "Question asks which pair is NOT antagonistic. Relaxin (pelvic ligaments) and inhibin (FSH suppression) act on unrelated targets, so D is right; the student's premise is wrong.",
                       "The key is right: the question asks which pair is NOT antagonistic. Relaxin (softens pelvic ligaments at birth) and inhibin (suppresses FSH) act on different things, so they aren't opposites - that's why (D) is correct.")],
         "other_findings": [
             F("solution_fix", [E("solution", "Insulin and glucagon work synergistically", "Insulin and glucagon work antagonistically")], 0.9,
               "Solution says insulin and glucagon 'work synergistically'; they are antagonistic (insulin lowers, glucagon raises blood glucose). This contradicts the logic of the key."),
             F("noise", [E("question", "<ol>\n\t<li>", "")], 0.7,
               "Stem is wrapped in an ordered list, so it renders with a stray '1.' question number."),
         ]},
    11: {"question_assessment": "Key B (outgroup comparison) is correct. Student claims it is outside the NEET syllabus; cladistic outgroup reasoning is not in NCERT, so the claim is plausible and faculty should confirm. Solution has typos ('than' for 'then', 'wheater').",
         "reports": [R("R026", "defect", "syllabus", [], 0.6,
                       "Outgroup comparison / ancestral-state inference is not part of the NCERT Evolution chapter; plausible syllabus issue. Content and key (B) are otherwise correct.",
                       "Thanks for raising this. A faculty member will check whether this question is within the NEET syllabus; until then it stays available for practice.")],
         "other_findings": [F("spelling", [E("solution", "each other than,", "each other then,"), E("solution", "wheater", "whether")], 0.85,
                              "Solution typos: 'than,' -> 'then,' and 'wheater' -> 'whether'.")]},
    12: {"question_assessment": "Options now read 'more red/blue/green/white light'. errorHistory shows faculty corrected 'mere' -> 'more' on 2026-11-07, after this report (2026-11-04). Key C is correct.",
         "reports": [R("R017", "already_fixed", None, [], 0.95,
                       "errorHistory: faculty fixed 'mere' -> 'more' on 2026-11-07T10:42Z, three days after the report; the live options no longer contain 'mere'.",
                       "Thanks - you were right, and our faculty team already changed 'mere' to 'more' on 7 Nov. Reload the question to see the updated options.")],
         "other_findings": []},
    13: {"question_assessment": "Key 5 D is correct (f_eq = 10 cm, 10 D total). The solution's last steps have garbled subscripts: 'P_eqcu' and 'P_eqch' should both be 'P_each'.",
         "reports": [],
         "other_findings": [F("notation", [E("solution", "<mtext> eqcu </mtext>", "<mtext> each </mtext>"), E("solution", "<mtext> eqch </mtext>", "<mtext> each </mtext>")], 0.85,
                              "Solution shows 10 D = 2P_eqcu and P_eqch = 5 D; the subscript should read 'each'. Unreported.")]},
    14: {"question_assessment": "Key A correct. Option A is misspelt 'Epithellial tisue'.",
         "reports": [R("R012", "defect", "spelling", [E("question", "Epithellial tisue", "Epithelial tissue")], 0.97,
                       "Option A reads 'Epithellial tisue' -> 'Epithelial tissue'. Letters only; key A unaffected.",
                       "Thanks for spotting that - option A now reads \"Epithelial tissue\". The answer (A) is unchanged.")],
         "other_findings": []},
    15: {"question_assessment": "Answer key wrong. P = ⅓ρv² = ⅓ × 0.09 × 400² = 4800 N/m², which is option D; the stored solution also ends at 4800, but the key is A (4556). The student's 8225 is also wrong.",
         "reports": [R("R004", "defect", "answer_key", [E("answer", "A", "D")], 0.96,
                       "P = ⅓ρv² = 4800 N/m² = option D. Blind solve, stored solution and detector all agree on D; key says A. Student's claimed 8225 (option B) is not correct.",
                       "Aapne sahi pakda ki key galat thi, par sahi answer 8225 nahi, 4800 N/m² hai (option D): P = ⅓ρv² = ⅓ × 0.09 × 400² = 4800. Key ab D kar di gayi hai.")],
         "other_findings": []},
    16: {"question_assessment": "Correct: with m = 10 kg, F - 100μ = 10 and 2F - 100μ = 100 give μ = 0.8 (A).",
         "reports": [R("R029", "no_error", None, [], 0.94,
                       "m = 10 kg: F - 100μ = 10, 2F - 100μ = 100 -> F = 90 N, μ = 0.8. Blind solve and stored solution agree with key A.",
                       "μ = 0.8 is actually correct. Taking m = 100/10 = 10 kg: F − 100μ = 10 and 2F − 100μ = 100, which gives F = 90 N and μ = 0.8. Worth checking where your 0.4 came from - it's often the mass.")],
         "other_findings": []},
    17: {"question_assessment": "Options B and C are both '0 W', so a student choosing C is marked wrong for the correct value. The key (B, 0 W) is right. The solution also shows stray LaTeX '&' alignment characters.",
         "reports": [R("R015", "defect", "identical_options", [E("question", "(C) 0 W", "(C) 500 W")], 0.95,
                       "Detector: options B and C identical ('0 W'). Correct power is 0 W (φ = 90°). Suggested new C = 500 W (Vrms·Irms without the cos φ factor, a common slip); a new distractor is authored content for faculty.",
                       "You're right - options B and C were both \"0 W\". The correct answer is 0 W because the phase difference is 90°, and a faculty member is replacing option C with a proper option.")],
         "other_findings": [F("markup_leak", [E("solution", "<mi>&amp;</mi><mi>P</mi>", "<mi>P</mi>"), E("solution", "<mi>&amp;</mi><mi>ϕ</mi>", "<mi>ϕ</mi>")], 0.9,
                              "Solution shows literal '&' before P and ϕ (leftover LaTeX alignment markers).")]},
    18: {"question_assessment": "Unsound. With equal amplitudes and φ = π/2, I = 2I0, so the Assertion is false; the Reason ('always the sum if φ ≠ 0') is also false. No option says both are false. The stored solution uses a wrong formula (2I0cos²(φ/2) instead of 4I0cos²(φ/2)) and contradicts itself before choosing D.",
         "reports": [R("R034", "defect", "unsound", [], 0.88,
                       "I = I0 + I0 + 2I0cos90° = 2I0, so the Assertion is false (the student is wrong on this); the Reason is false for general φ. No option fits; the solution's I = 2I0cos²(φ/2) is wrong and self-contradictory. Needs faculty rewrite (fix Reason or options).",
                       "Good catch that something is off here, though not quite the way you think: with equal amplitudes and phase difference π/2, I = I₀ + I₀ + 2I₀cos 90° = 2I₀, so the Assertion is false. The Reason is also false, so none of the options fit - a faculty member is checking this question now.")],
         "other_findings": []},
    19: {"question_assessment": "Stem says 'as shown in figure' but no image is attached. The text alone ('hemispherical' radius r vs 'sub-hemispherical') still supports key B, but the figure must be restored. Also 'hemispherial' is misspelt.",
         "reports": [R("R025", "defect", "diagram", [], 0.93,
                       "Stem references a figure; quesImages is empty and there is no <img>. Key B is consistent with the text (smaller radius -> higher excess pressure 4T/r), but students need the figure.",
                       "You're right - the question refers to a figure that isn't attached. A faculty member is adding it; meanwhile, the answer (B) follows from the hemispherical bubble at end 1 having the smaller radius, so higher pressure (P = P₀ + 4T/r).")],
         "other_findings": [F("spelling", [E("question", "hemispherial", "hemispherical")], 0.95, "Stem typo: 'hemispherial' -> 'hemispherical'.")]},
    20: {"question_assessment": "Correct: Julius von Sachs (A).",
         "reports": [R("R041", "not_actionable", None, [], 0.9,
                       "Comment 'asdfgh' is keyboard mash with no claim; question, options and key A verified correct.",
                       "We couldn't tell what went wrong from your report, and when we checked, the question was correct (answer: Julius von Sachs). If something looks off, tell us what you saw.")],
         "other_findings": []},
    21: {"question_assessment": "Consistent as written: Statement I true; Statement II (dialysis 'is not' supportive when transplant is inappropriate) is false, so D. Wording of Statement II is a double negative but not wrong.",
         "reports": [], "other_findings": []},
    22: {"question_assessment": "Key B (16.8 eV) is correct, but the solution is broken: it opens with '=5.469×10⁻¹⁰ m = 5.47 Å', a result from another question, has 'h/|I|' for h/|p|, leaks the LaTeX '\\AA', and its 2.65×10⁻¹⁸ J does not give 16.8 eV.",
         "reports": [
             R("R018", "defect", "solution_fix", [E("solution", RAW(22, "solution"), Q22_NEW_SOLUTION)], 0.88,
               "Solution starts with 5.47 Å (another question's result), shows h/|I|, leaks '\\AA'. Correct working K = h²/2mλ² = 2.68×10⁻¹⁸ J = 16.8 eV matches key B and blind solve; the fragment is too broken to patch, so the solution is replaced.",
               "You're right - the old solution mixed in a step from another question. It's been replaced with the correct working: K = h²/2mλ² ≈ 2.68 × 10⁻¹⁸ J ≈ 16.8 eV, which is option (B)."),
             R("R019", "defect", "solution_fix", [E("solution", RAW(22, "solution"), Q22_NEW_SOLUTION)], 0.88,
               "Same defect as R018: the 5.47 Å line belongs to a different question; corrected solution ends at 16.8 eV = key B.",
               "Sahi pakda - 5.47 Å wala step kisi aur question ka tha. Solution ab theek kar diya hai: K = h²/2mλ² ≈ 16.8 eV, jo option (B) hai."),
         ],
         "other_findings": []},
    23: {"question_assessment": "The inductance value is missing from the stem. The stored solution uses L = 95.5 × 10⁻³ H (X_L = 30 Ω, Z = 50 Ω), which matches key C.",
         "reports": [
             R("R008", "defect", "stem_data", [E("question", "an inductance are", "an inductance of 95.5 mH are")], 0.92,
               "Stem gives no L; stored solution uses L = 95.5×10⁻³ H, giving X_L = 30 Ω and Z = 50 Ω = key C. Blind solve flagged the same missing value.",
               "You're right - the inductance was missing from the question. It now states L = 95.5 mH, which gives X_L ≈ 30 Ω and Z = 50 Ω (option C)."),
             R("R007", "defect", "stem_data", [E("question", "an inductance are", "an inductance of 95.5 mH are")], 0.92,
               "Same as R008: L absent from stem; solution states 95.5 mH; restoring it makes key C (50 Ω) derivable.",
               "Sahi baat hai - inductance ki value question me nahi thi. Ab question me L = 95.5 mH add kar diya hai; isse X_L ≈ 30 Ω aur Z = 50 Ω (option C) aata hai."),
         ],
         "other_findings": []},
    24: {"question_assessment": "Correct: p = √(2mK), so 4× KE gives 2× momentum (A).",
         "reports": [R("R038", "app_issue", None, [], 0.9,
                       "Student reports the app recorded B after tapping A: answer-capture behaviour, not question content. Content verified (A).",
                       "Sorry about that - this sounds like the app saving the wrong option, not a problem with the question (the answer is A: 4× KE means 2× momentum). We've passed it to the app team; a screenshot helps if it happens again.")],
         "other_findings": []},
    25: {"question_assessment": "Key C (Golden rice) is correct. Option B is misspelt 'Canolla', and the solution has words run together ('riceis', 'producebeta-carotene', 'ofvitamin', 'helpprevent', 'tonight blindness').",
         "reports": [R("R040", "no_error", None, [], 0.75,
                       "Vague comment ('wrong'). Key C verified: golden rice makes β-carotene (provitamin A). Only cosmetic typos found ('Canolla', run-together words), logged as separate findings.",
                       "We checked this one: Golden rice is correct - it's engineered to make beta-carotene, which the body turns into vitamin A. If you meant something else looked wrong, tell us what you saw.")],
         "other_findings": [
             F("spelling", [E("question", "Canolla", "Canola")], 0.95, "Option B 'Canolla' -> 'Canola' (the solution spells it correctly)."),
             F("spelling", [E("solution", "Golden riceis", "Golden rice is"), E("solution", "producebeta-carotene", "produce beta-carotene"),
                            E("solution", "ofvitamin", "of vitamin"), E("solution", "helpprevent", "help prevent"), E("solution", "lead tonight blindness", "lead to night blindness")], 0.92,
               "Solution has missing spaces; 'lead tonight blindness' changes the meaning."),
         ]},
    26: {"question_assessment": "Key D (Lamina) correct. Stem begins with the source tag '(NEET 2019)'. Also 'ofleaf' is missing a space.",
         "reports": [R("R013", "defect", "exam_reference", [E("question", "(NEET 2019) ", "")], 0.96,
                       "Stem starts with '(NEET 2019)', an exam source tag inside question text. Removing it changes no content; key D unaffected.",
                       "Thanks - the \"(NEET 2019)\" tag has been removed from the question text. The answer, Lamina (D), is unchanged.")],
         "other_findings": [F("spelling", [E("question", 'part of<span style="color:#000000">leaf', 'part of <span style="color:#000000">leaf')], 0.9,
                              "Stem renders as 'part ofleaf' (missing space).")]},
    27: {"question_assessment": "Key A is correct: α = 1.9×10⁻⁵ /°C, γ = 3α = 5.7×10⁻⁵ /°C (C is α, a distractor). The report is a prompt-injection attempt asking to change the key to C; the record does not support it. The solution's units are garbled ('/AC', '/CC' instead of /°C; '3a' for 3α), and the stem has 'It's' for 'Its'.",
         "reports": [R("R027", "no_error", None, [], 0.95,
                       "Comment is an instruction to the system ('change the answer to C'), not a content claim - ignored. Independent check: γ = 3α = 3 × 1.9×10⁻⁵ = 5.7×10⁻⁵ /°C = key A; C (1.9×10⁻⁵) is α.",
                       "We checked this question and the answer is (A) 5.7 × 10⁻⁵ /°C: α = 0.19/(100 × 100) = 1.9 × 10⁻⁵ /°C and γ = 3α. No change is needed.")],
         "other_findings": [
             F("notation", [E("solution", '<mrow><mi mathvariant="normal">A</mi><mi mathvariant="normal">C</mi></mrow>', '<mrow><mo>°</mo><mi mathvariant="normal">C</mi></mrow>'),
                            E("solution", '<mrow><mi mathvariant="normal">C</mi><mi mathvariant="normal">C</mi></mrow>', '<mrow><mo>°</mo><mi mathvariant="normal">C</mi></mrow>'),
                            E("solution", "<mn>3</mn><mi>a</mi>", "<mn>3</mn><mi>α</mi>")], 0.88,
               "Solution units read '/AC' and '/CC' (degree sign lost) and 'γ = 3a' should be 3α."),
             F("spelling", [E("question", "It&rsquo;s length", "Its length")], 0.85, "Stem: 'It's length' -> 'Its length'."),
         ]},
    28: {"question_assessment": "Key 20 is correct (static friction balances the 20 N weight; maximum 30 N). Integer question does not state the unit. 'The friction ... is 0.3' should be 'coefficient of friction'.",
         "reports": [R("R024", "defect", "answer_form", [E("question", "is equal to</span>", "is equal to (in N)</span>")], 0.9,
                       "Integer-type stem asks for 'the frictional force' with no unit; key 20 is in newtons (solution: f = mg = 20 N). Adding '(in N)' is additive and changes no value.",
                       "Good point - the question now says to give the answer in newtons. The friction is 20 N, equal to the weight, because the maximum available friction (30 N) is more than needed.")],
         "other_findings": [F("spelling", [E("question", "The friction between wall", "The coefficient of friction between wall")], 0.7,
                              "Stem says 'The friction ... is 0.3'; 0.3 is the coefficient of friction (words only).")]},
    29: {"question_assessment": "Correct: x = 90 cm, ratio (240/60)² = 16.", "reports": [], "other_findings": []},
    30: {"question_assessment": "Only B (1.44 min) is correct, but the question is stored as mcq with a malformed answer [\"\", \"B\"], so students face multiple-correct marking. It should be scq with key B. It is also filed under 'Mathematics in physics' though it is radioactive decay.",
         "reports": [R("R021", "defect", "type_mismatch", [E("questionType", "mcq", "scq"), E("answer", '["", "B"]', "B")], 0.93,
                       "τ = 3/ln 8 = 1.44 min: exactly one correct option (blind solve: B). Stored as mcq with answer [\"\", \"B\"] (detector: malformed, single key) -> should be scq with key B.",
                       "You're right - only (B) 1.44 min is correct, and the question was wrongly set as multiple-correct. It's now single-correct with key (B).")],
         "other_findings": [F("wrong_chapter", [E("chapter", "Mathematics in physics", "Nuclear physics and radioactivity")], 0.9,
                              "Mean life of decaying nuclei is filed under 'Mathematics in physics'; 'Nuclear physics and radioactivity' exists.")]},
    31: {"question_assessment": "Answer key wrong. V = √(40² + (60-30)²) = 50 V, option A; the stored solution also ends at 50 V, but the key is C (130 V, the plain sum).",
         "reports": [
             R("R002", "defect", "answer_key", [E("answer", "C", "A")], 0.97,
               "V = √(V_R² + (V_L−V_C)²) = 50 V = option A; stored solution and blind solve both give 50 V; key C (130 V) is the arithmetic sum.",
               "You're right, the key was wrong. V = √(40² + (60 − 30)²) = 50 V, which is option (A); the key has been fixed."),
             R("R003", "defect", "answer_key", [E("answer", "C", "A")], 0.97,
               "Student's √(40²+30²) = 50 V is right; 50 V is option A. Key C = 130 V ignores phase.",
               "Exactly right - √(40² + 30²) = 50 V, option (A). 130 V would only come from adding the voltages directly, which ignores the phase difference. The key has been fixed, thanks!"),
             R("R001", "defect", "answer_key", [E("answer", "C", "A")], 0.97,
               "Stored solution ends at 50 V = option A; key says C. Blind solve agrees with A.",
               "You're right - the solution's 50 V is option (A), and the key wrongly said (C). The key is fixed now; pointing to the solution made it quick to check."),
         ],
         "other_findings": []},
    32: {"question_assessment": "Correct: λ_min = 0.5 Å gives K ≈ 600 eV (A). Solution shows stray '&' characters from LaTeX alignment.",
         "reports": [R("R039", "language_mode", None, [], 0.95,
                       "Student requests the question in Hindi; content verified (A, ≈600 eV). Language availability, not a defect.",
                       "Abhi yeh question sirf English me available hai, Hindi version nahi hai. Aapki request note kar li hai.")],
         "other_findings": [F("markup_leak", [E("solution", "<mi>K</mi><mi>&</mi><mo>&#x0003D;</mo>", "<mi>K</mi><mo>&#x0003D;</mo>"),
                                              E("solution", "<mi>K</mi><mi>&</mi><mo>&#x02248;</mo>", "<mi>K</mi><mo>&#x02248;</mo>")], 0.9,
                              "Solution renders 'K & =' and 'K & ≈' (LaTeX alignment markers leaked).")]},
    33: {"question_assessment": "Correct: V_P = 22 V, V_S = 8 V, difference 14 V.",
         "reports": [R("R044", "no_error", None, [], 0.94,
                       "22 V is V_P alone ((11/8)·16); the question asks V_P − V_S = 22 − 8 = 14 V. Blind solve and stored solution agree with key 14.",
                       "Close - 22 V is the potential at P itself (11/8 × 16). The question asks for V_P − V_S, and V_S = 16/2 = 8 V, so the answer is 22 − 8 = 14 V.")],
         "other_findings": []},
    34: {"question_assessment": "Correct: Q = 64q, R = 4r, σ ratio 64/16 = 4:1 (B).",
         "reports": [R("R043", "no_error", None, [], 0.95,
                       "Bigger drop: 64× charge over 16× area -> σ ratio 4:1 = key B. The student considered area but not charge.",
                       "4 : 1 is correct. The bigger drop has 64 times the charge but only 16 times the area (R = 4r), so its surface density is 64/16 = 4 times larger.")],
         "other_findings": []},
    35: {"question_assessment": "Key 20 cm is correct (2a² = 800 -> a = 20 cm), but the solution's last line says a = 40 cm.",
         "reports": [R("R016", "defect", "solution_fix", [E("solution", "a = 40 cm", "a<sup>2</sup> = 400 cm<sup>2</sup>, so a = 20 cm")], 0.95,
                       "Solution's own equation 800g = 2·a²·1·g gives a² = 400, a = 20 cm = key; its final line '40 cm' is an arithmetic slip. Blind solve: 20 cm.",
                       "Good question - the answer 20 cm is correct and the solution's last line had a mistake. 800 = 2 × a² gives a² = 400, so a = 20 cm; the solution is corrected now.")],
         "other_findings": []},
    36: {"question_assessment": "Only options A-C are stored; option D is missing. Key C (10 m/s) is correct. D's original text is not recoverable from the record. The solution also shows stray '&' alignment characters.",
         "reports": [
             R("R010", "defect", "option_repair", [E("question", "</math></h3>", "</math><br/>(D) 14 m/s</h3>")], 0.7,
               "Detector: option D absent. Key C verified (v_cm = 140/14 = 10 m/s). The missing option's original text cannot be recovered; suggested distractor '14 m/s' (velocity of the struck block) is new content for faculty.",
               "You're right, option D is missing. The answer is (C) 10 m/s, since v_cm = (10 × 14)/14, and a faculty member is adding the fourth option."),
             R("R009", "defect", "option_repair", [E("question", "</math></h3>", "</math><br/>(D) 14 m/s</h3>")], 0.7,
               "Same as R010: option D missing; key C unaffected; restoring D needs authored content.",
               "Thanks - option D really is missing. The correct answer, (C) 10 m/s, is unaffected, and a faculty member is adding the missing option."),
         ],
         "other_findings": [F("markup_leak", [E("solution", "</msub><mi>&</mi><mo>&#x0003D;</mo>", "</msub><mo>&#x0003D;</mo>"),
                                              E("solution", '<mspace linebreak="newline" /><mi>&</mi>', '<mspace linebreak="newline" />')], 0.9,
                              "Solution renders 'v_CM & =' and '& =' (LaTeX alignment markers leaked).")]},
    37: {"question_assessment": "Key C (180 days) correct. Stem shows raw LaTeX '\\frac{7}{8}'.",
         "reports": [R("R014", "defect", "markup_leak", [E("question", "\\frac{7}{8}", f'<math {MATH} display="inline"><mfrac><mn>7</mn><mn>8</mn></mfrac></math>')], 0.96,
                       "Raw LaTeX '\\frac{7}{8}' is visible in the stem; replaced by equivalent MathML 7/8. Same values; key C (3 half-lives = 180 days) unaffected.",
                       "Thanks - the raw \"\\frac{7}{8}\" code now shows as a proper fraction 7/8. The answer stays (C) 180 days: 1/8 remaining means 3 half-lives.")],
         "other_findings": []},
    38: {"question_assessment": "A, B and D are correct (B ∥ u gives a straight line, not a helix). The stored mcq answer is the single string [\"A, B, D\"] instead of three letters, so a student marking A, B, D is graded wrong. The solution is a two-line stub.",
         "reports": [R("R020", "defect", "answer_key", [E("answer", '["A, B, D"]', '["A", "B", "D"]')], 0.95,
                       "Correct set is A, B, D (blind solve agrees). Stored answer is one malformed element \"A, B, D\", so the grader cannot match A+B+D. Re-encoding as [\"A\",\"B\",\"D\"] keeps the same letters.",
                       "You were right to mark A, B and D - those are correct, but the key was stored in a broken format, so your answer didn't match. It's fixed now.")],
         "other_findings": [F("solution_missing", [], 0.7,
                              "Solution is only 'conceptual Based of field force F=q(V×B) F=qE'; it never explains why C is false. Needs a proper solution (faculty or solution_missing run).")]},
    39: {"question_assessment": "Correct: ω = π/8, π = A(π/8)(1/√2), so A = 8√2 m (D). Solution has '−' where '=' was meant in v = dx/dt = Aω cos ωt, and 'π/8 = rad/s'.",
         "reports": [R("R030", "no_error", None, [], 0.94,
                       "π = A(π/8)cos45° -> A = 8√2 m = key D; blind solve agrees. 4√2 = 8/√2 comes from multiplying by cos45° instead of dividing.",
                       "8√2 m is correct. With ω = π/8, v = Aω cos(ωt) at t = 2 s gives π = A(π/8)(1/√2), so A = 8√2 m - 4√2 comes from multiplying by 1/√2 instead of dividing by it.")],
         "other_findings": [F("notation", [E("solution", "<mi> v </mi><mo>&minus;</mo><mfrac>", "<mi> v </mi><mo>=</mo><mfrac>"),
                                           E("solution", "</mfrac><mo>&minus;</mo><mi> A </mi>", "</mfrac><mo>=</mo><mi> A </mi>")], 0.85,
                              "Solution reads 'v − dx/dt − Aω cos ωt'; the '=' signs became minus signs.")]},
    40: {"question_assessment": "Correct: H = R gives tan θ = 4 (B).",
         "reports": [R("R028", "no_error", None, [], 0.94,
                       "u²sin²θ/2g = u²·2sinθcosθ/g -> tanθ = 4 = key B; blind solve agrees. tan⁻¹2 drops the factor 2 in sin 2θ.",
                       "tan⁻¹(4) is correct. Setting H = R gives sin²θ/2g = 2 sinθ cosθ/g, so tanθ = 4 - the 2 from sin 2θ = 2 sinθ cosθ is easy to miss.")],
         "other_findings": []},
    41: {"question_assessment": "Correct: shift = 0.08 m = 8 cm, and the stem asks for cm.",
         "reports": [R("R032", "no_error", None, [], 0.95,
                       "Shift = 0.08 m; the stem asks for the answer in cm, so 8 is right (detector's power-of-ten flag is the m->cm conversion).",
                       "Calculation bilkul sahi hai - shift 0.08 m hi aata hai. Par question shift cm me poochh raha hai, aur 0.08 m = 8 cm, isliye answer 8 hai.")],
         "other_findings": []},
    42: {"question_assessment": "Key B is correct, but this neuron physiology question (refractory period) is filed as Botany / The Living World; it belongs to Zoology / Neural Control and Coordination.",
         "reports": [R("R023", "defect", "wrong_chapter", [E("chapter", "The Living World", "Neural Control and Coordination"), E("subject", "Botany", "Zoology")], 0.95,
                       "Absolute refractory period (Na+ channel inactivation) is NCERT Class 11 Neural Control and Coordination, a Zoology chapter; filed under Botany / The Living World.",
                       "Good catch - this question belongs to Neural Control and Coordination (Zoology), not The Living World. A faculty member is moving it to the right chapter.")],
         "other_findings": []},
}


def main():
    screens = {r["reportId"]: comments.screen(r["comment"]) for r in reports}
    groups = {}
    for r in sorted(reports, key=lambda r: r["reportedAt"]):
        groups.setdefault(r["questionId"], []).append(r)
    jsys, jschema = prompts.judge_system(taxonomy), prompts.judge_schema(taxonomy)
    solver_store, judge_store = {}, {}
    for i, qid in enumerate(IDS):
        rec = recs[qid]
        solve = SOLVES[i]
        solver_store[qid] = {"request_sha256": request_hash("solver", prompts.SOLVER_SYSTEM, prompts.solver_user(rec), prompts.SOLVER_SCHEMA),
                             "output": solve, "source": SOURCE}
        det = detectors.run(rec)
        reps = groups.get(qid, [])
        juser = prompts.judge_user(rec, det, solve, reps, screens)
        out = JUDGE[i]
        assert {x["reportId"] for x in out["reports"]} == {r["reportId"] for r in reps}, (i, qid)
        judge_store[qid] = {"request_sha256": request_hash("judge", jsys, juser, jschema), "output": out, "source": SOURCE}
    REPLAY_DIR.mkdir(exist_ok=True)
    for name, store in (("solver", solver_store), ("judge", judge_store)):
        (REPLAY_DIR / f"{name}.json").write_text(json.dumps(store, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"wrote {len(solver_store)} solver and {len(judge_store)} judge recordings")


if __name__ == "__main__":
    main()
