# Техническое задание: IR Learning Hub для Home Assistant

## 1. Назначение

**IR Learning Hub** — локальный модуль для Home Assistant, предназначенный для обучения, хранения и отправки инфракрасных команд через Zigbee IR-пульт, подключённый к Home Assistant через **ZHA**.

Цель проекта — дать пользователю простой интерфейс для работы с ИК-устройствами без Developer Tools, ручного копирования IR-кодов и постоянного редактирования YAML.

Целевой UX:

```text
Выбрал устройство → выбрал команду → нажал Learn → направил оригинальный пульт → проверил → сохранил
```

## 2. Принципы реализации

Проект должен использовать только каноничные интерфейсы Home Assistant:

- ZHA как официальный способ взаимодействия с Zigbee-устройством;
- стандартные HA services;
- стандартное хранилище `.storage` для пользовательских данных;
- custom integration API Home Assistant;
- Lovelace/custom card API для пользовательского интерфейса;
- helpers только для UI-состояния, а не для хранения IR-кодов.

Проект не должен:

- патчить ядро Home Assistant;
- изменять внутренние файлы ZHA;
- использовать monkey patching;
- зависеть от неофициальных изменений в HA core;
- хранить IR-коды в `input_text` helpers;
- создавать отдельную entity/helper на каждую IR-команду;
- требовать облако Tuya, Smart Life или Tuya IoT Platform.

## 3. Целевая архитектура

```text
ZHA Tuya IR Remote
        ↓
custom_components/ir_learning_hub/
        ↓
.storage/ir_learning_hub
        ↓
Home Assistant services + entities
        ↓
Lovelace card / automations / Hermes Agent
```

## 4. Поддерживаемые сценарии

### 4.1 Generic IR device

Подходит для:

- усилителей;
- телевизоров;
- CD/DVD/Blu-ray-плееров;
- медиаплееров;
- проекторов;
- ресиверов;
- простых ИК-устройств.

Модель данных:

```text
одно действие = один IR-код
```

Примеры команд:

- `power`;
- `volume_up`;
- `volume_down`;
- `mute`;
- `input_cd`;
- `play`;
- `pause`.

### 4.2 Climate IR device

Подходит для кондиционеров и тепловых насосов.

Модель данных:

```text
одно состояние климатического устройства = один IR-код
```

Причина: большинство кондиционеров не отправляет отдельные команды вида `temp_up` или `mode_cool`. Пульт обычно передаёт полное состояние:

```text
режим + температура + скорость вентилятора + swing + дополнительные флаги
```

Пример ключа команды:

```text
cool_23_auto_swing_off
heat_21_low_swing_on
```

Поддержка `climate_ir` должна идти отдельной фазой после успешной реализации generic-режима.

## 5. Хранение данных

### 5.1 Основное хранилище

IR-коды должны храниться в `.storage` через стандартный механизм Home Assistant `Store`.

Хранилище создаётся через API Home Assistant:

```python
Store(hass, STORAGE_VERSION, "ir_learning_hub")
```

Фактический файл хранения:

```text
.storage/ir_learning_hub
```

Прямое ручное редактирование файла пользователем не является основным сценарием.

### 5.2 Формат данных

Базовая структура:

```json
{
  "version": 1,
  "locations": {
    "cabinet": {
      "name": "Кабинет",
      "devices": {
        "yamaha_amp": {
          "name": "Усилитель Yamaha",
          "type": "generic",
          "commands": {
            "power": {
              "name": "Power",
              "code": "JgBgAAAAAA0ODQ0NDg0NDg0NDRANDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDRANDRINDQ3+...",
              "format": "zosung_string",
              "updated_at": "2026-06-09T16:42:00+00:00",
              "verified": true
            },
            "volume_up": {
              "name": "Vol+",
              "code": "JgBYAAABKZUTEhMSExITEhMSExITEhMSExITEhMSExITEhMSExITEhMSExITEhMS...",
              "format": "zosung_string",
              "updated_at": "2026-06-09T16:45:00+00:00",
              "verified": true
            }
          }
        }
      }
    }
  }
}
```

Для первой подтверждённой реализации с Tuya TS1201 / Zosung IR code хранится как строка, полученная из `last_learned_ir_code`, без дополнительного base64-кодирования. Отправка должна использовать эту же строку как значение `code` для команды отправки.

Поле `format` для первой реализации:

```text
zosung_string
```

Новые форматы допускаются только после отдельной проверки реального устройства и миграции registry.

### 5.3 Требования к хранилищу

Хранилище должно поддерживать:

- добавление устройства;
- переименование устройства;
- удаление устройства;
- добавление команды;
- переименование команды;
- удаление команды;
- сохранение нового IR-кода;
- замену существующего IR-кода;
- отметку `verified` после успешного тестирования;
- экспорт данных;
- импорт данных;
- миграцию формата при изменении версии.

## 6. Интеграция с ZHA

### 6.1 Требования

Интеграция должна работать с IR-пультом, подключённым через ZHA, используя официальные механизмы Home Assistant для вызова ZHA-команд.

На первом этапе необходимо подтвердить, что конкретное устройство поддерживает:

1. включение режима обучения;
2. получение выученного IR-кода;
3. отправку сохранённого IR-кода;
4. стабильное повторение команды после перезапуска Home Assistant.

