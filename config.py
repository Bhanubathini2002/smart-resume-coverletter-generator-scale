"""
config.py — every path and knob in ONE place. Nothing else hardcodes a path.

Clone-and-run: the only things you normally touch are
  * the LLM endpoint  -> environment variables LLM_BASE_URL / LLM_API_KEY / LLM_MODEL (or a .env file)
  * your templates    -> templates/base_resume.tex + templates/base_coverletter.tex, then
                         python engine/build_engine.py
  * your default city -> DEFAULT_CITY_ST (must exist in Address/address_for_resume.xlsx)
"""
import json, os, shutil

APP_ROOT   = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR  = os.path.join(APP_ROOT, "Input")
OUTPUT_DIR = os.path.join(APP_ROOT, "Output")
LOG_DIR    = os.path.join(APP_ROOT, "logs")
ADDRESS_BOOK = os.path.join(APP_ROOT, "Address", "address_for_resume.xlsx")
TEMPLATES  = os.path.join(APP_ROOT, "templates")
BASE_RESUME      = os.path.join(TEMPLATES, "base_resume.tex")
BASE_COVERLETTER = os.path.join(TEMPLATES, "base_coverletter.tex")
ATS_PROMPT       = os.path.join(TEMPLATES, "ATS_prompt.md")

# ---- .env (optional): KEY=VALUE lines next to this file ---------------------
_env = os.path.join(APP_ROOT, ".env")
if os.path.exists(_env):
    for line in open(_env, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# ---- page targets (enforced by render.py auto-fit + run.py verify) ----------
RESUME_PAGES = int(os.environ.get("RESUME_PAGES", "1"))   # intern / new-grad resume: exactly 1 page
COVER_PAGES  = 1

# ---- LLM (any OpenAI-compatible chat endpoint) -------------------------------
#   OpenAI:      LLM_BASE_URL=https://api.openai.com/v1        LLM_MODEL=gpt-4o-mini
#   Anthropic via an OpenAI-compatible proxy / gateway, Groq, Together, Ollama (http://localhost:11434/v1) ...
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY  = os.environ.get("LLM_API_KEY",  "sk-your-key")
LLM_MODEL    = os.environ.get("LLM_MODEL",    "gpt-4o-mini")
LLM_MAX_TOKENS = 3500
LLM_WORKERS    = int(os.environ.get("LLM_WORKERS", "4"))   # parallel jobs (LaTeX + LLM)

# ---- LaTeX -------------------------------------------------------------------
# pdflatex is found on PATH (MiKTeX / TeX Live). Override with LATEX_BIN=<folder containing pdflatex>.
_bin = os.environ.get("LATEX_BIN", "")
def _tex(name):
    if _bin: return os.path.join(_bin, name + (".exe" if os.name == "nt" else ""))
    return shutil.which(name) or name
XELATEX  = _tex("xelatex")
PDFLATEX = _tex("pdflatex")
RESUME_ENGINE = PDFLATEX    # the sample resume template uses \pdfgentounicode -> pdflatex
COVER_ENGINE  = PDFLATEX

# ---- output file names: <Your_Name>.pdf + <Your_Name>_Cover_Letter.pdf ------
# The name is read from the resume template header by build_engine.py (engine/base_spec.json).
def _candidate():
    try:
        return json.load(open(os.path.join(APP_ROOT, "engine", "base_spec.json"), encoding="utf-8")).get("name") or "Resume"
    except Exception:
        return "Resume"
_BASENAME  = "_".join(_candidate().split())
RESUME_PDF = f"{_BASENAME}.pdf"
COVER_PDF  = f"{_BASENAME}_Cover_Letter.pdf"

# ---- address default (remote / "United States" / unparseable location) -------
DEFAULT_CITY_ST = ("houston", "TX")   # (city lower-case, ST) — must be a row in the address book

# ---- level gate ----------------------------------------------------------------
# Rows whose Level / Job Title match none of these are still processed, but flagged in the log.
ENTRY_LEVEL_WORDS = ("intern", "internship", "co-op", "coop", "entry", "junior", "new grad", "graduate",
                     "early career", "associate", "apprentice", "trainee", "fellow", "student", "campus")

# ---- output columns appended to the Excel -------------------------------------
NEW_COLUMNS = ["complete_address_section", "updated_resume_section", "jd", "coverletter", "ats"]
