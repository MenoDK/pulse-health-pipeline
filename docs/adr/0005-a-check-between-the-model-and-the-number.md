# ADR 0005: A check between the model and the number

Status: Accepted

## Context
Indicators are computed in code, from exact counts, and each is scored as an exact fraction. A short summary in prose
is useful, and a language model can write it. A model can also write a different number than the one it was given, and
nobody reading a fluent paragraph will notice.

## Decision
1. **The numbers are never produced by the model.** The report is computed first. A narrator (a template, or a model
   behind the same `Narrator` interface) only turns it into prose.
2. **The prose is checked against the report before anyone reads it** (`narrate`). Every number in the text must be one
   the report contains, written the way the report writes it, **and in the same role**: a figure followed by a percent
   sign must be one of the report's percentages; a bare figure one of its counts, weights, dates or its score. "63%"
   cannot pass just because 63 happens to be a count.
3. **A figure is compared whole.** 63.0 is in the report; 63 and 6.3 are not. A text may not round a figure or take a
   piece of it.
4. **A token shaped like a stored pseudonym is refused.**
5. **A text that fails is replaced by the template's own text**, and the response says it was replaced and why, so a
   caller can tell the difference.
6. **A narrator that raises is replaced too.** The report never depends on the narrator being up.

## Rejected alternatives
- **Trust the model and ask it to be careful.** A prompt is a request, not a guarantee.
- **Ask a second model to judge the first.** It can be wrong in the same way, and it costs another call.
- **Compare the digits only, without roles.** It lets a model quote 63 percent where 63 is a count: the exact failure
  that matters.
- **Show the prose and the table side by side and let the reader compare.** Nobody does.

## Consequences
- (+) A wrong number cannot reach the reader through the prose. The lab lets a visitor switch a narrator that invents,
  one that rounds and one that leaks a pseudonym, and watch each refused.
- (−) **The check is on digits.** A number spelled out in words ("seventy percent") is not detected. The README lists it.
- (−) A model that writes correct prose in an unusual number format is refused and replaced by the template. That is the
  safe direction.
