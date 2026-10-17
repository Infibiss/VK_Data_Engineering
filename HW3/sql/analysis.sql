CREATE OR REPLACE TEMP VIEW source_rows AS
SELECT *
FROM read_csv(
    getvariable('data_uri'),
    columns = {
        'source': 'VARCHAR',
        'vacancy_id': 'VARCHAR',
        'status': 'VARCHAR',
        'snapshot_date': 'VARCHAR',
        'published_at': 'VARCHAR',
        'area': 'VARCHAR',
        'employer_id': 'VARCHAR',
        'employer_inn': 'VARCHAR',
        'employer_ogrn': 'VARCHAR',
        'employer_name': 'VARCHAR',
        'name': 'VARCHAR',
        'role': 'VARCHAR',
        'sphere': 'VARCHAR',
        'salary_from': 'VARCHAR',
        'salary_to': 'VARCHAR',
        'currency': 'VARCHAR',
        'gross': 'VARCHAR',
        'experience': 'VARCHAR',
        'schedule': 'VARCHAR',
        'employment': 'VARCHAR',
        'key_skills': 'VARCHAR',
        'description': 'VARCHAR',
        'url': 'VARCHAR'
    },
    auto_detect = false,
    header = true,
    delim = ',',
    quote = '"',
    escape = '"',
    compression = 'gzip',
    encoding = 'utf-8',
    nullstr = '',
    allow_quoted_nulls = true,
    strict_mode = true,
    ignore_errors = false,
    null_padding = false,
    max_line_size = 16777216,
    buffer_size = 67108864
);

