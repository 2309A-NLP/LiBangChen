# Markdown 兼容思维导图 — 设计文档

## 一、项目概述

### 1.1 项目名称
**MindMark** — 基于 Markdown 的在线思维导图工具

### 1.2 项目定位
一款支持 Markdown 语法编辑、实时渲染为交互式思维导图的 Web 应用。用户输入 Markdown 层级文本，左侧编辑、右侧实时生成可拖拽、缩放、折叠的思维导图。

### 1.3 核心价值
- **零学习成本**：用 Markdown 标题语法（`#` `##` `###`）表达层级结构
- **所见即所得**：编辑与导图实时双向同步
- **跨平台**：纯 Web 应用，浏览器即用，无需安装

---

## 二、功能需求

### 2.1 核心功能 (MVP)

| 模块 | 功能 | 描述 |
|------|------|------|
| Markdown 编辑器 | 语法高亮 | 支持 `#` ~ `######` 标题、无序列表 `-`、有序列表 `1.` |
| 思维导图渲染 | 层级树布局 | 根据标题层级自动生成辐射状/树状布局 |
| 交互操作 | 拖拽平移 | 鼠标拖拽画布平移视图 |
| 交互操作 | 滚轮缩放 | 滚轮缩放导图大小 (10% ~ 300%) |
| 交互操作 | 节点折叠 | 点击节点折叠/展开子节点 |
| 导出 | PNG 导出 | 导图区域截图导出 |
| 导出 | SVG 导出 | 矢量图导出 |
| 导出 | MD 导出 | 还原为 Markdown 文本 |

### 2.2 进阶功能 (V2)

| 模块 | 功能 | 描述 |
|------|------|------|
| 编辑器 | 实时预览同步 | 编辑时导图实时更新 (debounce 300ms) |
| 主题 | 多套配色 | 提供 5+ 预设主题，支持自定义配色 |
| 节点编辑 | 双击编辑 | 双击节点直接修改文字 |
| 节点编辑 | 拖拽调整 | 拖拽节点改变父子关系 |
| 导入 | 文件导入 | 支持导入 `.md` 文件 |
| 历史 | 撤销/重做 | Ctrl+Z / Ctrl+Y 操作历史 |

### 2.3 高级功能 (V3)

| 模块 | 功能 | 描述 |
|------|------|------|
| 协作 | 分享链接 | 生成只读分享链接 |
| 存储 | 云端存储 | 用户登录后云端保存 |
| 模板 | 导图模板 | 提供项目规划、读书笔记等模板 |
| 搜索 | 节点搜索 | Ctrl+F 搜索并高亮定位节点 |

---

## 三、技术架构

### 3.1 技术选型

```
┌─────────────────────────────────────────────┐
│                   前端 (SPA)                  │
│  ┌───────────┐  ┌──────────┐  ┌───────────┐ │
│  │ 编辑器面板 │  │ 导图画布  │  │  工具栏    │ │
│  │ CodeMirror│  │  D3.js   │  │  Toolbar  │ │
│  └───────────┘  └──────────┘  └───────────┘ │
│         │              │             │        │
│         └──────────────┼─────────────┘        │
│                ┌───────┴───────┐              │
│                │  状态管理      │              │
│                │  Zustand      │              │
│                └───────┬───────┘              │
│                ┌───────┴───────┐              │
│                │  MD 解析器     │              │
│                │  unified +     │              │
│                │  remark       │              │
│                └───────────────┘              │
└─────────────────────────────────────────────┘
```

| 层 | 技术 | 说明 |
|----|------|------|
| 框架 | **React 18** + TypeScript | 组件化开发，类型安全 |
| 构建 | **Vite 5** | 极速 HMR，ESBuild 打包 |
| Markdown 解析 | **unified + remark-parse** | AST 解析，精确提取标题层级 |
| 思维导图渲染 | **D3.js v7** | SVG 渲染，力导向/树布局 |
| 代码编辑器 | **CodeMirror 6** | 轻量、可扩展的 Markdown 编辑器 |
| 状态管理 | **Zustand** | 轻量、无 boilerplate |
| 样式 | **Tailwind CSS** | 原子化 CSS，快速开发 |
| 导出 | **html-to-image** + **file-saver** | PNG/SVG 导出 |

