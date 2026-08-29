# SPDX-License-Identifier: GPL-3.0-or-later
"""Load Blender .mo catalogs and build bilingual override dictionaries.

Implementation module imported by the add-on as `.core`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from collections import OrderedDict
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import bpy

MsgKey = Tuple[str, str]
Catalog = Dict[MsgKey, str]
TranslationsDict = Dict[str, Catalog]

MO_MAGIC_LE = 0x950412DE
MO_MAGIC_BE = 0xDE120495
CONTEXT_SEP = "\x04"

# Older Blender used zh_CN / zh_TW; 4.0+ uses zh_HANS / zh_HANT.
LOCALE_ALIASES = {
    "zh_CN": "zh_HANS",
    "zh_TW": "zh_HANT",
    "zh_Hans": "zh_HANS",
    "zh_Hant": "zh_HANT",
    "zh_HANS": "zh_HANS",
    "zh_HANT": "zh_HANT",
}

ENGLISH_LOCALES = frozenset(
    {"en_US", "en_GB", "en", "C", "Default", "DEFAULT", "Automatic"}
)

# Fallback labels when the languages file is missing.
LOCALE_NAMES = {
    "en_US": "English",
    "en_GB": "English (UK)",
    "ca_AD": "Catalan",
    "es": "Spanish",
    "es_ES": "Spanish",
    "fr_FR": "French",
    "de_DE": "German",
    "it_IT": "Italian",
    "ja_JP": "Japanese",
    "ko_KR": "Korean",
    "pt_PT": "Portuguese",
    "pt_BR": "Portuguese (Brazil)",
    "ru_RU": "Russian",
    "zh_HANS": "Simplified Chinese",
    "zh_HANT": "Traditional Chinese",
    "zh_CN": "Simplified Chinese",
    "zh_TW": "Traditional Chinese",
    "ar_EG": "Arabic",
    "cs_CZ": "Czech",
    "nl_NL": "Dutch",
    "fi_FI": "Finnish",
    "el_GR": "Greek",
    "he_IL": "Hebrew",
    "hi_IN": "Hindi",
    "hu_HU": "Hungarian",
    "id_ID": "Indonesian",
    "pl_PL": "Polish",
    "sk_SK": "Slovak",
    "sr_RS": "Serbian",
    "sv_SE": "Swedish",
    "th_TH": "Thai",
    "tr_TR": "Turkish",
    "uk_UA": "Ukrainian",
    "vi_VN": "Vietnamese",
    "ro_RO": "Romanian",
    "bg_BG": "Bulgarian",
    "da_DK": "Danish",
    "nb_NO": "Norwegian Bokmål",
    "eo": "Esperanto",
    "eu_EU": "Basque",
    "fa_IR": "Persian",
    "hr_HR": "Croatian",
    "ka": "Georgian",
    "kk": "Kazakh",
    "ky_KG": "Kyrgyz",
    "ne_NP": "Nepali",
    "sl": "Slovenian",
    "ta": "Tamil",
    "uz_UZ": "Uzbek",
}

SHORT_LABELS = {
    "en_US": "EN",
    "en_GB": "EN",
    "zh_HANS": "简",
    "zh_HANT": "繁",
    "ja_JP": "日",
    "ko_KR": "韩",
    "fr_FR": "FR",
    "de_DE": "DE",
    "es": "ES",
    "ru_RU": "RU",
    "pt_BR": "BR",
    "pt_PT": "PT",
    "it_IT": "IT",
    "pl_PL": "PL",
    "uk_UA": "UK",
    "tr_TR": "TR",
    "vi_VN": "VI",
    "th_TH": "TH",
    "ar_EG": "AR",
    "nl_NL": "NL",
    "sv_SE": "SV",
    "cs_CZ": "CS",
    "hu_HU": "HU",
    "ro_RO": "RO",
    "id_ID": "ID",
    "hi_IN": "HI",
    "sk_SK": "SK",
    "ca_AD": "CA",
    "fi_FI": "FI",
    "el_GR": "EL",
    "he_IL": "HE",
    "da": "DA",
    "nb": "NB",
    "hr": "HR",
    "sr_RS": "SR",
    "sl": "SL",
    "bg_BG": "BG",
    "ka": "KA",
    "ta": "TA",
    "lt": "LT",
    "eo": "EO",
}


def short_label(locale: str) -> str:
    loc = canonical_locale(locale)
    if loc in SHORT_LABELS:
        return SHORT_LABELS[loc]
    if loc in LOCALE_NAMES:
        return LOCALE_NAMES[loc][:2].upper()
    return loc.split("_", 1)[0].upper()[:3]


_CATALOG_CACHE_MAX = 4
_catalog_cache: "OrderedDict[str, Tuple[float, int, Catalog]]" = OrderedDict()
_locale_index_cache: Optional[List[Tuple[str, str, str]]] = None
_CACHE_KEEP = 12


def canonical_locale(locale: str) -> str:
    if not locale:
        return "en_US"
    return LOCALE_ALIASES.get(locale, locale)


def is_english(locale: str) -> bool:
    return canonical_locale(locale) in ENGLISH_LOCALES or locale in ENGLISH_LOCALES


def locale_candidates(locale: str) -> List[str]:
    """Folder names gettext / Blender may use for this locale.

    Official catalogs live in short dirs (`ja`, `fr`) while the UI language
    code is the ISO id from the languages file (`ja_JP`, `fr_FR`). Chinese
    happens to use the same string for both (`zh_HANS`), which is why only
    that pair appeared to work.
    """
    loc = canonical_locale(locale or "")
    names: List[str] = []

    def add(value: str) -> None:
        if value and value not in names:
            names.append(value)

    add(loc)
    if locale:
        add(locale)
    for alias, target in LOCALE_ALIASES.items():
        if target == loc or alias == loc:
            add(alias)
            add(target)

    if "@" in loc:
        base, variant = loc.split("@", 1)
        lang = base.split("_", 1)[0]
        add(f"{lang}@{variant}")
        add(base)
        add(lang)

    if "_" in loc.split("@", 1)[0]:
        add(loc.split("_", 1)[0])

    return names


def parse_mo(path: str) -> Catalog:
    """Parse a GNU gettext .mo file into {(msgctxt, msgid): msgstr}."""
    with open(path, "rb") as handle:
        data = handle.read()

    if len(data) < 20:
        return {}

    magic = struct.unpack_from("<I", data, 0)[0]
    if magic == MO_MAGIC_LE:
        endian = "<"
    elif magic == MO_MAGIC_BE:
        endian = ">"
    else:
        magic_be = struct.unpack_from(">I", data, 0)[0]
        if magic_be == MO_MAGIC_LE:
            endian = ">"
        else:
            raise ValueError(f"Not a GNU MO file: {path}")

    def u32(offset: int) -> int:
        return struct.unpack_from(endian + "I", data, offset)[0]

    nstrings = u32(8)
    orig_tab = u32(12)
    trans_tab = u32(16)

    catalog: Catalog = {}
    for i in range(nstrings):
        o_len = u32(orig_tab + i * 8)
        o_off = u32(orig_tab + i * 8 + 4)
        t_len = u32(trans_tab + i * 8)
        t_off = u32(trans_tab + i * 8 + 4)
        if o_off + o_len > len(data) or t_off + t_len > len(data):
            continue

        orig = data[o_off : o_off + o_len].decode("utf-8", errors="replace")
        trans = data[t_off : t_off + t_len].decode("utf-8", errors="replace")

        if not orig:
            continue

        # Plural forms: msgid\0msgid_plural  /  msgstr[0]\0msgstr[1]...
        if "\x00" in orig:
            orig = orig.split("\x00", 1)[0]
            trans = trans.split("\x00", 1)[0]

        if CONTEXT_SEP in orig:
            ctx, msgid = orig.split(CONTEXT_SEP, 1)
        else:
            ctx, msgid = "", orig

        if msgid:
            catalog[(sys.intern(ctx), sys.intern(msgid))] = trans

    return catalog


def user_datafiles_dir(subpath: str = "", create: bool = False) -> str:
    try:
        return bpy.utils.user_resource("DATAFILES", path=subpath, create=create) or ""
    except TypeError:
        # Older bpy.utils.user_resource may not take path=.
        try:
            base = bpy.utils.user_resource("DATAFILES", create=create) or ""
        except Exception:
            return ""
        if not base:
            return ""
        full = os.path.join(base, subpath) if subpath else base
        if create and subpath:
            os.makedirs(full, exist_ok=True)
        return full
    except Exception:
        return ""


def user_locale_root(create: bool = False) -> str:
    return user_datafiles_dir("locale", create=create)


def backup_root(create: bool = False) -> str:
    base = user_datafiles_dir("bilingual_ui", create=create)
    if not base:
        return ""
    path = os.path.join(base, "original_mo")
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def backup_mo_path(locale: str, create_dir: bool = False) -> str:
    root = backup_root(create=create_dir)
    if not root:
        return ""
    return os.path.join(root, canonical_locale(locale) + ".mo")


def _system_locale_roots() -> List[str]:
    """Official locale dirs only. Never include the user overlay folder."""
    roots: List[str] = []
    version = bpy.app.version
    ver_str = f"{version[0]}.{version[1]}"
    binary_dir = os.path.dirname(bpy.app.binary_path)

    candidates = []
    for kind in ("LOCAL", "SYSTEM"):
        try:
            candidates.append(os.path.join(bpy.utils.resource_path(kind), "datafiles", "locale"))
        except Exception:
            pass

    candidates.extend(
        [
            os.path.join(binary_dir, ver_str, "datafiles", "locale"),
            os.path.join(binary_dir, "datafiles", "locale"),
            os.path.join(binary_dir, "Resources", ver_str, "datafiles", "locale"),
        ]
    )

    seen = set()
    for path in candidates:
        if not path:
            continue
        norm = os.path.normpath(path)
        if norm in seen:
            continue
        seen.add(norm)
        if os.path.isdir(norm):
            roots.append(norm)
    return roots


def _locale_roots() -> List[str]:
    return _system_locale_roots()


def _parse_languages_file(path: str) -> Dict[str, str]:
    """Parse Blender's locale/languages file: ID:MENULABEL:ISOCODE[:PERCENT]."""
    names: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(":")
                if len(parts) < 3:
                    continue
                label, code = parts[1].strip(), parts[2].strip()
                if not code or code in {"Default", "DEFAULT", "Automatic", "C"}:
                    continue
                names[code] = label
    except OSError:
        pass
    return names


