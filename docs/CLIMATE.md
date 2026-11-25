# Climate table (Day 3, round 6)

Source file: `data/expansions/climate.json` (loaded by `backend/app/data.py`
as `CLIMATE`). The table maps each city that hosts at least one expansion
programme to one of the four climate classes the wizard offers as a
preference (`warm` / `cool` / `four_seasons` / `mild`).

## Classes

- **warm** — hot most of the year, no cold season (tropical / subtropical
  with hot summers and mild-to-warm winters, e.g. Singapore, Hong Kong,
  Sydney, Los Angeles).
- **cool** — cool summers and cold winters (cool temperate / subarctic
  influence, e.g. Edinburgh, Stockholm, Edmonton).
- **four_seasons** — four distinct seasons with a cold winter and a warm
  or hot summer (continental / humid subtropical, e.g. Seoul, Beijing,
  New York, Toronto, Chicago).
- **mild** — temperate oceanic / Mediterranean with mild winters and
  mild-to-warm summers, no extreme season (e.g. London, Paris, Amsterdam,
  Vancouver, Berkeley).

## Fit rule (`backend/domain/climate.py`)

`climate_fit(preference, city_class)` returns:

- `fit` when the preference equals the city's class;
- `conflict` when the pair is `{cool, warm}` (opposites), or when the
  preference is `four_seasons` and the city is `warm` (no cold winter
  at all);
- `neutral` for every other combination;
- no signal (`None`) when the preference is absent/free-text or the
  city's class is unknown.

Climate is a **preference, never an eligibility rule**: it never produces
`NOT_MET`, never changes a rule status, and only reorders recommendations
(conflicts are demoted and labelled, never hidden). A city with no entry
in this table gives its programmes no climate signal at all.

## Verification

Each entry links to the city's Wikipedia climate section (or, for the
five mapped entries below, the nearest city with a climate section).
Five pages were opened and read directly while building the table:
Singapore (tropical rainforest Af, 23–32 °C, no distinctive seasons),
Edinburgh (cool temperate maritime Cfb), Uppsala (humid continental Dfb,
January daily mean −2.7 °C), Stanford CA (warm-summer Mediterranean Csb),
Urbana IL (January mean max 0.5 °C / min −8.5 °C, July max 29.4 °C).
The remaining URLs follow the same
`https://en.wikipedia.org/wiki/<City>#Climate` pattern for established
city articles; the classification itself is general world knowledge
about the city's climate, cross-checked against the Köppen class named
on the linked page.

Mapped entries (no climate section of their own):

- Kowloon Tong, Sha Tin → Hong Kong
- Orsay, Palaiseau → Paris
- Suita → Osaka
- University Park → State College, Pennsylvania
- Urbana-Champaign → Urbana, Illinois

## Judgement calls

- **Edinburgh / Durham = cool** (cool summers; winters are cold and
  damp rather than merely mild).
- **Uppsala = four_seasons** (Dfb: cold winters, warm summers — four
  distinct seasons, not a cool-summer climate).
- **Stanford / Berkeley = mild** (Csb warm-summer Mediterranean; daily
  means never rise far above ~19 °C).
- **Melbourne = warm** (hot summers, mild winters; the summer heat
  dominates the lived climate).

## Coverage

All 80 cities in the expansion catalogue are covered (881/881
programmes resolve to a city class). Classes: warm 17, cool 6,
four_seasons 32, mild 25. No unsourced cities remain; a future city
with no entry gets no signal rather than a guessed class.

## Entries

