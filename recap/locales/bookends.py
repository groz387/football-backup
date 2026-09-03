"""Terrace trash-talk bookend pools.

First spoken sentence (hook) and last spoken sentence (outro) only.
The analysis body stays in the clean football register.

AZ is the native vulgar smash. EN/ES/RU are local terrace talk — never a
literal translation of the Azerbaijani curses.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Featured smash languages
# ---------------------------------------------------------------------------

AZ_HOOKS = [
    "{winner} {loser_gen} götünə ağac soxdu",
    "{winner} {loser_acc} belə soydu ki, stadion susdu",
    "{winner} {loser_gen} kürəyinə mindi",
    "{loser} bu gecə gijdıllax oldu, {winner} işini bitirdi",
    "{winner} {loser_acc} hamamda qoydu",
    "{winner} {loser_gen} ağzına qapadı",
    "{winner} {loser_acc} elə əzdi ki, analar ağladı",
    "{winner} {loser_gen} götünü başı etdi",
]

AZ_HOOKS_DRAW = [
    "Bu oyunda hamı gijdıllax çıxdı",
    "Heç kim oğlan olmadığını sübut etmədi",
    "Doxsan dəqiqə, sıfır kişi",
]

AZ_HOOKS_HIDE = [
    "Gecənin gijdıllaxını hələ demirik",
    "Kimə ağac soxuldu, hesabdan sonra",
    "Əvvəl lent, sonra göt",
]

AZ_OUTROS = [
    "Bəs sizcə, kim bu oyunda ən gijdıllaxiydi?",
    "Yorumda yaz, bu matçın ən gijdıllaxı kim oldu?",
    "Kim daha çox utandı, de görək?",
    "Bu oyunun kralı kim idi, yoxsa hamısı gijdıllax?",
    "Gijdıllaxı aşağıya yaz, utanmasın",
]

EN_HOOKS = [
    "{winner} sent {loser} home in a bin bag",
    "{winner} took {loser} behind the woodshed",
    "{winner} ran {loser} off the park",
    "{winner} had {loser} on toast",
    "{winner} put {loser} through the blender",
    "{winner} left {loser} with nothing but the bus fare",
    "{winner} stuffed {loser} in the boot and drove off",
    "{winner} fucking ran {loser} off the park",
    "{winner} pissed all over {loser}",
]

EN_HOOKS_DRAW = [
    "Ninety minutes of fucking nobody showing up",
    "Both lots bottled this shit",
    "A stalemate that deserved a hiding, frankly bollocks",
]

EN_HOOKS_HIDE = [
    "Someone's getting dragged. Not yet.",
    "A hiding is coming. Watch the tape.",
    "The bin bag is packed. Score later.",
]

EN_OUTROS = [
    "So who was the biggest bottleneck tonight?",
    "Drop it — who bottled this one?",
    "Be honest, who was a passenger out there?",
    "Who needs a hiding after that?",
    "Name the passenger. Don't be shy.",
]

ES_HOOKS = [
    "{winner} dejó a {loser} para el arrastre",
    "{winner} se merendó a {loser}",
    "{winner} mandó a {loser} a casa llorando",
    "{winner} hizo trizas a {loser}",
    "{winner} le dio un palizón a {loser}",
    "{winner} bordó a {loser} y ni se despeinó",
    "{winner} jodió a {loser} sin piedad",
    "{winner} dejó a {loser} hecho una mierda",
]

ES_HOOKS_DRAW = [
    "Noventa minutos de mierda compartida",
    "Nadie se puso los pantalones, joder",
    "Empate de los que duelen",
]

ES_HOOKS_HIDE = [
    "Hay paliza. El marcador espera.",
    "Alguien se va llorando. Todavía no.",
    "Primero la cinta. El arrastre después.",
]

ES_OUTROS = [
    "¿Quién fue el más payaso del partido?",
    "Dilo: ¿quién se hizo el ridículo?",
    "¿Quién mereció el bidón esta noche?",
    "¿Quién fue el pasajero? Suéltalo abajo.",
    "¿A quién hay que esconder tras esto?",
]

RU_HOOKS = [
    "{winner} устроил {loser} разнос",
    "{winner} укатал {loser} в асфальт",
    "{winner} вытер ноги об {loser}",
    "{winner} оставил {loser} без штанов",
    "{winner} закатал {loser} в бетон",
    "{winner} сделал с {loser} что хотел",
    "{winner} устроил {loser} пиздец",
    "{winner} вытер хуй об {loser}",
]

RU_HOOKS_DRAW = [
    "Девяносто минут взаимного пиздеца",
    "Никто не вышел играть, блять",
    "Ничья, за которую стыдно",
]

RU_HOOKS_HIDE = [
    "Кого размазали — скажем после счёта.",
    "Разнос будет. Пока лента.",
    "Кто без штанов, ещё не говорим.",
]

RU_OUTROS = [
    "Ну и кто тут самый беспомощный?",
    "Пишите — кто сегодня полный пассажир?",
    "Кто опозорился сильнее всех?",
    "Кто сегодня был лишним на поле?",
    "Назовите главного неудачника. Не стесняйтесь.",
]

# ---------------------------------------------------------------------------
# Other farm languages — local terrace talk, still first/last only
# ---------------------------------------------------------------------------

TR_HOOKS = [
    "{winner} {loser}'i sahadan sildi",
    "{winner} {loser}'i rezil etti",
    "{winner} {loser}'e gözdağı verdi",
]
TR_HOOKS_DRAW = ["Doksan dakika, sıfır erkek"]
TR_HOOKS_HIDE = ["Rezillik geliyor. Skor sonra."]
TR_OUTROS = [
    "Sizce bu maçın en zayıf halli kimdi?",
    "Yorumlara yaz: bu gecenin rezili kim?",
]

FR_HOOKS = [
    "{winner} a mis {loser} dans la poche",
    "{winner} a balayé {loser}",
    "{winner} a humilié {loser}",
]
FR_HOOKS_DRAW = ["Quatre-vingt-dix minutes de honte partagée"]
FR_HOOKS_HIDE = ["La raclée arrive. Le score attend."]
FR_OUTROS = [
    "Qui a été le plus ridicule ce soir ?",
    "Allez, qui a été le passager ?",
]

DE_HOOKS = [
    "{winner} hat {loser} demontiert",
    "{winner} hat {loser} vom Platz gefegt",
    "{winner} hat {loser} vorgeführt",
]
DE_HOOKS_DRAW = ["Neunzig Minuten peinliche Leere"]
DE_HOOKS_HIDE = ["Eine Abreibung kommt. Ergebnis später."]
DE_OUTROS = [
    "Wer war heute der größte Fehlgriff?",
    "Wer war der größte Passagier?",
]

IT_HOOKS = [
    "{winner} ha massacrato {loser}",
    "{winner} ha umiliato {loser}",
    "{winner} ha spazzato {loser}",
]
IT_HOOKS_DRAW = ["Novanta minuti di vergogna a metà"]
IT_HOOKS_HIDE = ["C'è una batosta. Il risultato aspetta."]
IT_OUTROS = [
    "Chi è stato il più ridicolo stasera?",
    "Chi è stato il passeggero? Dillo sotto.",
]

PT_BR_HOOKS = [
    "{winner} passou o carro em {loser}",
    "{winner} humilhou {loser}",
    "{winner} fez {loser} de gato e sapato",
]
PT_BR_HOOKS_DRAW = ["Noventa minutos de vergonha dividida"]
PT_BR_HOOKS_HIDE = ["Tem sova. O placar espera."]
PT_BR_OUTROS = [
    "Quem foi o maior fiasco da partida?",
    "Manda aí: quem foi o passageiro?",
]

PT_PT_HOOKS = [
    "{winner} passou por cima de {loser}",
    "{winner} humilhou {loser}",
    "{winner} limpou o chão com {loser}",
]
PT_PT_HOOKS_DRAW = ["Noventa minutos de vergonha a meias"]
PT_PT_HOOKS_HIDE = ["Há tareia. O resultado espera."]
PT_PT_OUTROS = [
    "Quem foi o maior flop do jogo?",
    "Quem foi o passageiro? Diz abaixo.",
]

AR_HOOKS = [
    "{winner} ذبح {loser}",
    "{winner} أذل {loser}",
    "{winner} مسح الأرض بـ {loser}",
]
AR_HOOKS_DRAW = ["تسعين دقيقة عار مشترك"]
AR_HOOKS_HIDE = ["في ذبح. النتيجة بعدين."]
AR_OUTROS = [
    "مين كان أضعف واحد الليلة؟",
    "قولوا: مين كان الراكب؟",
]

UK_HOOKS = [
    "{winner} розкатав {loser}",
    "{winner} витер ноги об {loser}",
    "{winner} залишив {loser} без штанів",
]
UK_HOOKS_DRAW = ["Дев'яносто хвилин спільного сорому"]
UK_HOOKS_HIDE = ["Рознос буде. Рахунок потім."]
UK_OUTROS = [
    "Хто тут найбільший пасажир?",
    "Хто сьогодні осоромився найбільше?",
]

PL_HOOKS = [
    "{winner} rozniósł {loser}",
    "{winner} zmiażdżył {loser}",
    "{winner} przetarł {loser} o boisko",
]
PL_HOOKS_DRAW = ["Dziewięćdziesiąt minut wspólnego wstydu"]
PL_HOOKS_HIDE = ["Lanie będzie. Wynik później."]
PL_OUTROS = [
    "Kto był największą wpadką?",
    "Kto był pasażerem? Napisz.",
]

NL_HOOKS = [
    "{winner} veegde {loser} van het veld",
    "{winner} maakte {loser} belachelijk",
    "{winner} zette {loser} klem",
]
NL_HOOKS_DRAW = ["Negentig minuten gedeelde schaamte"]
NL_HOOKS_HIDE = ["Er komt een pak slaag. Stand later."]
NL_OUTROS = [
    "Wie was de grootste afgang?",
    "Wie was de passagier vanavond?",
]

JA_HOOKS = [
    "{winner}が{loser}を叩き潰した",
    "{winner}が{loser}を沈めた",
    "{winner}が{loser}を一蹴した",
]
JA_HOOKS_DRAW = ["九十分、誰も男じゃなかった"]
JA_HOOKS_HIDE = ["袋叩きは後で。まずはテープ。"]
JA_OUTROS = [
    "一番ダメだったのは誰？",
    "乗客は誰だった？下に書け。",
]

KO_HOOKS = [
    "{winner}가 {loser}를 박살냈다",
    "{winner}가 {loser}를 망신줬다",
    "{winner}가 {loser}를 밀어버렸다",
]
KO_HOOKS_DRAW = ["90분 동안 둘 다 민망했다"]
KO_HOOKS_HIDE = ["망신은 나중에. 먼저 테이프."]
KO_OUTROS = [
    "오늘 제일 못한 선수는?",
    "승객이 누구였는지 아래에 써.",
]

HI_HOOKS = [
    "{winner} ने {loser} को धूल चटा दी",
    "{winner} ने {loser} की वाट लगा दी",
    "{winner} ने {loser} को घर भेज दिया",
]
HI_HOOKS_DRAW = ["नब्बे मिनट की साझा शर्म"]
HI_HOOKS_HIDE = ["धुल तो उड़ेगी। स्कोर बाद में।"]
HI_OUTROS = [
    "आज सबसे फ्लॉप कौन था?",
    "यात्री कौन था? नीचे लिखो।",
]


def _pack(win, draw, hide, outro) -> dict[str, tuple[str, ...]]:
    return {
        "hooks": tuple(win),
        "hooks_draw": tuple(draw),
        "hooks_hide": tuple(hide),
        "outros": tuple(outro),
    }


POOLS: dict[str, dict[str, tuple[str, ...]]] = {
    "az": _pack(AZ_HOOKS, AZ_HOOKS_DRAW, AZ_HOOKS_HIDE, AZ_OUTROS),
    "en": _pack(EN_HOOKS, EN_HOOKS_DRAW, EN_HOOKS_HIDE, EN_OUTROS),
    "es": _pack(ES_HOOKS, ES_HOOKS_DRAW, ES_HOOKS_HIDE, ES_OUTROS),
    "ru": _pack(RU_HOOKS, RU_HOOKS_DRAW, RU_HOOKS_HIDE, RU_OUTROS),
    "tr": _pack(TR_HOOKS, TR_HOOKS_DRAW, TR_HOOKS_HIDE, TR_OUTROS),
    "fr": _pack(FR_HOOKS, FR_HOOKS_DRAW, FR_HOOKS_HIDE, FR_OUTROS),
    "de": _pack(DE_HOOKS, DE_HOOKS_DRAW, DE_HOOKS_HIDE, DE_OUTROS),
    "it": _pack(IT_HOOKS, IT_HOOKS_DRAW, IT_HOOKS_HIDE, IT_OUTROS),
    "pt-BR": _pack(PT_BR_HOOKS, PT_BR_HOOKS_DRAW, PT_BR_HOOKS_HIDE, PT_BR_OUTROS),
    "pt-PT": _pack(PT_PT_HOOKS, PT_PT_HOOKS_DRAW, PT_PT_HOOKS_HIDE, PT_PT_OUTROS),
    "ar": _pack(AR_HOOKS, AR_HOOKS_DRAW, AR_HOOKS_HIDE, AR_OUTROS),
    "uk": _pack(UK_HOOKS, UK_HOOKS_DRAW, UK_HOOKS_HIDE, UK_OUTROS),
    "pl": _pack(PL_HOOKS, PL_HOOKS_DRAW, PL_HOOKS_HIDE, PL_OUTROS),
    "nl": _pack(NL_HOOKS, NL_HOOKS_DRAW, NL_HOOKS_HIDE, NL_OUTROS),
    "ja": _pack(JA_HOOKS, JA_HOOKS_DRAW, JA_HOOKS_HIDE, JA_OUTROS),
    "ko": _pack(KO_HOOKS, KO_HOOKS_DRAW, KO_HOOKS_HIDE, KO_OUTROS),
    "hi": _pack(HI_HOOKS, HI_HOOKS_DRAW, HI_HOOKS_HIDE, HI_OUTROS),
}


def locales() -> tuple[str, ...]:
    return tuple(POOLS.keys())


def bookends_for(code: str, *, kids: bool = False) -> dict[str, tuple[str, ...]]:
    """Hook / outro pools for a language. Kids mode returns empty (clean copy)."""
    pack = POOLS.get(code) or POOLS.get((code or "").replace("_", "-")) or POOLS["en"]
    if kids:
        return {"hooks": (), "hooks_draw": (), "hooks_hide": (), "outros": ()}
    return {
        "hooks": pack["hooks"],
        "hooks_draw": pack["hooks_draw"],
        "hooks_hide": pack["hooks_hide"],
        "outros": pack["outros"],
    }


def hooks_for(code: str, *, draw: bool = False, hide: bool = False) -> tuple[str, ...]:
    pack = POOLS.get(code) or POOLS["en"]
    if hide:
        return pack["hooks_hide"] or pack["hooks"]
    if draw:
        return pack["hooks_draw"] or pack["hooks"]
    return pack["hooks"]


def outros_for(code: str) -> tuple[str, ...]:
    pack = POOLS.get(code) or POOLS["en"]
    return pack["outros"]