def discover_locales(force: bool = False) -> List[Tuple[str, str, str]]:
    """Return [(locale, label, mo_path_or_empty), ...] including English."""
    global _locale_index_cache
    if _locale_index_cache is not None and not force:
        return _locale_index_cache

    file_names: Dict[str, str] = {}
    mo_paths: Dict[str, str] = {}

    for root in _locale_roots():
        lang_file = os.path.join(root, "languages")
        if os.path.isfile(lang_file):
            file_names.update(_parse_languages_file(lang_file))

        try:
            entries = os.listdir(root)
        except OSError:
            continue
        for name in entries:
            locale_dir = os.path.join(root, name)
            if not os.path.isdir(locale_dir):
                continue
            mo = os.path.join(locale_dir, "LC_MESSAGES", "blender.mo")
            if os.path.isfile(mo):
                mo_paths[canonical_locale(name)] = mo
                if name not in mo_paths:
                    mo_paths[name] = mo

    def mo_for(code: str) -> str:
        for cand in locale_candidates(code):
            path = mo_paths.get(cand)
            if path:
                return path
        return ""

    items: List[Tuple[str, str, str]] = [
        ("en_US", "English (Original)", ""),
    ]
    seen = {"en_US"}
    used_mo = set()

    # Prefer ISO codes from the languages file — those match view.language.
    labeled = sorted(
        file_names.items(),
        key=lambda kv: (kv[1] or kv[0]).lower(),
    )
    for code, label in labeled:
        loc = canonical_locale(code)
        if loc in seen or is_english(loc):
            continue
        seen.add(loc)
        mo = mo_for(loc)
        if mo:
            used_mo.add(os.path.normpath(mo))
        items.append((loc, label, mo))

    for folder, mo in sorted(mo_paths.items()):
        loc = canonical_locale(folder)
        if loc in seen or is_english(loc):
            continue
        if mo and os.path.normpath(mo) in used_mo:
            continue
        seen.add(loc)
        label = file_names.get(folder) or file_names.get(loc) or LOCALE_NAMES.get(loc) or folder
        items.append((loc, label, mo))
        if mo:
            used_mo.add(os.path.normpath(mo))

    _locale_index_cache = items
    return items


