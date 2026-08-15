"""UI and script localization for match-recap videos.

English remains the source of truth for deterministic copy. Non-English runs:

1. Swap every chrome / stat / legend label from the catalogs below.
2. Rewrite free-form titles, insights and narration into the target language
   (Gemini when available; otherwise a conservative offline pass that keeps
   numbers and proper nouns intact and translates known template lines).

Supported codes: ``en``, ``az``, ``es``, ``ru``.
"""

from __future__ import annotations

import re
from typing import Any

SUPPORTED = ("en", "az", "es", "ru")
ALIASES = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "az": "az",
    "aze": "az",
    "azerbaijani": "az",
    "azeri": "az",
    "es": "es",
    "spa": "es",
    "spanish": "es",
    "español": "es",
    "espanol": "es",
    "ru": "ru",
    "rus": "ru",
    "russian": "ru",
}

LANGUAGE_NAMES = {
    "en": "English",
    "az": "Azerbaijani",
    "es": "Spanish",
    "ru": "Russian",
}

_current = "en"


def normalize_language(value: str | None) -> str:
    raw = (value or "en").strip().lower()
    code = ALIASES.get(raw)
    if code is None:
        raise ValueError(
            f"Unsupported language {value!r}. Choose one of: {', '.join(SUPPORTED)}"
        )
    return code


def set_language(code: str) -> str:
    global _current
    _current = normalize_language(code)
    return _current


def get_language() -> str:
    return _current


def language_name(code: str | None = None) -> str:
    return LANGUAGE_NAMES.get(code or _current, "English")


# ---------------------------------------------------------------------------
# catalogs
# ---------------------------------------------------------------------------

STAT_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "goals": "Goals",
        "shots": "Shots",
        "shots_on_target": "On target",
        "shots_blocked": "Blocked",
        "big_chances": "Big chances",
        "pass_share_pct": "Pass share",
        "pass_accuracy_pct": "Pass accuracy",
        "touch_share_pct": "Touch share",
        "final_third_passes": "Final-third passes",
        "box_entry_passes": "Passes into the box",
        "penalty_box_touches": "Box touches",
        "key_passes": "Chances created",
        "corners": "Corners",
        "fouls": "Fouls",
        "saves": "Keeper saves",
        "blocks": "Blocks",
        "tackles_won": "Tackles won",
        "interceptions": "Interceptions",
        "offsides": "Offsides",
    },
    "az": {
        "goals": "Qollar",
        "shots": "Zərbələr",
        "shots_on_target": "Çərçivəyə",
        "shots_blocked": "Bloklanan",
        "big_chances": "Böyük şanslar",
        "pass_share_pct": "Pas payı",
        "pass_accuracy_pct": "Pas dəqiqliyi",
        "touch_share_pct": "Toxunuş payı",
        "final_third_passes": "Hücum üçdə biri",
        "box_entry_passes": "Cəriməyə paslar",
        "penalty_box_touches": "Cərimə toxunuşları",
        "key_passes": "Yaradılan şanslar",
        "corners": "Künc zərbələri",
        "fouls": "Follar",
        "saves": "Qapıçı seyvləri",
        "blocks": "Bloklar",
        "tackles_won": "Qazanılan mübarizələr",
        "interceptions": "Tutmalar",
        "offsides": "Ofsaydlar",
    },
    "es": {
        "goals": "Goles",
        "shots": "Tiros",
        "shots_on_target": "A puerta",
        "shots_blocked": "Bloqueados",
        "big_chances": "Grandes ocasiones",
        "pass_share_pct": "Cuota de pases",
        "pass_accuracy_pct": "Precisión de pase",
        "touch_share_pct": "Cuota de toques",
        "final_third_passes": "Pases en último tercio",
        "box_entry_passes": "Pases al área",
        "penalty_box_touches": "Toques en el área",
        "key_passes": "Ocasiones creadas",
        "corners": "Córners",
        "fouls": "Faltas",
        "saves": "Paradas",
        "blocks": "Bloqueos",
        "tackles_won": "Entradas ganadas",
        "interceptions": "Intercepciones",
        "offsides": "Fueras de juego",
    },
    "ru": {
        "goals": "Голы",
        "shots": "Удары",
        "shots_on_target": "В створ",
        "shots_blocked": "Заблокированные",
        "big_chances": "Острые моменты",
        "pass_share_pct": "Доля передач",
        "pass_accuracy_pct": "Точность передач",
        "touch_share_pct": "Доля касаний",
        "final_third_passes": "Передачи в финальной трети",
        "box_entry_passes": "Передачи в штрафную",
        "penalty_box_touches": "Касания в штрафной",
        "key_passes": "Созданные моменты",
        "corners": "Угловые",
        "fouls": "Фолы",
        "saves": "Сейвы вратаря",
        "blocks": "Блоки",
        "tackles_won": "Отборы",
        "interceptions": "Перехваты",
        "offsides": "Офсайды",
    },
}