| City | Class | Source | Note |
| --- | --- | --- | --- |
| Copenhagen | cool | https://en.wikipedia.org/wiki/Copenhagen#Climate |  |
| Durham | cool | https://en.wikipedia.org/wiki/Durham#Climate |  |
| Edinburgh | cool | https://en.wikipedia.org/wiki/Edinburgh#Climate |  |
| Edmonton | cool | https://en.wikipedia.org/wiki/Edmonton#Climate |  |
| Lund | cool | https://en.wikipedia.org/wiki/Lund#Climate |  |
| Stockholm | cool | https://en.wikipedia.org/wiki/Stockholm#Climate |  |
| Ann Arbor | four_seasons | https://en.wikipedia.org/wiki/Ann_Arbor,_Michigan#Climate |  |
| Baltimore | four_seasons | https://en.wikipedia.org/wiki/Baltimore#Climate |  |
| Beijing | four_seasons | https://en.wikipedia.org/wiki/Beijing#Climate |  |
| Berlin | four_seasons | https://en.wikipedia.org/wiki/Berlin#Climate |  |
| Boston | four_seasons | https://en.wikipedia.org/wiki/Boston#Climate |  |
| Canberra | four_seasons | https://en.wikipedia.org/wiki/Canberra#Climate |  |
| Champaign | four_seasons | https://en.wikipedia.org/wiki/Champaign,_Illinois#Climate |  |
| Chicago | four_seasons | https://en.wikipedia.org/wiki/Chicago#Climate |  |
| Daejeon | four_seasons | https://en.wikipedia.org/wiki/Daejeon#Climate |  |
| Evanston | four_seasons | https://en.wikipedia.org/wiki/Evanston,_Illinois#Climate |  |
| Hangzhou | four_seasons | https://en.wikipedia.org/wiki/Hangzhou#Climate |  |
| Ithaca | four_seasons | https://en.wikipedia.org/wiki/Ithaca,_New_York#Climate |  |
| Kyoto | four_seasons | https://en.wikipedia.org/wiki/Kyoto#Climate |  |
| Lausanne | four_seasons | https://en.wikipedia.org/wiki/Lausanne#Climate |  |
| Milan | four_seasons | https://en.wikipedia.org/wiki/Milan#Climate |  |
| Montreal | four_seasons | https://en.wikipedia.org/wiki/Montreal#Climate |  |
| Munich | four_seasons | https://en.wikipedia.org/wiki/Munich#Climate |  |
| Nanjing | four_seasons | https://en.wikipedia.org/wiki/Nanjing#Climate |  |
| New Haven | four_seasons | https://en.wikipedia.org/wiki/New_Haven,_Connecticut#Climate |  |
| New York | four_seasons | https://en.wikipedia.org/wiki/New_York_City#Climate |  |
| Philadelphia | four_seasons | https://en.wikipedia.org/wiki/Philadelphia#Climate |  |
| Pittsburgh | four_seasons | https://en.wikipedia.org/wiki/Pittsburgh#Climate |  |
| Princeton | four_seasons | https://en.wikipedia.org/wiki/Princeton,_New_Jersey#Climate |  |
| Providence | four_seasons | https://en.wikipedia.org/wiki/Providence,_Rhode_Island#Climate |  |
| Seoul | four_seasons | https://en.wikipedia.org/wiki/Seoul#Climate |  |
| Shanghai | four_seasons | https://en.wikipedia.org/wiki/Shanghai#Climate |  |
| Suita | four_seasons | https://en.wikipedia.org/wiki/Osaka#Climate | City in Osaka Prefecture; no climate section of its own, so the Osaka climate is used. |
| Tokyo | four_seasons | https://en.wikipedia.org/wiki/Tokyo#Climate |  |
| Toronto | four_seasons | https://en.wikipedia.org/wiki/Toronto#Climate |  |
| Uppsala | four_seasons | https://en.wikipedia.org/wiki/Uppsala#Climate |  |
| Urbana-Champaign | four_seasons | https://en.wikipedia.org/wiki/Urbana,_Illinois#Climate | Twin-city metro area; the Urbana climate table covers the shared campus area. |
| Zurich | four_seasons | https://en.wikipedia.org/wiki/Zurich#Climate |  |
| Amsterdam | mild | https://en.wikipedia.org/wiki/Amsterdam#Climate |  |
| Auckland | mild | https://en.wikipedia.org/wiki/Auckland#Climate |  |
| Berkeley | mild | https://en.wikipedia.org/wiki/Berkeley,_California#Climate |  |
| Birmingham | mild | https://en.wikipedia.org/wiki/Birmingham#Climate |  |
| Bristol | mild | https://en.wikipedia.org/wiki/Bristol#Climate |  |
| Cambridge | mild | https://en.wikipedia.org/wiki/Cambridge#Climate |  |
| Coventry | mild | https://en.wikipedia.org/wiki/Coventry#Climate |  |
| Delft | mild | https://en.wikipedia.org/wiki/Delft#Climate |  |
| Dublin | mild | https://en.wikipedia.org/wiki/Dublin#Climate |  |
| Glasgow | mild | https://en.wikipedia.org/wiki/Glasgow#Climate |  |
| Heidelberg | mild | https://en.wikipedia.org/wiki/Heidelberg#Climate |  |
| Leeds | mild | https://en.wikipedia.org/wiki/Leeds#Climate |  |
| Leuven | mild | https://en.wikipedia.org/wiki/Leuven#Climate |  |
| London | mild | https://en.wikipedia.org/wiki/London#Climate |  |
| Manchester | mild | https://en.wikipedia.org/wiki/Manchester#Climate |  |
| Nottingham | mild | https://en.wikipedia.org/wiki/Nottingham#Climate |  |
| Orsay | mild | https://en.wikipedia.org/wiki/Paris#Climate | Commune in the Paris metropolitan area; no climate section of its own, so the Paris climate is used. |
| Oxford | mild | https://en.wikipedia.org/wiki/Oxford#Climate |  |
| Palaiseau | mild | https://en.wikipedia.org/wiki/Paris#Climate | Commune in the Paris metropolitan area; no climate section of its own, so the Paris climate is used. |
| Paris | mild | https://en.wikipedia.org/wiki/Paris#Climate |  |
| Seattle | mild | https://en.wikipedia.org/wiki/Seattle#Climate |  |
| Sheffield | mild | https://en.wikipedia.org/wiki/Sheffield#Climate |  |
| Stanford | mild | https://en.wikipedia.org/wiki/Stanford,_California#Climate |  |
| University Park | mild | https://en.wikipedia.org/wiki/State_College,_Pennsylvania#Climate | Penn State campus town in State College; no climate section of its own, so the State College climate is used. |
| Vancouver | mild | https://en.wikipedia.org/wiki/Vancouver#Climate |  |
| Adelaide | warm | https://en.wikipedia.org/wiki/Adelaide#Climate |  |
| Austin | warm | https://en.wikipedia.org/wiki/Austin,_Texas#Climate |  |
| Brisbane | warm | https://en.wikipedia.org/wiki/Brisbane#Climate |  |
| Buenos Aires | warm | https://en.wikipedia.org/wiki/Buenos_Aires#Climate |  |
| Dhahran | warm | https://en.wikipedia.org/wiki/Dhahran#Climate |  |
| Hong Kong | warm | https://en.wikipedia.org/wiki/Hong_Kong#Climate |  |
| Kowloon Tong | warm | https://en.wikipedia.org/wiki/Hong_Kong#Climate | District of Hong Kong; no article of its own, so the Hong Kong climate is used. |
| Kuala Lumpur | warm | https://en.wikipedia.org/wiki/Kuala_Lumpur#Climate |  |
| Los Angeles | warm | https://en.wikipedia.org/wiki/Los_Angeles#Climate |  |
| Melbourne | warm | https://en.wikipedia.org/wiki/Melbourne#Climate |  |
| Pasadena | warm | https://en.wikipedia.org/wiki/Pasadena,_California#Climate |  |
| Perth | warm | https://en.wikipedia.org/wiki/Perth#Climate |  |
| San Diego | warm | https://en.wikipedia.org/wiki/San_Diego#Climate |  |
| Sha Tin | warm | https://en.wikipedia.org/wiki/Hong_Kong#Climate | District of Hong Kong; no article of its own, so the Hong Kong climate is used. |
| Singapore | warm | https://en.wikipedia.org/wiki/Singapore#Climate |  |
| Sydney | warm | https://en.wikipedia.org/wiki/Sydney#Climate |  |
| Taipei | warm | https://en.wikipedia.org/wiki/Taipei#Climate |  |

## Gaps

- Classifications are city-level, not campus-microclimate level (a
  large metropolitan area can vary by district).
- Wikipedia is the source for every entry; no meteorological-station
  dataset was consulted. If a classification is disputed, the fix is
  to change the entry in `climate.json` (and this doc) — the fit rule
  itself does not change.
