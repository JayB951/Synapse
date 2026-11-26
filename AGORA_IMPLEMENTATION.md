# AGORA – megvalósítási specifikáció

Állapot: elfogadott alapelvek, megvalósítás alatt  
Projekt: WORLD SHARDS / SYNAPSE  
Prioritás: elsődleges fejlesztési cél

## 1. Cél

Az AGORA a WORLD SHARDS napi közéleti-történelmi rovata. Naponta két aktuális eseményt dolgoz fel:
- egy magyarországi / magyar vonatkozású hírt;
- egy nemzetközi hírt.

Mindkét hírhez három, az esemény szempontjából releváns történelmi személyiség kapcsolódik. Ez naponta összesen hat történelmi kommentárt jelent.

## 2. Kötelező szerkesztési alapelv

A hírválasztást kizárólag az alábbi szakmai szempontok határozzák meg:
- az esemény jelentősége és közérdekűsége;
- hírérték;
- aktualitás;
- a tények ellenőrizhetősége;
- több, egymástól független forrásból történő megerősíthetőség.

NINCS:
- politikai kiegyensúlyozási kvóta;
- bal–jobb vagy kormány–ellenzék arány;
- szerkesztőségi irányultság szerinti súlyozás;
- kötelező politikai nézőpont-egyensúly.

A források sokfélesége kizárólag a tényellenőrzést és a torzítások felismerését szolgálja. Egy esemény jelentősége nem attól függ, hogy mely politikai szereplőnek kedvez vagy árt.

## 3. Napi tartalmi kimenet

Minden napi kiadásban:
- pontosan 1 magyar hír;
- pontosan 1 nemzetközi hír;
- hírenként 3 releváns történelmi személyiség;
- személyenként 3 összefüggő kommentárrész.

A kommentár három tartalmi dimenziója:
1. Értelmezés: hogyan értelmezné az adott személyiség a mai eseményt a dokumentált gondolkodása alapján?
2. Következmények: milyen következményekre, veszélyekre, történelmi mintázatokra figyelmeztetne?
3. Megoldás: milyen elveket, intézkedéseket vagy megoldási irányokat javasolhatna?

A három dimenzió folyó szövegként jelenjen meg, ne kérdés-felelet listaként.

## 4. Történelmi hitelesség

- A személyiségek kiválasztása az adott eseményhez való tényleges gondolati, szakmai vagy történelmi relevancián alapul.
- A kommentár dokumentált művekre, beszédekre, levelekre, döntésekre és hiteles történeti feldolgozásokra támaszkodjon.
- Nem tulajdonítható nekik kitalált, szó szerinti idézet.
- A mai eseményre adott gondolatkísérletet egyértelműen rekonstruált, hipotetikus értelmezésként kell jelölni.
- A történelmi személyiség nézeteit nem szabad leegyszerűsíteni vagy mai politikai kategóriákba kényszeríteni.
- A kommentár forrásai és az esemény tényszerű forrásai külön legyenek kezelve.

## 5. Javasolt technikai felépítés

Az AGORA külön modul legyen a meglévő SYNAPSE/WORLD SHARDS rendszerben; a jelenlegi gyűjtőket, publikációs folyamatot és napi kiadást nem írjuk át szükségtelenül.

Adatfolyam:
1. RSS-források lekérése.
2. Hírek egységesítése közös rekordformára.
3. Duplikátumok és ugyanazon eseményhez tartozó cikkek csoportosítása.
4. Frissesség, jelentőség, forrásmegerősítés és ellenőrizhetőség szerinti rangsorolás.
5. Magyar és nemzetközi jelöltlista kialakítása.
6. Naponta egy-egy hír kiválasztása.
7. Történelmi személyiségek kiválasztása és forrásprofilok hozzárendelése.
8. Hat kommentár előállítása és forrásellenőrzése.
9. AGORA tartalom átadása a meglévő kiadványépítőnek.

Az első verzió ingyenes forrásokra és a meglévő GitHub Actions + Supabase Free infrastruktúrára épüljön. Fizetős AI/API-szolgáltatás nem lehet kötelező függőség.

## 6. Hírgyűjtési és rangsorolási szabályok

