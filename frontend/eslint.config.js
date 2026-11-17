// Reglas de ESLint del frontend de NotIA.
//
// Revisa TypeScript, los componentes Svelte y los scripts de Node. Los archivos
// .astro los revisa `astro check` (npm run check).
import js from '@eslint/js';
import security from 'eslint-plugin-security';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';
import ts from 'typescript-eslint';

import svelteConfig from './svelte.config.js';

export default ts.config(
  { ignores: ['dist/', '.astro/', 'node_modules/'] },

  js.configs.recommended,
  ...ts.configs.strict,
  ...svelte.configs.recommended,
  security.configs.recommended,

  {
    // Código que corre en el navegador.
    files: ['src/**/*.{ts,svelte}', 'src/**/*.svelte.ts'],
    languageOptions: { globals: globals.browser },
  },
  {
    // Scripts de build y archivos de configuración: corren en Node.
    files: ['scripts/**/*.mjs', '*.config.{js,mjs}'],
    languageOptions: { globals: globals.node },
  },
  {
    // Los scripts de build leen y escriben rutas que entrega quien los ejecuta
    // (dist/ y csp-hashes.json) y arman sus expresiones regulares con constantes
    // del propio archivo: no reciben datos de usuarios. Estas dos reglas siguen
    // activas en src/, que es el código que llega al navegador.
    files: ['scripts/**/*.mjs'],
    rules: {
      'security/detect-non-literal-fs-filename': 'off',
      'security/detect-non-literal-regexp': 'off',
    },
  },
  {
    // Los componentes Svelte usan TypeScript en su bloque <script>.
    files: ['**/*.svelte', '**/*.svelte.ts'],
    languageOptions: {
      parserOptions: {
        parser: ts.parser,
        extraFileExtensions: ['.svelte'],
        svelteConfig,
      },
    },
  },
  {
    rules: {
      // Regla del proyecto: nada de HTML sin escapar. El texto que llega de la
      // API se muestra siempre como texto.
      'svelte/no-at-html-tags': 'error',
      // Ningún código se arma a partir de texto.
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-new-func': 'error',
      eqeqeq: ['error', 'always'],
    },
  },
);
