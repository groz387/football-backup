"""Locale pack loader."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from typing import Any

from . import _extras

# Canonical codes in attention-market order.
LOCALE_MODULES = {
    "en": "recap.locales.en",
    "az": "recap.locales.az",
    "es": "recap.locales.es",
    "tr": "recap.locales.tr",
    "pt-BR": "recap.locales.pt_br",
    "pt-PT": "recap.locales.pt_pt",
    "fr": "recap.locales.fr",
    "de": "recap.locales.de",
    "it": "recap.locales.it",
    "ar": "recap.locales.ar",
    "ru": "recap.locales.ru",
    "uk": "recap.locales.uk",
    "pl": "recap.locales.pl",
    "nl": "recap.locales.nl",
    "ja": "recap.locales.ja",
    "ko": "recap.locales.ko",
    "hi": "recap.locales.hi",
}


@dataclass(frozen=True)
class LocalePack:
    code: str
    name: str
    native_name: str
    aliases: tuple[str, ...]
    stat_labels: dict[str, str]
    ui: dict[str, str]
    offline_lines: dict[str, str] = field(default_factory=dict)
    explicit_fallbacks: frozenset[str] = field(default_factory=frozenset)

    def ui_key_set(self) -> set[str]:
        return set(self.ui) | set(self.explicit_fallbacks)

    def stat_key_set(self) -> set[str]:
        return set(self.stat_labels) | set(self.explicit_fallbacks)


def _merged_ui(mod: Any) -> dict[str, str]:
    ui = dict(getattr(_extras, "EXTRA_UI", {}) or {})
    ui.update(getattr(_extras, "EXTRA_MORE", {}) or {})
    ui.update(getattr(_extras, "POLISH_UI", {}) or {})
    ui.update(dict(mod.UI))
    return ui


def _from_module(mod: Any) -> LocalePack:
    return LocalePack(
        code=str(mod.CODE),
        name=str(mod.NAME),
        native_name=str(getattr(mod, "NATIVE_NAME", mod.NAME)),
        aliases=tuple(mod.ALIASES),
        stat_labels=dict(mod.STAT_LABELS),
        ui=_merged_ui(mod),
        offline_lines=dict(getattr(mod, "OFFLINE_LINES", {}) or {}),
        explicit_fallbacks=frozenset(getattr(mod, "EXPLICIT_FALLBACKS", ()) or ()),
    )


_CACHE: dict[str, LocalePack] = {}


def load_pack(code: str) -> LocalePack:
    if code in _CACHE:
        return _CACHE[code]
    mod_name = LOCALE_MODULES.get(code)
    if not mod_name:
        raise KeyError(code)
    pack = _from_module(import_module(mod_name))
    _CACHE[code] = pack
    return pack


def available_codes() -> tuple[str, ...]:
    found = []
    for code, mod_name in LOCALE_MODULES.items():
        try:
            load_pack(code)
        except (ImportError, ModuleNotFoundError, KeyError):
            continue
        found.append(code)
    return tuple(found)


def all_packs() -> dict[str, LocalePack]:
    return {code: load_pack(code) for code in available_codes()}


def clear_cache() -> None:
    _CACHE.clear()
