# Bilingual UI

[中文说明](README.zh-CN.md)

[![CI](https://github.com/AuraYoona/blender-bilingual-ui/actions/workflows/ci.yml/badge.svg)](https://github.com/AuraYoona/blender-bilingual-ui/actions/workflows/ci.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)

Blender add-on that shows the interface in two languages at once.

- Simplified Chinese + English → `缩放 (Scale)`
- Japanese + Simplified Chinese → `スケール (缩放)`
- English + French → `Scale (Échelle)`

Any pair of languages shipped with Blender works. The front language does not have to match the current UI language.

## Install

Download `bilingual_ui.zip` from [Releases](https://github.com/AuraYoona/blender-bilingual-ui/releases).

**Blender 4.2+**

1. `Edit > Preferences > Extensions > Install from Disk`
2. Enable **Bilingual UI**

**Blender 3.6 – 4.1**

1. `Edit > Preferences > Add-ons > Install…`
2. Enable **Bilingual UI**

A **Bilingual** tab appears in the 3D View sidebar. Full options live in the add-on preferences.

## Usage

1. Open the add-on preferences
2. Pick **Front Language** (shown first)
3. Pick **Back Language** (shown second)
4. Click **Apply Bilingual UI**

A compact switch appears on the right of the top bar (for example `简+EN`):

- **Click** cycles Front → Back → Both
- **Arrow** opens a popup to change languages and format
- **Shift-click** the switch also opens that popup

Blender’s own UI language can stay as it is. The overlay is written into the catalog the current UI is loading.

### Modes

| Mode | Behaviour |
| --- | --- |
| Fixed Pair (default) | You choose both languages. The UI can stay Chinese while labels show `スケール (Scale)` |
| Follow UI Language | Front language tracks Blender’s UI language; back language is the one you picked |

### Format

- `A (B)` → `缩放 (Scale)`
- `B (A)` → `Scale (缩放)`
- `A / B` → `缩放 / Scale`
- `A B` → `缩放 Scale`
- `A [B]` → `缩放 [Scale]`
- `A — B` → `缩放 — Scale`

### Filters

- **Skip Multiline** — leave tooltips with line breaks in one language
- **Max Source Length** — leave source strings longer than this alone (default 80)

Filtered entries keep their original translation, so nothing falls back to English.

## Compatibility

- Blender 3.6+ (`bl_info`)
- Blender 4.2+ (`blender_manifest.toml`)
- Language packs come with Blender; enable a language in Preferences before selecting it here

## License

[GPL-3.0-or-later](LICENSE)

## https://linux.do/
