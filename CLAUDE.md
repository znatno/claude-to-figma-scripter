# claude-to-figma-scripter — інструкції для Claude Code

## Що це

Малюємо дизайн у Figma через Scripter плагін (Figma Plugin API).
Правила генерації коду — в `scripter.md` (скіл claude-to-figma-scripter).

## run.py — основний спосіб

Окремий Python-процес тримає Firefox з Figma і Scripter.

### Запуск сервера (ідемпотентно — безпечно викликати щоразу)

```bash
# Без креденшалів — якщо нема .auth-state.json, буде чекати ручного логіну (Google/SSO/2FA — все працює)
python run.py --ensure FIGMA_URL

# З креденшалами — автозаповнення форми
python run.py --ensure FIGMA_URL EMAIL PASSWORD
```

`--ensure` перевіряє `/tmp/claude-figma.fifo`. Якщо сервер уже крутиться — повертає "server already running" за <1с. Інакше — спавнить `--serve` у фоні і чекає "Scripter opened." у `/tmp/claude-figma.log` (до 2.5 хв з креденшалами, до 6 хв при ручному логіні).

### Виконання коду

```bash
python run.py "figma plugin api код"        # inline
python run.py --file script.js              # з файлу (рекомендовано)
```

### Запуск плагінів (Propstar і т.д.)

```bash
python run.py "__plugin__:Propstar > Create property table"
python run.py "__reopen_scripter__"   # після плагіна
```

### Без скріншотів

Не робити скріншот якщо користувач не просить побачити результат.
`figma.notify()` в try/catch підтвердить успіх. Сервер виводить "OK".

---

## Ключові правила та як уникати помилок

### 1. Два етапи для складних макетів (ОБОВ'ЯЗКОВО)

**Проблема:** великий скрипт з `setBoundVariableForPaint` + створення нод падає мовчки, створюються тільки перші кілька елементів, решта зникає без помилки.

**Рішення:** завжди розділяти на два скрипти:
1. **Скрипт 1** — створити ВСЮ візуальну структуру з хардкод RGB кольорами
2. **Скрипт 2** — пройтись по нодах через `findOne/findAll` і прив'язати змінні

**Чому:** якщо binding впаде, візуал вже створений і не втрачається. Кожен крок можна перевірити окремо.

### 2. Прив'язка змінних до fills/strokes

**Проблема:** `node.setBoundVariable("fills", 0, v)` кидає помилку:
`"fills and strokes variable bindings must be set on paints directly"`

**Рішення:** використовувати `figma.variables.setBoundVariableForPaint()`:
```ts
const f = JSON.parse(JSON.stringify(node.fills));
f[0] = figma.variables.setBoundVariableForPaint(f[0], "color", v);
node.fills = f;
```

**Чому `JSON.parse(JSON.stringify(...))`:** `node.fills` повертає frozen array — пряма мутація кидає `Cannot assign to read only property`.

**Для числових пропертів** (radius, width, height, padding) — `setBoundVariable` працює нормально:
```ts
node.setBoundVariable("topLeftRadius", v);
```

Детально — `scripter.md`, Rule 7.

### 3. Перевірка результату після кожного скрипта

**Проблема:** `output.txt` часто не оновлюється (Scripter output panel кешує старий вивід). Дивишся на нього і думаєш що скрипт не спрацював, або навпаки.

**Рішення:**
- `figma.notify("msg")` — завжди видно на скріншоті (зелена/червона панель внизу)
- Окремий dump-скрипт для верифікації структури (print дерева нод)
- `tail -N /tmp/claude-figma.log` — сервер друкує "OK" або "Error" після кожного виконання
- Скріншот (`result.png`) — останній засіб, якщо все інше не працює

### 4. Іменування нод для Step 2

**Проблема:** в Step 2 (binding) потрібно знайти конкретні ноди. Без імен — неможливо.

**Рішення:** в Step 1 давати осмислені `name` кожному фрейму/прямокутнику:
```ts
row.name = "Semantic";        // findOne(n => n.name === "Semantic")
swatch.name = "Primary";      // findOne(n => n.name === "Primary")
pill.name = "Blue";            // findOne(n => n.name === "Blue")
```

### 5. Propstar після кожного Component Set

**Проблема:** без Propstar Component Set — це вертикальна стрічка з 100+ варіантів, в якій нічого не зрозуміло.

