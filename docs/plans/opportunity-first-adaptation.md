# Opportunity-first adaptation plan

Актуальное ТЗ: `AI_OUTREACH_SYSTEM_TZ_MVP_v1.4.md`.

Версия `v1.3` сохранена без изменений. В `v1.4` между завершённым Этапом 9 и
Production decision добавлен обязательный Этап 10 Personalization and Local Pilot;
Production decision перенесён в Этап 11.

## Текущая точка (обновлено 2026-08-02)

- PostgreSQL backups перед `0003`–`0012`, включая `pre_0012_20260802_stage10.json.gz`, созданы и проверены.
- Alembic revision: `20260802_0012`.
- Mini-CRM schema применена.
- CRM API, Dashboard и Jinja2 routes проверены на PostgreSQL.
- Блок 1 (opportunity enums и DTO) завершён.
- Блок 2 (расширение Candidate Profile) завершён: additive schema, REST, UI и permissions.
- Блоки 3–6 завершены: persistence foundation, guarded pipeline, API/UI и decision gate.
- Этап 3 Research завершён: manual URL, safe fetcher, provenance, facts, signals,
  hypotheses, public-contact extraction, deduplication и timeouts.
- Этап 4 Relevance завершён: детерминированные восемь score-компонентов, versioned formula,
  input provenance, explicit thresholds, UI explanation и immutable manual override.
- Этап 5 Generation завершён: decision-gated Professional/Friendly drafts, structured adapter,
  prompt versioning, provenance, deterministic validators, blocked state и PII-free usage.
- Этап 6 Review Center завершён: A/B review, editor/regenerate, immutable revisions,
  approve/defer/reject/do-not-contact, source inspector, permissions panel и approval guards.
- Этап 7 Delivery завершён: Mailpit test-send, feature-gated real SMTP, atomic one-time
  approval consumption, idempotency, suppression, current consent revalidation и PII-safe audit.
- Этап 8 Follow-up и History завершён: business-day due calculation в IANA timezone,
  deterministic proposal/validator, manual approval/defer/reject/cancel, automatic cancellation,
  manual replies/outcomes и unified timeline/audit.
- Этап 9 Analytics и Portfolio завершён: read-only aggregate API, фильтры, opportunity funnel,
  outcome analytics, portfolio UI, synthetic `.example` demo, screenshots и CI quality gate.
- Техническая основа Этапа 10 реализована локально: single-owner auth/CSRF, 23 review states,
  purpose-specific permissions, preview-first structured import, readiness/calibration API и UI.
- Интеграционные тесты полного пути и аналитики добавлены; полный quality gate: 82 passed,
  Ruff и MyPy clean.
- Legacy Candidate Profile и consent history сохранены.

## План адаптации

### 1. Opportunity enums и DTO

Добавить типы opportunity, signals, positioning strategy, collaboration formats,
user decisions и новый pipeline vocabulary.

Готово, когда enum/DTO покрыты unit-тестами и не меняют существующую БД.

### 2. Расширение Candidate Profile

Добавить `CandidateExperience`, `CandidateSkill`, `CandidateStrength`, карьерные
предпочтения, независимые remote/hybrid/on-site/relocation/travel настройки и ограничения.

Использовать только additive migration `0004`; legacy profile fields, facts, contacts,
permissions и consent history сохранить.

### 3. Opportunity foundation

Добавить source/provenance foundation и сущности:

- `OpportunitySignal`;
- `CompanyOpportunity`;
- `OpportunityAssessment`;
- `PositioningRecommendation`.

Использовать новую migration `0005`; существующую `0003` не изменять.

### 4. Opportunity-first pipeline

Добавить новые статусы и guarded transitions. Выполнить явный backfill:

```text
qualified -> opportunity_identified
```

Разделить `APPROVED_FOR_OUTREACH` и approval конкретной ревизии письма. Добавить
watchlist, deferred, project discussion, consulting discussion и agreement.

### 5. API и UI

Добавить company-scoped endpoints для opportunities, signals, assessment, strategy и
user decision. Расширить Candidate Profile, Dashboard, Companies, Pipeline и карточку компании.

### 6. Пользовательский decision gate

Разрешать draft generation только после явного решения `outreach`. Обычный PATCH статуса
не должен обходить guard. Решения defer, deeper research, not relevant и watchlist должны
сохраняться отдельно и попадать в timeline/audit.

### 7. Детерминированный relevance scoring

Реализовать:

- `business_fit_score`;
- `ai_automation_fit_score`;
- `hybrid_fit_score`;
- `format_fit_score`;
- `geography_fit_score`;
- `timing_signal_score`;
- `contactability_score`;
- `overall_opportunity_score`.

Breakdown, input IDs, weights и formula version сохранять в `OpportunityAssessment`.
AI извлекает и объясняет, но не устанавливает итоговые числа.

### 8. Проверки

После каждого блока запускать Ruff, MyPy, unit/API/PostgreSQL integration tests и migration
checks. В финале выполнить upgrade с revision `0003`, проверку сохранности Candidate Profile,
Docker smoke-test и проверку отсутствия способов обойти consent/decision/approval.

## Следующее действие

Этапы 1–9 завершены. Этап 10 начат, его техническая основа и regression gate готовы. Следующий
контролируемый шаг — владелец локально создаёт credentials, входит в Dashboard и по блокам
согласует минимально достаточный реальный профиль. Затем выполняются первая волна 3–5 публичных
компаний, совместная calibration и расширенный цикл до 10 компаний, только через Mailpit.

Этап 10 нельзя отметить завершённым до реального pilot и явного принятия владельцем. Production
decision остаётся Этапом 11; VPS, публикация, внешний экспорт и реальные письма выключены.
