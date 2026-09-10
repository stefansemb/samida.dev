# Beslut 0005: Python och FastAPI för backend

- Status: accepterat
- Datum: 2026-09-08

## Beslut

SAMIDAs lokala agentmotor och API byggs i Python 3.12 med FastAPI. Webbklienten
hålls separat och kommunicerar med backend via ett lokalt API.

## Konsekvenser

- Ollama, filverktyg, PowerShell och framtida AI-integrationer kan implementeras
  som tydliga Python-moduler.
- Modellproviders delar ett internt gränssnitt.
- Backend kan testas oberoende av webbgränssnittet.
- Valet av frontendramverk förblir öppet.

