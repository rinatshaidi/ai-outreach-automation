# Single Outreach System - visual polish brief

## Goal

Refine the visual presentation of the existing FastAPI/Jinja web application.
Do not redesign the product logic, data model, search/research pipeline, scoring,
contacts, draft generation, revisions, owner decisions, Gmail integration, or permissions.

The primary workflow is company-centric:

Search -> selected companies -> open company -> read decision brief -> contacts ->
prepare message -> edit or AI rewrite -> confirm -> copy/send manually or defer.

The application is a private single-owner tool. Use fictional company names and no personal
or production data in any visual prototype.

## Visual direction

- Calm, premium, credible private-workspace interface; not a generic SaaS dashboard.
- Generous whitespace, restrained blue accent, warm neutral background, strong readable type.
- Do not use KPI tiles, score dashboards, excessive pills, or technical status codes.
- Russian is the default dashboard locale; every visible label must have an English equivalent.
- Responsive first: desktop is a focused workspace; iPhone is a comfortable vertical flow.

## Screen 1: selected companies inbox

Header:

- Title: `Подобранные компании`.
- A full-width search field: `Что найти?` and one button: `Найти`.
- Quiet helper: `Можно искать по отрасли, стране или вставить сайт конкретной компании.`
- Secondary text link: `История поиска`.

List:

- Title: `Новые компании`.
- Compact cards only for companies that need a decision.
- Each card: company name, one-line description, country/industry, why selected,
  current signal, contact status, last research date.
- Primary action: `Открыть компанию`; secondary: `Не интересно`.
- Do not show scores, `Стоит рассмотреть`, or internal pipeline labels on cards.

## Screen 2: company workspace

Top header: company name, website, country, industry, last research date, human owner state.

Navigation: `Краткий вывод`, `Исследование`, `Контакты`, `Письмо`, `Активность`.

Decision brief should be a compact executive block, not a large grid of cards:

1. Why it is in the inbox.
2. What matters now.
3. Where the owner’s experience may help.
4. Best contact and main risk.
5. One clear next action.

Full research remains below but should use readable sections and expandable secondary detail.

## Screen 3: message workspace

Show two dimensions clearly:

- Format: `Развёрнутое письмо` / `Короткое сообщение`.
- Tone: `Профессиональный` / `Дружелюбный`.

The editable message is central. Actions:

- `Сохранить новую версию`
- `Скопировать письмо` / `Скопировать сообщение`
- `Изменить с помощью ИИ`
- `Подтвердить`
- `Отложить`
- `Не использовать`

AI rewrite is secondary. Replace a large ambiguous field with compact suggestion chips
(`Сделать короче`, `Теплее`, `Акцент на AI`) plus an optional custom instruction.
Manual editing must remain obvious and independent from AI.

For a short message, show verified social channels as optional external links. Never imply that
the system sends messages to LinkedIn, Facebook, VK, or Telegram automatically.

## Profile

Normal profile editing is simple and grouped by: positioning, work preferences, experience,
skills, strengths, contacts, and permissions. The verbose final verification is a collapsed
secondary `Проверка данных и безопасность` section, not normal profile content.

## Mobile

- One-column flow.
- Search remains at the top.
- Cards and sections have 16px minimum tap targets.
- Horizontal format/tone controls scroll safely or become a segmented control.
- No wide data tables.
- Keep primary action sticky only when it materially helps; do not obscure text.

## Explicit exclusions

- No dashboard analytics redesign.
- No new CRM/pipeline architecture.
- No data deletion.
- No real external send UI enabled by default.
- No SaaS/multi-user/billing features.