UI: dict[str, dict[str, str]] = {
    "en": {
        "watermark": "EVENT DATA RECAP",
        "match_recap": "MATCH RECAP",
        "the_baseline": "THE BASELINE",
        "full_time": "FULL TIME",
        "after_extra_time": "AFTER EXTRA TIME",
        "on_penalties": "ON PENALTIES",
        "goals": "GOALS",
        "no_goals": "NO GOALS",
        "no_goals_in_match": "NO GOALS IN THIS MATCH",
        "shots_none_counted": "{shots} SHOTS, NONE OF THEM COUNTED",
        "attacking_up": "ATTACKING UP",
        "attacking_down": "ATTACKING DOWN",
        "shots_on_target_line": "{shots} SHOTS / {on_target} ON TARGET",
        "markers_team_colour": "MARKERS TAKE EACH TEAM'S COLOUR",
        "pressure_curve_empty": "NOT ENOUGH EVENTS FOR A PRESSURE CURVE",
        "attacking_pressure": "ATTACKING PRESSURE PER 5 MINUTES",
        "no_touch_coords": "NO TOUCH COORDINATES IN THIS EXPORT",
        "passes": "PASSES",
        "metres": "METRES",
        "goal": "GOAL",
        "too_few_shots_frame": "TOO FEW SHOTS REACHED THE FRAME",
        "scored_n": "{n} SCORED",
        "all_stopped": "ALL STOPPED",
        "shots_reached_target": "SHOTS THAT REACHED THE TARGET",
        "count_per_zones": "COUNT PER SIX ZONES",
        "not_enough_passes": "NOT ENOUGH PASSES FOR A NETWORK",
        "completed": "COMPLETED",
        "accuracy": "ACCURACY",
        "final_third": "FINAL THIRD",
        "into_the_box": "INTO THE BOX",
        "attacking_up_with_team": "{team}  /  ATTACKING UP",
        "pass_share": "Pass share",
        "final_third_short": "Final third",
        "into_box_short": "Into the box",
        "outcome_goal": "Goal",
        "outcome_saved": "Saved",
        "outcome_off_target": "Off target",
        "outcome_blocked": "Blocked",
        "outcome_woodwork": "Woodwork",
        "period_first_half": "First half",
        "period_second_half": "Second half",
        "period_extra_time": "Extra time",
        "period_extra_time_1": "Extra time 1",
        "period_extra_time_2": "Extra time 2",
        "boundary_ht": "HT",
        "boundary_ft": "FT",
        "boundary_et": "ET",
        "peak": "PEAK {block}",
        "build_up": "BUILD-UP",
        "sub_shot_map": "Every attempt, by outcome",
        "sub_momentum": "{home} above the line, {away} below",
        "sub_zone": "Touch volume across eighteen zones",
        "sub_goalmouth": "Where on-target shots crossed the line",
        "sub_pass_network": "Average positions and strongest links",
        "sub_sterile": "Pass share against what it produced",
        "hook_needed_minutes": "{team} NEEDED {n} MINUTES",
        "hook_ran_riot": "{team} RAN RIOT",
        "hook_found_a_way": "{team} FOUND A WAY",
        "hook_extra_time": "{team} NEEDED EXTRA TIME",
        "hook_shootout": "{team} SURVIVE THE SHOOTOUT",
        "hook_goals_take_it": "{n} GOALS, {team} TAKE IT",
        "hook_nobody_blinked": "NOBODY BLINKED",
        "hook_honours_even": "HONOURS EVEN AT {score}",
        "hook_stat_on_target": "{n} ON TARGET",
        "hook_stat_big_chances": "{n} BIG CHANCES",
        "hook_stat_shots": "{n} SHOTS",
        "hook_stat_margin": "{n} GOALS CLEAR",
        "hook_had_more_shots": "{team} HAD MORE SHOTS.",
        "hook_had_more_corners": "{team} HAD MORE CORNERS.",
        "hook_had_more_blocked": "{team} HAD MORE BLOCKED SHOTS.",
        "hook_had_more_chances": "{team} HAD MORE BIG CHANCES.",
        "hook_had_more_box": "{team} HAD MORE TOUCHES IN THE BOX.",
        "hook_had_more_pressure": "{team} HAD MORE PRESSURE.",
        "hook_more_shots": "MORE SHOTS.",
        "hook_more_corners": "MORE CORNERS.",
        "hook_more_blocked": "MORE BLOCKED SHOTS.",
        "hook_more_chances": "MORE BIG CHANCES.",
        "hook_more_box": "MORE TOUCHES IN THE BOX.",
        "hook_more_pressure": "MORE PRESSURE.",
        "hook_still_lost": "THEY STILL LOST.",
        "hook_still_level": "IT STILL FINISHED LEVEL.",
        "hook_nobody_scored": "AND NOBODY SCORED.",
        "hook_one_moment": "ONE MOMENT DECIDED IT.",
        "hook_then_it_was_over": "THEN IT WAS OVER.",
        "hook_turned_late": "THE MATCH TURNED IN THE {n}TH MINUTE.",
        "hook_had_the_ball": "{team} HAD THE BALL.",
        "hook_not_the_chances": "NOT THE CHANCES.",
        "hook_n_shots": "{n} SHOTS.",
    },
    "az": {
        "watermark": "HADİSƏ VERİLƏRİ",
        "match_recap": "MATÇ XÜLASƏSİ",
        "the_baseline": "ƏSAS GÖSTƏRİCİLƏR",
        "full_time": "OYUN SONU",
        "after_extra_time": "ƏLAVƏ VAXTDAN SONRA",
        "on_penalties": "PENALTİLƏRLƏ",
        "goals": "QOLLAR",
        "no_goals": "QOL YOXDUR",
        "no_goals_in_match": "BU MATÇDA QOL OLMAYIB",
        "shots_none_counted": "{shots} ZƏRBƏ, HEÇ BİRİ QOL OLMADI",
        "attacking_up": "YUXARI HÜCUM",
        "attacking_down": "AŞAĞI HÜCUM",
        "shots_on_target_line": "{shots} ZƏRBƏ / {on_target} ÇƏRÇİVƏYƏ",
        "markers_team_colour": "İŞARƏLƏR KOMANDA RƏNGİNDƏDİR",
        "pressure_curve_empty": "TƏZYİQ ƏYRİSİ ÜÇÜN KİFAYƏT HADİSƏ YOXDUR",
        "attacking_pressure": "5 DƏQİQƏLİK HÜCUM TƏZYİQİ",
        "no_touch_coords": "BU EKSPORTDA TOXUNUŞ KOORDİNATI YOXDUR",
        "passes": "PASLAR",
        "metres": "METR",
        "goal": "QOL",
        "too_few_shots_frame": "ÇƏRÇİVƏYƏ AZ ZƏRBƏ ÇATIB",
        "scored_n": "{n} QOL",
        "all_stopped": "HAMISI DAYANDIRILDI",
        "shots_reached_target": "HƏDƏFƏ ÇATAN ZƏRBƏLƏR",
        "count_per_zones": "ALTİ ZONA ÜZRƏ SAY",
        "not_enough_passes": "ŞƏBƏKƏ ÜÇÜN KİFAYƏT PAS YOXDUR",
        "completed": "UĞURLU",
        "accuracy": "DƏQİQLİK",
        "final_third": "HÜCUM ÜÇDƏ BİRİ",
        "into_the_box": "CƏRİMƏYƏ",
        "attacking_up_with_team": "{team}  /  YUXARI HÜCUM",
        "pass_share": "Pas payı",
        "final_third_short": "Hücum üçdə biri",
        "into_box_short": "Cəriməyə",
        "outcome_goal": "Qol",
        "outcome_saved": "Seyv",
        "outcome_off_target": "Kənar",
        "outcome_blocked": "Blok",
        "outcome_woodwork": "Dirək",
        "period_first_half": "Birinci hissə",
        "period_second_half": "İkinci hissə",
        "period_extra_time": "Əlavə vaxt",
        "period_extra_time_1": "Əlavə vaxt 1",
        "period_extra_time_2": "Əlavə vaxt 2",
        "boundary_ht": "HT",
        "boundary_ft": "FT",
        "boundary_et": "ET",
        "peak": "PİK {block}",
        "build_up": "QURULUŞ",
        "sub_shot_map": "Hər cəhd, nəticəsinə görə",
        "sub_momentum": "{home} xəttin üstündə, {away} altında",
        "sub_zone": "On səkkiz zona üzrə toxunuşlar",
        "sub_goalmouth": "Çərçivəyə zərbələrin keçdiyi yer",
        "sub_pass_network": "Orta mövqelər və ən güclü əlaqələr",
        "sub_sterile": "Pas payı və onun nəticəsi",
        "hook_needed_minutes": "{team} {n} DƏQİQƏYƏ BİTİRDİ",
        "hook_ran_riot": "{team} DAĞITDI",
        "hook_found_a_way": "{team} YOL TAPDI",
        "hook_extra_time": "{team} ƏLAVƏ VAXT LAZIM OLDU",
        "hook_shootout": "{team} PENALTİLƏRDƏ QALİB",
        "hook_goals_take_it": "{n} QOL, {team} APARIR",
        "hook_nobody_blinked": "HEÇ KİM GERİ ÇƏKİLMƏDİ",
        "hook_honours_even": "HESAB BƏRABƏR: {score}",
        "hook_stat_on_target": "{n} ÇƏRÇİVƏYƏ",
        "hook_stat_big_chances": "{n} BÖYÜK ŞANS",
        "hook_stat_shots": "{n} ZƏRBƏ",
        "hook_stat_margin": "{n} QOL FƏRQİ",
        "hook_had_more_shots": "{team} DAHA ÇOX ZƏRBƏ ENDİRDİ.",
        "hook_had_more_corners": "{team} DAHA ÇOX KÜNC VURDU.",
        "hook_had_more_blocked": "{team} DAHA ÇOX BLOKLANAN ZƏRBƏSİ VARDI.",
        "hook_had_more_chances": "{team} DAHA ÇOX BÖYÜK ŞANSI VARDI.",
        "hook_had_more_box": "{team} CƏRİMƏDƏ DAHA ÇOX TOXUNDU.",
        "hook_had_more_pressure": "{team} DAHA ÇOX TƏZYİQ GÖSTƏRDİ.",
        "hook_more_shots": "DAHA ÇOX ZƏRBƏ.",
        "hook_more_corners": "DAHA ÇOX KÜNC.",
        "hook_more_blocked": "DAHA ÇOX BLOKLANAN ZƏRBƏ.",
        "hook_more_chances": "DAHA ÇOX BÖYÜK ŞANS.",
        "hook_more_box": "CƏRİMƏDƏ DAHA ÇOX TOXUNUŞ.",
        "hook_more_pressure": "DAHA ÇOX TƏZYİQ.",
        "hook_still_lost": "YENƏ UDUZDULAR.",
        "hook_still_level": "YENƏ HESAB BƏRABƏR QALDI.",
        "hook_nobody_scored": "VƏ HEÇ KİM QOL VURMADI.",
        "hook_one_moment": "BİR AN QƏRAR VERDİ.",
        "hook_then_it_was_over": "SONRA HƏR ŞEY BİTDİ.",
        "hook_turned_late": "OYUN {n}-Cİ DƏQİQƏDƏ DÖNDÜ.",
        "hook_had_the_ball": "{team} TOPA SAHİB İDİ.",
        "hook_not_the_chances": "ŞANSLARA YOX.",
        "hook_n_shots": "{n} ZƏRBƏ.",
    },
    "es": {
        "watermark": "DATOS DE EVENTOS",
        "match_recap": "RESUMEN DEL PARTIDO",
        "the_baseline": "LA BASE",
        "full_time": "FINAL",
        "after_extra_time": "TRAS LA PRÓRROGA",
        "on_penalties": "EN PENALTIS",
        "goals": "GOLES",
        "no_goals": "SIN GOLES",
        "no_goals_in_match": "NO HUBO GOLES EN ESTE PARTIDO",
        "shots_none_counted": "{shots} TIROS, NINGUNO ENTRÓ",
        "attacking_up": "ATAQUE ARRIBA",
        "attacking_down": "ATAQUE ABAJO",
        "shots_on_target_line": "{shots} TIROS / {on_target} A PUERTA",
        "markers_team_colour": "LOS MARCADORES USAN EL COLOR DEL EQUIPO",
        "pressure_curve_empty": "NO HAY EVENTOS PARA LA CURVA DE PRESIÓN",
        "attacking_pressure": "PRESIÓN OFENSIVA CADA 5 MINUTOS",
        "no_touch_coords": "NO HAY COORDENADAS DE TOQUES EN ESTE EXPORT",
        "passes": "PASES",
        "metres": "METROS",
        "goal": "GOL",
        "too_few_shots_frame": "DEMASIADOS POCOS TIROS LLEGARON AL MARCO",
        "scored_n": "{n} GOLES",
        "all_stopped": "TODOS DETENIDOS",
        "shots_reached_target": "TIROS QUE LLEGARON A PUERTA",
        "count_per_zones": "CONTEO POR SEIS ZONAS",
        "not_enough_passes": "NO HAY PASES SUFICIENTES PARA LA RED",
        "completed": "COMPLETADOS",
        "accuracy": "PRECISIÓN",
        "final_third": "ÚLTIMO TERCIO",
        "into_the_box": "AL ÁREA",
        "attacking_up_with_team": "{team}  /  ATAQUE ARRIBA",
        "pass_share": "Cuota de pases",
        "final_third_short": "Último tercio",
        "into_box_short": "Al área",
        "outcome_goal": "Gol",
        "outcome_saved": "Parada",
        "outcome_off_target": "Fuera",
        "outcome_blocked": "Bloqueado",
        "outcome_woodwork": "Palo",
        "period_first_half": "Primera parte",
        "period_second_half": "Segunda parte",
        "period_extra_time": "Prórroga",
        "period_extra_time_1": "Prórroga 1",
        "period_extra_time_2": "Prórroga 2",
        "boundary_ht": "HT",
        "boundary_ft": "FT",
        "boundary_et": "ET",
        "peak": "PICO {block}",
        "build_up": "JUGADA",
        "sub_shot_map": "Cada intento, por resultado",
        "sub_momentum": "{home} por encima, {away} por debajo",
        "sub_zone": "Toques en dieciocho zonas",
        "sub_goalmouth": "Dónde cruzaron la línea los tiros a puerta",
        "sub_pass_network": "Posiciones medias y enlaces más fuertes",
        "sub_sterile": "Cuota de pases frente a lo que produjo",
        "hook_needed_minutes": "{team} LO CERRÓ EN {n} MINUTOS",
        "hook_ran_riot": "{team} ARRASÓ",
        "hook_found_a_way": "{team} ENCONTRÓ EL CAMINO",
        "hook_extra_time": "{team} NECESITÓ LA PRÓRROGA",
        "hook_shootout": "{team} SUPERÓ LOS PENALTIS",
        "hook_goals_take_it": "{n} GOLES, {team} SE LO LLEVA",
        "hook_nobody_blinked": "NADIE PARPADEÓ",
        "hook_honours_even": "EMPATE A {score}",
        "hook_stat_on_target": "{n} A PUERTA",
        "hook_stat_big_chances": "{n} GRANDES OCASIONES",
        "hook_stat_shots": "{n} TIROS",
        "hook_stat_margin": "{n} GOLES DE MARGEN",
        "hook_had_more_shots": "{team} TUVO MÁS TIROS.",
        "hook_had_more_corners": "{team} TUVO MÁS CÓRNERS.",
        "hook_had_more_blocked": "{team} TUVO MÁS TIROS BLOQUEADOS.",
        "hook_had_more_chances": "{team} TUVO MÁS GRANDES OCASIONES.",
        "hook_had_more_box": "{team} TOCÓ MÁS EN EL ÁREA.",
        "hook_had_more_pressure": "{team} TUVO MÁS PRESIÓN.",
        "hook_more_shots": "MÁS TIROS.",
        "hook_more_corners": "MÁS CÓRNERS.",
        "hook_more_blocked": "MÁS TIROS BLOQUEADOS.",
        "hook_more_chances": "MÁS GRANDES OCASIONES.",
        "hook_more_box": "MÁS TOQUES EN EL ÁREA.",
        "hook_more_pressure": "MÁS PRESIÓN.",
        "hook_still_lost": "AUN ASÍ PERDIERON.",
        "hook_still_level": "AUN ASÍ TERMINÓ EN EMPATE.",
        "hook_nobody_scored": "Y NADIE MARCÓ.",
        "hook_one_moment": "UN MOMENTO LO DECIDIÓ.",
        "hook_then_it_was_over": "Y SE ACABÓ.",
        "hook_turned_late": "EL PARTIDO GIRÓ EN EL MINUTO {n}.",
        "hook_had_the_ball": "{team} TUVO EL BALÓN.",
        "hook_not_the_chances": "NO LAS OCASIONES.",
        "hook_n_shots": "{n} TIROS.",
    },
    "ru": {
        "watermark": "СОБЫТИЙНЫЕ ДАННЫЕ",
        "match_recap": "ОБЗОР МАТЧА",
        "the_baseline": "БАЗОВЫЕ ПОКАЗАТЕЛИ",
        "full_time": "ФИНАЛ",
        "after_extra_time": "ПОСЛЕ ДОПОЛНИТЕЛЬНОГО ВРЕМЕНИ",
        "on_penalties": "ПО ПЕНАЛЬТИ",
        "goals": "ГОЛЫ",
        "no_goals": "БЕЗ ГОЛОВ",
        "no_goals_in_match": "В ЭТОМ МАТЧЕ НЕ БЫЛО ГОЛОВ",
        "shots_none_counted": "{shots} УДАРОВ, НИ ОДИН НЕ ЗАСЧИТАН",
        "attacking_up": "АТАКА ВВЕРХ",
        "attacking_down": "АТАКА ВНИЗ",
        "shots_on_target_line": "{shots} УДАРОВ / {on_target} В СТВОР",
        "markers_team_colour": "МАРКЕРЫ В ЦВЕТАХ КОМАНД",
        "pressure_curve_empty": "НЕДОСТАТОЧНО СОБЫТИЙ ДЛЯ КРИВОЙ ДАВЛЕНИЯ",
        "attacking_pressure": "АТАКУЮЩЕЕ ДАВЛЕНИЕ ПО 5 МИНУТ",
        "no_touch_coords": "В ЭКСПОРТЕ НЕТ КООРДИНАТ КАСАНИЙ",
        "passes": "ПАСЫ",
        "metres": "МЕТРЫ",
        "goal": "ГОЛ",
        "too_few_shots_frame": "СЛИШКОМ МАЛО УДАРОВ ДОШЛО ДО РАМКИ",
        "scored_n": "{n} ГОЛОВ",
        "all_stopped": "ВСЕ ОТРАЖЕНЫ",
        "shots_reached_target": "УДАРЫ, ДОШЕДШИЕ ДО СТВОРА",
        "count_per_zones": "СЧЁТ ПО ШЕСТИ ЗОНАМ",
        "not_enough_passes": "НЕДОСТАТОЧНО ПАСОВ ДЛЯ СЕТИ",
        "completed": "ТОЧНЫЕ",
        "accuracy": "ТОЧНОСТЬ",
        "final_third": "ФИНАЛЬНАЯ ТРЕТЬ",
        "into_the_box": "В ШТРАФНУЮ",
        "attacking_up_with_team": "{team}  /  АТАКА ВВЕРХ",
        "pass_share": "Доля передач",
        "final_third_short": "Финальная треть",
        "into_box_short": "В штрафную",
        "outcome_goal": "Гол",
        "outcome_saved": "Сейв",
        "outcome_off_target": "Мимо",
        "outcome_blocked": "Блок",
        "outcome_woodwork": "Штанга",
        "period_first_half": "Первый тайм",
        "period_second_half": "Второй тайм",
        "period_extra_time": "Доп. время",
        "period_extra_time_1": "Доп. время 1",
        "period_extra_time_2": "Доп. время 2",
        "boundary_ht": "HT",
        "boundary_ft": "FT",
        "boundary_et": "ET",
        "peak": "ПИК {block}",
        "build_up": "РОЗЫГРЫШ",
        "sub_shot_map": "Каждый удар — по исходу",
        "sub_momentum": "{home} выше линии, {away} ниже",
        "sub_zone": "Касания по восемнадцати зонам",
        "sub_goalmouth": "Где удары в створ пересекли линию",
        "sub_pass_network": "Средние позиции и сильные связи",
        "sub_sterile": "Доля передач и что из этого вышло",
        "hook_needed_minutes": "{team} РЕШИЛИ ЗА {n} МИНУТ",
        "hook_ran_riot": "{team} УСТРОИЛИ РАЗГРОМ",
        "hook_found_a_way": "{team} НАШЛИ СПОСОБ",
        "hook_extra_time": "{team} ПОНАДОБИЛОСЬ ДОП. ВРЕМЯ",
        "hook_shootout": "{team} ВЫСТОЯЛИ В ПЕНАЛЬТИ",
        "hook_goals_take_it": "{n} ГОЛОВ, {team} ЗАБИРАЮТ",
        "hook_nobody_blinked": "НИКТО НЕ МОРГНУЛ",
        "hook_honours_even": "НИЧЬЯ {score}",
        "hook_stat_on_target": "{n} В СТВОР",
        "hook_stat_big_chances": "{n} ОСТРЫХ МОМЕНТОВ",
        "hook_stat_shots": "{n} УДАРОВ",
        "hook_stat_margin": "{n} ГОЛА РАЗНИЦЫ",
        "hook_had_more_shots": "У {team} БОЛЬШЕ УДАРОВ.",
        "hook_had_more_corners": "У {team} БОЛЬШЕ УГЛОВЫХ.",
        "hook_had_more_blocked": "У {team} БОЛЬШЕ ЗАБЛОКИРОВАННЫХ УДАРОВ.",
        "hook_had_more_chances": "У {team} БОЛЬШЕ ОСТРЫХ МОМЕНТОВ.",
        "hook_had_more_box": "У {team} БОЛЬШЕ КАСАНИЙ В ШТРАФНОЙ.",
        "hook_had_more_pressure": "У {team} БОЛЬШЕ ДАВЛЕНИЯ.",
        "hook_more_shots": "БОЛЬШЕ УДАРОВ.",
        "hook_more_corners": "БОЛЬШЕ УГЛОВЫХ.",
        "hook_more_blocked": "БОЛЬШЕ БЛОКОВ.",
        "hook_more_chances": "БОЛЬШЕ ОСТРЫХ МОМЕНТОВ.",
        "hook_more_box": "БОЛЬШЕ КАСАНИЙ В ШТРАФНОЙ.",
        "hook_more_pressure": "БОЛЬШЕ ДАВЛЕНИЯ.",
        "hook_still_lost": "И ВСЁ РАВНО ПРОИГРАЛИ.",
        "hook_still_level": "И ВСЁ РАВНО НИЧЬЯ.",
        "hook_nobody_scored": "И НИКТО НЕ ЗАБИЛ.",
        "hook_one_moment": "ОДИН МОМЕНТ ВСЁ РЕШИЛ.",
        "hook_then_it_was_over": "И ВСЁ ЗАКОНЧИЛОСЬ.",
        "hook_turned_late": "МАТЧ ПЕРЕЛОМИЛСЯ НА {n}-Й МИНУТЕ.",
        "hook_had_the_ball": "МЯЧ БЫЛ У {team}.",
        "hook_not_the_chances": "МОМЕНТОВ — НЕТ.",
        "hook_n_shots": "{n} УДАРОВ.",
    },
}

