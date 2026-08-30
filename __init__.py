# SPDX-License-Identifier: GPL-3.0-or-later
"""Bilingual UI — overlay a second language on Blender's interface."""

from __future__ import annotations

import importlib
import os
import sys

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import AddonPreferences, Operator, Panel


def _load_catalogs():
    """Import core.py, reloading it if a previous enable left it in sys.modules.

    Do not delete the module first — Blender 5.2's extension loader may not
    put the submodule back into sys.modules before importlib.reload() runs.
    """
    pkg = __name__
    catalogs_name = pkg + ".catalogs"
    if catalogs_name in sys.modules:
        del sys.modules[catalogs_name]
    name = pkg + ".core"
    existing = sys.modules.get(name)
    if existing is not None:
        try:
            return importlib.reload(existing)
        except Exception:
            pass
    from . import core as _core
    return _core


core = _load_catalogs()

bl_info = {
    "name": "Bilingual UI",
    "author": "AuraYoona",
    "version": (1, 4, 0),
    "blender": (3, 6, 0),
    "location": "Preferences > Add-ons > Bilingual UI",
    "description": "Show Blender's UI in two languages at once (any official locale pair)",
    "category": "Interface",
    "doc_url": "https://github.com/AuraYoona/blender-bilingual-ui",
}

ADDON_ID = __name__
_registered = False
_last_locale = ""
_status = "Idle"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

_locale_items_cache = None


def _locale_items(self, context):
    # Blender requires the returned enum tuples to stay alive.
    global _locale_items_cache
    items = []
    for code, label, _mo in core.discover_locales():
        items.append((code, f"{label} ({code})", label))
    if not items:
        items = [("en_US", "English (en_US)", "English")]
    _locale_items_cache = items
    return items


STYLE_ITEMS = (
    ("A_PAREN_B", "A (B)", "Front language, then back language in parentheses"),
    ("B_PAREN_A", "B (A)", "Back language, then front language in parentheses"),
    ("A_SLASH_B", "A / B", "Front / back, separated by a slash"),
    ("A_SPACE_B", "A B", "Front then back, separated by a space"),
    ("A_BRACKET_B", "A [B]", "Front language, then back language in brackets"),
    ("A_DASH_B", "A — B", "Front — back, separated by an em dash"),
)

MODE_ITEMS = (
    ("FOLLOW_UI", "Follow UI Language", "Front language tracks Blender's current UI language"),
    ("FIXED", "Fixed Pair", "Always use the two languages chosen below"),
)

DISPLAY_ITEMS = (
    ("FRONT", "Front", "Show only the front language"),
    ("BACK", "Back", "Show only the back language"),
    ("BILINGUAL", "Both", "Show front and back together"),
)

DISPLAY_ORDER = ("FRONT", "BACK", "BILINGUAL")


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

