# Server

SAMIDAs lokala backend använder Python och FastAPI.

## Utvecklingsstart

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m uvicorn samida.main:app --app-dir server --reload
```

API:t finns därefter på `http://127.0.0.1:8000`. Hälsokontrollen finns på
`/api/health` och FastAPIs lokala API-dokumentation på `/docs`.

## Nuvarande omfattning

- Providergränssnitt för framtida lokala och externa modeller.
- Ollama-provider med `gemma4:e4b` som standard.
- Hälsokontroll av Ollama och den valda modellen.
- Kontextmotor som alltid laddar kärnregler och väljer relevant lokalt minne.
- `/api/context/preview` visar exakt vilka filer och instruktioner som används.
- Chatt-endpoint med kontext, men ännu utan verktygsåtkomst.
- Lokalt SQLite-arkiv för att skapa, döpa, öppna och radera chattar.
- Lokalt sparade PNG-, JPEG- och WebP-skärmdumpar, högst 10 MB per bild.
- Bildinnehåll skickas till den lokala Ollama-modellen tillsammans med texten.
- RapidOCR läser text lokalt ur skärmdumpar innan modellanalysen.
