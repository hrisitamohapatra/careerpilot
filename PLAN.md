# CareerPilot Build Plan

## Phases
- [x] 1. Setup + Resume QA (scaffold, config, light theme, upload validation, DB, parsing, Chroma, QA node, UI)
- [x] 2. JD Match (extraction, code overlap, weighted score, DB save, Match tab)
- [x] 3. Job Search and Rank agent (adapters, aggregator, cache, sample fallback, refine loop, ranking, Jobs tab)
- [x] 4. Improve/Generate + Apply and Track (drafts, approval, guarded email, calendar + .ics)
- [x] 5. Router + full LangGraph
- [x] 6. Adaptive Mock Interview
- [x] 7. Polish, security pass, smoke.py, tests, README
- [x] 8. Reminder agent (replaces the Tracker tab): extract, validate, plan, approve, add to Google Calendar / .ics

- [x] 9. Frontend redesign: sidebar navigation (Dashboard, My Profile, Workspace, Reminders, Interview), cream/navy/orange theme, serif headings, mono status pills

## Decisions / simplifications
- Tracker tab replaced by the Reminders tab (user request). Sent applications are still saved in the `applications` table and listed in an expander there; follow-up events also appear in the Reminders list.
- Reminder agent: the model only reads dates from text. Code validates (future, within 400 days), plans the reminders, and creates events after approval only. Regex fallback when no Groq key.
- Reminders are one-way inserts; duplicates are detected in SQLite (key = kind, title, date, time).
- Approval gate is an explicit review screen + per-draft DB claim (no LangGraph `interrupt`); simpler across Streamlit reruns.
- Remote adapters live in one file `remote_sources.py` instead of four.
- Remotive allows ~4 requests/day, so Remotive, RemoteOK and Arbeitnow fetch the whole feed once per 24 h and filter locally.
- Jooble and Arbeitnow docs are not publicly readable; those adapters follow the spec's request shape and are not verified against live docs.
- Without GROQ_API_KEY every AI step has a labelled code-only fallback (so smoke.py, tests and the demo never break).
- Calendar events use dateTime + timeZone "Asia/Kolkata" (no tz database needed on Windows); the .ics file uses UTC (10:00 IST = 04:30Z).
- Sample listings act as a searchable fallback source, so the refine loop also works offline.
- Pins are from a Python 3.13 environment; relax a pin if your Python cannot install it.

## Not verified in the build sandbox
- Real Groq responses (no key), real Gmail send, real Google Calendar OAuth, the MiniLM embedding download (network blocked here), and Unit tests cover the logic with fakes. The new UI was checked in headless Chromium screenshots (fonts fall back offline; Google Fonts load on a normal connection).
