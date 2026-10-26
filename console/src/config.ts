import { Amplify } from 'aws-amplify';
import { cognitoUserPoolsTokenProvider } from 'aws-amplify/auth/cognito';
import { sessionStorage } from 'aws-amplify/utils';

export function configureAuth(): void {
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: String(import.meta.env.VITE_USER_POOL_ID ?? ''),
        userPoolClientId: String(import.meta.env.VITE_USER_POOL_CLIENT_ID ?? ''),
      },
    },
  });
  // Tokens live in sessionStorage, not localStorage (AGENTS.md §7: nothing sensitive in localStorage).
  cognitoUserPoolsTokenProvider.setKeyValueStorage(sessionStorage);
}
