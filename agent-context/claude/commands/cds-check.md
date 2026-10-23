---
description: Verifica la conformità ai requisiti di gara sull'uso dei servizi AWS CDS
---

Controlla il repository rispetto ai requisiti del hackathon sull'uso di AWS CDS e riporta un esito chiaro.

1. Cerca nel codice runtime (non nei documenti) le chiamate effettive ai client ammessi:
   - `socialmessaging` → `send_whatsapp_message` / `SendWhatsAppMessage`
   - `sesv2` → `send_email` / `SendEmail`
   - `pinpoint-sms-voice-v2` → `send_rcs_message` / `send_text_message`
   Per ognuna indica file e riga e se è raggiungibile da un flusso reale (non solo test).
2. Cerca usi **vietati**: client `pinpoint` (v1), `pinpoint-email`, EUM Push. Segnala qualsiasi occorrenza.
3. Verifica che **solo il Notifier** (`services/notifier/`) chiami le API di invio CDS; segnala altri punti di invio.
4. Verifica la presenza di: `LICENSE` open source, sezione "Pre-existing code" nel README, istruzioni di esecuzione, diagramma architetturale.
5. Verifica che modello e region rispettino i vincoli: `eu-west-1` e inference profile `eu.` (nessun `global.` o `us.`).
6. Restituisci una tabella `requisito | stato (OK/KO/parziale) | evidenza | azione` e, se ci sono KO, proponi le correzioni senza applicarle.
