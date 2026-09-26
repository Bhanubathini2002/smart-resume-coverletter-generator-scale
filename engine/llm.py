"""
llm.py — one function against ANY OpenAI-compatible chat endpoint (urllib only, no SDK).
Retries on 429/5xx, drops response_format if the endpoint rejects JSON mode,
parses tolerant JSON, and runs a validate->repair loop (max 3 tries).
"""
import json, re, sys, time, urllib.request, urllib.error, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prompts

def chat(base_url, api_key, model, messages, temperature=0.2, max_tokens=3500, json_mode=True, timeout=240):
    body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if json_mode: body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="replace")
            if e.code in (400, 422) and json_mode and ("response_format" in txt or "json_object" in txt):
                return chat(base_url, api_key, model, messages, temperature, max_tokens, json_mode=False, timeout=timeout)
            if e.code in (429, 500, 502, 503, 504, 529) and attempt < 3:
                time.sleep(2 ** attempt * 3); continue
            raise RuntimeError(f"HTTP {e.code}: {txt[:300]}")
        except Exception:
            if attempt < 3: time.sleep(2 ** attempt * 3); continue
            raise

def extract_json(text):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    m = re.search(r"\{.*\}", t, re.S)
    if m: t = m.group(0)
    t = re.sub(r",\s*([}\]])", r"\1", t)
    return json.loads(t)

def json_call(args, msgs, system, validate_fn, max_tries=3):
    """-> (obj, []) on success, (None, errors) after max_tries."""
    raw, errors = "", []
    for _ in range(max_tries):
        try:
            raw = chat(args.base_url, args.api_key, args.model, msgs, max_tokens=args.max_tokens)
            obj = extract_json(raw)
        except Exception as e:
            errors = [f"LLM/JSON error: {e}"]; msgs = prompts.repair_messages(system, raw, errors); continue
        errors = validate_fn(obj)
        if not errors: return obj, []
        msgs = prompts.repair_messages(system, json.dumps(obj, ensure_ascii=False), errors)
    return None, errors
