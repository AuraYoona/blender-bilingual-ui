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

- **Skip Untranslated**：两边都没翻译的条目不叠加
- **Skip Identical**：两种语言结果相同则不叠加
- **Skip Multiline**：跳过带换行的长 tooltip
- **Max Source Length**：超过该长度的源字符串忽略（默认 80）

**Apply to All UI Languages** 默认关掉。除非经常切换 Blender 界面语言，否则不要勾——给每种语言都生成一份又慢又占磁盘。

## 原理

Blender 5.x 查官方 UI 时**先读 `blender.mo`**，命中后不会再走 `bpy.app.translations.register()`。所以本插件直接写一份 catalog 覆盖：

1. 读取安装目录里的 `datafiles/locale/<locale>/LC_MESSAGES/blender.mo`
2. 把官方文件备份到用户目录 `datafiles/bilingual_ui/original_mo/`
3. 生成完整双语 `.mo`（未叠加的条目保留原文，避免掉回英文）
4. 写入用户目录 `datafiles/locale/<locale>/LC_MESSAGES/blender.mo`（该路径优先于安装目录，不改 Program Files）
5. 把它余语言用目录联接指回官方 catalog，避免用户 locale 根目录抢走查找路径后其它语言失效
6. 重新加载当前语言，让 Blender 再跑一次 `locale::init`

点 **Restore Original** 或禁用插件会去掉 overlay。生成过的 overlay 缓存在 `datafiles/bilingual_ui/cache/`，下次启动或切回同一对语言时直接复用。

部分 C 端写死、不走翻译系统的字符串无法覆盖。

## 兼容

- Blender 3.6+（`bl_info`）
- Blender 4.2+（`blender_manifest.toml`）
- 语言包随 Blender 安装走，先在偏好设置里启用对应语言再在这里选择

## 开发

```bash
python -m unittest tests.test_mo -q
python pack.py
```

`pack.py` 会在项目根目录写出 `bilingual_ui.zip`。

## 许可

[GPL-3.0-or-later](LICENSE)
