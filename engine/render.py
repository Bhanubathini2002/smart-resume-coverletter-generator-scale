"""
render.py — deterministic INTERN / ENTRY-LEVEL resume + cover-letter builder for ANY model.

The LLM produces ONLY a small JSON spec (see prompts.py). This module does everything else:
  * escape LaTeX, fill the slot template (preamble + fixed sections are never touched)
  * normalize: overlay the model's output on the base spec — companies matched by COMPANY,
    projects by NAME, coursework filtered to the base list; headings always come from the base
  * seniority lock: deterministic word swaps + hard errors for leadership / years claims
  * validate: no fabricated tech (blocklist + base-resume whitelist), counts, fixed facts intact
  * compile with MiKTeX (config.RESUME_ENGINE), count pages with pypdf
  * AUTO-FIT to config.RESUME_PAGES: too long -> drop the lowest-priority bullets round-robin
    (last items go first, by contract); too short -> pad from the base; loop until exact
  * cover letter: fill tokens + 4 paragraphs (length-repaired with TRUE filler from the template),
    compile, require exactly config.COVER_PAGES

Usage:
  from render import build_job
  result = build_job(job_dir, spec_dict, cl_dict, date_str)   # -> dict with ok/pages/notes
"""
import copy, json, os, re, shutil, subprocess, sys
from pypdf import PdfReader

ENGINE = os.path.dirname(os.path.abspath(__file__))
ROOT   = os.path.dirname(ENGINE)
sys.path.insert(0, ROOT)
import config                                                    # noqa: E402

def _load(name): return open(os.path.join(ENGINE, name), encoding="utf-8").read()
TEMPLATE    = _load("resume_template.tex")
CL_TEMPL    = open(config.BASE_COVERLETTER, encoding="utf-8").read()
BASE_SPEC   = json.loads(_load("base_spec.json"))
ALLOWED     = json.loads(_load("allowed_tech.json"))
FIXED_FACTS = json.loads(_load("fixed_facts.json"))
CL_FILLER   = json.loads(_load("cl_filler.json"))
ALLOWED_L   = {a.lower() for a in ALLOWED}

# ------------------------------------------------------------------ constants
# tech that intern JDs commonly ask for but the base resume does NOT have — hard-block even if a
# dumb model slips it in. Extend freely. (Anything already in the base resume is allowed regardless.)
BLOCKLIST = {
    "kotlin", "swift", "xcode", "objective-c", "android studio", "adobe", "photoshop", "firefly",
    "tensorrt", "rust", "vllm", "tgi", "sas", "oci", "oracle cloud", "kafka", "ruby", "next.js",
    "bazel", "afsim", "storm", "palantir", "alteryx", "zapier", "lovable", "ssas",
    "j2ee", "ejb", "spring boot", "spring framework", "spring mvc", "scala", "golang", ".net", "c#", "php", "matlab",
    "salesforce apex", "uipath", "automation anywhere", "snowpark", "dbt", "java", "julia", "stata", "spss",
    "power bi", "looker", "qlik", "simulink", "labview", "verilog", "vhdl", "cuda c", "openmp", "mpi",
    "spark", "pyspark", "hadoop", "kubernetes", "snowflake", "tableau", "c++", "go", "r language",
}
_BASE_TEXT = json.dumps(BASE_SPEC, ensure_ascii=False).lower()
def _has(word, text): return re.search(rf"(?<![a-z0-9+#.]){re.escape(word)}(?![a-z0-9+#])", text) is not None
BLOCKLIST = {b for b in BLOCKLIST if not _has(b, _BASE_TEXT)}

# seniority lock — deterministic swaps first, then anything left in SENIOR_WORDS is an error
SENIOR_SWAP = [(r"\barchitected\b", "built"), (r"\bArchitected\b", "Built"),
               (r"\bspearheaded\b", "initiated"), (r"\bSpearheaded\b", "Initiated"),
               (r"\bowned\b", "maintained"), (r"\bOwned\b", "Maintained"),
               (r"\benterprise-wide\b", "team-wide"), (r"\bEnterprise-wide\b", "Team-wide")]
