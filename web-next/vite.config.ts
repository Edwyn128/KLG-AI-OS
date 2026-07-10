import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'KLG AI OS',
        short_name: 'KLG',
        description: 'Kowal Law Group AI Operating System',
        theme_color: '#0a0e16',
        background_color: '#0a0e16',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
      },
    }),
  ],

  // In development, proxy all API calls to the FastAPI backend.
  // In production, FastAPI serves the built React app from the same origin,
  // so API paths (/alfred/*, /bloodhound/*, etc.) work without a proxy.
  server: {
    port: 5173,
    proxy: {
      '/alfred':     'http://localhost:8000',
      '/bloodhound': 'http://localhost:8000',
      '/cases':      'http://localhost:8000',
      '/slack':      'http://localhost:8000',
      '/auth':       'http://localhost:8000',
      '/health':     'http://localhost:8000',
    },
  },

  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
          state:  ['zustand'],
        },
      },
    },
  },
})
