# Примеры игровых цепочек

Выбраны после оценки test: 10 низких, 10 высоких и 5 пограничных.
Это демонстрации, не независимая проверка качества. Скор отражает учебные паттерны, не доказанную преступность.

Все цепочки достигают цели 360 000; история общая, лимиты указаны в context.json.

## Низкие

### game-grey-0-06821: cash_reserve

Скор **9.75/100**; цель разметки 10.45; ресурсы 31.29.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | cash_withdrawal | 52059.30 | — | 0 |
| 2 | card_transfer | 37516.10 | A | 1 |
| 3 | cash_withdrawal | 51631.20 | — | 1 |
| 4 | incoming_transfer | 80000 | D | 1 |
| 5 | card_transfer | 73218.60 | A | 1 |
| 6 | incoming_transfer | 80000 | D | 1 |
| 7 | card_transfer | 27421.30 | A | 1 |
| 8 | card_transfer | 65311.30 | A | 1 |
| 9 | incoming_transfer | 80000 | D | 1 |
| 10 | card_transfer | 40505.40 | A | 1 |
| 11 | card_transfer | 12336.80 | A | 1 |

Сработавшие интерпретации: {"matched_relay": 63}

### game-low-0-00011: cash_then_pause

Скор **0.01/100**; цель разметки 0.00; ресурсы 33.48.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | cash_withdrawal | 54000.00 | — | 0 |
| 2 | card_transfer | 72000.00 | A | 1 |
| 3 | incoming_transfer | 80000 | C | 1 |
| 4 | card_transfer | 45000.00 | A | 1 |
| 5 | incoming_transfer | 80000 | D | 1 |
| 6 | cash_withdrawal | 54000.00 | — | 1440 |
| 7 | card_transfer | 63000.00 | A | 1 |
| 8 | incoming_transfer | 80000 | A | 1 |
| 9 | card_transfer | 72000.00 | A | 1 |

Сработавшие интерпретации: {}

### game-low-0-00287: eight_repeated

Скор **0.01/100**; цель разметки 0.00; ресурсы 32.66.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | card_transfer | 30688.00 | C | 0 |
| 2 | card_transfer | 45000.00 | D | 1 |
| 3 | incoming_transfer | 80000 | B | 1 |
| 4 | card_transfer | 45280.80 | B | 1 |
| 5 | card_transfer | 35021.00 | D | 1 |
| 6 | incoming_transfer | 80000 | A | 1 |
| 7 | card_transfer | 53021.00 | D | 1 |
| 8 | card_transfer | 45000.00 | D | 1 |
| 9 | incoming_transfer | 80000 | A | 1 |
| 10 | card_transfer | 55833.20 | B | 10 |
| 11 | card_transfer | 50156.00 | B | 1 |

Сработавшие интерпретации: {}

### game-low-0-00442: fixture-00

Скор **0.00/100**; цель разметки 0.00; ресурсы 29.50.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | incoming_transfer | 80000 | D | 0 |
| 2 | incoming_transfer | 80000 | D | 1 |
| 3 | card_transfer | 57526.40 | D | 1440 |
| 4 | incoming_transfer | 80000 | D | 1 |
| 5 | card_transfer | 63759.60 | C | 1440 |
| 6 | card_transfer | 73993.30 | B | 1 |
| 7 | cash_withdrawal | 48510.30 | — | 1 |
| 8 | card_transfer | 58937.00 | C | 1 |
| 9 | card_transfer | 57273.40 | B | 1 |

Сработавшие интерпретации: {}

### game-low-0-00031: fixture-01

Скор **0.05/100**; цель разметки 0.00; ресурсы 19.83.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | salary | 30000 | employer | 0 |
| 2 | card_transfer | 76528.50 | A | 1 |
| 3 | card_transfer | 70571.70 | B | 1 |
| 4 | incoming_transfer | 79381 | D | 1 |
| 5 | card_transfer | 56958.00 | D | 1 |
| 6 | incoming_transfer | 79438 | B | 60 |
| 7 | card_transfer | 61075.00 | C | 1 |
| 8 | card_transfer | 73775.00 | D | 1 |
| 9 | cash_withdrawal | 21091.80 | — | 1 |

