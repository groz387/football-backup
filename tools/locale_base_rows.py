"""BASE (original 254 chrome/hook/bridge) overlays, English key order."""
from __future__ import annotations

from pathlib import Path

KEYS = Path("/tmp/base_keys_order.txt").read_text(encoding="utf-8").splitlines()
# Fallback if the dump is gone — keep in repo.
if len(KEYS) != 254:
    KEYS = """watermark
match_recap
the_baseline
full_time
after_extra_time
on_penalties
goals
no_goals
no_goals_in_match
shots_none_counted
attacking_up
attacking_down
shots_on_target_line
markers_team_colour
pressure_curve_empty
attacking_pressure
no_touch_coords
passes
metres
goal
too_few_shots_frame
scored_n
all_stopped
shots_reached_target
count_per_zones
not_enough_passes
completed
accuracy
final_third
into_the_box
attacking_up_with_team
pass_share
final_third_short
into_box_short
outcome_goal
outcome_saved
outcome_off_target
outcome_blocked
outcome_woodwork
period_first_half
period_second_half
period_extra_time
period_extra_time_1
period_extra_time_2
boundary_ht
boundary_ft
boundary_et
peak
build_up
sub_shot_map
sub_momentum
sub_zone
sub_goalmouth
sub_pass_network
sub_sterile
hook_needed_minutes
hook_ran_riot
hook_found_a_way
hook_extra_time
hook_shootout
hook_goals_take_it
hook_nobody_blinked
hook_honours_even
hook_stat_on_target
hook_stat_big_chances
hook_stat_shots
hook_stat_margin
hook_had_more_shots
hook_had_more_corners
hook_had_more_blocked
hook_had_more_chances
hook_had_more_box
hook_had_more_pressure
hook_more_shots
hook_more_corners
hook_more_blocked
hook_more_chances
hook_more_box
hook_more_pressure
hook_still_lost
hook_still_level
hook_nobody_scored
hook_one_moment
hook_then_it_was_over
hook_turned_late
hook_had_the_ball
hook_not_the_chances
hook_n_shots
bridge_owned_the_map
bridge_had_the_ball
bridge_keeper_work
bridge_watch_the_board
bridge_kept_shooting
bridge_pressure_uneven
bridge_one_move
bridge_n_passes
bridge_how_they_moved
bridge_numbers_split
bridge_board_caught_up
bridge_look_at_this
handoff_but
hook_punch_lost_0
hook_punch_lost_1
hook_punch_lost_2
hook_punch_lost_3
hook_punch_lost_4
hook_punch_lost_5
hook_punch_lost_6
hook_punch_lost_7
hook_punch_over_0
hook_punch_over_1
hook_punch_over_2
hook_punch_over_3
hook_punch_over_4
hook_punch_over_5
hook_punch_level_0
hook_punch_level_1
hook_punch_level_2
hook_punch_level_3
hook_punch_level_4
hook_punch_blank_0
hook_punch_blank_1
hook_punch_blank_2
hook_punch_blank_3
hook_claim_shots_0
hook_claim_shots_1
hook_claim_shots_2
hook_claim_corners_0
hook_claim_corners_1
hook_claim_blocked_0
hook_claim_blocked_1
hook_claim_chances_0
hook_claim_chances_1
hook_claim_chances_2
hook_claim_box_0
hook_claim_box_1
hook_claim_pressure_0
hook_claim_pressure_1
hook_claim_ball_0
hook_claim_ball_1
hook_claim_ball_2
hook_claim_not_chances_0
hook_claim_not_chances_1
hook_claim_late_0
hook_claim_late_1
hook_claim_late_2
hook_claim_one_0
hook_claim_one_1
hook_claim_one_2
hook_claim_nshots_0
hook_claim_nshots_1
hook_claim_comeback_0
hook_claim_comeback_1
hook_claim_comeback_2
hook_claim_stoppage_0
hook_claim_stoppage_1
hook_claim_stoppage_2
hook_claim_blowout_0
hook_claim_blowout_1
hook_claim_blowout_2
hook_claim_xg_0
hook_claim_xg_1
hook_claim_keeper_0
hook_claim_keeper_1
hook_claim_keeper_2
hook_claim_waste_0
hook_claim_waste_1
hook_claim_chain_0
hook_claim_chain_1
hook_claim_chain_2
hook_claim_pin_0
hook_claim_pin_1
hook_claim_red_0
hook_claim_red_1
hook_claim_og_0
hook_claim_og_1
hook_claim_pen_0
hook_claim_pen_1
hook_claim_level_0
hook_claim_level_1
bridge_zone_0
bridge_zone_1
bridge_zone_2
bridge_zone_3
bridge_heat_0
bridge_heat_1
bridge_heat_2
bridge_ball_0
bridge_ball_1
bridge_ball_2
bridge_funnel_0
bridge_funnel_1
bridge_funnel_2
bridge_keeper_0
bridge_keeper_1
bridge_keeper_2
bridge_frame_0
bridge_frame_1
bridge_frame_2
bridge_board_0
bridge_board_1
bridge_board_2
bridge_shots_0
bridge_shots_1
bridge_shots_2
bridge_shots_3
bridge_pressure_0
bridge_pressure_1
bridge_pressure_2
bridge_tilt_0
bridge_tilt_1
bridge_tilt_2
bridge_chain_0
bridge_chain_1
bridge_chain_2
bridge_pass_0
bridge_pass_1
bridge_pass_2
bridge_radar_0
bridge_radar_1
bridge_radar_2
bridge_slam_0
bridge_slam_1
bridge_slam_2
bridge_gauge_0
bridge_gauge_1
bridge_gauge_2
bridge_race_0
bridge_race_1
bridge_halves_0
bridge_halves_1
bridge_halves_2
bridge_player_0
bridge_player_1
bridge_player_2
bridge_numbers_0
bridge_numbers_1
bridge_close_0
bridge_close_1
bridge_close_2
bridge_close_3
bridge_look_0
bridge_look_1
bridge_look_2
sub_radar
sub_heatmap
sub_tilt
sub_funnel
sub_gauges
sub_slam
sub_race
sub_zones_time
sub_player
sub_keeper_frame""".splitlines()


