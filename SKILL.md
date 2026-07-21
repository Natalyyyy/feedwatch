---
name: instawatch
description: Мониторинг чужих публичных Instagram-аккаунтов с отчётами в Telegram. Триггеры — «настрой инстаграм-мониторинг», «отчёт по инстаграму», «что залетело в инстаграме», «проверь пульс инстаграма», «добавь/убери аккаунт из мониторинга», «обнови токен инстаграма».
---

# instawatch — мониторинг Instagram-аккаунтов

Все команды выполняются из папки скилла (`cd` в папку, где лежит этот файл).
Python-скрипты: `fetch.py` (сбор), `report.py` (отчёты), `schedule.py` (расписание).

## Онбординг (первый запуск: нет `config.json` или `.env`)

Веди пользователя по шагам, по одному вопросу за раз, на русском:

1. **Python.** Проверь `python3 --version` (нужен 3.9+). Нет — на Маке
   предложи `xcode-select --install`, на Linux — пакетный менеджер.
   Затем `python3 -c "import requests"` — если нет, `python3 -m pip install requests`.
2. **Источник данных.** Объясни выбор:
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
3. **Telegram.** Бот: @BotFather → /newbot → токен. chat_id: пользователь пишет
   боту любое сообщение, затем `curl https://api.telegram.org/bot<TOKEN>/getUpdates`
   → `message.chat.id`.
4. **Аккаунты.** Список username без @. Запиши всё в `.env` (по образцу
   `.env.example`) и `config.json` (по образцу `config.example.json`).
5. **Холодный старт.** `python3 fetch.py --limit 30` — база наполняется,
   медианы считаются с первого дня. Покажи пользователю, сколько постов
   собралось и какие аккаунты недоступны.
6. **Режим.** Спроси: ручной запуск или автоматика?
   - Ручной — ничего не делать, объясни триггеры («отчёт по инстаграму»,
     «проверь пульс»).
   - Автоматика — уточни времена (дефолты в config.json), затем
     `python3 schedule.py install`. Предупреди: еженедельный отчёт
     запускает headless Claude и тратит лимиты подписки пользователя.

## Ручные команды

- «отчёт по инстаграму» → `python3 report.py weekly` (показать в чате;
  спросить, отправить ли в ТГ — тогда с `--send`)
- «проверь пульс» → `python3 report.py pulse` (аналогично)
- «добавь @X в мониторинг» → дописать в `config.json` → `python3 fetch.py --limit 30`
  (холодный старт для нового аккаунта)
- «убери @X» → удалить из `config.json`
- «выключи/включи автоматику» → `python3 schedule.py remove` / `install`
- «как там мониторинг» → `python3 schedule.py status` + хвосты `data/*.log`

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