SENIOR_WORDS = ["led a team", "managed a team", "mentored", "strategic", "sme", "expert", "senior", "staff engineer", "principal"]
YEARS_RE = re.compile(r"\b(\d+\+?|one|two|three|four|five|six|seven|eight|nine|ten|several|many)\s*(?:-\s*\d+\s*)?(?:\+\s*)?years?\b|\bhalf a decade\b|\ba decade\b", re.I)

LIMITS = dict(coursework=(3, 8), skills=(4, 6), projects=(min(2, len(BASE_SPEC["projects"])), 4),
              project_bullets=(1, 4), exp_bullets=(2, 5))

# ------------------------------------------------------------------ helpers
def esc(s: str) -> str:
    """Escape LaTeX specials in model-written text. Order matters."""
    s = str(s)
    s = s.replace("\\", r"\textbackslash{}")
    for a, b in [("&", r"\&"), ("%", r"\%"), ("#", r"\#"), ("_", r"\_"), ("$", r"\$"), ("{", r"\{"), ("}", r"\}")]:
        s = s.replace(a, b)
    s = s.replace("~", r"$\sim$").replace("^", r"\^{}")
    s = s.replace("—", "---").replace("–", "--").replace("→", r"$\rightarrow$")
    s = s.replace("“", "``").replace("”", "''").replace("’", "'").replace("‘", "`")
    return s

def words(s): return len(re.findall(r"\S+", s or ""))

def pages(pdf):
    try: return len(PdfReader(pdf).pages)
    except Exception: return -1

def pdf_text(pdf):
    try: return "\n".join((p.extract_text() or "") for p in PdfReader(pdf).pages)
    except Exception: return ""

def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=180)

def compile_tex(cwd, engine, tex):
    for _ in range(2):
        r = run([engine, "-interaction=nonstopmode", "-halt-on-error", tex], cwd)
    return r.returncode == 0

def _key(s): return re.sub(r"\s+", " ", str(s or "")).strip().lower()

# ------------------------------------------------------------------ validation
def _known(tok: str) -> bool:
    """A skill token is legitimate if it (or every word of it) already appears in the base resume."""
    low = tok.lower().strip()
    if low in _BASE_TEXT: return True
    parts = [p for p in re.split(r"[\s\-]+", low) if len(p) > 2]
    return bool(parts) and all(p in _BASE_TEXT for p in parts)

def _prose(spec):
    out = []
    for p in spec.get("projects", []): out += list(p.get("bullets", []))
    for e in spec.get("experience", []): out += list(e.get("bullets", []))
    return " ".join(str(x) for x in out)

def find_fabrications(spec) -> list:
    """Tech in the spec that is blocklisted, or skill-row tokens absent from the base resume.
    Bullets are free prose — only the blocklist applies there."""
    bad = set()
    for row in spec.get("skills", []):
        for tok in re.split(r"[,;/()\[\]]", row.get("items", "")):
            tok = tok.strip(" .:")
            if not tok: continue
            low = tok.lower()
            if any(_has(b, low) for b in BLOCKLIST): bad.add(tok); continue
            if len(tok) > 2 and not _known(tok): bad.add(tok)
    low = _prose(spec).lower()
    for bl in BLOCKLIST:
        if _has(bl, low): bad.add(bl)
    return sorted(bad)

def find_seniority(text) -> list:
    """Leadership words and years-of-experience claims the base resume does not make."""
    low = text.lower()
    bad = [w for w in SENIOR_WORDS if re.search(rf"\b{re.escape(w)}\b", low)]
    for m in YEARS_RE.finditer(text):
        if m.group(0).lower() not in _BASE_TEXT: bad.append(f"years claim '{m.group(0)}'")
    return bad

