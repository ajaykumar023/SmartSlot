import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig({
    plugins: [react(), tailwindcss()],
    server: { port: 5173 },
    build: { rollupOptions: { output: { manualChunks(id) {
                    if (id.includes('/node_modules/@zxing/'))
                        return 'qr-scanner';
                    if (id.includes('/node_modules/react/') || id.includes('/node_modules/react-dom/'))
                        return 'react-vendor';
                    if (id.includes('/node_modules/lucide-react/'))
                        return 'icons';
                } } } },
});
