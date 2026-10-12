"""CareerPilot: Streamlit app (run with: streamlit run app.py)."""
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd
import streamlit as st

from careerpilot import config, db, graph, llm, parsing, security, store, ui_theme, vectorstore
from careerpilot.nodes import apply as apply_mod
from careerpilot.nodes import interview, match
from careerpilot.nodes import reminders
from careerpilot.nodes import jobs as jobs_mod
from careerpilot.schemas import Job
from careerpilot.tools import calendar_tool, email_tool
from careerpilot.tools.job_sources import aggregator

plain = ui_theme.plain
CITIES = [
    "Anywhere in India", "Bengaluru", "Hyderabad", "Pune", "Chennai", "Mumbai", "Delhi NCR", "Gurugram",
    "Noida", "Kolkata", "Ahmedabad", "Bhubaneswar", "Jaipur", "Kochi",
]
PAGES = ["Dashboard", "My Profile", "Workspace", "Reminders", "Interview"]
ICONS = {
    "Dashboard": ":material/dashboard:", "My Profile": ":material/person:", "Workspace": ":material/forum:",
    "Reminders": ":material/event:", "Interview": ":material/mic:",
}
WORKSPACE = ["Chat", "Match", "Jobs", "Apply"]
# Widget values that must survive a page change (Streamlit drops widget state when the widget is not drawn).
KEEP = ("nav", "ws", "target_role", "city", "include_remote", "enabled_sources", "jd_text", "user_name",
        "profile_resume", "remind_text", "remind_company", "remind_role")
KEEP_PREFIX = ("to_", "sub_", "body_", "fu_", "cl_", "ans_")

st.set_page_config(page_title="CareerPilot", page_icon=":material/confirmation_number:", layout="wide")
ui_theme.apply()
ss = st.session_state


def init() -> None:
    if "session_id" in ss:
        return
    ss.session_id = db.new_session()
    ss.update(
        resume_id=None, resume_text="", chat=[], last_match=None, jobs=[], job_log=[], job_statuses={},
        used_sample=False, selected_job=None, draft=None, apply_results={}, interview=interview.new_interview(),
        last_turn=None, limiter=security.SendLimiter(),
    )


def defaults() -> None:
    ss.setdefault("nav", "Dashboard")
    ss.setdefault("ws", "Chat")
    ss.setdefault("target_role", "")
    ss.setdefault("city", CITIES[0])
    ss.setdefault("include_remote", False)
    ss.setdefault("enabled_sources", list(aggregator.DEFAULT_ENABLED))
    ss.setdefault("jd_text", "")
    ss.setdefault("user_name", "")
    ss.setdefault("profile_resume", "")
    ss.setdefault("resume_source", "pasted")
    ss.setdefault("profile_msg", None)
    ss.setdefault("reminder_plan", [])
    ss.setdefault("reminder_log", [])
    ss.setdefault("reminder_results", None)
    ss.setdefault("plan_id", 0)


init()
defaults()

# A jump requested on the previous run (a button on another page) is applied before any widget is drawn.
if "_goto" in ss:
    _page, _sub = ss.pop("_goto")
    ss.nav = _page
    if _sub:
        ss.ws = _sub
for _k in list(ss.keys()):
    if _k in KEEP or _k.startswith(KEEP_PREFIX):
        ss[_k] = ss[_k]


def goto(page: str, sub: str | None = None) -> None:
    ss._goto = (page, sub)


def reset_data() -> None:
    """Button callback: wipe everything this session stored, then start fresh on the next run."""
    if ss.get("resume_id"):
        vectorstore.delete_resume_vectors(ss.resume_id)
    db.delete_session_data(ss.session_id)
    for k in list(ss.keys()):
        del ss[k]


def on_upload() -> None:
    f = ss.get("resume_file")
    if f is None:
        return
    try:
        ss.profile_resume = parsing.extract_text(f.name, f.getvalue())
        ss.resume_source, ss.profile_msg = "upload", None
    except security.ValidationError as e:
        ss.profile_msg = ("error", str(e))
    except Exception:  # noqa: BLE001
        ss.profile_msg = ("error", "Could not read that file. Paste the text instead.")


def badges(items: list, color: str) -> None:
    """Skill chips on one wrapping line. Text is escaped so it cannot become markdown."""
    if items:
        st.markdown(" ".join(f":{color}-badge[{plain(x)}]" for x in items))


def need_resume(where: str) -> bool:
    if ss.resume_id:
        return False
    with ui_theme.card():
        ui_theme.card_head("Add your resume first", "Everything here works from your resume. It takes a minute in My Profile.")
        st.info("Upload a resume to get started.")
        st.button("Go to My Profile", type="primary", key=f"goprofile_{where}", on_click=goto, args=("My Profile",))
    return True


