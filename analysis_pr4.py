#!/usr/bin/env python3
"""Практическая работа №4, вариант №1: ВСЕ аналитические расчёты на Python.

Запуск:
  python analysis_pr4.py --input "ПР4_Журнал_service_desk.csv" --out "powerbi_data"
"""

from __future__ import annotations
import argparse
import csv
import json
import math
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

MONTHS = {"Январь": "2026-01", "Февраль": "2026-02"}
MONTH_ALL = "Весь период"
CATEGORY_ALL = "Все категории"
CAT_CANON = {
    "доступ и учетные записи": "Доступ и учётные записи",
    "доступ и уз": "Доступ и учётные записи",
    "прикладное по": "Прикладное ПО",
    "сеть": "Сеть",
    "оборудование": "Оборудование",
    "информационная безопасность": "Информационная безопасность",
    "печать": "Печать",
    "телефония": "Телефония",
}
FCR_CANDIDATES = ("Решено с первого контакта", "Первый контакт (Да/Нет)", "FCR")
GOALS = [
    ("SLA", 0.92, 0.88, "higher", "Доля решённых в срок"),
    ("average_hours", 6.0, 9.0, "lower", "Среднее время решения"),
    ("p90_hours", 20.0, 30.0, "lower", "90-й перцентиль времени решения"),
    ("repeat_share", 0.08, 0.12, "lower", "Доля повторных обращений"),
    ("rating", 4.3, 4.0, "higher", "Средняя оценка пользователя"),
]
COLORS = {"зелёный": "#15803D", "жёлтый": "#D97706", "красный": "#B91C1C", "нет нормы": "#64748B", "нет данных": "#64748B"}


def load_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        result = list(csv.DictReader(stream))
    if not result:
        raise ValueError("Исходный файл пуст")
    required = {
        "ID обращения", "Дата регистрации", "Категория", "Приоритет", "Услуга", "Исполнитель",
        "Время реакции, ч", "Время решения, ч", "Норматив решения (SLA), ч",
        "Повторное обращение", "Оценка пользователя (1-5)", "Нарушение SLA"
    }
    if missing := required - set(result[0]):
        raise ValueError(f"Не хватает колонок в CSV: {sorted(missing)}")
    return result


