"""Emit recap/locales/*.py from English + native overlays.

Run from repo root: python3 tools/gen_locale_packs.py
"""
from __future__ import annotations

import pickle
import pprint
import re
import sys
from pathlib import Path

re_ph = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from recap.locales import en as en_mod  # noqa: E402
from recap.locales._extras import EXTRA_STAT, EXTRA_UI, EXTRA_MORE  # noqa: E402

OUT = ROOT / "recap" / "locales"
DUMP = ROOT / "tools" / "i18n_base.pkl"
if not DUMP.exists():
    DUMP = Path("/tmp/i18n_dump.pkl")


EN_UI: dict[str, str] = {}
EN_STAT: dict[str, str] = {}


def emit(filename: str, code: str, name: str, native: str, aliases: tuple[str, ...],
         stat: dict, ui: dict, offline: dict | None = None) -> None:
    missing_ui = [k for k in EN_UI if k not in ui]
    missing_stat = [k for k in EN_STAT if k not in stat]
    extra_ph = []
    for key, tmpl in ui.items():
        en_t = EN_UI.get(key)
        if en_t is None:
            extra_ph.append((key, ["<missing en>"], sorted(re_ph.findall(tmpl))))
            continue
        en_ph = set(re_ph.findall(en_t))
        got_ph = set(re_ph.findall(tmpl))
        if en_ph != got_ph:
            extra_ph.append((key, sorted(en_ph), sorted(got_ph)))
    if missing_ui or missing_stat or extra_ph:
        raise SystemExit(
            f"{code} incomplete: ui={missing_ui[:8]} stat={missing_stat} ph={extra_ph[:8]}"
        )
    body = (
        f'"""{name} recap copy — native football register."""\n'
        "from __future__ import annotations\n\n"
        f"CODE = {code!r}\n"
        f"NAME = {name!r}\n"
        f"NATIVE_NAME = {native!r}\n"
        f"ALIASES = {aliases!r}\n"
        "EXPLICIT_FALLBACKS = frozenset()\n\n"
        f"STAT_LABELS = {pprint.pformat(stat, width=96, sort_dicts=True)}\n\n"
        f"UI = {pprint.pformat(ui, width=96, sort_dicts=True)}\n\n"
        f"OFFLINE_LINES = {pprint.pformat(offline or {}, width=96, sort_dicts=True)}\n"
    )
    path = OUT / filename
    path.write_text(body, encoding="utf-8")
    print(f"  wrote {path.name} ({len(ui)} ui, {len(stat)} stat)")


# ---------------------------------------------------------------------------
# STAT overlays
# ---------------------------------------------------------------------------

