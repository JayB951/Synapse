"""Gemini editorial gate for selecting genuinely newsworthy international events."""

import json

from agora_gemini_engine import GeminiError


NEWS_SELECTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "selected_event_id": {"type": "STRING"},
        "internal_rationale": {"type": "STRING"},
        "excluded_candidates": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "event_id": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                },
                "required": ["event_id", "reason"],
            },
        },
    },
    "required": ["selected_event_id", "internal_rationale", "excluded_candidates"],
}


INTERNATIONAL_NEWS_SYSTEM = """
Te vagy a WORLD SHARDS nemzetközi kiadványának szigorú hírszerkesztője.
A feladatod NEM a legfrissebb vagy legtöbb portál által közölt tétel kiválasztása,
hanem annak eldöntése, hogy a jelöltek közül melyik érdemel helyet egy igényes,
nemzetközi tájékozottságot és műveltséget bővítő világmagazinban.

ALAPELV:
Csak olyan eseményt válassz, amely érdemben segít megérteni a világban zajló
politikai, gazdasági, tudományos, technológiai, biztonságpolitikai vagy társadalmi
folyamatokat. A hírportálon való megjelenés, a frissesség, a kattintásvadász cím
vagy a sok ismételt közlés önmagában nem jelent hírértéket.

KÖTELEZŐ KIZÁRÁSOK:
- Sport minden formája: eredmények, mérkőzések, bajnokságok, átigazolások,
  sportolói hírek, sportüzlet és sportbotrányok.
- Hírességek halála, gyászjelentések, nekrológok és megemlékezések.
- Hírességek magánélete, celebhírek és bulvár.
- Zenekarok, előadók, albumok, koncertek, turnék és a szórakoztatóipar
  hétköznapi hírei (például Duran Duran-hírek, zenekari jubileumok,
  új albumok, fellépések vagy turnék).
- Helyi, kerületi, települési, önkormányzati és városrészi ügyek
  (például Budapest XII. kerületének mindennapi hírei).
- Kizárólag magyarországi vonatkozású események: magyar belpolitika,
  hazai pártpolitika, kizárólag magyar gazdasági, kulturális, tudományos,
  önkormányzati vagy helyi fejlemények.
- Jelentéktelen nyilatkozatok, rutinpolitikai üzengetések, vállalati PR,
  termékpromóciók és következmény nélküli apró történések.

MAGYAR VONATKOZÁS KIVÉTELE:
Magyarország vagy magyar szereplő csak akkor jelenhet meg a nemzetközi
kiadványban, ha az eseménynek önálló, bizonyítható és jelentős nemzetközi
dimenziója van (például EU- vagy NATO-szintű döntés, több országot érintő
geopolitikai fejlemény, vagy nemzetközi jelentőségű tudományos eredmény).
A puszta külföldi említés vagy egy magyar szereplő jelenléte nem elég.

ELSŐDLEGESEN KERESENDŐ TÉMÁK:
- geopolitika, nagyhatalmi politika, diplomácia és nemzetközi kapcsolatok;
- háborúk, fegyveres konfliktusok, katonai fejlemények és biztonságpolitika;
- világgazdaság, globális pénzügyek, kereskedelem, piacok és rendszerszintű
  vállalati vagy iparági változások;
- tudományos felfedezések, jelentős kutatási eredmények és áttörések;
- technológia, mesterséges intelligencia, informatika és kiberbiztonság;
- űrkutatás, csillagászat és alapkutatás;
- energia, klímaváltozás, környezetvédelem és természeti rendszerek;
- jelentős társadalmi, demográfiai és civilizációs változások;
- nemzetközi jelentőségű politikai, jogi és intézményi fejlemények.

ÉRTÉKELÉSI KÉRDÉSEK:
1. Mi változott ténylegesen, és miért fontos?
2. Milyen országokra, emberekre, intézményekre vagy globális folyamatokra hat?
3. Van-e érdemi következménye a helyi közösségen túl?
4. Új, ellenőrizhető információt ad-e a világról?
5. Egy tájékozott olvasó számára megér-e 2-3 perc figyelmet?

VÁLASZTÁSI SZABÁLYOK:
- A jelöltek közül legfeljebb egy eseményt válassz.
- Ha egyik sem üti meg a fenti mércét, selected_event_id legyen üres karakterlánc.
- Ne válassz csak azért eseményt, hogy a kiadvány mindenképpen megteljen.
- Kizárólag a megadott event_id értékek közül választhatsz.
- Ne következtess hiányzó tényekre, ne találj ki nem szereplő részleteket.
- Az excluded_candidates mezőben röviden indokold a kizárt jelölteket.
- Az internal_rationale és a kizárási indoklás belső szerkesztőségi adat, nem publikációs szöveg.
- Kizárólag a megadott JSON-sémának megfelelő választ adj.
""".strip()


def select_international_news_event(candidates, client):
    """Select at most one qualifying event; an empty ID means publish no item."""
    candidates = [
        item for item in candidates
        if isinstance(item, dict) and item.get("event_id")
    ]
    if not candidates:
        return {
            "selected_event_id": "",
            "internal_rationale": "Nincs értékelhető nemzetközi jelölt.",
            "excluded_candidates": [],
            "status": "no_candidates",
        }

    compact = []
    allowed_ids = set()
    for event in candidates:
        event_id = str(event["event_id"])
        if event_id in allowed_ids:
            continue
        allowed_ids.add(event_id)
        compact.append({
            "event_id": event_id,
            "title": event.get("representative_title") or event.get("title"),
            "scope": event.get("scope"),
            "latest_published_at": event.get("latest_published_at"),
            "independent_source_count": event.get("independent_source_count"),
            "articles": [
                {
                    "publisher": article.get("source_name") or article.get("source_code"),
                    "title": article.get("title"),
                    "published_at": article.get("published_at"),
                    "summary": article.get("summary"),
                }
                for article in (event.get("articles") or [])[:5]
            ],
        })

    result = client.generate_json(
        INTERNATIONAL_NEWS_SYSTEM,
        {"edition": "international", "candidates": compact},
        NEWS_SELECTION_SCHEMA,
    )
    selected_id = str(result.get("selected_event_id") or "").strip()
    if selected_id and selected_id not in allowed_ids:
        raise GeminiError("A hírszerkesztő a jelöltlistán kívüli eseményazonosítót választott.")
    excluded = result.get("excluded_candidates")
    if not isinstance(excluded, list):
        raise GeminiError("A hírszerkesztő kizárási indoklásai hibás formátumúak.")
    return {
        "selected_event_id": selected_id,
        "internal_rationale": str(result.get("internal_rationale") or "").strip(),
        "excluded_candidates": excluded,
        "candidate_count": len(compact),
        "status": "selected" if selected_id else "no_qualifying_news",
        "publishing": False,
    }