Сработавшие интерпретации: {}

### game-low-0-01196: fixture-02

Скор **0.00/100**; цель разметки 0.00; ресурсы 22.27.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | incoming_transfer | 76342 | C | 0 |
| 2 | card_transfer | 70200.00 | B | 1440 |
| 3 | card_transfer | 57034.80 | B | 10 |
| 4 | incoming_transfer | 75920 | C | 1 |
| 5 | card_transfer | 58563.80 | B | 1440 |
| 6 | cash_withdrawal | 41475.90 | — | 1 |
| 7 | incoming_transfer | 77494 | C | 1 |
| 8 | card_transfer | 73650.00 | B | 1440 |
| 9 | card_transfer | 59075.50 | B | 1 |

Сработавшие интерпретации: {}

### game-low-0-02405: fixture-04

Скор **0.00/100**; цель разметки 0.00; ресурсы 25.32.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | card_transfer | 78625.00 | C | 0 |
| 2 | cash_withdrawal | 93694.60 | — | 1 |
| 3 | incoming_transfer | 75937 | D | 1 |
| 4 | card_transfer | 76006.70 | D | 1440 |
| 5 | incoming_transfer | 75702 | C | 1 |
| 6 | card_transfer | 64438.80 | B | 1440 |
| 7 | incoming_transfer | 77620 | A | 1 |
| 8 | card_transfer | 47234.90 | C | 1440 |

Сработавшие интерпретации: {}

### game-grey-0-04755: fixture-05

Скор **9.45/100**; цель разметки 10.61; ресурсы 31.28.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | card_transfer | 74908.00 | D | 0 |
| 2 | card_transfer | 75107.00 | D | 10 |
| 3 | incoming_transfer | 80000 | C | 1 |
| 4 | card_transfer | 65985.00 | D | 10 |
| 5 | incoming_transfer | 80000 | D | 1 |
| 6 | card_transfer | 71200.00 | D | 1440 |
| 7 | incoming_transfer | 80000 | B | 10 |
| 8 | card_transfer | 72800.00 | D | 1 |

Сработавшие интерпретации: {"matched_relay": 64}

### game-low-0-01328: fixture-06

Скор **0.01/100**; цель разметки 0.00; ресурсы 15.54.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | card_transfer | 31333.00 | B | 0 |
| 2 | card_transfer | 49371.10 | B | 1 |
| 3 | incoming_transfer | 80000 | C | 1 |
| 4 | card_transfer | 55963.00 | B | 1440 |
| 5 | card_transfer | 47500.00 | A | 1 |
| 6 | incoming_transfer | 80000 | B | 1 |
| 7 | card_transfer | 56961.00 | B | 1440 |
| 8 | card_transfer | 60251.90 | A | 1 |
| 9 | incoming_transfer | 80000 | B | 1 |
| 10 | card_transfer | 29576.00 | C | 1440 |
| 11 | card_transfer | 49044.00 | C | 1 |

Сработавшие интерпретации: {}

### game-grey-0-06902: fixture-07

Скор **9.11/100**; цель разметки 10.45; ресурсы 36.18.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | card_transfer | 67772.70 | A | 0 |
| 2 | incoming_transfer | 80000 | B | 1 |
| 3 | card_transfer | 63000.00 | A | 1 |
| 4 | card_transfer | 67784.30 | A | 1 |
| 5 | incoming_transfer | 80000 | B | 1 |
| 6 | card_transfer | 33702.00 | A | 1 |
| 7 | incoming_transfer | 80000 | B | 1 |
| 8 | card_transfer | 62443.00 | A | 1 |
| 9 | card_transfer | 65298.00 | A | 1 |

Сработавшие интерпретации: {"matched_relay": 63}

## Высокие

### game-high-0-16822: cash_reserve