STAT = {
    "az": {
        **pickle.load(open(DUMP, "rb"))["STAT"]["az"],
        "dribbles_won": "Uğurlu driblinqlər",
        "dispossessed": "Top itkiləri",
        "xg": "xG",
        "xgot": "xGOT",
        "red_cards": "Qırmızı vərəqələr",
    },
    "es": {
        **pickle.load(open(DUMP, "rb"))["STAT"]["es"],
        "dribbles_won": "Regates ganados",
        "dispossessed": "Pérdidas",
        "xg": "xG",
        "xgot": "xGOT",
        "red_cards": "Rojas",
    },
    "ru": {
        **pickle.load(open(DUMP, "rb"))["STAT"]["ru"],
        "dribbles_won": "Обводки",
        "dispossessed": "Потери",
        "xg": "xG",
        "xgot": "xGOT",
        "red_cards": "Удаления",
    },
    "tr": {
        "goals": "Goller", "shots": "Şutlar", "shots_on_target": "Kaleyi bulan",
        "shots_blocked": "Bloklanan", "big_chances": "Net pozisyonlar",
        "pass_share_pct": "Pas payı", "pass_accuracy_pct": "Pas isabeti",
        "touch_share_pct": "Topa dokunma payı", "final_third_passes": "Son üçte pas",
        "box_entry_passes": "Cezaya pas", "penalty_box_touches": "Cezada dokunuş",
        "key_passes": "Kilit pas", "corners": "Kornerler", "fouls": "Fauller",
        "saves": "Kaleci kurtarışları", "blocks": "Bloklar", "tackles_won": "Kazanan müdahale",
        "interceptions": "Top kapma", "offsides": "Ofsaytlar",
        "dribbles_won": "Başarılı çalım", "dispossessed": "Top kaybı",
        "xg": "xG", "xgot": "xGOT", "red_cards": "Kırmızı kart",
    },
    "pt-BR": {
        "goals": "Gols", "shots": "Finalizações", "shots_on_target": "No gol",
        "shots_blocked": "Bloqueados", "big_chances": "Grandes chances",
        "pass_share_pct": "Fatia de passes", "pass_accuracy_pct": "Precisão de passe",
        "touch_share_pct": "Fatia de toques", "final_third_passes": "Passes no terço final",
        "box_entry_passes": "Passes na área", "penalty_box_touches": "Toques na área",
        "key_passes": "Passes decisivos", "corners": "Escanteios", "fouls": "Faltas",
        "saves": "Defesas do goleiro", "blocks": "Bloqueios", "tackles_won": "Desarmes certos",
        "interceptions": "Interceptações", "offsides": "Impedimentos",
        "dribbles_won": "Dribles certos", "dispossessed": "Desarmes sofridos",
        "xg": "xG", "xgot": "xGOT", "red_cards": "Cartões vermelhos",
    },
    "pt-PT": {
        "goals": "Golos", "shots": "Remates", "shots_on_target": "À baliza",
        "shots_blocked": "Bloqueados", "big_chances": "Grandes ocasiões",
        "pass_share_pct": "Quota de passes", "pass_accuracy_pct": "Precisão de passe",
        "touch_share_pct": "Quota de toques", "final_third_passes": "Passes no terço final",
        "box_entry_passes": "Passes para a área", "penalty_box_touches": "Toques na área",
        "key_passes": "Passes-chave", "corners": "Cantos", "fouls": "Faltas",
        "saves": "Defesas do guarda-redes", "blocks": "Bloqueios", "tackles_won": "Desarmes ganhos",
        "interceptions": "Interceptações", "offsides": "Foras de jogo",
        "dribbles_won": "Dribles ganhos", "dispossessed": "Desarmes sofridos",
        "xg": "xG", "xgot": "xGOT", "red_cards": "Cartões vermelhos",
    },
    "fr": {
        "goals": "Buts", "shots": "Tirs", "shots_on_target": "Cadrés",
        "shots_blocked": "Contrés", "big_chances": "Grosses occasions",
        "pass_share_pct": "Part de passes", "pass_accuracy_pct": "Précision de passe",
        "touch_share_pct": "Part de touches", "final_third_passes": "Passes dernier tiers",
        "box_entry_passes": "Passes dans la surface", "penalty_box_touches": "Touches dans la surface",
        "key_passes": "Passes clés", "corners": "Corners", "fouls": "Fautes",
        "saves": "Arrêts du gardien", "blocks": "Contres", "tackles_won": "Tacles gagnés",
        "interceptions": "Interceptions", "offsides": "Hors-jeux",
        "dribbles_won": "Dribbles réussis", "dispossessed": "Ballons perdus",
        "xg": "xG", "xgot": "xGOT", "red_cards": "Cartons rouges",
    },
    "de": {
        "goals": "Tore", "shots": "Abschlüsse", "shots_on_target": "Aufs Tor",
        "shots_blocked": "Geblockt", "big_chances": "Große Chancen",
        "pass_share_pct": "Passanteil", "pass_accuracy_pct": "Passquote",
        "touch_share_pct": "Ballkontakt-Anteil", "final_third_passes": "Pässe im letzten Drittel",
        "box_entry_passes": "Pässe in den Strafraum", "penalty_box_touches": "Kontakte im Strafraum",
        "key_passes": "Schlüsselpässe", "corners": "Ecken", "fouls": "Fouls",
        "saves": "Keeper-Paraden", "blocks": "Blöcke", "tackles_won": "Gewonnene Tacklings",
        "interceptions": "Abfangen", "offsides": "Abseits",
        "dribbles_won": "Gewonnene Dribblings", "dispossessed": "Ballverluste",
        "xg": "xG", "xgot": "xGOT", "red_cards": "Rote Karten",
    },
    "it": {
        "goals": "Gol", "shots": "Tiri", "shots_on_target": "Nello specchio",
        "shots_blocked": "Bloccati", "big_chances": "Grandi occasioni",
        "pass_share_pct": "Quota passaggi", "pass_accuracy_pct": "Precisione passaggi",
        "touch_share_pct": "Quota tocchi", "final_third_passes": "Passaggi ultimo terzo",
        "box_entry_passes": "Passaggi in area", "penalty_box_touches": "Tocchi in area",
        "key_passes": "Passaggi chiave", "corners": "Calci d'angolo", "fouls": "Falli",
        "saves": "Parate del portiere", "blocks": "Blocchi", "tackles_won": "Contrastí vinti",
        "interceptions": "Intercetti", "offsides": "Fuorigioco",
        "dribbles_won": "Dribbling riusciti", "dispossessed": "Palloni persi",
        "xg": "xG", "xgot": "xGOT", "red_cards": "Espulsioni",
    },
    "ar": {
        "goals": "أهداف", "shots": "تسديدات", "shots_on_target": "على المرمى",
        "shots_blocked": "مصدودة", "big_chances": "فرص سانحة",
        "pass_share_pct": "حصة التمرير", "pass_accuracy_pct": "دقة التمرير",
        "touch_share_pct": "حصة اللمسات", "final_third_passes": "تمريرات الثلث الأخير",
        "box_entry_passes": "تمريرات إلى الصندوق", "penalty_box_touches": "لمسات في الصندوق",
        "key_passes": "تمريرات حاسمة", "corners": "ركنيات", "fouls": "أخطاء",
        "saves": "تصديات الحارس", "blocks": "تصديات دفاعية", "tackles_won": "التحامات ناجحة",
        "interceptions": "قطوعات", "offsides": "تسللات",
        "dribbles_won": "مراوغات ناجحة", "dispossessed": "فقد الكرة",
        "xg": "xG", "xgot": "xGOT", "red_cards": "بطاقات حمراء",
    },
    "ja": {
        "goals": "得点", "shots": "シュート", "shots_on_target": "枠内",
        "shots_blocked": "ブロック", "big_chances": "決定機",
        "pass_share_pct": "パス占有", "pass_accuracy_pct": "パス成功率",
        "touch_share_pct": "タッチ占有", "final_third_passes": "最終ラインのパス",
        "box_entry_passes": "ボックスへのパス", "penalty_box_touches": "ボックス内タッチ",
        "key_passes": "キーパス", "corners": "コーナー", "fouls": "ファウル",
        "saves": "キーパーセーブ", "blocks": "ブロック", "tackles_won": "タックル成功",
        "interceptions": "インターセプト", "offsides": "オフサイド",
        "dribbles_won": "ドリブル成功", "dispossessed": "ボールロスト",
        "xg": "xG", "xgot": "xGOT", "red_cards": "退場",
    },
    "ko": {
        "goals": "골", "shots": "슈팅", "shots_on_target": "유효슈팅",
        "shots_blocked": "블록", "big_chances": "결정적 기회",
        "pass_share_pct": "패스 점유", "pass_accuracy_pct": "패스 성공률",
        "touch_share_pct": "터치 점유", "final_third_passes": "최종 3분의 1 패스",
        "box_entry_passes": "박스 진입 패스", "penalty_box_touches": "박스 터치",
        "key_passes": "키패스", "corners": "코너킥", "fouls": "파울",
        "saves": "골키퍼 선방", "blocks": "블록", "tackles_won": "태클 성공",
        "interceptions": "인터셉트", "offsides": "오프사이드",
        "dribbles_won": "드리블 성공", "dispossessed": "볼 손실",
        "xg": "xG", "xgot": "xGOT", "red_cards": "퇴장",
    },
    "hi": {
        "goals": "गोल", "shots": "शॉट्स", "shots_on_target": "ऑन टारगेट",
        "shots_blocked": "ब्लॉक", "big_chances": "बड़े चांस",
        "pass_share_pct": "पास शेयर", "pass_accuracy_pct": "पास सटीकता",
        "touch_share_pct": "टच शेयर", "final_third_passes": "फाइनल थर्ड पास",
        "box_entry_passes": "बॉक्स में पास", "penalty_box_touches": "बॉक्स टच",
        "key_passes": "की-पास", "corners": "कॉर्नर", "fouls": "फाउल",
        "saves": "कीपर सेव", "blocks": "ब्लॉक", "tackles_won": "टैकल जीते",
        "interceptions": "इंटरसेप्शन", "offsides": "ऑफसाइड",
        "dribbles_won": "ड्रिबल सफल", "dispossessed": "बॉल लॉस",
        "xg": "xG", "xgot": "xGOT", "red_cards": "रेड कार्ड",
    },
    "pl": {
        "goals": "Gole", "shots": "Strzały", "shots_on_target": "Celne",
        "shots_blocked": "Zablokowane", "big_chances": "Klarowne sytuacje",
        "pass_share_pct": "Udział nadań", "pass_accuracy_pct": "Celność podań",
        "touch_share_pct": "Udział kontaktów", "final_third_passes": "Podania w tercji",
        "box_entry_passes": "Podania w pole karne", "penalty_box_touches": "Kontakty w polu",
        "key_passes": "Kluczowe podania", "corners": "Rzuty rożne", "fouls": "Faule",
        "saves": "Interwencje bramkarza", "blocks": "Bloki", "tackles_won": "Wygrane odbiory",
        "interceptions": "Przejęcia", "offsides": "Spalone",
        "dribbles_won": "Udane dryblingi", "dispossessed": "Straty",
        "xg": "xG", "xgot": "xGOT", "red_cards": "Czerwone kartki",
    },
    "nl": {
        "goals": "Goals", "shots": "Schoten", "shots_on_target": "Op doel",
        "shots_blocked": "Geblokt", "big_chances": "Grote kansen",
        "pass_share_pct": "Passaandeel", "pass_accuracy_pct": "Passnauwkeurigheid",
        "touch_share_pct": "Balaanrakingen-aandeel", "final_third_passes": "Passes laatste derde",
        "box_entry_passes": "Passes het zestien in", "penalty_box_touches": "Aanrakingen in het zestien",
        "key_passes": "Sleutelpasses", "corners": "Corners", "fouls": "Overtredingen",
        "saves": "Keepersreddingen", "blocks": "Blokken", "tackles_won": "Gewonnen tackles",
        "interceptions": "Onderscheppingen", "offsides": "Buitenspel",
        "dribbles_won": "Geslaagde dribbels", "dispossessed": "Balverlies",
        "xg": "xG", "xgot": "xGOT", "red_cards": "Rode kaarten",
    },
    "uk": {
        "goals": "Голи", "shots": "Удари", "shots_on_target": "У площину",
        "shots_blocked": "Заблоковані", "big_chances": "Гольові моменти",
        "pass_share_pct": "Частка передач", "pass_accuracy_pct": "Точність передач",
        "touch_share_pct": "Частка дотиків", "final_third_passes": "Передачі в фінальній третині",
        "box_entry_passes": "Передачі в штрафний", "penalty_box_touches": "Дотики в штрафному",
        "key_passes": "Ключові передачі", "corners": "Кутові", "fouls": "Фоли",
        "saves": "Сейви воротаря", "blocks": "Блоки", "tackles_won": "Виграні відбори",
        "interceptions": "Перехоплення", "offsides": "Офсайди",
        "dribbles_won": "Вдалі обведення", "dispossessed": "Втрати",
        "xg": "xG", "xgot": "xGOT", "red_cards": "Червоні картки",
    },
}

