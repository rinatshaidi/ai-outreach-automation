# P0 — Evidence-backed matching для Single Outreach

## Цель

Система должна находить не «компании с похожими словами», а редкие, проверяемые
возможности, где можно честно ответить на четыре вопроса:

1. Что у компании происходит сейчас?
2. Какой подтверждённый опыт владельца к этому относится?
3. Что именно можно предложить компании?
4. Почему есть смысл написать сейчас и кому?

Дневной лимит в пять компаний — верхняя граница нагрузки, а не KPI. Ноль новых
компаний допустим только после достаточного, понятного исследования; не после
HTTP 403, timeout или неполной проверки.

## Диагноз текущей реализации

- Профиль имеет достаточные структурированные и разрешённые для scoring данные.
- Daily discovery использует только широкие роли и отрасли, а не карту доказанных
  задач, предпочтений и стоп-факторов владельца.
- `opportunity-relevance-v1` начисляет базовые баллы за силу профиля, формат и
  общие opportunity tags. Это делает score похожим на оценку кандидата вообще,
  а не конкретного соответствия компании.
- Keyword matching в `supported_matches` появляется после оценки и не является
  обязательным основанием высокого score.
- Контактность ошибочно влияет на релевантность. Контакт нужен для действия,
  но отсутствие контакта не доказывает отсутствие fit.

## Целевая модель

### 1. Owner fit map

Профиль преобразуется в 2–3 явных профессиональных трека. Для каждого трека
хранятся:

- тип задач, которые владелец реально решал;
- подтверждённые доказательства опыта;
- допустимый формат: работа, проект, консалтинг, партнёрство;
- предпочтительные индустрии/контексты;
- стоп-факторы и границы позиционирования.

Трек не равен списку skills. Например, «запуск и координация проектов с
подрядчиками» — отдельная рабочая гипотеза с доказательствами, а не просто
`project management` + `contractors`.

#### Initial calibration v0.1 — confirmed tracks (2026-09-30)

The owner has confirmed the following three tracks. This is a matching contract,
not outward-facing copy and not a claim of suitability for every role within a
track.

| Track | What the system may look for | Owner-side proof required | Positioning boundary |
| --- | --- | --- | --- |
| Project delivery and operations | Project launches, operational delivery, coordination of contractors or complex execution work | Verified delivery, launch, operations or contractor-management evidence | Do not infer a domain-specialist credential from management experience alone. |
| Business development and expansion | New markets, partnerships, commercial launch, territory growth or an operationally relevant growth initiative | Verified negotiation, territory-development, launch or commercial-delivery evidence | A generic sales vacancy is not enough; there must be a plausible business-development contribution. |
| Practical AI/Python automation | A documented workflow, automation initiative, implementation need or operations problem suitable for automation | Verified practical technology evidence plus a real business/operations use case | Never position the owner as a senior ML engineer or imply unverified engineering depth. |

The current structured profile supports the calibration: it contains verified
experience evidence for delivery, contractor management, negotiations, territory
development, launches and operations management, as well as verified practical
technology evidence. Exact profile text remains private and is resolved only by
record identifiers inside the application.

For every future company card, this map must return a human-readable answer:

```text
track → company signal → owner proof → proposed contribution → reason to write → risk → action state
```

Example action states are `ready to contact`, `fit confirmed — find a contact`,
`research more`, and `not a match`. This replaces a bare percentage or a generic
"why it fits" paragraph.

### 2. Company opportunity evidence

Для match требуется хотя бы один свежий, проверенный факт из разрешённых типов:

- релевантная открытая вакансия;
- expansion, запуск, новый рынок, партнёрская программа;
- подтверждённая операционная / проектная / automation-потребность;
- публичная инициатива, на которую можно предложить конкретный вклад.

Общее описание компании, меню сайта, cookie-баннер, набор продуктов или только
наличие контакта не являются opportunity evidence.

The same exclusion applies to a capability keyword on the owner side. A company
cannot become recommended merely because both texts contain words such as
"projects", "growth" or "AI".

### 3. Match thesis

Каждая кандидатная компания получает один или несколько `MatchThesis`:

```text
company evidence → owner evidence → applicable contribution → reason to write → risk
```

Тезис создаётся только при наличии доказательства с обеих сторон. Он обязан
содержать source IDs, дату/свежесть и один из статусов:

- `READY_TO_CONTACT` — есть match thesis, достаточный current signal и путь к адресату;
- `MATCH_CONFIRMED_CONTACT_PENDING` — fit подтверждён, но контакт нужно искать;
- `RESEARCH_CANDIDATE` — правдоподобная гипотеза, но evidence ещё недостаточно;
- `NOT_A_MATCH` — нет fit или есть стоп-фактор.

### 4. Score как вторичная диагностика

Число не должно заменять тезис. Если отсутствует company opportunity evidence
или owner evidence, score не может дать `READY_TO_CONTACT` независимо от
остальных baseline points.

После gates score может ранжировать только сопоставимые тезисы:

- directness of fit — 0–40;
- strength/freshness of company signal — 0–25;
- realism of contribution — 0–20;
- addressability/contact path — 0–10;
- constraint compatibility — 0–5.

Риски не вычитаются скрыто: они показываются отдельно. Контактность влияет на
готовность к действию, не на факт профессионального соответствия.

## P0 tasks

1. **Profile calibration** — create the three confirmed tracks above from the
   current profile, link them to private evidence record IDs, and explicitly
   store their positioning boundaries and stop-factors.
2. **Evidence taxonomy** — отделить activity text от opportunity evidence;
   добавить freshness, source quality и запрет для web chrome.
3. **Match thesis service** — сопоставлять owner evidence и company evidence,
   сохранять связку и риск; не менять generation/delivery.
4. **Readiness states** — разделить `fit confirmed`, `contact pending` и
   `ready to contact`; вернуть непросмотренные компании в inbox независимо от
   отсутствия контакта.
5. **Score recalibration** — убрать profile-only baselines из решения, сохранить
   breakdown как secondary diagnostic.
6. **Calibration set** — вручную проверить 10–15 сохранённых компаний:
   интересна / неинтересна / причина. Результат используется для настройки
   правил, не для неявного обучения модели.
7. **Daily discovery gate** — искать до исчерпания исследовательского бюджета,
   а не завершать день после blocked sources; фиксировать `0` как отсутствие
   подтверждённых matches либо технически неполный поиск.

## Acceptance

Для любой компании, показанной в active inbox, владелец видит без raw research:

- один конкретный текущий signal компании и источник;
- один конкретный подтверждённый элемент своего опыта;
- реалистичный сценарий вклада;
- честный риск/неизвестность;
- лучший адресат либо явный статус «ищем контакт».

Компания без такой связки остаётся в research candidates, но не выглядит как
рекомендованная к обращению. Решённые компании переходят в history; непросмотренные
не исчезают из inbox.