- RSS legyen az elsődleges gyűjtési módszer, ahol megbízható feed áll rendelkezésre.
- A cikk eredeti forrásoldalára mutató URL-t kell tárolni; feed- vagy API-végpont nem helyettesítheti a cikk forráslinkjét.
- A hír megjelenési idejét és a gyűjtés idejét külön kell tárolni.
- Az azonos eseményről szóló cikkeket csoportosítani kell, nem külön hírekként kezelni.
- A forrásmegerősítésnél az egymástól független szerkesztőségeket kell számolni, nem a cikkek puszta darabszámát.
- A rangsorolás súlyai legyenek átláthatók és tesztelhetők.
- A politikai irányultság nem lehet rangsorolási mező vagy pontozási tényező.
- Bizonytalan, ellentmondásos vagy még fejlődő eseménynél a bizonytalanságot meg kell őrizni; nem szabad tényt állítani feltételezésből.
- A gyűjtő kezdetben csak jelölteket ment; nem küld ki automatikusan kiadást.

## 7. Mérföldkövek

### M0 – Alapelvek és specifikáció
- [x] Napi 2 hír: 1 magyar, 1 nemzetközi.
- [x] Hírenként 3 történelmi személyiség.
- [x] Személyenként háromrészes, összefüggő kommentár.
- [x] Hírérték-alapú kiválasztás politikai kvóta nélkül.
- [x] Forrásalapú történelmi rekonstrukció, kitalált idézetek nélkül.

### M1 – Hírforrások és RSS-gyűjtő
- Ingyenes, stabil magyar és nemzetközi RSS-források kiválasztása.
- RSS parser és egységes belső adatmodell.
- Dátum-, URL-, cím- és forrásnormalizálás.
- Hibás feedek és duplikátumok kezelése.
- Tesztek hálózati hívás nélkül, mintafeedekkel.

### M2 – Eseménycsoportosítás és rangsorolás
- [ ] M2.1: determinisztikus, külső függőség nélküli első eseménycsoportosító (CI-ellenőrzés folyamatban).
- [x] Magyar és nemzetközi hírek külön csoportban maradnak.
- [x] Azonos URL több forrásból megőrzi a forrásonkénti rekordokat.
- [x] Fuzzy cím-egyezés csak azonos nyelven, 72 órás időablakban.
- [x] Hiányzó dátumnál csak azonos URL alapján történik csoportosítás.
- [ ] M2.2: éles jelöltlistán történő kézi minőségellenőrzés és küszöbhangolás.
- Ugyanazon esemény cikkeinek csoportosítása.
- Független források számítása.
- Frissesség, jelentőség, közérdekűség, ellenőrizhetőség pontozása.
- Külön magyar és nemzetközi shortlist.
- Napi 1+1 kiválasztás és naplózás.

#### M2.2–M2.4 – Feldolgozó pipeline (implementálva, kézi hangolás még hátravan)

- [x] RSS-gyűjtés és M2.1 eseménycsoportosítás összekötése.
- [x] Determinisztikus, 0–100 pontos bizonyíték/frissesség pontozás.
- [x] Külön magyar és nemzetközi shortlist.
- [x] Napi 1+1 szerkesztőségi javaslat, ha van megfelelő friss jelölt.
- [x] JSON-kimenet, forrás- és feldolgozási metaadatok.
- [x] Offline tesztek és GitHub Actions ellenőrzés.
- [x] Nincs automatikus publikálás, adatbázis-írás vagy fizetős API-függőség.

A pontozás összetevői: frissesség (40), független források (30), lefedettség/cikkszám (15), metaadat-teljesség (15). A pontszám nem állítja, hogy automatikusan megméri az esemény valódi közérdekű jelentőségét; ezt továbbra is szerkesztői döntésként kell értékelni. Politikai irányultság nem bemenet. Minden javaslat kötelező emberi szerkesztői ellenőrzést igényel.

Futtatás:
- Éles RSS-gyűjtéssel: `python agora_pipeline.py`
- Korábbi gyűjtés feldolgozása: `python agora_pipeline.py --input collector_output.json --output agora_candidates.json`

A kézi minőségellenőrzés, a pontozási küszöbök valós feedeken történő hangolása és a 14 napos próbaüzem továbbra is külön feladat.

