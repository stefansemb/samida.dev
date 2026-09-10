# Beslut 0008: Lokalt chattarkiv och skärmdumpar

- Status: accepterat
- Datum: 2026-09-08

## Beslut

Chattar och meddelanden sparas lokalt i SQLite. Skärmdumpar sparas som lokala
bildfiler med metadata i databasen. De kan klistras in direkt i chattfältet och
skickas till en bildkapabel modell.

## Regler

- En chatt kan skapas, öppnas, döpas om och raderas.
- Radering kräver en synlig bekräftelse och tar även bort chattens bildfiler.
- Tillåtna bildformat är PNG, JPEG och WebP, högst 10 MB.
- Bildens faktiska filsignatur valideras innan den sparas.
- Chattdata är lokal och används inte som långtidsminne automatiskt.

## Verifierad modellkapacitet

Ollama rapporterar att `gemma4:e4b` har `vision`-kapacitet. Ett verkligt test
verifierade hela uppladdnings- och svarskedjan. Modellens egen läsning av en
liten Windows-dialogruta var inte tillförlitlig. Därför kör SAMIDA även lokal
RapidOCR och skickar den extraherade texten som stöd till modellen. OCR-texten
sparas med meddelandet och kan granskas i webbchatten.