def find_mo(locale: str) -> Optional[str]:
    loc = canonical_locale(locale)
    if is_english(loc):
        return None
    wanted = locale_candidates(locale)
    for code, _label, mo in discover_locales():
        if not mo:
            continue
        if code == loc or code in wanted or loc in locale_candidates(code):
            return mo
    for root in _locale_roots():
        for name in wanted:
            mo = os.path.join(root, name, "LC_MESSAGES", "blender.mo")
            if os.path.isfile(mo):
                return mo
    return None


def load_catalog(locale: str) -> Optional[Catalog]:
    """Return the original catalog for locale, or None for English/identity.

    Prefers the pre-overlay backup so re-applying never double-wraps.
    """
    if is_english(locale):
        return None
    path = backup_mo_path(locale)
    if not path or not os.path.isfile(path):
        path = find_mo(locale)
    if not path:
        return None
    try:
        stat = os.stat(path)
    except OSError:
        return None
    cached = _catalog_cache.get(path)
    if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
        _catalog_cache.move_to_end(path)
        return cached[2]
    catalog = parse_mo(path)
    _catalog_cache[path] = (stat.st_mtime, stat.st_size, catalog)
    _catalog_cache.move_to_end(path)
    while len(_catalog_cache) > _CATALOG_CACHE_MAX:
        _catalog_cache.popitem(last=False)
    return catalog


def lookup(catalog: Optional[Catalog], ctx: str, msgid: str) -> str:
    if catalog is None:
        return msgid
    if (ctx, msgid) in catalog:
        return catalog[(ctx, msgid)]
    if ctx and ("*", msgid) in catalog:
        return catalog[("*", msgid)]
    if ("", msgid) in catalog:
        return catalog[("", msgid)]
    return msgid


def format_pair(primary: str, secondary: str, style: str) -> str:
    if not secondary or primary == secondary:
        return primary
    if secondary in primary:
        return primary
    if style == "A_PAREN_B":
        return f"{primary} ({secondary})"
    if style == "B_PAREN_A":
        return f"{secondary} ({primary})"
    if style == "A_SLASH_B":
        return f"{primary} / {secondary}"
    if style == "A_SPACE_B":
        return f"{primary} {secondary}"
    if style == "A_BRACKET_B":
        return f"{primary} [{secondary}]"
    if style == "A_DASH_B":
        return f"{primary} — {secondary}"
    return f"{primary} ({secondary})"


def current_locale() -> str:
    loc = getattr(bpy.app.translations, "locale", "") or "en_US"
    return canonical_locale(loc)


def should_skip(
    msgid: str,
    primary: str,
    secondary: str,
    skip_untranslated: bool,
    skip_identical: bool,
    skip_multiline: bool,
    max_length: int,
) -> bool:
    if skip_multiline and ("\n" in msgid or "\n" in primary or "\n" in secondary):
        return True
    if max_length > 0 and len(msgid) > max_length:
        return True
    if skip_identical and primary == secondary:
        return True
    if skip_untranslated and primary == msgid and secondary == msgid:
        return True
    return False


