"""
prompts.py — the ONLY thing the LLM ever does: turn (JD + base resume facts) into small JSON
specs. INTERN / ENTRY-LEVEL edition (rules compressed from templates/ATS_prompt.md).
Built for weak/cheap models:
  * TWO small calls per job (resume spec, then cover letter)
  * strict JSON schema, every field shown with an example
  * base resume content supplied as the ONLY allowed source of facts
  * rules stated as numbered constraints, not prose
  * seniority lock: no years-of-experience claims, no leadership / ownership verbs
  * repair prompt for when the model breaks the contract
"""
import json, os, re

ENGINE = os.path.dirname(os.path.abspath(__file__))
BASE_SPEC = json.load(open(os.path.join(ENGINE, "base_spec.json"), encoding="utf-8"))
_PUBLIC = lambda d: {k: v for k, v in d.items() if not k.startswith("_")}

# numbers that appear in the base resume (so rule 3 lists the real ones, whatever the template says)
_NUMS = list(dict.fromkeys(re.findall(r"~?\d+(?:\.\d+)?%|\d[\d,]*\+|thousands of \w+", json.dumps(BASE_SPEC, ensure_ascii=False))))
_EDU = BASE_SPEC.get("education") or {}
EDU_LINE = ", ".join(x for x in (_EDU.get("degree"), _EDU.get("school")) if x) or "the degree in BASE_RESUME"

RULES = f"""ABSOLUTE RULES
1. Use ONLY facts, employers, dates, projects, courses, tools and numbers that appear in BASE_RESUME. Never add a technology, tool, certification, employer, degree, course or metric that is not already there.
2. If the job asks for something BASE_RESUME does not have (example: Java, Kotlin, MATLAB, TensorRT, Rust, SAS, Spark), do NOT mention it anywhere. Map it to the closest REAL skill instead, or leave the gap.
3. Keep every number from BASE_RESUME exactly ({", ".join(_NUMS[:8]) or "there are none"}). Do not invent new percentages, counts, users or scale.
4. Reword, reorder, shorten, emphasize — that is your whole job. Put the technologies the job description repeats most FIRST, in the first bullets and the first skills row.
5. Order matters: MOST job-relevant items FIRST in every list. The last items may be deleted automatically to fit ONE page.
6. SENIORITY LOCK — this is an INTERNSHIP / ENTRY-LEVEL application. Verbs: built, implemented, developed, trained, evaluated, tested, prototyped, assisted, contributed, documented, learned, collaborated. NEVER use: architected, spearheaded, owned, led a team, managed a team, mentored, enterprise-wide, strategic, SME, expert, senior, principal. NEVER state a number of years of experience. Translate senior JD tasks downward (JD "architect a multi-agent platform" -> "prototyped a multi-step LLM workflow with tool calling").
7. Company names, project names and course names must be copied EXACTLY from BASE_RESUME; you rewrite only bullets and skills rows.
8. Bullets: 12-24 words. Action + tool + what was built + simple result. Prefer a concrete output (dashboard, API, parser, labeled dataset) over any number that is not in BASE_RESUME.
9. Plain text only. No LaTeX, no backslashes, no markdown, no bullet symbols, no emojis. Normal characters (&, %, #, ~) are fine.
10. Output ONLY a valid JSON object. No prose before or after. No markdown fences."""

SYSTEM_RESUME = "You tailor ONE intern / entry-level resume to ONE job description and output ONLY a JSON object.\n\n" + RULES
SYSTEM_CL     = "You write ONE intern / entry-level cover letter for ONE job and output ONLY a JSON object.\n\n" + RULES