CREATE OR REPLACE TEMP TABLE extraction AS
WITH classified AS (
    SELECT CASE
        WHEN role = 'Программист, разработчик'
             AND regexp_matches(
                 lower(name),
                 '(^|[^a-zа-яё0-9_])(android|андроид|ios|iphone|ipad|flutter|dart|react[ -]*native|xamarin|swift|objective[ -]*c|mobile|мобильн[а-яё]*)([^a-zа-яё0-9_]|$)'
             )
             AND NOT regexp_matches(
                 lower(name),
                 '(^|[^a-zа-яё0-9_])(qa|aqa|sdet|tester|testing|test|quality|тестиров[а-яё]*|тестирован[а-яё]*|автотест[а-яё]*|project|product|менеджер[а-яё]*|manager|консультант[а-яё]*|преподавател[а-яё]*|художник[а-яё]*|artist|backend|back[ -]*end|б[эе]к[эе]нд[а-яё]*|серверн[а-яё]*|sre|devops)([^a-zа-яё0-9_]|$)|мобильн[а-яё]*[ -]+(оператор[а-яё]*|сет[а-яё]*|торговл[а-яё]*)|mobile[ -]+web|мобильн[а-яё]*[ -]+верси[а-яё]*|release[ -]+train|автор[ -]+работ|руководитель[ -]+направлени|head[ -]+of[ -]+mobile|техническ[а-яё]*[ -]+специалист[а-яё]*|специалист[а-яё]*[ -]+поддержк[а-яё]*'
             )
             AND (
                 regexp_matches(lower(name), '(^|[^a-zа-яё0-9_])(android|андроид|ios|iphone|ipad|flutter|react[ .-]*native|xamarin|swift|objective[ -]*c|kotlin[ -]*multiplatform|kmp|kmm|qt|qml|maui|ionic|kivy|cordova|phonegap|nativescript|unity|capacitor|jetpack[ -]+compose|compose[ -]+multiplatform|мобильн[а-яё]*[ -]+интерфейс[а-яё]*[ -]+на[ -]+compose|unreal[ -]*engine|mobile[ -]*smarts|datamobile)([^a-zа-яё0-9_]|$)|1[сc].{0,60}мобильн|мобильн.{0,60}1[сc]')
                 OR regexp_matches(lower(coalesce(key_skills, '')), '(^|[^a-zа-яё0-9_])(android|андроид|ios|iphone|ipad|flutter|react[ .-]*native|xamarin|swift|objective[ -]*c|kotlin[ -]*multiplatform|kmp|kmm|qt|qml|maui|ionic|kivy|cordova|phonegap|nativescript|unity|capacitor|jetpack[ -]+compose|compose[ -]+multiplatform|мобильн[а-яё]*[ -]+интерфейс[а-яё]*[ -]+на[ -]+compose|unreal[ -]*engine|mobile[ -]*smarts|datamobile)([^a-zа-яё0-9_]|$)|1[сc].{0,60}мобильн|мобильн.{0,60}1[сc]')
                 OR (
                     (NOT regexp_matches(lower(name),
                         '(^|[^a-zа-яё0-9_])(python|php|golang|go|java)([^a-zа-яё0-9_]|$)')
                      OR regexp_matches(lower(coalesce(description, '')), '(^|[^a-zа-яё0-9_])(flutter|react[ .-]*native|xamarin|swift|objective[ -]*c|kotlin[ -]*multiplatform|kmp|kmm|qt|qml|maui|ionic|kivy|cordova|phonegap|nativescript|unity|capacitor|jetpack[ -]+compose|compose[ -]+multiplatform|мобильн[а-яё]*[ -]+интерфейс[а-яё]*[ -]+на[ -]+compose|unreal[ -]*engine|mobile[ -]*smarts|datamobile)([^a-zа-яё0-9_]|$)|1[сc].{0,60}мобильн|мобильн.{0,60}1[сc]'))
                     AND (NOT regexp_matches(lower(coalesce(key_skills, '')), '(^|[^a-zа-яё0-9_])(spring[ a-z]*|django|flask|fastapi|laravel|symfony|nest[ .]?js|node[ .]?js|asp[ .]?net|php|golang|hibernate|jdbc|backend|back[ -]*end|б[эе]к[эе]нд[а-яё]*)([^a-zа-яё0-9_]|$)')
                      OR regexp_matches(lower(coalesce(description, '')), '(^|[^a-zа-яё0-9_])(flutter|react[ .-]*native|xamarin|swift|objective[ -]*c|kotlin[ -]*multiplatform|kmp|kmm|qt|qml|maui|ionic|kivy|cordova|phonegap|nativescript|unity|capacitor|jetpack[ -]+compose|compose[ -]+multiplatform|мобильн[а-яё]*[ -]+интерфейс[а-яё]*[ -]+на[ -]+compose|unreal[ -]*engine|mobile[ -]*smarts|datamobile)([^a-zа-яё0-9_]|$)|1[сc].{0,60}мобильн|мобильн.{0,60}1[сc]'))
                     AND (
                         NOT regexp_matches(lower(name),
                             '(^|[^a-zа-яё0-9_])(web|веб|front[ -]*end|фронт[эе]нд[а-яё]*)([^a-zа-яё0-9_]|$)')
                         OR regexp_matches(lower(coalesce(description, '')), '(^|[^a-zа-яё0-9_])(flutter|react[ .-]*native|xamarin|swift|objective[ -]*c|kotlin[ -]*multiplatform|kmp|kmm|qt|qml|maui|ionic|kivy|cordova|phonegap|nativescript|unity|capacitor|jetpack[ -]+compose|compose[ -]+multiplatform|мобильн[а-яё]*[ -]+интерфейс[а-яё]*[ -]+на[ -]+compose|unreal[ -]*engine|mobile[ -]*smarts|datamobile)([^a-zа-яё0-9_]|$)|1[сc].{0,60}мобильн|мобильн.{0,60}1[сc]')
                     )
                     AND (
                         NOT regexp_matches(lower(coalesce(description, '')), '(^|[^a-zа-яё0-9_])(spring[ a-z]*|django|flask|fastapi|laravel|symfony|nest[ .]?js|node[ .]?js|asp[ .]?net|php|golang|hibernate|jdbc|backend|back[ -]*end|б[эе]к[эе]нд[а-яё]*)([^a-zа-яё0-9_]|$)')
                         OR regexp_matches(lower(coalesce(description, '')), '(^|[^a-zа-яё0-9_])(flutter|react[ .-]*native|xamarin|swift|objective[ -]*c|kotlin[ -]*multiplatform|kmp|kmm|qt|qml|maui|ionic|kivy|cordova|phonegap|nativescript|unity|capacitor|jetpack[ -]+compose|compose[ -]+multiplatform|мобильн[а-яё]*[ -]+интерфейс[а-яё]*[ -]+на[ -]+compose|unreal[ -]*engine|mobile[ -]*smarts|datamobile)([^a-zа-яё0-9_]|$)|1[сc].{0,60}мобильн|мобильн.{0,60}1[сc]')
                         OR regexp_matches(lower(coalesce(description, '')),
                             '(размещени|публикаци)[а-яё]*.{0,100}мобильн[а-яё]*.{0,60}(магазин|приложени)')
                     )
                 )
             )
        THEN struct_pack(
            source := source,
            vacancy_id := vacancy_id,
            name := name,
            area := area,
            key_skills := key_skills,
            salary_from := salary_from,
            salary_to := salary_to,
            currency := currency,
            gross := gross
        )
        ELSE NULL
    END AS vacancy
    FROM source_rows
)
SELECT
    count(*)::BIGINT AS input_rows,
    list(vacancy) FILTER (WHERE vacancy IS NOT NULL) AS vacancies