# English chrome / template lines → offline translations when Gemini is off.
_OFFLINE_LINES: dict[str, dict[str, str]] = {
    "az": {
        "THE BASELINE": "ƏSAS GÖSTƏRİCİLƏR",
        "FULL TIME": "OYUN SONU",
        "AFTER EXTRA TIME": "ƏLAVƏ VAXTDAN SONRA",
        "ON PENALTIES": "PENALTİLƏRLƏ",
        "EVERY GOAL": "HƏR QOL",
        "SHOT MAP": "ZƏRBƏ XƏRİTƏSİ",
        "PRESSURE": "TƏZYİQ",
        "TERRITORY": "ƏRAZİ",
        "ONE GOAL, TRACED": "BİR QOL, İZİ İLƏ",
        "BUILD-UP": "HÜCUM QURULUŞU",
        "THE FRAME": "ÇƏRÇİVƏ",
        "PASS NETWORK": "PAS ŞƏBƏKƏSİ",
        "CONTROL VS THREAT": "NƏZARƏT VƏ TƏHLÜKƏ",
        "EVENT DATA": "HADİSƏ VERİLƏRİ",
        "MATCH RECAP": "MATÇ XÜLASƏSİ",
        "MATCH RESULT": "OYUN NƏTİCƏSİ",
        "THE GOAL TIMELINE": "QOL XRONOLOGİYASI",
        "THE NUMBERS SPLIT DOWN THE MIDDLE": "RƏQƏMLƏR ORTADA BÖLÜNDÜ",
        "THE MOVE BEFORE THE GOAL": "QOLDAN ƏVVƏLKİ HƏRƏKƏT",
        "PRESSURE THROUGH THE MATCH": "MATÇ BOYU TƏZYİQ",
        "EXTRA TIME BROKE THE DEADLOCK": "ƏLAVƏ VAXT DALANI AÇDI",
        "THEY CAME OUT SWINGING": "SƏRT BAŞLADILAR",
        "THE FIRST HALF SET THE TONE": "BİRİNCİ HİSSƏ TONU VERDİ",
        "THE GAME TURNED AFTER THE BREAK": "FASILADAN SONRA OYUN DƏYİŞDİ",
        "IT WAS DECIDED LATE": "GEC QƏRARLAŞDI",
        "WHERE THE MATCH WAS PLAYED": "OYUN HARADA GEDİB",
        "EVERY ZONE WAS CONTESTED": "HƏR ZONA MÜBARİZƏLİ İDİ",
        "NOBODY BLINKED": "HEÇ KİM GERİ ÇƏKİLMƏDİ",
        "Every attempt, by outcome": "Hər cəhd, nəticəsinə görə",
        "Touch volume across eighteen zones": "On səkkiz zona üzrə toxunuşlar",
        "Average positions and strongest links": "Orta mövqelər və ən güclü əlaqələr",
        "Pass share against what it produced": "Pas payı və onun nəticəsi",
        "Where on-target shots crossed the line": "Çərçivəyə zərbələrin keçdiyi yer",
        "Neither side could claim the baseline counts.": "Heç bir tərəf əsas göstəricilərə tam sahib olmadı.",
        "Ninety minutes could not separate them.": "Doxsan dəqiqə onları ayıra bilmədi.",
        "A shootout of a match, decided in open play.": "Açıq oyunda həll olunan qol bolluğu.",
        "Level after 120 minutes, settled from the spot.": "120 dəqiqədən sonra bərabər, penaltilərlə həll.",
        "Two teams, two answers, one point each.": "İki komanda, iki cavab, hər birinə bir xal.",
        "Every finish moved the board.": "Hər bitirmə hesabı dəyişdi.",
        "Pressure stayed level throughout.": "Təzyiq bütün matç boyu bərabər qaldı.",
        "Not one goal all match.": "Bütün matçda bir qol belə olmadı.",
        "Built directly from the match event feed.": "Birbaşa matç hadisə axınından qurulub.",
        "The build-up to the goal, taken straight from the event coordinates.": "Qola aparan quruluş hadisə koordinatlarından götürülüb.",
        "Belgium took the result and the numbers.": "",  # placeholder avoided; proper-noun lines handled generically
    },
    "es": {
        "THE BASELINE": "LA BASE",
        "FULL TIME": "FINAL",
        "AFTER EXTRA TIME": "TRAS LA PRÓRROGA",
        "ON PENALTIES": "EN PENALTIS",
        "EVERY GOAL": "CADA GOL",
        "SHOT MAP": "MAPA DE TIROS",
        "PRESSURE": "PRESIÓN",
        "TERRITORY": "TERRITORIO",
        "ONE GOAL, TRACED": "UN GOL, TRAZADO",
        "BUILD-UP": "JUGADA PREVIA",
        "THE FRAME": "EL MARCO",
        "PASS NETWORK": "RED DE PASES",
        "CONTROL VS THREAT": "CONTROL VS AMENAZA",
        "EVENT DATA": "DATOS DE EVENTOS",
        "MATCH RECAP": "RESUMEN DEL PARTIDO",
        "MATCH RESULT": "RESULTADO",
        "THE GOAL TIMELINE": "CRONOLOGÍA DE GOLES",
        "THE NUMBERS SPLIT DOWN THE MIDDLE": "LOS NÚMEROS SE PARTEN A LA MITAD",
        "THE MOVE BEFORE THE GOAL": "LA JUGADA ANTES DEL GOL",
        "PRESSURE THROUGH THE MATCH": "PRESIÓN DURANTE EL PARTIDO",
        "EXTRA TIME BROKE THE DEADLOCK": "LA PRÓRROGA ROMPIÓ EL EMPATE",
        "THEY CAME OUT SWINGING": "SALIERON A PRESIONAR",
        "THE FIRST HALF SET THE TONE": "LA PRIMERA PARTE MARCÓ EL TONO",
        "THE GAME TURNED AFTER THE BREAK": "EL PARTIDO GIRÓ TRAS EL DESCANSO",
        "IT WAS DECIDED LATE": "SE DECIDIÓ TARDE",
        "WHERE THE MATCH WAS PLAYED": "DÓNDE SE JUGÓ EL PARTIDO",
        "EVERY ZONE WAS CONTESTED": "CADA ZONA FUE DISPUTADA",
        "NOBODY BLINKED": "NADIE PARPADEÓ",
        "Every attempt, by outcome": "Cada intento, por resultado",
        "Touch volume across eighteen zones": "Toques en dieciocho zonas",
        "Average positions and strongest links": "Posiciones medias y enlaces más fuertes",
        "Pass share against what it produced": "Cuota de pases frente a lo que produjo",
        "Where on-target shots crossed the line": "Dónde cruzaron la línea los tiros a puerta",
        "Neither side could claim the baseline counts.": "Ningún equipo dominó los datos base.",
        "Ninety minutes could not separate them.": "Noventa minutos no pudieron separarlos.",
        "A shootout of a match, decided in open play.": "Un partido de goles, decidido en juego abierto.",
        "Level after 120 minutes, settled from the spot.": "Empate tras 120 minutos, resuelto desde el punto de penalti.",
        "Two teams, two answers, one point each.": "Dos equipos, dos respuestas, un punto cada uno.",
        "Every finish moved the board.": "Cada remate movió el marcador.",
        "Pressure stayed level throughout.": "La presión se mantuvo pareja todo el partido.",
        "Not one goal all match.": "Ni un solo gol en todo el partido.",
        "Built directly from the match event feed.": "Construido directamente del feed de eventos.",
        "The build-up to the goal, taken straight from the event coordinates.": "La jugada previa al gol, tomada de las coordenadas de eventos.",
    },
    "ru": {
        "THE BASELINE": "БАЗОВЫЕ ПОКАЗАТЕЛИ",
        "FULL TIME": "ФИНАЛ",
        "AFTER EXTRA TIME": "ПОСЛЕ ДОП. ВРЕМЕНИ",
        "ON PENALTIES": "ПО ПЕНАЛЬТИ",
        "EVERY GOAL": "КАЖДЫЙ ГОЛ",
        "SHOT MAP": "КАРТА УДАРОВ",
        "PRESSURE": "ДАВЛЕНИЕ",
        "TERRITORY": "ТЕРРИТОРИЯ",
        "ONE GOAL, TRACED": "ОДИН ГОЛ, ПО ШАГАМ",
        "BUILD-UP": "РОЗЫГРЫШ",
        "THE FRAME": "РАМКА",
        "PASS NETWORK": "ПАССОВАЯ СЕТЬ",
        "CONTROL VS THREAT": "КОНТРОЛЬ И УГРОЗА",
        "EVENT DATA": "СОБЫТИЙНЫЕ ДАННЫЕ",
        "MATCH RECAP": "ОБЗОР МАТЧА",
        "MATCH RESULT": "РЕЗУЛЬТАТ МАТЧА",
        "THE GOAL TIMELINE": "ХРОНОЛОГИЯ ГОЛОВ",
        "THE NUMBERS SPLIT DOWN THE MIDDLE": "ЦИФРЫ РАЗДЕЛИЛИСЬ ПОРОВНУ",
        "THE MOVE BEFORE THE GOAL": "АТАКА ПЕРЕД ГОЛОМ",
        "PRESSURE THROUGH THE MATCH": "ДАВЛЕНИЕ НА ПРОТЯЖЕНИИ МАТЧА",
        "EXTRA TIME BROKE THE DEADLOCK": "ДОП. ВРЕМЯ СЛОМАЛО НИЧЬЮ",
        "THEY CAME OUT SWINGING": "НАЧАЛИ АГРЕССИВНО",
        "THE FIRST HALF SET THE TONE": "ПЕРВЫЙ ТАЙМ ЗАДАЛ ТОН",
        "THE GAME TURNED AFTER THE BREAK": "ИГРА ПЕРЕЛОМИЛАСЬ ПОСЛЕ ПЕРЕРЫВА",
        "IT WAS DECIDED LATE": "РЕШИЛОСЬ ПОЗДНО",
        "WHERE THE MATCH WAS PLAYED": "ГДЕ ШЁЛ МАТЧ",
        "EVERY ZONE WAS CONTESTED": "КАЖДАЯ ЗОНА БЫЛА СПОРНОЙ",
        "NOBODY BLINKED": "НИКТО НЕ МОРГНУЛ",
        "Every attempt, by outcome": "Каждый удар — по исходу",
        "Touch volume across eighteen zones": "Касания по восемнадцати зонам",
        "Average positions and strongest links": "Средние позиции и сильные связи",
        "Pass share against what it produced": "Доля передач и что из этого вышло",
        "Where on-target shots crossed the line": "Где удары в створ пересекли линию",
        "Neither side could claim the baseline counts.": "Ни одна сторона не забрала базовые показатели.",
        "Ninety minutes could not separate them.": "Девяносто минут не смогли их развести.",
        "A shootout of a match, decided in open play.": "Голевой матч, решённый в открытой игре.",
        "Level after 120 minutes, settled from the spot.": "Ничья после 120 минут, решено с точки.",
        "Two teams, two answers, one point each.": "Две команды, два ответа, по очку каждой.",
        "Every finish moved the board.": "Каждый удар менял счёт.",
        "Pressure stayed level throughout.": "Давление оставалось равным всю игру.",
        "Not one goal all match.": "За весь матч — ни одного гола.",
        "Built directly from the match event feed.": "Собрано напрямую из ленты событий матча.",
        "The build-up to the goal, taken straight from the event coordinates.": "Розыгрыш перед голом — из координат событий.",
    },
}