# =============================================================== sidebar
with st.sidebar:
    ui_theme.brand()
    st.radio("Navigate", PAGES, key="nav", label_visibility="collapsed", format_func=lambda p: f"{ICONS[p]} {p}")
    ui_theme.side_foot("Groq AI on" if llm.available() else "Offline mode, no Groq key")
    st.caption("Your data stays on this machine, except the text sent to Groq to write answers.")


# ================================================================ dashboard
def page_dashboard() -> None:
    name = ss.user_name.strip()
    ui_theme.page_header(
        "Overview", f"Welcome back, {name}" if name else "Welcome back",
        "Your search at a glance: where applications stand, what is coming up, and what to do next.",
    )
    apps = store.list_applications(ss.session_id)
    counts = Counter(a["status"] for a in apps)
    tone = {"Saved": "neutral", "Applied": "slate", "Interview": "orange", "Offer": "green", "Rejected": "red"}
    ui_theme.pills([(s, counts.get(s, 0), tone[s]) for s in store.APP_STATUSES])

    rows = store.list_reminders(ss.session_id)
    today = datetime.now(calendar_tool.IST).date()
    upcoming = [r for r in rows if r["event_date"] >= today.isoformat()]

    c1, c2, c3, c4 = st.columns(4)
    with c1, ui_theme.card():
        st.metric("Resume", "Ready" if ss.resume_id else "Missing")
        st.caption(f"{len(ss.resume_text):,} characters" if ss.resume_id else "Add it in My Profile")
    with c2, ui_theme.card():
        lm = ss.last_match
        st.metric("Last match", f"{lm['overall_score']:.0f}" if lm else "None")
        st.caption("out of 100" if lm else "Score a job description")
    with c3, ui_theme.card():
        st.metric("Jobs ranked", len(ss.jobs))
        st.caption("in your last search" if ss.jobs else "Run a search")
    with c4, ui_theme.card():
        st.metric("Coming up", len(upcoming))
        st.caption("reminders scheduled" if upcoming else "Nothing scheduled")

    left, right = st.columns([3, 2])
    with left, ui_theme.card():
        ui_theme.card_head("Coming up", "Deadlines, tests and interviews you added to your calendar.")
        if upcoming:
            ui_theme.timeline([(r["event_date"], r["kind"]) for r in upcoming[:4]], today)
        else:
            st.caption("Nothing yet. Paste a job post and the agent finds the dates.")
        st.button("Add reminders", key="dash_rem", on_click=goto, args=("Reminders",))
    with right, ui_theme.card():
        ui_theme.card_head("Next steps")
        steps = [
            (bool(ss.resume_id), "Add your resume", ("My Profile", None)),
            (bool(ss.target_role.strip()), "Set a target role and city", ("My Profile", None)),
            (bool(ss.jobs), "Find and rank jobs", ("Workspace", "Jobs")),
            (bool(apps), "Send an application", ("Workspace", "Apply")),
            (bool(rows), "Add a deadline reminder", ("Reminders", None)),
            (ss.interview["status"] != "idle", "Practise an interview", ("Interview", None)),
        ]
        for i, (done, label, target) in enumerate(steps):
            a, b = st.columns([5, 1], vertical_alignment="center")
            a.markdown((":material/check_circle: " if done else ":material/radio_button_unchecked: ") + label)
            b.button("", icon=":material/arrow_forward:", key=f"dash_step_{i}", on_click=goto, args=target)

    with ui_theme.card():
        ui_theme.card_head("Connections", "Everything works without these; each one unlocks more.")
        items = [("Groq AI", None, "green" if llm.available() else "off")]
        items += [(n if aggregator.source_state(n) == "ready" else f"{n} not set", None,
                   "green" if aggregator.source_state(n) == "ready" else "off") for n in aggregator.SOURCES]
        items += [("Gmail" if email_tool.smtp_configured() else "Gmail not set", None, "green" if email_tool.smtp_configured() else "off"),
                  ("Calendar" if calendar_tool.is_connected() else "Calendar not set", None,
                   "green" if calendar_tool.is_connected() else "off")]
        ui_theme.pills(items, tight=True)


