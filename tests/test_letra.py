"""Letra sincronizada por palabra para el Modo Karaoke (Pb-5, Sp-7)."""

from app.whisperx_run import construir_letra


def _palabra(texto, inicio, fin):
    return {"word": texto, "start": inicio, "end": fin}


def test_cada_palabra_conserva_su_tiempo():
    letra = construir_letra(
        [{"words": [_palabra("Hola", 1.0, 1.4), _palabra("mundo", 1.5, 2.0)]}]
    )
    assert letra == {
        "lineas": [
            {
                "inicio": 1.0,
                "fin": 2.0,
                "palabras": [
                    {"texto": "Hola", "inicio": 1.0, "fin": 1.4},
                    {"texto": "mundo", "inicio": 1.5, "fin": 2.0},
                ],
            }
        ]
    }


def test_una_pausa_larga_o_un_segmento_nuevo_empiezan_otra_linea():
    letra = construir_letra(
        [
            {"words": [_palabra("uno", 0, 0.5), _palabra("dos", 2.0, 2.4)]},
            {"words": [_palabra("tres", 2.5, 3.0)]},
        ]
    )
    textos = [[p["texto"] for p in li["palabras"]] for li in letra["lineas"]]
    assert textos == [["uno"], ["dos"], ["tres"]]


def test_las_lineas_largas_se_dividen():
    palabras = [_palabra(f"p{k}", k * 0.3, k * 0.3 + 0.2) for k in range(20)]
    letra = construir_letra([{"words": palabras}])
    assert [len(li["palabras"]) for li in letra["lineas"]] == [8, 8, 4]


def test_se_omiten_palabras_sin_tiempo_y_repeticiones():
    palabras = [{"word": "sin", "start": None, "end": None}] + [
        _palabra("la", k, k + 0.2) for k in range(10)
    ]
    letra = construir_letra([{"words": palabras}])
    total = sum(len(li["palabras"]) for li in letra["lineas"])
    assert total == 6