def build_bilingual_map(
    primary_locale: str,
    secondary_locale: str,
    style: str,
    skip_untranslated: bool = True,
    skip_identical: bool = True,
    skip_multiline: bool = True,
    max_length: int = 0,
    progress: Optional[Callable[[str], None]] = None,
) -> Tuple[Catalog, Dict[str, int]]:
    """Build {(ctx, msgid): bilingual} for one UI locale."""
    stats = {
        "primary_entries": 0,
        "secondary_entries": 0,
        "emitted": 0,
        "skipped": 0,
    }

    primary_cat = load_catalog(primary_locale)
    secondary_cat = load_catalog(secondary_locale)

    if primary_cat is not None:
        stats["primary_entries"] = len(primary_cat)
    if secondary_cat is not None:
        stats["secondary_entries"] = len(secondary_cat)

    if primary_cat is None and secondary_cat is None:
        if progress:
            progress("Both languages are English / missing catalogs.")
        return {}, stats

    # Walk the richer side so English-as-primary still gets keys.
    if primary_cat is not None:
        keys: Iterable[MsgKey] = primary_cat.keys()
    else:
        keys = secondary_cat.keys()  # type: ignore[union-attr]

    result: Catalog = {}
    for ctx, msgid in keys:
        primary = lookup(primary_cat, ctx, msgid)
        secondary = lookup(secondary_cat, ctx, msgid)
        if should_skip(
            msgid,
            primary,
            secondary,
            skip_untranslated,
            skip_identical,
            skip_multiline,
            max_length,
        ):
            stats["skipped"] += 1
            continue
        result[(ctx, msgid)] = format_pair(primary, secondary, style)
        stats["emitted"] += 1

    if progress:
        progress(
            f"{primary_locale}+{secondary_locale}: "
            f"{stats['emitted']} bilingual, {stats['skipped']} skipped"
        )
    return result, stats


def build_full_catalog(
    primary_locale: str,
    secondary_locale: str,
    style: str,
    skip_untranslated: bool = True,
    skip_identical: bool = True,
    skip_multiline: bool = True,
    max_length: int = 0,
    progress: Optional[Callable[[str], None]] = None,
) -> Tuple[Catalog, Dict[str, int]]:
    """Complete catalog for a .mo file: original strings plus bilingual overlays.

    Entries that fail the skip filters keep their original translation so the
    UI does not fall back to English msgid.
    """
    stats = {
        "primary_entries": 0,
        "secondary_entries": 0,
        "emitted": 0,
        "kept": 0,
        "skipped": 0,
    }

    primary_cat = load_catalog(primary_locale)
    secondary_cat = load_catalog(secondary_locale)

    if primary_cat is not None:
        stats["primary_entries"] = len(primary_cat)
    if secondary_cat is not None:
        stats["secondary_entries"] = len(secondary_cat)

    if primary_cat is None and secondary_cat is None:
        if progress:
            progress("Both languages are English / missing catalogs.")
        return {}, stats

    if primary_cat is not None:
        result: Catalog = dict(primary_cat)
        keys: Iterable[MsgKey] = list(primary_cat.keys())
    else:
        assert secondary_cat is not None
        result = {(ctx, msgid): msgid for ctx, msgid in secondary_cat.keys()}
        keys = list(secondary_cat.keys())

    for ctx, msgid in keys:
        primary = lookup(primary_cat, ctx, msgid)
        secondary = lookup(secondary_cat, ctx, msgid)
        if should_skip(
            msgid,
            primary,
            secondary,
            skip_untranslated,
            skip_identical,
            skip_multiline,
            max_length,
        ):
            stats["kept"] += 1
            continue
        result[(ctx, msgid)] = format_pair(primary, secondary, style)
        stats["emitted"] += 1

    stats["skipped"] = stats["kept"]
    if progress:
        progress(
            f"{primary_locale}+{secondary_locale}: "
            f"{stats['emitted']} bilingual, {stats['kept']} kept original, "
            f"{len(result)} total"
        )
    return result, stats