class BilingualPreferences(AddonPreferences):
    bl_idname = ADDON_ID

    enabled: BoolProperty(
        name="Enable Bilingual UI",
        description="Write bilingual catalogs over Blender's interface translations",
        default=True,
        update=lambda self, context: _on_enable_changed(),
    )

    mode: EnumProperty(
        name="Mode",
        description="How the front language is chosen",
        items=MODE_ITEMS,
        default="FIXED",
    )

    language_a: EnumProperty(
        name="Front Language",
        description="Language shown first in the bilingual string",
        items=_locale_items,
        update=lambda self, context: _on_pair_changed(),
    )

    language_b: EnumProperty(
        name="Back Language",
        description="Language shown second (typically English)",
        items=_locale_items,
        default=0,
        update=lambda self, context: _on_pair_changed(),
    )

    display_mode: EnumProperty(
        name="Display",
        description="Front only, back only, or both languages",
        items=DISPLAY_ITEMS,
        default="BILINGUAL",
        update=lambda self, context: _on_display_changed(),
    )

    show_header_switch: BoolProperty(
        name="Show Header Switch",
        description="Show the Front / Back / Both switch in the top bar",
        default=True,
    )

    style: EnumProperty(
        name="Format",
        description="How the two languages are combined",
        items=STYLE_ITEMS,
        default="A_PAREN_B",
    )

    apply_all_locales: BoolProperty(
        name="Apply to All UI Languages",
        description=(
            "Write the same Front+Back pair into every installed locale folder. "
            "Leave off unless you switch Blender's UI language often — it is much slower"
        ),
        default=False,
    )

    skip_untranslated: BoolProperty(
        name="Skip Untranslated",
        description="Do not overlay strings that have no translation in either language",
        default=True,
    )

    skip_identical: BoolProperty(
        name="Skip Identical",
        description="Do not overlay when both languages produce the same text",
        default=True,
    )

    skip_multiline: BoolProperty(
        name="Skip Multiline",
        description="Ignore tooltips and other strings that contain line breaks",
        default=True,
    )

    max_length: IntProperty(
        name="Max Source Length",
        description="Ignore source strings longer than this (0 = no limit). Helps skip long tooltips",
        default=80,
        min=0,
        max=2000,
    )

    auto_refresh: BoolProperty(
        name="Auto Refresh on Language Change",
        description="Rebuild bilingual strings when Blender's UI language changes",
        default=True,
    )

    rename_workspaces: BoolProperty(
        name="Rename Workspace Tabs",
        description=(
            "Also rename the workspace data-blocks (Layout, Modeling, …). "
            "Blender translates those names when a file loads, so the tabs "
            "cannot follow a catalog swap on their own"
        ),
        default=True,
    )

    last_report: StringProperty(
        name="Last Report",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        header = layout.row()
        header.prop(self, "enabled", toggle=True)

        col = layout.column()
        col.enabled = self.enabled

        box = col.box()
        box.label(text="Languages", icon="WORLD")
        box.prop(self, "mode", expand=True)

        split = box.split(factor=0.5)
        left = split.column()
        right = split.column()
        left.enabled = self.mode != "FOLLOW_UI"
        left.prop(self, "language_a")
        right.prop(self, "language_b")
        if self.mode == "FOLLOW_UI":
            box.label(text=f"Front follows UI language: {_label_for(core.current_locale())}")

        row = box.row()
        row.operator(BILINGUAL_OT_swap.bl_idname, icon="ARROW_LEFTRIGHT")
        row.operator(BILINGUAL_OT_reload_locales.bl_idname, icon="FILE_REFRESH")

        box = col.box()
        box.label(text="Display", icon="FONTPREVIEW")
        box.prop(self, "style", expand=False)
        preview = _preview_text(self)
        if preview:
            box.label(text=f"Preview:  {preview}", icon="HIDE_OFF")
        box.prop(self, "display_mode", expand=True)
        box.prop(self, "apply_all_locales")
        box.prop(self, "auto_refresh")
        box.prop(self, "show_header_switch")
        box.prop(self, "rename_workspaces")

        box = col.box()
        box.label(text="Filters", icon="FILTER")
        box.prop(self, "skip_untranslated")
        box.prop(self, "skip_identical")
        box.prop(self, "skip_multiline")
        box.prop(self, "max_length")

        col.label(text="Changing options does not apply until you click Apply.")
        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator(BILINGUAL_OT_apply.bl_idname, icon="CHECKMARK")
        row.operator(BILINGUAL_OT_clear.bl_idname, icon="X")

        status_box = col.box()
        status_box.label(text=f"Status: {_status}", icon="INFO")
        if self.last_report:
            for line in self.last_report.split("\n"):
                status_box.label(text=line)


def _prefs() -> BilingualPreferences | None:
    addon = bpy.context.preferences.addons.get(ADDON_ID)
    if addon is None:
        return None
    return addon.preferences


def _label_for(code: str) -> str:
    for loc, label, _mo in core.discover_locales():
        if loc == code:
            return label
    return core.LOCALE_NAMES.get(code, code)


def _preview_text(prefs: BilingualPreferences) -> str:
    # Do not parse .mo files just to draw preferences — that stalls the UI.
    front, back = _pair_from_prefs(prefs)
    display = getattr(prefs, "display_mode", "BILINGUAL")
    a = core.short_label(front)
    b = core.short_label(back)
    if display == "FRONT":
        return a
    if display == "BACK":
        return b
    return core.format_pair(a, b, prefs.style)


def _header_label(prefs) -> str:
    if prefs is None or not prefs.enabled:
        return "Off"
    front, back = _pair_from_prefs(prefs)
    a = core.short_label(front)
    b = core.short_label(back)
    display = getattr(prefs, "display_mode", "BILINGUAL")
    if display == "FRONT":
        return a
    if display == "BACK":
        return b
    return f"{a}+{b}"


# ---------------------------------------------------------------------------
# Apply / clear
# ---------------------------------------------------------------------------

def apply_bilingual(report=None) -> str:
    global _status, _last_locale, _registered
    prefs = _prefs()
    if prefs is None:
        _status = "Preferences unavailable"
        return _status

    if not prefs.enabled:
        if prefs.rename_workspaces:
            core.restore_workspace_names(core.current_locale())
        restore = core.restore_overlays()
        _registered = False
        _status = (
            f"Disabled · restored {restore.get('restored', 0)} official catalogs, "
            f"removed {restore.get('removed', 0)} overlays"
        )
        prefs.last_report = _status
        return _status

    front, back = _pair_from_prefs(prefs)
    display = getattr(prefs, "display_mode", "BILINGUAL")

    if display == "BILINGUAL" and front == back:
        _status = "Front and back languages are the same — nothing to overlay"
        prefs.last_report = _status
        return _status

    current = core.current_locale()

    def progress(msg: str):
        if report:
            report({"INFO"}, msg)

    targets = _write_targets(prefs, front, back)
    if not targets:
        _status = (
            "English has no translation catalog. Pick a non-English Front or Back language."
        )
        prefs.last_report = _status
        return _status
    fingerprint = core.overlay_fingerprint(
        front,
        back,
        display,
        prefs.style,
        prefs.skip_untranslated,
        prefs.skip_identical,
        prefs.skip_multiline,
        prefs.max_length,
        prefs.apply_all_locales,
        targets,
    )

    if _cached_mo_ready(fingerprint):
        host = targets[0]
        if core.swap_overlay_files(fingerprint, targets):
            if core.canonical_locale(core.current_locale()) != core.canonical_locale(host):
                core.set_ui_language(host)
            if prefs.rename_workspaces:
                core.sync_workspace_names(
                    fingerprint=fingerprint, official_locale=host
                )
            _registered = True
            _last_locale = core.current_locale()
            _status = _format_status(display, front, back, cached=True)
            prefs.last_report = _status
            _schedule_warmup(prefs, front, back, targets)
            return _status

    cached_mo = core.cached_overlay_path(fingerprint)
    catalog = None
    stats = {"emitted": 0, "kept": 0}
    if cached_mo and os.path.isfile(cached_mo):
        catalog = core.load_cached_overlay(fingerprint)
        if catalog:
            stats["emitted"] = len(catalog)
            progress(f"Reusing cached overlay {fingerprint}")

    if catalog is None:
        _status = "Building…"
        items, stats = _build_overlay_items(prefs, front, back, progress)
        if not items:
            if display != "BILINGUAL":
                source = front if display == "FRONT" else back
                restore = core.restore_overlays()
                _registered = False
                _status = f"Active [{display}]: {_label_for(source)} (official catalog)"
                prefs.last_report = _status
                return _status
            _status = (
                f"No bilingual strings built for {front} + {back}. "
                "Check that .mo catalogs exist for at least one of the two languages."
            )
            prefs.last_report = _status
            return _status
        catalog = items[0][1]
        core.store_overlay_cache(fingerprint, catalog)
        cached_mo = core.cached_overlay_path(fingerprint)
    else:
        items = [(loc, catalog) for loc in targets]

    written = core.install_overlays(
        items, progress=progress, fingerprint=fingerprint, cache_mo=cached_mo or ""
    )
    if prefs.rename_workspaces:
        core.sync_workspace_names(
            fingerprint=fingerprint,
            catalog=catalog,
            official_locale=targets[0] if targets else front,
        )
    _registered = True
    _last_locale = core.current_locale()
    _status = _format_status(
        display, front, back, stats=stats, written=written, cached=bool(catalog)
    )
    prefs.last_report = _status
    _schedule_warmup(prefs, front, back, targets)
    return _status


def _format_status(display, front, back, stats=None, written=None, cached=False) -> str:
    tag = {"FRONT": "Front", "BACK": "Back", "BILINGUAL": "Both"}.get(display, display)
    pair = (
        _label_for(front)
        if display == "FRONT"
        else _label_for(back)
        if display == "BACK"
        else f"{_label_for(front)} + {_label_for(back)}"
    )
    extra = "cached" if cached and not (stats and stats.get("emitted")) else ""
    if stats:
        extra = (
            f"{stats.get('emitted', 0)} strings / {stats.get('kept', 0)} kept"
            + (f"  ·  {written.get('locales', 0)} locale(s)" if written else "")
        )
        if cached and written and written.get("user_written"):
            extra += "  ·  from cache"
    elif cached:
        extra = "already applied"
    return f"Active [{tag}]: {pair}  ·  {extra}"


def _pair_from_prefs(prefs):
    if prefs.mode == "FOLLOW_UI":
        front = core.current_locale()
    else:
        front = prefs.language_a or core.current_locale()
    back = prefs.language_b or "en_US"
    return front, back


def _write_targets(prefs, front: str, back: str = "") -> list[str]:
    """Folders Blender will actually load.

    English has no blender.mo. If the UI is English, host the overlay in the
    first non-English language of the pair and switch the UI to that locale.
    """
    if prefs.apply_all_locales:
        targets = [code for code, _label, mo in core.discover_locales() if mo]
        current = core.current_locale()
        if current not in targets and not core.is_english(current):
            targets.append(current)
        if front not in targets and not core.is_english(front):
            targets.append(front)
        return [t for t in targets if not core.is_english(t)]

    current = core.current_locale()
    if not core.is_english(current) and core.overlay_folders_for(current):
        return [current]
    host = core.pick_host_locale(front, back, current)
    if host:
        if core.canonical_locale(current) != host:
            core.set_ui_language(host)
        return [host]
    return []


def _build_overlay_items(prefs, front: str, back: str, progress):
    targets = _write_targets(prefs, front, back)
    items = []
    totals = {"emitted": 0, "kept": 0, "locales": 0}
    display = getattr(prefs, "display_mode", "BILINGUAL")
    current = core.current_locale()

    if display == "FRONT":
        catalog, stats = core.build_mono_catalog(front, seed_locale=current, progress=progress)
    elif display == "BACK":
        catalog, stats = core.build_mono_catalog(back, seed_locale=current, progress=progress)
    else:
        catalog, stats = core.build_full_catalog(
            front,
            back,
            prefs.style,
            skip_untranslated=prefs.skip_untranslated,
            skip_identical=prefs.skip_identical,
            skip_multiline=prefs.skip_multiline,
            max_length=prefs.max_length,
            progress=progress,
        )
    if not catalog:
        return items, totals
    for loc in targets:
        items.append((loc, catalog))
    totals["emitted"] = stats["emitted"]
    totals["kept"] = stats.get("kept", 0)
    totals["locales"] = len(items)
    return items, totals


def _cached_mo_ready(fingerprint: str) -> bool:
    path = core.cached_overlay_path(fingerprint)
    return bool(path and os.path.isfile(path))


_warmup_job = None


def _schedule_warmup(prefs, front: str, back: str, targets):
    """Build Front/Back/Both overlay files in the background after a successful apply."""
    global _warmup_job
    pending = []
    for mode in DISPLAY_ORDER:
        fp = core.overlay_fingerprint(
            front,
            back,
            mode,
            prefs.style,
            prefs.skip_untranslated,
            prefs.skip_identical,
            prefs.skip_multiline,
            prefs.max_length,
            prefs.apply_all_locales,
            targets,
        )
        if not _cached_mo_ready(fp):
            pending.append(mode)
    if not pending:
        return
    _warmup_job = {
        "front": front,
        "back": back,
        "targets": list(targets),
        "pending": pending,
        "style": prefs.style,
        "skip_untranslated": prefs.skip_untranslated,
        "skip_identical": prefs.skip_identical,
        "skip_multiline": prefs.skip_multiline,
        "max_length": prefs.max_length,
        "apply_all": prefs.apply_all_locales,
    }
    if not bpy.app.timers.is_registered(_warmup_step):
        bpy.app.timers.register(_warmup_step, first_interval=0.4)


def _warmup_step():
    global _warmup_job
    job = _warmup_job
    if not job or not job.get("pending"):
        _warmup_job = None
        return None
    mode = job["pending"].pop(0)
    fp = core.overlay_fingerprint(
        job["front"],
        job["back"],
        mode,
        job["style"],
        job["skip_untranslated"],
        job["skip_identical"],
        job["skip_multiline"],
        job["max_length"],
        job["apply_all"],
        job["targets"],
    )
    if not _cached_mo_ready(fp):
        seed = job["targets"][0] if job["targets"] else job["front"]
        if mode == "FRONT":
            catalog, _stats = core.build_mono_catalog(job["front"], seed_locale=seed)
        elif mode == "BACK":
            catalog, _stats = core.build_mono_catalog(job["back"], seed_locale=seed)
        else:
            catalog, _stats = core.build_full_catalog(
                job["front"],
                job["back"],
                job["style"],
                skip_untranslated=job["skip_untranslated"],
                skip_identical=job["skip_identical"],
                skip_multiline=job["skip_multiline"],
                max_length=job["max_length"],
            )
        if catalog:
            core.store_overlay_cache(fp, catalog)
    if job["pending"]:
        return 0.35
    _warmup_job = None
    return None


def clear_bilingual():
    global _status, _registered
    prefs = _prefs()
    if prefs is None or prefs.rename_workspaces:
        core.restore_workspace_names(core.current_locale())
    restore = core.restore_overlays()
    _registered = False
    _status = (
        f"Cleared · restored {restore.get('restored', 0)} official catalogs, "
        f"removed {restore.get('removed', 0)} overlays"
    )
    if prefs is not None:
        prefs.last_report = _status


_updating = False
_msgbus_owner = object()


def _on_enable_changed():
    global _updating
    if _updating:
        return
    if not bpy.app.timers.is_registered(_deferred_apply):
        bpy.app.timers.register(_deferred_apply, first_interval=0.15)


def _on_display_changed():
    global _updating
    if _updating:
        return
    prefs = _prefs()
    if prefs is None or not prefs.enabled:
        return
    if not bpy.app.timers.is_registered(_deferred_apply):
        bpy.app.timers.register(_deferred_apply, first_interval=0.05)


def _on_pair_changed():
    global _updating
    if _updating:
        return
    prefs = _prefs()
    if prefs is None:
        return
    if prefs.mode == "FOLLOW_UI":
        prefs.mode = "FIXED"
    if not prefs.enabled:
        return
    if bpy.app.timers.is_registered(_deferred_apply):
        bpy.app.timers.unregister(_deferred_apply)
    bpy.app.timers.register(_deferred_apply, first_interval=0.35)


def _deferred_apply():
    global _updating
    _updating = True
    try:
        apply_bilingual()
    except Exception as exc:
        global _status
        _status = f"Error: {exc}"
        prefs = _prefs()
        if prefs is not None:
            prefs.last_report = _status
    finally:
        _updating = False
    return None


def _watch_language():
    prefs = _prefs()
    if prefs is None or not prefs.enabled or not prefs.auto_refresh:
        return
    current = core.current_locale()
    global _last_locale
    if current == _last_locale:
        return
    if prefs.apply_all_locales and _registered:
        _last_locale = current
        return
    if not bpy.app.timers.is_registered(_deferred_apply):
        bpy.app.timers.register(_deferred_apply, first_interval=0.2)


def _subscribe_language():
    try:
        bpy.msgbus.clear_by_owner(_msgbus_owner)
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.PreferencesView, "language"),
            owner=_msgbus_owner,
            args=(),
            notify=_watch_language,
        )
    except Exception:
        if not bpy.app.timers.is_registered(_poll_language):
            bpy.app.timers.register(_poll_language, persistent=True, first_interval=2.0)


