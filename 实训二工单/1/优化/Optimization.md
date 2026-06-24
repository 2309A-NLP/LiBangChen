# 思维导图项目 — 优化建议

## 一、性能优化

### 1.1 解析性能

| 优化点 | 问题描述 | 解决方案 | 优先级 |
|--------|---------|---------|--------|
| **增量解析** | 全量重新解析整个 MD 文本 | 仅解析变更区域，使用 AST diff 算法 (如 `micromark` 增量模式) | 🔴 高 |
| **Web Worker 解析** | 大文件解析阻塞主线程 | 将 remark-parse 放入 Web Worker，解析完成回传 TreeNode | 🔴 高 |
| **解析结果缓存** | 相同输入重复解析 | 对 `md5(markdownText)` 做 LRU 缓存，缓存命中直接返回 | 🟡 中 |
| **懒加载解析** | 折叠节点下的内容也被解析 | 折叠节点跳过子节点解析，展开时按需解析 | 🟡 中 |

### 1.2 渲染性能

| 优化点 | 问题描述 | 解决方案 | 优先级 |
|--------|---------|---------|--------|
| **虚拟化渲染** | 500+ 节点全部渲染到 SVG DOM | 仅渲染视口可见节点 + 可视缓冲区，其余懒渲染 | 🔴 高 |
| **Canvas 替代 SVG** | 大量节点时 SVG DOM 膨胀 | 节点数 > 200 时自动切换 Canvas 渲染 (Konva.js) | 🔴 高 |
| **requestAnimationFrame** | 缩放/拖拽时频繁 setState | 使用 rAF 合并渲染，避免每帧都触发 React 重渲染 | 🟡 中 |
| **React.memo** | 节点组件无意义重渲染 | Node 组件使用 `React.memo` + `useMemo` 避免不必要更新 | 🟡 中 |
| **连线简化** | 大量贝塞尔曲线计算 | 折叠态连线直接用直线，展开态使用简化的二次贝塞尔 | 🟢 低 |

### 1.3 打包优化

| 优化点 | 问题描述 | 解决方案 | 优先级 |
|--------|---------|---------|--------|
| **Tree Shaking** | D3.js 全量引入 (~500KB) | 按需引入 `d3-hierarchy`, `d3-zoom`, `d3-selection` 等子模块 | 🔴 高 |
| **Code Splitting** | 单 bundle 过大 | React.lazy + Suspense 拆分编辑器/导图/导出模块 | 🟡 中 |
| **资源压缩** | JS/CSS 未充分压缩 | Vite 开启 `terser` + `brotli` + gzip | 🟡 中 |
| **图片懒加载** | 主题预览图阻塞首屏 | 主题缩略图使用 `loading="lazy"` + 低质量占位 | 🟢 低 |

---

## 二、用户体验优化

### 2.1 编辑体验

| 优化点 | 描述 | 方案 |
|--------|------|------|
| **自动补全** | Markdown 语法自动补全 | CodeMirror autocomplete 扩展 + 自定义快捷键插入模板 |
| **实时字数统计** | 编辑器底部显示字数/节点数 | 使用 CodeMirror State 的 `countColumn` 扩展 |
| **大纲导航** | 右侧浮动大纲快速跳转 | 解析标题生成大纲树，点击滚动到对应位置 |
| **焦点保持** | 点击导图节点后编辑器焦点丢失 | 点击导图时记住编辑器光标位置，可快速切回 |
| **代码块支持** | 节点内的代码片段渲染 | 解析 `` ``` `` 代码块，渲染为带语法高亮的子节点 |

### 2.2 导图交互

| 优化点 | 描述 | 方案 |
|--------|------|------|
| **平滑动画** | 折叠/展开动画生硬 | 使用 `d3.transition().ease(d3.easeCubicInOut)` 过渡 |
| **焦点居中** | 搜索结果节点不在可视区域 | `d3.zoom().transform` 动画移动到目标节点 + 高亮闪烁 |
| **多选操作** | 无法批量操作节点 | Shift+点击多选 → 右键批量删除/改色/折叠 |
| **小地图** | 大导图找不到位置 | 右下角 minimap 缩略图，框出当前视口 |
| **节点连线优化** | 交叉连线混乱 | 引入 `d3.tree().separation()` 优化间距，减少交叉 |
| **触摸支持** | 移动端无手势支持 | 双指缩放、单指拖拽、长按右键菜单 |

### 2.3 快捷键系统

```
Ctrl+S        → 保存为 .md 文件
Ctrl+Z        → 撤销
Ctrl+Y        → 重做
Ctrl+F        → 搜索节点
Ctrl+E        → 导出 PNG
Ctrl+Shift+E  → 导出 SVG
Ctrl++        → 放大
Ctrl+-        → 缩小
Ctrl+0        → 重置缩放 (100%)
Tab           → 增加缩进 (在编辑器中)
Shift+Tab     → 减少缩进
Ctrl+B        → **加粗** 选中文本
Ctrl+[        → 折叠当前节点
Ctrl+]        → 展开当前节点
Esc           → 取消选中 / 关闭弹窗
```

---

## 三、代码质量优化

### 3.1 架构层面

| 优化点 | 问题 | 方案 |
|--------|------|------|
| **分层解耦** | 解析、渲染、交互耦合在一起 | 严格按照 `parser → store → renderer` 单向数据流 |
| **错误边界** | 单组件崩溃导致白屏 | React Error Boundary 包裹编辑器/导图两个面板 |
| **类型安全** | any 类型滥用 | 开启 `strict: true`，禁止隐式 any |
| **测试覆盖** | 核心逻辑无测试 | parser / layout / export 单元测试覆盖率 > 80% |

### 3.2 代码规范

```typescript
// ✅ 推荐：纯函数 + 类型明确
function parseMarkdownToTree(markdown: string): TreeNode[] {
  const ast = remark.parse(markdown);
  return buildTree(ast);
}

