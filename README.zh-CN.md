# Bilingual UI

[English](README.md)

[![CI](https://github.com/AuraYoona/blender-bilingual-ui/actions/workflows/ci.yml/badge.svg)](https://github.com/AuraYoona/blender-bilingual-ui/actions/workflows/ci.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)

Blender 界面双语显示插件：任意两种官方语言可以同时出现在菜单和按钮上。

- 简体中文 + English → `缩放 (Scale)`
- 日本語 + 简体中文 → `スケール (缩放)`
- English + Français → `Scale (Échelle)`

Blender 自带的语言都能配对。前语言不必等于当前界面语言。

## 安装

从 [Releases](https://github.com/AuraYoona/blender-bilingual-ui/releases) 下载 `bilingual_ui.zip`。

**Blender 4.2+**

1. `编辑 > 偏好设置 > 扩展 > 从磁盘安装`
2. 启用 **Bilingual UI**

**Blender 3.6 – 4.1**

1. `编辑 > 偏好设置 > 插件 > 安装…`
2. 启用 **Bilingual UI**

3D 视图侧栏会出现 **Bilingual** 面板，完整选项在插件偏好设置里。

## 用法

1. 打开插件偏好设置
2. 选 **Front Language**（显示在前面的语言）
3. 选 **Back Language**（显示在后面的语言）
4. 点 **Apply Bilingual UI**

顶栏右侧会出现一个小开关（例如 `简+EN`）：

- **单击**循环：前语言 → 后语言 → 双语
- **小三角**打开面板，改前后语言和格式
- **Shift+单击**开关同样打开该面板

Blender 自己的界面语言可以保持不变。双语写进当前 UI 正在加载的 catalog。

### 模式

| 模式 | 行为 |
| --- | --- |
| Fixed Pair（默认） | 自己选两种语言。界面可以是中文，标签却显示 `スケール (Scale)` |
| Follow UI Language | 前语言跟随 Blender 界面语言，后语言是你选的 Back Language |

### 格式

- `A (B)` → `缩放 (Scale)`
- `B (A)` → `Scale (缩放)`
- `A / B` → `缩放 / Scale`
- `A B` → `缩放 Scale`
- `A [B]` → `缩放 [Scale]`
- `A — B` → `缩放 — Scale`

### 过滤器

- **Skip Multiline**：带换行的长 tooltip 只保留一种语言
- **Max Source Length**：超过该长度的源字符串不叠加（默认 80）

被过滤的条目保留原译文，不会掉回英文。

## 兼容

- Blender 3.6+（`bl_info`）
- Blender 4.2+（`blender_manifest.toml`）
- 语言包随 Blender 安装走，先在偏好设置里启用对应语言再在这里选择

## 许可

[GPL-3.0-or-later](LICENSE)
