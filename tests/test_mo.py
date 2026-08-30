# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline tests for MO parsing and bilingual formatting (no Blender required)."""

from __future__ import annotations

import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Stub bpy so core.py can be imported outside Blender.
import types

bpy_stub = types.ModuleType("bpy")
app = types.SimpleNamespace(
    version=(4, 2, 0),
    binary_path=os.path.join(tempfile.gettempdir(), "blender"),
    translations=types.SimpleNamespace(locale="zh_HANS"),
)
utils = types.SimpleNamespace(
    resource_path=lambda kind: tempfile.gettempdir(),
    user_resource=lambda kind: "",
)
bpy_stub.app = app
bpy_stub.utils = utils
bpy_stub.context = types.SimpleNamespace(window_manager=None, preferences=None)
sys.modules.setdefault("bpy", bpy_stub)

import core as core_mod  # noqa: E402
from core import (  # noqa: E402
    CONTEXT_SEP,
    MO_MAGIC_LE,
    canonical_locale,
    format_pair,
    is_english,
    locale_candidates,
    lookup,
    parse_mo,
    short_label,
    should_skip,
)


def write_mo(path: str, entries: dict) -> None:
    """Write a little-endian GNU MO with optional msgctxt via CONTEXT_SEP in the key."""
    keys = []
    vals = []
    for (ctx, msgid), msgstr in entries.items():
        orig = msgid if ctx in ("",) else f"{ctx}{CONTEXT_SEP}{msgid}"
        keys.append(orig.encode("utf-8"))
        vals.append(msgstr.encode("utf-8"))

    n = len(keys)
    header_size = 28
    table_size = n * 8
    orig_tab = header_size
    trans_tab = orig_tab + table_size
    data_off = trans_tab + table_size

    orig_index = []
    trans_index = []
    blob = bytearray()
    offset = data_off
    for k in keys:
        orig_index.append((len(k), offset))
        blob.extend(k)
        blob.extend(b"\x00")
        offset += len(k) + 1
    for v in vals:
        trans_index.append((len(v), offset))
        blob.extend(v)
        blob.extend(b"\x00")
        offset += len(v) + 1

    header = struct.pack(
        "<7I",
        MO_MAGIC_LE,
        0,  # revision
        n,
        orig_tab,
        trans_tab,
        0,  # hash size
        0,  # hash offset
    )
    tables = bytearray()
    for length, off in orig_index:
        tables.extend(struct.pack("<II", length, off))
    for length, off in trans_index:
        tables.extend(struct.pack("<II", length, off))

    with open(path, "wb") as handle:
        handle.write(header)
        handle.write(tables)
        handle.write(blob)


class MoParseTests(unittest.TestCase):
    def test_parse_with_and_without_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "blender.mo")
            write_mo(
                path,
                {
                    ("", "Scale"): "缩放",
                    ("*", "Scale"): "缩放星",
                    ("Operator", "Delete"): "删除",
                },
            )
            catalog = parse_mo(path)
            self.assertEqual(catalog[("", "Scale")], "缩放")
            self.assertEqual(catalog[("*", "Scale")], "缩放星")
            self.assertEqual(catalog[("Operator", "Delete")], "删除")

    def test_plural_takes_singular(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "blender.mo")
            # Simulate msgid\0msgid_plural
            entries_raw = {
                b"File\x00Files": "文件\x00文件们".encode("utf-8"),
            }
            # Hand-roll one plural entry.
            keys = list(entries_raw)
            vals = [entries_raw[k] for k in keys]
            n = 1
            header_size = 28
            orig_tab = header_size
            trans_tab = orig_tab + 8
            data_off = trans_tab + 8
            blob = keys[0] + b"\x00" + vals[0] + b"\x00"
            header = struct.pack("<7I", MO_MAGIC_LE, 0, n, orig_tab, trans_tab, 0, 0)
            tables = struct.pack(
                "<IIII",
                len(keys[0]),
                data_off,
                len(vals[0]),
                data_off + len(keys[0]) + 1,
            )
            with open(path, "wb") as handle:
                handle.write(header + tables + blob)
            catalog = parse_mo(path)
            self.assertEqual(catalog[("", "File")], "文件")


