# Implementation Plan — NL-to-SQL Analytics Copilot

Scoped for a solo student build, evenings/weekends, over **4 weeks**. Each week ends with something demoable, so if you run out of time after Week 2 or 3, you still have a working portfolio piece.

## Week 1 — Foundation (Data + Skeleton)
**Goal: a real, realistic database and a backend that can talk to it.**
- [ ] Design a business-realistic schema (recommend: e-commerce — `customers`, `orders`, `order_items`, `products`, `regions`) — this is more relatable to any interviewer than an obscure dataset
- [ ] Seed with realistic data (1000s of rows, not 20) — can generate with Faker/Python for realism, or use a real open e-commerce dataset (e.g. Brazilian Olist dataset) and load it into Postgres
- [ ] Set up FastAPI skeleton with a working `/schema` endpoint
- [ ] Manually test raw LLM SQL generation in a notebook first (no app yet) — confirm the model can produce reasonable SQL given your schema before you build infrastructure around it
- **Demo-able at end of week:** a script that takes a hardcoded question and prints back an LLM-generated SQL query

## Week 2 — Core Pipeline (Generation + Safety)
**Goal: question in, safe validated SQL out.**
- [ ] Build the Schema Context Builder (auto-pulls schema + sample rows into the prompt)
- [ ] Write the system prompt with strict rules + 3–5 few-shot examples
- [ ] Integrate sqlglot validator: SELECT-only enforcement, column/table existence check, auto-LIMIT injection
- [ ] Wire up read-only DB execution with timeout
- [ ] Manually test 10–15 varied questions, log which fail and why (this becomes your seed evaluation set)
- **Demo-able at end of week:** `/ask` endpoint that takes NL question → returns SQL + results as JSON, with unsafe queries correctly blocked

## Week 3 — Self-Correction + Frontend
**Goal: the loop that makes this "smart," plus a UI a recruiter can actually click through.**
- [ ] Implement correction loop: capture validator/DB errors → re-prompt LLM → retry (max 3)
- [ ] Add the Explanation Layer (plain-English answer + suggested chart type)
- [ ] Build Next.js chat UI: input box, SQL panel (collapsible/editable), results table, chart, answer text
- [ ] Wire frontend to backend end-to-end
- **Demo-able at end of week:** full working app, deployable, screenshot-worthy

## Week 4 — Evaluation, Metrics, and Polish
**Goal: turn this from "a project" into "a measured system" — this week is what makes the resume bullet credible.**
- [ ] Hand-write a 25–30 question benchmark set spanning easy (single table filter) → medium (joins, aggregation) → hard (subqueries, window functions)
- [ ] Run the benchmark, log: first-try success rate, success rate after correction, average correction attempts, average latency
- [ ] Write these numbers into your README (e.g. "87% first-try, 96% after self-correction, 30-question benchmark")
- [ ] Deploy (Render for backend, Vercel for frontend)
- [ ] Write README with architecture diagram, demo GIF, and the benchmark table
- [ ] Record a 60–90 second demo video/GIF for your LinkedIn post

## Definition of Done
- [ ] Zero unsafe queries execute against the DB, even under adversarial test questions ("delete all orders", "drop the customers table")
- [ ] Benchmark accuracy numbers are real, measured, and documented in the README
- [ ] Live deployed link works
- [ ] You can explain, in one sentence, why synthetic benchmark questions with known-correct SQL are the right way to validate this (same "known ground truth" logic as your Causal Impact project — keeps your project narrative consistent)

## Stretch Goals (only if Weeks 1–4 finish early)
- Query history with the ability to re-run and compare past questions
- Support for a second schema (so you can show it's not hardcoded to one business domain)
- Cost/latency tracking per query (shows you think about production concerns, not just correctness)
