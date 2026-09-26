"""
build_engine.py — (re)generate the engine files from templates/base_resume.tex + base_coverletter.tex.
Run this whenever either template changes:

    python engine/build_engine.py

Writes:
    engine/resume_template.tex   base resume with {{SLOTS}}  (preamble + fixed sections untouched)
    engine/base_spec.json        base resume as JSON = the model's ONLY fact source
    engine/fixed_facts.json      strings that must survive verbatim in every PDF (employers, dates, degree, ...)
    engine/allowed_tech.json     tokens that already appear in the base resume (whitelist reference)
    engine/cl_filler.json        the 4 true body paragraphs of the cover letter (length repair filler)

Template = the user's intern resume (Jake Gutierrez style, pdflatex, 1 page). Parsed generically:
    header city              'City,St'                                   -> {{CITY_ST}}
    Education coursework     \\resumeItem{Coursework: ...}                -> {{COURSEWORK}}   (LLM reorders / trims the base list)
    Experience               every \\resumeSubheading{Co}{Loc}{Role}{Dates} + items  -> {{EXPERIENCE}} (bullets editable)
    Projects                 every \\resumeProjectHeading{...}{dates} + items       -> {{PROJECTS}}   (bullets editable)
    Technical Skills         every \\textbf{Cat}{: items}                            -> {{SKILLS}}     (rows editable)
Everything else (name/links, education lines, certification, research/volunteer) is fixed text.
"""
import json, os, re, sys

ENGINE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(ENGINE)
sys.path.insert(0, ROOT)
import config

def unesc(s):
    """LaTeX-ish base text -> plain text the LLM sees (and render.esc re-escapes)."""
    s = re.sub(r"\\(?:texttt|emph|textbf|textit)\{(.*?)\}", r"\1", s)
    s = s.replace(r"$\sim$", "~").replace(r"\&", "&").replace(r"\%", "%").replace(r"\#", "#").replace(r"\_", "_")
    s = s.replace("vs.\\ ", "vs. ").replace(r"\textasciitilde{}", "~").replace(r"\textasciitilde", "~")
    s = s.replace("---", "—").replace("--", "–").replace("``", "“").replace("''", "”")
    return re.sub(r"\s+", " ", s).strip()

ITEM_RE = re.compile(r"\\resumeItem\{(.*?)\}\s*\n(?=\s*(?:\\resumeItem|\\resumeItemListEnd|\Z))", re.S)
def items(block): return [unesc(x) for x in ITEM_RE.findall(block)]

SUB_RE  = re.compile(r"\\resumeSubheading\s*\n\s*\{(.*?)\}\{(.*?)\}\s*\n\s*\{(.*?)\}\{(.*?)\}\s*\n\s*\\resumeItemListStart\n(.*?)\\resumeItemListEnd", re.S)
PROJ_RE = re.compile(r"\\resumeProjectHeading\s*\n\s*\{(.*?)\}\{(.*?)\}\s*\n\s*\\resumeItemListStart\n(.*?)\\resumeItemListEnd", re.S)
SKILL_RE = re.compile(r"\\textbf\{(.*?)\}\{: (.*?)\}(?: \\\\)?\n")

def _section(body, name):
    m = re.search(r"(\\section\{" + re.escape(name) + r"\}.*?)(?=\n%-{3,}|\\end\{document\})", body, re.S)
    assert m, f"section '{name}' not found"
    return m

