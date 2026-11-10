# Third-party notices

Este proyecto se distribuye bajo la licencia **GNU General Public License v3.0
o posterior** (ver [LICENSE](LICENSE)).

## JapaneseFurigana (Anki add-on 678316993)

El módulo `sakuratips_reader/furigana.py` es una adaptación del archivo
`reading.py` del complemento **JapaneseFurigana**:

- Autor: proyecto JapaneseFurigana / obynio
- Sitio: <https://ankiweb.net/shared/info/678316993>
- Repositorio: <https://github.com/obynio/anki-japanese-furigana>
- Licencia: GNU GPL v3.0 o posterior

La adaptación reemplaza la invocación del binario de MeCab incluido en el
complemento por la API de `mecab-python3` con el diccionario IPADIC, conservando
el mismo procedimiento de lectura y división kanji/kana. El texto original de la
licencia GPL se incluye en [LICENSE](LICENSE).

## MeCab

- Autor: Taku Kudo
- Sitio: <https://taku910.github.io/mecab/>
- Licencia: triple licencia BSD / LGPL / GPL (ver el proyecto original)

Este proyecto no redistribuye binarios de MeCab; utiliza el paquete de Python
`mecab-python3`.

## IPADIC

- Diccionario de análisis morfológico japonés para MeCab.
- Paquete de Python: <https://pypi.org/project/ipadic/>
- Licencia: ver el paquete `ipadic` distribuido por pip.

Este proyecto no redistribuye el diccionario; lo instala como dependencia.

## Otras dependencias

- BeautifulSoup4 (MIT)
- Flask (BSD-3-Clause)
- Requests (Apache-2.0)
- mecab-python3 (BSD-3-Clause)
- ipadic (ver licencia del paquete)

Los textos completos de las licencias de estas dependencias están disponibles en
sus distribuciones originales.
