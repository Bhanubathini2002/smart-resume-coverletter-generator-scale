"""
jd_fetch.py — job description, fetched ONCE and cached in the Excel `jd` column.

Primary: the Jobright link. Jobright's SSR page embeds a __NEXT_DATA__ JSON with the JD
already STRUCTURED (summary, responsibilities, must-have / nice-to-have, core skills,
work-auth flags). No HTML scraping, no LLM distillation — one 0.6 s request per job.

Fallback: the original posting URL -> strip HTML -> plain text (for rows with no Jobright link).
Both produce the same text layout the LLM prompts expect.
"""
import html as htmlmod, json, re, ssl, time, urllib.request, urllib.error

_CTX = ssl.create_default_context(); _CTX.check_hostname = False; _CTX.verify_mode = ssl.CERT_NONE
_UA  = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return r.read().decode("utf-8", "ignore")

def _bullets(items, limit=14):
    out = []
    for it in (items or [])[:limit]:
        s = it.get("skill") if isinstance(it, dict) else it
        s = str(s or "").strip()
        if s: out.append("- " + s)
    return out

def from_jobright(url, company=""):
    """Structured JD text from a jobright.ai/jobs/info/<id> page. Raises on failure.
    Jobright rate-limits bursts with a JS 'security check' page -> back off and retry."""
    m = None
    for attempt in range(4):
        page = _get(url)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
        if m: break
        time.sleep(3 * (attempt + 1))
    if not m: raise RuntimeError("no __NEXT_DATA__ after 4 tries (security check page)")
    jr = json.loads(m.group(1))["props"]["pageProps"]["dataSource"]["jobResult"]
    q  = jr.get("qualifications") or {}
    dq = jr.get("detailQualifications") or {}
    core = [f'{s.get("skill")}' for s in (jr.get("jdCoreSkills") or []) if s.get("skill")]
    def _s(x, key):  # dict-or-string tolerant
        return str(x.get(key) or x.get("skill") or "") if isinstance(x, dict) else str(x or "")
    mh   = dq.get("mustHave") or {}
    hard = [_s(x, "skill") for x in (mh.get("hardSkill") or []) if _s(x, "skill")]
    yoe  = [_s(x, "yoe") for x in (mh.get("yoe") or []) if _s(x, "yoe")]
    edu  = [_s(x, "education") for x in (mh.get("education") or []) if _s(x, "education")]
    flags = [k for k in ("isWorkAuthRequired", "isCitizenOnly", "isClearanceRequired") if jr.get(k)]
    lines = [
        f"Title: {jr.get('jobTitle','')}",
        f"Company: {company or jr.get('companyName') or ''}".rstrip(": "),
        f"Details: {jr.get('jobLocation','')} | {jr.get('workModel','')} | {jr.get('employmentType','')} | {jr.get('jobSeniority','')} | {jr.get('salaryDesc') or 'salary n/a'}"
        + (f" | {'; '.join(yoe)}" if yoe else ""),
        "",
        (jr.get("jobSummary") or "").strip(),
        "",
        "Responsibilities:", *_bullets(jr.get("coreResponsibilities")),
        "",
        "Required:", *_bullets(q.get("mustHave")),
    ]
    if q.get("niceToHave"):
        lines += ["", "Preferred:", *_bullets(q.get("niceToHave"), 8)]
    if edu:   lines += ["", "Education: " + "; ".join(edu)]
    if flags: lines += ["", "Flags: " + ", ".join(flags)]
    lines += ["", "Keywords: " + ", ".join(dict.fromkeys(core + hard))]
    text = "\n".join(lines)
    if len(text) < 300: raise RuntimeError("JD too short")
    return text[:6000]

_DROP = re.compile(r"<(script|style|nav|header|footer|svg|noscript)[^>]*>.*?</\1>", re.S | re.I)

def from_html(url):
    """Plain-text JD from any employer/ATS page (best effort)."""
    page = _get(url)
    page = _DROP.sub(" ", page)
    page = re.sub(r"<br\s*/?>|</(p|li|div|h\d|tr)>", "\n", page, flags=re.I)
    text = htmlmod.unescape(re.sub(r"<[^>]+>", " ", page))
    text = re.sub(r"[ \t]+", " ", text); text = re.sub(r"\n\s*\n+", "\n", text).strip()
    # keep the densest region: from the first responsibilities/requirements heading onward
    m = re.search(r"(responsibilit|what you.ll do|qualifications|requirements|about the role)", text, re.I)
    if m: text = text[max(0, m.start() - 800):]
    if len(text) < 400: raise RuntimeError("page has no readable JD text")
    return text[:6000]

def fetch(jobright_url, original_url="", company=""):
    """-> (jd_text, source) ; source in {'jobright','original','FAILED'}."""
    errs = []
    if jobright_url and "jobright.ai" in jobright_url:
        try: return from_jobright(jobright_url, company), "jobright"
        except Exception as e: errs.append(f"jobright: {e}")
    if original_url and original_url.startswith("http") and "linkedin.com" not in original_url:
        try: return from_html(original_url), "original"
        except Exception as e: errs.append(f"original: {e}")
    return "FETCH_FAILED: " + " | ".join(errs)[:300], "FAILED"

if __name__ == "__main__":
    import sys
    t, s = fetch(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    print(f"[{s}] {len(t)} chars\n{t[:1500]}")
