import svelte from '@astrojs/svelte';
import { defineConfig } from 'astro/config';

// Dirección de Django en desarrollo. No es un secreto: solo existe en el computador local.
const API_LOCAL = 'http://127.0.0.1:8000';

export default defineConfig({
  // Sitio estático, sin SSR: en producción lo sirve Django desde el mismo dominio que la API.
  output: 'static',
  integrations: [svelte()],
  server: { port: 4321 },
  vite: {
    server: {
      // En desarrollo, /api se reenvía a Django para conservar el mismo origen
      // que en producción (cookies SameSite=Strict y sin CORS).
      proxy: {
        '/api': { target: API_LOCAL, changeOrigin: false },
      },
    },
  },
});
