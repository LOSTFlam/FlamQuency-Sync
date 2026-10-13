"""Точка входа для `python -m flamquency`.

Нужен не только для удобства: «Огниво» и планировщик запускают
`python -m flamquency <команда>`, и без этого файла любая искра падала бы
с «No module named flamquency.__main__».
"""
import sys

from flamquency.cli import main

if __name__ == "__main__":
    sys.exit(main())
