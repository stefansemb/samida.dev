# Beslut 0006: Transparent kontextmotor

- Status: accepterat som första implementation
- Datum: 2026-09-08

## Beslut

SAMIDAs kärninstruktioner laddas alltid. Minnesfiler väljs deterministiskt efter
innehållet i användarens meddelanden. API:t redovisar vilka filer som användes
och erbjuder en separat förhandsgranskning av hela systemkontexten.

## Konsekvenser

- Urvalet är lätt att förstå, testa och granska.
- Personminne skickas inte med när det saknar relevans.
- Den första versionen kräver ingen vektordatabas eller embeddingmodell.
- Mer avancerad lokal sökning kan införas senare utan att ändra minnesfilerna.

