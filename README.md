# SAMIDA

### CamoFox för lokal research

SAMIDA kan använda en lokalt körd CamoFox-server för GitHub Trending. För normal användning startas båda tillsammans:

```powershell
.\tools\start-samida.ps1 -CamofoxRoot 'C:\sökväg\till\camofox-browser'
```

Launcher-skriptet väntar på att CamoFox är frisk, startar därefter SAMIDA och stänger CamoFox när SAMIDA avslutas. RSS-källor hämtas fortfarande via vanlig HTTP. Vid felsökning kan SAMIDA köras utan CamoFox genom att sätta `SAMIDA_CAMOFOX_ENABLED=false`.

Inga cookies, konton eller inloggningar används.
SAMIDA är en personlig agent och assistent som körs genom en lokal webbapp.
Projektet byggs som en hybridlösning: minne, inställningar och behörigheter ägs
lokalt, medan språkmodellen kan vara lokal eller nås via en extern API-provider.

## Mål

- En privat och begriplig minnesstruktur i Markdown.
- En lokal chatt som fungerar som huvudsakligt gränssnitt.
- Utbytbara modellproviders utan att SAMIDAs identitet behöver skrivas om.
- Skills, plugins och verktyg som kan installeras separat.
- Tydlig åtkomstkontroll för filer, program, nätverk och externa konton.
- Spårbara beslut och möjlighet att granska vad agenten har gjort.

## Projektstatus

Projektgrund skapad. Teknikstack, modeller, minnessökning och första
appintegration ska beslutas tillsammans innan implementationen börjar.

## Kataloger

- `memory/` – långsiktig information som användaren kan läsa och ändra.
- `instructions/` – identitet, arbetsregler, kommunikationsstil och säkerhet.
- `skills/` – återanvändbara instruktioner och arbetsflöden.
- `plugins/` – installerbara integrationer och tillägg.
- `tools/` – funktioner som agenten kan anropa.
- `config/` – konfiguration utan hemligheter.
- `server/` – framtida lokal backend och agentmotor.
- `web/` – framtida webbgränssnitt.
- `data/` – framtida lokala index och strukturerad applikationsdata.
- `conversations/` – valfri lokal konversationshistorik.
- `docs/` – arkitektur, krav och dokumenterade beslut.

Hemligheter som API-nycklar ska aldrig skrivas i Markdown eller checkas in i Git.
