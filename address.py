"""
address.py — Location cell -> full street address (for application forms) + "City, ST" (resume header).

Rule (Bhanu, 2026-09-12): exact city in the address book -> that address;
city missing -> nearest city in the SAME state; remote / "United States" / junk -> Houston default.
"""
import re
import openpyxl
import config

NEAREST = {  # (jd city, ST) -> (address-book city, ST)
    ('san mateo','CA'):('san francisco','CA'), ('santa clara','CA'):('san jose','CA'),
    ('sunnyvale','CA'):('san jose','CA'),      ('palo alto','CA'):('san jose','CA'),
    ('mountain view','CA'):('san jose','CA'),  ('menlo park','CA'):('san francisco','CA'),
    ('south san francisco','CA'):('san francisco','CA'), ('dublin','CA'):('san francisco','CA'),
    ('burlingame','CA'):('san francisco','CA'),('foster city','CA'):('san francisco','CA'),
    ('redwood city','CA'):('san francisco','CA'), ('cupertino','CA'):('san jose','CA'),
    ('hawthorne','CA'):('los angeles','CA'),   ('irvine','CA'):('los angeles','CA'),
    ('santa monica','CA'):('los angeles','CA'),('pasadena','CA'):('los angeles','CA'),
    ('french lake','MN'):('minneapolis','MN'), ('georgetown','KY'):('lexington','KY'),
    ('irving','TX'):('dallas','TX'),           ('plano','TX'):('dallas','TX'),
    ('frisco','TX'):('dallas','TX'),           ('richardson','TX'):('dallas','TX'),
    ('round rock','TX'):('austin','TX'),       ('bastrop','TX'):('austin','TX'),
    ('jupiter','FL'):('miami','FL'),           ('fort lauderdale','FL'):('miami','FL'),
    ('aberdeen','MD'):('baltimore','MD'),      ('fort meade','MD'):('baltimore','MD'),
    ('patuxent river','MD'):('baltimore','MD'),('bethesda','MD'):('baltimore','MD'),
    ('leawood','KS'):('overland park','KS'),
    ('kirkland','WA'):('seattle','WA'),        ('redmond','WA'):('seattle','WA'),
    ('bellevue','WA'):('seattle','WA'),
    ('quincy','MA'):('boston','MA'),           ('cambridge','MA'):('boston','MA'),
    ('north collins','NY'):('buffalo','NY'),   ('bolingbrook','IL'):('chicago','IL'),
    ('el dorado','AR'):('little rock','AR'),
    ('dearborn','MI'):('detroit','MI'),        ('ann arbor','MI'):('detroit','MI'),
    ('arlington','VA'):('richmond','VA'),      ('mclean','VA'):('richmond','VA'),
    ('reston','VA'):('richmond','VA'),         ('herndon','VA'):('richmond','VA'),
}

LOC_RE    = re.compile(r'([A-Za-z][A-Za-z .\-]{1,25}),\s*([A-Z]{2})\b')
CITYST_RE = re.compile(r',\s*([A-Za-z .\-]+),\s*([A-Z]{2})\s*\d{5}')

_BOOK = None

def load_book():
    global _BOOK
    if _BOOK: return _BOOK
    ws = openpyxl.load_workbook(config.ADDRESS_BOOK, read_only=True).active
    by_city, by_state = {}, {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[1]: continue
        city, state, addr = str(row[1]).strip(), str(row[2]).strip().upper(), str(row[4]).strip()
        by_city[(city.lower(), state)] = addr
        by_state.setdefault(state, []).append((city, addr))
    _BOOK = (by_city, by_state)
    return _BOOK

def resolve(location):
    """-> (full_address, how) where how in {'exact','nearest','default'}."""
    by_city, by_state = load_book()
    default = by_city[config.DEFAULT_CITY_ST]
    if not location: return default, "default"
    hits = LOC_RE.findall(str(location).strip())
    if not hits: return default, "default"
    city, state = hits[-1][0].strip().lower(), hits[-1][1].upper()   # LAST match: titles leak into the cell
    if (city, state) in by_city:  return by_city[(city, state)], "exact"
    if (city, state) in NEAREST:  return by_city[NEAREST[(city, state)]], "nearest"
    if state in by_state:         return by_state[state][0][1], "nearest"
    return default, "default"

def city_st(full_address):
    """'2850 West Walnut Street, Chicago, IL 60612' -> 'Chicago, IL'."""
    m = CITYST_RE.search(full_address or "")
    return f"{m.group(1).strip()}, {m.group(2)}" if m else "Houston, TX"