# ================================================================== profile
def page_profile() -> None:
    c1, c2 = st.columns([5, 1.6], vertical_alignment="bottom")
    with c1:
        ui_theme.page_header("Your details", "My Profile", "Update your resume, target role and search preferences in one place.")
    with c2:
        save = st.button("Save changes", type="primary", key="save_profile", use_container_width=True)

    st.text_input("Your name", key="user_name", placeholder="Used for the greeting on your dashboard")

    with ui_theme.card():
        ui_theme.card_head("Resume", "Upload your latest file and keep the text below current. The text is what gets scored and rewritten.")
        st.file_uploader("Upload resume", type=["pdf", "docx"], key="resume_file", on_change=on_upload,
                         label_visibility="collapsed", help="PDF or DOCX, up to 5 MB. Scanned images cannot be read; paste the text instead.")
        if ss.profile_msg:
            st.error(ss.profile_msg[1])
        st.text_area("Resume text", key="profile_resume", height=260, placeholder="Paste your resume content here...")
        if ss.resume_id:
            st.caption(f"Saved version: {len(ss.resume_text):,} characters. Click Save changes after editing the text.")

    with ui_theme.card():
        ui_theme.card_head("Job search preferences", "The role, city and boards every match score and job search is measured against.")
        a, b = st.columns(2)
        a.text_input("Target role", key="target_role", placeholder="Backend Engineer")
        b.selectbox("Target city", CITIES, key="city")
        with st.container(key="remote-card"):
            x, y = st.columns([8, 1], vertical_alignment="center")
            x.markdown('<p class="row-title">Include remote roles</p>'
                       '<p class="row-desc">Rank remote-friendly posts alongside your city.</p>', unsafe_allow_html=True)
            y.toggle("Include remote roles", key="include_remote", label_visibility="collapsed")
        st.pills(
            "Job sources", list(aggregator.SOURCES), selection_mode="multi", key="enabled_sources",
            format_func=lambda n: n if aggregator.source_state(n) == "ready" else f"{n} (key not set)",
        )
        st.caption("Sources marked key not set are skipped. With none ready, the bundled sample listings are searched.")

    with ui_theme.card():
        ui_theme.card_head("Your data", "Your resume text is sent to the Groq API to write answers. Job searches send only a role and a city. "
                           "Use sample or non-sensitive data for demos.")
        st.button("Delete my data", icon=":material/delete:", key="delete_data", on_click=reset_data)

    if save:
        text = ss.profile_resume.strip()
        try:
            if not text:
                st.toast("Preferences saved. Add your resume text to use the Workspace.")
            else:
                cleaned = security.clean_text(text)
                if ss.resume_id and cleaned == ss.resume_text:
                    st.toast("Saved")
                else:
                    with st.status("Reading and indexing your resume...") as s:
                        old = ss.resume_id
                        rid = db.save_resume(ss.session_id, ss.resume_source, cleaned)
                        vectorstore.index_resume(rid, parsing.split_sections(cleaned))
                        if old:
                            vectorstore.delete_resume_vectors(old)
                        s.update(label="Resume ready", state="complete")
                    ss.update(resume_id=rid, resume_text=cleaned, chat=[], last_match=None, interview=interview.new_interview())
                    st.toast("Saved. Your resume is ready.")
        except security.ValidationError as e:
            st.error(str(e))
        except Exception:  # noqa: BLE001
            st.error("Could not index the resume. Check your internet connection for the first model download and try again.")


# ================================================================ workspace
def ws_chat() -> None:
    for m in ss.chat:
        with st.chat_message(m["role"]):
            st.markdown(plain(m["content"]))
            if m.get("sources"):
                with st.expander("Sources from your resume"):
                    for sec, snip in m["sources"]:
                        st.markdown(f"**{plain(sec)}**")
                        st.markdown(plain(snip))
    if not ss.chat:
        st.caption("Try: What are my strongest skills?  |  Score my resume against the job description  |  Find jobs for me  |  "
                   "Remind me: interview on 5 Nov at 11 am  |  Start a mock interview")
    q = st.chat_input("Ask about your resume, or tell me what to do")
    if q:
        q = security.cap_chat(q)
        ss.chat.append({"role": "user", "content": q})
        state = {
            "user_message": q, "session_id": ss.session_id, "resume_id": ss.resume_id, "resume_text": ss.resume_text,
            "target_role": ss.get("target_role", "").strip(), "city": ss.get("city", ""),
            "include_remote": ss.get("include_remote", False), "enabled_sources": ss.get("enabled_sources", []),
            "jd_text": ss.get("jd_text", "").strip(), "last_match": ss.last_match, "jobs": ss.jobs,
            "selected_job": ss.selected_job, "interview": ss.interview,
        }
        try:
            with st.status("Working on it...") as s:
                out = graph.run_turn(state)
                s.update(label="Done", state="complete")
            ss.chat.append({"role": "assistant", "content": out.get("final_response", ""), "sources": out.get("sources", [])})
            if out.get("last_match"):
                ss.last_match = out["last_match"]
            if out.get("jobs") is not None and out.get("intent") == "jobs":
                ss.jobs, ss.job_log = out["jobs"], out.get("job_log", [])
                ss.job_statuses, ss.used_sample = out.get("job_statuses", {}), out.get("used_sample", False)
            if out.get("draft") and out.get("intent") == "apply":
                ss.draft = out["draft"]
            if out.get("interview"):
                ss.interview = out["interview"]
            if out.get("intent") == "remind" and out.get("reminder_plan") is not None:
                ss.reminder_plan, ss.reminder_log = out["reminder_plan"], out.get("reminder_log", [])
                ss.reminder_results, ss.plan_id = None, ss.plan_id + 1
        except llm.LLMUnavailable as e:
            ss.chat.append({"role": "assistant", "content": str(e)})
        except Exception:  # noqa: BLE001
            ss.chat.append({"role": "assistant", "content": "Something went wrong on my side. Please try again."})
        st.rerun()