_PERIOD_KEYS = {
    "First half": "period_first_half",
    "Second half": "period_second_half",
    "Extra time": "period_extra_time",
    "Extra time 1": "period_extra_time_1",
    "Extra time 2": "period_extra_time_2",
    "HT": "boundary_ht",
    "FT": "boundary_ft",
    "ET": "boundary_et",
}


def t(key: str, *, lang: str | None = None, **kwargs: Any) -> str:
    code = lang or _current
    catalog = UI.get(code) or UI["en"]
    template = catalog.get(key) or UI["en"].get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError):
            return template
    return template


def stat_label(key: str, *, lang: str | None = None) -> str:
    code = lang or _current
    labels = STAT_LABELS.get(code) or STAT_LABELS["en"]
    return labels.get(key) or STAT_LABELS["en"].get(key) or key.replace("_", " ").capitalize()


def score_qualifier(after_extra_time: bool = False, after_shootout: bool = False,
                    *, lang: str | None = None) -> str:
    if after_shootout:
        return t("on_penalties", lang=lang)
    if after_extra_time:
        return t("after_extra_time", lang=lang)
    return ""


def period_label(english: str, *, lang: str | None = None) -> str:
    key = _PERIOD_KEYS.get(english)
    if key:
        return t(key, lang=lang)
    return english