### 6.2 Ограничение

Проект не должен реализовывать поддержку всех Tuya IR-пультов абстрактно на первой итерации.

Первая цель — поддержать один конкретный подтверждённый пульт и один подтверждённый путь отправки команд через ZHA.

### 6.2.1 Механизм получения выученного IR-кода

Phase 0 подтвердила, что стандартные внешние механизмы Home Assistant не отдают выученный IR-код для проверенного TS1201.

Для Tuya TS1201 / Zosung IR ожидаемая модель такая:

1. интеграция включает режим обучения на ZHA IR-пульте;
2. пульт получает IR-сигнал от оригинального пульта;
3. quirk обновляет атрибут `last_learned_ir_code` (`attribute_id: 0x0000`) в Zosung IR control cluster;
4. custom integration получает строковый код напрямую из zigpy device object и сохраняет его во временное состояние `last_learned_code`.

Основной метод для MVP:

```text
прямой доступ к ZHA device proxy и zigpy device object внутри custom integration
```

Ожидаемый путь реализации:

```python
from homeassistant.components.zha.helpers import async_get_zha_device_proxy

zha_device_proxy = await async_get_zha_device_proxy(hass, ieee)
zigpy_device = zha_device_proxy.device
cluster = zigpy_device.endpoints[1].zosung_ircontrol
attrs, failed = await cluster.read_attributes(["last_learned_ir_code"])
code = attrs.get("last_learned_ir_code")
```

Допустимый дополнительный механизм:

```text
listener/callback на изменение cluster attribute внутри runtime-объекта интеграции
```

Нерабочие для проверенного устройства методы:

- HA event bus: за 60 секунд теста не получено событий от TS1201;
- state changes: entity `switch.kabinet_pult_distantsionnyi_audio` не менялась;
- HA service `zha.read_zigbee_cluster_attributes`: возвращал HTTP 400 Bad Request для вариантов чтения `last_learned_ir_code`.

Следовательно, `learn` в Phase 1 должен быть реализован через прямое взаимодействие с ZHA/zigpy runtime objects, а не только через публичные HA services.

### 6.3 Конфигурация IR-передатчика

Пользователь должен иметь возможность выбрать ZHA-устройство IR-пульта в настройках интеграции.

Минимальные параметры:

- `ieee` устройства;
- `endpoint_id`;
- `cluster_id`;
- формат команды обучения;
- формат команды отправки;
- timeout обучения.

Значения по умолчанию допускаются только после проверки на реальном устройстве.

Интеграция должна использовать config entry, а не обязательную настройку через `configuration.yaml`. Минимальный `config_flow` для MVP должен позволять выбрать один ZHA IR-пульт по IEEE из доступных ZHA-устройств. Если автоматическая фильтрация модели на первом этапе ненадёжна, допустим ручной выбор IEEE из списка с отображением manufacturer/model.

`manifest.json` должен явно объявлять зависимость от ZHA:

```json
{
  "dependencies": ["zha"],
  "config_flow": true
}
```

## 7. Сервисы Home Assistant

Интеграция должна предоставлять стандартные HA services.

### 7.1 `ir_learning_hub.learn`

Запускает режим обучения для выбранной команды.

Пример данных:

```yaml
location_id: cabinet
device_id: yamaha_amp
command_id: power
timeout: 30
```

Поведение:

1. включает режим обучения на IR-пульте;
2. ожидает получения IR-кода;
3. сохраняет код во временное состояние `last_learned_code`;
4. не перезаписывает существующую команду без явного подтверждения;
5. возвращает ошибку при timeout.

### 7.2 `ir_learning_hub.save_last_learned`

Сохраняет последний полученный код в выбранную команду.

Пример данных:

```yaml
location_id: cabinet
device_id: yamaha_amp
command_id: power
verified: false
```

`save_last_learned` не должен автоматически устанавливать `verified: true`. Значение `verified: true` допустимо только после успешного `test_last_learned` или явного подтверждения пользователя в UI. Если пользователь выполняет `learn → save` без теста, команда сохраняется с `verified: false`, а UI должен показывать предупреждение.

### 7.3 `ir_learning_hub.test_last_learned`

Отправляет последний выученный код без сохранения.

Назначение: проверить, что был выучен правильный сигнал.

После успешного теста временное состояние последнего кода может быть помечено как проверенное, чтобы последующий `save_last_learned` сохранил команду с `verified: true`.

### 7.4 `ir_learning_hub.send`

Отправляет сохранённую команду.

Пример данных:

```yaml
location_id: cabinet
device_id: yamaha_amp
command_id: volume_up
```

### 7.5 `ir_learning_hub.add_device`

Добавляет новое IR-устройство.

Пример данных:

```yaml
location_id: cabinet
device_id: yamaha_amp
name: Усилитель Yamaha
type: generic
```

### 7.6 `ir_learning_hub.add_command`

Добавляет новую команду к устройству.

Пример данных:

```yaml
location_id: cabinet
device_id: yamaha_amp
command_id: power
name: Power
```

### 7.7 `ir_learning_hub.delete_command`

Удаляет команду.

### 7.8 `ir_learning_hub.rename_device`

Переименовывает устройство без изменения его внутреннего ID.