### 3.2 备选方案对比

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| **markmap 直接使用** | 开箱即用、成熟 | 定制性差、不可控 | ❌ 不适合深度定制 |
| **ECharts 树图** | 生态好、中文友好 | 思维导图定制弱 | ❌ |
| **D3.js 自研** | 完全可控、任意定制 | 开发量大 | ✅ 最佳选择 |
| **Canvas (Konva)** | 性能好、适合大量节点 | SVG 导出麻烦 | 备选 |

---

## 四、核心模块设计

### 4.1 Markdown 解析模块 (`parser.ts`)

```
输入: Markdown 文本
  │
  ▼
remark-parse → MDAST (Markdown AST)
  │
  ▼
自定义遍历器 → TreeNode[]
  │
  ▼
输出: 树形节点数据
```

**TreeNode 数据结构：**

```typescript
interface TreeNode {
  id: string;              // 唯一标识 (nanoid)
  label: string;           // 节点文本 (去除 # 标记)
  level: number;           // 层级深度 0=根节点
  children: TreeNode[];    // 子节点
  collapsed: boolean;      // 是否折叠
  meta?: {
    hasList: boolean;      // 是否包含列表
    listItems: string[];   // 列表项 (挂为子节点)
    emphasis: boolean;     // 是否加粗
    tags: string[];        // 标签 #tag
  };
}
```

**解析规则：**

| Markdown | AST Type | 映射 |
|----------|----------|------|
| `# 标题` | heading(depth=1) | 根节点 |
| `## 二级` | heading(depth=2) | 一级子节点 |
| `### 三级` | heading(depth=3) | 二级子节点 |
| `- 列表项` | list + listItem | 挂载到最近标题 |
| `**加粗**` | strong | meta.emphasis = true |
| `#tag` | text | meta.tags.push |

### 4.2 思维导图渲染模块 (`renderer.ts`)

**布局算法：**

采用 **右侧树形布局 (Right-side Tree Layout)**：

```
           ┌── 子节点1 ── 孙节点1
根节点 ────┼── 子节点2 ── 孙节点2
           └── 子节点3
```

核心参数：
- 节点宽度：`120px` (最小)，动态根据文本长度计算
- 节点高度：`40px`
- 水平间距：`80px`
- 垂直间距：`20px`
- 圆角半径：`8px`

**渲染流程：**

```
1. 计算布局 → d3.tree().nodeSize([nodeHeight, nodeWidth])
2. 生成路径 → d3.linkHorizontal() 贝塞尔曲线连线
3. 渲染节点 → SVG <g> 分组 (rect + text)
4. 绑定事件 → click(折叠) / dblclick(编辑) / drag(调整)
5. 动画过渡 → d3.transition().duration(300)
```

**SVG 结构：**

```xml
<svg id="mindmap">
  <defs>
    <marker id="arrow">...</marker>  <!-- 连线箭头 -->
    <filter id="shadow">...</filter> <!-- 节点阴影 -->
  </defs>
  <g class="links">
    <path class="link" d="M...C..." />  <!-- 连线 -->
  </g>
  <g class="nodes">
    <g class="node" transform="translate(x,y)">
      <rect rx="8" ... />              <!-- 节点背景 -->
      <text>节点文字</text>             <!-- 节点文本 -->
      <circle class="collapse-btn" />  <!-- 折叠按钮 -->
    </g>
  </g>
</svg>
```

### 4.3 编辑器模块 (`Editor.tsx`)

**CodeMirror 6 配置：**

```typescript
import { EditorView, keymap } from '@codemirror/view';
import { markdown } from '@codemirror/lang-markdown';
import { oneDark } from '@codemirror/theme-one-dark';

const extensions = [
  markdown(),                    // Markdown 语言支持
  oneDark,                       // 暗色主题
  EditorView.lineWrapping,       // 自动换行
  keymap.of([                    // 快捷键
    { key: 'Ctrl-s', run: () => { saveFile(); return true; } }
  ])
];
```

**实时同步机制：**

```
Editor onChange (debounce 300ms)
  → 更新 Store 中的 markdownText
  → parser(markdownText) → TreeNode[]
  → renderer(TreeNode[]) → 更新 SVG
```

### 4.4 交互模块 (`interaction.ts`)