def outcome_label(outcome: str, *, lang: str | None = None) -> str:
    return t(f"outcome_{outcome}", lang=lang)


def offline_line(text: str, *, lang: str | None = None) -> str:
    """Translate a known English chrome/template line; leave unknowns alone."""
    code = lang or _current
    if code == "en" or not text:
        return text
    table = _OFFLINE_LINES.get(code) or {}
    if text in table and table[text]:
        return table[text]
    upper = text.upper()
    for source, target in table.items():
        if source.upper() == upper and target:
            return target
    # Patterned titles that embed a team name.
    patterns = [
        (r"^(.+) NEEDED EXTRA TIME$", {
            "az": "{name} ƏLAVƏ VAXT LAZIM OLDU",
            "es": "{name} NECESITÓ LA PRÓRROGA",
            "ru": "{name} ПОНАДОБИЛОСЬ ДОП. ВРЕМЯ",
        }),
        (r"^(.+) RAN RIOT$", {
            "az": "{name} DOMİNANTO OLDU",
            "es": "{name} ARRASÓ",
            "ru": "{name} УСТРОИЛИ РАЗГРОМ",
        }),
        (r"^(.+) FOUND A WAY$", {
            "az": "{name} YOL TAPDI",
            "es": "{name} ENCONTRÓ EL CAMINO",
            "ru": "{name} НАШЛИ СПОСОБ",
        }),
        (r"^(.+) SURVIVE THE SHOOTOUT$", {
            "az": "{name} PENALTİLƏRDƏ QALİB GƏLDİ",
            "es": "{name} SUPERÓ LOS PENALTIS",
            "ru": "{name} ВЫСТОЯЛИ В СЕРИИ ПЕНАЛЬТИ",
        }),
        (r"^(.+) LED ALMOST EVERYTHING$", {
            "az": "{name} DEMƏK OLAR HƏR ŞEYDƏ ÖNDƏ",
            "es": "{name} LIDERÓ CASI TODO",
            "ru": "{name} ВЕЛИ ПОЧТИ ВО ВСЁМ",
        }),
        (r"^(.+) KEPT TESTING THE KEEPER$", {
            "az": "{name} QAPINI SİNAYIRDI",
            "es": "{name} SIGUIÓ PROBANDO AL PORTERO",
            "ru": "{name} ПРОДОЛЖАЛИ ПРОВЕРЯТЬ ВРАТАРЯ",
        }),
        (r"^(.+) OWNED THE MAP$", {
            "az": "{name} XƏRİTƏYƏ SAHİB OLDU",
            "es": "{name} DOMINÓ EL MAPA",
            "ru": "{name} ЗАБРАЛИ КАРТУ",
        }),
        (r"^(.+) HAD WORK TO DO$", {
            "az": "{name} İŞİ VAR İDİ",
            "es": "{name} TUVO TRABAJO",
            "ru": "{name} ПРИШЛОСЬ РАБОТАТЬ",
        }),
        (r"^(.+) HAD THE BALL$", {
            "az": "{name} TOPA SAHİB İDİ",
            "es": "{name} TUVO EL BALÓN",
            "ru": "{name} ВЛАДЕЛИ МЯЧОМ",
        }),
        (r"^HOW (.+) MOVED THE BALL$", {
            "az": "{name} TOPU NECƏ HƏRƏKƏT ETDİRDİ",
            "es": "CÓMO {name} MOVIÓ EL BALÓN",
            "ru": "КАК {name} ДВИГАЛИ МЯЧ",
        }),
        (r"^(\d+) GOALS, ONE RUNNING SCORE$", {
            "az": "{name} QOL, BİR CANLI HESAB",
            "es": "{name} GOLES, UN MARCADOR CORRIENTE",
            "ru": "{name} ГОЛОВ, ОДИН ТЕКУЩИЙ СЧЁТ",
        }),
        (r"^(\d+) PASSES TO THE FINISH$", {
            "az": "FİNİŞƏ {name} PAS",
            "es": "{name} PASES HASTA EL REMATE",
            "ru": "{name} ПАСОВ ДО УДАРА",
        }),
        (r"^(\d+) GOALS, (.+) TAKE IT$", {
            "az": "{n} QOL, {name} QALİB GƏLİR",
            "es": "{n} GOLES, {name} SE LO LLEVA",
            "ru": "{n} ГОЛОВ, {name} ЗАБИРАЮТ",
        }),
        (r"^HONOURS EVEN AT (.+)$", {
            "az": "HESAB BƏRABƏR: {name}",
            "es": "EMPATE A {name}",
            "ru": "НИЧЬЯ {name}",
        }),
        (r"^(.+) above the line, (.+) below$", {
            "az": "{name} xəttin üstündə, {other} altında",
            "es": "{name} por encima, {other} por debajo",
            "ru": "{name} выше линии, {other} ниже",
        }),
        (r"^(.+) NEEDED (\d+) MINUTES$", {
            "az": "{name} {n} DƏQİQƏYƏ BİTİRDİ",
            "es": "{name} LO CERRÓ EN {n} MINUTOS",
            "ru": "{name} РЕШИЛИ ЗА {n} МИНУТ",
        }),
    ]
    for pattern, by_lang in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        template = by_lang.get(code)
        if not template:
            return text
        groups = match.groups()
        mapping = {"name": groups[0]}
        if len(groups) >= 2:
            mapping["other"] = groups[1]
            mapping["n"] = groups[1]
        if "{n}" in template and len(groups) >= 2:
            return template.format(**mapping)
        if "{other}" in template and len(groups) >= 2:
            return template.format(**mapping)
        return template.format(name=groups[0])
    return text


