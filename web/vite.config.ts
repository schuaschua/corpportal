import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// `npm run dev` proxies the APIs like nginx does in the container (compose ports 8001/8002/8003).
const api = (target: string, prefix: string) => ({
  target,
  changeOrigin: true,
  rewrite: (path: string) => path.replace(new RegExp(`^${prefix}`), ''),
});

export default defineConfig({
  plugins: [react()],
  build: { chunkSizeWarningLimit: 800 }, // Fluent UI; one internal PoC app
  server: {
    port: 5173,
    proxy: {
      '/api/accounts': api('http://localhost:8001', '/api/accounts'),
      '/api/payments': api('http://localhost:8002', '/api/payments'),
      '/api/insights': api('http://localhost:8003', '/api/insights'),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
  },
});