class FormatTests(unittest.TestCase):
    def test_styles(self):
        self.assertEqual(format_pair("缩放", "Scale", "A_PAREN_B"), "缩放 (Scale)")
        self.assertEqual(format_pair("缩放", "Scale", "B_PAREN_A"), "Scale (缩放)")
        self.assertEqual(format_pair("缩放", "Scale", "A_SLASH_B"), "缩放 / Scale")
        self.assertEqual(format_pair("缩放", "Scale", "A_SPACE_B"), "缩放 Scale")
        self.assertEqual(format_pair("缩放", "Scale", "A_BRACKET_B"), "缩放 [Scale]")
        self.assertEqual(format_pair("缩放", "Scale", "A_DASH_B"), "缩放 — Scale")

    def test_identical_and_contained(self):
        self.assertEqual(format_pair("Scale", "Scale", "A_PAREN_B"), "Scale")
        self.assertEqual(format_pair("缩放 (Scale)", "Scale", "A_PAREN_B"), "缩放 (Scale)")

    def test_lookup_fallback(self):
        cat = {("Operator", "Delete"): "删除", ("*", "Scale"): "缩放星", ("", "Scale"): "缩放"}
        self.assertEqual(lookup(cat, "Operator", "Delete"), "删除")
        self.assertEqual(lookup(cat, "*", "Scale"), "缩放星")
        self.assertEqual(lookup(cat, "Operator", "Scale"), "缩放星")
        self.assertEqual(lookup(None, "*", "Scale"), "Scale")
        self.assertEqual(lookup(cat, "*", "Missing"), "Missing")


