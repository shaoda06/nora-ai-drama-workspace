import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import { version } from './package.json';
export default defineConfig({
  plugins: [react(), {
    name: 'release-version',
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'release.json', source: JSON.stringify({ version }) });
    },
  }],
  define: { __APP_VERSION__: JSON.stringify(version) },
  server: { proxy: { '/api': 'http://127.0.0.1:8781' } },
});
