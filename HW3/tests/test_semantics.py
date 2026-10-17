import csv
import gzip
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import common


class Semantics(unittest.TestCase):
    def test_mobile_developers_exclude_automotive_and_testers(self):
        self.assertTrue(common.is_variant({'role': common.ROLE, 'name': 'Senior Android-разработчик'}))
        self.assertTrue(common.is_variant({'role': common.ROLE, 'name': 'Разработчик мобильных приложений'}))
        self.assertTrue(common.is_variant({'role': common.ROLE, 'name': 'iOS / Swift developer'}))
        self.assertFalse(common.is_variant({'role': common.ROLE, 'name': 'Программист 1С автомобильный бизнес'}))
        self.assertFalse(common.is_variant({'role': 'Тестировщик', 'name': 'Android QA'}))
        self.assertFalse(common.is_variant({'role': common.ROLE, 'name': 'Java Backend developer'}))

    def test_mislabeled_roles_do_not_admit_other_segments(self):
        for title in ['QA Automation Engineer/SDET Mobile (Flutter Driver + Dart)',
                      'Главный Java-разработчик (мобильный оператор)',
                      'Dart-разработчик/программист серверной части',
                      'Ручной тестировщик (мобильное приложение + Web)',
                      'Project менеджер отдела мобильной разработки (Igaming)',
                      'Преподаватель курса Разработка мобильных приложений',
                      'С++ Developer (Пакетное ядро мобильной сети)',
                      'Frontend разработчик в Core Mobile Web']:
            with self.subTest(title=title):
                self.assertFalse(common.is_variant({'role': common.ROLE, 'name': title}))
        self.assertFalse(common.is_variant({'role': common.ROLE,
                                          'name': 'Senior Python-разработчик (команда мобильной разработки)',
                                          'key_skills': 'Python; Django; PostgreSQL'}))
        self.assertTrue(common.is_variant({'role': common.ROLE, 'name': 'Разработчик мобильных приложений',
                                         'key_skills': 'React Native; Node.js'}))

    def test_skills_are_counted_once_per_vacancy(self):
        self.assertEqual(common.skills(' Java ;Kotlin; JAVA;; Python\t language '),
                         ('java', 'kotlin', 'python language'))

    def test_mobile_wording_does_not_admit_web_without_client_evidence(self):
        for title in ['WEB - разработчик (поддержка и развитие SmartApp приложений платформы мобильного доступа)',
                      'Фронтенд-разработчик мобильных сервисов',
                      'Front-end developer мобильной платформы']:
            with self.subTest(title=title):
                self.assertFalse(common.is_variant({'role': common.ROLE, 'name': title}))
        self.assertTrue(common.is_variant({'role': common.ROLE,
                                         'name': 'Frontend mobile developer',
                                         'key_skills': 'React Native; TypeScript'}))

    def test_description_disambiguates_generic_mobile_titles(self):
        for title, description in [
            ('Ведущий разработчик мобильного приложения', 'Разработка API. Spring Boot, JDBC, Hibernate. Опыт backend.'),
            ('Senior Java разработчик, Команда Мобильное приложение', 'Разработка Back End сервисов. Spring Cloud.'),
            ('Программист Python (веб и мобильные проекты)', 'Бекенд логика. Python, Django, Docker-compose.'),
            ('Java Developer (команда мобильного приложения)', 'Микросервисы Spring; в команде iOS и Android разработчики.'),
            ('Технический специалист по мобильному приложению', 'Обновление баннеров, обработка жалоб')]:
            self.assertFalse(common.is_variant({'role': common.ROLE, 'name': title,
                                              'description': description}))
        for title, description in [
            ('Frontend разработчик (кросс-платформенное мобильное приложение)', 'Мобильная разработка Capacitor/Ionic/Angular'),
            ('Ведущий инженер-программист (мобильное приложение)', 'Kotlin; знание Flutter/Cordova/Swift; Laravel будет преимуществом'),
            ('Мобильный разработчик Kotlin', 'Мобильных интерфейсов на Compose, взаимодействие с бэкендом'),
            ('Программист 1С мобильных и веб решений', 'Разработка мобильного клиента 1С')]:
            self.assertTrue(common.is_variant({'role': common.ROLE, 'name': title,
                                             'description': description}))

    def test_salary_uses_comparable_net_rubles(self):
        row = {'currency': 'RUR', 'gross': 'false', 'salary_from': '100000', 'salary_to': '200000'}
        self.assertEqual(common.salary(row), 150000)
        row['salary_to'] = ''
        self.assertEqual(common.salary(row), 100000)
        row['gross'] = 'true'
        self.assertIsNone(common.salary(row))
        row.update(gross='false', currency='USD')
        self.assertIsNone(common.salary(row))

    def test_quoted_newline_and_utf8_survive_streaming(self):
        buf = io.StringIO(newline='')
        writer = csv.DictWriter(buf, fieldnames=list(dict.fromkeys(common.FIELDS + ['description'])))
        writer.writeheader()
        writer.writerow({'role': common.ROLE, 'name': 'iOS разработчик', 'key_skills': 'Swift; iOS',
                         'description': 'Строка с запятой,\nи вторая строка'})
        body = io.BytesIO(gzip.compress(buf.getvalue().encode('utf-8')))
        rows = list(common.python_rows(body))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'iOS разработчик')
        self.assertEqual(rows[0]['description'], 'Строка с запятой,\nи вторая строка')

    def test_exact_single_pair_triple_counts(self):
        from mapreduce import map_batch
        rows = [{'area': 'Москва', 'skills': ['android', 'kotlin', 'sql']},
                {'area': 'Москва', 'skills': ['android', 'kotlin']}]
        result = map_batch(rows, 'combiner', False)
        self.assertEqual(result[('', ('android',))], 2)
        self.assertEqual(result[('', ('android', 'kotlin'))], 2)
        self.assertEqual(result[('', ('android', 'kotlin', 'sql'))], 1)
        self.assertEqual(result[('Москва', ('android', 'kotlin'))], 2)
        self.assertEqual(sum(v for (r, s), v in result.items() if r == ''), 10)

    def test_salary_medians_include_empty_skill_vacancies_in_regions(self):
        from aggregates import pay_statistics
        from mapreduce import map_batch
        rows = [{'area': 'Москва', 'skills': ['android', 'kotlin'], 'salary': 100000},
                {'area': 'Москва', 'skills': ['android'], 'salary': 200000},
                {'area': 'Москва', 'skills': [], 'salary': 300000}]
        counts = map_batch(rows, 'combiner', False)
        pay, regions = pay_statistics(rows, counts)
        android = next(x for x in pay if x['region'] == '' and x['skills'] == ['android'])
        self.assertEqual((android['count'], android['n_salary'], android['median_salary']),
                         (2, 2, 150000))
        self.assertEqual(regions[0], {'region': 'Москва', 'jobs': 3, 'with_skills': 2,
                                      'salary_jobs': 3, 'median_salary': 200000})


if __name__ == '__main__':
    unittest.main()
