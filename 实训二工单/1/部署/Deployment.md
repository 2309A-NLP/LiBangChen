# 思维导图项目 — 部署文档

## 一、部署概览

本项目为纯前端 SPA 应用，支持多种部署方式。推荐使用 **静态站点托管** 方案。

| 部署方式 | 适用场景 | 成本 | 难度 |
|---------|---------|------|------|
| **GitHub Pages** | 个人/演示项目 | 免费 | ⭐ 简单 |
| **Vercel** | 快速部署、自动 CI/CD | 免费 | ⭐ 简单 |
| **Netlify** | 托管 + Serverless 函数 | 免费 | ⭐ 简单 |
| **Nginx (VPS)** | 自有服务器、完全可控 | 低 | ⭐⭐ 中等 |
| **Docker + Nginx** | 容器化部署 | 低 | ⭐⭐⭐ 较难 |
| **阿里云 OSS + CDN** | 国内加速访问 | 低 | ⭐⭐ 中等 |

---

## 二、构建产物

### 2.1 本地构建

```bash
# 1. 安装依赖
npm install

# 2. 生产构建
npm run build

# 3. 构建产物在 dist/ 目录
ls -lh dist/
# ├── index.html
# ├── assets/
# │   ├── index-abc123.js    (JS bundle)
# │   ├── index-abc123.css   (CSS bundle)
# │   └── vendor-xyz789.js   (第三方库 chunk)
# └── favicon.svg
```

### 2.2 本地预览构建产物

```bash
# 使用 vite preview
npm run preview

# 或使用 serve
npx serve dist -p 3000
```

---

## 三、方式一：GitHub Pages 部署

### 3.1 配置 vite.config.ts

```typescript
// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/mindmark/',  // 👈 改为你的 GitHub 仓库名
});
```

### 3.2 GitHub Actions 自动部署

创建 `.github/workflows/deploy.yml`：

```yaml
name: Deploy to GitHub Pages

on:
  push:
    branches: [ main ]
  workflow_dispatch:      # 支持手动触发

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: true

jobs:
  build-and-deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'

      - name: Install dependencies
        run: npm ci

      - name: Lint check
        run: npm run lint

      - name: Type check
        run: npm run type-check

      - name: Unit tests
        run: npm run test -- --coverage

      - name: Build
        run: npm run build

      - name: Setup Pages
        uses: actions/configure-pages@v4

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: './dist'

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

### 3.3 手动部署

```bash
# 安装 gh-pages
npm install --save-dev gh-pages

# package.json 添加脚本
# "deploy": "gh-pages -d dist"

npm run build
npm run deploy
```

---

## 四、方式二：Vercel 部署 (推荐)

### 4.1 命令行部署

```bash
# 安装 Vercel CLI
npm install -g vercel

# 首次部署
vercel

# 配置：
# ? Set up and deploy: Y
# ? Which scope: (选择你的账号)
# ? Link to existing project: N
# ? Project name: mindmark
# ? In which directory: ./
# ? Framework Preset: Vite
# ? Build Command: npm run build
# ? Output Directory: dist
# ? Development Command: npm run dev

# 生产部署
vercel --prod
```

### 4.2 vercel.json 配置

```json
{
  "framework": "vite",
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "devCommand": "npm run dev",
  "installCommand": "npm install",
  "headers": [
    {
      "source": "/assets/(.*)",
      "headers": [
        {
          "key": "Cache-Control",
          "value": "public, max-age=31536000, immutable"
        }
      ]
    },
    {
      "source": "/(.*)",
      "headers": [
        {
          "key": "X-Content-Type-Options",
          "value": "nosniff"
        },
        {
          "key": "X-Frame-Options",
          "value": "DENY"
        },
        {
          "key": "X-XSS-Protection",
          "value": "1; mode=block"
        }
      ]
    }
  ],
  "redirects": [
    {
      "source": "/(.*)",
      "destination": "/index.html"
    }
  ]
}
```

---

## 五、方式三：Nginx VPS 部署

### 5.1 服务器准备

```bash
# 更新系统 (Ubuntu/Debian)
sudo apt update && sudo apt upgrade -y

# 安装 Nginx
sudo apt install nginx -y

# 启动并设置开机自启
sudo systemctl start nginx
sudo systemctl enable nginx

# 检查状态
sudo systemctl status nginx
```

### 5.2 上传构建产物

```bash
# 在本地执行
npm run build

