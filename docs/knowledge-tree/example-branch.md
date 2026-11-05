# Example branch: caching strategy

**Root question:** how should reads be served when the catalogue has 2 million rows and a p95 budget of 200 ms?

Maturity: **1 of 4**: framed (a question and a scale exist); not yet explored, measured or decided.

## Scale, with numbers

| Fact | Value | Source |
| --- | --- | --- |
| rows in the catalogue | 2,000,000 | measured, 2026-11-05 |
| read/write ratio | 95/5 | assumed: replace with a measurement |

## Open questions

1. What is the p95 without any cache? (measure before designing)
2. Which reads are hot enough to deserve one?

## Promotion rule

Level 2 needs a measurement of question 1. Level 3 needs a prototype that meets the budget. Level 4 needs an
[ADR](../adr/README.md) and production numbers. Nothing is promoted on opinion.
