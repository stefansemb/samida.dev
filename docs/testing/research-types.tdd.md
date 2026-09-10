# Researchtyper – TDD-evidens

## Källa och användarresor

Kraven kom från den godkända SAMIDA-planen. En användare kan köra och läsa AI-research och mobilappsresearch var för sig. Befintliga rapporter förblir AI-research. Schemalagda skript väljer typ explicit.

## RED och GREEN

| Garanti | Test | Typ | Resultat |
|---|---|---|---|
| Rapporter lagras och filtreras per researchtyp | `server/tests/test_storage.py::test_research_reports_are_stored_and_filtered_by_type` | integration | PASS |
| Äldre rapporter migreras till `ai_general` | `server/tests/test_storage.py::test_existing_research_reports_are_migrated_to_ai_general` | migration | PASS |
| Mobilresearch använder en mobilanpassad prompt | `server/tests/test_research.py::test_mobile_research_uses_mobile_specific_sources_and_prompt` | unit | PASS |
| API:t injicerar CamoFox och håller typernas listor separata | `server/tests/test_research.py::test_research_api_injects_camofox_and_separates_report_types` | API-integration | PASS |
| Okänd researchtyp avvisas | `server/tests/test_research.py::test_research_api_rejects_unknown_type` | API-integration | PASS |

RED: `python -m pytest server/tests/test_storage.py server/tests/test_research.py -q` gav 5 avsedda fel innan implementationen, inklusive den tidigare `NameError`-buggen för `camofox`.

GREEN: `python -m pytest -q` gav `12 passed`.

Reviewcykelns RED var en compile-time RED eftersom `parse_feed` ännu saknades. Efter implementation verifierar de nya testerna Atom-parsning, avgränsning av opålitlig källdata och idempotenta API-omförsök. Slutlig GREEN: `15 passed`.

## Övrig verifiering

- `npx oxlint app/page.tsx`: PASS.
- `npm run build`: PASS efter reviewändringarna.
- PowerShell-parser på båda researchskripten: PASS.
- Projektets fulla `npm run lint` har befintliga fel i genererade `components/ui/*`, `hooks/use-mobile.ts` och `components/ui/chart.tsx`. Den ändrade sidan är ren när den lintas separat.
- Coverage-plugin finns inte i projektets utvecklingsberoenden, så något procentvärde kunde inte mätas utan installation.
- Ingen Windows-task registrerades i denna ändring.
