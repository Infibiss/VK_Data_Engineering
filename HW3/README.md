# ДЗ 3 - вариант 9

Муртазалиев Матвей Асланович, J3310, ИСУ 466797. Вариант 9: программист, разработчик на мобильных платформах.

## Запуск

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
sh scripts/start_rustfs.sh
```

В другом терминале с активированным окружением:

```sh
python3 scripts/run_all.py
```

Перед запуском положить `it_vacancies_2024.csv` в папку `HW3`.

RustFS: S3 `http://127.0.0.1:9100`, консоль `http://127.0.0.1:9101`. Данные `hw3admin` / `hw3-local-secret`. 

## Файлы

- `scripts/mapreduce.py` - мой mapper и reducer. `baseline`, `combiner`, `fast`, оптимизированный `stream`.
- `sql/analysis.sql`, `scripts/duckdb_job.py` - независимые фильтр и SQL расчёт из S3.
- `scripts/profile.py` - время и пик суммарной RSS процессов расчёта. Журнал `evidence/profile.jsonl`.
- `scripts/analyze.py` - сверка и формирование таблиц `results/`.
- `evidence/` - выводы команд, замеры и скриншоты.
- `HW3_report.pdf` - сам отчёт