Скор **92.43/100**; цель разметки 92.54; ресурсы 28.45.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | cash_withdrawal | 50954.05 | — | 0 |
| 2 | card_transfer | 58215.50 | B | 1 |
| 3 | cash_withdrawal | 61718.00 | — | 1 |
| 4 | incoming_transfer | 77969 | D | 1 |
| 5 | card_transfer | 30197.65 | B | 1 |
| 6 | incoming_transfer | 76701 | D | 1 |
| 7 | card_transfer | 12981.60 | B | 1 |
| 8 | card_transfer | 73698.65 | B | 1 |
| 9 | incoming_transfer | 78343 | D | 1 |
| 10 | card_transfer | 17960.60 | B | 1 |
| 11 | card_transfer | 74273.95 | B | 1 |

Сработавшие интерпретации: {"matched_relay": 558}

### game-high-0-00184: cash_then_pause

Скор **99.97/100**; цель разметки 100.00; ресурсы 32.36.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | cash_withdrawal | 48616.50 | — | 0 |
| 2 | card_transfer | 74919.20 | B | 1 |
| 3 | incoming_transfer | 80000 | B | 1 |
| 4 | card_transfer | 53628.20 | C | 1 |
| 5 | incoming_transfer | 80000 | A | 1 |
| 6 | cash_withdrawal | 67272.50 | — | 1 |
| 7 | card_transfer | 56317.25 | C | 1 |
| 8 | incoming_transfer | 80000 | B | 60 |
| 9 | card_transfer | 79246.35 | D | 60 |

Сработавшие интерпретации: {"cash_conversion": 603, "matched_relay": 52}

### game-high-0-00194: eight_repeated

Скор **100.00/100**; цель разметки 100.00; ресурсы 33.99.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | card_transfer | 54449.00 | D | 0 |
| 2 | card_transfer | 47331.00 | D | 1 |
| 3 | incoming_transfer | 80000 | D | 1 |
| 4 | card_transfer | 34500.00 | D | 1 |
| 5 | card_transfer | 39615.00 | D | 1 |
| 6 | incoming_transfer | 80000 | D | 1 |
| 7 | card_transfer | 39763.30 | D | 1 |
| 8 | card_transfer | 43720.00 | D | 1 |
| 9 | incoming_transfer | 80000 | D | 1 |
| 10 | card_transfer | 57640.70 | D | 1 |
| 11 | card_transfer | 42981.00 | D | 1 |

Сработавшие интерпретации: {"repeated_returns": 603}

### game-high-0-00314: fixture-00

Скор **99.98/100**; цель разметки 100.00; ресурсы 35.28.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | incoming_transfer | 80000 | C | 0 |
| 2 | incoming_transfer | 80000 | A | 1 |
| 3 | card_transfer | 77976.00 | B | 1 |
| 4 | incoming_transfer | 80000 | B | 1 |
| 5 | card_transfer | 79049.00 | D | 1 |
| 6 | card_transfer | 58033.00 | C | 1 |
| 7 | cash_withdrawal | 25751.00 | — | 1 |
| 8 | card_transfer | 79405.00 | B | 1 |
| 9 | card_transfer | 79786.00 | C | 1 |

Сработавшие интерпретации: {"matched_relay": 603}

### game-high-0-01981: fixture-01

Скор **99.98/100**; цель разметки 100.00; ресурсы 37.51.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | card_transfer | 64220.40 | B | 0 |
| 2 | card_transfer | 67339.00 | B | 1 |
| 3 | incoming_transfer | 80000 | D | 1 |
| 4 | card_transfer | 77448.80 | B | 1 |
| 5 | incoming_transfer | 80000 | D | 1 |
| 6 | card_transfer | 57094.20 | B | 1 |
| 7 | incoming_transfer | 80000 | D | 1 |
| 8 | card_transfer | 78611.10 | B | 1 |
| 9 | cash_withdrawal | 15286.50 | — | 1 |

Сработавшие интерпретации: {"matched_relay": 603}

### game-high-0-00048: fixture-02

