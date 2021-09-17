<img src="https://raw.githubusercontent.com/alryaz/hass-pik-intercom/master/images/header.png" height="100" alt="Home Assistant + ПИК Домофон">

_&#xab;ПИК Домофон&#xbb;_ для _Home Assistant_
==================================================

> Управление домофонами в экосистеме группы ПИК. Поддержка просмотра видеопотока и открытия дверей.
>
> Intercom management within PIK Group ecosystem. Video feed and door unlocking supported.
> 
> [![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
> [![Лицензия](https://img.shields.io/badge/%D0%9B%D0%B8%D1%86%D0%B5%D0%BD%D0%B7%D0%B8%D1%8F-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
> [![Поддержка](https://img.shields.io/badge/%D0%9F%D0%BE%D0%B4%D0%B4%D0%B5%D1%80%D0%B6%D0%B8%D0%B2%D0%B0%D0%B5%D1%82%D1%81%D1%8F%3F-%D0%B4%D0%B0-green.svg)](https://github.com/alryaz/hass-pik-intercom/graphs/commit-activity)
>
> [![Пожертвование Yandex](https://img.shields.io/badge/%D0%9F%D0%BE%D0%B6%D0%B5%D1%80%D1%82%D0%B2%D0%BE%D0%B2%D0%B0%D0%BD%D0%B8%D0%B5-Yandex-red.svg)](https://money.yandex.ru/to/410012369233217)
> [![Пожертвование PayPal](https://img.shields.io/badge/%D0%9F%D0%BE%D0%B6%D0%B5%D1%80%D1%82%D0%B2%D0%BE%D0%B2%D0%B0%D0%BD%D0%B8%D0%B5-Paypal-blueviolet.svg)](https://www.paypal.me/alryaz)

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

1. Установите
   HACS ([инструкция по установке на оф. сайте](https://hacs.xyz/docs/installation/installation/))
1. Добавьте репозиторий в список дополнительных:
    1. Откройте главную страницу _HACS_
    1. Откройте раздел _Интеграции (Integrations)_
    1. Нажмите три точки сверху справа (допонительное меню)
    1. Выберите _Пользовательские репозитории_
    1. Скопируйте `https://github.com/alryaz/hass-pik-intercom` в поле вводавыберите _Интеграция (Integration)_ в выпадающем списке -> Нажмите _Добавить (Add)_
    1. Выберите _Интеграция (Integration)_ в выпадающем списке
    1. Нажмите _Добавить (Add)_
1. Найдите `PIK Intercom` (`ПИК Домофон`) в поиске по интеграциям
1. Установите последнюю версию компонента, нажав на кнопку `Установить` (`Install`)
1. Перезапустите Home Assistant

## Конфигурация компонента:
- Вариант А: Через _Интеграции_ (в поиске - _PIK Intercom_ или _ПИК Домофон_)
- Вариант Б: YAML

### Пример конфигурации YAML
```yaml
pik_intercom:
  username: 1234567890
  password: super_password
```

## Использование компонента

> ⚠️ **Внимание!** Данный раздел находится в разработке.

### Просмотр видео &mdash; платформа `camera`

_Объекты обладают форматом ID: `camera.<ID домофона>_camera`_

На данный момент реализовано потоковое видео и получение снимков (JPEG).

Данная возможность является экспериментальной; при возникновении ошибок,
[создайте issue](https://github.com/alryaz/hass-pik-intercom/issues/new).

### Открытие дверей &mdash; платформа `switch`

_Объекты обладают форматом ID: `switch.<ID домофона>_unlocker`_

Компонент открывает доступ к нескольким объектам на платформе `switch`, соответствующим
кнопкам открытия дверей, ассоциированных с домофоном.

Чтобы открыть дверь домофона, достаточно воспользоваться службой `switch.turn_on`.
Более подробно почитать про действия выключатель возможно в
[официальной документации](https://www.home-assistant.io/integrations/switch/).

### Последний звонок в дверь &mdash; платформа `sensor`

_Объекты обладают форматом ID: `sensor.last_call_session`_

Компонент предоставляет информацию о последнем зарегистрированном в системе звонке.

## Отказ от ответственности

Данное программное обеспечение никак не связано и не одобрено ПАО «ПИК СЗ», владельца
торговой марки «ПИК Домофон». Используйте его на свой страх и риск. Автор ни при каких
обстоятельствах не несёт ответственности за порчу или утрату вашего имущества и возможного
вреда в отношении третьих лиц.

Все названия брендов и продуктов принадлежат их законным владельцам.