def _poll_language():
    _watch_language()
    return 2.0


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class BILINGUAL_OT_apply(Operator):
    bl_idname = "bilingual.apply"
    bl_label = "Apply Bilingual UI"
    bl_description = "Rebuild and register bilingual interface strings"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            msg = apply_bilingual(report=self.report)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class BILINGUAL_OT_clear(Operator):
    bl_idname = "bilingual.clear"
    bl_label = "Restore Original"
    bl_description = "Remove bilingual overlays and restore Blender's translations"
    bl_options = {"REGISTER"}

    def execute(self, context):
        prefs = _prefs()
        if prefs is not None and prefs.enabled:
            prefs.enabled = False
        else:
            clear_bilingual()
        self.report({"INFO"}, "Bilingual UI cleared")
        return {"FINISHED"}


class BILINGUAL_OT_swap(Operator):
    bl_idname = "bilingual.swap"
    bl_label = "Swap Languages"
    bl_description = "Swap front and back languages (switches to Fixed Pair mode)"
    bl_options = {"REGISTER"}

    def execute(self, context):
        prefs = _prefs()
        if prefs is None:
            return {"CANCELLED"}
        front = core.current_locale() if prefs.mode == "FOLLOW_UI" else prefs.language_a
        back = prefs.language_b
        if not front or not back:
            self.report({"WARNING"}, "Pick both languages first")
            return {"CANCELLED"}
        prefs.mode = "FIXED"
        prefs.language_a = back
        prefs.language_b = front
        return {"FINISHED"}