def _soften(s: str) -> str:
    for pat, rep in SENIOR_SWAP: s = re.sub(pat, rep, s)
    return s

def _bullets(x, fallback):
    b = [_soften(str(v).strip()) for v in (x or []) if str(v).strip()]
    return b or list(fallback)

def normalize(spec: dict) -> dict:
    """Overlay the model output on the base spec, coerce shapes, apply the seniority swaps, clamp
    to LIMITS and TOP UP short lists from the base so a weak model's thin output still renders."""
    base = copy.deepcopy(BASE_SPEC); spec = spec or {}
    s = {}
    # coursework: subset of the base list, model order; unknown courses dropped
    bc = {_key(c): c for c in base["coursework"]}
    cw = [bc[_key(c)] for c in (spec.get("coursework") or []) if _key(c) in bc]
    cw = list(dict.fromkeys(cw)) or list(base["coursework"])
    for c in base["coursework"]:
        if len(cw) >= LIMITS["coursework"][0]: break
        if c not in cw: cw.append(c)
    s["coursework"] = cw[:LIMITS["coursework"][1]]
    # skills
    sk = [r for r in (spec.get("skills") or []) if isinstance(r, dict) and r.get("category") and r.get("items")]
    s["skills"] = [{"category": str(r["category"]).strip(" :"), "items": str(r["items"]).strip()} for r in sk] or base["skills"]
    have = {_key(r["category"]) for r in s["skills"]}
    for r in base["skills"]:
        if len(s["skills"]) >= LIMITS["skills"][0]: break
        if _key(r["category"]) not in have: s["skills"].append(r); have.add(_key(r["category"]))
    # experience: base (chronological) order always; matched by company; heading from base
    by_co = {_key(e.get("company")): e for e in (spec.get("experience") or []) if isinstance(e, dict)}
    s["experience"] = [{**e, "bullets": _bullets((by_co.get(_key(e["company"])) or {}).get("bullets"), e["bullets"]), "_base": list(e["bullets"])}
                       for e in base["experience"]]
    # projects: model order = priority; matched by name; missing base projects appended last
    by_name = {_key(p["name"]): p for p in base["projects"]}
    projs, seen = [], set()
    for p in (spec.get("projects") or []):
        if not isinstance(p, dict): continue
        b = by_name.get(_key(p.get("name")))
        if not b or _key(b["name"]) in seen: continue
        seen.add(_key(b["name"]))
        projs.append({**b, "bullets": _bullets(p.get("bullets"), b["bullets"]), "_base": list(b["bullets"])})
    for b in base["projects"]:
        if _key(b["name"]) not in seen: projs.append({**b, "bullets": list(b["bullets"]), "_base": list(b["bullets"])})
    s["projects"] = projs
    # ---- floors (top up from base) and ceilings ---------------------------
    for lst, floor, ceil in [(s["experience"], *LIMITS["exp_bullets"]), (s["projects"], *LIMITS["project_bullets"])]:
        for x in lst:
            sig = {v.lower()[:60] for v in x["bullets"]}
            for b in x["_base"]:
                if len(x["bullets"]) >= floor: break
                if b.lower()[:60] not in sig: x["bullets"].append(b); sig.add(b.lower()[:60])
            x["bullets"] = x["bullets"][:ceil]
    s["skills"] = s["skills"][:LIMITS["skills"][1]]
    s["projects"] = s["projects"][:LIMITS["projects"][1]]
    return s

