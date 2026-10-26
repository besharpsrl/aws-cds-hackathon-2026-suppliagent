/** Cognito groups of the console (INFRASTRUCTURE_DESIGN §5.8); `judge` is read-only (FN-28). */
export const ROLES = ['backoffice', 'sales_rep', 'judge'] as const;
export type Role = (typeof ROLES)[number];

/** Reads the `cognito:groups` claim of the ID token; anything unexpected yields no roles. */
export function rolesFromGroups(groups: unknown): Role[] {
  if (!Array.isArray(groups)) return [];
  return ROLES.filter((role) => groups.includes(role));
}

export const isReadOnly = (roles: readonly Role[]): boolean =>
  roles.length > 0 && roles.every((role) => role === 'judge');