RESUME_SCHEMA = {
  "coursework": ["EXACT course names from BASE_RESUME coursework, most job-relevant FIRST, 4-8 items, nothing new"],
  "skills": [{"category": "1-3 word category (Languages, ML / AI, Data & Tools, Cloud & Dev Tools, AI Tools ...)", "items": "comma-separated technologies, 2-7 items, no duplicates across rows"}],
  "experience": [{"company": "EXACT company name from BASE_RESUME", "bullets": ["string, 12-24 words, builder verb + tool + what was built + result; keep every number exactly"]}],
  "projects": [{"name": "EXACT project name from BASE_RESUME", "bullets": ["string, 12-24 words, what was built + stack + one JD-matching technique + concrete result"]}]
}
RESUME_COUNTS = ("coursework: 4-8 | skills: 4-6 rows, 12-18 technologies total | "
                 "experience: EVERY company from BASE_RESUME, 3-5 bullets for the most recent, 2-4 for the others | "
                 "projects: EVERY project from BASE_RESUME, 2-4 bullets each, most job-relevant project FIRST")

CL_SCHEMA = {
  "addr": "string: the job's 'City, ST', or 'Remote, United States' if the job is remote",
  "p1": "string, 45-70 words: I am applying for <title> at <company>, found through Jobright; name the degree from BASE_RESUME and give a one-line reason you fit",
  "p2": "string, 70-110 words: map the 2-3 strongest job requirements to BASE_RESUME experience and project proof, using the real numbers from BASE_RESUME exactly or none at all",
  "p3": "string, 55-100 words: stack fit plus how you work (write evaluations and tests, document, ask for feedback, learn fast); echo 3-5 exact keywords from the job description",
  "p4": "string, 35-65 words: ONE specific sentence about this company's product, domain or team; mention the internship term or start date if the job states one; ask for a conversation; thank them"
}

def _job_block(jd, company, title, city_st, level):
    return f"""JOB
company: {company}
title: {title}
location: {city_st}
level: {level or 'Internship / Entry Level'}

JOB DESCRIPTION
{jd.strip()[:6000]}
"""

def _base_public():
    return {"coursework": BASE_SPEC["coursework"], "skills": BASE_SPEC["skills"],
            "experience": [_PUBLIC(e) for e in BASE_SPEC["experience"]],
            "projects": [_PUBLIC(p) for p in BASE_SPEC["projects"]]}

def build_messages(jd, company, title, city_st, level):
    """Call 1 — resume spec."""
    user = (_job_block(jd, company, title, city_st, level) +
            "\nBASE_RESUME (the only allowed source of facts)\n" + json.dumps(_base_public(), ensure_ascii=False, indent=0) +
            "\n\nOUTPUT_SCHEMA — every key is required\n" + json.dumps(RESUME_SCHEMA, ensure_ascii=False, indent=0) +
            "\n\nREQUIRED COUNTS\n" + RESUME_COUNTS + "\n\nReturn the JSON object now.")
    return [{"role": "system", "content": SYSTEM_RESUME}, {"role": "user", "content": user}]

def build_cl_messages(jd, company, title, city_st, level):
    """Call 2 — cover letter (smaller BASE_RESUME excerpt so weak models don't truncate)."""
    facts = {"education": EDU_LINE,
             "experience": [{"company": e["company"], "role": e["role"], "dates": e["dates"], "bullets": e["bullets"][:4]} for e in BASE_SPEC["experience"]],
             "projects": [{"name": p["name"], "tech": p["tech"], "bullets": p["bullets"][:2]} for p in BASE_SPEC["projects"]],
             "skills": BASE_SPEC["skills"][:5]}
    user = (_job_block(jd, company, title, city_st, level) +
            "\nBASE_RESUME (the only allowed source of facts)\n" + json.dumps(facts, ensure_ascii=False, indent=0) +
            "\n\nOUTPUT_SCHEMA — every key is required, respect the word counts\n" + json.dumps(CL_SCHEMA, ensure_ascii=False, indent=0) +
            "\n\nReturn the JSON object now.")
    return [{"role": "system", "content": SYSTEM_CL}, {"role": "user", "content": user}]

def repair_messages(system, previous_output, errors):
    return [
        {"role": "system", "content": system},
        {"role": "user", "content":
            "Your previous JSON had these problems:\n- " + "\n- ".join(errors) +
            "\n\nFix ONLY those problems and return the complete corrected JSON object.\nPrevious output:\n" + previous_output[:12000]},
    ]
