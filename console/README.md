# console – back-office console & sales rep web chat (React + Vite + TypeScript)

Cognito groups: `backoffice`, `sales_rep`, `judge` (read-only). Brand assets in `../assets/brand/`.
Backlog: T-62 (real API wiring, done), T-63 (conversations and handoff, done), T-64…T-66.

## Run locally

```bash
cp console/.env.example console/.env.local   # fill with the outputs of suppliagent-<env>-console
npm run dev -w console                       # http://localhost:5173
npm test -w console | npm run build -w console
```

- Sign-in: Cognito user pool (SRP) via Amplify Auth; tokens are kept in `sessionStorage`, never `localStorage`.
- Users are created by an admin (Cognito console or `aws cognito-idp admin-create-user` + `admin-add-user-to-group`); a `sales_rep` also needs the `custom:repId` attribute. With a temporary password the login asks for a new one at first access (or use `admin-set-user-password --permanent`).
- Orders views (`src/orders/`) run on mock data by default for local development (4 synthetic orders on the eval ticket photos); set `VITE_ORDERS_SOURCE=api` to use the real API (list, detail with the ticket photo, line correction, conversations with *Take over* / *Reply* / *Release*; lists refresh by polling every 2 s).
- `src/api/client.ts` calls the REST API with the ID token; roles are enforced by the API, the route guard (`RequireRole`) is UI only.
- Publish the SPA online with `scripts/deploy-console.sh [dev]` (needs the ConsoleStack deployed and AWS credentials): it reads the Cognito/API ids from the stack outputs, builds, syncs the site bucket and invalidates CloudFront. Orders use the real API (`VITE_ORDERS_SOURCE=api`); pass `VITE_ORDERS_SOURCE=mock` for mock data.
- UI: Tailwind CSS v4 + shadcn/ui components copied in `src/components/ui/` (`components.json`, alias `@/` → `src/`). Theme tokens in `src/styles.css` follow the beSharp Brand Identity Guidelines v1.0: Be Sharple `#7531AF` as primary, Black Rock sidebar, White Not backgrounds; Sora for text, Montserrat Black all caps for titles (open substitute of Gotham). Fonts are bundled with `@fontsource`, no external CDN. Success/warning/error colours are functional additions, always paired with an icon and text.