def render_match(m: dict) -> None:
    with ui_theme.card():
        c1, c2 = st.columns([1, 3], vertical_alignment="center")
        with c1:
            st.metric("Overall match", f"{m['overall_score']:.0f} / 100")
        with c2:
            st.progress(min(1.0, m["overall_score"] / 100))
            if m.get("notes"):
                st.caption(plain(m["notes"]))
    with ui_theme.card():
        ui_theme.card_head("Breakdown")
        for c in m["breakdown"]:
            a, b, d = st.columns([3, 1, 6], vertical_alignment="center")
            a.markdown(f"**{plain(c['name'])}**")
            a.caption(f"Weight {c['weight']}%")
            b.markdown(f"**{c['score']:.0f}**")
            with d:
                st.progress(min(1.0, c["score"] / 100))
                st.caption(plain(c.get("reason", "")))
    x, y = st.columns(2)
    with x, ui_theme.card():
        ui_theme.card_head("Skills you have")
        badges(m["matched_skills"][:14], "green")
        if not m["matched_skills"]:
            st.caption("No overlap found yet.")
    with y, ui_theme.card():
        ui_theme.card_head("Skills to add or learn")
        badges(m["missing_skills"][:14], "orange")
        if not m["missing_skills"]:
            st.caption("Nothing missing. Nice.")
    if m.get("suggestions"):
        with ui_theme.card():
            ui_theme.card_head("Next steps")
            for s in m["suggestions"]:
                st.markdown("- " + plain(s))


def ws_match() -> None:
    with ui_theme.card():
        ui_theme.card_head("Job description", "Paste the posting you want to score your resume against.")
        st.text_area("Job description", key="jd_text", height=190, label_visibility="collapsed",
                     placeholder="Paste a job description here...")
        jd = ss.get("jd_text", "").strip()
        go = st.button("Score this job description", type="primary", disabled=not jd)
    if go:
        with st.status("Scoring your resume against the job...") as s:
            res = match.compute_match(ss.resume_text, jd, use_llm=llm.available())
            jd_id = db.save_jd(ss.session_id, "Pasted job description", "", jd[:8000])
            store.save_match(ss.resume_id, jd_id, res.model_dump())
            ss.last_match = res.model_dump()
            s.update(label="Scored", state="complete")
    if ss.last_match:
        render_match(ss.last_match)


def run_jobs() -> None:
    inputs = {
        "resume_text": ss.resume_text, "target_role": ss.get("target_role", "").strip(), "city": ss.get("city", ""),
        "include_remote": ss.get("include_remote", False), "enabled_sources": ss.get("enabled_sources", []),
        "session_id": ss.session_id,
    }
    with st.status("Running the job search agent...", expanded=True) as status:
        def on_update(node: str, upd: dict) -> None:
            if node == "plan_keywords":
                st.markdown(plain("Planned searches: " + "; ".join(upd.get("queries", []))))
            for line in upd.get("rounds", []):
                st.markdown(plain(line))
            if node == "evaluate_results" and not upd.get("need_more"):
                st.markdown("Enough results. Scoring the best listings against your resume...")

        final = jobs_mod.run_job_agent(inputs, on_update)
        status.update(label="Search finished", state="complete", expanded=False)
    ss.jobs, ss.job_log = final.get("ranked", []), final.get("rounds", [])
    ss.job_statuses, ss.used_sample = final.get("statuses", {}), final.get("used_sample", False)


def band(score: float) -> str:
    return "high" if score >= 70 else "mid" if score >= 45 else "low"


BAND_LABEL = {"high": ("Strong match", "green"), "mid": ("Good fit", "orange"), "low": ("Stretch", "slate")}


def start_application(r: dict) -> None:
    ss.selected_job = r
    ss.draft = apply_mod.draft_for_job(ss.session_id, ss.resume_text, r)


def apply_cb(i: int) -> None:
    """Apply button callback: draft the application, then open the Apply section on the next run."""
    start_application(ss.jobs[i])
    goto("Workspace", "Apply")


