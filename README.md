# SAMIDA

SAMIDA är en personlig, lokal-först AI-assistent: minne, inställningar och
behörigheter ägs lokalt, medan språkmodellen kan vara lokal (Ollama) eller nås
via en extern provider (Anthropic/OpenAI). Chatt med bildgenerering, lokal
filåtkomst, webbsökning, väder och läsbehörighet till Google Kalender/Gmail
(read-only).

## Kom igång

Tre sätt att köra SAMIDA:

- **SAMIDA Desktop** – en riktig Windows-app, inget konto eller delad server.
  Se [desktop/README.md](desktop/README.md) för hur man bygger en
  installer (`npm run dist` i `desktop/`) som varken kräver Python eller
  Node på måldatorn.
- **Lokal utveckling** – kör backend och webbapp separat, se
  [server/README.md](server/README.md) och `web/`.
- **Den hostade webbappen** – `app.samida.dev`.

### CamoFox för lokal research

SAMIDA kan använda en lokalt körd CamoFox-server för GitHub Trending. För normal användning startas båda tillsammans:

```powershell
.\tools\start-samida.ps1 -CamofoxRoot 'C:\sökväg\till\camofox-browser'
```

Launcher-skriptet väntar på att CamoFox är frisk, startar därefter SAMIDA och stänger CamoFox när SAMIDA avslutas. RSS-källor hämtas fortfarande via vanlig HTTP. Vid felsökning kan SAMIDA köras utan CamoFox genom att sätta `SAMIDA_CAMOFOX_ENABLED=false`.

## Mål

- En privat och begriplig minnesstruktur i Markdown.
- En lokal chatt som fungerar som huvudsakligt gränssnitt.
- Utbytbara modellproviders utan att SAMIDAs identitet behöver skrivas om.
- Skills, plugins och verktyg som kan installeras separat.
- Tydlig åtkomstkontroll för filer, program, nätverk och externa konton.
- Spårbara beslut och möjlighet att granska vad agenten har gjort.

## Kataloger

- `memory/` – långsiktig information som användaren kan läsa och ändra. Ägarens personliga data - checkas aldrig in i en distribuerad installer (se `desktop/README.md`).
- `instructions/` – identitet, arbetsregler, kommunikationsstil och säkerhet.
- `server/` – lokal backend (FastAPI) och agentmotor. Se `server/README.md`.
- `web/` – webbgränssnittet (Next.js/vinext).
- `desktop/` – SAMIDA Desktop, Electron-appen och dess installer-pipeline.
- `tools/` – deploy-konfiguration (Caddy/systemd) och launcher-skript.
- `data/`, `conversations/` – lokala index, SQLite-databas och konversationshistorik (gitignorade).
- `docs/` – arkitektur, krav och dokumenterade beslut.

Hemligheter som API-nycklar ska aldrig skrivas i Markdown eller checkas in i Git - se `.env.example`.