def build_mono_catalog(
    locale: str,
    seed_locale: Optional[str] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> Tuple[Catalog, Dict[str, int]]:
    """Single-language catalog keyed like the seed locale (usually the current UI).

    English has no blender.mo; keys then come from seed so we can overlay
    English msgids onto a translated UI.
    """
    stats = {
        "primary_entries": 0,
        "secondary_entries": 0,
        "emitted": 0,
        "kept": 0,
        "skipped": 0,
    }
    loc_cat = load_catalog(locale)
    seed_cat = load_catalog(seed_locale) if seed_locale else None
    if loc_cat is not None:
        stats["primary_entries"] = len(loc_cat)
    if seed_cat is not None:
        stats["secondary_entries"] = len(seed_cat)

    if loc_cat is None and seed_cat is None:
        if progress:
            progress(f"{locale}: no catalog (English identity needs a seed locale)")
        return {}, stats

    keys: Iterable[MsgKey]
    if seed_cat is not None:
        keys = seed_cat.keys()
    else:
        assert loc_cat is not None
        keys = loc_cat.keys()

    result: Catalog = {}
    for ctx, msgid in keys:
        result[(ctx, msgid)] = lookup(loc_cat, ctx, msgid)
        stats["emitted"] += 1

    if progress:
        progress(f"{locale} mono: {stats['emitted']} strings")
    return result, stats


def write_mo(path: str, catalog: Catalog) -> None:
    """Write a little-endian GNU MO. Original strings are sorted by bytes."""
    items: List[Tuple[bytes, bytes]] = [
        (b"", b"Content-Type: text/plain; charset=UTF-8\n")
    ]
    for (ctx, msgid), msgstr in catalog.items():
        if not msgid:
            continue
        orig = msgid if ctx in ("",) else f"{ctx}{CONTEXT_SEP}{msgid}"
        items.append((orig.encode("utf-8"), (msgstr or "").encode("utf-8")))

    items.sort(key=lambda kv: kv[0])
    n = len(items)
    header_size = 28
    orig_tab = header_size
    trans_tab = orig_tab + n * 8
    data_off = trans_tab + n * 8

    orig_index: List[Tuple[int, int]] = []
    trans_index: List[Tuple[int, int]] = []
    blob = bytearray()
    offset = data_off
    for orig, _trans in items:
        orig_index.append((len(orig), offset))
        blob.extend(orig)
        blob.extend(b"\x00")
        offset += len(orig) + 1
    for _orig, trans in items:
        trans_index.append((len(trans), offset))
        blob.extend(trans)
        blob.extend(b"\x00")
        offset += len(trans) + 1

    header = struct.pack(
        "<7I",
        MO_MAGIC_LE,
        0,
        n,
        orig_tab,
        trans_tab,
        0,
        0,
    )
    tables = bytearray()
    for length, off in orig_index:
        tables.extend(struct.pack("<II", length, off))
    for length, off in trans_index:
        tables.extend(struct.pack("<II", length, off))

    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as handle:
        handle.write(header)
        handle.write(tables)
        handle.write(blob)
    os.replace(tmp, path)


def locale_folder_name(locale: str) -> str:
    mo = find_mo(locale)
    if mo:
        return os.path.basename(os.path.dirname(os.path.dirname(mo)))
    return canonical_locale(locale)


def overlay_folders_for(locale: str) -> List[str]:
    """User-locale directories to write so both ISO and short names resolve.

    Japanese UI is `ja_JP` but the official file is `locale/ja/`. Write both.
    English has no blender.mo — never emit a folder for it.
    """
    folders: List[str] = []

    def add(name: str) -> None:
        if name and name not in folders and not is_english(name):
            folders.append(name)

    add(canonical_locale(locale))
    add(locale_folder_name(locale))
    return folders


def pick_host_locale(*candidates: str) -> str:
    """First non-English locale that can hold a blender.mo overlay."""
    seen = set()
    for raw in candidates:
        loc = canonical_locale(raw or "")
        if not loc or loc in seen or is_english(loc):
            continue
        seen.add(loc)
        if overlay_folders_for(loc):
            return loc
    return ""


def set_ui_language(locale: str) -> bool:
    """Point Blender's UI language at a catalog we can overlay."""
    loc = canonical_locale(locale)
    if not loc:
        return False
    prefs = bpy.context.preferences
    if prefs is None:
        return False
    try:
        if hasattr(prefs.view, "use_translate_interface"):
            prefs.view.use_translate_interface = True
        prefs.view.language = loc
        redraw_ui()
        return True
    except Exception:
        return False


def build_translations_dict(
    secondary_locale: str,
    style: str,
    apply_all_locales: bool,
    skip_untranslated: bool,
    skip_identical: bool,
    skip_multiline: bool,
    max_length: int,
    progress: Optional[Callable[[str], None]] = None,
) -> Tuple[TranslationsDict, Dict[str, int]]:
    """Build the dict expected by bpy.app.translations.register()."""
    active = current_locale()
    locales = [active]
    if apply_all_locales:
        extra = [code for code, _label, mo in discover_locales() if mo]
        for code in extra:
            if code not in locales:
                locales.append(code)
        if "en_US" not in locales:
            locales.append("en_US")

    merged: TranslationsDict = {}
    totals = {
        "primary_entries": 0,
        "secondary_entries": 0,
        "emitted": 0,
        "skipped": 0,
        "locales": 0,
    }

    for loc in locales:
        catalog, stats = build_bilingual_map(
            loc,
            secondary_locale,
            style,
            skip_untranslated=skip_untranslated,
            skip_identical=skip_identical,
            skip_multiline=skip_multiline,
            max_length=max_length,
            progress=progress,
        )
        if not catalog:
            continue
        for key in locale_keys(loc):
            merged[key] = catalog
        totals["locales"] += 1
        totals["emitted"] += stats["emitted"]
        totals["skipped"] += stats["skipped"]
        totals["primary_entries"] = max(totals["primary_entries"], stats["primary_entries"])
        totals["secondary_entries"] = max(totals["secondary_entries"], stats["secondary_entries"])

    return merged, totals


def locale_keys(locale: str) -> List[str]:
    loc = canonical_locale(locale)
    keys = {loc, locale}
    for alias, target in LOCALE_ALIASES.items():
        if target == loc or alias == loc:
            keys.add(alias)
            keys.add(target)
    return list(keys)


STATE_VERSION = 2
CACHE_FORMAT = 1


def _state_path() -> str:
    root = user_datafiles_dir("bilingual_ui", create=True)
    if not root:
        return ""
    return os.path.join(root, "overlay_state.json")


def _load_state() -> dict:
    path = _state_path()
    if not path or not os.path.isfile(path):
        return {
            "version": STATE_VERSION,
            "system_replaced": [],
            "user_written": [],
            "junctions": [],
            "copied_mo": [],
            "fingerprint": "",
            "cache_files": [],
        }
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("bad state")
        data.setdefault("system_replaced", [])
        data.setdefault("user_written", [])
        data.setdefault("junctions", [])
        data.setdefault("copied_mo", [])
        data.setdefault("fingerprint", "")
        data.setdefault("cache_files", [])
        return data
    except (OSError, ValueError, json.JSONDecodeError):
        return {
            "version": STATE_VERSION,
            "system_replaced": [],
            "user_written": [],
            "junctions": [],
            "copied_mo": [],
            "fingerprint": "",
            "cache_files": [],
        }


def _save_state(state: dict) -> None:
    path = _state_path()
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def cache_root(create: bool = False) -> str:
    base = user_datafiles_dir("bilingual_ui", create=create)
    if not base:
        return ""
    path = os.path.join(base, "cache")
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def overlay_fingerprint(
    front: str,
    back: str,
    display: str,
    style: str,
    skip_untranslated: bool,
    skip_identical: bool,
    skip_multiline: bool,
    max_length: int,
    apply_all: bool,
    targets: Iterable[str],
) -> str:
    """Stable id for a generated overlay. Source .mo mtimes are included so a
    Blender update invalidates the cache automatically.
    """
    parts = [
        f"fmt={CACHE_FORMAT}",
        f"front={canonical_locale(front)}",
        f"back={canonical_locale(back)}",
        f"display={display}",
        f"style={style}",
        f"skip_u={int(skip_untranslated)}",
        f"skip_i={int(skip_identical)}",
        f"skip_m={int(skip_multiline)}",
        f"max={max_length}",
        f"all={int(apply_all)}",
        "targets=" + ",".join(sorted({canonical_locale(t) for t in targets})),
    ]
    locales = {canonical_locale(front), canonical_locale(back)}
    locales.update(canonical_locale(t) for t in targets)
    for loc in sorted(locales):
        if is_english(loc):
            parts.append(f"{loc}=en")
            continue
        path = backup_mo_path(loc) or find_mo(loc)
        if not path or not os.path.isfile(path):
            path = find_mo(loc)
        if not path or not os.path.isfile(path):
            parts.append(f"{loc}=missing")
            continue
        try:
            st = os.stat(path)
            parts.append(f"{loc}={int(st.st_mtime)}:{st.st_size}")
        except OSError:
            parts.append(f"{loc}=missing")
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return digest


def cached_overlay_path(fingerprint: str, create: bool = False) -> str:
    root = cache_root(create=create)
    if not root:
        return ""
    return os.path.join(root, fingerprint + ".mo")


def overlay_cache_hit(fingerprint: str, targets: Iterable[str]) -> bool:
    """True when the on-disk overlay already matches this fingerprint."""
    if not fingerprint:
        return False
    state = _load_state()
    if state.get("fingerprint") != fingerprint:
        return False
    written = list(state.get("user_written") or [])
    if not written:
        return False
    for path in written:
        if not os.path.isfile(path):
            return False
    expected = set()
    for loc in targets:
        for folder in overlay_folders_for(loc):
            path = user_mo_path(loc, folder=folder, prepare=False)
            if path:
                expected.add(os.path.normpath(path))
    have = {os.path.normpath(p) for p in written}
    return expected.issubset(have) and bool(expected)


def store_overlay_cache(fingerprint: str, catalog: Catalog) -> Optional[str]:
    path = cached_overlay_path(fingerprint, create=True)
    if not path or not catalog:
        return None
    if os.path.isfile(path):
        return path
    write_mo(path, catalog)
    state = _load_state()
    files = list(state.get("cache_files") or [])
    if path not in files:
        files.append(path)
    extra = files[:-_CACHE_KEEP] if len(files) > _CACHE_KEEP else []
    kept = files[-_CACHE_KEEP:] if len(files) > _CACHE_KEEP else files
    for old in extra:
        try:
            if os.path.isfile(old):
                os.remove(old)
        except OSError:
            pass
    state["cache_files"] = kept
    _save_state(state)
    return path


def load_cached_overlay(fingerprint: str) -> Optional[Catalog]:
    path = cached_overlay_path(fingerprint)
    if not path or not os.path.isfile(path):
        return None
    return parse_mo(path)


def prune_overlay_cache() -> None:
    state = _load_state()
    files = list(state.get("cache_files") or [])
    if len(files) <= _CACHE_KEEP:
        return
    extra = files[:-_CACHE_KEEP]
    kept = files[-_CACHE_KEEP:]
    for old in extra:
        try:
            if os.path.isfile(old):
                os.remove(old)
        except OSError:
            pass
    state["cache_files"] = kept
    _save_state(state)


def official_mo_paths(locale: str) -> List[str]:
    """Existing official blender.mo files for this locale (system/local, not user overlay)."""
    wanted = set(locale_keys(locale))
    wanted.add(locale_folder_name(locale))
    paths: List[str] = []
    seen = set()
    for root in _system_locale_roots():
        for name in wanted:
            mo = os.path.join(root, name, "LC_MESSAGES", "blender.mo")
            if not os.path.isfile(mo):
                continue
            norm = os.path.normpath(mo)
            if norm in seen:
                continue
            seen.add(norm)
            paths.append(norm)
    return paths


def ensure_backup(locale: str) -> Optional[str]:
    dest = backup_mo_path(locale, create_dir=True)
    if not dest:
        return None
    if os.path.isfile(dest):
        return dest
    src = find_mo(locale)
    if not src or not os.path.isfile(src):
        return None
    shutil.copy2(src, dest)
    return dest


def _dir_link(src: str, dst: str) -> bool:
    if os.path.lexists(dst):
        return True
    try:
        os.symlink(src, dst, target_is_directory=True)
        return True
    except OSError:
        pass
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", dst, src],
            capture_output=True,
            text=True,
            creationflags=flags,
        )
        return result.returncode == 0
    return False


