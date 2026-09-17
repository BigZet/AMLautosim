"""Postselected held-out game examples; not an independent accuracy estimate."""
import argparse
import json
from pathlib import Path
import pandas as pd

def export(data, model, output):
    frame = pd.read_csv(model / 'predictions.csv')
    frame = frame[frame.split == 'test'].merge(pd.read_csv(data / 'targets.csv').drop(columns='split'), on='scenario_id')
    cases = {r['scenario_id']: r for r in (json.loads(s) for s in (data / 'casebook.jsonl').read_text(encoding='utf8').splitlines())}
    context = json.loads((data / 'context.json').read_bytes())
    target = f"{float(context['objectives']['target_outflow']):,.0f}".replace(',', ' ')
    lines = ['# Примеры игровых цепочек', '',
             'Выбраны после оценки test: 10 низких, 10 высоких и 5 пограничных.',
             'Это демонстрации, не независимая проверка качества. Скор отражает учебные паттерны, не доказанную преступность.', '',
             f'Все цепочки достигают цели {target}; история общая, лимиты указаны в context.json.', '']
    for title, subset, count in [('Низкие', frame[frame.probability < .1], 10),
                                 ('Высокие', frame[frame.probability >= .9], 10),
                                 ('Пограничные', frame[(frame.probability >= .1) & (frame.probability < .9)], 5)]:
        ordered = subset.sort_values(['route_family', 'scenario_id'])
        selected = pd.concat([ordered.drop_duplicates('route_family'), ordered]).drop_duplicates('scenario_id').head(count)
        assert len(selected) == count
        lines += [f'## {title}', '']
        for row in selected.itertuples():
            case = cases[row.scenario_id]
            lines += [f'### {row.scenario_id}: {row.route_family}', '',
                      f'Скор **{100 * row.probability:.2f}/100**; цель разметки {100 * row.target_probability:.2f}; ресурсы {row.resource_score:.2f}.', '',
                      '| Шаг | Операция | Сумма | Сторона | Интервал, мин |', '|---:|---|---:|---|---:|']
            for n, s in enumerate(case['steps'], 1):
                party = s.get('sender_id', s.get('recipient_id', '—'))
                lines.append(f"| {n} | {s['card']['code']} | {s['amount']} | {party} | {s.get('interval_minutes') or 0} |")
            lines += ['', 'Сработавшие интерпретации: ' + json.dumps(case['rule_support'], ensure_ascii=False), '']
    output.write_text('\n'.join(lines), encoding='utf8')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path)
    parser.add_argument('model', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    export(args.data, args.model, args.output)