### M3 – Történelmi személyiségek adatbázisa

Állapot: első strukturált katalógus és determinisztikus illesztő elkészült.

- [x] 18 induló történelmi személyiség strukturált profilja.
- [x] Korszak, szakterület, relevanciatémák, keresőkifejezések és dokumentált alapelvek.
- [x] Művek, archívumok és forráslinkek profilhoz kötése.
- [x] Történeti korlátok és anakronizmus-veszélyek rögzítése.
- [x] Cím + elérhető cikkösszefoglaló alapján magyarázható kulcsszavas illesztés.
- [x] Legfeljebb 3 személy kiválasztása; nincs kötelező feltöltés gyenge egyezés esetén.
- [ ] Katalógus bővítése és forráslinkek egyenkénti szerkesztői ellenőrzése.
- [ ] Ismétlődés-rotáció tartós naplózása.

A kiválasztás témakapcsolatot jelez, nem politikai egyetértést vagy támogatást. A kulcsszavas pontszám előzetes relevanciajelzés, minden személyi hozzárendelés emberi ellenőrzést igényel.

### M4 – Kommentármotor

Állapot: strukturált kommentár-előkészítő elkészült; kész szöveg automatikus generálása még nincs bekapcsolva.

- [x] Személyenként három rész: értelmezés, következmények, megoldási irány.
- [x] Minden részhez kutatási kérdések és profilhoz kötött történelmi forráslinkek.
- [x] Dokumentált alapelvek és személyhez kötött történeti korlátok átadása.
- [x] Hipotetikus rekonstrukció kötelező jelölése.
- [x] Szó szerinti idézet csak pontos forrás és hely megadásával használható.
- [x] Mai tényállításokhoz aktuális hírforrás, történelmi állításokhoz történeti forrás szükséges.
- [x] Nincs kitalált idézet, automatikus publikálás vagy fizetős AI/API-függőség.
- [ ] Szerkesztői kutatás és a kommentárszövegek megírása/generálása.
- [ ] Történeti források és minden állítás tételes ellenőrzése.

Futtatás:
`python agora_pipeline.py --output agora_candidates.json`
`python agora_daily_editorial.py --input agora_candidates.json --output agora_editorial.json`

A két parancs a napi hírjavaslatokat, a személyi hozzárendeléseket és a kommentár-vázakat előkészíti. A kommentár-részek üres kutatási vázak, nem publikálható szövegek.


### Kézi, valós RSS-próba

A `.github/workflows/agora-daily-preview.yml` workflow kézzel indítható a GitHub Actions felületéről. Lekéri az aktuális RSS-jelölteket, elkészíti a rangsort, hozzárendeli a történelmi személyiségeket, majd 7 napig elérhető ZIP-artifactként elmenti az előnézeti JSON-fájlokat. Nem publikál és nem ír adatbázisba.

### M5 – Szerkesztési minőségbiztosítás
- Tényellenőrzési kapuk.
- Források és bizonytalanságok ellenőrzése.
- Tartalmi ismétlődés és személyiség-rotáció.
- Tesztkiadások, publikálás nélkül.

### M6 – WORLD SHARDS integráció
- AGORA adatmodell átadása a kiadványépítőnek.
- Webes megjelenés.
- E-mailes megjelenés.
- Hivatkozások, tipográfia és mobilnézet ellenőrzése.

### M7 – Próbaüzem
- Legalább 14 napos belső próba.
- Napi két hír és hat kommentár teljességének ellenőrzése.
- Forrásminőség, relevancia, változatosság és stabilitás mérése.
- Csak sikeres próba után automatikus napi publikálás.

## 8. Első fejlesztési feladat

Az M1 első lépése a magyar és nemzetközi RSS-források jegyzékének összeállítása. Minden feednél ellenőrizni kell:
- elérhetőség;
- frissítési gyakoriság;
- eredeti cikk URL-jének megléte;
- publikálási idő megléte;
- stabil RSS/XML szerkezet;
- felhasználási feltételek és attribúció.

Ezután készül az önálló, tesztelhető RSS-gyűjtő modul. A meglévő kiadási és publikálási workflow csak a későbbi integrációs mérföldkőben módosul.