Скор **99.98/100**; цель разметки 100.00; ресурсы 37.51.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | incoming_transfer | 80000 | C | 0 |
| 2 | card_transfer | 73797.00 | D | 1 |
| 3 | card_transfer | 73842.50 | D | 1 |
| 4 | incoming_transfer | 80000 | B | 1 |
| 5 | card_transfer | 61444.00 | D | 1 |
| 6 | cash_withdrawal | 24085.50 | — | 1 |
| 7 | incoming_transfer | 80000 | D | 1 |
| 8 | card_transfer | 56073.00 | D | 1 |
| 9 | card_transfer | 70758.00 | D | 1 |

Сработавшие интерпретации: {"matched_relay": 318, "consolidation": 603}

### game-grey-0-05265: fixture-03

Скор **91.82/100**; цель разметки 85.07; ресурсы 38.28.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | incoming_transfer | 77309 | B | 0 |
| 2 | card_transfer | 42594.00 | B | 1 |
| 3 | cash_withdrawal | 40097.70 | — | 1 |
| 4 | incoming_transfer | 75032 | B | 1 |
| 5 | card_transfer | 77177.90 | B | 1 |
| 6 | card_transfer | 68296.40 | B | 1 |
| 7 | incoming_transfer | 78006 | B | 1 |
| 8 | cash_withdrawal | 58787.00 | — | 1 |
| 9 | card_transfer | 73047.00 | B | 1 |

Сработавшие интерпретации: {"matched_relay": 513, "cash_conversion": 501, "repeated_returns": 405}

### game-high-0-00188: fixture-04

Скор **100.00/100**; цель разметки 100.00; ресурсы 39.90.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | card_transfer | 67631.40 | C | 0 |
| 2 | cash_withdrawal | 86106.60 | — | 1 |
| 3 | incoming_transfer | 77437 | C | 1 |
| 4 | card_transfer | 67841.10 | C | 1 |
| 5 | incoming_transfer | 75016 | C | 1 |
| 6 | card_transfer | 71262.00 | C | 1 |
| 7 | incoming_transfer | 75311 | C | 1 |
| 8 | card_transfer | 67158.90 | C | 1 |

Сработавшие интерпретации: {"matched_relay": 345, "repeated_returns": 603}

### game-high-0-00217: fixture-05

Скор **93.47/100**; цель разметки 93.53; ресурсы 39.50.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | card_transfer | 76000.00 | D | 0 |
| 2 | card_transfer | 76000.00 | D | 1 |
| 3 | incoming_transfer | 80000 | B | 1 |
| 4 | card_transfer | 76000.00 | D | 1 |
| 5 | incoming_transfer | 80000 | A | 1 |
| 6 | card_transfer | 76000.00 | D | 1 |
| 7 | incoming_transfer | 80000 | D | 1 |
| 8 | card_transfer | 76000.00 | D | 1 |

Сработавшие интерпретации: {"matched_relay": 564}

### game-high-0-00025: fixture-06

Скор **100.00/100**; цель разметки 100.00; ресурсы 20.66.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | card_transfer | 22254.20 | D | 0 |
| 2 | card_transfer | 21579.30 | D | 1 |
| 3 | incoming_transfer | 80000 | D | 1 |
| 4 | card_transfer | 57470.00 | D | 10 |
| 5 | card_transfer | 63112.50 | D | 1 |
| 6 | incoming_transfer | 80000 | D | 1 |
| 7 | card_transfer | 46458.00 | D | 1 |
| 8 | card_transfer | 54918.30 | D | 1440 |
| 9 | incoming_transfer | 80000 | D | 1 |
| 10 | card_transfer | 51386.20 | D | 60 |
| 11 | card_transfer | 42821.50 | D | 60 |

Сработавшие интерпретации: {"repeated_returns": 603}

## Пограничные

### game-grey-0-01303: cash_reserve

