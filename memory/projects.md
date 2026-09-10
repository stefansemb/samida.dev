# Projekt

> Status: låst grundstruktur 2026-09-08. Projektposter får uppdateras när Stefan
> uttryckligen ändrar status eller lämnar ny information.

## Registerprinciper

- SAMIDA ska känna till Stefans samtliga aktiva projekt.
- Varje projekt ska ha namn, status, syfte, sökväg eller adress, teknik och
  relevanta anteckningar.
- Projektkännedom ger inte automatiskt skrivbehörighet till projektets filer
  eller tjänster; åtkomst styrs separat.
- Inaktiva och avslutade projekt arkiveras och blandas inte in i den normala
  arbetskontexten.

## SAMIDA

- Status: aktivt.
- Sökväg: `C:\AiProjects\SAMIDA`.
- Personlig lokal agentplattform med webbchatt, Markdown-baserat minne,
  utbytbara modellproviders, skills, plugins och kontrollerad programåtkomst.
- SAMIDA är tekniskt fristående från Jarvis och Jarvis Web.
- CamoFox Browser testades isolerat 2026-09-09 och fungerar för att öppna en
  offentlig sida och läsa dess accessibility-snapshot. Den får användas för
  anonym research på offentliga webbsidor med telemetri och sessionspersistens
  avstängda. Använd inte cookie-import, privata konton eller inloggade sessioner.
  Starta servern tillfälligt när research behövs och stäng den efteråt.
- ECC (affaan-m/ECC) ska testas separat som möjligt kodningsagent-ramverk.
  Ingen global installation eller ändring av SAMIDAs befintliga instruktioner
  och skills innan utvärdering. Börja med arbetsflöde, kodgranskning,
  verifiering och AgentShield.
- HyperFrames (heygen-com/hyperframes) är noterat för ett framtida separat
  test. Projektet omvandlar HTML, CSS och media till deterministiska MP4-videor
  och erbjuder agentinriktade skills. Ingen installation eller testkörning nu.

## Pirate Survival

- Status: aktivt och huvudsakligt långsiktigt spelprojekt.
- Sökväg: `C:\Games\PirateSurvival\PirateSurvival`.
- Teknik: Unreal Engine, C++ och Blueprints.
- Survivalspel med en växande World Partition uppbyggd av öar.
- Nwiro används med MCP-anslutning så att Claude kan göra ändringar direkt i
  Unreal.
- Mål: få ett fullt fungerande spel färdigt och därefter eventuellt publicera
  det på Steam.

## Jarvis Web

- Status: aktivt.
- Ett lokalt webbgränssnitt med mörkt marinblå/cyan, modulbaserad dashboard i
  Jarvis OS-identitet.
- Avsett att bli gränssnittet för Jarvis-daemonen, inte en separat AI-backend.
- Fjärråtkomst via Cloudflare Tunnel är ett medvetet senare steg.
- Jarvis och Jarvis Web är separata från SAMIDA. SAMIDA ska inte ersätta dem och
  ska inte automatiskt dela kod, backend, identitet eller konfiguration med dem.
- Projekten ska ändå vara kända av SAMIDA så att den kan hjälpa till med dem när
  Stefan ber om det och separat åtkomst har beviljats.
