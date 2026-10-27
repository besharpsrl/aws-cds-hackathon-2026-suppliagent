# SuppliAgent – Testi e template

> Stato: **v0.1** (26/10/2026) · Contiene i template WhatsApp (T-28). Le altre sezioni (informativa e consenso, email HTML e PDF, RCS/SMS, messaggi di sistema) sono ancora in [TODO_DOCS](./TODO_DOCS.md) §3.

## 1. Template WhatsApp

**Fonte unica**: i JSON in [`services/notifier/whatsapp_templates/`](../services/notifier/whatsapp_templates/) (`<nome>.<lingua>.json`, formato `template-definition` di Meta). Si usano sia per l'invio a Meta sia dal Notifier (T-24): i testi si cambiano solo lì. `tests/test_whatsapp_templates.py` verifica le regole di Meta (nomi, variabili `{{1}}…{{n}}` in ordine, corpo che non inizia né finisce con una variabile, esempi, lunghezze di header/footer/pulsanti, stessa forma IT/EN).

Servono **solo fuori dalla finestra di 24 ore** (F-11.C2): dentro la finestra il Notifier manda messaggi liberi o interattivi.

| Template | Categoria | Quando (flusso) | Variabili | Pulsanti (quick reply) |
|---|---|---|---|---|
| `order_confirmation` | UTILITY | Ordine confermato (F-07, FN-12/14), insieme all'email con PDF | 1 nome · 2 numero ordine · 3 data consegna · 4 n. righe · 5 limite per le modifiche (cut-off) | *Modifica ordine* |
| `order_pending_reminder` | UTILITY | Bozza non confermata dopo `pendingReminderHours` (FN-12) | 1 nome · 2 n. righe · 3 data consegna · 4 limite per confermare | *Vedi riepilogo* · *Annulla bozza* |
| `delivery_update` | UTILITY | Giorno di consegna (F-12, FN-18), se il contatto usa WhatsApp | 1 nome · 2 numero ordine · 3–4 fascia oraria | *Ricevuto* · *Segnala problema* |
| `reorder_suggestion` | MARKETING | Riordino proattivo (F-13, FN-19), solo con consenso | 1 nome · 2 prodotti abituali · 3 data ultimo ordine · 4 prossima consegna | *Riordina uguale* · *Modifica* · *No grazie* · *Stop proposte* |

Scelte di contenuto:
- Nessun pulsante conferma un ordine "alla cieca": *Vedi riepilogo* e *Riordina uguale* portano al riepilogo, la conferma esplicita arriva dopo (FN-12, AGENTS §8.1).
- Footer "Assistente virtuale ordini · messaggio automatico" su tutti: l'agente si dichiara assistente virtuale (AGENTS §8.8). Nessun nome del distributore né marchi di terzi (AGENTS §11).
- `reorder_suggestion` è MARKETING: *Stop proposte* revoca il consenso proattivo (FN-19, F-13). Meta può comunque riclassificare la categoria.
- Nessun prezzo, sconto o promessa commerciale nei testi.

### Invio a Meta (task T-29, una volta per WABA)

Prerequisito: WABA collegata ad AWS End User Messaging Social in `eu-west-1` (T-20). Con l'ID della WABA (`aws socialmessaging list-linked-whatsapp-business-accounts`):

```bash
export AWS_PROFILE=default AWS_REGION=eu-west-1
for f in services/notifier/whatsapp_templates/*.json; do
  aws socialmessaging create-whatsapp-message-template --id <WABA_ID> --template-definition "fileb://$f"
done
aws socialmessaging list-whatsapp-message-templates --id <WABA_ID>   # stato: PENDING → APPROVED/REJECTED
```

**Stato (WABA `dev`, `waba-8c2d297ba5154c33b7d0ceac98c7410a`)**: gli 8 template sono stati inviati il 27/10/2026 e risultano `PENDING` (categorie assegnate da Meta: UTILITY per i primi tre, MARKETING per `reorder_suggestion`). L'esito `APPROVED`/`REJECTED` va verificato con `list-whatsapp-message-templates` e annotato qui (task T-29).

In alternativa: console AWS End User Messaging Social → *Message templates* → *Create template*, copiando i testi dai JSON. Se Meta rifiuta un template, si corregge il JSON (il test deve restare verde) e lo si reinvia.