def ensure_user_locale_bridge(overlay_folders: Iterable[str]) -> dict:
    """Make user datafiles/locale the complete catalog root.

    Copies the languages file and junctions every official locale we are not
    overlaying, so other languages keep working after the user folder exists.
    """
    created = {"languages": False, "junctions": [], "copied_mo": []}
    user_root = user_locale_root(create=True)
    if not user_root:
        return created

    overlay = {canonical_locale(name) for name in overlay_folders}
    overlay.update(overlay_folders)

    for sys_root in _system_locale_roots():
        src_lang = os.path.join(sys_root, "languages")
        if os.path.isfile(src_lang):
            dst_lang = os.path.join(user_root, "languages")
            if not os.path.isfile(dst_lang):
                shutil.copy2(src_lang, dst_lang)
                created["languages"] = True
            break

    for sys_root in _system_locale_roots():
        try:
            names = os.listdir(sys_root)
        except OSError:
            continue
        for name in names:
            if name in overlay or canonical_locale(name) in overlay:
                continue
            src = os.path.join(sys_root, name)
            if not os.path.isdir(src):
                continue
            dst = os.path.join(user_root, name)
            if os.path.lexists(dst):
                if _is_link(dst):
                    continue
                # Leftover empty overlay dir from a previous language — replace
                # with a junction so Blender can still find the official catalog.
                try:
                    leftover = os.listdir(dst)
                except OSError:
                    leftover = ["?"]
                if leftover in ([], ["LC_MESSAGES"]):
                    inner = os.path.join(dst, "LC_MESSAGES")
                    try:
                        if os.path.isdir(inner) and not os.listdir(inner):
                            os.rmdir(inner)
                        os.rmdir(dst)
                    except OSError:
                        continue
                    if os.path.lexists(dst):
                        continue
                else:
                    continue
            if _dir_link(src, dst):
                created["junctions"].append(dst)
                continue
            src_mo = os.path.join(src, "LC_MESSAGES", "blender.mo")
            dst_mo = os.path.join(dst, "LC_MESSAGES", "blender.mo")
            if os.path.isfile(src_mo) and not os.path.isfile(dst_mo):
                os.makedirs(os.path.dirname(dst_mo), exist_ok=True)
                shutil.copy2(src_mo, dst_mo)
                created["copied_mo"].append(dst_mo)
    return created