class LocaleTests(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(canonical_locale("zh_CN"), "zh_HANS")
        self.assertEqual(canonical_locale("zh_TW"), "zh_HANT")
        self.assertTrue(is_english("en_US"))
        self.assertTrue(is_english("en_GB"))
        self.assertFalse(is_english("zh_HANS"))
        self.assertEqual(short_label("zh_HANS"), "简")
        self.assertEqual(short_label("en_US"), "EN")
        self.assertEqual(short_label("ja_JP"), "日")

    def test_locale_candidates_short_dirs(self):
        self.assertIn("ja", locale_candidates("ja_JP"))
        self.assertIn("ja_JP", locale_candidates("ja_JP"))
        self.assertIn("fr", locale_candidates("fr_FR"))
        self.assertIn("zh_HANS", locale_candidates("zh_HANS"))
        self.assertIn("sr@latin", locale_candidates("sr_RS@latin"))
        self.assertIn("pt_BR", locale_candidates("pt_BR"))

    def test_overlay_folders_include_short_and_iso(self):
        orig = core_mod.find_mo

        def fake_find(locale):
            loc = canonical_locale(locale)
            mapping = {
                "ja_JP": "/tmp/locale/ja/LC_MESSAGES/blender.mo",
                "ja": "/tmp/locale/ja/LC_MESSAGES/blender.mo",
                "fr_FR": "/tmp/locale/fr/LC_MESSAGES/blender.mo",
                "zh_HANS": "/tmp/locale/zh_HANS/LC_MESSAGES/blender.mo",
            }
            return mapping.get(loc) or mapping.get(locale)

        core_mod.find_mo = fake_find
        try:
            ja = core_mod.overlay_folders_for("ja_JP")
            self.assertIn("ja_JP", ja)
            self.assertIn("ja", ja)
            zh = core_mod.overlay_folders_for("zh_HANS")
            self.assertEqual(zh, ["zh_HANS"])
            self.assertEqual(core_mod.overlay_folders_for("en_US"), [])
            self.assertEqual(core_mod.pick_host_locale("en_US", "zh_HANS"), "zh_HANS")
            self.assertEqual(core_mod.pick_host_locale("en_US", "en_GB"), "")
        finally:
            core_mod.find_mo = orig

    def test_should_skip(self):
        self.assertTrue(
            should_skip("Scale", "Scale", "Scale", True, True, True, 0)
        )
        self.assertTrue(
            should_skip("a\nb", "a\nb", "c", False, False, True, 0)
        )
        self.assertTrue(
            should_skip("x" * 10, "x", "y", False, False, False, 5)
        )
        self.assertFalse(
            should_skip("Scale", "缩放", "Scale", True, True, True, 80)
        )


class BilingualMapTests(unittest.TestCase):
    def test_chinese_plus_english(self):
        zh = {("*", "Scale"): "缩放", ("Operator", "Delete"): "删除"}
        orig_load = core_mod.load_catalog

        def fake_load(locale):
            loc = canonical_locale(locale)
            if loc == "zh_HANS":
                return zh
            return None

        core_mod.load_catalog = fake_load
        try:
            catalog, stats = core_mod.build_bilingual_map(
                "zh_HANS", "en_US", "A_PAREN_B"
            )
        finally:
            core_mod.load_catalog = orig_load

        self.assertEqual(catalog[("*", "Scale")], "缩放 (Scale)")
        self.assertEqual(catalog[("Operator", "Delete")], "删除 (Delete)")
        self.assertEqual(stats["emitted"], 2)

    def test_english_plus_japanese(self):
        ja = {("*", "Scale"): "スケール"}
        orig_load = core_mod.load_catalog

        def fake_load(locale):
            if canonical_locale(locale) == "ja_JP":
                return ja
            return None

        core_mod.load_catalog = fake_load
        try:
            catalog, _stats = core_mod.build_bilingual_map(
                "en_US", "ja_JP", "A_PAREN_B"
            )
        finally:
            core_mod.load_catalog = orig_load

        self.assertEqual(catalog[("*", "Scale")], "Scale (スケール)")

    def test_japanese_plus_chinese(self):
        ja = {("*", "Scale"): "スケール", ("*", "OnlyJA"): "日本語のみ"}
        zh = {("*", "Scale"): "缩放"}
        orig_load = core_mod.load_catalog

        def fake_load(locale):
            loc = canonical_locale(locale)
            if loc == "ja_JP":
                return ja
            if loc == "zh_HANS":
                return zh
            return None

        core_mod.load_catalog = fake_load
        try:
            catalog, _stats = core_mod.build_bilingual_map(
                "ja_JP", "zh_HANS", "A_SLASH_B", skip_identical=True
            )
        finally:
            core_mod.load_catalog = orig_load

        self.assertEqual(catalog[("*", "Scale")], "スケール / 缩放")
        # Chinese missing → falls back to English msgid
        self.assertEqual(catalog[("*", "OnlyJA")], "日本語のみ / OnlyJA")

    def test_mono_catalog_uses_seed_keys(self):
        zh = {("*", "Scale"): "缩放", ("Operator", "Delete"): "删除"}
        orig_load = core_mod.load_catalog

        def fake_load(locale):
            if locale and canonical_locale(locale) == "zh_HANS":
                return zh
            return None

        core_mod.load_catalog = fake_load
        try:
            catalog, stats = core_mod.build_mono_catalog("en_US", seed_locale="zh_HANS")
        finally:
            core_mod.load_catalog = orig_load

        self.assertEqual(catalog[("*", "Scale")], "Scale")
        self.assertEqual(catalog[("Operator", "Delete")], "Delete")
        self.assertEqual(stats["emitted"], 2)


class MoRoundTripTests(unittest.TestCase):
    def test_write_then_parse(self):
        catalog = {
            ("*", "Scale"): "缩放 (Scale)",
            ("Operator", "Delete"): "删除 (Delete)",
            ("", "File"): "文件 (File)",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "blender.mo")
            core_mod.write_mo(path, catalog)
            loaded = parse_mo(path)
            self.assertEqual(loaded[("*", "Scale")], "缩放 (Scale)")
            self.assertEqual(loaded[("Operator", "Delete")], "删除 (Delete)")
            self.assertEqual(loaded[("", "File")], "文件 (File)")

    def test_full_catalog_keeps_skipped(self):
        zh = {("*", "Scale"): "缩放", ("*", "Same"): "Same"}
        orig_load = core_mod.load_catalog

        def fake_load(locale):
            if canonical_locale(locale) == "zh_HANS":
                return zh
            return None

        core_mod.load_catalog = fake_load
        try:
            catalog, stats = core_mod.build_full_catalog(
                "zh_HANS", "en_US", "A_PAREN_B", skip_identical=True
            )
        finally:
            core_mod.load_catalog = orig_load

        self.assertEqual(catalog[("*", "Scale")], "缩放 (Scale)")
        self.assertEqual(catalog[("*", "Same")], "Same")
        self.assertEqual(stats["emitted"], 1)
        self.assertEqual(stats["kept"], 1)


class FingerprintTests(unittest.TestCase):
    def test_fingerprint_stable_and_sensitive(self):
        kwargs = dict(
            front="zh_HANS",
            back="en_US",
            display="BILINGUAL",
            style="A_PAREN_B",
            skip_untranslated=True,
            skip_identical=True,
            skip_multiline=True,
            max_length=80,
            apply_all=False,
            targets=["zh_HANS"],
        )
        a = core_mod.overlay_fingerprint(**kwargs)
        b = core_mod.overlay_fingerprint(**kwargs)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 16)
        other = dict(kwargs)
        other["style"] = "A_SLASH_B"
        self.assertNotEqual(a, core_mod.overlay_fingerprint(**other))


class WorkspaceLabelTests(unittest.TestCase):
    def test_labels_prefer_workspace_context(self):
        cat = {
            ("WorkSpace", "Layout"): "布局 (Layout)",
            ("", "Layout"): "布局别名",
            ("WorkSpace", "Modeling"): "建模 (Modeling)",
            ("Operator", "Delete"): "删除 (Delete)",
        }
        labels = core_mod.workspace_labels(cat)
        self.assertEqual(labels["Layout"], "布局 (Layout)")
        self.assertEqual(labels["Modeling"], "建模 (Modeling)")
        self.assertNotIn("Delete", labels)

    def test_default_context_is_ignored(self):
        # The default context holds the whole UI; matching it could rename a
        # workspace to an unrelated string.
        cat = {("", "Scripting"): "脚本 (Scripting)", ("", "Some tooltip"): "提示"}
        self.assertEqual(core_mod.workspace_labels(cat), {})

    def test_empty_catalog(self):
        self.assertEqual(core_mod.workspace_labels(None), {})
        self.assertEqual(core_mod.workspace_labels({}), {})


if __name__ == "__main__":
    unittest.main()