**Рішення:** після `figma.combineAsVariants()` обов'язково:
```bash
# 1. Виділити компонент (через Scripter)
python run.py --file select_component.js

# 2. Запустити Propstar
python run.py "__plugin__:Propstar > Create property table"

# 3. Зачекати ~15с, потім перевідкрити Scripter
sleep 15
python run.py "__reopen_scripter__"
```

**Що робить Propstar:** розкладає всі варіанти в сітку по properties (Variant × Size × State), підписує рядки і колонки.

### 6. Перезапуск сервера

**Проблема:** `pkill -f "run.py --serve"` з наступним стартом часто дає `exit code 144`.

**Рішення:** використовуй `--ensure` замість голого `--serve` — він сам робить startup + readiness polling:
```bash
# Зупинити (може дати 144 — це ОК)
pkill -f "run.py --serve" 2>/dev/null; sleep 2; rm -f /tmp/claude-figma.fifo

# Запустити знову (блокує поки не стане ready)
python run.py --ensure "FIGMA_URL"
```

`--ensure` чекає появи "Scripter opened." у `/tmp/claude-figma.log` і повертає керування тільки коли сервер готовий. На Linux додай `DISPLAY=:99` перед командою.

### 7. Розмір скриптів

**Проблема:** дуже великі скрипти (>8KB) можуть мовчки обрізатись при clipboard paste в Scripter.

**Рішення:**
- Використовувати `--file` замість inline коду
- Якщо скрипт >5KB — розбити на кілька менших
- Мінімізувати код: короткі імена змінних, без зайвих пробілів
- Хелпери (`bF`, `bS`, `bN`) замість повних викликів

### 8. Радіуси в Aethra DS: --radius = 4px

**Проблема:** `rounded-lg` за замовчуванням в Tailwind = 8px, але в цій дизайн-системі `--radius: 0.25rem` = 4px. Тому `rounded-lg = var(--radius) = 4px`.

**Таблиця:**
- `rounded` (Tailwind default) = `var(--radius)` = **4px** → використати `radius/lg`
- `rounded-sm` = `calc(var(--radius) - 4px)` = **0px** → `radius/sm`
- `rounded-md` = `calc(var(--radius) - 2px)` = **2px** → `radius/md`
- `rounded-lg` = `var(--radius)` = **4px** → `radius/lg` (НЕ 8px!)
- `rounded-xl` = `calc(var(--radius) + 4px)` = **8px** → `radius/xl`

**Як перевіряти:** через Playwright `getComputedStyle(el).borderRadius` на rendered компоненті — це єдине джерело правди для обчислених значень.

### 9. Аудит через Scripter текстом (без скріншотів)

**Як:** запустити скрипт який `print()` дерево нод з розмірами, потім зчитати `output.txt`.

**Важливо:**
- `print()` в Scripter виводить тільки один виклик (останній перезаписує попередній)
- Тому збирати все в один `print(lines.join("\\n"))`
- Символи Unicode (❖) ламають `String()` конкатенацію → санітизувати через `.replace(/[^\\x20-\\x7E]/g, "")`

### 10. Порядок створення Auto Layout фрейму

**Проблема:** `resize()`, `itemSpacing`, `paddingTop` і т.д. ігноруються якщо встановлені ДО `layoutMode`.

**Рішення:** строгий порядок:
```ts
const f = figma.createFrame();
parent.appendChild(f);          // 1. Спочатку додати в дерево
f.layoutMode = "VERTICAL";      // 2. Потім layoutMode
f.resize(400, 100);             // 3. Потім розмір
f.primaryAxisSizingMode = "AUTO"; // 4. Потім sizing mode
f.itemSpacing = 16;             // 5. Потім spacing/padding
f.paddingTop = 24;
```

---

## Коментарі Figma

Для читання коментарів використовуй Figma REST API (див. `figma-comments.md`).
**Потрібен токен** — якщо його немає, попроси користувача:

> Щоб читати коментарі з Figma, мені потрібен REST API токен. Згенеруй на https://www.figma.com/developers/api#access-tokens і скинь сюди.

```bash
curl -s -H "X-Figma-Token: TOKEN" "https://api.figma.com/v1/files/FILE_KEY/comments"
```

Фільтруй по `resolved_at` — показуй тільки невирішені.

---

## MCP fallback

Якщо run.py недоступний — один `browser_run_code` з clipboard paste + Run.

Firefox: `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`
Профіль зайнятий: `pkill -f "firefox.*mcp-firefox"`

## Браузер

Playwright MCP з Firefox. Конфіг у `.mcp.json`.
Xvfb віртуальний дисплей (`DISPLAY=:99`) для headed режиму.