# 上传到服务器
scp -r dist/* user@your-server-ip:/var/www/mindmark/

# 或使用 rsync
rsync -avz --delete dist/ user@your-server-ip:/var/www/mindmark/
```

### 5.3 Nginx 配置文件

`/etc/nginx/sites-available/mindmark`：

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name your-domain.com www.your-domain.com;

    root /var/www/mindmark;
    index index.html;

    # Gzip 压缩
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_comp_level 6;
    gzip_types
        text/plain
        text/css
        text/javascript
        application/javascript
        application/json
        image/svg+xml
        application/xml+rss;

    # 静态资源缓存
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # SPA 路由回退
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 安全头
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # 日志
    access_log /var/log/nginx/mindmark-access.log;
    error_log /var/log/nginx/mindmark-error.log;
}

# HTTPS 重定向 (获取 SSL 证书后启用)
# server {
#     listen 80;
#     server_name your-domain.com;
#     return 301 https://$server_name$request_uri;
# }
#
# server {
#     listen 443 ssl http2;
#     server_name your-domain.com;
#
#     ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
#     ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
#     ssl_protocols TLSv1.2 TLSv1.3;
#     ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
#
#     # ... 其余配置同上
# }
```

### 5.4 启用站点

```bash
# 创建软链接
sudo ln -s /etc/nginx/sites-available/mindmark /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重载 Nginx
sudo nginx -s reload
```

### 5.5 SSL 证书 (Let's Encrypt)

```bash
# 安装 certbot
sudo apt install certbot python3-certbot-nginx -y

# 获取证书并自动配置 Nginx
sudo certbot --nginx -d your-domain.com -d www.your-domain.com

# 设置自动续期 (crontab)
sudo crontab -e
# 添加: 0 3 * * * certbot renew --quiet --post-hook "nginx -s reload"
```

---

## 六、方式四：Docker 部署

### 6.1 Dockerfile

```dockerfile
# ---- Build Stage ----
FROM node:20-alpine AS builder

WORKDIR /app

# 利用 Docker 缓存层
COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---- Production Stage ----
FROM nginx:alpine

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 Nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
```

### 6.2 nginx.conf (Docker)

```nginx
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/javascript application/javascript application/json image/svg+xml;

    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

### 6.3 docker-compose.yml

```yaml
version: '3.8'

services:
  mindmark:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: mindmark
    ports:
      - "8080:80"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:80/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 5s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### 6.4 Docker 部署命令

```bash
# 构建镜像
docker build -t mindmark:latest .

# 使用 docker-compose
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止
docker-compose down

# 更新部署
docker-compose pull
docker-compose up -d --build
```

---

## 七、方式五：阿里云 OSS + CDN (国内优化)

### 7.1 OSS 配置

```bash
# 安装 ossutil
# 下载: https://help.aliyun.com/document_detail/120075.html

# 配置 AK
ossutil config

# 上传构建产物
ossutil cp -r dist/ oss://your-bucket-name/mindmark/ \
  --meta Cache-Control:"public, max-age=31536000, immutable" \
  --include "assets/*"

ossutil cp dist/index.html oss://your-bucket-name/mindmark/index.html \
  --meta Cache-Control:"no-cache"
```

### 7.2 CDN 加速

1. 在阿里云 CDN 控制台添加域名
2. 源站选择 OSS Bucket
3. 配置缓存规则：
   - `/assets/*` → 缓存 365 天
   - `/index.html` → 不缓存
4. 开启 HTTPS、HTTP/2、Brotli 压缩
5. CNAME 解析到 CDN 域名

---

## 八、环境变量配置

### 8.1 .env 文件

```bash
# .env.production
VITE_APP_TITLE=MindMark
VITE_APP_VERSION=$npm_package_version
VITE_GA_ID=G-XXXXXXXXXX           # Google Analytics (可选)
VITE_SENTRY_DSN=                  # Sentry 错误监控 (可选)
```

### 8.2 在代码中使用

```typescript
const APP_TITLE = import.meta.env.VITE_APP_TITLE;
const APP_VERSION = import.meta.env.VITE_APP_VERSION;

// 条件加载分析
if (import.meta.env.PROD && import.meta.env.VITE_GA_ID) {
  // 初始化 Google Analytics
}
```

---

## 九、CI/CD 流水线 (GitHub Actions 完整版)

`.github/workflows/ci-cd.yml`：

```yaml
name: CI/CD Pipeline

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  # ---- 代码质量检查 ----
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'
      - run: npm ci
      - run: npm run lint
      - run: npm run type-check
      - run: npm run test -- --coverage
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        if: github.ref == 'refs/heads/main'

  # ---- 构建 ----
  build:
    needs: quality
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'
      - run: npm ci
      - run: npm run build
      - name: Upload build artifact
        uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  # ---- 部署到 Vercel (main 分支) ----
  deploy-vercel:
    needs: build
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to Vercel
        uses: amondnet/vercel-action@v25
        with:
          vercel-token: ${{ secrets.VERCEL_TOKEN }}
          vercel-org-id: ${{ secrets.VERCEL_ORG_ID }}
          vercel-project-id: ${{ secrets.VERCEL_PROJECT_ID }}
          vercel-args: '--prod'

  # ---- 部署到 GitHub Pages (main 分支) ----
  deploy-gh-pages:
    needs: build
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    permissions:
      pages: write
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: actions/configure-pages@v4
      - uses: actions/upload-pages-artifact@v3
        with:
          path: './dist'
      - uses: actions/deploy-pages@v4
```

---

## 十、健康检查 & 监控

### 10.1 健康检查端点 (如使用 Nginx)

```nginx
location /health {
    access_log off;
    return 200 "OK";
    add_header Content-Type text/plain;
}
```

### 10.2 监控建议

| 工具 | 用途 | 成本 |
|------|------|------|
| **Google Analytics** | 用户行为分析 | 免费 |
| **Sentry** | 前端错误监控 | 免费额度 |
| **UptimeRobot** | 服务可用性监控 | 免费 (50 个监控) |
| **Lighthouse CI** | 性能回归检测 | 免费 |

---

## 十一、部署检查清单

- [ ] `npm run build` 构建成功，无错误
- [ ] `npm run preview` 本地预览正常
- [ ] 所有页面路由正常 (刷新不 404)
- [ ] 静态资源加载正常 (CSS/JS/图片)
- [ ] HTTPS 已启用
- [ ] Gzip/Brotli 压缩已开启
- [ ] 静态资源 Cache-Control 头配置正确
- [ ] `index.html` 设置了 `no-cache`
- [ ] CSP 安全头已配置
- [ ] 自定义域名 DNS 解析正常
- [ ] 404 页面已配置
- [ ] sitemap.xml / robots.txt 已部署 (如需 SEO)
- [ ] 部署后功能冒烟测试通过

---

## 十二、快速部署脚本

创建 `scripts/deploy.sh`：

```bash
#!/bin/bash
set -e

echo "🚀 MindMark 部署脚本"
echo "======================"

# 检查环境
if ! command -v node &> /dev/null; then
    echo "❌ 请先安装 Node.js (>= 18)"
    exit 1
fi

# 选择部署目标
echo ""
echo "请选择部署方式:"
echo "  1) Vercel (推荐)"
echo "  2) GitHub Pages"
echo "  3) 服务器 Nginx"
echo "  4) Docker"
read -p "输入数字 (1-4): " choice

# 安装依赖
echo ""
echo "📦 安装依赖..."
npm ci

# 代码检查
echo ""
echo "🔍 代码检查..."
npm run lint || true

# 测试
echo ""
echo "🧪 运行测试..."
npm run test -- --passWithNoTests || true

# 构建
echo ""
echo "🏗️  构建项目..."
npm run build

case $choice in
  1)
    echo ""
    echo "▲ 部署到 Vercel..."
    npx vercel --prod
    ;;
  2)
    echo ""
    echo "🐙 部署到 GitHub Pages..."
    npx gh-pages -d dist
    ;;
  3)
    echo ""
    read -p "输入服务器地址 (user@host): " SERVER
    read -p "输入部署路径 (/var/www/mindmark): " PATH_DEPLOY
    echo "📤 上传到服务器..."
    rsync -avz --delete dist/ "$SERVER:$PATH_DEPLOY"
    echo "✅ 上传完成！请在服务器上重载 Nginx"
    ;;
  4)
    echo ""
    echo "🐳 Docker 部署..."
    docker build -t mindmark:latest .
    docker-compose up -d
    echo "✅ Docker 部署完成！访问 http://localhost:8080"
    ;;
  *)
    echo "❌ 无效选择"
    exit 1
    ;;
esac

echo ""
echo "🎉 部署完成！"
```

```bash
# 赋予执行权限
chmod +x scripts/deploy.sh

# 执行
./scripts/deploy.sh
```

---

> 📅 文档版本: v1.0  
> 📝 最后更新: 2026-06-22