### 7.9 `ir_learning_hub.rename_command`

Переименовывает команду без изменения её внутреннего ID.

### 7.10 `ir_learning_hub.export_registry`

Экспортирует текущую базу IR-кодов.

### 7.11 `ir_learning_hub.import_registry`

Импортирует базу IR-кодов с проверкой версии и структуры.

## 8. Entities

Интеграция должна создавать минимум одну диагностическую entity.

### 8.1 Sensor: `sensor.ir_learning_hub_status`

Показывает текущее состояние:

- `idle`;
- `learning`;
- `code_received`;
- `sending`;
- `error`.

Attributes:

```yaml
last_action: learn
last_location_id: cabinet
last_device_id: yamaha_amp
last_command_id: power
last_error: null
last_error_message: null
last_updated: "2026-06-09T16:42:00+00:00"
```

### 8.2 Optional entities

Дополнительно, но не обязательно для MVP:

- `button.ir_learning_hub_learn`;
- `button.ir_learning_hub_send`;
- `select.ir_learning_hub_device`;
- `select.ir_learning_hub_command`.

Для MVP допустимо управлять через services и Lovelace card без создания большого количества entities. Если карточке нужны динамические списки, предпочтительнее собственные `select` entities интеграции, автоматически заполненные из registry, а не ручные helpers.

## 9. Lovelace UI

Технология реализации MVP должна оставаться простой и локальной:

- предпочтительно собственная custom card интеграции, если требуется полноценный управляемый UI;
- допустима временная YAML/Lovelace-конфигурация для ручной проверки backend;
- внешние HACS-карточки допустимы только как опциональный ускоритель разработки, но не должны быть обязательной зависимостью MVP.

### 9.1 Базовая карточка

Карточка должна предоставлять:

- выбор локации;
- выбор устройства;
- выбор команды;
- кнопку `Learn`;
- кнопку `Test`;
- кнопку `Save`;
- кнопку `Send`;
- отображение текущего статуса;
- отображение последнего действия;
- отображение ошибки, если она есть.

Базовый UX:

```text
IR Пульт

Локация:    [Кабинет ▼]
Устройство: [Усилитель Yamaha ▼]
Команда:    [Power ▼]

[Learn] [Test] [Save] [Send]

Статус: Код получен, ожидает проверки
Последнее: 16:42 — Усилитель Yamaha / Power
```

### 9.2 Обязательный сценарий обучения

Карточка должна реализовывать безопасный сценарий:

```text
Learn → код получен → Test → Save
```

Не допускается автоматическое перезаписывание существующей команды сразу после обучения без явного подтверждения пользователя.

### 9.3 Управление устройствами и командами

Карточка должна позволять:

- добавить устройство;
- добавить команду;
- переименовать устройство;
- переименовать команду;
- удалить команду;
- переобучить команду.

Для MVP допускается выполнять эти операции через стандартную панель Services / Developer Tools. Но целевая версия должна поддерживать это из UI.

### 9.4 Button Grid

После реализации базовой карточки должна быть добавлена сетка команд выбранного устройства.

Пример:

```text
[Power] [Vol+] [Vol-] [Mute]
[Input CD] [Input AUX] [Input TV]
[Play] [Pause] [Stop] [Next]
```

Каждая кнопка вызывает:

```yaml
service: ir_learning_hub.send
```

с соответствующими `location_id`, `device_id`, `command_id`.

## 10. Helpers и UI-состояние

Helpers допускаются только как временное UI-состояние для Lovelace при ручной проверке backend, если custom card или собственные select entities ещё не готовы.

Предпочтительный путь для целевой версии:

```text
sensor.ir_learning_hub_status
select.ir_learning_hub_device
select.ir_learning_hub_command
```

Разрешённые helpers для промежуточной реализации:

```text
input_select.ir_location
input_select.ir_device
input_select.ir_command
input_text.ir_status
input_boolean.ir_learning_mode
```

Запрещённый подход:

```text
input_text.ir_{device}_{command}
```

Причины запрета:

- лимит длины значения;
- сложные переименования;
- загрязнение entity registry;
- сложная динамическая генерация UI;
- плохая масштабируемость;
- отсутствие нормальной миграции данных.

## 11. Agent / Hermes compatibility

Интеграция должна быть пригодна для вызова голосовым или текстовым агентом.

Минимально необходимые сервисы:

```yaml
ir_learning_hub.send
ir_learning_hub.learn
```

Примеры intent-уровня:

```text
включи усилитель
сделай громче усилитель
выключи телевизор
обучи кнопку Power для усилителя
```

На уровне интеграции не требуется реализовывать NLP. Достаточно иметь стабильные services с понятными параметрами.

Связь фраз с командами может быть реализована отдельно в Hermes Agent.

## 12. Ошибки и валидация

Интеграция должна обрабатывать следующие ситуации:

- IR-пульт недоступен;
- ZHA-команда завершилась ошибкой;
- timeout при обучении;
- код не получен;
- код получен, но пустой или некорректный;
- команда уже существует;
- устройство не существует;
- команда не существует;
- физический IR-передатчик не выбран при наличии нескольких transmitters;
- физический IR-передатчик недоступен или не найден в ZHA;
- ZHA integration недоступна;
- попытка отправить пустую команду;
- ошибка чтения/записи storage;
- несовместимая версия registry.