def validate(spec, city_st) -> list:
    errs = []
    if not city_st or not re.fullmatch(r"[A-Za-z .\-]+, [A-Z]{2}", city_st):
        errs.append(f"city_st must be 'City, ST' — got {city_st!r}")
    if len(spec["skills"]) < LIMITS["skills"][0]: errs.append("too few skill rows")
    if len(spec["projects"]) < LIMITS["projects"][0]: errs.append("too few projects (use the project names from BASE_RESUME exactly)")
    for p in spec["projects"]:
        if len(p["bullets"]) < LIMITS["project_bullets"][0]: errs.append(f"project '{p['name']}' has no bullets")
    for e in spec["experience"]:
        if len(e["bullets"]) < LIMITS["exp_bullets"][0]: errs.append(f"too few bullets for {e['company']}")
    for b in [x for e in spec["experience"] for x in e["bullets"]] + [x for p in spec["projects"] for x in p["bullets"]]:
        if words(b) > 40: errs.append(f"bullet too long ({words(b)} words, max 24): {b[:50]}...")
    fab = find_fabrications(spec)
    if fab: errs.append("fabricated/blocked tech (remove, it is not in BASE_RESUME): " + ", ".join(fab))
    sen = find_seniority(_prose(spec) + " " + " ".join(r["items"] for r in spec["skills"]))
    if sen: errs.append("entry-level tone violated, remove: " + ", ".join(sen))
    return errs

# ------------------------------------------------------------------ rendering
def _items(bullets): return "".join("        \\resumeItem{" + esc(b) + "}\n" for b in bullets)

def render_resume(spec, city_st) -> str:
    exp = "".join("    \\resumeSubheading\n      " + e["_head"] + "\n      \\resumeItemListStart\n" + _items(e["bullets"]) + "      \\resumeItemListEnd\n\n"
                  for e in spec["experience"]).rstrip("\n") + "\n"
    projs = "".join("      \\resumeProjectHeading\n          " + p["_head"] + "\n          \\resumeItemListStart\n" + _items(p["bullets"]) + "          \\resumeItemListEnd\n"
                    for p in spec["projects"])
    skills = " \\\\\n".join("     \\textbf{" + esc(r["category"]) + "}{: " + esc(r["items"]) + "}" for r in spec["skills"]) + "\n"
    out = TEMPLATE
    for k, v in {"CITY_ST": esc(city_st), "COURSEWORK": esc(", ".join(spec["coursework"])),
                 "EXPERIENCE": exp, "PROJECTS": projs, "SKILLS": skills}.items():
        out = out.replace("{{" + k + "}}", v)
    assert "{{" not in out, "unfilled slot"
    return out

def _counts(spec):
    return f"cw{len(spec['coursework'])} s{len(spec['skills'])} e{'/'.join(str(len(e['bullets'])) for e in spec['experience'])} p{'/'.join(str(len(p['bullets'])) for p in spec['projects'])}"

def _trim_once(spec) -> bool:
    """Drop one lowest-priority item from the section with the most headroom above its floor
    (round-robin, so no section gets gutted). Whole projects / courses go last."""
    pb = [p for p in spec["projects"] if len(p["bullets"]) > LIMITS["project_bullets"][0]]
    eb = [e for e in spec["experience"] if len(e["bullets"]) > LIMITS["exp_bullets"][0]]
    cands = [("skills", len(spec["skills"]) - LIMITS["skills"][0]),
             ("proj_bullets", sum(len(p["bullets"]) - LIMITS["project_bullets"][0] for p in pb)),
             ("exp_bullets", sum(len(e["bullets"]) - LIMITS["exp_bullets"][0] for e in eb))]
    what, room = max(cands, key=lambda c: c[1])
    if room > 0:
        if what == "skills": spec["skills"].pop()
        elif what == "proj_bullets": pb[-1]["bullets"].pop()               # last project first (lowest priority)
        else: max(eb, key=lambda e: len(e["bullets"]))["bullets"].pop()    # fattest company first
        return True
    if len(spec["projects"]) > LIMITS["projects"][0]: spec["projects"].pop(); return True
    if len(spec["coursework"]) > LIMITS["coursework"][0]: spec["coursework"].pop(); return True
    return False

