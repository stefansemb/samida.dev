# Skills

En skill är en fristående `.md`-fil i den här mappen som beskriver ett
arbetsflöde SAMIDA ska följa steg för steg, istället för att improvisera fritt.
Formatet är validerat mot en lokal gratismodell (kvantiserad 27B via Ollama) i
ett separat prototyp-labb (`samidax`) innan det portades hit.

## Format

```markdown
# Objective
En mening om vad skillen ska åstadkomma.

# Steps
1. Konkreta, ordnade steg.
2. ...

# Rules
- Hårda krav skillen alltid måste följa (t.ex. "verifiera innan du påstår att
  det fungerar", "svara på svenska", gränser för längd/omfång).
```

Filnamnet (utan `.md`) är skillens namn, t.ex. `skills/research-report.md` blir
`research-report`.

## Hur det laddas

`GET /api/skills` listar tillgängliga skillnamn. Ett chattanrop till
`/api/conversations/{id}/chat` kan skicka med `"skill": "research-report"` för
att aktivera den för den vändan; innehållet läggs till i systemprompten och
modellen får fler verktygsanrop i följd (`SKILL_MAX_TOOL_ITERATIONS` i
`server/samida/agent.py`) eftersom ett riktigt arbetsflöde ofta tar fler steg
än vanlig chatt. Se `server/samida/skills.py` och `server/samida/context.py`.

## Behörigheter

En skill kan bara använda verktyg som redan är tillgängliga i den aktuella
konversationen (workspace-verktyg kräver att en arbetskatalog är vald, precis
som idag). En skill deklarerar inga nya behörigheter själv - write_file och
update_memory kräver fortfarande ägarens godkännande som vanligt.