FROM classified;

CREATE OR REPLACE MACRO strip_skill(skill) AS trim(
    skill,
    concat(
        chr(9), chr(10), chr(11), chr(12), chr(13),
        chr(28), chr(29), chr(30), chr(31), chr(32), chr(133), chr(160),
        chr(5760), chr(8192), chr(8193), chr(8194), chr(8195), chr(8196),
        chr(8197), chr(8198), chr(8199), chr(8200), chr(8201), chr(8202),
        chr(8232), chr(8233), chr(8239), chr(8287), chr(12288)
    )
);

CREATE OR REPLACE TEMP TABLE selected AS
WITH unpacked AS (
    SELECT
        vacancy.source AS source,
        vacancy.vacancy_id AS vacancy_id,
        vacancy.name AS name,
        vacancy.area AS area,
        vacancy.key_skills AS key_skills,
        vacancy.currency AS currency,
        vacancy.gross AS gross,
        try_cast(vacancy.salary_from AS DOUBLE) AS salary_from,
        try_cast(vacancy.salary_to AS DOUBLE) AS salary_to
    FROM extraction
    CROSS JOIN UNNEST(vacancies) AS t(vacancy)
), prepared AS (
    SELECT *,
        CASE WHEN salary_from > 0 AND isfinite(salary_from)
             THEN salary_from ELSE NULL END AS salary_low,
        CASE WHEN salary_to > 0 AND isfinite(salary_to)
             THEN salary_to ELSE NULL END AS salary_high
    FROM unpacked
)
SELECT
    row_number() OVER ()::BIGINT AS vacancy_row,
    source,
    vacancy_id,
    name,
    area,
    list_sort(list_distinct(list_filter(
        list_transform(
            string_split(coalesce(key_skills, ''), ';'),
            skill -> lower(regexp_replace(strip_skill(skill), '[ \t\r\n\f\v]+', ' ', 'g'))
        ),
        skill -> skill <> ''
    ))) AS skills,
    CASE WHEN upper(trim(currency)) IN ('RUR', 'RUB')
                   AND lower(trim(gross)) = 'false' THEN
        CASE
            WHEN salary_low IS NOT NULL AND salary_high IS NOT NULL
                THEN (salary_low + salary_high) / 2.0
            ELSE coalesce(salary_low, salary_high)
        END
    ELSE NULL END::DOUBLE AS salary
FROM prepared;

CREATE OR REPLACE TEMP TABLE combinations AS
WITH positions AS (
    SELECT vacancy_row, area, salary, skills, index_i
    FROM selected
    CROSS JOIN UNNEST(range(1, len(skills) + 1)) AS p(index_i)
)
SELECT vacancy_row, area, salary, [skills[index_i]] AS skills
FROM positions
UNION ALL
SELECT vacancy_row, area, salary, [skills[index_i], skills[index_j]] AS skills
FROM positions
CROSS JOIN UNNEST(range(index_i + 1, len(skills) + 1)) AS q(index_j)
UNION ALL
SELECT vacancy_row, area, salary,
       [skills[index_i], skills[index_j], skills[index_k]] AS skills
FROM positions
CROSS JOIN UNNEST(range(index_i + 1, len(skills) + 1)) AS q(index_j)
CROSS JOIN UNNEST(range(index_j + 1, len(skills) + 1)) AS r(index_k);

CREATE OR REPLACE TEMP TABLE combination_counts AS
WITH scopes AS (
    SELECT '' AS region, skills, salary
    FROM combinations
    UNION ALL
    SELECT area AS region, skills, salary
    FROM combinations
    WHERE area IN ('Москва', 'Санкт-Петербург', 'Новосибирск')
)
SELECT
    region,
    skills,
    count(*)::BIGINT AS count,
    count(salary)::BIGINT AS n_salary,
    median(salary)::DOUBLE AS median_salary
FROM scopes
GROUP BY region, skills;

CREATE OR REPLACE TEMP TABLE regional_summary AS
WITH requested_regions(sort_order, region) AS (
    VALUES (1, 'Москва'), (2, 'Санкт-Петербург'), (3, 'Новосибирск')
)
SELECT
    r.sort_order,
    r.region,
    count(s.vacancy_row)::BIGINT AS jobs,
    count(*) FILTER (WHERE len(s.skills) > 0)::BIGINT AS with_skills,
    count(s.salary)::BIGINT AS salary_jobs,
    median(s.salary)::DOUBLE AS median_salary
FROM requested_regions AS r
LEFT JOIN selected AS s ON s.area = r.region
GROUP BY r.sort_order, r.region;
