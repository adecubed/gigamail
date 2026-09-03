// ESLint flat config per la console Electron.
//
// Due mondi: main/preload sono CommonJS Node; i renderer sono script browser
// caricati via <script> che condividono funzioni globali tra file (renderer.js
// usa cio' che definisce renderer_utils.js, ecc.). Per quel gruppo no-undef
// resterebbe cieco senza un manifesto di tutti i nomi condivisi: finche' la
// console non passa a moduli ES (lavoro 0.3.0), la' e' spento.
const js = require('@eslint/js');

const NODE_GLOBALS = {
  require: 'readonly', module: 'writable', exports: 'writable',
  process: 'readonly', __dirname: 'readonly', Buffer: 'readonly',
  console: 'readonly', setTimeout: 'readonly', clearTimeout: 'readonly',
  setInterval: 'readonly', clearInterval: 'readonly', URL: 'readonly',
  // I preload girano nel contesto renderer: hanno anche le API web.
  fetch: 'readonly', FormData: 'readonly', URLSearchParams: 'readonly',
  Blob: 'readonly', AbortController: 'readonly',
};

const BROWSER_GLOBALS = {
  window: 'readonly', document: 'readonly', navigator: 'readonly',
  console: 'readonly', fetch: 'readonly', alert: 'readonly',
  confirm: 'readonly', prompt: 'readonly', localStorage: 'readonly',
  setTimeout: 'readonly', clearTimeout: 'readonly',
  setInterval: 'readonly', clearInterval: 'readonly',
  requestAnimationFrame: 'readonly', URL: 'readonly',
  URLSearchParams: 'readonly', Blob: 'readonly', FileReader: 'readonly',
  FormData: 'readonly', AbortController: 'readonly', Audio: 'readonly',
  MediaRecorder: 'readonly', AudioContext: 'readonly', Event: 'readonly',
  CustomEvent: 'readonly', DOMParser: 'readonly', Node: 'readonly',
  getComputedStyle: 'readonly', atob: 'readonly', btoa: 'readonly',
};

module.exports = [
  { ignores: ['node_modules/**', 'dist/**', 'python-embedded/**'] },
  {
    files: ['main.js', 'preload*.js', 'calendar_notifier.js', 'sync-version.js', 'tests/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'commonjs',
      globals: NODE_GLOBALS,
    },
    rules: {
      ...js.configs.recommended.rules,
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },
  {
    files: ['tests/**/*.mjs'],
    languageOptions: { ecmaVersion: 2022, sourceType: 'module', globals: NODE_GLOBALS },
    rules: {
      ...js.configs.recommended.rules,
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },
  {
    files: ['renderer*.js', 'i18n.js', 'voice_mail.js', 'popup_bridge.js', 'mail_render.js', 'features.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'script',
      globals: { ...BROWSER_GLOBALS, module: 'readonly' },
    },
    rules: {
      ...js.configs.recommended.rules,
      'no-undef': 'off',
      'no-unused-vars': 'off',
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },
];
