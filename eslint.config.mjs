import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: [
      '**/node_modules/',
      '**/cdk.out/',
      '**/dist/',
      '.venv/',
      'seed/private/',
      'seed/raw/',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
);
