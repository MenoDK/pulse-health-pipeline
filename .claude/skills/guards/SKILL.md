---
name: guards
description: Use when a class of mistake has happened more than once, or when asked to "make sure X never happens again". Turns the lesson into a test that fails the build instead of a sentence in a document.
---

# Guards

A guard is a test that fails when a *class* of error comes back. Advice in a document is forgotten; a red build is not.

## Writing one

1. **Derive, do not list.** Compute the set under test from the code or disk (routes, files, tables), so a new
   member is covered automatically. A hand-kept list is a guard that rots.
2. **Accuse at the defect's granularity.** `expect({ [name]: value })` so the failure names the culprit, not "false".
3. **Every dismissal carries a written reason**, and a dismissal that stops matching is itself reported.
4. **Prove it can fail.** Break the thing on purpose, watch the guard go red, restore. A guard never seen
   failing is decoration. Do it again with a *partial* break, because the sloppy version of a guard passes the total one.
5. **Prove it sees something.** Assert it examined more than zero items; otherwise it passes by finding nothing.

## Beware

A test that does not actually run while a green number is shown. Check the count goes up when you add one.
