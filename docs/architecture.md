# Arkitektur – arbetsutkast

## Beslutade principer

- SAMIDA ska vara en hybridlösning.
- Webbgränssnitt, konfiguration, minne och behörigheter ska vara lokala.
- Både lokala och externa modellproviders ska kunna användas.
- Modeller ska inte få direkt, obegränsad åtkomst till datorn.
- Ollama är första lokala modellprovider.
- `gemma4:e4b` är första lokala chattmodell.
- Backend byggs med Python 3.12 och FastAPI.
- Målet är bred lokal kapabilitet med kontrollerad behörighet, inte obegränsad
  direktåtkomst från modellen.

## Föreslagna komponenter

1. Lokal webbklient för chatt, inställningar och minnesgranskning.
2. Lokal server med agentloop och providergränssnitt.
3. Kontextbyggare som väljer instruktioner och relevant minne.
4. Verktygsregister med scheman, risknivåer och behörighetskontroll.
5. Modellrouter som väljer lokal eller extern modell per uppgift.
6. Lokal lagring för konversationer, verktygslogg och sökindex.

## Öppna beslut

- Frontendramverk.
- Vilken molnprovider som ska stödjas först.
- Enkel textsökning eller lokal semantisk sökning för minnet.
- Exakt modellrouter: manuellt val, regler eller automatisk klassificering.
- Första app/program som SAMIDA ska få kontrollerad åtkomst till.
- Exakt godkännandemodell för PowerShell, webbläsare och externa konton.

Se även `permissions.md` och `capability-roadmap.md`.
