import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  build: {
    target: 'es2020',
    sourcemap: false,
    chunkSizeWarningLimit: 500,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: 'react-vendor',
              test: /node_modules[\\/](react|react-dom|react-is)[\\/]/,
              priority: 30,
              maxSize: 260000,
            },
            {
              name: 'charts-vendor',
              test: /node_modules[\\/](recharts|d3-[^\\/]+|victory-vendor)[\\/]/,
              priority: 20,
              maxSize: 360000,
              entriesAware: true,
            },
            {
              name: 'icons-vendor',
              test: /node_modules[\\/]lucide-react[\\/]/,
              priority: 10,
              maxSize: 220000,
            },
            {
              name: 'vendor',
              test: /node_modules[\\/]/,
              priority: 1,
              maxSize: 320000,
              entriesAware: true,
            },
          ],
        },
      },
    },
  },
})
