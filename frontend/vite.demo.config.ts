import { readFileSync } from 'node:fs'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

// viteSingleFile()只内联构建管线产出的JS/CSS（<script>/<link rel="stylesheet">指向的build
// 产物），public/下原样拷贝的静态文件（这里是favicon.svg）不在它管辖范围内，会继续以外部文件
// 形式躺在dist-demo/旁边——对"完全自包、双击即开、不用管相对路径"这个demo构建的目标来说，这就
// 是唯一剩下的外部依赖，不修就不是真正的单文件。手写一个transformIndexHtml插件，把favicon的
// href直接换成base64 data URI，只在demo构建生效，不改动frontend/index.html本身（正常生产
// 构建仍然引用/favicon.svg这个真实静态资源，两边各自独立）。
function inlineFaviconPlugin(): Plugin {
  return {
    name: 'inline-favicon-data-uri',
    transformIndexHtml(html) {
      const svg = readFileSync(new URL('./public/favicon.svg', import.meta.url))
      const dataUri = `data:image/svg+xml;base64,${svg.toString('base64')}`
      return html.replace(/\.?\/favicon\.svg/, dataUri)
    },
  }
}

// 静态demo构建的独立配置——刻意跟vite.config.ts分开一个文件，不是在那份配置里加个if分支：
// 主配置那份"生产构建必须显式设VITE_API_BASE_URL"的护栏是给"真的要连真实后端"的生产部署写的，
// demo构建完全不连后端（src/api.ts的IS_DEMO分支直接从bundle里的src/demo-data/resolve只读
// GET，见该文件顶部注释），硬套同一个护栏只会逼着在demo构建时也去设一个用不到的假URL，纯粹
// 混淆意图。两份配置各自独立、各管各的，比一份配置里塞两套互不相关的校验逻辑更清楚。
//
// viteSingleFile()把构建产物的JS/CSS全部内联进一个HTML文件——demo.html因此可以离线双击打开
// （file://协议下ES module的跨源限制不适用，因为压根没有独立的.js文件要再发一次请求去加载），
// 也可以直接扔进任意静态托管，不用担心相对路径/base配置对不上。
//
// npm run build:demo 用这份配置（见package.json），产物是 dist-demo/index.html——Vite的HTML
// 产物文件名固定跟着input走，不是rollupOptions.output能改的（那个只管JS/CSS chunk命名），
// 想要demo.html这个文件名，由package.json的build:demo脚本在构建后再rename一步，不在这里硬来。
export default defineConfig({
  define: {
    'import.meta.env.VITE_DEMO_MODE': JSON.stringify('true'),
  },
  plugins: [react(), inlineFaviconPlugin(), viteSingleFile()],
  build: {
    outDir: 'dist-demo',
    emptyOutDir: true,
  },
})
