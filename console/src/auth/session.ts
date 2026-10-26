import { fetchAuthSession } from 'aws-amplify/auth';
import { rolesFromGroups, type Role } from './roles';

export interface AuthUser {
  email: string;
  roles: Role[];
}

/** Current user from the stored Cognito session, or null when signed out. */
export async function loadUser(): Promise<AuthUser | null> {
  const { tokens } = await fetchAuthSession();
  const payload = tokens?.idToken?.payload;
  if (!payload) return null;
  return {
    email: String(payload.email ?? ''),
    roles: rolesFromGroups(payload['cognito:groups']),
  };
}

/** The REST authorizer validates the ID token (not the access token). */
export async function getIdToken(): Promise<string> {
  const { tokens } = await fetchAuthSession();
  const token = tokens?.idToken?.toString();
  if (!token) throw new Error('Not signed in');
  return token;
}
