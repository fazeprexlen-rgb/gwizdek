#!/usr/bin/env python3
"""Gwizdek: generator bloga o aktualnych wydarzeniach w sporcie.

Co robi:
1. Pobiera dzienne trendy wyszukiwań Google (Google Trends, RSS) dla Polski
   i wybiera z nich tematy sportowe.
2. Dla każdego takiego tematu pobiera najnowsze wiadomości (Google News, RSS).
3. Dodaje nagłówki z działu Sport oraz wiadomości z kilku dyscyplin.
4. Zapisuje dane dnia do data/RRRR-MM-DD.json i buduje statyczną stronę w site/.

Używa wyłącznie biblioteki standardowej Pythona (3.9+).
Publikowane są tytuły, nazwy źródeł i linki. Treść artykułów nie jest kopiowana.
"""
import argparse
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Warsaw")
SITE_NAME = "Gwizdek"

TRENDS_URL = "https://trends.google.com/trending/rss?geo=PL"
NEWS_SEARCH = "https://news.google.com/rss/search?q={q}&hl=pl&gl=PL&ceid=PL:pl"
SPORT_SECTION = "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=pl&gl=PL&ceid=PL:pl"

# Nazwa działu na stronie -> zapytanie do Google News (when:1d = ostatnia doba).
DISCIPLINES = {
    "Piłka nożna": "piłka nożna when:1d",
    "Koszykówka": "koszykówka OR NBA when:1d",
    "Siatkówka": "siatkówka when:1d",
    "Tenis": "tenis ATP OR WTA when:1d",
    "Formuła 1": "Formuła 1 when:1d",
    "Sporty walki": "MMA OR UFC OR boks when:1d",
    "Skoki narciarskie": "skoki narciarskie when:1d",
}

MAX_TOPICS = 8
ITEMS_PER_TOPIC = 3
ITEMS_PER_DISCIPLINE = 4
MAX_HEADLINES = 8

# Początki słów, po których rozpoznajemy sportowy temat w trendach.
SPORT_RE = re.compile(
    r"\b(?:piłk|futbol|liga|ligi|ligę|mecz|puchar|mistrzost|eliminacj|reprezentacj|kadra|kadry|"
    r"ekstraklas|transfer|trener|bramk|gol\b|nba|nfl|nhl|f1\b|formuł|grand prix|tenis|atp|wta|"
    r"siatk|koszyk|skoki|skoczk|ufc|mma|boks|igrzysk|olimp|lekkoatlet|biegi|narciars|"
    r"champions|premier league|la liga|bundesliga|serie a|real madrid|barcelon|legia|lech|"
    r"lewandowsk|świątek|hurkacz|stoch|kubacki)",
    re.IGNORECASE,
)

MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca",
          "sierpnia", "września", "października", "listopada", "grudnia"]

esc = lambda s: html.escape(s or "", quote=True)


# --------------------------------------------------------------------------- pobieranie

def fetch(url, fixtures):
    """Pobiera adres albo (w trybie testowym) czyta plik z katalogu fixtures."""
    if fixtures:
        name = "trends.xml" if "trends.google" in url else "news.xml"
        return (Path(fixtures) / name).read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; GwizdekBot/1.0)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def get(url, fixtures):
    try:
        return fetch(url, fixtures)
    except Exception as exc:  # sieć bywa zawodna, więc jeden błąd nie przerywa całości
        print(f"[ostrzeżenie] {url}: {exc}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- parsowanie

def local(tag):
    return tag.rsplit("}", 1)[-1]


def text_of(el, name):
    for child in el:
        if local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def iso_date(value):
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except Exception:
        return ""


def parse_news(raw, limit):
    items, seen = [], set()
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        print(f"[ostrzeżenie] błędny XML: {exc}", file=sys.stderr)
        return items
    for it in root.iter("item"):
        title, link, source = text_of(it, "title"), text_of(it, "link"), text_of(it, "source")
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3].strip()
        if not title or not link.startswith(("http://", "https://")) or link in seen:
            continue
        seen.add(link)
        items.append({"title": title, "url": link, "source": source,
                      "published": iso_date(text_of(it, "pubDate"))})
        if len(items) >= limit:
            break
    return items


def parse_trends(raw):
    trends = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        print(f"[ostrzeżenie] błędny XML trendów: {exc}", file=sys.stderr)
        return trends
    for it in root.iter("item"):
        news_titles = []
        for child in it:
            if local(child.tag) == "news_item":
                t = text_of(child, "news_item_title")
                if t:
                    news_titles.append(t)
        trends.append({"title": text_of(it, "title"),
                       "traffic": text_of(it, "approx_traffic"),
                       "news_titles": news_titles})
    return trends


def is_sport(trend):
    return bool(SPORT_RE.search(trend["title"] + " " + " ".join(trend["news_titles"])))


def news_for(query, limit, fixtures):
    raw = get(NEWS_SEARCH.format(q=urllib.parse.quote_plus(query)), fixtures)
    return parse_news(raw, limit) if raw else []