def build_resume(base):
    i = base.index(r"\begin{document}"); pre, body = base[:i], base[i:]
    assert "City,St" in body, "header must contain the literal placeholder City,St"
    t = body.replace("City,St", "{{CITY_ST}}", 1)
    # coursework (inside Education, fixed otherwise)
    m_cw = re.search(r"(\\resumeItem\{Coursework: )(.*?)(\})", t)
    assert m_cw, "\\resumeItem{Coursework: ...} not found in Education"
    coursework = [c.strip() for c in unesc(m_cw.group(2)).split(",") if c.strip()]
    t = t[:m_cw.start(2)] + "{{COURSEWORK}}" + t[m_cw.end(2):]
    # experience: replace everything between ListStart and ListEnd of the Experience section
    exp_sec = _section(body, "Experience").group(1)
    comps = SUB_RE.findall(exp_sec)
    assert comps, "no \\resumeSubheading blocks in Experience"
    t = t.replace(exp_sec, re.sub(r"(\\resumeSubHeadingListStart\n)(.*)(\s*\\resumeSubHeadingListEnd)", r"\1{{EXPERIENCE}}\3", exp_sec, count=1, flags=re.S), 1)
    # projects
    proj_sec = _section(body, "Projects").group(1)
    projs = PROJ_RE.findall(proj_sec)
    assert projs, "no \\resumeProjectHeading blocks in Projects"
    t = t.replace(proj_sec, re.sub(r"(\\resumeSubHeadingListStart\n)(.*)(\s*\\resumeSubHeadingListEnd)", r"\1{{PROJECTS}}\3", proj_sec, count=1, flags=re.S), 1)
    # skills
    sk_sec = _section(body, "Technical Skills").group(1)
    skills = SKILL_RE.findall(sk_sec)
    assert skills, "no \\textbf{Cat}{: items} rows in Technical Skills"
    t = t.replace(sk_sec, re.sub(r"(\\small\{\\item\{\n)(.*?)(\s*\}\})", r"\1{{SKILLS}}\3", sk_sec, count=1, flags=re.S), 1)
    template = pre + t
    slots = set(re.findall(r"\{\{([A-Z_]+)\}\}", template))
    need = {"CITY_ST", "COURSEWORK", "EXPERIENCE", "PROJECTS", "SKILLS"}
    assert not (need - slots), f"template slots not found: {need - slots}"

    def proj_meta(head):
        """'\\textbf{ParseDoc.ai} $|$ \\emph{Python, PyTorch}' -> (name, tech)"""
        n = re.search(r"\\textbf\{(.*?)\}", head); tech = re.search(r"\\emph\{(.*?)\}", head)
        return unesc(n.group(1) if n else head), unesc(tech.group(1) if tech else "")
    edu = SUB_RE.search(_section(body, "Education").group(1))
    m_name = re.search(r"\\textbf\{\\Huge \\scshape (.*?)\}", body)
    spec = {
        "name": unesc(m_name.group(1)) if m_name else "Resume",
        "education": ({"school": unesc(edu.group(1)), "location": unesc(edu.group(2)), "degree": unesc(edu.group(3)), "dates": unesc(edu.group(4))} if edu else {}),
        "coursework": coursework,
        "skills": [{"category": unesc(a), "items": unesc(b)} for a, b in skills],
        "experience": [{"company": unesc(c), "location": unesc(loc), "role": unesc(r), "dates": unesc(d),
                        "_head": f"{{{c}}}{{{loc}}}\n      {{{r}}}{{{d}}}", "bullets": items(b)} for c, loc, r, d, b in comps],
        "projects": [{"name": proj_meta(h)[0], "tech": proj_meta(h)[1], "dates": unesc(d),
                      "_head": f"{{{h}}}{{{d}}}", "bullets": items(b)} for h, d, b in projs],
    }
    fixed = []
    for e in spec["experience"]:
        fixed.append(e["company"]); fixed += [x.strip() for x in re.split(r"[–—]", e["dates"]) if x.strip()]
    if edu: fixed += [unesc(edu.group(1)), unesc(edu.group(3))]
    fixed += [p["name"] for p in spec["projects"]]
    return template, spec, list(dict.fromkeys(f for f in fixed if f))

def allowed_tokens(spec):
    blob = json.dumps({k: v for k, v in spec.items()}, ensure_ascii=False); toks = set()
    for part in re.split(r"[,;/()\[\]]| and | with | via | on | using |\s---\s|—|–|\|", blob):
        part = part.strip(" .:\"'{}")
        if 1 < len(part) <= 40 and re.search(r"[A-Za-z]", part) and not part.islower():
            toks.add(part)
    return sorted(toks)

_MACRO = {r"\clCompany's": "your company's", r"\clCompany{}": "your company", r"\clCompany": "your company",
          r"\clJobTitle{}": "advertised", r"\clJobTitle": "advertised", r"\clHowFound": "Jobright"}

def cl_filler(cl):
    """The 4 body paragraphs of the cover letter template as plain text -> true filler sentences."""
    body = re.search(r"^% P1 OPENING(.*?)\\vspace\{[0-9.]+em\}\nSincerely", cl, re.S | re.M)
    assert body, "cover letter body markers (% P1 OPENING ... Sincerely) not found"
    parts = re.split(r"^% P[1-4] [A-Z]+[^\n]*\n", "% P1 OPENING" + body.group(1), flags=re.M)[1:]
    assert len(parts) == 4, "cover letter needs exactly 4 body blocks (% P1 .. % P4)"
    out = {}
    for k, part in zip(("p1", "p2", "p3", "p4"), parts):
        lines = [l for l in part.splitlines() if l.strip() and not l.lstrip().startswith("%")]
        txt = re.sub(r"<<.*?>>", "", " ".join(lines))
        for a, b in _MACRO.items(): txt = txt.replace(a, b)
        txt = re.sub(r"\\textbf\{(.*?)\}", r"\1", txt)
        txt = re.sub(r"\\[a-zA-Z]+\{?", "", txt)
        txt = unesc(txt).replace("{", "").replace("}", "")
        out[k] = re.sub(r"\s+", " ", txt).strip()
    return out

def main():
    base = open(config.BASE_RESUME, encoding="utf-8").read()
    cl = open(config.BASE_COVERLETTER, encoding="utf-8").read()
    template, spec, fixed = build_resume(base)
    open(os.path.join(ENGINE, "resume_template.tex"), "w", encoding="utf-8").write(template)
    json.dump(spec, open(os.path.join(ENGINE, "base_spec.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump(fixed, open(os.path.join(ENGINE, "fixed_facts.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    toks = allowed_tokens(spec)
    json.dump(toks, open(os.path.join(ENGINE, "allowed_tech.json"), "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    filler = cl_filler(cl)
    json.dump(filler, open(os.path.join(ENGINE, "cl_filler.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"name: {spec['name']}")
    print(f"coursework: {spec['coursework']}")
    print(f"skills rows: {[s['category'] for s in spec['skills']]}")
    print(f"experience: {[(e['company'], e['role'], e['dates'], len(e['bullets'])) for e in spec['experience']]}")
    print(f"projects:   {[(p['name'], p['dates'], len(p['bullets'])) for p in spec['projects']]}")
    print(f"fixed facts ({len(fixed)}): {fixed}")
    print(f"allowed tech tokens: {len(toks)}   cl filler words: {[len(v.split()) for v in filler.values()]}")

if __name__ == "__main__":
    main()
