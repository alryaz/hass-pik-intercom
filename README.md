<img src="https://raw.githubusercontent.com/alryaz/hass-pik-intercom/master/images/header.png" height="100" alt="Home Assistant + ПИК Домофон">

_&#xab;ПИК Домофон&#xbb;_ для _Home Assistant_
==================================================

> Управление домофонами в экосистеме группы ПИК. Поддержка просмотра видеопотока и открытия дверей.
>
> Intercom management within PIK Group ecosystem. Video feed and door unlocking supported.
> 
> [![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
> [![Лицензия](https://img.shields.io/badge/%D0%9B%D0%B8%D1%86%D0%B5%D0%BD%D0%B7%D0%B8%D1%8F-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
> [![Поддержка](https://img.shields.io/badge/%D0%9F%D0%BE%D0%B4%D0%B4%D0%B5%D1%80%D0%B6%D0%B8%D0%B2%D0%B0%D0%B5%D1%82%D1%81%D1%8F%3F-%D0%B4%D0%B0-green.svg?style=for-the-badge)](https://github.com/alryaz/hass-pandora-cas/graphs/commit-activity)

> 💵 **Пожертвование на развитие проекта**  
> [![Пожертвование YooMoney](https://img.shields.io/badge/YooMoney-8B3FFD.svg?style=for-the-badge)](https://yoomoney.ru/to/410012369233217)
> [![Пожертвование Тинькофф](https://img.shields.io/badge/Tinkoff-F8D81C.svg?style=for-the-badge)](https://www.tinkoff.ru/cf/3g8f1RTkf5G)
> [![Пожертвование Cбербанк](https://img.shields.io/badge/Сбербанк-green.svg?style=for-the-badge)](https://www.sberbank.com/ru/person/dl/jc?linkname=3pDgknI7FY3z7tJnN)
> [![Пожертвование DonationAlerts](https://img.shields.io/badge/DonationAlerts-fbaf2b.svg?style=for-the-badge)](https://www.donationalerts.com/r/alryaz)
>
> 💬 **Техническая поддержка**  
> [![Группа в Telegram](https://img.shields.io/endpoint?url=https%3A%2F%2Ftg.sumanjay.workers.dev%2Falryaz_ha_addons&style=for-the-badge)](https://telegram.dog/alryaz_ha_addons)

> **Библиотека API «ПИК Домофон»: [alryaz/pik-intercom-python](https://github.com/alryaz/pik-intercom-python)**

> **Интеграция для личного кабинета ЖКХ «ПИК Комфорт»: [alryaz/hass-pik-comfort](https://github.com/alryaz/hass-pik-comfort)**

## Скриншоты

<details>
  <summary>Просмотр видеопотока домофона</summary> 
  <img src="https://raw.githubusercontent.com/alryaz/hass-pik-intercom/main/images/camera.png" alt="Скриншот: Просмотр видеопотока домофона">
</details>
<details>
  <summary>Открытие двери у домофона</summary> 
  <img src="https://raw.githubusercontent.com/alryaz/hass-pik-intercom/main/images/unlockers.png" alt="Скриншот: Открытие двери у домофона">
</details>

## Установка

> Также рекомендуется установить компонент [AlexxIT/WebRTC](https://github.com/AlexxIT/WebRTC).
> Он позволяет просматривать видеопотоки в реальном времени через окна браузера.

### Home Assistant Community Store

> 🎉  **Рекомендованный метод установки.**

1. Установите
   HACS ([инструкция по установке на оф. сайте](https://hacs.xyz/docs/installation/installation/)).
2. Добавьте репозиторий в список дополнительных:
    1. Откройте главную страницу _HACS_.
    2. Откройте раздел _Интеграции (Integrations)_.
    3. Нажмите три точки сверху справа (допонительное меню).
    4. Выберите _Пользовательские репозитории_.
    5. Скопируйте `https://github.com/alryaz/hass-pik-intercom` в поле вводавыберите _Интеграция (Integration)_ в выпадающем списке -> Нажмите _Добавить (Add)_.
    6. Выберите _Интеграция (Integration)_ в выпадающем списке.
    7. Нажмите _Добавить (Add)_.
3. Найдите `PIK Intercom` (`ПИК Домофон`) в поиске по интеграциям.
4. Установите последнюю версию компонента, нажав на кнопку `Установить` (`Install`).
5. Перезапустите сервер _Home Assistant_.

### Вручную

> ⚠️ **Внимание!** Данный вариант **<ins>не рекомендуется</ins>** в силу сложности поддержки установленной интеграции в актуальном
> состоянии.

0. _(предварительно)_ Создайте (если отсутствует) папку `custom_components` внутри папки с конфигурацией Вашего _Home Assistant_.
1. Скачайте архив с интеграцией:
   1. Для загрузки последней стабильной версии:
      1. Перейдите на [страницу последнего релиза](https://github.com/alryaz/hass-pik-intercom/releases/latest)
      2. Нажмите на кнопку скачивания исходного кода (текст: _Source code (zip)_)
   2. Для загрузки последней "превью"-версии (не стабильно, может не работать вовсе):
      1. Перейдите по [ссылке скачивания исходного кода](https://github.com/alryaz/hass-pik-intercom/archive/refs/heads/main.zip)
2. Откройте папку `hass-pik-intercom-####` внутри загруженного архива (`####` - индекс версии интеграции).
3. Извлеките содержимое папки `custom_components` внутри архива в Вашу папку `custom_components` (из шага №0).
4. Перезапустите сервер _Home Assistant_.

## Настройка

[![Открыть Ваш Home Assistant и начать настройку интеграции.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=pik_intercom)

Нажмите на кнопку выше, или следуйте следующим инструкциям:
1. Откройте `Настройки` -> `Интеграции`
2. Нажмите внизу справа страницы кнопку с плюсом
3. Введите в поле поиска `PIK`  
   - Если интеграция не была найдена на данном этапе, перезапустите Home Assistant и очистите кеш браузера.
4. Выберите первый результат из списка
5. Следуйте инструкциям, описываемым на экране.
6. После завершения настройки начнётся обновление состояний объектов.

- **Вариант А:** Через _Интеграции_: [![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=pik_intercom)
- **Вариант Б:** YAML (см. пример ниже)

### Пример конфигурации YAML
```yaml
pik_intercom:
  # Номер телефона.
  # Поддерживается свободный формат ввода.
  username: 79876543210

  # Пароль для входа
  password: super_password
```

## Использование компонента

> ℹ️ Каждый объект компонента обладает атрибутом `id`, указывающим
> на внутренний идентификатор объекта.
> 
> От данной информации можно отталкиваться в автоматизациях.

### Просмотр видео &mdash; платформа `camera`

На данный момент реализовано потоковое видео и получение снимков (JPEG).

Данная возможность является экспериментальной; при возникновении ошибок,
[создайте issue](https://github.com/alryaz/hass-pik-intercom/issues/new).

### Открытие дверей &mdash; платформа `button`

Компонент открывает доступ к нескольким объектам на платформе `button`, соответствующим
кнопкам открытия дверей, ассоциированных с домофоном.

Одним из объектов является `button.last_call_session_unlocker`. Данный объект
является вспомогательной абстракцией и позволяет выполнить открытие
домофонной двери, с панели которой был выполнен вызов.

Чтобы открыть дверь домофона, достаточно воспользоваться службой `button.press`.
Более подробно почитать про действия объекта типа «кнопка» возможно в
[официальной документации](https://www.home-assistant.io/integrations/button/).

### Время звонка &mdash; платформа `sensor`

Объекты с идентификаторами `sensor.last_call_session_<...>_at` являются
отражением временных меток, заданных последней зарегистрированной сессии звонка:
- `Created At` &mdash; время создания записи о вызове
- `Updated At` &mdash; последние обновление данных о звонке
- `Finished At` &mdash; время завершения вызова (ответом, сбросом, или по времени)

**_N.B._** Существует вероятность перехода объектов в состояние `unavailable` («недоступно»),
если API не выдаст информацию о звонке. Необходимо учитывать это в автоматизациях.

### Статус звонка &mdash; платформа `binary_sensor`

Объект с идентификатором `binary_sensor.last_call_session_active` отражает
текущее состояние звонка в дверь.

Если производится звонок в дверь, объект меняет своё состояние с `off` на `on`.
По завершению звонка объект возвращает своё состояние с `on` на `off`.

**_N.B._** Существует вероятность перехода объект в состояние `unavailable` («недоступно»),
если API не выдаст информацию о звонке. Необходимо учитывать это в автоматизациях.

### Последний звонок в дверь &mdash; платформа `sensor`

Объект обладает ID: `sensor.last_call_session`

Компонент предоставляет информацию о последнем зарегистрированном в системе звонке.

### Счётчики &mdash; платформа `sensor`

Компонент позволяет получить информацию о зарегистрированных счётчиках (пока что
только ГВС/ХВС).

**_N.B._** Если Вы обладаете счётчиками другого типа, [создайте issue](https://github.com/alryaz/hass-pik-intercom/issues/new).
Их загрузка не гарантируется компонентом.

## Отказ от ответственности

Данное программное обеспечение никак не связано и не одобрено ПАО «ПИК СЗ», владельца
торговой марки «ПИК Домофон». Используйте его на свой страх и риск. Автор ни при каких
обстоятельствах не несёт ответственности за порчу или утрату вашего имущества и возможного
вреда в отношении третьих лиц.

Все названия брендов и продуктов принадлежат их законным владельцам.
