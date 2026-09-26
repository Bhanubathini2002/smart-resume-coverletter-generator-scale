# Intern / Entry-Level Resume & Cover Letter Generator

Drop a spreadsheet of job postings in `Input/`, run one command, get a **tailored 1-page resume + 1-page
cover letter PDF for every job**, plus the spreadsheet back with the file paths, the job description,
the detected ATS and a mailing address. Built for internship, co-op, new-grad and junior applications:
the model may reword and reorder, but it can never invent a tool, employer, metric or seniority.

```
Input/jobs.xlsx  ──►  run.py  ──►  Output/<day>/<Company>_<Title>/<Your_Name>.pdf
                                                             <Your_Name>_Cover_Letter.pdf
                                   Input/<day>/updated/jobs_updated.xlsx   (+5 columns)
```

## Quick start (5 steps)

1. **Install**: Python 3.10+, a LaTeX distribution with `pdflatex` on PATH (MiKTeX or TeX Live), then
   `pip install -r requirements.txt`.
2. **LLM**: copy `.env.example` to `.env` and set `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.
   Any OpenAI-compatible chat endpoint works (OpenAI, Groq, Together, Ollama, a gateway in front of Claude/Gemini).
3. **Your templates**: replace `templates/base_resume.tex` and `templates/base_coverletter.tex` with yours
   (keep the shapes listed below), then run `python engine/build_engine.py`.
4. **Your city**: `Address/address_for_resume.xlsx` maps a job's city to a mailing address for application
   forms. Edit the `Houston, TX` row (or change `DEFAULT_CITY_ST` in `config.py`) to your own address.
5. **Run**: put a jobs `.xlsx` in `Input/` (see `samples/jobs_sample_2026-09-26.xlsx`) and run
   `run.bat` (Windows) or `./run.sh` (macOS/Linux).

Re-running the same file is safe: finished jobs are skipped. `--redo` regenerates everything.
`python run.py Input/jobs.xlsx --model gpt-4o-mini --workers 6` overrides the model / parallelism.

## Input spreadsheet

First sheet, header row 1. Columns the pipeline reads (others are ignored and preserved):

| column | required | used for |
|---|---|---|
| `Job Title`, `Company` | yes | output folder name, prompts |
| `Location` | yes | `City, ST` on the documents + mailing address (`Remote`/blank → default city) |
| `Level`, `Job Type` | no | passed to the prompt; rows that do not look intern/entry-level are flagged in the log |
| `Jobright Link` | no | job description is fetched from Jobright's structured page (best source) |
| `Original Job Posting Link` | no | fallback JD source (HTML → text) and ATS detection |

No link, or a dead one? Put the job description in `Output/<day>/<Company>_<Title>/jd_manual.txt` and rerun.

## What the run does

| # | step | output |
|---|---|---|
| 1 | file the workbook by the date in its name (`…2026-09-26…`) | `Input/<M_D_YYYY>/original/` |
| 2 | address: exact city → nearest same-state → default | column `complete_address_section` |
| 3 | ATS detection from the posting URL (65 vendors, 14 boards) + company-site fingerprint | column `ats` |
| 4 | job description, fetched once and cached | column `jd` |
| 5 | 2 LLM calls per job → small JSON → `render.py` validates, fills your templates, compiles, auto-fits to exactly 1 page | the two PDFs |
| 6 | verify from disk (pypdf page counts) and write paths | columns `updated_resume_section`, `coverletter` |
| 7 | report | `logs/<day>_<file>.json` |

## Rules enforced in code (not by the model)

- **Facts are fixed**: employers, roles, dates, degree, university, project names and headings, certification,
  contact line. They are verified in the compiled PDF text; a missing one fails the job.
- **No fabricated tools**: every skill token must already appear in your base resume; a blocklist of commonly
  requested tools you do not have is rejected even in prose (`engine/render.py`, `BLOCKLIST`).
- **Seniority lock** (intern tone): `architected / spearheaded / owned` are swapped to builder verbs;
  `led a team / managed a team / mentored / SME / expert / senior` and any "N years of experience" claim are rejected.
- **Length**: resume trimmed or padded until exactly `RESUME_PAGES` (default 1); cover letter exactly 1 page,
  paragraphs length-repaired with true sentences taken from your own template.
- The model only ever returns: coursework order, skills rows, experience bullets, project bullets, and the four
  cover-letter paragraphs.

## Template shapes the parser needs

`engine/build_engine.py` turns your templates into slots. Keep these shapes (see the samples):

**Resume** (`templates/base_resume.tex`, Jake Gutierrez style, pdflatex)
- header: `\textbf{\Huge \scshape Your Name}` and the literal `City,St` where your city goes
- Education: a `\resumeSubheading{School}{Location}{Degree}{Dates}` block containing `\resumeItem{Coursework: A, B, C}`
- Experience: one `\resumeSubheading{Company}{Location}{Role}{Dates}` + `\resumeItemListStart … \resumeItemListEnd` per job (any number)
- Projects: one `\resumeProjectHeading{\textbf{Name} $|$ \emph{tech}}{dates}` + item list per project (any number)
- Technical Skills: one `\textbf{Category}{: items}` per line
- Everything else (links, certification, research/volunteer, …) is copied verbatim

**Cover letter** (`templates/base_coverletter.tex`, pdflatex)
- tokens `\clDate`, `\clHiringManager`, `\clCompany`, `\clCompanyAddr`, `\clJobTitle`, `\clHowFound`
- four body blocks introduced by the comment lines `% P1 OPENING`, `% P2 PROOF`, `% P3 FIT`, `% P4 CLOSE`
- closing `\vspace{…em}` followed by a line starting with `Sincerely`
- the four sample paragraphs double as the *filler* used when the model writes too little, so keep them
  generic (no company names) and true.

After any template change: `python engine/build_engine.py` (prints what it parsed; fails loudly if a shape is missing).

## Layout

```
run.py / run.bat / run.sh     the whole pipeline
config.py                     paths, LLM (.env), LaTeX, page targets, default city
address.py                    Location → mailing address + "City, ST"
jd_fetch.py                   Jobright structured JD, HTML fallback, jd_manual.txt override
engine/llm.py                 OpenAI-compatible chat (urllib, retries, JSON repair loop)
engine/prompts.py             rules + JSON schemas for the 2 calls
engine/render.py              validate · block fabrication + seniority · LaTeX · auto-fit · verify
engine/ats_detect.py          ATS / job-board detection
engine/build_engine.py        templates → resume_template.tex, base_spec.json, fixed_facts.json, allowed_tech.json, cl_filler.json
templates/                    base_resume.tex, base_coverletter.tex (samples — replace), ATS_prompt.md (reference)
Address/address_for_resume.xlsx   city → mailing address book (edit the default row)
samples/jobs_sample_2026-09-26.xlsx   input format
```

## License

MIT. The sample resume layout is derived from Jake Gutierrez's LaTeX resume (MIT).
