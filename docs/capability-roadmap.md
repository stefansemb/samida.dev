# Kapabilitetsplan – arbetsutkast

Detta är en diskussionsgrund, inte en låst implementationsordning.

## Grundfunktioner

- Lokal webbchatt med streaming.
- Lokalt chattarkiv med skapa, döpa om, öppna och radera.
- Inklistring och lokal lagring av skärmdumpar.
- Ollama-provider med `gemma4:e4b`.
- Valbar extern modellprovider.
- Instruktions- och minnesladdning från Markdown.
- Granskning av vad som skickas till en extern modell.
- Verktygslogg och bekräftelsedialoger.

## Lokalt arbete

- Ett lokalt register över alla aktiva projekt, med status och relevant kontext.
- Läsa, skapa och ändra filer i godkända arbetsytor.
- Hitta och växla mellan Unreal-, webb- och andra projekt.
- Git-status, diff, commits och versionshistorik.
- PowerShell med policykontroll.
- Köra tester, byggen och utvecklingsservrar.
- Läsa felloggar och föreslå eller genomföra korrigeringar.

## Webbläsare

- Öppna och läsa webbsidor.
- Söka och samla källor.
- Fylla formulär efter godkännande.
- Nedladdning till godkända kataloger.
- Inloggade eller publicerande handlingar kräver stramare regler.

## Kommunikation och planering

- En särskild Gmail via OAuth, inte sparat lösenord.
- Läsa och sammanfatta valda etiketter eller mappar.
- Skapa e-postutkast.
- Sändning kräver bekräftelse som standard.
- Möjliga framtida tillägg: Google Calendar, uppgifter, kontakter och
  aviseringar.

## Bra framtida verktyg att diskutera

- GitHub för issues, pull requests och repositories.
- Kalender och påminnelser.
- Anteckningar och kunskapsbas.
- Säkerhetskopiering av SAMIDAs minne och konfiguration.
- Dokument-, bild- och PDF-analys.
- Lokal OCR för tillförlitlig läsning av text i tekniska skärmdumpar.
- Röstinmatning och uppläsning.
- Lokalt bildskapande eller extern bildmodell.
- Notiser när långvariga byggen eller uppgifter är klara.

## Föreslagen första integrationsordning

1. Ollama och lokal chatt.
2. Minnesläsning med tydlig kontextvisning.
3. Projektmappar och Git.
4. Begränsad PowerShell.
5. Webbläsarläsning och sökning.
6. Gmail-utkast via ett separat konto.
7. Först därefter bredare datorstyrning.