| 交互 | 实现方式 | 技术细节 |
|------|---------|---------|
| 画布拖拽 | `d3.zoom()` | 绑定到 SVG，限制缩放范围 |
| 节点折叠 | `node.on('click')` | 切换 `collapsed`，重新计算布局 |
| 节点悬停 | CSS `:hover` + tooltip | 显示完整文本 (截断时) |
| 右键菜单 | `contextmenu` 事件 | 新增/删除/编辑子节点 |
| 键盘导航 | 方向键 | ↑↓ 切换焦点节点，←→ 折叠/展开 |

### 4.5 导出模块 (`export.ts`)

| 导出格式 | 实现方法 |
|---------|---------|
| **PNG** | `html-to-image` → `toPng(svgElement)` → `file-saver` 下载 |
| **SVG** | 序列化 SVG DOM → `new Blob([svgString])` → 下载 |
| **Markdown** | 从 `TreeNode[]` 反向生成 MD 文本 → 下载 `.md` |
| **PDF** | 先转 PNG → jsPDF 封装 → 下载 (V2) |

---

## 五、数据流设计

```
                  ┌──────────────┐
                  │   Zustand    │
                  │   Store      │
                  └──────┬───────┘
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
  ┌──────────┐   ┌──────────────┐   ┌──────────┐
  │ Editor   │   │  MindMap     │   │ Toolbar  │
  │ 组件     │   │  组件        │   │ 组件     │
  └────┬─────┘   └──────┬───────┘   └────┬─────┘
       │                │                │
       ▼                ▼                ▼
  markdownText     treeData          actions
  (string)         (TreeNode[])      (export/undo)
```

**Zustand Store 设计：**

```typescript
interface MindMapStore {
  // 状态
  markdownText: string;
  treeData: TreeNode[];
  selectedNodeId: string | null;
  scale: number;
  theme: Theme;
  history: { past: string[]; future: string[] };

  // 操作
  setMarkdownText: (text: string) => void;
  parseToTree: () => void;
  toggleCollapse: (nodeId: string) => void;
  setScale: (scale: number) => void;
  setTheme: (theme: Theme) => void;
  undo: () => void;
  redo: () => void;
  exportPNG: () => void;
  exportSVG: () => void;
  exportMD: () => void;
}
```

---

## 六、界面布局

```
┌──────────────────────────────────────────────────┐
│  🌳 MindMark             主题 ▼  导出 ▼  撤销 重做│  ← 顶栏
├────────────────┬─────────────────────────────────┤
│                │                                 │
│  Markdown      │      思维导图 SVG 画布            │
│  编辑器        │                                 │
│  (40% 宽度)    │      (可拖拽、缩放)               │
│                │                                 │
│  # 根节点      │         ┌── 子节点1              │
│  ## 子节点1    │  根节点 ─┤                       │
│  ### 孙节点    │         └── 子节点2              │
│  ## 子节点2    │                                 │
│                │                                 │
│                │                                 │
├────────────────┴─────────────────────────────────┤
│  💡 提示: 滚轮缩放 | 拖拽平移 | 点击折叠 | Ctrl+S 保存 │  ← 状态栏
└──────────────────────────────────────────────────┘
```

---

## 七、主题系统

### 预设主题配色

| 主题名 | 根节点 | 一级 | 二级 | 连线 | 背景 |
|--------|--------|------|------|------|------|
| 默认蓝 | `#3B82F6` | `#60A5FA` | `#93C5FD` | `#94A3B8` | `#F8FAFC` |
| 暗夜 | `#6366F1` | `#818CF8` | `#A5B4FC` | `#64748B` | `#1E293B` |
| 森林 | `#059669` | `#34D399` | `#6EE7B7` | `#78716C` | `#F0FDF4` |
| 日落 | `#EA580C` | `#F97316` | `#FB923C` | `#A8A29E` | `#FFF7ED` |
| 紫韵 | `#7C3AED` | `#8B5CF6` | `#A78BFA` | `#9CA3AF` | `#FAF5FF` |

### 自定义主题

```typescript
interface Theme {
  name: string;
  rootColor: string;
  levelColors: string[];    // 按层级着色
  linkColor: string;
  backgroundColor: string;
  fontFamily: string;
  fontSize: number;
  nodeRadius: number;
  lineStyle: 'curve' | 'straight' | 'step';
}
```

---

## 八、项目目录结构

