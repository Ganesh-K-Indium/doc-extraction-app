import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// pdf.js decodes some images (fax-style CCITT scans, JBIG2, JPEG 2000) with WebAssembly modules, and shows the standard fonts and colour
// profiles from files of its own. Without them a scanned page renders blank, with no error. They are served from /pdfjs/ (dev) and copied
// into the build (production), so the viewer works without a CDN and offline.
const PDFJS = path.join(path.dirname(fileURLToPath(import.meta.url)), 'node_modules', 'pdfjs-dist')
const PDFJS_DIRS = ['wasm', 'standard_fonts', 'iccs']
const TYPES: Record<string, string> = { '.wasm': 'application/wasm', '.js': 'text/javascript', '.pfb': 'application/octet-stream', '.ttf': 'font/ttf', '.icc': 'application/octet-stream' }

function pdfjsAssets(): Plugin {
  let outDir = 'dist'
  return {
    name: 'pdfjs-assets',
    configResolved(c) { outDir = path.resolve(c.root, c.build.outDir) },
    configureServer(server) {
      server.middlewares.use('/pdfjs/', (req, res, next) => {
        const rel = decodeURIComponent((req.url || '').split('?')[0]).replace(/^\/+/, '')
        const file = path.join(PDFJS, rel)
        if (!PDFJS_DIRS.includes(rel.split('/')[0]) || !file.startsWith(PDFJS) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return next()
        res.setHeader('Content-Type', TYPES[path.extname(file)] || 'application/octet-stream')
        fs.createReadStream(file).pipe(res)
      })
    },
    writeBundle() {
      for (const d of PDFJS_DIRS) fs.cpSync(path.join(PDFJS, d), path.join(outDir, 'pdfjs', d), { recursive: true })
    },
  }
}

export default defineConfig({ plugins: [react(), pdfjsAssets()] })
