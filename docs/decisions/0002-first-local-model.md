# Beslut 0002: Första lokala modell

- Status: accepterat
- Datum: 2026-09-08

## Beslut

Ollama används som SAMIDAs första lokala modellprovider. Det exakta
modellnamnet är `gemma4:e4b`.

## Verifiering

Modellen finns installerad lokalt i Ollama och har testats av användaren.
Installationen verifierades även med `ollama list` när beslutet dokumenterades.

## Konsekvenser

- Den första provideradaptern ska anropa Ollamas lokala API.
- Modellnamnet ska ligga i konfiguration och inte hårdkodas i agentmotorn.
- SAMIDA ska senare kunna byta modell per samtal eller uppgift.
- Externa modellproviders ska använda samma interna providergränssnitt.