```
mindmark/
├── public/
│   └── favicon.svg
├── src/
│   ├── main.tsx                    # 入口
│   ├── App.tsx                     # 根组件
│   ├── components/
│   │   ├── Editor/
│   │   │   ├── Editor.tsx          # Markdown 编辑器
│   │   │   └── Editor.css
│   │   ├── MindMap/
│   │   │   ├── MindMap.tsx         # 导图 SVG 容器
│   │   │   ├── Node.tsx            # 单节点组件
│   │   │   ├── Link.tsx            # 连线组件
│   │   │   └── MindMap.css
│   │   ├── Toolbar/
│   │   │   └── Toolbar.tsx         # 顶部工具栏
│   │   └── StatusBar/
│   │       └── StatusBar.tsx       # 底部状态栏
│   ├── core/
│   │   ├── parser.ts               # MD → AST → TreeNode
│   │   ├── layout.ts               # D3 布局计算
│   │   ├── renderer.ts             # D3 SVG 渲染
│   │   ├── interaction.ts          # 缩放、拖拽、折叠
│   │   └── export.ts               # PNG/SVG/MD 导出
│   ├── store/
│   │   └── useMindMapStore.ts      # Zustand Store
│   ├── theme/
│   │   ├── themes.ts               # 预设主题
│   │   └── useTheme.ts             # 主题 hook
│   ├── types/
│   │   └── index.ts                # 类型定义
│   └── utils/
│       ├── debounce.ts
│       └── id.ts
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
└── README.md
```

---

## 九、关键算法

### 9.1 Markdown → TreeNode 解析算法

```
function parseMarkdownToTree(md: string): TreeNode[] {
  1. 使用 remark-parse 将 md 解析为 AST
  2. 遍历 AST 节点，维护一个 levelStack 栈
  3. 遇到 heading 节点：
     a. 创建 TreeNode
     b. 根据 depth 找到正确的父节点 (栈中 depth < 当前 depth 的最近节点)
     c. 将新节点 push 到父节点的 children
     d. 更新栈 (pop 掉所有 depth >= 当前 depth 的节点，push 当前节点)
  4. 遇到 list 节点：
     a. 将 listItem 创建为 TreeNode
     b. 挂载到栈顶节点下
  5. 返回根节点数组 (depth=1 的节点)
}
```

### 9.2 布局坐标计算

```
function computeLayout(root: TreeNode, containerWidth, containerHeight) {
  1. 使用 d3.hierarchy(root) 创建层级结构
  2. treeLayout = d3.tree()
       .nodeSize([nodeHeight + gap, nodeWidth + gap])
       .separation((a, b) => (a.parent === b.parent ? 1 : 1.5))
  3. treeLayout(rootHierarchy)
  4. 每个节点获得 x, y 坐标
  5. 返回带坐标的节点数组
}
```

---

## 十、非功能性需求

| 指标 | 目标值 |
|------|--------|
| 首屏加载 | < 2s (gzip 后 < 200KB) |
| 解析性能 | 1000 行 MD < 100ms |
| 渲染性能 | 500 节点 < 500ms |
| 缩放帧率 | ≥ 30fps |
| 兼容性 | Chrome 90+, Firefox 90+, Edge 90+, Safari 15+ |
| 响应式 | 支持 1024px ~ 4K 分辨率 |

---

## 十一、开发计划

| 阶段 | 周期 | 内容 |
|------|------|------|
| **P0 - 基础搭建** | 第 1 周 | 项目脚手架、Vite + React + Tailwind 配置 |
| **P1 - 核心解析** | 第 1 周 | Markdown 解析器、TreeNode 数据结构 |
| **P2 - 导图渲染** | 第 2 周 | D3.js 集成、树布局、SVG 节点渲染 |
| **P3 - 交互实现** | 第 2-3 周 | 缩放、拖拽、折叠、双击编辑 |
| **P4 - 编辑器** | 第 3 周 | CodeMirror 集成、实时同步 |
| **P5 - 导出功能** | 第 4 周 | PNG/SVG/MD 导出 |
| **P6 - 主题系统** | 第 4 周 | 预设主题、自定义主题 |
| **P7 - 测试优化** | 第 5 周 | 单元测试、E2E 测试、性能优化 |
| **P8 - 部署上线** | 第 5 周 | CI/CD、静态部署 |

---

> 📅 文档版本: v1.0  
> 📝 最后更新: 2026-06-22  
> 👤 作者: MindMark Team