_ENGLISH_LEFTOVER = re.compile(
    r"\b(against|above the line|pass share|every attempt|touch volume|"
    r"average positions|what it produced|on.target|eighteen zones|"
    r"strongest links|the keeper|match result|match recap|full time|"
    r"the baseline|every goal|shot map|where on-target)\b",
    re.IGNORECASE,
)


def looks_english(text: str) -> bool:
    """True when a public string still contains leftover English template copy."""
    if not text:
        return False
    return bool(_ENGLISH_LEFTOVER.search(text))


def scrub_english_leftovers(scenes: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    """Hide or translate English chrome that leaked under a localized headline.

    Gemini often rewrites the title and leaves the English subtitle behind.
    An untranslated line under an Azerbaijani headline reads like debug text.
    """
    code = normalize_language(language)
    if code == "en":
        return scenes
    out = []
    for scene in scenes:
        updated = dict(scene)
        hook = bool(updated.get("hook"))
        for field in ("kicker", "title", "subtitle", "insight", "narration", "hook_stat"):
            value = str(updated.get(field) or "")
            if not value:
                continue
            translated = offline_line(value, lang=code)
            if translated != value:
                updated[field] = translated
                continue
            if looks_english(value) and not hook:
                updated[field] = "" if field in ("subtitle", "kicker", "hook_stat") else value
        if isinstance(updated.get("lines"), list):
            updated["lines"] = [offline_line(str(item), lang=code) for item in updated["lines"]]
        out.append(updated)
    return out


def localize_scenes_offline(scenes: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    code = normalize_language(language)
    if code == "en":
        return scenes
    out = []
    for scene in scenes:
        updated = dict(scene)
        for field in ("kicker", "title", "subtitle", "insight", "narration", "hook_stat"):
            value = str(updated.get(field) or "")
            if not value:
                continue
            updated[field] = offline_line(value, lang=code)
        if isinstance(updated.get("lines"), list):
            updated["lines"] = [offline_line(str(item), lang=code) for item in updated["lines"]]
        # Closing / title kickers that are score qualifiers.
        if updated.get("kicker") in ("AFTER EXTRA TIME", "ON PENALTIES", "FULL TIME"):
            mapping = {
                "AFTER EXTRA TIME": t("after_extra_time", lang=code),
                "ON PENALTIES": t("on_penalties", lang=code),
                "FULL TIME": t("full_time", lang=code),
            }
            updated["kicker"] = mapping[scene.get("kicker", "FULL TIME")]
        out.append(updated)
    return out


def localize_scenes(
    scenes: list[dict[str, Any]],
    language: str,
    gemini: Any | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Return (scenes, method) where method is en|gemini|offline."""
    code = normalize_language(language)
    if code == "en":
        return scenes, "en"
    if gemini is not None and getattr(gemini, "enabled", False):
        translated = gemini.translate_script(scenes, code)
        if translated:
            from .director import apply_script

            return scrub_english_leftovers(apply_script(scenes, translated), code), "gemini"
    return scrub_english_leftovers(localize_scenes_offline(scenes, code), code), "offline"
