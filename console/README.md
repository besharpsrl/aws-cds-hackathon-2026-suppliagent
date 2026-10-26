# console – back-office console & sales rep web chat (React + Vite + TypeScript)

Cognito groups: `backoffice`, `sales_rep`, `judge` (read-only). Brand assets in `../assets/brand/`.
Backlog: T-62…T-66.

## Run locally

```bash
cp console/.env.example console/.env.local   # fill with the outputs of suppliagent-<env>-console
npm run dev -w console                       # http://localhost:5173
npm test -w console | npm run build -w console
```

- Sign-in: Cognito user pool (SRP) via Amplify Auth; tokens are kept in `sessionStorage`, never `localStorage`.
- Users are created by an admin (Cognito console or `aws cognito-idp admin-create-user` + `admin-add-user-to-group`); a `sales_rep` also needs the `custom:repId` attribute. With a temporary password the login asks for a new one at first access (or use `admin-set-user-password --permanent`).
- `src/api/client.ts` calls the REST API with the ID token; roles are enforced by the API, the route guard (`RequireRole`) is UI only.
- Deploy of the built SPA to the site bucket is not automated yet: `npm run build -w console`, then `aws s3 sync console/dist s3://<SiteBucketName> --delete` and a CloudFront invalidation.