Ошибки должны быть доступны:

- в UI карточки;
- в логах Home Assistant;
- через status sensor attributes.

Коды ошибок должны быть стабильными строками, пригодными для UI и агентских сценариев:

```text
device_offline
zha_command_failed
learn_timeout
code_not_received
code_empty
device_not_found
command_not_found
command_already_exists
transmitter_required
transmitter_unavailable
zha_unavailable
storage_read_failed
storage_write_failed
incompatible_version
```

`last_error` в status sensor содержит один из этих кодов или `null`. Человекочитаемый текст ошибки хранится отдельно в `last_error_message`.

## 13. Нефункциональные требования

- Работа полностью локально.
- Отсутствие зависимости от Tuya Cloud.
- Отсутствие зависимости от Smart Life.
- Отсутствие ручного редактирования YAML после первичной установки.
- Совместимость с перезапуском Home Assistant.
- Возможность резервного копирования базы кодов.
- Читаемая структура данных.
- Возможность миграции данных при обновлениях.
- Минимальное количество создаваемых entities.
- Отсутствие хака ядра Home Assistant.

## 14. Фазы реализации

## Фаза 0. Проверка ZHA IR-пульта

### Цель

Подтвердить, что выбранный ZHA IR-пульт реально пригоден для проекта.

### Объём

Проверить вручную через стандартные инструменты Home Assistant:

1. включение режима обучения;
2. получение IR-кода;
3. отправку полученного IR-кода;
4. реакцию реального устройства;
5. повторную отправку после перезапуска HA.

### Критерии готовности

Изначальный полный критерий:

```text
Learn → получить код → Send → устройство реагирует → перезапуск HA → Send → устройство снова реагирует
```

Для проверенного TS1201 этот критерий не выполнен через стандартные HA API, потому что код не попадает в event bus и не читается через `zha.read_zigbee_cluster_attributes`.

Phase 0 считается завершённой как исследовательская фаза, потому что:

- `IRLearn` запускается через HA service;
- устройство физически принимает IR-сигнал;
- quirk содержит `last_learned_ir_code`;
- `IRSend` вызывается через HA service;
- точка разрыва локализована: выученный код недоступен через внешние HA API;
- для Phase 1 определён обязательный путь: прямой доступ к zigpy device object внутри custom integration.

### Тесты

- Обучение кнопки `Power` от реального пульта.
- Отправка выученного кода.
- Проверка реакции устройства.
- Проверка timeout при отсутствии ИК-сигнала.
- Проверка поведения при недоступном IR-пульте.

### Результат

Документированы:

- модель IR-пульта;
- IEEE адрес;
- endpoint;
- cluster;
- рабочая команда обучения;
- рабочая команда отправки;
- формат полученного кода.

Результаты проверки конкретного устройства зафиксированы в разделе 19.

## Фаза 1. Minimal custom integration backend

### Цель

Создать минимальную custom integration без UI-карточки, которая предоставляет services и хранит registry в `.storage`.

### Объём

Структура:

```text
custom_components/ir_learning_hub/
  manifest.json
  __init__.py
  config_flow.py
  const.py
  device_profiles.py
  services.yaml
  storage.py
  zha_adapter.py
```

Требования к backend-инициализации:

- services регистрируются глобально один раз на integration domain в `async_setup`, а не отдельно для каждого config entry;
- config entry создаёт одну инсталляцию integration domain; mutable список IR-передатчиков хранится в registry/storage, а не как основной источник истины в config entry options;
- `async_setup_entry` поднимает runtime-объекты конкретной настройки и status entity;
- `manifest.json` содержит `dependencies: ["zha"]` и `config_flow: true`;
- storage создаётся через `Store(hass, STORAGE_VERSION, "ir_learning_hub")`.

Для MVP допустим один активный IR-передатчик, но naming и storage-модель должны сразу различать:

- `transmitter_id` — физический IR-передатчик, обычно нормализованный IEEE без двоеточий;
- `device_id` — управляемое IR-устройство из registry, например `yamaha_amp`.

Это нужно, чтобы multi-transmitter поддержка не конфликтовала с существующими services `location_id/device_id/command_id`.

Требования к `zha_adapter.py` для проверенного TS1201:

- получить ZHA device proxy через `async_get_zha_device_proxy(hass, ieee)`;
- получить `zigpy_device` из proxy;
- работать с endpoint `1` и cluster `zosung_ircontrol` / `0xE004`;
- запускать `IRLearn` командой `1` с `on_off: true`;
- отправлять `IRSend` командой `2` с параметром `code`;
- читать `last_learned_ir_code` напрямую из zigpy cluster;
- держать learning window открытым повторным запуском `IRLearn` примерно каждые 8 секунд до `learning_timeout`;
- корректно обрабатывать battery EndDevice: перед обучением пробуждать устройство через identify button или эквивалентный wake-up сценарий.

Реализовать services:

- `ir_learning_hub.learn`;
- `ir_learning_hub.test_last_learned`;
- `ir_learning_hub.save_last_learned`;
- `ir_learning_hub.send`;
- `ir_learning_hub.add_device`;
- `ir_learning_hub.add_command`.

