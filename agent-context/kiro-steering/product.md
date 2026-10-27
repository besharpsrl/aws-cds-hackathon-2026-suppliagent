---
inclusion: always
---

# Product – SuppliAgent

SuppliAgent è un agente AI per gli **ordini HoReCa** di un distributore alimentare (cliente reale di beSharp), costruito per l'AWS CDS Agentic AI Partner Hackathon (consegna 28/10/2026, code freeze 28/10 ore 12:00; stato e backlog in `START_HERE.md`).

## Utenti
- **Ristoratore**: ordina su WhatsApp (foto del bigliettino scritto a mano, vocale, testo) o via email; conferma con un tap; riceve conferma via email con PDF e SMS/RCS, avvisi di consegna, proposte di riordino.
- **Agente di commercio**: copilota su WhatsApp o chat web – consigli per cliente, catalogo e schede tecniche, briefing, ordini per conto del cliente (solo il proprio portafoglio).
- **Back office**: console web con ordini, righe incerte, problemi di consegna, handoff, KPI.

## Regole di dominio (sempre valide)
1. Nessun ordine inviato all'ERP senza **conferma esplicita**.
2. Chiarimenti solo sulle righe incerte, max 3 opzioni + "Altro".
3. Max **1 suggerimento** per ordine, solo con consenso.
4. Riordino proattivo: max 1 proposta ogni 7 giorni per cliente, mai di notte, mai senza consenso.
5. WhatsApp fuori finestra 24h → solo **template approvati**.
6. **Una risposta per raffica** di messaggi (debounce) e ordine garantito per chat.
7. Tutti gli invii passano dal **Notifier**.
8. L'agente si dichiara assistente virtuale; niente prezzi/sconti fuori listino; niente dati di altri clienti.
9. Solo **dati anonimizzati o sintetici**.

## Fonti di verità
- Funzionalità e criteri di accettazione: #[[file:docs/03_FUNCTIONAL_SPEC.md]]
- Flussi, stati, casi ed errori: #[[file:docs/02_TECHNICAL_FLOWS.md]]
- Panoramica: #[[file:docs/01_PROJECT_OVERVIEW.md]]

Ogni task deve citare le `FN-xx` (e i flussi `F-xx.Cn`) che implementa. Se il comportamento cambia, aggiorna i documenti.