def ws_jobs() -> None:
    role = ss.get("target_role", "").strip()
    with ui_theme.card():
        a, b = st.columns([4, 1.4], vertical_alignment="center")
        with a:
            ui_theme.card_head("Find jobs", f"Searching for {role} in {ss.city}." if role else "Set a target role in My Profile first.")
        with b:
            find = st.button("Find jobs", type="primary", disabled=not role, use_container_width=True)
        if not role:
            st.button("Open My Profile", key="jobs_to_profile", on_click=goto, args=("My Profile",))
    if find:
        run_jobs()

    if ss.job_log:
        with st.expander("What the agent did", expanded=False):
            for line in ss.job_log:
                st.markdown(plain(line))
    if ss.job_statuses:
        st.caption("Sources: " + "; ".join(f"{k}: {v}" for k, v in ss.job_statuses.items()))
    if ss.used_sample:
        st.warning("These are sample listings, not live jobs. No live source returned relevant results "
                   "(add API keys in .env to search real listings).")

    if ss.jobs:
        with st.expander("Table view"):
            st.dataframe(
                pd.DataFrame([{
                    "Score": round(r["score"]), "Title": r["job"]["title"], "Company": r["job"]["company"],
                    "Location": r["job"]["location"], "Salary": Job(**r["job"]).salary_text(),
                    "Source": r["job"]["source"], "Missing": ", ".join(r["missing"][:5]), "Link": r["job"]["url"],
                } for r in ss.jobs]),
                column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open")},
                hide_index=True,
            )
        for i, r in enumerate(ss.jobs):
            j = Job(**r["job"])
            bd = band(r["score"])
            with st.container(border=True, key=f"pass-{bd}-{i}"):
                a, b, c = st.columns([6, 2, 2])
                with a:
                    ui_theme.pills([(BAND_LABEL[bd][0], None, BAND_LABEL[bd][1])], tight=True)
                    st.markdown(f"**{plain(j.title)}**")
                    st.markdown(plain(f"{j.company or 'Company not listed'}  |  {j.location or 'Location not listed'}"))
                    st.caption(f"{j.salary_text()}  |  via {plain(j.source)}")
                with b:
                    st.metric("Match", f"{r['score']:.0f}")
                with c:
                    st.button("Apply", key=f"apply_{i}", on_click=apply_cb, args=(i,))
                    if j.url:
                        st.link_button("Open listing", j.url)
                st.divider()
                x, y = st.columns(2)
                with x:
                    st.caption("You have")
                    badges(r["matched"][:6], "green")
                with y:
                    st.caption("Missing")
                    badges(r["missing"][:6], "orange")
        used = {r["job"]["source"] for r in ss.jobs}
        credits = [aggregator.SOURCES[n].attribution for n in used if n in aggregator.SOURCES and aggregator.SOURCES[n].attribution]
        if credits:
            st.caption(" | ".join(credits))


def ws_apply() -> None:
    d, sel = ss.draft, ss.selected_job
    if not d or not sel:
        with ui_theme.card():
            ui_theme.card_head("No application in progress", "Pick a job in Jobs and click Apply to draft an application.")
            st.info("Pick a job in the Jobs tab and click Apply to draft an application.")
            st.button("Go to Jobs", key="apply_to_jobs", on_click=goto, args=("Workspace", "Jobs"))
        return
    j = sel["job"]
    did = d["draft_id"]
    result = ss.apply_results.get(did)
    with st.container(border=True, key="card-apply"):
        st.markdown(f"### {plain(j['title'])}")
        st.markdown(plain(f"{j.get('company', '')}  |  {j.get('location', '')}  |  via {j.get('source', '')}  |  match {sel['score']:.0f}"))
        if j.get("url"):
            st.link_button("Open the original listing", j["url"])
        if not d.get("used_ai"):
            st.caption("This draft came from a simple template because the AI model was not available.")
        to = st.text_input("Send to", value=config.env("SMTP_USER"), key=f"to_{did}",
                           help="Listings rarely show a recruiter email. Type one, or send it to yourself to test.")
        subject = st.text_input("Subject", value=d["subject"], key=f"sub_{did}")
        body = st.text_area("Email", value=d["body"], height=260, key=f"body_{did}")
        follow = st.date_input("Follow up on", value=apply_mod.default_follow_up(), min_value=date.today(), key=f"fu_{did}")
        with st.expander("Cover letter"):
            st.text_area("Cover letter", value=d["cover_letter"], height=300, key=f"cl_{did}", label_visibility="collapsed")
            st.download_button("Download cover letter (.txt)", d["cover_letter"], file_name="cover_letter.txt")

        st.markdown(f"**On approval:** send this email to {plain(to or 'the address above')}, "
                    f"save the application, and add a calendar event on {follow.strftime('%d %b %Y')} at 10:00 IST.")
        st.caption(f"Emails sent this session: {ss.limiter.count} of {ss.limiter.limit}")
        if not calendar_tool.is_connected():
            st.caption("Google Calendar is not connected, so you will get an .ics file instead.")
            if calendar_tool.has_client_secrets() and st.button("Connect Google Calendar"):
                try:
                    calendar_tool.connect()
                    st.rerun()
                except calendar_tool.CalendarError as e:
                    st.error(str(e))
                except Exception:  # noqa: BLE001
                    st.error("Could not connect to Google Calendar. Try again.")

        c1, c2 = st.columns([1, 1])
        done = result is not None and result.get("email") in ("sent", "smtp missing")
        approve = c1.button("Approve and send", type="primary", disabled=done or ss.limiter.remaining() == 0, key=f"ok_{did}")
        cancel = c2.button("Cancel", key=f"cancel_{did}", disabled=done)
        if cancel:
            ss.draft, ss.selected_job = None, None
            st.rerun()
        if approve:
            try:
                security.validate_recipient(to), security.validate_subject(subject), security.validate_body(body)
                with st.spinner("Sending..."):
                    ss.apply_results[did] = apply_mod.execute_approved(
                        ss.session_id, sel, did, to, subject, body, follow, ss.limiter)
                st.rerun()
            except security.ValidationError as e:
                st.error(str(e))

    if result:
        if result.get("error"):
            st.error(result["error"])
        if result["email"] == "sent":
            st.success("Email sent and application saved. You can see it on the Dashboard.")
        elif result["email"] == "smtp missing":
            st.warning("Gmail sending is not set up (SMTP_USER and SMTP_APP_PASSWORD in .env), so nothing was sent. "
                       "The application is saved with the status Saved.")
            st.download_button("Download the email (.txt)", f"To: {to}\nSubject: {subject}\n\n{body}", file_name="application_email.txt")
        if result["calendar"] == "created":
            st.success("Follow-up event added to Google Calendar.")
        elif result["calendar"] == "ics only":
            st.info("Add the follow-up to any calendar app with this file.")
            st.download_button("Download follow-up (.ics)", result["ics"], file_name="follow_up.ics", mime="text/calendar")