def num(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        n = float(str(value).strip().replace(",", "."))
        return n if math.isfinite(n) else None
    except ValueError:
        return None


def canon_category(value: str) -> str:
    key = " ".join(value.strip().split()).casefold().replace("ё", "е")
    if key not in CAT_CANON:
        raise ValueError(f"Неизвестная категория (сначала уточните справочник): {value!r}")
    return CAT_CANON[key]


def percentile_inc(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    left = math.floor(index)
    right = math.ceil(index)
    return ordered[left] + (ordered[right] - ordered[left]) * (index - left)


def get_fcr(value: str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    v = str(value).strip().casefold()
    if v in {"да", "yes", "true", "1"}:
        return 1
    if v in {"нет", "no", "false", "0"}:
        return 0
    raise ValueError(f"Неверное значение FCR: {value!r}")


def get_repeat_flag(value: str | None) -> int:
    """Повторное обращение: Да -> 1, Нет -> 0 (не подменять пропуски значением Нет)."""
    v = str(value or "").strip().casefold()
    if v not in {"да", "нет"}:
        raise ValueError(f"Неизвестное значение поля «Повторное обращение»: {value!r}")
    return int(v == "да")


def text_val(x):
    return "" if x is None else x


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None):
    if not rows and not fields:
        raise ValueError(f"Нет данных для выгрузки {path}")
    cols = fields or list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        w = csv.DictWriter(stream, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({c: text_val(row.get(c)) for c in cols})


def evaluate(name: str, actual: float | None) -> tuple[str, str]:
    g = next((q for q in GOALS if q[0] == name), None)
    if g is None:
        label = "нет данных" if actual is None else "нет нормы"
    else:
        _, target, yellow_border, direction, _ = g
        if actual is None:
            label = "нет данных"
        elif direction == "higher":
            label = "зелёный" if actual >= target else "жёлтый" if actual >= yellow_border else "красный"
        else:
            label = "зелёный" if actual <= target else "жёлтый" if actual <= yellow_border else "красный"
    return label, COLORS[label]


def metrics(records: list[dict]) -> dict:
    times = [r["resolution_hours"] for r in records]
    ratings = [r["rating"] for r in records if r["rating"] is not None]
    fcr_known = [r for r in records if r["fcr"] is not None]
    fcr_estimated = sum(bool(r["fcr_is_estimate"]) for r in fcr_known)
    fcr_actual = len(fcr_known) - fcr_estimated
    fcr_numerator = sum(r["fcr"] for r in fcr_known)
    fcr_share = fcr_numerator / len(fcr_known) if fcr_known else None
    n = len(records)
    ontime = sum(r["sla_ok"] for r in records)
    repeated = sum(r["repeated"] for r in records)
    if fcr_estimated and fcr_actual:
        fcr_method = "смешанный: фактический признак + косвенная оценка по повторности"
    elif fcr_estimated:
        fcr_method = "косвенная оценка по отсутствию признака повторности"
    elif fcr_actual:
        fcr_method = "фактический признак решения с первого контакта"
    else:
        fcr_method = "нет данных"
    result = {
        "requests": n,
        "sla_ontime": ontime,
        "sla_breaches": n - ontime,
        "sla_share": ontime / n if n else None,
        "sla_target": .92,
        "sla_deviation_pp": (ontime / n - .92) * 100 if n else None,
        "mean_resolution_h": statistics.mean(times) if n else None,
        "median_resolution_h": statistics.median(times) if n else None,
        "p90_resolution_h": percentile_inc(times, .90),
        "repeat_cases": repeated,
        "repeat_share": repeated / n if n else None,
        "rating_count": len(ratings),
        "rating_average": statistics.mean(ratings) if ratings else None,
        "fcr_known_cases": len(fcr_known),
        "fcr_resolved_first": fcr_numerator,
        "fcr_share": fcr_share,
        "fcr_label": ("Нет данных" if fcr_share is None else
                      f"{fcr_share:.2%}".replace(".", ",") + (" (оценка)" if fcr_estimated else "")),
        "fcr_method": fcr_method,
        "fcr_is_estimate": fcr_estimated > 0,
        "fcr_estimated_cases": fcr_estimated,
        "fcr_actual_cases": fcr_actual,
        "fcr_proxy_share": (n - repeated) / n if n else None,
        "p99_resolution_h": percentile_inc(times, .99),
    }
    for metric, col in [
        ("SLA", "sla_share"), ("average_hours", "mean_resolution_h"),
        ("p90_hours", "p90_resolution_h"), ("repeat_share", "repeat_share"),
        ("rating", "rating_average"), ("fcr", "fcr_share")
    ]:
        result[metric + "_status"], result[metric + "_color"] = evaluate(metric, result[col])
    return result


def prepare(raw: list[dict]):
    ids: set[str] = set()
    deduped: list[dict] = []
    excluded: list[dict] = []
    dup_count = 0
    for row in raw:
        row = dict(row)
        rid = row["ID обращения"]
        if rid in ids:
            # Unlike blindly dropping conflicting IDs, verify they are identical.
            old = next(r for r in deduped if r["ID обращения"] == rid)
            if old != row:
                raise ValueError(f"ID {rid} имеет разные записи: требуется ручная проверка")
            dup_count += 1
            excluded.append({"id": rid, "reason": "полный дубликат", **row})
            continue
        ids.add(rid)
        deduped.append(row)

    no_time = 0
    negative = 0
    invalid_sla = 0
    changed_categories = 0
    missing_employees = 0
    bad_rating = 0
    mismatched_sla = 0
    normalized: list[dict] = []
    fcr_col = next((c for c in FCR_CANDIDATES if c in deduped[0]), None)
    for r in deduped:
        t = num(r["Время решения, ч"])
        if t is None:
            no_time += 1
            excluded.append({"id": r["ID обращения"], "reason": "отсутствует/некорректно время решения", **r})
            continue
        if t < 0:
            negative += 1
            excluded.append({"id": r["ID обращения"], "reason": "отрицательное время решения", **r})
            continue
        sla = num(r["Норматив решения (SLA), ч"])
        if sla is None or sla <= 0:
            invalid_sla += 1
            excluded.append({"id": r["ID обращения"], "reason": "некорректный норматив SLA", **r})
            continue
        category = canon_category(r["Категория"])
        changed_categories += category != r["Категория"]
        employee = r["Исполнитель"].strip()
        missing_employees += not bool(employee)
        rating = num(r["Оценка пользователя (1-5)"])
        if rating is not None and not (1 <= rating <= 5):
            bad_rating += 1
            rating = None
        dt = datetime.fromisoformat(r["Дата регистрации"].strip())
        status = int(t <= sla)
        flag = r["Нарушение SLA"].strip().casefold()
        if flag in ("да", "нет") and (flag == "да") != (status == 0):
            mismatched_sla += 1
        repeated = get_repeat_flag(r["Повторное обращение"])
        true_fcr = get_fcr(r.get(fcr_col)) if fcr_col else None
        # Косвенная оценка FCR: не повторное => условно решено с первого контакта.
        # Если есть достоверное поле FCR, используем его вместо оценки.
        fcr_is_estimate = true_fcr is None
        fcr = 1 - repeated if fcr_is_estimate else true_fcr
        normalized.append({
            "id": r["ID обращения"], "registered_at": dt,
            "registered_at_text": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "month_code": dt.strftime("%Y-%m"), "category": category,
            "priority": r["Приоритет"].strip(), "service": r["Услуга"].strip(),
            "employee": employee or "не указан",
            "reaction_hours": num(r["Время реакции, ч"]),
            "resolution_hours": t, "sla_hours": sla, "sla_ok": status,
            "repeated": repeated,
            "rating": rating,
            "fcr": fcr,
            "fcr_is_estimate": fcr_is_estimate,
        })
    if mismatched_sla:
        raise ValueError(f"Найдены {mismatched_sla} противоречий SLA; выясните причину перед сдачей")
    report = {
        "source_rows": len(raw), "duplicates": dup_count,
        "unique_rows": len(deduped), "missing_time": no_time, "negative_time": negative,
        "bad_sla": invalid_sla, "category_labels_before": len({r["Категория"] for r in raw}),
        "categories_after": len({r["category"] for r in normalized}),
        "category_values_changed": changed_categories,
        "missing_employee": missing_employees,
        "missing_rating_after": sum(r["rating"] is None for r in normalized),
        "invalid_rating": bad_rating, "mismatched_sla": mismatched_sla,
        "clean_rows": len(normalized), "fcr_column": fcr_col,
        "fcr_definition": "Оценка FCR = количество обращений со значением 'Повторное обращение = нет' / количество обращений; не является фактическим FCR",
        "first_date": min(r["registered_at"].isoformat() for r in normalized),
        "last_date": max(r["registered_at"].isoformat() for r in normalized),
    }
    return normalized, excluded, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path(__file__).parent / "ПР4_Журнал_service_desk.csv")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "powerbi_data")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    raw = load_csv(args.input)
    clean, excluded, audit = prepare(raw)
    sampled = [r for r in clean if r["month_code"] in MONTHS.values()]
    cats = sorted({r["category"] for r in sampled})
    month_options = [MONTH_ALL, *MONTHS]
    cat_options = [CATEGORY_ALL, *cats]
    if len(sampled) == 0 or len(cats) != 7:
        raise ValueError("Проверьте период/категории — данные отличаются от учебного журнала")

    def filtered(month_name: str, category_name: str):
        target_month = MONTHS.get(month_name)
        return [r for r in sampled if (target_month is None or r["month_code"] == target_month)
                and (category_name == CATEGORY_ALL or r["category"] == category_name)]

    summary_rows: list[dict] = []
    category_rows: list[dict] = []
    trend_rows: list[dict] = []
    detail_rows: list[dict] = []
    for month_name in month_options:
        for category_name in cat_options:
            subset = filtered(month_name, category_name)
            keys = {"month_selection": month_name, "category_selection": category_name}
            summary_rows.append({**keys, **metrics(subset)})
            for actual_cat in cats:
                matching = [r for r in subset if r["category"] == actual_cat]
                if matching:
                    category_rows.append({**keys, "actual_category": actual_cat, **metrics(matching)})
            for month_label, month_code in MONTHS.items():
                matching = [r for r in subset if r["month_code"] == month_code]
                if matching:
                    trend_rows.append({**keys, "actual_month": month_code, "month_label": month_label,
                                       "month_order": int(month_code[-2:]), **metrics(matching)})
            for r in subset:
                detail_rows.append({**keys,
                    "id": r["id"], "date_time": r["registered_at_text"],
                    "actual_month": r["month_code"], "actual_category": r["category"],
                    "priority": r["priority"], "service": r["service"], "employee": r["employee"],
                    "resolution_hours": r["resolution_hours"], "sla_hours": r["sla_hours"],
                    "sla_ok": r["sla_ok"], "repeated": r["repeated"],
                    "rating": r["rating"], "first_contact": r["fcr"],
                    "first_contact_is_estimate": r["fcr_is_estimate"],
                })

    write_csv(args.out / "01_KPI_по_фильтрам.csv", summary_rows)
    write_csv(args.out / "02_Категории_по_фильтрам.csv", category_rows)
    write_csv(args.out / "03_Динамика_по_фильтрам.csv", trend_rows)
    write_csv(args.out / "04_Обращения_по_фильтрам.csv", detail_rows)
    write_csv(args.out / "05_Фильтр_месяц.csv", [
        {"month_selection": name, "sort_order": i} for i, name in enumerate(month_options)
    ])
    write_csv(args.out / "06_Фильтр_категория.csv", [
        {"category_selection": name, "sort_order": i} for i, name in enumerate(cat_options)
    ])
    write_csv(args.out / "07_Нормативы.csv", [
        {"metric": g[0], "description": g[4], "target": g[1], "yellow_border": g[2],
         "direction": g[3]} for g in GOALS
    ])
    write_csv(args.out / "08_Исключенные_записи.csv", excluded,
        fields=["id", "reason", *raw[0].keys()])
    # Сохраняем две версии набора данных: весь очищенный журнал и выборку варианта №1.
    journal_fields = [
        "id", "registered_at_text", "month_code", "category", "priority", "service", "employee",
        "reaction_hours", "resolution_hours", "sla_hours", "sla_ok", "repeated", "rating", "fcr", "fcr_is_estimate",
    ]
    for filename, records in [
        ("09_Очищенный_журнал.csv", clean),
        ("10_Выборка_вариант1.csv", sampled),
    ]:
        write_csv(args.out / filename, [
            {k: v for k, v in r.items() if k != "registered_at"}
            for r in records
        ], fields=journal_fields)
    stat = metrics(sampled)
    audit["selected_rows"] = len(sampled)
    audit["selected_jan"] = sum(r["month_code"] == "2026-01" for r in sampled)
    audit["selected_feb"] = sum(r["month_code"] == "2026-02" for r in sampled)
    audit["p99_selected"] = stat["p99_resolution_h"]
    audit["outliers_selected"] = sum(r["resolution_hours"] > stat["p99_resolution_h"] for r in sampled)
    audit["summary_selected"] = stat
    audit["category_selected"] = {
        c: metrics([r for r in sampled if r["category"] == c]) for c in cats
    }
    audit["month_selected"] = {
        m: metrics([r for r in sampled if r["month_code"] == code]) for m, code in MONTHS.items()
    }
    (args.out / "11_Проверка_расчётов.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Integrity tests: exhaustive contexts must exactly match their source subset.
    assert len(summary_rows) == len(month_options) * len(cat_options) == 24
    assert stat["requests"] == 716 and stat["sla_ontime"] == 435
    assert stat["sla_breaches"] == 281 and round(stat["sla_share"]*100, 2) == 60.75
    assert audit["clean_rows"] == 1377 and audit["duplicates"] == 12
    # Если исходный файл не содержит истинного признака FCR, проверяем оценку.
    if audit["fcr_column"] is None:
        assert stat["fcr_resolved_first"] == 650
        assert round(stat["fcr_share"] * 100, 2) == 90.78
        assert stat["fcr_estimated_cases"] == 716
    assert len(detail_rows) == 4 * len(sampled)
    for month_name in month_options:
        for category_name in cat_options:
            group = filtered(month_name, category_name)
            s = next(r for r in summary_rows if (r["month_selection"],r["category_selection"]) == (month_name,category_name))
            assert s["requests"] == len(group)
            assert sum(r["requests"] for r in category_rows
                      if r["month_selection"] == month_name and r["category_selection"] == category_name) == len(group)
            assert sum(r["requests"] for r in trend_rows
                      if r["month_selection"] == month_name and r["category_selection"] == category_name) == len(group)
    print("Готово. Выгружено в:", args.out.resolve())
    print(f"Исходно: {len(raw)}; очищено: {audit['clean_rows']}; январь–февраль: {stat['requests']}")
    print(f"SLA {stat['sla_share']:.2%}; медиана {stat['median_resolution_h']:.2f} ч; P90 {stat['p90_resolution_h']:.2f} ч")
    print(f"FCR: {stat['fcr_label']} — {stat['fcr_method']}")
    print("Таблиц для дашборда: 7; дополнительные файлы: аудит, очищенный журнал и выборка варианта №1.")


if __name__ == "__main__":
    main()