def _is_link(path: str) -> bool:
    if os.path.islink(path):
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        try:
            if isjunction(path):
                return True
        except OSError:
            pass
    if os.name == "nt":
        try:
            attrs = getattr(os.lstat(path), "st_file_attributes", 0)
            return bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
        except OSError:
            return False
    return False


def _remove_link(path: str) -> None:
    if not os.path.lexists(path):
        return
    try:
        os.unlink(path)
        return
    except OSError:
        pass
    try:
        os.rmdir(path)
    except OSError:
        pass


def user_mo_path(locale: str, folder: Optional[str] = None, prepare: bool = True) -> str:
    name = folder or locale_folder_name(locale)
    root = user_locale_root(create=prepare)
    if not root or not name:
        return ""
    loc_dir = os.path.join(root, name)
    if prepare and _is_link(loc_dir):
        _remove_link(loc_dir)
    return os.path.join(loc_dir, "LC_MESSAGES", "blender.mo")


def _write_mo_safe(path: str, catalog: Catalog) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    write_mo(path, catalog)


def _try_replace_official(path: str, catalog: Catalog) -> bool:
    try:
        _write_mo_safe(path, catalog)
        return True
    except OSError:
        return False


def unload_catalogs() -> str:
    """Switch UI language to English so Windows can replace mapped .mo files."""
    prefs = bpy.context.preferences
    if prefs is None:
        return ""
    view = prefs.view
    current = view.language
    try:
        if current != "en_US":
            view.language = "en_US"
        else:
            view.language = "DEFAULT"
    except Exception:
        return current
    return current


def reload_current_language() -> None:
    """Drop the mapped catalog and load it again from disk."""
    previous = unload_catalogs()
    restore_language(previous)


def restore_language(language: str) -> None:
    if not language:
        return
    prefs = bpy.context.preferences
    if prefs is None:
        return
    try:
        if hasattr(prefs.view, "use_translate_interface"):
            prefs.view.use_translate_interface = True
        prefs.view.language = language
    except Exception:
        pass
    redraw_ui()


def install_overlays(
    items: List[Tuple[str, Catalog]],
    progress: Optional[Callable[[str], None]] = None,
    fingerprint: str = "",
    cache_mo: str = "",
) -> Dict[str, int]:
    """Write bilingual blender.mo into the user datafiles locale folder.

    Blender 5.x looks up built-in UI in blender.mo first; Python
    translations.register() is only a fallback and cannot override hits.
    User datafiles/locale is searched before the install directory, so we
    never modify Program Files.
    """
    stats = {
        "locales": 0,
        "emitted": 0,
        "system_written": 0,
        "user_written": 0,
        "system_failed": 0,
    }
    if not items:
        return stats

    state = _load_state()
    overlay_folders: List[str] = []
    for loc, cat in items:
        if not cat:
            continue
        overlay_folders.extend(overlay_folders_for(loc))
    overlay_folders = list(dict.fromkeys(overlay_folders))

    previous = unload_catalogs()
    host = ""
    for loc, cat in items:
        if cat and overlay_folders_for(loc):
            host = canonical_locale(loc)
            break
    restore_to = host if host else previous
    try:
        keep_paths = set()
        for loc, cat in items:
            if not cat:
                continue
            for folder in overlay_folders_for(loc):
                path = user_mo_path(loc, folder=folder)
                if path:
                    keep_paths.add(os.path.normpath(path))
        _purge_user_files(state, keep_paths=keep_paths, stats=stats)

        bridge = ensure_user_locale_bridge(overlay_folders)
        for path in bridge.get("junctions", []):
            if path not in state["junctions"]:
                state["junctions"].append(path)
        for path in bridge.get("copied_mo", []):
            if path not in state["copied_mo"]:
                state["copied_mo"].append(path)

        for locale, catalog in items:
            if not catalog:
                continue
            ensure_backup(locale)
            stats["locales"] += 1
            stats["emitted"] += len(catalog)

            folders = overlay_folders_for(locale)
            if not folders:
                continue
            written_any = False
            for folder in folders:
                user_path = user_mo_path(locale, folder=folder)
                if not user_path:
                    continue
                if cache_mo and os.path.isfile(cache_mo):
                    os.makedirs(os.path.dirname(user_path), exist_ok=True)
                    shutil.copy2(cache_mo, user_path)
                else:
                    _write_mo_safe(user_path, catalog)
                stats["user_written"] += 1
                written_any = True
                if user_path not in state["user_written"]:
                    state["user_written"].append(user_path)
                loc_dir = os.path.dirname(os.path.dirname(user_path))
                state["junctions"] = [
                    p
                    for p in state["junctions"]
                    if os.path.normpath(p) != os.path.normpath(loc_dir)
                ]
                if progress:
                    progress(f"Wrote {locale} as {folder} ({len(catalog)} strings)")
            if not written_any:
                raise RuntimeError(
                    f"Could not resolve user datafiles path for {locale}."
                )
        if fingerprint:
            state["fingerprint"] = fingerprint
    finally:
        _save_state(state)
        restore_language(restore_to)

    return stats