# Italian typo fix
STAT["it"]["tackles_won"] = "Contrasti vinti"


def _load_dump():
    return pickle.load(open(DUMP, "rb"))


AZ_FIXES = {
    "hook_claim_level_0": "{home} {away} QARŞI.",
    "hook_claim_pin_0": "{team} ONLARI SIĞIŞDIRDI.",
    "bridge_slam_1": "{n}. BUDUR ZƏRBƏ.",
    "bridge_heat_2": "TOXUNUŞ-TOXUNUŞ. SIĞIŞDIRMA.",
    "hook_claim_stoppage_1": "ƏLAVƏ DƏQİQƏ. {team}. BIÇAĞ.",
    "hook_punch_lost_3": "HESAB MARAQLANMADI. SOYDULAR.",
}

ES_FIXES = {
    "hook_punch_lost_0": "AUN ASÍ PERDIERON.",
    "hook_claim_xg_1": "{n} xG. Y FUE UN ATRACO.",
    "hook_claim_stoppage_1": "EL DESCUENTO. {team}. EL CIERRE.",
    "hook_claim_keeper_2": "EL PORTERO ROBÓ LA NOCHE.",
}

RU_FIXES = {
    "hook_punch_lost_3": "ТАБЛО БЫЛО БЕЗРАЗЛИЧНО. ОБНЕСЛИ.",
    "hook_claim_xg_1": "{n} xG. МАТЧ УКРАЛИ.",
    "hook_claim_stoppage_1": "КОМПЕНСАЦИЯ. {team}. НОЖ.",
    "hook_claim_keeper_2": "ВРАТАРЬ УКРАЛ ВЕЧЕР.",
}