# --------------------------------------------------------------------------- zbieranie danych dnia

def collect(fixtures, day):
    topics = []
    raw = get(TRENDS_URL, fixtures)
    for trend in (parse_trends(raw) if raw else []):
        if not trend["title"] or not is_sport(trend):
            continue
        items = news_for(trend["title"] + " when:2d", ITEMS_PER_TOPIC, fixtures)
        if items:
            topics.append({"title": trend["title"], "traffic": trend["traffic"], "items": items})
        if len(topics) >= MAX_TOPICS:
            break

    raw = get(SPORT_SECTION, fixtures)
    headlines = parse_news(raw, MAX_HEADLINES) if raw else []

    disciplines = []
    for name, query in DISCIPLINES.items():
        items = news_for(query, ITEMS_PER_DISCIPLINE, fixtures)
        if items:
            disciplines.append({"name": name, "items": items})

    if not (topics or headlines or disciplines):
        raise SystemExit("Nie udało się pobrać żadnych danych. Strona nie została zmieniona.")

    return {"date": day.isoformat(),
            "generated": datetime.now(TZ).isoformat(timespec="minutes"),
            "topics": topics, "headlines": headlines, "disciplines": disciplines}


# --------------------------------------------------------------------------- HTML

CSS = """
:root{--bg:#f6f7f9;--surface:#fff;--fg:#12151c;--muted:#586071;--line:#e1e4ea;--accent:#c62828;
--font-display:"Inter Tight","Helvetica Neue",Arial,sans-serif;--font-body:"Inter",system-ui,-apple-system,"Segoe UI",sans-serif;
--font-mono:"JetBrains Mono",ui-monospace,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#0e1117;--surface:#151a23;--fg:#eceef3;--muted:#9aa3b4;--line:#242b38;--accent:#ff7b72;color-scheme:dark}}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:1.0625rem/1.6 var(--font-body);-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.wrap{width:100%;max-width:1080px;margin-inline:auto;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
header{border-bottom:1px solid var(--line)}
header .wrap{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:.5rem 1.5rem;padding-block:.9rem}
.logo{font:700 1.4rem var(--font-display);letter-spacing:-.03em}
.logo i{display:inline-block;width:.5em;height:.5em;background:var(--accent);border-radius:50%;margin-left:.12em}
nav{display:flex;gap:1.25rem;font-size:.95rem;color:var(--muted)}
nav a:hover{color:var(--fg)}
main{padding-block:clamp(2rem,6vw,4rem)}
.eyebrow{font:.75rem var(--font-mono);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.eyebrow b{color:var(--accent);font-weight:500}
h1,h2,h3{font-family:var(--font-display);font-weight:700;letter-spacing:-.025em;line-height:1.1;margin:0;text-wrap:balance}
h1{font-size:clamp(2.3rem,7.5vw,4.8rem);letter-spacing:-.04em;margin-top:.8rem;max-width:16ch}
.sub{color:var(--muted);font-size:1.1rem;max-width:52ch;margin:1.25rem 0 0}
h2{font-size:1.5rem;margin:3rem 0 1.25rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,320px),1fr));gap:2.25rem 2rem}
.card{min-width:0;border-top:1px solid var(--fg);padding-top:1rem}
.card h3{font-size:1.3rem;margin:.4rem 0 .8rem}
ul{list-style:none;margin:0;padding:0;display:grid;gap:.9rem}
li{min-width:0}
li a{display:block;font-weight:500;line-height:1.35}
li a:hover{text-decoration:underline;text-decoration-color:var(--accent);text-decoration-thickness:2px;text-underline-offset:.18em}
.src{display:block;color:var(--muted);font-size:.82rem;margin-top:.15rem}
.empty{color:var(--muted)}
.days{max-width:520px}
.days li a{display:flex;justify-content:space-between;gap:1rem;padding-block:.6rem;border-bottom:1px solid var(--line);font-weight:500}
footer{border-top:1px solid var(--line);padding-block:2rem;color:var(--muted);font-size:.88rem}
footer p{margin:.3rem 0}
"""

PAGE = """<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<meta name="description" content="Codzienny przegląd tego, co w sporcie wyszukują Polacy.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@600;700&family=Inter:wght@400;500&family=JetBrains+Mono:wght@400;500&display=swap">
<style>{{CSS}}</style>
</head>
<body>
<header><div class="wrap">
<a class="logo" href="{{ROOT}}index.html" aria-label="{{SITE}}, strona główna">{{SITE}}<i aria-hidden="true"></i></a>
<nav aria-label="Nawigacja"><a href="{{ROOT}}index.html">Dziś</a><a href="{{ROOT}}archiwum.html">Archiwum</a></nav>
</div></header>
<main class="wrap">
{{BODY}}
</main>
<footer><div class="wrap">
<p>Tytuły i linki pochodzą z Google News i Google Trends. Treść artykułów należy do ich wydawców, kliknij tytuł, żeby przeczytać całość.</p>
<p>Strona aktualizuje się automatycznie raz na dobę.</p>
</div></footer>
</body>
</html>
"""