class BILINGUAL_OT_reload_locales(Operator):
    bl_idname = "bilingual.reload_locales"
    bl_label = "Rescan Languages"
    bl_description = "Rescan Blender's locale folder for installed .mo catalogs"
    bl_options = {"REGISTER"}

    def execute(self, context):
        core.clear_caches()
        locales = core.discover_locales(force=True)
        mo_count = sum(1 for _c, _l, mo in locales if mo)
        self.report({"INFO"}, f"Found {len(locales)} languages, {mo_count} catalogs")
        return {"FINISHED"}


class BILINGUAL_OT_cycle_display(Operator):
    bl_idname = "bilingual.cycle_display"
    bl_label = "Cycle Bilingual Display"
    bl_description = "Cycle Front → Back → Both. Shift-click opens language picker"
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        if event.shift:
            return bpy.ops.bilingual.header_popup("INVOKE_DEFAULT")
        return self.execute(context)

    def execute(self, context):
        prefs = _prefs()
        if prefs is None:
            return {"CANCELLED"}
        global _updating
        _updating = True
        try:
            if not prefs.enabled:
                prefs.display_mode = "BILINGUAL"
                prefs.enabled = True
            else:
                current = prefs.display_mode if prefs.display_mode in DISPLAY_ORDER else "BILINGUAL"
                prefs.display_mode = DISPLAY_ORDER[(DISPLAY_ORDER.index(current) + 1) % len(DISPLAY_ORDER)]
            msg = apply_bilingual(report=self.report)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        finally:
            _updating = False
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class BILINGUAL_OT_header_popup(Operator):
    bl_idname = "bilingual.header_popup"
    bl_label = "Bilingual Languages"
    bl_description = "Choose front and back languages"
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=300)

    def draw(self, context):
        prefs = _prefs()
        layout = self.layout
        if prefs is None:
            layout.label(text="Enable Bilingual UI first")
            return
        layout.prop(prefs, "enabled")
        col = layout.column()
        col.enabled = prefs.enabled
        col.prop(prefs, "language_a", text="Front")
        col.prop(prefs, "language_b", text="Back")
        col.prop(prefs, "display_mode", expand=True)
        col.prop(prefs, "style", text="Format")
        row = col.row(align=True)
        row.operator(BILINGUAL_OT_apply.bl_idname, text="Apply")
        row.operator(BILINGUAL_OT_swap.bl_idname, text="Swap")
        layout.label(text=_status)

    def execute(self, context):
        return {"FINISHED"}