def pack(rows: list[str]) -> dict[str, str]:
    if len(rows) != 254:
        raise ValueError(f"want 254, got {len(rows)}")
    return dict(zip(KEYS, rows))


# Turkish match-night register.
TR = pack([
    "", "MAÇ ÖZETİ", "TABAN", "MAÇ SONU", "UZATMA SONRASI", "PENALTILARLA",
    "GOLLER", "GOL YOK", "BU MAÇTA GOL YOK",
    "{shots} ŞUT, HİÇBİRİ YAZILMADI", "YUKARI HÜCUM", "AŞAĞI HÜCUM",
    "{shots} ŞUT / {on_target} KALEYİ BULAN", "İŞARETLER TAKIM RENGİNDE",
    "BASKI EĞRİSİ İÇİN YETERLİ OLAY YOK", "5 DAKİKALIK HÜCUM BASKISI",
    "BU DIŞA AKTARIMDA DOKUNUŞ KOORDİNATI YOK", "PASLAR", "METRE", "GOL",
    "ÇERÇEVEYE AZ ŞUT ULAŞTI", "{n} GOL", "HEPSİ KESİLDİ",
    "KALEYİ BULAN ŞUTLAR", "ALTI BÖLGEYE GÖRE SAYI", "AĞ İÇİN YETERLİ PAS YOK",
    "İSABETLİ", "İSABET", "SON ÜÇTE BİR", "CEZAYA",
    "{team}  /  YUKARI HÜCUM", "Pas payı", "Son üçte bir", "Cezaya",
    "Gol", "Kurtarış", "Dışarı", "Blok", "Direk",
    "İlk yarı", "İkinci yarı", "Uzatma", "Uzatma 1", "Uzatma 2",
    "İY", "MS", "UZ", "ZİRVE {block}", "ORGANİZASYON",
    "Her deneme, sonucuna göre", "{home} çizginin üstünde, {away} altında",
    "On sekiz bölgede dokunuş", "Kaleyi bulan şutların geçtiği yer",
    "Ortalama konumlar ve en güçlü bağlar", "Pas payı ve ne ürettiği",
    "{team} {n} DAKİKADA BİTİRDİ", "{team} DAĞITTI", "{team} YOLUNU BULDU",
    "{team} UZATMAYA İHTİYAÇ DUYDU", "{team} PENALTILARDA AYAKTA",
    "{n} GOL, {team} ALIYOR", "KİMSE GERİ ADIM ATMADI", "SKOR BERABERE: {score}",
    "{n} KALEYİ BULAN", "{n} NET POZİSYON", "{n} ŞUT", "{n} GOL FARKI",
    "{team} DAHA ÇOK ŞUT ÇEKTİ.", "{team} DAHA ÇOK KORNER KULLANDI.",
    "{team} DAHA ÇOK BLOKLANAN ŞUTU VARDI.", "{team} DAHA ÇOK NET POZİSYON BULDU.",
    "{team} CEZADA DAHA ÇOK DOKUNDU.", "{team} DAHA ÇOK BASKI KURDU.",
    "DAHA ÇOK ŞUT.", "DAHA ÇOK KORNER.", "DAHA ÇOK BLOKLANAN ŞUT.",
    "DAHA ÇOK NET POZİSYON.", "CEZADA DAHA ÇOK DOKUNUŞ.", "DAHA ÇOK BASKI.",
    "YİNE DE KAYBETTİLER.", "YİNE BERABERE BİTTİ.", "VE KİMSE GOL ATMADI.",
    "BİR AN KARAR VERDİ.", "SONRA BİTTİ.", "MAÇ {n}. DAKİKADA DÖNDÜ.",
    "{team} TOPA SAHİPTİ.", "POZİSYONLARA DEĞİL.", "{n} ŞUT.",
    "{team} HARİTAYA SAHİP OLDU.", "{team} TOPA SAHİPTİ.",
    "{team}’İN İŞİ VARDI.", "{n} GOL. SKORA BAK.",
    "{team} ŞUT ÇEKMEYE DEVAM ETTİ.", "BASKI EŞİT DEĞİLDİ.",
    "BİR HAREKET İŞİ BİTİRDİ.", "{n} PAS. BİR BİTİRİŞ.",
    "{team} TOPU BÖYLE GEZDİRDİ.", "RAKAMLAR UYUŞMADI.",
    "SONRA SKOR KONUŞTU.", "DUR. BUNA BAK.",
    "{proof}. Ama {next}.",
    "YİNE DE KAYBETTİLER.", "VE YİNE KAYBETTİLER.", "HİÇBİRİ SAYILMADI.",
    "SKOR UMURSAMADI.", "EVE BOŞ DÖNDÜLER.", "PUANLAR ÖTEKİNE GİTTİ.",
    "YETMEDİ.", "SONUÇ HAYIR DEDİ.",
    "SONRA BİTTİ.", "GECE OYDU.", "MAÇ. KAPANDI.",
    "KAPI ÇARPILDI.", "GERİ YOL YOK.", "ÇÖZÜLDÜ. BİTTİ.",
    "YİNE BERABERE KALDI.", "KİMSE KİLİDİ AÇAMADI.", "KİŞİ BAŞI BİR PUAN.",
    "SKOR YERİNDE KALDI.", "AYRILAMADILAR.",
    "VE KİMSE VURAMADI.", "AĞ KIPIRDAMADI.", "SIFIR. SKORDA.", "İKİSİ DE BOŞ.",
    "{team} {n} ŞUT ÇEKTİ.", "{team} İÇİN {n} ŞUT.", "{team} ŞUTU BULDU.",
    "{team} {n} KORNER KULLANDI.", "{n} KORNER. HEPSİ {team}.",
    "{team} DAHA ÇOK BLOKLANAN ŞUTU VARDI.", "{n} ŞUT BLOKTA ÖLDÜ.",
    "{team} {n} NET POZİSYON BULDU.", "{n} NET POZİSYON. {team}.",
    "POZİSYONLAR {team} TARAFINA GİTTİ.",
    "{team} CEZADA YAŞADI.", "{team} CEZADA {n} DOKUNUŞ.",
    "{team} DAHA ÇOK BASKI KURDU.", "BASKI {team} TARAFINDAYDI.",
    "{team} TOPA SAHİPTİ.", "PASLARIN %{n}’İ. {team}.", "{team} TOPU YIĞDI.",
    "POZİSYONLAR YOK.", "POZİSYONLAR ÖTEKİNE GİTTİ.",
    "MAÇ {n}. DAKİKADA DÖNDÜ.", "{n}. DAKİKA. KESIŞ.", "{team} {n}.’YE KADAR BEKLEDİ.",
    "BİR AN ÇÖZDÜ.", "BİR VURUŞ. MAÇ OYDU.", "{team} BİRİNE İHTİYAÇ DUYDU.",
    "{n} ŞUT.", "{n} DENEME. SIFIR GOL.",
    "{team} GERİDEN GELMEK ZORUNDA KALDI.", "GERİDEYDİLER. SONRA {team} ÇEVİRDİ.",
    "GERİDEN. {n}. DAKİKADA.",
    "{n}. DAKİKA BİTİRDİ.", "UZATMA. {team}. BİTİRDİ.", "{n}.’YE KADAR BEKLEDİLER.",
    "{team} EVİ DAĞITTI.", "{n} GOL FARKI.", "BU MAÇ DEĞİLDİ.",
    "{team} xG’DE KAZANDI.", "{n} xG. FARK ETMEDİ.",
    "{team} HER ŞEYİ KESTİ.", "{n} KURTARIŞ. DUVAR.", "KALECİ GECEYİ ÇALDI.",
    "{team} {n} ŞUT ÇEKTİ.", "{n} ŞUT. GERİYE NEREDEYSE HİÇ.",
    "{n} PAS. BİR BİTİRİŞ.", "{team} PAS PAS KURDU.", "{n} PASLIK BIÇAK.",
    "{team} ONLARI SIKIŞTIRDI.", "%{n} EĞİM. ÇIKIŞ YOK.",
    "KIRMIZI KART HESABI DEĞİŞTİRDİ.", "{n} KOVULDU. MAÇ DÖNDÜ.",
    "KENDİ KALESİ ZARAR VERDİ.", "{n}. DAKİKADA KENDİLERİNİ YENDİLER.",
    "PENALTI ÇÖZDÜ.", "NOKTADAN. {n}. DAKİKA.",
    "{home} {away} KARŞI.", "İKİ TAKIM. KAZANAN YOK.",
    "{team} HARİTAYA SAHİPTİ.", "SAHAYA BAK.", "{n} DOKUNUŞ YETTİ.", "BURADA YAŞADILAR.",
    "ISI HARİTASI YALAN SÖYLEMİYOR.", "{team} BU YARIYI PİŞİRDİ.", "DOKUNUŞ-DOKUNUŞ. SIKIŞTIRMA.",
    "{team} TOPA SAHİPTİ.", "PASLARIN %{n}’İ.", "KONTROL. SONRA HİÇ.",
    "POZİSYONLARIN ÖLMESİNE BAK.", "HUNİ SIFIRA DARALIYOR.", "HÜCUMLAR BURADA AÇLIĞA DÜŞTÜ.",
    "{team}’İN İŞİ VARDI.", "{n} KURTARIŞ. BAK.", "ÇERÇEVE KUŞATMADAYDI.",
    "AĞA ULAŞAN HER ŞUT.", "İŞTE TUĞLA DUVAR.", "YERLEŞTİRME. SONRA KESİŞ.",
    "{n} GOL. SKORA BAK.", "HER BİTİRİŞ, SIRAYLA.", "SKOR BÖYLE HAREKET ETTİ.",
    "{team} ŞUT ÇEKMEYE DEVAM ETTİ.", "{n} ŞUT. BAK.", "HER DENEME, HARİTADA.", "İŞTE ŞUT GALERİSİ.",
    "BASKI EŞİT DEĞİLDİ.", "DÖNÜŞE BAK.", "TAM O AN DÖNDÜ.",
    "SAHA EĞİMİ, DAKİKA DAKİKA.", "TEHLİKELİ ÜÇTE BİR KİMİNDİ.", "DALGA GERİ GELMEDİ.",
    "{n} PAS. BİR BİTİRİŞ.", "BİR HAREKET İŞİ BİTİRDİ.", "BIÇAĞI İZLE.",
    "{team} TOPU BÖYLE GEZDİRDİ.", "BAĞLARI İZLE.", "ONLARIN ŞEKLİ, PASLARDA.",
    "MAÇIN ŞEKLİ.", "ALTI EKSEN. BİR HİKÂYE.", "İŞTE PROFİL.",
    "BİR RAKAM. MAÇ.", "{n}. İŞTE KAFA.", "BU SAYIYI OKU.",
    "POZİSYONLAR GOLLERİNE KARŞI.", "ÇEVİRME YALAN SÖYLEDİ.", "KALİTE. SONRA BİTİRİŞ.",
    "ZAMANA GÖRE xG.", "SKORUN SAYMADIĞI YARIŞ.",
    "İKİ FARKLI YARIYDI.", "OTUZAR DAKİKA.", "HARİTA DEĞİŞTİ.",
    "BİR İSİM BUNU TAŞIDI.", "İŞTE ZİRVE.", "OYUNCUYU İZLE.",
    "RAKAMLAR UYUŞMADI.", "BÖLÜNMEYİ OKU.",
    "SONRA SKOR KONUŞTU.", "NASIL BİTTİ, İŞTE.", "SKOR. NİHAYET.", "GECE OYDU.",
    "DUR. BUNA BAK.", "ŞİMDİ RESİM.", "BU OKUMAYI DEĞİŞTİRİYOR.",
    "Altı eksen, iki takım", "Sahada dokunuş yoğunluğu", "Hücum üçte biri pas payı",
    "Gole dönmeyen kontrol", "Pozisyon kalitesi ve bitiriş", "Geceyi yazan rakam",
    "Biriken xG gollere karşı", "Üç dilimde saha", "Bantta sıçrayan oyuncu",
    "Çerçeveye ulaşan her şut",
])

