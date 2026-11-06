# ДЗ 4 — ZooKeeper

Муртазалиев Матвей Асланович, J3310, ИСУ 466797. Вариант 9: мобильные разработчики.

## Запуск

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
export JAVA_HOME=/путь/к/java17
bash scripts/zk_ensemble.sh up
bash scripts/zk_ensemble.sh status
```

ZooKeeper распаковывается в три копии в `.runtime/native/`. Конфиги находятся в `config/native/`. Порты клиентов: 22181, 22182, 22183.
В другом терминале запустить RustFS из ДЗ3.

## Проверка

Из `HW4`, с активированным окружением:

```sh
python3 scripts/zk_demo.py quorum
python3 scripts/zk_demo.py ephemeral
FENCING=0 python3 scripts/failover.py --label repeat-without-fencing
FENCING=1 python3 scripts/failover.py --label repeat-with-fencing
```

Лейбл каждого нового прогона должен быть уникален. `failover.py` запускает получателя и два координатора, отправляет первому SIGSTOP и SIGCONT и сверяет все принятые CSV с `HW3/results/skills_2.csv`. Расчёт использует фильтр и маппер ДЗ3. Указатель на чекпоинт хранится в ZooKeeper, накопленные данные в `.runtime/runs/`. Координаторы работают на одной машине и читают эту общую папку.

Журналы в `logs/`, результаты в `results/without-fencing/` и `results/with-fencing/`.
Проверка восстановления на небольшом наборе: `python3 -m unittest discover -s tests -v`.
