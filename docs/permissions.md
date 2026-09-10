# Behörighetsmodell – arbetsutkast

## Grundidé

SAMIDA kan på sikt ha bred teknisk förmåga, men språkmodellen ska aldrig själv
inneha operativsystemets eller externa kontons rättigheter. Modellen föreslår
ett verktygsanrop. Den lokala agentmotorn validerar mål, argument, policy och
eventuellt användargodkännande innan verktyget körs.

## Föreslagna körlägen

### Observera

Endast läsning. SAMIDA får läsa godkända projekt, loggar och webbsidor men inte
ändra något.

### Arbeta

SAMIDA får göra normala, reversibla ändringar inom godkända projekt och köra
förhandsgodkända kommandon. Känsliga handlingar kräver fortfarande bekräftelse.

### Förhöjt

Tillfällig, tidsbegränsad åtkomst för installation, systemändringar eller arbete
utanför normala kataloger. Läget aktiveras uttryckligen och stängs automatiskt.

## Risknivåer

- Låg: läsa filer, söka, visa Git-status, öppna en webbsida.
- Medel: skapa eller ändra filer i ett godkänt projekt, köra tester och byggen.
- Hög: radera, flytta många filer, installera program, ändra systeminställningar,
  skicka e-post eller publicera information.
- Förbjuden utan särskilt beslut: lösenordsåtkomst, kringgå säkerhet, permanenta
  ekonomiska handlingar eller självständig utökning av behörigheter.

## Skydd

- Tillåtna kataloger anges med absoluta sökvägar.
- PowerShell-kommandon analyseras och loggas före körning.
- Rekursiv radering och systemändringar kräver alltid bekräftelse.
- Externa meddelanden visas som utkast före sändning som standard.
- Webbläsarsessioner och konton isoleras där det är möjligt.
- Alla verktygsanrop får tid, verktygsnamn, mål, resultat och risknivå i loggen.
- Hemligheter exponeras aldrig för modellen när ett verktyg kan använda dem
  internt.

