# Gwizdek: blog o sporcie, który aktualizuje się sam

Program `generate.py` raz na dobę:

1. pobiera dzienne trendy wyszukiwań Google dla Polski (Google Trends, kanał RSS),
2. wybiera z nich tematy sportowe i dla każdego pobiera najnowsze wiadomości (Google News, RSS),
3. dodaje nagłówki z działu Sport oraz wiadomości z kilku dyscyplin,
4. buduje statyczną stronę w katalogu `site/` (dzień bieżący, archiwum wcześniejszych dni).

Wymaga tylko Pythona 3.9+ i nie ma żadnych zależności do instalacji.

## Dlaczego nie scrapuje wyników wyszukiwania Google

Bezpośrednie pobieranie strony wyników Google łamie jego regulamin i jest szybko blokowane (CAPTCHA).
Zamiast tego program używa oficjalnych kanałów RSS Google Trends i Google News, które pokazują to samo:
co ludzie wyszukują i co o tym piszą media. Na stronie trafiają tylko tytuły, nazwy źródeł i linki,
a nie treść artykułów, więc nic nie jest kopiowane od wydawców.

## Uruchomienie raz, na swoim komputerze

```bash
python3 generate.py          # pobiera dane i buduje site/
python3 -m http.server -d site 8000   # podgląd na http://localhost:8000
```

Test bez internetu, na przykładowych plikach:

```bash
python3 generate.py --fixtures tests/fixtures --data /tmp/dane --out /tmp/site
```

## Automatyczna aktualizacja co 24 godziny

### Wariant A: GitHub Actions + GitHub Pages (za darmo, bez własnego serwera)

1. Załóż repozytorium na GitHubie i wgraj do niego cały ten katalog.
2. W repozytorium wejdź w **Settings → Pages** i jako **Source** wybierz **GitHub Actions**.
3. Wejdź w **Actions**, wybierz „Codzienna aktualizacja bloga” i kliknij **Run workflow**, żeby sprawdzić działanie.
4. Od tej pory workflow `.github/workflows/daily.yml` uruchamia się sam codziennie o 05:15 UTC
   (06:15 lub 07:15 czasu polskiego). Dane każdego dnia są zapisywane w katalogu `data/`,
   dlatego archiwum rośnie z dnia na dzień.

Godzinę zmienisz w linii `cron:` w pliku workflow.

### Wariant B: własny serwer lub komputer (cron)

```cron
15 6 * * * cd /sciezka/do/sport-blog && /usr/bin/python3 generate.py --out /var/www/html
```

## Dostosowanie

W `generate.py` na górze pliku możesz zmienić:

- `DISCIPLINES`: dyscypliny i zapytania wyszukiwania,
- `SPORT_RE`: słowa, po których rozpoznawany jest sportowy temat w trendach,
- `MAX_TOPICS`, `ITEMS_PER_TOPIC`: ile tematów i wiadomości pokazywać,
- `TRENDS_URL`: kod kraju (`geo=PL`).

## Uwagi

- Gdy Google nie odpowie, program wypisze ostrzeżenie i pominie ten element. Jeśli nie pobierze niczego,
  kończy się błędem i nie nadpisuje poprzedniej wersji strony.
- Format kanału Google Trends bywa zmieniany. Gdyby lista „Na topie w wyszukiwarce” była stale pusta,
  sprawdź adres w `TRENDS_URL`.
- Jeśli publikujesz stronę publicznie, zachowaj w stopce informację o źródłach.
