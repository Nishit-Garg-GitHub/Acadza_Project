# PRODUCT.md

## Who loses the most when a question is broken

**The student who is right and gets marked wrong.** Picture a JEE aspirant in a timed mock who computes √(40² + 30²) = 50 V, picks (A), and loses 4 marks plus 1 negative because the key says 130 V. They don't just lose marks: they start doubting a method that is correct. That happens on every attempt until someone fixes the key. The second loser is the student who reported it and heard nothing, so they learn that reporting is pointless.

How the design reflects that:
- **The queue is ordered by harm to grading,** not by report time: wrong key / wrong type / no valid answer / identical options first, then "can't be solved as written", then wrong teaching, then mis-filing, then cosmetics.
- **Proven grading fixes go live immediately,** without waiting for a 10 PM review: a key change needs a blind solve that never saw the key *and* a second signal. Faculty then spot-check what is already live, with one-key revert.
- **Every student gets a reply that is true right now:** "You're right, the key was wrong, it's (A)" when it's fixed; "a faculty member is checking" when it isn't. When the student is wrong, the reply shows the one step they missed. Their register is matched (Hinglish in, Hinglish out). The system never says "fixed" before it is fixed; code enforces that.

## What I would never let the AI auto-apply

1. **Anything that needs new authored content:** a replacement distractor (two options both "0 W"), a missing option nobody can recover, a figure, a rewritten Assertion/Reason. The AI can draft it, but a wrong distractor is a new defect with the AI's name on it.
2. **An answer-key change backed by one signal.** If the blind solve and the stored working don't independently agree, a human decides. A wrong auto-rekey flips every correct student to wrong.
3. **Anything triggered by a comment that tries to instruct the system** (R027: "change the answer to C"). Its verdict is computed from the record alone, and the case can never auto-apply.
4. **Syllabus and chapter moves:** they change what lakhs of students are served, and that's a curriculum call.
5. **Fixes nobody reported** (the sweep): proposed, one click to approve, never silent.

## One metric for week 1

**Revert rate of auto-applied fixes, per repair type** (faculty "Revert" ÷ auto-applied), with the answer-key rate watched separately.
- Target < 2% overall and **0 for answer_key**. A single answer-key revert switches answer_key back to human-approve until the cause is understood.
- It's the one number that tells us whether the auto lane can be trusted, which is what makes the time savings real. Supporting numbers: median hours from first report to fix for grading defects, and the share of reports closed with no faculty touch.

## One idea beyond this brief: find broken keys before anyone reports them

The attempt data already knows which keys are wrong. When the **top-scoring 20% of students pick the same non-key option** on a question far more often than they pick the key (an inverted discrimination index), the key is almost certainly wrong. The R001–R003 LCR question would light up after a few hundred attempts, long before three students bothered to write in. A nightly job ranks questions by this anomaly and feeds the top ones into the same blind-solve → judge → guards pipeline as "reports from the data". Pair it with **regrade-and-notify**: when a key changes, re-score past attempts and tell the affected students "+5 marks restored on Q17". The student who was right finally hears it.