Скор **66.27/100**; цель разметки 66.67; ресурсы 9.62.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | salary | 30000 | employer | 0 |
| 2 | cash_withdrawal | 33473.00 | — | 1 |
| 3 | card_transfer | 65991.00 | C | 1 |
| 4 | cash_withdrawal | 72607.00 | — | 1 |
| 5 | card_transfer | 16598.00 | C | 1 |
| 6 | incoming_transfer | 79022 | C | 1 |
| 7 | card_transfer | 36527.90 | C | 1 |
| 8 | card_transfer | 57991.00 | C | 1 |
| 9 | incoming_transfer | 79940 | C | 1 |
| 10 | card_transfer | 35611.00 | C | 1440 |
| 11 | card_transfer | 41201.10 | C | 10 |

Сработавшие интерпретации: {"repeated_returns": 402}

### game-grey-0-00095: cash_then_pause

Скор **33.05/100**; цель разметки 33.33; ресурсы 28.14.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | cash_withdrawal | 44424.90 | — | 0 |
| 2 | card_transfer | 79841.10 | A | 1 |
| 3 | incoming_transfer | 80000 | B | 1 |
| 4 | card_transfer | 34594.80 | A | 60 |
| 5 | incoming_transfer | 80000 | D | 1 |
| 6 | cash_withdrawal | 71067.10 | — | 1 |
| 7 | card_transfer | 52166.30 | A | 1 |
| 8 | incoming_transfer | 80000 | B | 1440 |
| 9 | card_transfer | 77905.80 | A | 60 |

Сработавшие интерпретации: {"matched_relay": 111, "cash_conversion": 201}

### game-grey-0-00128: eight_repeated

Скор **45.94/100**; цель разметки 46.27; ресурсы 30.43.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | card_transfer | 66030.00 | C | 0 |
| 2 | card_transfer | 35432.00 | C | 1 |
| 3 | incoming_transfer | 80000 | C | 1 |
| 4 | card_transfer | 42646.00 | A | 1 |
| 5 | card_transfer | 49436.00 | B | 1 |
| 6 | incoming_transfer | 80000 | D | 1 |
| 7 | card_transfer | 57401.00 | B | 1 |
| 8 | card_transfer | 48306.00 | C | 1 |
| 9 | incoming_transfer | 80000 | D | 1 |
| 10 | card_transfer | 49529.00 | A | 1 |
| 11 | card_transfer | 51220.00 | B | 1 |

Сработавшие интерпретации: {"repeated_fanout": 279}

### game-grey-0-00307: fixture-00

Скор **72.47/100**; цель разметки 70.15; ресурсы 26.76.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | incoming_transfer | 78539 | A | 0 |
| 2 | incoming_transfer | 78434 | B | 60 |
| 3 | card_transfer | 71561.00 | A | 1 |
| 4 | incoming_transfer | 77671 | B | 1 |
| 5 | card_transfer | 75725.00 | A | 1 |
| 6 | card_transfer | 63362.30 | A | 1 |
| 7 | cash_withdrawal | 25126.00 | — | 1 |
| 8 | card_transfer | 76639.00 | A | 1 |
| 9 | card_transfer | 67586.70 | A | 1440 |

Сработавшие интерпретации: {"matched_relay": 423, "consolidation": 402}

### game-grey-0-00122: fixture-01

Скор **32.53/100**; цель разметки 32.01; ресурсы 30.85.

| Шаг | Операция | Сумма | Сторона | Интервал, мин |
|---:|---|---:|---|---:|
| 1 | card_transfer | 65513.00 | A | 0 |
| 2 | card_transfer | 64716.30 | C | 10 |
| 3 | incoming_transfer | 80000 | C | 1 |
| 4 | card_transfer | 64682.00 | D | 1 |
| 5 | incoming_transfer | 80000 | A | 1 |
| 6 | card_transfer | 75684.70 | B | 60 |
| 7 | incoming_transfer | 80000 | B | 10 |
| 8 | card_transfer | 74916.00 | A | 1 |
| 9 | cash_withdrawal | 14488.00 | — | 1 |

Сработавшие интерпретации: {"matched_relay": 193}