def _purge_user_files(
    state: dict,
    keep_paths: Optional[set] = None,
    stats: Optional[dict] = None,
) -> None:
    """Remove previously written user overlays except those in keep_paths."""
    if stats is None:
        stats = {}
    stats.setdefault("removed", 0)
    stats.setdefault("failed", 0)
    keep = {os.path.normpath(p) for p in (keep_paths or set())}

    remaining_written = []
    remaining_copied = []
    for path in list(state.get("copied_mo") or []) + list(state.get("user_written") or []):
        if os.path.normpath(path) in keep:
            if path in (state.get("copied_mo") or []):
                remaining_copied.append(path)
            else:
                remaining_written.append(path)
            continue
        try:
            if os.path.isfile(path):
                os.remove(path)
                stats["removed"] += 1
            lc_dir = os.path.dirname(path)
            loc_dir = os.path.dirname(lc_dir)
            for folder in (lc_dir, loc_dir):
                try:
                    os.rmdir(folder)
                except OSError:
                    pass
        except OSError:
            stats["failed"] += 1
            remaining_written.append(path)
    state["user_written"] = remaining_written
    state["copied_mo"] = remaining_copied


def restore_overlays(progress: Optional[Callable[[str], None]] = None) -> Dict[str, int]:
    """Put official blender.mo files back and remove user overlays."""
    stats = {"restored": 0, "removed": 0, "failed": 0}
    state = _load_state()
    previous = unload_catalogs()
    try:
        for row in list(state.get("system_replaced") or []):
            path = row.get("path") if isinstance(row, dict) else row
            locale = row.get("locale") if isinstance(row, dict) else ""
            if not path:
                continue
            backup = backup_mo_path(locale) if locale else ""
            if (not backup or not os.path.isfile(backup)) and locale:
                backup = backup_mo_path(canonical_locale(str(locale)))
            if not backup or not os.path.isfile(backup):
                parts = os.path.normpath(path).split(os.sep)
                if "LC_MESSAGES" in parts:
                    idx = parts.index("LC_MESSAGES")
                    if idx > 0:
                        backup = backup_mo_path(parts[idx - 1])
            if backup and os.path.isfile(backup) and os.path.isfile(path):
                try:
                    shutil.copy2(backup, path)
                    stats["restored"] += 1
                except OSError:
                    stats["failed"] += 1
                    if progress:
                        progress(f"Could not restore {path}")
            elif backup and os.path.isfile(backup) and not os.path.isfile(path):
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    shutil.copy2(backup, path)
                    stats["restored"] += 1
                except OSError:
                    stats["failed"] += 1

        _purge_user_files(state, keep_paths=set(), stats=stats)

        remaining_junctions = []
        for path in list(state.get("junctions") or []):
            if not os.path.lexists(path):
                continue
            try:
                os.unlink(path)
                stats["removed"] += 1
            except OSError:
                try:
                    os.rmdir(path)
                    stats["removed"] += 1
                except OSError:
                    stats["failed"] += 1
                    remaining_junctions.append(path)
        state["junctions"] = remaining_junctions

        user_root = user_locale_root(create=False)
        if user_root and os.path.isdir(user_root):
            lang_file = os.path.join(user_root, "languages")
            try:
                leftover = os.listdir(user_root)
            except OSError:
                leftover = ["?"]
            if leftover == ["languages"] or leftover == []:
                try:
                    if os.path.isfile(lang_file):
                        os.remove(lang_file)
                    os.rmdir(user_root)
                except OSError:
                    pass

        kept_cache = list(state.get("cache_files") or [])
        _save_state(
            {
                "version": STATE_VERSION,
                "system_replaced": [],
                "user_written": [],
                "junctions": [],
                "copied_mo": [],
                "fingerprint": "",
                "cache_files": kept_cache,
            }
        )
    finally:
        restore_language(previous)
    if progress:
        progress(f"Restored {stats['restored']} official catalogs, removed {stats['removed']} overlays")
    return stats


def redraw_ui() -> None:
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            area.tag_redraw()


def refresh_translations() -> None:
    """Force Blender to re-read interface strings from .mo catalogs."""
    prefs = bpy.context.preferences
    if prefs is None:
        redraw_ui()
        return
    view = prefs.view
    try:
        if hasattr(view, "use_translate_interface"):
            view.use_translate_interface = True
        current = view.language
        view.language = "en_US" if current != "en_US" else "DEFAULT"
        view.language = current
    except Exception:
        pass
    redraw_ui()


def clear_caches() -> None:
    global _locale_index_cache
    _catalog_cache.clear()
    _locale_index_cache = None
