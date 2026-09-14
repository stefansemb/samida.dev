# Minnespolicy

## Minnestyper

- Profilminne: stabil information om användaren.
- Preferensminne: hur SAMIDA bör kommunicera och arbeta.
- Projektminne: mål, status och viktiga beslut.
- Lärdomar: verifierade slutsatser som är användbara igen.
- Samtalshistorik: separat från långtidsminnet och valfri att spara.

## Regler

- Minnet är lokalt och ska vara möjligt för användaren att läsa och redigera.
- Endast relevant minne skickas till vald modellprovider.
- Känslig information markeras och skickas aldrig externt utan stöd i policyn.
- Nya bestående minnen ska kunna granskas, ändras och raderas.
- Motstridiga uppgifter ska inte tyst ersätta varandra.

## Verktyget update_memory

Använd `update_memory` när ett samtal avslöjar något varaktigt värt att spara i
profil-, preferens-, projekt- eller lärdomsminnet - t.ex. ett nytt beslut, en
bekräftad preferens, eller en lärdom som visade sig stämma. Spara inte
tillfälliga eller redan kända fakta.

`update_memory` har alltid medelrisk och pausar för användarens godkännande
innan något skrivs - anta aldrig samtycke, och föreslå aldrig att skriva över
befintligt innehåll. Verktyget lägger alltid till en ny, daterad sektion.

