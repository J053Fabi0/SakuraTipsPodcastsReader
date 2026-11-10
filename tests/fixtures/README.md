# Fixtures HTML

Fragmentos recortados del contenedor del articulo (`itemprop="articleBody"`)
de SakuraTips, usados para pruebas deterministas sin red.

| Archivo | Fuente | Fecha de obtencion | Lineas japon | Lineas ingles |
|---|---|---|---|---|
| `54.html` | https://sakuratips.com/2020/12/20/54/ | 2026-11-10 | 25 | 25 |
| `53.html` | https://sakuratips.com/2020/12/19/53/ | 2026-11-10 | 23 | 20 |
| `93.html` | https://sakuratips.com/2021/01/28/93/ | 2026-11-10 | 28 | 28 |

`93.html` incluye el pie promocional posterior a `<div class="jin-sen">` para
comprobar que el extractor lo excluye. Antes de la corrección producia 28/30.

La especificacion original menciona 34/30 para la pagina 53, pero el DOM actual
y la copia archivada de 2020-12-19 producen 23/20 con el algoritmo definido.
La prueba verifica que la discrepancia se detecte y que el mensaje incluya
ambas cantidades reales.