### Критерии готовности

- Интеграция загружается без ошибок.
- Services появляются в Home Assistant.
- Registry создаётся в `.storage`.
- Можно добавить устройство.
- Можно добавить команду.
- Можно выучить код.
- Можно протестировать код до сохранения.
- Можно сохранить код.
- Можно отправить сохранённую команду.

### Тесты

- Unit-тесты storage-слоя.
- Проверка создания пустого registry.
- Проверка добавления устройства.
- Проверка добавления команды.
- Проверка запрета дубликатов.
- Проверка сохранения и чтения IR-кода.
- Ручной end-to-end тест с реальным IR-устройством.

## Фаза 2. Status entity и базовая диагностика

### Цель

Добавить прозрачную диагностику состояния интеграции.

### Объём

Реализовать:

- `sensor.ir_learning_hub_status`;
- attributes последнего действия;
- логирование ошибок;
- понятные сообщения для UI.

### Критерии готовности

- Пользователь видит текущее состояние интеграции.
- Ошибки обучения и отправки видны без просмотра raw logs.
- Последнее действие отображается в attributes.

### Тесты

- Статус меняется на `learning` при обучении.
- Статус меняется на `code_received` после получения кода.
- Статус меняется на `sending` при отправке.
- Статус меняется на `error` при ошибке.
- Attributes содержат последнее устройство и команду.

## Фаза 3. Базовая Lovelace-карточка

### Цель

Дать пользователю простой UI для обучения и отправки команд.

### Объём

Карточка должна поддерживать:

- выбор location;
- выбор device;
- выбор command;
- кнопки `Learn`, `Test`, `Save`, `Send`;
- отображение статуса;
- отображение ошибок.

### Критерии готовности

Пользователь может без Developer Tools выполнить сценарий:

```text
выбрать устройство → выбрать команду → Learn → Test → Save → Send
```

### Тесты

- Карточка загружается на dashboard.
- Список устройств читается из registry.
- Список команд обновляется при смене устройства.
- `Learn` вызывает правильный service.
- `Test` отправляет последний код без сохранения.
- `Save` сохраняет последний код.
- `Send` отправляет сохранённую команду.
- Ошибка отображается в карточке.

## Фаза 4. Управление устройствами и командами из UI

### Цель

Убрать необходимость использовать Developer Tools для добавления и редактирования устройств.

### Объём

В карточке или отдельной панели реализовать:

- добавление устройства;
- добавление команды;
- переименование устройства;
- переименование команды;
- удаление команды;
- переобучение команды.

### Критерии готовности

Пользователь может полностью настроить generic IR-устройство из UI.

### Тесты

- Добавление нового устройства.
- Добавление новой команды.
- Запрет некорректного ID.
- Переименование сохраняет внутренний ID.
- Удаление требует подтверждения.
- После изменений списки в карточке обновляются.

## Фаза 5. Button Grid

### Цель

Сделать удобный пульт для повседневного управления.

### Объём

Для выбранного устройства карточка отображает сетку всех сохранённых команд.

Каждая кнопка вызывает `ir_learning_hub.send`.

### Критерии готовности

Пользователь может управлять устройством одним нажатием без выбора команды из списка.

### Тесты

- Grid строится из registry.
- Кнопки отправляют правильные команды.
- Команды без кода отображаются как disabled.
- После добавления новой команды grid обновляется.

## Фаза 6. Export / Import / Backup

### Цель

Обеспечить переносимость и восстановление базы IR-кодов.

### Объём

Реализовать:

- export registry;
- import registry;
- проверку версии;
- проверку структуры;
- защиту от перезаписи без подтверждения.

### Критерии готовности

Пользователь может сохранить и восстановить базу IR-кодов.

### Тесты

- Export создаёт валидный JSON.
- Import валидного JSON восстанавливает устройства и команды.
- Import несовместимой версии завершается ошибкой.
- Import повреждённого JSON не ломает текущий registry.

## Фаза 7. Hermes Agent compatibility

### Цель

Подготовить интеграцию к управлению через агента.

### Объём

Гарантировать стабильные service-интерфейсы:

```yaml
ir_learning_hub.send
ir_learning_hub.learn
```

Добавить alias-поля для команд:

```json
"aliases": ["включи усилитель", "power amp", "усилитель питание"]
```

### Критерии готовности

Hermes Agent может вызвать команду по device/command ID или по alias.

### Тесты

- Вызов команды по `device_id` и `command_id`.
- Вызов команды по alias.
- Ошибка при неоднозначном alias.
- Ошибка при неизвестной команде.

## Фаза 8. Climate IR

### Цель

Добавить поддержку кондиционеров без нарушения generic-модели.

### Объём

Реализовать тип устройства:

```text
climate_ir
```

Поддержать матрицу кодов по состояниям:

- режим;
- температура;
- скорость вентилятора;
- swing;
- дополнительные флаги.

Пример state key:

```text
cool_23_auto_swing_off
```

### Критерии готовности

Пользователь может обучить и отправить не отдельную кнопку, а состояние кондиционера.

### Тесты

- Сохранение состояния `cool_23_auto_swing_off`.
- Отправка состояния.
- Ошибка при неизвестной комбинации.
- UI не показывает climate-матрицу для generic-устройств.