def page_workspace() -> None:
    ui_theme.page_header("Workspace", "Search, score and apply",
                         "Ask questions about your resume, score a posting, find jobs and send an approved application.")
    if need_resume("workspace"):
        return
    st.radio("Section", WORKSPACE, key="ws", horizontal=True, label_visibility="collapsed")
    {"Chat": ws_chat, "Match": ws_match, "Jobs": ws_jobs, "Apply": ws_apply}[ss.ws]()


# =============================================================== reminders
def offsets_text(mins: list, all_day: bool) -> str:
    parts = []
    for m in mins:
        if all_day:
            k = -(-m // 1440)
            hh, mm = divmod(k * 1440 - m, 60)
            parts.append(f"{hh}:{mm:02d} the day before" if k == 1 else f"{hh}:{mm:02d}, {k} days before")
        elif m == 0:
            parts.append("at the start")
        elif m % 1440 == 0:
            n = m // 1440
            parts.append(f"{n} day{'s' if n > 1 else ''} before")
        elif m % 60 == 0:
            n = m // 60
            parts.append(f"{n} hour{'s' if n > 1 else ''} before")
        else:
            parts.append(f"{m} minutes before")
    return ", ".join(parts) or "Calendar default"


def when_text(it: dict) -> str:
    d = date.fromisoformat(it["date"]).strftime("%a %d %b %Y")
    return d + (", all day" if it.get("all_day") else f", {it['time']} IST")


def page_reminders() -> None:
    ui_theme.page_header("Calendar agent", "Reminders",
                         "Paste a job post, an email or a message. The agent finds deadlines and interview dates, "
                         "plans the reminders, and adds them to Google Calendar once you approve.")
    cal_ok = calendar_tool.is_connected()
    with ui_theme.card():
        c1, c2 = st.columns([4, 1.3], vertical_alignment="center")
        with c1:
            ui_theme.pills([("Google Calendar connected" if cal_ok else "Google Calendar not connected", None,
                             "green" if cal_ok else "off")], tight=True)
            if not cal_ok:
                st.caption("Approved reminders come as an .ics file you can import into any calendar.")
        if not cal_ok and calendar_tool.has_client_secrets():
            with c2:
                if st.button("Connect", key="connect_cal_reminders", use_container_width=True):
                    try:
                        calendar_tool.connect()
                        st.rerun()
                    except calendar_tool.CalendarError as e:
                        st.error(str(e))
                    except Exception:  # noqa: BLE001
                        st.error("Could not connect to Google Calendar. Try again.")

    with ui_theme.card():
        ui_theme.card_head("Paste text", "A job post, a recruiter email, a WhatsApp message. Anything with dates in it.")
        rtext = st.text_area("Paste text", key="remind_text", height=130, label_visibility="collapsed",
                             placeholder="Last date to apply: 30 Oct 2026. Online test on 2 Nov at 6 pm. Interview on 5 Nov at 11 am.")
        a, b = st.columns(2)
        rcompany = a.text_input("Company (optional)", key="remind_company")
        rrole = b.text_input("Role (optional)", key="remind_role")
        find = st.button("Find dates", type="primary")
    if find:
        if not rtext.strip():
            st.warning("Paste some text first.")
        else:
            with st.status("Reading the text...", expanded=True) as s:
                res = reminders.run_reminder_agent(security.clean_text(rtext, 6000), rcompany, rrole, use_llm=llm.available())
                for line in res["log"]:
                    st.markdown(plain(line))
                s.update(label="Done", state="complete", expanded=False)
            ss.reminder_plan, ss.reminder_log = res["plan"], res["log"]
            ss.reminder_results, ss.plan_id = None, ss.plan_id + 1
            if not res["plan"]:
                st.info("No usable dates found. Include the date, for example: interview on 5 Nov 2026 at 11 am.")

    with st.expander("Add one reminder by hand"):
        m1, m2, m3, m4 = st.columns([2, 3, 2, 2])
        mkind = m1.selectbox("Type", ["deadline", "interview", "test", "follow_up", "other"],
                             format_func=lambda k: reminders.KIND_LABEL[k], key="manual_kind")
        mtitle = m2.text_input("What for", key="manual_title", placeholder="SDE-1 at Acme")
        mdate = m3.date_input("Date", min_value=date.today(), key="manual_date")
        mtime = m4.text_input("Time (24h, optional)", key="manual_time", placeholder="11:30")
        if st.button("Plan it"):
            try:
                ss.reminder_plan = reminders.plan_manual(mkind, mtitle, "", mdate.isoformat(), mtime.strip())
                ss.reminder_log, ss.reminder_results, ss.plan_id = ["Planned from your entry."], None, ss.plan_id + 1
            except ValueError as e:
                st.error(str(e))

    if ss.reminder_plan:
        with ui_theme.card():
            ui_theme.card_head("Review", "Untick anything you do not want. Nothing is added until you approve.")
            if ss.reminder_log:
                with st.expander("What the agent did"):
                    for line in ss.reminder_log:
                        st.markdown(plain(line))
            df = pd.DataFrame([{
                "Add": it.get("add", True), "Event": it["title"], "When": when_text(it),
                "Reminders": offsets_text(it["reminders_min"], it["all_day"]), "Note": it["note"],
            } for it in ss.reminder_plan])
            edited = st.data_editor(
                df, hide_index=True, key=f"plan_editor_{ss.plan_id}",
                column_config={"Add": st.column_config.CheckboxColumn("Add", default=True)},
                disabled=["Event", "When", "Reminders", "Note"],
            )
            picks = [bool(x) for x in edited["Add"].tolist()]
            n = sum(picks)
            st.markdown(f"**On approval:** {n} event{'s' if n != 1 else ''} will be "
                        + ("added to your Google Calendar." if cal_ok else "saved so you can download an .ics file."))
            st.caption("Wrong date? Fix the text above and run Find dates again.")
            if st.button("Approve and add to calendar", type="primary", disabled=n == 0):
                items = [dict(it, add=picks[i]) for i, it in enumerate(ss.reminder_plan)]
                with st.spinner("Adding to your calendar..."):
                    ss.reminder_results = reminders.create_events(ss.session_id, items, approved=True)
                ss.reminder_plan = []
                st.rerun()

    if ss.reminder_results:
        out = ss.reminder_results
        with ui_theme.card():
            ui_theme.card_head("Result")
            st.dataframe(pd.DataFrame([{"Event": r["title"], "Date": r["date"], "Status": r["status"]} for r in out["results"]]),
                         hide_index=True)
            if any(r["status"] == "created" for r in out["results"]):
                st.success("Added to Google Calendar.")
            if out["ics"]:
                st.info("Google Calendar is not connected, so these are saved as an .ics file. Open it to import them.")
                st.download_button("Download reminders (.ics)", out["ics"], file_name="careerpilot_reminders.ics", mime="text/calendar")

    rows = store.list_reminders(ss.session_id)
    today = datetime.now(calendar_tool.IST).date()
    upcoming = [r for r in rows if r["event_date"] >= today.isoformat()][:5]
    with ui_theme.card():
        ui_theme.card_head("Scheduled")
        if upcoming:
            ui_theme.timeline([(r["event_date"], r["kind"]) for r in upcoming], today)
        if not rows:
            st.info("Reminders you approve show up here, including the follow-ups from the Apply tab.")
        else:
            st.dataframe(pd.DataFrame([{
                "Event": r["title"], "Date": r["event_date"], "Time": "All day" if r["all_day"] else r["event_time"],
                "Calendar": "In Google Calendar" if r["calendar_status"] == "created" else "ICS file only",
            } for r in rows]), hide_index=True)
    sent = store.list_applications(ss.session_id)
    if sent:
        with st.expander(f"Applications you sent ({len(sent)})"):
            st.dataframe(pd.DataFrame([{
                "Role": a["job_title"], "Company": a["company"], "Source": a["source"], "Status": a["status"],
                "Applied": a["applied_date"], "Follow up": a["follow_up_date"],
            } for a in sent]), hide_index=True)


# =============================================================== interview
def iv_payload() -> dict:
    lm = ss.last_match or {}
    sel = ss.selected_job or {}
    jd = ss.get("jd_text", "").strip() or (sel.get("job", {}).get("description", "") if sel else "")
    return {
        "resume_text": ss.resume_text, "jd_text": jd, "role": ss.get("target_role", "").strip(),
        "missing_skills": sel.get("missing") or lm.get("missing_skills", []),
        "session_id": ss.session_id, "resume_id": ss.resume_id,
    }


def show_feedback(t: dict) -> None:
    s = t["scores"]
    cols = st.columns(5)
    for col, (label, key) in zip(cols, [("Overall", "overall"), ("Relevance", "relevance"), ("Depth", "depth"), ("Clarity", "clarity"), ("Examples", "examples")]):
        col.metric(label, f"{s[key]:g}" + (" / 10" if key == "overall" else ""))
    f = t["feedback"]
    x, y = st.columns(2)
    with x:
        st.markdown("**What worked**")
        for it in f["strengths"] or ["Nothing stood out yet."]:
            st.markdown("- " + plain(it))
    with y:
        st.markdown("**What to fix**")
        for it in f["weaknesses"] or ["No major gaps."]:
            st.markdown("- " + plain(it))
    with st.expander("Why this score, and a stronger answer"):
        st.markdown(plain(f["justification"]))
        st.markdown("**A stronger answer**")
        st.markdown(plain(f["improved_sample_answer"]))


def page_interview() -> None:
    ui_theme.page_header("Practice", "Mock interview",
                         "Five questions, one at a time, scored on a rubric. A weak answer gets one follow-up.")
    if need_resume("interview"):
        return
    iv = ss.interview
    if iv["status"] == "idle":
        with st.container(border=True, key="card-start"):
            ui_theme.card_head("Ready when you are",
                               "Two questions from your resume, two on skill gaps, one behavioural. "
                               "A weak answer gets one follow-up on the same topic.")
            if not ss.get("jd_text", "").strip() and not ss.selected_job:
                st.caption("Tip: paste a job description in Workspace, Match, or pick a job, so the questions match a real role.")
            if st.button("Start the interview", type="primary"):
                with st.spinner("Planning your questions..."):
                    out = interview.step({**iv_payload(), "interview": interview.new_interview()})
                ss.interview, ss.last_turn = out["interview"], None
                st.rerun()
    elif iv["status"] == "asking":
        if ss.last_turn:
            with ui_theme.card():
                ui_theme.card_head("Feedback on your last answer")
                show_feedback(ss.last_turn)
        q = iv["current_question"]
        with st.container(border=True, key="card-question"):
            if q.get("is_followup"):
                ui_theme.pills([("Follow-up", None, "orange")], tight=True)
                st.caption("Your last answer scored below 5, so here is one more try on the same topic.")
            else:
                ui_theme.pills([(f"Question {iv['current_index'] + 1} of {len(iv['question_plan'])}", None, "slate")], tight=True)
            st.markdown(f"### {plain(q['text'])}")
            akey = f"ans_{iv['current_index']}_{int(q.get('is_followup', False))}_{len(iv['history'])}"
            ans = st.text_area("Your answer", key=akey, height=160, placeholder="Answer as you would in the interview")
            if st.button("Submit answer", type="primary"):
                if not ans.strip():
                    st.warning("Write an answer first.")
                else:
                    with st.spinner("Scoring your answer..."):
                        out = interview.step({**iv_payload(), "interview": iv, "answer": security.cap_chat(ans)})
                    ss.interview, ss.last_turn = out["interview"], out.get("last_eval")
                    st.rerun()
    else:
        r = iv["report"]
        with ui_theme.card():
            ui_theme.card_head("Interview report")
            st.metric("Overall", f"{r['overall']:g} / 10")
            st.progress(min(1.0, r["overall"] / 10))
            st.dataframe(
                pd.DataFrame([{"Question": q["question"], "Topic": q["topic"], "Score": q["score"],
                               "Follow-up used": "yes" if q["followup"] else "no"} for q in r["per_question"]]),
                hide_index=True,
            )
        x, y = st.columns(2)
        with x, ui_theme.card():
            ui_theme.card_head("Top strengths")
            for it in r["top_strengths"] or ["Keep practising to build a pattern."]:
                st.markdown("- " + plain(it))
        with y, ui_theme.card():
            ui_theme.card_head("Top weaknesses")
            for it in r["top_weaknesses"] or ["None flagged."]:
                st.markdown("- " + plain(it))
        with ui_theme.card():
            ui_theme.card_head("Study plan")
            for it in r["study_plan"]:
                st.markdown("- " + plain(it))
        if ss.last_turn:
            with st.expander("Feedback on the last answer"):
                show_feedback(ss.last_turn)
        if st.button("Start a new interview"):
            ss.interview, ss.last_turn = interview.new_interview(), None
            st.rerun()


# ================================================================ dispatch
{
    "Dashboard": page_dashboard, "My Profile": page_profile, "Workspace": page_workspace,
    "Reminders": page_reminders, "Interview": page_interview,
}[ss.nav]()