PT_BR = pack([
    "", "RESUMO DA PARTIDA", "A BASE", "FIM DE JOGO", "DEPOIS DA PRORROGAÇÃO", "NOS PÊNALTIS",
    "GOLS", "SEM GOLS", "SEM GOLS NESTE JOGO",
    "{shots} FINALIZAÇÕES, NENHUMA VALEU", "ATAQUE PRA CIMA", "ATAQUE PRA BAIXO",
    "{shots} CHUTES / {on_target} NO GOL", "OS MARCADORES USAM A COR DO TIME",
    "SEM EVENTOS PRA CURVA DE PRESSÃO", "PRESSÃO OFENSIVA A CADA 5 MINUTOS",
    "SEM COORDENADAS DE TOQUE NESTE EXPORT", "PASSES", "METROS", "GOL",
    "POUCOS CHUTES CHEGARAM NO GOL", "{n} GOLS", "TODOS DEFENDIDOS",
    "CHUTES QUE CHEGARAM NO GOL", "CONTAGEM NAS SEIS ZONAS", "PASSES INSUFICIENTES PRA REDE",
    "CERTOS", "PRECISÃO", "TERÇO FINAL", "NA ÁREA",
    "{team}  /  ATAQUE PRA CIMA", "Fatia de passes", "Terço final", "Na área",
    "Gol", "Defesa", "Pra fora", "Bloqueado", "Trave",
    "Primeiro tempo", "Segundo tempo", "Prorrogação", "Prorrogação 1", "Prorrogação 2",
    "INT", "FIM", "PR", "PICO {block}", "CONSTRUÇÃO",
    "Cada tentativa, pelo resultado", "{home} acima da linha, {away} abaixo",
    "Toques em dezoito zonas", "Onde os chutes no gol cruzaram a linha",
    "Posições médias e elos mais fortes", "Fatia de passe contra o que rendeu",
    "{team} FECHOU EM {n} MINUTOS", "{team} PASSEOU", "{team} ACHOU O CAMINHO",
    "{team} PRECISOU DA PRORROGAÇÃO", "{team} AGUENTOU OS PÊNALTIS",
    "{n} GOLS, {team} LEVA", "NINGUÉM PISCOU", "EMPATE EM {score}",
    "{n} NO GOL", "{n} GRANDES CHANCES", "{n} FINALIZAÇÕES", "{n} GOLS DE FOLGA",
    "{team} TEVE MAIS FINALIZAÇÕES.", "{team} TEVE MAIS ESCANTEIOS.",
    "{team} TEVE MAIS CHUTES BLOQUEADOS.", "{team} TEVE MAIS GRANDES CHANCES.",
    "{team} TOCOU MAIS NA ÁREA.", "{team} TEVE MAIS PRESSÃO.",
    "MAIS FINALIZAÇÕES.", "MAIS ESCANTEIOS.", "MAIS CHUTES BLOQUEADOS.",
    "MAIS GRANDES CHANCES.", "MAIS TOQUES NA ÁREA.", "MAIS PRESSÃO.",
    "AINDA ASSIM PERDERAM.", "AINDA ASSIM EMPATOU.", "E NINGUÉM MARCOU.",
    "UM LANCE DECIDIU.", "AÍ ACABOU.", "O JOGO VIROU AOS {n}.",
    "{team} TEVE A BOLA.", "NÃO AS CHANCES.", "{n} FINALIZAÇÕES.",
    "{team} DONO DO MAPA.", "{team} TEVE A BOLA.",
    "{team} TEVE TRABALHO.", "{n} GOLS. OLHA O PLACAR.",
    "{team} SEGUIU CHUTANDO.", "A PRESSÃO NÃO FOI IGUAL.",
    "UM LANCE FEZ O ESTRAGO.", "{n} PASSES. UMA FINALIZAÇÃO.",
    "ASSIM O {team} GIROU A BOLA.", "OS NÚMEROS NÃO BATERAM.",
    "AÍ O PLACAR FALOU.", "ESPERA. OLHA ISSO.",
    "{proof}. Mas {next}.",
    "AINDA ASSIM PERDERAM.", "E AINDA ASSIM PERDERAM.", "NADA CONTOU.",
    "O PLACAR NÃO QUIS SABER.", "FORAM EMBORA SEM NADA.", "OS PONTOS FORAM PRO OUTRO LADO.",
    "NÃO DEU.", "O RESULTADO DISSE NÃO.",
    "AÍ ACABOU.", "ESSA FOI A NOITE.", "JOGO. FECHADO.",
    "A PORTA BATEU.", "SEM VOLTA.", "RESOLVIDO. FIM.",
    "CONTINUOU EMPATADO.", "NINGUÉM QUEBROU O EMPATE.", "UM PONTO PRA CADA.",
    "TRAVADOS NO EMPATE.", "NÃO TEVE SEPARAÇÃO.",
    "E NINGUÉM MARCOU.", "A REDE NÃO MEXEU.", "ZERO. NO PLACAR.", "OS DOIS EM BRANCO.",
    "{team} TEVE {n} FINALIZAÇÕES.", "{n} CHUTES PRO {team}.", "{team} FICOU ACHANDO O CHUTE.",
    "{team} TEVE {n} ESCANTEIOS.", "{n} ESCANTEIOS. TUDO {team}.",
    "{team} TEVE MAIS CHUTES BLOQUEADOS.", "{n} CHUTES MORRERAM NO BLOQUEIO.",
    "{team} TEVE {n} GRANDES CHANCES.", "{n} GRANDES CHANCES. {team}.",
    "AS CHANCES FORAM PRO {team}.",
    "{team} VIVEU NA ÁREA.", "{n} TOQUES NA ÁREA PRO {team}.",
    "{team} TEVE MAIS PRESSÃO.", "A PRESSÃO FOI DO {team}.",
    "{team} TEVE A BOLA.", "{n}% DOS PASSES. {team}.", "{team} ENGOLIU A BOLA.",
    "NÃO AS CHANCES.", "AS CHANCES FORAM PRO OUTRO LADO.",
    "O JOGO VIROU AOS {n}.", "MINUTO {n}. ALI CORTOU.", "{team} ESPEROU ATÉ OS {n}.",
    "UM LANCE DECIDIU.", "UM SOCO. ESSE FOI O JOGO.", "{team} SÓ PRECISOU DE UM.",
    "{n} FINALIZAÇÕES.", "{n} TENTATIVAS. ZERO GOLS.",
    "{team} TEVE QUE VIRAR.", "ESTAVAM PERDENDO. AÍ O {team} VIROU.",
    "DE TRÁS. AOS {n}.",
    "O MINUTO {n} FECHOU.", "ACRÉSCIMOS. {team}. O FECHAMENTO.", "ESPERARAM ATÉ OS {n}.",
    "{team} DEITOU E ROLOU.", "{n} GOLS DE LUZ.", "ISSO AQUI NÃO FOI JOGO.",
    "{team} GANHOU O xG.", "{n} xG. E NÃO IMPORTOU.",
    "{team} PAROU TUDO.", "{n} DEFESAS. UM MURO.", "O GOLEIRO ROUBOU A NOITE.",
    "{team} TEVE {n} FINALIZAÇÕES.", "{n} CHUTES. QUASE NADA DE VOLTA.",
    "{n} PASSES. UMA FINALIZAÇÃO.", "{team} ARMOU PASSE A PASSE.", "UMA FACA DE {n} PASSES.",
    "{team} PRENDEU ELES LÁ ATRÁS.", "{n}% DE INCLINAÇÃO. SEM SAÍDA.",
    "UMA VERMELHA MUDOU A CONTA.", "{n} EXPULSO. O JOGO VIROU.",
    "UM GOL CONTRA FEZ O ESTRAGO.", "SE VENCERAM AOS {n}.",
    "UM PÊNALTI RESOLVEU.", "DA MARCA. AOS {n}.",
    "{home} CONTRA {away}.", "DOIS TIMES. SEM VENCEDOR.",
    "{team} DONO DO MAPA.", "OLHA O TERRITÓRIO.", "{n} TOQUES BASTARAM.", "FOI ALI QUE ELES VIVERAM.",
    "O MAPA DE CALOR NÃO MENTE.", "{team} COZINHOU ESSE TEMPO.", "TOQUE A TOQUE. O PRENDE.",
    "{team} TEVE A BOLA.", "{n}% DOS PASSES.", "CONTROLE. DEPOIS NADA.",
    "OLHA AS CHANCES MORRENDO.", "O FUNIL APERTA ATÉ ZERO.", "OS ATAQUES MORRERAM AQUI.",
    "{team} TEVE TRABALHO.", "{n} DEFESAS. OLHA.", "O GOL ESTAVA SITIADO.",
    "CADA CHUTE QUE CHEGOU NO GOL.", "ESSE É O MURO DE TIJOLO.", "COLOCAÇÃO. DEPOIS A DEFESA.",
    "{n} GOLS. OLHA O PLACAR.", "CADA FINALIZAÇÃO, NA ORDEM.", "O PLACAR ANDOU ASSIM.",
    "{team} SEGUIU CHUTANDO.", "{n} CHUTES. OLHA.", "CADA TENTATIVA, NO MAPA.", "ESSA É A GALERIA.",
    "A PRESSÃO NÃO FOI IGUAL.", "OLHA A VIRADA.", "ALI INCLINOU.",
    "INCLINAÇÃO, MINUTO A MINUTO.", "QUEM TEVE O TERÇO PERIGOSO.", "A ONDA NÃO VOLTOU.",
    "{n} PASSES. UMA FINALIZAÇÃO.", "UM LANCE FEZ O ESTRAGO.", "SEGUE A FACA.",
    "ASSIM O {team} GIROU A BOLA.", "SEGUE OS ELOS.", "A FORMA DELES, EM PASSES.",
    "A FORMA DO JOGO.", "SEIS EIXOS. UMA HISTÓRIA.", "ESSE É O PERFIL.",
    "UM NÚMERO. O JOGO.", "{n}. ESSE É O GANCHO.", "LÊ ESSE NÚMERO.",
    "CHANCES CONTRA GOLS.", "A CONVERSÃO MENTIU.", "QUALIDADE. DEPOIS A FINALIZAÇÃO.",
    "xG NO TEMPO.", "A CORRIDA QUE O PLACAR IGNOROU.",
    "FORAM DOIS TEMPOS DIFERENTES.", "TRINTA MINUTOS DE CADA VEZ.", "O MAPA MUDOU.",
    "UM NOME CARREGOU ISSO.", "ESSE É O PICO.", "SEGUE O JOGADOR.",
    "OS NÚMEROS NÃO BATERAM.", "LÊ A DIVISÃO.",
    "AÍ O PLACAR FALOU.", "ASSIM TERMINOU.", "O PLACAR. ENFIM.", "ESSA FOI A NOITE.",
    "ESPERA. OLHA ISSO.", "AGORA A IMAGEM.", "ISSO MUDA A LEITURA.",
    "Seis eixos, os dois times", "Densidade de toques no campo", "Fatia de passe no terço final",
    "Controle que não virou gol", "Qualidade da chance contra a finalização", "O número que definiu a noite",
    "xG acumulado contra os gols", "Território em três cortes", "O jogador que disparou a fita",
    "Cada chute no gol no marco",
])

BASE = {"tr": TR, "pt-BR": PT_BR}