class BILINGUAL_OT_toggle(Operator):
    bl_idname = "bilingual.toggle"
    bl_label = "Toggle Bilingual UI"
    bl_description = "Enable or disable bilingual interface strings"
    bl_options = {"REGISTER"}

    def execute(self, context):
        prefs = _prefs()
        if prefs is None:
            return {"CANCELLED"}
        prefs.enabled = not prefs.enabled
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Sidebar panel
# ---------------------------------------------------------------------------

class BILINGUAL_PT_sidebar(Panel):
    bl_label = "Bilingual UI"
    bl_idname = "BILINGUAL_PT_sidebar"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bilingual"

    def draw(self, context):
        prefs = _prefs()
        layout = self.layout
        if prefs is None:
            layout.label(text="Enable the add-on in Preferences")
            return

        layout.prop(prefs, "enabled", toggle=True)
        col = layout.column()
        col.enabled = prefs.enabled
        col.prop(prefs, "mode", text="")
        col.prop(prefs, "language_a", text="Front")
        col.prop(prefs, "language_b", text="Back")
        if prefs.mode == "FOLLOW_UI":
            col.label(text=f"Front locked to UI: {_label_for(core.current_locale())}")
        col.prop(prefs, "display_mode", expand=True)
        col.prop(prefs, "style", text="Format")
        row = col.row(align=True)
        row.operator(BILINGUAL_OT_apply.bl_idname, text="Apply")
        row.operator(BILINGUAL_OT_clear.bl_idname, text="Clear")
        if _status:
            layout.label(text=_status)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    BilingualPreferences,
    BILINGUAL_OT_apply,
    BILINGUAL_OT_clear,
    BILINGUAL_OT_swap,
    BILINGUAL_OT_reload_locales,
    BILINGUAL_OT_cycle_display,
    BILINGUAL_OT_header_popup,
    BILINGUAL_OT_toggle,
    BILINGUAL_PT_sidebar,
)


