# Beslut 0001: Hybridarkitektur

- Status: accepterat
- Datum: 2026-09-08

## Beslut

SAMIDA byggs som en hybridlösning. Lokala och externa modeller ska exponeras
genom samma interna providergränssnitt. SAMIDAs identitet, minne, behörigheter
och användargränssnitt ska inte vara bundna till en enskild modellleverantör.

## Konsekvenser

- Integritetskänsliga uppgifter kan styras till en lokal modell.
- Kraftfullare molnmodeller kan användas när användaren tillåter det.
- Providerbyte blir enklare men kräver en tydlig gemensam abstraktion.
- Gränssnittet måste visa vilken provider som används och vad som lämnar datorn.

