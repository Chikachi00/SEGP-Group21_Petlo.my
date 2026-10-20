import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Generated CV outputs must not be watched: Windows directory handles can block atomic renames.
  server: {
    watch: {
      ignored: ["**/outputs/**", "**/backend/data/**", "**/.venv/**", "**/data/raw/**"],
    },
  },
})