def _draw_topbar(self, context):
    if getattr(context.region, "alignment", "") != "RIGHT":
        return
    prefs = _prefs()
    if prefs is None or not getattr(prefs, "show_header_switch", True):
        return
    layout = self.layout
    row = layout.row(align=True)
    row.operator(
        BILINGUAL_OT_cycle_display.bl_idname,
        text=_header_label(prefs),
        depress=bool(prefs.enabled and prefs.display_mode == "BILINGUAL"),
    )
    row.operator(BILINGUAL_OT_header_popup.bl_idname, text="", icon="DOWNARROW_HLT")


def register():
    global core
    core = _load_catalogs()
    for cls in classes:
        bpy.utils.register_class(cls)
    if hasattr(bpy.types, "TOPBAR_HT_upper_bar"):
        bpy.types.TOPBAR_HT_upper_bar.append(_draw_topbar)
    _subscribe_language()
    prefs = _prefs()
    if prefs is not None and prefs.enabled and not bpy.app.timers.is_registered(_deferred_apply):
        bpy.app.timers.register(_deferred_apply, first_interval=0.4)


def unregister():
    try:
        bpy.msgbus.clear_by_owner(_msgbus_owner)
    except Exception:
        pass
    if bpy.app.timers.is_registered(_poll_language):
        bpy.app.timers.unregister(_poll_language)
    if bpy.app.timers.is_registered(_deferred_apply):
        bpy.app.timers.unregister(_deferred_apply)
    if bpy.app.timers.is_registered(_warmup_step):
        bpy.app.timers.unregister(_warmup_step)
    if hasattr(bpy.types, "TOPBAR_HT_upper_bar"):
        try:
            bpy.types.TOPBAR_HT_upper_bar.remove(_draw_topbar)
        except Exception:
            pass
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    core.clear_caches()