## 15. Отложенные возможности

Следующие функции не входят в MVP:

- автоматическое распознавание моделей ИК-устройств;
- база готовых IR-кодов;
- интеграция с Tuya Cloud;
- поддержка Zigbee2MQTT;
- поддержка нескольких IR-передатчиков одновременно;
- полноценная climate entity;
- генерация IR-кодов для кондиционеров;
- мобильное onboarding-приложение;
- публикация в HACS.

Эти функции могут быть добавлены позже, если базовая модель подтвердит стабильность.

## 16. MVP scope

Минимальная полезная версия включает только:

1. один ZHA IR-передатчик;
2. generic IR devices;
3. хранение в `.storage`;
4. services для learn/test/save/send;
5. status sensor;
6. простую Lovelace-карточку;
7. ручное добавление устройств и команд через UI или services.

MVP не включает:

- climate IR;
- Hermes Agent;
- HACS-публикацию;
- поддержку нескольких пультов;
- автоматическую базу кодов.

## 17. Основные риски

### 17.1 Неполная поддержка IR-пульта в ZHA

Если устройство не отдаёт выученный код или не принимает код на отправку, проект невозможен без поддержки на уровне ZHA/quirk.

Статус после Phase 0: риск подтверждён частично. IRLearn и IRSend работают через HA services, но выученный код не доступен через стандартные HA API/event bus. Митигируется в Phase 1 прямым доступом custom integration к ZHA/zigpy runtime objects.

### 17.2 Нестабильный формат Tuya-команд

Tuya IR-пульты могут использовать нестандартные manufacturer-specific команды.

Митигируется ограничением первой версии на одну проверенную модель.

### 17.3 Слишком сложный UI

Попытка сразу реализовать универсальный пульт, climate, aliases и agent-интеграцию может привести к overengineering.

Митигируется фазовым подходом.

### 17.4 Ошибочное обучение команд

Пользователь может случайно выучить не ту кнопку.

Митигируется обязательным сценарием:

```text
Learn → Test → Save
```

## 18. Критерий успеха проекта

Проект считается успешным на уровне MVP, если пользователь может:

1. добавить IR-устройство;
2. добавить команду;
3. обучить команду с физического пульта;
4. проверить её до сохранения;
5. сохранить команду;
6. отправить команду из UI;
7. отправить команду через Home Assistant service;
8. перезапустить Home Assistant и не потерять базу кодов.

## 19. Phase 0 Device Notes

### 19.1 Подтверждённые данные об устройстве

| Параметр | Значение |
|---|---|
| Модель | TS1201 (MOES UFO-R11) |
| Manufacturer | `_TZ3290_ot6ewjvmejq5ekhl` |
| IEEE | `b0:e8:e8:ff:fe:16:ef:35` |
| Endpoint | 1 |
| Device type | EndDevice, battery-powered |
| Quirk applied | `zhaquirks.tuya.ts1201.ZosungIRBlaster` |
| IR Control cluster (in) | `0xE004` / 57348 (`ZosungIRControl`) |
| IR Transmit cluster (in) | `0xED00` / 60672 (`ZosungIRTransmit`) |
| Switch entity | `switch.kabinet_pult_distantsionnyi_audio` |
| Identify button | `button.kabinet_pult_distantsionnyi_audio_identifikatsiia` |

### 19.2 Рабочие команды через HA services

IRLearn:

```yaml
service: zha.issue_zigbee_cluster_command
data:
  ieee: "b0:e8:e8:ff:fe:16:ef:35"
  endpoint_id: 1
  cluster_id: 57348
  cluster_type: "in"
  command: 1
  command_type: "server"
  params:
    on_off: true
```

Для проверенного quirk `on_off: true` соответствует активному режиму обучения в Tuya/Zosung протоколе.

IRSend:

```yaml
service: zha.issue_zigbee_cluster_command
data:
  ieee: "b0:e8:e8:ff:fe:16:ef:35"
  endpoint_id: 1
  cluster_id: 57348
  cluster_type: "in"
  command: 2
  command_type: "server"
  params:
    code: "BASE64_OR_PLAIN_IR_CODE"
```

Команда отправки возвращает HTTP 200 при вызове с синтаксически корректным payload. Полная e2e-проверка реакции устройства требует сначала получить реальный код через custom integration.

### 19.3 Неработающие операции

- Чтение атрибута `last_learned_ir_code` через `zha.read_zigbee_cluster_attributes` возвращает HTTP 400 Bad Request для проверенных вариантов payload.
- Подписка на `zha_event` не получает событий от TS1201 при обучении.
- Подписка на event bus без фильтра за 60 секунд не показывает событий от TS1201.
- State entity `switch.kabinet_pult_distantsionnyi_audio` не меняется при физическом обучении.
- Quirk сохраняет код во внутреннем zigpy device object, но не публикует его наружу через стандартный HA event bus.

### 19.4 Механизм получения кода для Phase 1

Единственный подтверждённый путь для custom integration — прямой доступ к zigpy device object через ZHA helper:

