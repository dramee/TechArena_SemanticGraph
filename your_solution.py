#!/usr/bin/env python3
"""TechArena: предсказание графа исполнения Train Ticket без запуска приложения.

    python3 your_solution.py skeleton/trainticket.json.gz targets/trainticket scenarios/*.json -o submission.json

Подробности — в SOLUTION.md. Код решения — в каталоге solution/ (только стандартная библиотека Python 3.8+)."""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "solution"))
import solve

if __name__ == "__main__":
    solve.run_main()
