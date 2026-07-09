# End-to-End Workflow — NL-to-SQL Analytics Copilot

## Aim
Let a non-technical business user ask a plain-English question and get a **correct, safe, explained** answer from a real database — without knowing SQL, and without the system silently hallucinating a wrong answer.

## Why this matters (the business case, for your README/interview)
Analysts spend a large share of their time answering the same category of repetitive ad-hoc question ("what were sales last week by region"). A copilot that safely self-serves these reduces analyst turnaround time from hours to seconds, and this exact category of product (text-to-SQL copilots) is an active area companies are building internally in 2026 — so this project isn't a toy exercise, it mirrors real internal tooling.

## End-to-End Flow (Aim → Input → Process → Result)

**1. Aim:** Answer "Which region had the biggest drop in repeat customers last quarter?"

**2. Input:** User types the question into the chat UI. No SQL knowledge required.

**3. Process:**
- Backend fetches the live schema (tables: `customers`, `orders`, `regions`) + sample rows
- LLM is prompted with schema + rules + the question → generates a candidate SQL query with a join across `orders` and `regions`, a quarter-over-quarter repeat-customer calculation, and an `ORDER BY` + `LIMIT`
- Safety Validator parses the SQL: confirms it's SELECT-only, confirms every column referenced actually exists, injects a LIMIT if missing
- If validation fails (e.g. model referenced a non-existent `customer_region` column instead of joining properly) → the specific error is sent back to the LLM → it retries with the correction, referencing the real join path
- Once valid, query executes against a **read-only** connection with a timeout
- Results (a small table of regions + repeat-customer drop %) are sent back to the LLM's Explanation Layer, which produces: *"The North region saw the largest decline, down from 42% to 31% repeat customers quarter-over-quarter."*

**4. Result delivered to user:**
- The plain-English answer (front and center)
- The results table
- An auto-generated bar chart comparing regions
- The exact SQL used (collapsible, editable — so a technical user can verify or tweak it)

**5. Logged for evaluation:** question, generated SQL, number of correction attempts (0 in a clean case, up to 3 if corrections were needed), and final success/failure — feeding into your benchmark accuracy metric.

## The Value Chain (why each step earns its place)
| Step | Without it | With it |
|---|---|---|
| Schema context injection | Model guesses column names → frequent hallucination | Model only ever references real columns |
| Safety validator | Any generated SQL runs as-is — dangerous | Only verified SELECT-only, schema-valid queries execute |
| Self-correction loop | First mistake = dead end, user sees an error | System recovers from its own mistakes, like a junior analyst double-checking their query |
| Explanation layer | User has to read a results table themselves | User gets a direct, plain-English answer |
| Evaluation log | "It seems to work" (unverifiable claim) | A measured, defensible accuracy number for your resume |

## Resume-ready summary line
> Built an end-to-end NL-to-SQL analytics copilot (FastAPI, Claude API, sqlglot, Next.js) that converts plain-English business questions into validated, safety-checked SQL with a self-correction loop, achieving [X]% first-try and [Y]% post-correction accuracy on a 30-question benchmark.

Fill in [X]/[Y] once you run the Week 4 evaluation — don't estimate these numbers, measure them. A real, slightly-imperfect number ("87%, not 100%") is far more credible to an interviewer than a suspiciously perfect claim.