```python
from homeassistant.components.zha.helpers import async_get_zha_device_proxy

zha_device_proxy = await async_get_zha_device_proxy(hass, ieee)
zigpy_device = zha_device_proxy.device

cluster = zigpy_device.endpoints[1].zosung_ircontrol
attrs, failed = await cluster.read_attributes(["last_learned_ir_code"])
code = attrs.get("last_learned_ir_code")
```

Дополнительно можно проверить listener на изменение cluster attribute внутри runtime-объекта интеграции, но он не должен быть единственным механизмом до подтверждения стабильности после перезапуска Home Assistant.

### 19.5 EndDevice требования

TS1201 является battery-powered EndDevice и может спать вне активного окна. Для успешного обучения в MVP требуется:

1. пробудить устройство через `button.press` для `button.kabinet_pult_distantsionnyi_audio_identifikatsiia` или эквивалентное действие;
2. сразу запустить `IRLearn`;
3. удерживать learning window открытым циклическим `IRLearn` примерно каждые 8 секунд;
4. использовать `learning_timeout` по умолчанию 60 секунд;
5. завершать цикл обучения при получении непустого `last_learned_ir_code` или timeout.

### 19.6 Формат IR-кода

Ожидается `CharacterString`, передаваемый в `IRSend` как строка без дополнительного преобразования интеграцией.

Предполагаемый формат содержимого строки — base64-encoded IR timing data, например:

```text
JgBgAAABK5ESNhI2EjYRNhE2EwANBQ==
```

Точный формат должен быть подтверждён после первого успешного чтения `last_learned_ir_code` через custom integration.

### 19.7 Вердикт Phase 0

Риск 17.1 подтверждён:

- устройство физически работает: LED горит, IRLearn активируется, IR-сигнал принимается;
- стандартные HA API не дают доступа к выученному коду;
- event bus не публикует IR-события TS1201;
- backend custom integration возможен, но должен обращаться к ZHA/zigpy runtime objects;
- scripts/helpers без custom integration не подходят для сценария обучения.

Phase 0 завершена. Phase 1 может начинаться с пониманием, что IRLearn/IRSend через ZHA services работают, а получение кода требует прямого доступа к zigpy device object.

### 19.8 Открытые проверки для начала Phase 1

Перед полноценной реализацией services нужно сделать минимальный probe внутри custom integration:

1. подтвердить, что `async_get_zha_device_proxy(hass, ieee)` доступен в целевой версии Home Assistant;
2. подтвердить фактический путь к cluster: `zigpy_device.endpoints[1].zosung_ircontrol` или альтернативное имя/ID;
3. прочитать `last_learned_ir_code` после физического обучения и зафиксировать реальный тип/формат значения;
4. проверить, очищается ли `last_learned_ir_code` между попытками обучения или нужно хранить previous value и ждать изменения;
5. проверить, работает ли cluster attribute listener после reload integration и restart Home Assistant;
6. отправить прочитанный код через `IRSend` и подтвердить реакцию реального CD-плеера;
7. повторить отправку после перезапуска Home Assistant, чтобы подтвердить пригодность сохранённого registry-кода.

До выполнения этих проверок storage и service contracts можно реализовывать, но `learn` должен считаться experimental.

## 20. Multi-transmitter и portability

### 20.1 Термины

В рамках проекта нужно строго различать два типа устройств:

- `transmitter` — физический Zigbee IR-передатчик, подключённый к ZHA, например TS1201;
- `device` — управляемое IR-устройство пользователя, например усилитель, CD-плеер или телевизор.

В service API `device_id` остаётся ID управляемого IR-устройства. Для выбора физического пульта используется отдельное поле `transmitter_id`. Если в registry есть только один transmitter, services могут использовать его по умолчанию.

### 20.2 Автоматическое обнаружение transmitters

При первой установке `config_flow` должен попытаться найти совместимые ZHA IR-передатчики.

Алгоритм обнаружения:

1. получить список ZHA device proxies доступным helper API текущей версии Home Assistant;
2. для каждого устройства определить manufacturer, model и quirk class;
3. сопоставить устройство с известным profile из `device_profiles.py`;
4. предложить пользователю найденные transmitters для добавления;
5. если ничего не найдено, показать понятное сообщение и действие повторного сканирования.

Сопоставление по quirk class не должно сравнивать объект класса с plain string напрямую. Реализация должна нормализовать значение до стабильной строки вида:

```text
module.ClassName
```

или использовать другой подтверждённый в Phase 1 способ идентификации quirk.

Начальный поддерживаемый profile:

```text
ts1201_zosung
```

для `zhaquirks.tuya.ts1201.ZosungIRBlaster` / TS1201 / MOES UFO-R11.

### 20.3 Storage-модель transmitters

Registry должен быть готов к нескольким физическим IR-передатчикам, даже если MVP использует один.

Пример верхнего уровня:

```json
{
  "version": 1,
  "transmitters": {
    "b0e8e8fffe16ef35": {
      "ieee": "b0:e8:e8:ff:fe:16:ef:35",
      "name": "Кабинет IR",
      "area_name": "Кабинет",
      "manufacturer": "_TZ3290_ot6ewjvmejq5ekhl",
      "model": "TS1201",
      "quirk_class": "zhaquirks.tuya.ts1201.ZosungIRBlaster",
      "profile": "ts1201_zosung",
      "config": {
        "endpoint_id": 1,
        "ir_control_cluster": 57348,
        "ir_transmit_cluster": 60672,
        "learn_timeout": 60,
        "learn_reassert_interval": 8
      },
      "enabled": true,
      "needs_confirmation": false
    }
  },
  "locations": {}
}
```