def fmt_date(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def when(iso):
    if not iso:
        return ""
    d = datetime.fromisoformat(iso).astimezone(TZ)
    return f"{d.day} {MONTHS[d.month - 1]}, {d:%H:%M}"


def li(it):
    meta = " · ".join(x for x in (it.get("source", ""), when(it.get("published", ""))) if x)
    return (f'<li><a href="{esc(it["url"])}" target="_blank" rel="noopener noreferrer">{esc(it["title"])}</a>'
            f'<span class="src">{esc(meta)}</span></li>')


def card(label, title, items):
    return (f'<section class="card"><span class="eyebrow">{label}</span><h3>{esc(title)}</h3>'
            f'<ul>{"".join(li(i) for i in items)}</ul></section>')


def render_page(title, body, root):
    return (PAGE.replace("{{TITLE}}", esc(title)).replace("{{CSS}}", CSS)
            .replace("{{ROOT}}", root).replace("{{SITE}}", SITE_NAME).replace("{{BODY}}", body))


def render_day(data, root):
    updated = datetime.fromisoformat(data["generated"]).strftime("%H:%M")
    parts = [f'<span class="eyebrow"><b>{fmt_date(data["date"])}</b> · zaktualizowano {updated}</span>',
             "<h1>Co dziś w sporcie.</h1>",
             '<p class="sub">Tematy, które Polacy wyszukują w Google, i najnowsze wiadomości z kilku dyscyplin.</p>']

    parts.append("<h2>Na topie w wyszukiwarce</h2>")
    if data["topics"]:
        cards = []
        for t in data["topics"]:
            label = f'<b>{esc(t["traffic"])}</b> wyszukań' if t.get("traffic") else "Trend"
            cards.append(card(label, t["title"], t["items"]))
        parts.append(f'<div class="grid">{"".join(cards)}</div>')
    else:
        parts.append('<p class="empty">Dziś żaden sportowy temat nie trafił do trendów Google.</p>')

    if data["headlines"]:
        parts.append("<h2>Nagłówki dnia</h2>")
        parts.append(f'<ul>{"".join(li(i) for i in data["headlines"])}</ul>')

    if data["disciplines"]:
        parts.append("<h2>Dyscypliny</h2>")
        cards = [card("Dyscyplina", d["name"], d["items"]) for d in data["disciplines"]]
        parts.append(f'<div class="grid">{"".join(cards)}</div>')

    return render_page(f"{SITE_NAME}, {fmt_date(data['date'])}", "\n".join(parts), root)


def render_archive(dates):
    rows = "".join(f'<li><a href="dni/{d}.html"><span>{fmt_date(d)}</span><span aria-hidden="true">→</span></a></li>'
                   for d in dates)
    body = ('<span class="eyebrow">Archiwum</span><h1>Wcześniejsze dni.</h1>'
            f'<h2>Wszystkie wydania</h2><ul class="days">{rows}</ul>')
    return render_page(f"Archiwum, {SITE_NAME}", body, "")


def build_site(out_dir, data_dir):
    files = sorted(Path(data_dir).glob("????-??-??.json"), reverse=True)
    if not files:
        raise SystemExit("Brak danych w katalogu data/.")
    out = Path(out_dir)
    (out / "dni").mkdir(parents=True, exist_ok=True)
    dates = []
    for i, f in enumerate(files):
        data = json.loads(f.read_text(encoding="utf-8"))
        dates.append(data["date"])
        (out / "dni" / f"{data['date']}.html").write_text(render_day(data, "../"), encoding="utf-8")
        if i == 0:
            (out / "index.html").write_text(render_day(data, ""), encoding="utf-8")
    (out / "archiwum.html").write_text(render_archive(dates), encoding="utf-8")
    return len(dates)


# --------------------------------------------------------------------------- start

def main():
    ap = argparse.ArgumentParser(description="Generator bloga sportowego Gwizdek")
    ap.add_argument("--out", default="site", help="katalog wyjściowy strony")
    ap.add_argument("--data", default="data", help="katalog z danymi dni (JSON)")
    ap.add_argument("--fixtures", help="katalog z plikami trends.xml i news.xml (tryb testowy, bez internetu)")
    ap.add_argument("--rebuild-only", action="store_true", help="tylko zbuduj stronę z istniejących danych")
    args = ap.parse_args()

    data_dir = Path(args.data)
    data_dir.mkdir(parents=True, exist_ok=True)

    if not args.rebuild_only:
        day = datetime.now(TZ).date()
        data = collect(args.fixtures, day)
        (data_dir / f"{day.isoformat()}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Zapisano dane z {day}: tematów {len(data['topics'])}, "
              f"nagłówków {len(data['headlines'])}, dyscyplin {len(data['disciplines'])}.")

    n = build_site(args.out, data_dir)
    print(f"Zbudowano stronę w {args.out}/ ({n} dni w archiwum).")


if __name__ == "__main__":
    main()