// ❌ 避免：副作用 + any
function parse(data: any): any {
  store.markdown = data;  // 副作用
  return doParse(data);
}
```

### 3.3 状态管理优化

| 优化点 | 方案 |
|--------|------|
| 避免 prop-drilling | 使用 Zustand selector 精确订阅，减少不必要渲染 |
| 状态归一化 | TreeNode 使用 `{ [id]: node }` 扁平存储，children 存 ID 数组 |
| 操作原子化 | 折叠/展开/编辑等操作封装为 action，保证状态一致性 |

---

## 四、可访问性优化 (A11Y)

| 优化点 | 方案 |
|--------|------|
| 键盘导航 | 导图节点支持 Tab 切换、Enter 展开/折叠、方向键移动焦点 |
| ARIA 标签 | SVG 节点添加 `role="treeitem"`, `aria-expanded`, `aria-level` |
| 屏幕阅读器 | 提供文字版大纲视图作为 fallback |
| 色彩对比度 | 所有主题配色通过 WCAG AA 标准 (对比度 ≥ 4.5:1) |
| 焦点可见 | 键盘焦点时节点显示明显轮廓 (focus-visible) |

---

## 五、SEO & 可分享性优化

| 优化点 | 方案 |
|--------|------|
| **OG 标签** | 导图分享链接动态生成 `<meta og:image>` 缩略图 |
| **SSR 预览** | 分享页使用预渲染 (prerender.io 或 Vite SSG) |
| **URL 编码** | Markdown 内容 base64 编码到 URL hash (`#data=...`) |
| **复制链接** | 一键复制分享链接 + 导图缩略图 |

---

## 六、安全优化

| 优化点 | 风险 | 方案 |
|--------|------|------|
| **XSS 防护** | Markdown 中注入 `<script>` | remark 解析时使用 `sanitize` 插件过滤危险标签 |
| **CSP 策略** | 第三方 CDN 脚本风险 | 配置 Content-Security-Policy 头 |
| **文件上传** | 导入 .md 文件可能包含恶意内容 | 前端沙箱解析 + 文件大小限制 (5MB) |
| **依赖安全** | npm 包供应链攻击 | `npm audit` 定期扫描 + Dependabot 自动更新 |

---

## 七、优化优先级矩阵

```
                    影响大
                      │
         🟡 中优先    │    🔴 高优先
         ·动画优化    │    ·增量解析
         ·代码拆分    │    ·虚拟化渲染
         ·主题定制    │    ·Tree Shaking
         ·A11Y 优化   │    ·Web Worker
                      │
  ────────────────────────────────── 复杂度高
                      │
         🟢 低优先    │    🟡 中优先
         ·小地图      │    ·Canvas 切换
         ·SEO 优化    │    ·状态归一化
         ·分享链接    │    ·SSR 预览
                      │
                    影响小
```

---

## 八、性能指标目标

| 指标 | 优化前 (预估) | 优化后目标 | 测量工具 |
|------|:---:|:---:|------|
| FCP (首次内容绘制) | 2.5s | < 1.5s | Lighthouse |
| LCP (最大内容绘制) | 3.5s | < 2.0s | Lighthouse |
| TBT (总阻塞时间) | 500ms | < 200ms | Lighthouse |
| 解析 1000 行 MD | 300ms | < 100ms | Performance API |
| 渲染 500 节点 | 800ms | < 300ms | Performance API |
| 缩放 FPS | 20fps | ≥ 45fps | Chrome DevTools FPS |
| Bundle Size | 600KB | < 200KB (gzip) | `vite build --debug` |

---

> 📅 文档版本: v1.0  
> 📝 最后更新: 2026-06-22