def _pad_once(spec) -> bool:
    """Put one base bullet back (experience first, then projects). False when nothing left to add."""
    for lst, ceil in [(spec["experience"], LIMITS["exp_bullets"][1]), (spec["projects"], LIMITS["project_bullets"][1])]:
        for x in lst:
            for b in x["_base"]:
                if b not in x["bullets"] and len(x["bullets"]) < ceil: x["bullets"].append(b); return True
    return False

def _facts_missing(txt):
    flat = re.sub(r"\s+", " ", txt).lower()
    missing = []
    for f in FIXED_FACTS:
        parts = [p.strip() for p in re.split(r"[–—]", f) if p.strip()]
        if any(re.sub(r"\s+", " ", p).lower() not in flat for p in parts): missing.append(f)
    return missing

def build_resume(job_dir, spec, city_st, max_iter=16) -> dict:
    spec = normalize(spec)
    errs = validate(spec, city_st)
    if errs: return {"ok": False, "stage": "validate", "errors": errs}
    target = config.RESUME_PAGES; notes = []
    for _ in range(max_iter):
        open(os.path.join(job_dir, "main.tex"), "w", encoding="utf-8").write(render_resume(spec, city_st))
        if not compile_tex(job_dir, config.RESUME_ENGINE, "main.tex"):
            return {"ok": False, "stage": "compile", "errors": ["latex failed — see main.log"]}
        n = pages(os.path.join(job_dir, "main.pdf"))
        if n == target: break
        if n > target:
            if not _trim_once(spec): return {"ok": False, "stage": "fit", "errors": ["cannot trim further"]}
            notes.append("trimmed -> " + _counts(spec))
        else:
            if not _pad_once(spec): return {"ok": False, "stage": "fit", "errors": [f"{n} page(s) and nothing left to add"]}
            notes.append("padded from base -> " + _counts(spec))
    else:
        return {"ok": False, "stage": "fit", "errors": [f"could not reach {target} page(s) in {max_iter} iterations"]}

    shutil.copy(os.path.join(job_dir, "main.pdf"), os.path.join(job_dir, config.RESUME_PDF))
    txt = pdf_text(os.path.join(job_dir, config.RESUME_PDF))
    missing = _facts_missing(txt)
    if missing: return {"ok": False, "stage": "facts", "errors": ["fixed facts missing from PDF: " + ", ".join(missing)]}
    if "City,St" in txt or "{{" in txt: return {"ok": False, "stage": "facts", "errors": ["placeholder leaked into PDF"]}
    return {"ok": True, "pages": target, "notes": notes, "final_counts": _counts(spec)}

# ------------------------------------------------------------------ cover letter
CL_WORDS = {"p1": (40, 80), "p2": (60, 125), "p3": (50, 115), "p4": (30, 75)}

