# ДЗ 5 — Kubernetes

Муртазалиев М. А., J3310, ИСУ 466797. Вариант 9 — мобильные разработчики.

## Запуск

Нужны Docker, kubectl, Python 3 и kind 0.31.0. Кластер `hw5` создаётся отдельно, kubeconfig хранится в `.runtime/`. Docker Desktop выделено 10 CPU и 8 GiB памяти. Манифесты ожидания CPU и вытеснения рассчитаны на эту конфигурацию одноузлового кластера.

Команды из корня репозитория. Исходный S3 ДЗ 3 должен содержать `s3://hh-lake/raw/it_vacancies_2024.csv.gz` и работать на порту 9100. Запуск исходного RustFS в отдельном терминале:

```sh
RUSTFS_BINARY="$PWD/HW2/bin/rustfs" zsh HW3/scripts/start_rustfs.sh
```

Можно указать другой путь к исполняемому файлу RustFS через `RUSTFS_BINARY`. Dockerfile использует исходные фильтр и маппер из `HW3/scripts`, сборка выполняется из корня репозитория.

```sh
sh HW5/scripts/run.sh cluster
sh HW5/scripts/run.sh memory
sh HW5/scripts/run.sh storage
```

Для переноса данных открыть порт S3 кластера в отдельном терминале:

```sh
sh HW5/scripts/kube.sh -n hw5 port-forward service/rustfs 9200:9000
```

Затем:

```sh
sh HW5/scripts/run.sh migrate
sh HW5/scripts/run.sh parallel
sh HW5/scripts/run.sh scheduling
sh HW5/scripts/run.sh collect
```

Если kind находится вне PATH, передать `KIND_BIN=/путь/к/kind`. Повторные журналы сохраняются в `.runtime/repeat-logs/`, результаты в `.runtime/repeat-results/`. Этапы `memory`, `parallel` и `scheduling` пересоздают свои тестовые Job и Pod в пространствах ДЗ 5.

## Результаты

В `logs/` находятся журналы сдаваемого запуска. `results/single/` и `results/parallel/` содержат полный CSV, топ-10 и измерения. `results/verification.json` фиксирует побайтовое совпадение с `HW3/results/skills_2.csv` и между режимами.

При пределе 32 MiB расчёт завершился `OOMKilled`, код 137. Измеренный пик RSS 59,14 MiB. Предел 80 MiB выбран как `ceil(59.14 × 1.25 / 16) × 16`; успешный повтор сохранён в `logs/pairs-calibrated.log`. При повторе скрипт проверяет, что новый измеренный пик с тем же запасом укладывается в 80 MiB, и сохраняет расчёт в `memory-limit.json` рядом с повторными журналами. Worker и reducer используют 80 MiB, подготовка четырёх gzip-частей — 512 MiB. При переносе S3 проверен SHA256 исходного и скопированного объекта.

Запуск проверки разделения и объединения на небольшом наборе:

```sh
docker run --rm --entrypoint python hw5-job:local -m unittest discover -s /app -p test_job.py -v
```
