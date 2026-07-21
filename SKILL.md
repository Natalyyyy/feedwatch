---
name: feedwatch
description: Мониторинг чужих публичных Instagram-аккаунтов и Telegram-каналов с отчётами в Telegram. Триггеры — «настрой мониторинг соцсетей», «настрой инстаграм-мониторинг», «настрой мониторинг каналов», «отчёт по инстаграму», «отчёт по каналам», «что залетело в инстаграме/телеграме», «проверь пульс», «добавь/убери аккаунт или канал из мониторинга», «обнови токен инстаграма».
---

# feedwatch — мониторинг Instagram и Telegram

Все команды выполняются из папки скилла (`cd` в папку, где лежит этот файл).
Python-скрипты: `fetch.py` (сбор), `report.py` (отчёты), `schedule.py` (расписание).

## Онбординг (первый запуск: нет `config.json` или `.env`)

Веди пользователя по шагам, по одному вопросу за раз, на русском:

1. **Python.** Проверь `python3 --version` (нужен 3.9+). Нет — на Маке
   предложи `xcode-select --install`, на Linux — пакетный менеджер.
   Затем `python3 -c "import requests"` — если нет, `python3 -m pip install requests`.
2. **Платформы.** Спроси, что мониторим: Instagram, Telegram или обе.
   - Instagram — источник данных:
     - **Apify** — любые публичные аккаунты; платно (~$2.5–3 за 1000 постов,
       при 10 аккаунтах с ежедневным пульсом ≈ $8–10/мес; бесплатного кредита
       $5/мес хватит попробовать). Нужен токен: apify.com → Sign up →
       Settings → Integrations → Personal API token.
     - **Meta Graph API** — бесплатно, но мониторить можно только
       бизнес/креатор-аккаунты, и нужен свой Instagram Business/Creator аккаунт,
       привязанный к странице Facebook. Шаги: developers.facebook.com →
       Create App (Business) → добавить продукт Instagram Graph API →
       Graph API Explorer → выдать права `instagram_basic`,
       `business_management`, `pages_show_list` → сгенерировать токен →
       обменять на long-lived (живёт 60 дней). `IG_BUSINESS_ID` — id своего
       IG-аккаунта: запрос `me/accounts` → `?fields=instagram_business_account`.
   - Telegram — источник данных:
     - **web** (по умолчанию) — веб-превью t.me, бесплатно и без ключей;
       не работает для каналов со скрытым превью.
     - **tgstat** — нужен платный токен api.tgstat.ru (кабинет TGStat →
       API), лимиты по тарифу; в `.env` — `TGSTAT_TOKEN`.
3. **Telegram-бот для доставки.** Бот: @BotFather → /newbot → токен. chat_id:
   пользователь пишет боту любое сообщение, затем
   `curl https://api.telegram.org/bot<TOKEN>/getUpdates` → `message.chat.id`.
4. **Аккаунты/каналы.** Список username без @. Запиши всё в `.env` (по образцу
   `.env.example`) и `config.json` (по образцу `config.example.json`) —
   секции `instagram` и/или `telegram`.
5. **Холодный старт.** `python3 fetch.py --limit 30` — база наполняется,
   медианы считаются с первого дня. Покажи пользователю, сколько постов
   собралось и какие аккаунты/каналы недоступны.
6. **Режим.** Спроси: ручной запуск или автоматика?
   - Ручной — ничего не делать, объясни триггеры («отчёт по инстаграму»,
     «отчёт по каналам», «проверь пульс»).
   - Автоматика — уточни времена (дефолты в config.json), затем
     `python3 schedule.py install`. Предупреди: еженедельный отчёт
     запускает headless Claude и тратит лимиты подписки пользователя.

## Ручные команды

- «отчёт по инстаграму» / «отчёт по каналам» / «что залетело в телеграме» →
  `python3 report.py weekly` (единый отчёт по всем настроенным платформам;
  показать в чате; спросить, отправить ли в ТГ — тогда с `--send`)
- «проверь пульс» → `python3 report.py pulse` (аналогично)
- «добавь @X в мониторинг» → дописать в `config.json` секцию `instagram` →
  `python3 fetch.py --limit 30` (холодный старт для нового аккаунта)
- «добавь канал @X» → дописать в `config.json` секцию `telegram` →
  `python3 fetch.py --limit 30`
- «убери @X» / «убери канал @X» → удалить из соответствующей секции
  `config.json`
- «выключи/включи автоматику» → `python3 schedule.py remove` / `install`
- «как там мониторинг» → `python3 schedule.py status` (+ на macOS хвосты
  `data/*.log`; в cron на Linux логов нет)

## Обновление токена Meta («обнови токен инстаграма»)

Токен живёт 60 дней. Веди по шагам: Graph API Explorer → сгенерировать
новый user token с теми же правами → обменять на long-lived:
`https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id=<APP_ID>&client_secret=<APP_SECRET>&fb_exchange_token=<КОРОТКИЙ_ТОКЕН>`
→ записать новый токен в `.env` (`IG_ACCESS_TOKEN`) → проверить:
`python3 fetch.py --limit 3`.

## Важно

- Ссылка на пост обязана быть в каждой строке отчёта — это уже зашито в код,
  не переписывай форматтеры.
- Все сравнения — в кратных медианы аккаунта, не в абсолютных цифрах.
- Секреты только в `.env`, не в config.json и не в git.