def _fit_paragraph(key, text):
    """Deterministic length repair: extend short paragraphs with true filler, clip long ones."""
    lo, hi = CL_WORDS[key]
    t = _soften((text or "").strip())
    if words(t) < lo:
        t = (t.rstrip(" .") + ". " if t else "") + CL_FILLER[key]
    if words(t) > hi:
        cut = " ".join(t.split()[:hi])
        t = cut[:cut.rfind(".") + 1] if "." in cut[len(cut)//2:] else cut.rstrip(",;") + "."
    return t

def build_cover_letter(job_dir, cl, company, title, city_st, date_str) -> dict:
    cl = {k: _fit_paragraph(k, cl.get(k, "")) for k in CL_WORDS} | {"addr": cl.get("addr") or city_st}
    errs = []
    for k, (lo, hi) in CL_WORDS.items():
        w = words(cl.get(k, ""))
        if not lo <= w <= hi: errs.append(f"{k} {w} words (want {lo}-{hi})")
    cl = {k: re.sub(r"<<.*?>>", "", v) if isinstance(v, str) else v for k, v in cl.items()}
    body_txt = " ".join(cl[k] for k in CL_WORDS)
    fab = [b for b in BLOCKLIST if _has(b, body_txt.lower())]
    if fab: errs.append("blocked tech in cover letter: " + ", ".join(fab))
    sen = find_seniority(body_txt)
    if sen: errs.append("entry-level tone violated in cover letter, remove: " + ", ".join(sen))
    if errs: return {"ok": False, "stage": "validate", "errors": errs}

    t = CL_TEMPL
    t = t.replace(r"\newcommand{\clDate}{<<DATE>>}", r"\newcommand{\clDate}{" + esc(date_str) + "}")
    t = t.replace(r"\newcommand{\clHiringManager}{<<HIRING MANAGER>>}", r"\newcommand{\clHiringManager}{Hiring Manager}")
    t = t.replace(r"\newcommand{\clCompany}{<<COMPANY NAME>>}", r"\newcommand{\clCompany}{" + esc(company) + "}")
    t = t.replace(r"\newcommand{\clCompanyAddr}{<<COMPANY CITY, STATE>>}", r"\newcommand{\clCompanyAddr}{" + esc(cl.get("addr", city_st)) + "}")
    t = t.replace(r"\newcommand{\clJobTitle}{<<JOB TITLE>>}", r"\newcommand{\clJobTitle}{" + esc(title) + "}")
    t = t.replace(r"\newcommand{\clReqId}{<<REQ ID or omit>>}" + "\n", "")
    t = t.replace(r"\newcommand{\clHowFound}{<<HOW FOUND>>}", r"\newcommand{\clHowFound}{Jobright}")
    t = t.replace(r"\noindent\textbf{Re:} \clJobTitle{} \textbar{} \clReqId", r"\noindent\textbf{Re:} \clJobTitle")
    assert "<<" not in re.sub(r"(?m)^\s*%.*$", "", t), "unfilled cover letter token"
    body_re = re.compile(r"(^% P1 OPENING.*?)(\\vspace\{[0-9.]+em\}\nSincerely)", re.S | re.M)
    body = ("% P1 OPENING\n" + esc(cl["p1"]) + "\n\n% P2 PROOF\n" + esc(cl["p2"]) +
            "\n\n% P3 FIT\n" + esc(cl["p3"]) + "\n\n% P4 CLOSE\n" + esc(cl["p4"]) + "\n\n")
    t, n = body_re.subn(lambda m: body + m.group(2), t)
    assert n == 1, "cover letter body region not found"
    open(os.path.join(job_dir, "coverletter.tex"), "w", encoding="utf-8").write(t)
    if not compile_tex(job_dir, config.COVER_ENGINE, "coverletter.tex"):
        return {"ok": False, "stage": "compile", "errors": ["latex failed — see coverletter.log"]}
    n = pages(os.path.join(job_dir, "coverletter.pdf"))
    if n != config.COVER_PAGES: return {"ok": False, "stage": "fit", "errors": [f"cover letter is {n} pages (want {config.COVER_PAGES})"]}
    shutil.copy(os.path.join(job_dir, "coverletter.pdf"), os.path.join(job_dir, config.COVER_PDF))
    return {"ok": True, "pages": n}

# ------------------------------------------------------------------ entry
def build_job(job_dir, spec, cl, date_str) -> dict:
    meta = json.load(open(os.path.join(job_dir, "job.json"), encoding="utf-8"))
    r = build_resume(job_dir, spec, meta["city_st"])
    c = build_cover_letter(job_dir, cl, meta["company"], meta["title"], meta["city_st"], date_str) if r["ok"] else {"ok": False, "skipped": True}
    for f in os.listdir(job_dir):
        if f.endswith((".aux", ".log", ".out", ".synctex.gz")):
            try: os.remove(os.path.join(job_dir, f))
            except OSError: pass
    return {"folder": meta["folder"], "num": meta["num"], "resume": r, "cover_letter": c, "ok": r["ok"] and c.get("ok", False)}