def _existing(code: str, extra: dict, fixes: dict) -> tuple[dict, dict, dict]:
    dump = _load_dump()
    ui = dict(dump["UI"][code])
    ui.update(extra)
    ui.update(fixes)
    stat = dict(STAT[code])
    offline = dict(dump["OFFLINE"].get(code) or {})
    return ui, stat, offline


def _finish(ui: dict, extra: dict, more: dict) -> dict:
    """English extras fill gaps; native overlays always win."""
    out = dict(ui)
    for key, value in EXTRA_UI.items():
        out.setdefault(key, value)
    for key, value in EXTRA_MORE.items():
        out.setdefault(key, value)
    out.update(extra)
    out.update(more)
    return out


def main() -> None:
    global EN_UI, EN_STAT
    from tools.locale_extra_ui import AZ_EXTRA, ES_EXTRA, RU_EXTRA
    from tools.locale_extra_rows import PT_BR, TR
    from tools.locale_extra_rows_eu import DE, FR, IT
    from tools.locale_extra_rows_west import NL as NL_X, PL as PL_X, PT_PT, european_pt
    from tools.locale_extra_rows_asia import AR as AR_X, HI as HI_X, JA as JA_X, KO as KO_X, UK as UK_X
    from tools.locale_extra_more import MORE as MORE35
    from tools.locale_base_rows import BASE as BASE_CORE
    from tools.locale_base_eu import DE as DE_B, FR as FR_B, IT as IT_B, NL as NL_B, PL as PL_B
    from tools.locale_base_east import AR as AR_B, HI as HI_B, JA as JA_B, KO as KO_B, UK as UK_B

    dump = _load_dump()
    EN_UI = dict(dump["UI"]["en"])
    EN_UI.update(EXTRA_UI)
    EN_UI.update(EXTRA_MORE)
    EN_STAT = dict(dump["STAT"]["en"])
    EN_STAT.update(EXTRA_STAT)

    emit("en.py", "en", "English", "English",
         ("en", "eng", "english"), EN_STAT, EN_UI, {})

    az_ui, az_stat, az_off = _existing("az", AZ_EXTRA, AZ_FIXES)
    emit("az.py", "az", "Azerbaijani", "Azərbaycan",
         ("az", "aze", "azerbaijani", "azeri"), az_stat, _finish(az_ui, AZ_EXTRA, MORE35["az"]), az_off)
    es_ui, es_stat, es_off = _existing("es", ES_EXTRA, ES_FIXES)
    emit("es.py", "es", "Spanish", "Español",
         ("es", "spa", "spanish", "español", "espanol"), es_stat, _finish(es_ui, ES_EXTRA, MORE35["es"]), es_off)
    ru_ui, ru_stat, ru_off = _existing("ru", RU_EXTRA, RU_FIXES)
    emit("ru.py", "ru", "Russian", "Русский",
         ("ru", "rus", "russian"), ru_stat, _finish(ru_ui, RU_EXTRA, MORE35["ru"]), ru_off)

    BASE = {
        **BASE_CORE,
        "fr": FR_B, "de": DE_B, "it": IT_B, "nl": NL_B, "pl": PL_B,
        "ar": AR_B, "ja": JA_B, "ko": KO_B, "hi": HI_B, "uk": UK_B,
        "pt-PT": european_pt(BASE_CORE["pt-BR"]),
    }
    extras = {
        "tr": TR, "pt-BR": PT_BR, "pt-PT": PT_PT,
        "fr": FR, "de": DE, "it": IT, "nl": NL_X, "pl": PL_X,
        "ar": AR_X, "ja": JA_X, "ko": KO_X, "hi": HI_X, "uk": UK_X,
    }
    meta = {
        "tr": ("tr.py", "tr", "Turkish", "Türkçe", ("tr", "tur", "turkish", "turkce", "türkçe")),
        "pt-BR": ("pt_br.py", "pt-BR", "Portuguese (Brazil)", "Português (Brasil)",
                  ("pt-BR", "ptbr", "pt-br", "pt_br", "pt", "brazilian")),
        "pt-PT": ("pt_pt.py", "pt-PT", "Portuguese (Portugal)", "Português (Portugal)",
                  ("pt-PT", "ptpt", "pt-pt", "pt_pt")),
        "fr": ("fr.py", "fr", "French", "Français", ("fr", "fra", "fre", "french", "francais")),
        "de": ("de.py", "de", "German", "Deutsch", ("de", "ger", "deu", "german", "deutsch")),
        "it": ("it.py", "it", "Italian", "Italiano", ("it", "ita", "italian", "italiano")),
        "ar": ("ar.py", "ar", "Arabic", "العربية", ("ar", "ara", "arabic")),
        "ja": ("ja.py", "ja", "Japanese", "日本語", ("ja", "jpn", "jp", "japanese")),
        "ko": ("ko.py", "ko", "Korean", "한국어", ("ko", "kor", "kr", "korean")),
        "hi": ("hi.py", "hi", "Hindi", "हिन्दी", ("hi", "hin", "hindi")),
        "pl": ("pl.py", "pl", "Polish", "Polski", ("pl", "pol", "polish")),
        "nl": ("nl.py", "nl", "Dutch", "Nederlands", ("nl", "dut", "nld", "dutch")),
        "uk": ("uk.py", "uk", "Ukrainian", "Українська", ("uk", "ukr", "ua", "ukrainian")),
    }
    for code, extra in extras.items():
        if code not in BASE:
            print(f"  skip {code}: no BASE overlay yet")
            continue
        ui = dict(EN_UI)
        ui.update(BASE[code])
        ui.update(extra)
        ui.update(MORE35.get(code, {}))
        filename, c, name, native, aliases = meta[code]
        emit(filename, c, name, native, aliases, STAT[code], ui, {})


if __name__ == "__main__":
    main()

