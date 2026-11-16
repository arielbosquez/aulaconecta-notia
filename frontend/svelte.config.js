import { vitePreprocess } from '@astrojs/svelte';

export default {
  // Permite TypeScript dentro de los componentes .svelte.
  preprocess: vitePreprocess(),
};
