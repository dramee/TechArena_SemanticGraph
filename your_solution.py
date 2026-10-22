#!/usr/bin/env python3
"""TechArena: предсказание графа исполнения Train Ticket без его запуска.

Запуск::

    python3 your_solution.py skeleton/trainticket.json.gz \
        targets/trainticket scenarios/*.json -o submission.json

Подробности — в SOLUTION.md, код решения — в пакете ``solution``
(только стандартная библиотека Python).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from solution.solve import run_main  # noqa: E402

if __name__ == "__main__":
    run_main()