Ключ transmitter — нормализованный IEEE без двоеточий. IEEE уникален для физического Zigbee-устройства, но не переносим на новый физический пульт, поэтому он не должен быть единственным portability-механизмом.

Mutable список transmitters хранится в `.storage/ir_learning_hub`. Config entry используется для жизненного цикла integration domain и запуска flow/options flow, а не как основной registry для часто меняемого списка transmitters.

### 20.4 Device profiles

Все параметры конкретной модели IR-передатчика должны быть вынесены в `device_profiles.py`:

- `endpoint_id`;
- `ir_control_cluster`;
- `ir_transmit_cluster`;
- формат команды обучения;
- формат команды отправки;
- атрибут с последним выученным кодом;
- необходимость cyclic learn;
- дефолтные `learning_timeout` и `learn_reassert_interval`.

Начальный profile:

```python
PROFILES = {
    "ts1201_zosung": {
        "description": "Tuya TS1201 / MOES UFO-R11 with ZosungIRBlaster quirk",
        "endpoint_id": 1,
        "ir_control_cluster": 0xE004,
        "ir_transmit_cluster": 0xED00,
        "learn_command": {
            "command": 1,
            "params_true": {"on_off": True},
            "params_false": {"on_off": False}
        },
        "send_command": {
            "command": 2,
            "params_template": {"code": "{ir_code}"}
        },
        "last_learned_attribute": "last_learned_ir_code",
        "last_learned_attribute_id": 0x0000,
        "learn_reassert_interval": 8,
        "learning_timeout": 60
    }
}
```

Profiles для не-ZHA устройств, например Broadlink, не должны добавляться в `zha_adapter.py`. Для них потребуется отдельный adapter interface и отдельная фаза, потому что текущий MVP завязан на ZHA/zigpy.

### 20.5 Multi-transmitter service routing

Services должны принимать optional `transmitter_id`:

```yaml
location_id: cabinet
device_id: yamaha_amp
command_id: power
transmitter_id: b0e8e8fffe16ef35
```

Правила выбора transmitter:

1. если `transmitter_id` передан, использовать его;
2. если не передан и в registry один enabled transmitter, использовать его;
3. если не передан и enabled transmitters несколько, вернуть ошибку `transmitter_required`;
4. если transmitter отключён или не найден в ZHA, вернуть `transmitter_unavailable`.

Для MVP UI может скрывать выбор transmitter, если активный transmitter только один.

### 20.6 Добавление transmitters после установки

Добавление нового физического пульта после первой установки должно идти через стандартный HA config/options flow или repair flow.

Lovelace-card не должна напрямую мутировать config entry. Допустимые варианты:

- показать действие, которое открывает стандартный HA flow добавления/настройки integration;
- вызвать service интеграции `ir_learning_hub.scan_transmitters`, если такой service будет добавлен позднее;
- показать инструкцию перейти в настройки интеграции.

Flow должен показывать только ZHA IR transmitters, которые ещё не добавлены в registry, и определять profile по подтверждённому profile matcher.

### 20.7 Portability между HA инсталляциями

Стандартный HA backup/restore переносит `.storage/ir_learning_hub` и все сохранённые IR-коды. Не переносятся автоматически:

- IEEE нового физического transmitter;
- `area_id`, потому что он локален для конкретной HA-инсталляции;
- наличие ZHA и pairing конкретного Zigbee-устройства.

При старте после restore интеграция должна:

1. загрузить сохранённые transmitters и registry;
2. просканировать текущие ZHA устройства, если ZHA доступен;
3. найти кандидатов по profile, manufacturer, model и area name;
4. если сохранённый IEEE не найден, не менять его автоматически;
5. создать Repair issue и предложить пользователю сопоставить сохранённый transmitter с найденным ZHA-устройством, оставить отключённым или удалить конфигурацию.

Автоматическая замена IEEE без подтверждения запрещена, потому что несколько одинаковых TS1201 в одной инсталляции неотличимы только по `(model, manufacturer)`.

Area portability должна использовать `area_name` как подсказку для пользователя. `area_id` можно хранить как runtime/local metadata, но не считать переносимым идентификатором.

### 20.8 Graceful degradation

Если ZHA недоступен, интеграция должна стартовать без падения, загрузить registry и выставить status/error:

```text
zha_unavailable
```

При этом services, требующие реального transmitter, должны возвращать ошибку `zha_unavailable` или `transmitter_unavailable`, а UI должен показывать repair/instruction вместо пустого состояния.

### 20.9 Ограничения MVP

Multi-transmitter архитектура должна быть заложена в naming, storage и profiles, но полноценная UX-поддержка нескольких transmitters может идти после стабилизации Phase 1 для одного TS1201.

Минимум для Phase 1:

- `device_profiles.py` с `ts1201_zosung`;
- storage-ключ `transmitters`, даже если в нём один transmitter;
- optional `transmitter_id` в service schema;
- корректная ошибка при нескольких transmitters без явного выбора;
- без автоматического IEEE remap без подтверждения пользователя.
