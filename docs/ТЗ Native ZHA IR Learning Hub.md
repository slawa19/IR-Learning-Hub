# Техническое задание: Native ZHA IR Learning Hub для Tuya TS1201 / MOES UFO-R11

Локальная Home Assistant custom integration для обучения, хранения и отправки IR-команд без SmartIR runtime.

## 1. Цель проекта

Создать локальную Home Assistant custom integration для обучения, хранения и отправки ИК-команд через Zigbee IR-пульт Tuya TS1201 / MOES UFO-R11, подключённый через ZHA.

Проект должен быть самостоятельным native ZHA runtime для сохранённых ИК-команд. SmartIR, IR Wrapper, Tuya Cloud, Smart Life и Zigbee2MQTT не нужны для MVP.

Проект больше не зависит от SmartIR. Он самостоятельно обучает, хранит и отправляет IR-команды через TS1201/ZHA.

Целевой пользовательский сценарий:

```text
выбрал устройство → выбрал команду → Learn → нажал кнопку физического пульта → Read → Test → Save → Send из UI/HA service
```

## 2. Что уже подтверждено

Устройство работает локально через ZHA без Tuya Cloud, Smart Life и Zigbee2MQTT.

Параметры устройства:

```text
Модель: TS1201 / MOES UFO-R11
Manufacturer: _TZ3290_ot6ewjvmejq5ekhl
IEEE: b0:e8:e8:ff:fe:16:ef:35
Endpoint: 1
IR control cluster: 0xE004 / 57348
IR transmit cluster: 0xED00 / 60672
Quirk: zhaquirks.tuya.ts1201.ZosungIRBlaster
Send command: 2
Learn command: 1
Attribute with learned code: 0
```

Примечание по clusters: cluster `0xED00 / 60672` обнаружен на устройстве, но в MVP не используется. Learn/send подтверждены через cluster `0xE004 / 57348`.

Проверено:

- ZHA-устройство найдено.
- Quirk `zhaquirks.tuya.ts1201.ZosungIRBlaster` активен.
- Cluster `0xE004 / 57348` присутствует.
- Отправка ИК-кода работает через `zha.issue_zigbee_cluster_command`.
- Обучение ИК-кода работает через `zha.issue_zigbee_cluster_command`.
- Выученный код можно прочитать через ZHA WebSocket API:
  - endpoint: `zha/devices/clusters/attributes/value`
  - attribute id: `0`
- IR Wrapper не нужен и не должен использоваться.
- SmartIR не нужен для runtime, потому что native ZHA уже закрывает learn/read/send.

## 3. Главный архитектурный вывод

```text
TS1201 / ZHA native API
  ↓
custom integration
  - learn
  - read_last_code
  - test_code
  - save_command
  - send_command
  - storage
  - status
  ↓
HA services / Lovelace card / automations / agents
```

SmartIR исключается из основной архитектуры. Причина: SmartIR `v1.18.1` не имеет встроенного controller backend для ZHA / TS1201, а native ZHA API уже умеет отправлять команды напрямую.

SmartIR export может быть добавлен когда-нибудь как дополнительная функция переноса кодов, но не входит в MVP и не должен влиять на service contracts, storage-модель или UI первого релиза.

### 3.1 Почему не SmartIR runtime

SmartIR состоит из двух независимых частей:

1. JSON-файлы кодов;
2. controller backend для физической отправки команд.

IR Learning Hub теоретически может создать JSON-файл с кодами, совместимый со структурой SmartIR. Но SmartIR без ZHA/TS1201 controller backend не сможет отправить эти команды через TS1201.

Поэтому SmartIR не используется как runtime в MVP. Runtime проекта — native ZHA API через собственные Home Assistant services.

## 3.2 Milestone 0: backend-чтение attribute 0

Перед полноценной реализацией MVP нужно проверить главный оставшийся технический риск: Python-код custom integration должен уметь прочитать ZHA attribute `0` без frontend WebSocket-клиента.

Критерии готовности и fallback описаны в разделе `12. MVP`, подраздел `MVP-0`.

## 4. Что должно получиться

Пользовательский сценарий:

```text
1. Пользователь открывает IR Learning Hub.
2. Выбирает или создаёт управляемое IR-устройство, например CD-плеер.
3. Выбирает или создаёт команду, например open_close.
4. Нажимает Learn.
5. Нажимает кнопку на физическом ИК-пульте.
6. Система читает base64-код из ZHA attribute 0.
7. Пользователь нажимает Test.
8. Если устройство сработало, пользователь нажимает Save.
9. Команда сохраняется во внутренний registry.
10. Пользователь отправляет сохранённую команду из UI, HA service, automation или agent.
```

## 5. Область проекта

### Входит в проект

- Минимальная custom integration для Home Assistant.
- Config flow для выбора ZHA TS1201.
- Services для обучения, чтения, тестирования, сохранения и отправки IR-команд.
- Хранение команд в `.storage` через Home Assistant `Store`.
- Status sensor для диагностики.
- Простая custom card или панель мастера для UI.
- Button grid для отправки сохранённых команд.
- Возможность использовать команды в automations и agents через HA services.

### Не входит в MVP

- SmartIR runtime или SmartIR export.
- IR Wrapper.
- Tuya Cloud.
- Smart Life.
- Zigbee2MQTT.
- Хаки ядра Home Assistant.
- Хранение кодов в `input_text` / helpers как финальная архитектура.
- Полноценная climate entity.
- Поддержка нескольких IR-передатчиков одновременно.
- Автоматическая база готовых IR-кодов.

## 6. Архитектура

Home Assistant integration domain:

```text
ir_learning_hub
```

Структура custom integration:

```text
custom_components/ir_learning_hub/
  manifest.json
  __init__.py
  config_flow.py
  const.py
  services.yaml
  storage.py
  zha_adapter.py
  sensor.py
```

Логика работы с ZHA и хранением должна находиться в custom integration, а не в Lovelace-карточке.

Настройка должна идти через `config_flow`: выбрать ZHA TS1201, сохранить IEEE, endpoint, cluster и timeout. Хардкод IEEE допустим только в документации и тестовых примерах.

`manifest.json` должен содержать:

```json
{
  "domain": "ir_learning_hub",
  "name": "IR Learning Hub",
  "dependencies": ["zha"],
  "config_flow": true
}
```

В MVP поддерживается один настроенный transmitter. Все services работают с активным config entry по умолчанию. Поле `transmitter_id` в service contracts не используется до появления поддержки нескольких IR-передатчиков.

В service API термин `device_id` не используется для управляемого IR-устройства, чтобы не конфликтовать с Home Assistant device registry. Для управляемого IR-устройства используется `ir_device_id`.

Config entry является единственным source of truth для transmitter-параметров: IEEE, endpoint, cluster, command IDs, timeout. Storage хранит только пользовательский registry locations / IR-devices / commands.

## 7. Интеграция с ZHA

### 7.1 Learn

Для запуска режима обучения использовать ZHA cluster command:

```yaml
action: zha.issue_zigbee_cluster_command
data:
  ieee: "b0:e8:e8:ff:fe:16:ef:35"
  endpoint_id: 1
  cluster_id: 57348
  cluster_type: in
  command: 1
  command_type: server
  params:
    on_off: "true"
```

Ожидаемый результат:

```text
[]
```

После запуска пользователь должен навести физический пульт на TS1201 и нажать нужную кнопку. LED на устройстве загорается синим, после получения команды гаснет.

### 7.2 Read last learned code

После обучения нужно прочитать значение attribute `0` через ZHA WebSocket API:

```text
zha/devices/clusters/attributes/value
```

Параметры чтения:

```text
IEEE: b0:e8:e8:ff:fe:16:ef:35
Endpoint: 1
Cluster: 57348 / 0xE004
Attribute ID: 0
```

Ожидаемый результат:

```text
base64 IR-код
```

Если значение пустое, значит команда ещё не была обучена или обучение не завершилось.

Перед новым learn интеграция должна запоминать предыдущее значение attribute `0`. После learn успехом считается только непустой код, отличающийся от предыдущего значения, либо код, полученный после подтверждённого события завершения обучения, если такое событие будет доступно.

Implementation note: если backend custom integration не может вызвать тот же WebSocket handler напрямую, допустим fallback через ZHA gateway/device proxy / zigpy device object. Ожидаемый fallback-путь должен быть проверен в Milestone 0:

```python
zha_device = zha_gateway.get_device(ieee)
cluster = zha_device.device.endpoints[1].in_clusters[0xE004]
attrs, failed = await cluster.read_attributes([0])
code = attrs.get(0) or attrs.get("last_learned_ir_code")
```

Точный объектный путь может отличаться в HA 2026.6.1, поэтому Milestone 0 должен зафиксировать фактически рабочий API. Fallback не должен требовать monkey patching.

### 7.3 Send / Test

Для отправки IR-кода использовать:

```yaml
action: zha.issue_zigbee_cluster_command
data:
  ieee: "b0:e8:e8:ff:fe:16:ef:35"
  endpoint_id: 1
  cluster_id: 57348
  cluster_type: in
  command: 2
  command_type: server
  params:
    code: "<base64>"
```

Ожидаемый результат:

```text
[]
```

Критерий успеха: управляемое устройство выполнило действие.

## 8. Services custom integration

Интеграция должна предоставить минимум следующие services.

### 8.1 `ir_learning_hub.learn`

Запускает режим обучения на TS1201.

Параметры:

```yaml
timeout: 60
```

Результат:

```text
learn_started
```

### 8.2 `ir_learning_hub.read_last_code`

Читает последний выученный код из ZHA attribute `0`.

Параметры:

```text
нет
```

Результат:

```yaml
code: "<base64>"
```

Если код пустой, service должен вернуть ошибку `code_empty`.

Service должен использовать Home Assistant service response data для возврата кода вызывающему клиенту.

### 8.3 `ir_learning_hub.learn_and_read`

Запускает обучение и ожидает новый код в одном вызове.

Параметры:

```yaml
timeout: 60
poll_interval: 1
```

Поведение:

1. запомнить предыдущее значение attribute `0`;
2. включить режим обучения;
3. опрашивать attribute `0` до timeout;
4. считать успехом непустой код, отличающийся от предыдущего значения, либо код, полученный после подтверждённого события завершения обучения, если такое событие будет доступно;
5. вернуть base64-код через service response data.

Polling должен быть полностью async и не блокировать Home Assistant event loop. Между попытками чтения нужно использовать неблокирующее ожидание:

```python
await asyncio.sleep(poll_interval)
```

Запрещены синхронные циклы ожидания, `time.sleep()` и busy-wait внутри service handler.

Если код не появился до timeout, service должен вернуть ошибку `learn_timeout`.

### 8.4 `ir_learning_hub.test_code`

Отправляет указанный код через ZHA без сохранения.

Параметры:

```yaml
code: "<base64>"
```

Результат:

```text
sent
```

### 8.5 `ir_learning_hub.save_command`

Сохраняет код в registry.

Параметры:

```yaml
location_id: cabinet
ir_device_id: cd_player
command_id: open_close
name: Open/Close
code: "<base64>"
verified: true
```

Результат:

```text
saved
```

Если `verified: false`, команда сохраняется, но UI должен показывать предупреждение. `send_command` может отправлять непроверенную команду, но UI должен визуально отличать её от проверенной и предлагать сначала выполнить `test_code`.

Если команда с таким `location_id` / `ir_device_id` / `command_id` уже существует, `save_command` работает как upsert: заменяет `code`, `name`, `verified`, `format` и `updated_at`, не требуя предварительного удаления команды.

### 8.6 `ir_learning_hub.send_command`

Отправляет сохранённую команду через ZHA.

Параметры:

```yaml
location_id: cabinet
ir_device_id: cd_player
command_id: open_close
```

Результат:

```text
sent
```

### 8.7 `ir_learning_hub.list_commands`

Возвращает список сохранённых locations, IR-устройств и команд.

Параметры:

```text
нет
```

Результат через service response data:

```yaml
locations:
  cabinet:
    name: Кабинет
    devices:
      cd_player:
        name: CD Player
        commands:
          - open_close
          - power
          - play
```

### 8.8 Registry management services

Минимально нужны:

- `ir_learning_hub.add_location`
- `ir_learning_hub.add_device`
- `ir_learning_hub.add_command`
- `ir_learning_hub.rename_location`
- `ir_learning_hub.rename_device`
- `ir_learning_hub.rename_command`
- `ir_learning_hub.delete_location`
- `ir_learning_hub.delete_device`
- `ir_learning_hub.delete_command`
- `ir_learning_hub.list_commands`

`delete_location` и `delete_device` должны требовать явного подтверждения в service data или UI, потому что удаляют вложенные команды.

Формат ID:

```text
location_id:   [a-z0-9_]+
ir_device_id:  [a-z0-9_]+
command_id:    [a-z0-9_]+
```

Display names могут быть любыми человекочитаемыми строками. Stable IDs не должны содержать пробелы, кириллицу или спецсимволы, чтобы их было безопасно использовать в automations и agents.

`export_registry` и `import_registry` не входят в MVP и относятся к отложенным возможностям.

Services, возвращающие данные вызывающему клиенту, должны использовать механизм Home Assistant service response data. Это обязательно для `read_last_code`, `learn_and_read`, `list_commands` и будущих export services.

### 8.9 Ошибки services

Services должны возвращать стабильные коды ошибок, пригодные для UI, automations и agents:

```text
transmitter_not_configured
zha_device_not_found
cluster_not_found
learn_failed
learn_timeout
code_empty
send_failed
command_not_found
storage_error
```

Человекочитаемое описание ошибки должно возвращаться отдельно от кода ошибки, чтобы UI мог локализовать сообщения без разбора произвольного текста.

## 9. Хранение данных

IR-коды хранить в `.storage`, не в helpers.

Storage не хранит transmitter-конфигурацию. Эти параметры принадлежат config entry. Это исключает расхождение между setup options и registry.

Хранилище должно создаваться через стандартный Home Assistant `Store`:

```python
Store(hass, 1, "ir_learning_hub")
```

Пример внутренней структуры:

```json
{
  "version": 1,
  "locations": {
    "cabinet": {
      "name": "Кабинет",
      "devices": {
        "cd_player": {
          "name": "CD Player",
          "type": "generic",
          "commands": {
            "open_close": {
              "name": "Open/Close",
              "code": "base64-code",
              "format": "zosung_base64",
              "verified": true,
              "updated_at": "2026-06-09T16:42:00+00:00"
            }
          }
        }
      }
    }
  }
}
```

Код нужно хранить как opaque string без перекодирования. Интеграция не должна валидировать или модифицировать содержимое base64-кода, кроме проверки, что строка непустая. Формат Zosung может быть vendor-specific payload, а не универсальный IR base64.

Поле `format` фиксирует формат transport payload для будущих миграций и дополнительных передатчиков. В MVP значение всегда `zosung_base64`, при отправке оно не вызывает перекодирования.

При изменении storage schema версия `Store` должна увеличиваться, а integration должна выполнять миграцию старых данных до актуальной структуры.

## 10. Status entity

Интеграция должна создать диагностический sensor:

```text
sensor.ir_learning_hub_status
```

Состояния:

- `idle`
- `learning`
- `code_received`
- `sending`
- `error`

Attributes:

```yaml
last_action: learn
last_location_id: cabinet
last_ir_device_id: cd_player
last_command_id: open_close
last_error: null
last_error_message: null
last_updated: "2026-06-09T16:42:00+00:00"
```

Status sensor предназначен для диагностики. UI, automations и agents должны использовать services, а не парсить attributes sensor как основной API.

## 11. UI мастера

UI должен быть реализован как Home Assistant custom panel / Lovelace card поверх services `ir_learning_hub.*`. UI не должен напрямую реализовывать низкоуровневую работу с ZHA, читать zigpy objects или обращаться к ZHA WebSocket API. Единственный runtime API для UI — services custom integration и их response data.

### 11.1 Основные зоны интерфейса

Минимальный UI состоит из четырёх зон:

1. transmitter status;
2. registry navigator;
3. learning workspace;
4. command grid.

#### Transmitter status

Показывает состояние выбранного TS1201:

- configured / not configured;
- IEEE;
- endpoint;
- cluster `0xE004`;
- последнее действие;
- последний error code, если есть.

Если transmitter не настроен, UI должен показать call-to-action открыть config flow / integration options. Learn, Test и Send должны быть disabled.

#### Registry navigator

Позволяет выбрать или создать:

- выбор location;
- выбор или создание IR-устройства;
- выбор или создание команды.

Location, IR-device и command должны иметь stable ID и display name. ID валидируются по правилам из раздела `8.8 Registry management services`.

Рекомендуемый layout:

```text
[Location select]  [+]
[IR device select] [+]
[Command select]   [+]
```

При создании элемента UI должен показывать два поля:

```text
ID
Name
```

`Name` может автоматически предлагаться из `ID`, но пользователь может изменить его.

#### Learning workspace

Содержит основной сценарий обучения:

- `Learn`;
- `Read code`;
- code preview;
- `Test`;
- `Save command`.

Code preview должен показывать только начало и конец base64-кода, чтобы интерфейс не ломался длинной строкой:

```text
eyJr...AA==
```

Полный код можно раскрыть через secondary action `Show full code` / `Copy code`.

#### Command grid

Показывает сохранённые команды выбранного IR-устройства в виде кнопок отправки. Каждая кнопка должна вызывать `ir_learning_hub.send_command`.

Команды с `verified: false` должны иметь отдельный визуальный статус. При ручной отправке из UI такая команда должна показать confirmation dialog с предложением сначала выполнить `Test`. Automations и service calls не блокируются этим UI-подтверждением.

### 11.2 UI flow

Основной flow:

```text
idle
  → learning
  → code_received
  → tested
  → saved
```

Поведение состояний:

- `idle`: пользователь выбирает location, IR-устройство и команду;
- `learning`: после `Learn` / `learn_and_read` показывается ожидание нажатия кнопки физического пульта и timeout countdown;
- `code_received`: отображается полученный base64-код и доступны `Test` / `Save`;
- `tested`: после успешного `Test` команда может сохраняться как `verified: true`;
- `saved`: команда отображается в списке и button grid;
- `error`: показывается стабильный error code и человекочитаемое сообщение, например `learn_timeout`.

При `learn_timeout` UI должен вернуться в `idle` или позволить повторить `Learn` без потери выбранных location / IR-device / command.

### 11.3 Состояния кнопок

#### Idle

- `Learn`: enabled, если выбран transmitter и заполнены location / IR-device / command;
- `Read code`: enabled, если выбран transmitter;
- `Test`: disabled, пока нет текущего code preview;
- `Save command`: disabled, пока нет текущего code preview.

#### Learning

- `Learn`: disabled;
- `Read code`: disabled;
- `Test`: disabled;
- `Save command`: disabled;
- показывается countdown до timeout;
- доступна `Cancel`, если реализация service поддерживает cancellation; иначе кнопка не показывается.

#### Code received

- `Learn`: enabled для повторного обучения;
- `Read code`: enabled;
- `Test`: enabled;
- `Save command`: enabled, но по умолчанию сохраняет `verified: false`, если `Test` ещё не был успешным.

#### Tested

- `Save command`: enabled и сохраняет `verified: true`;
- `Test`: можно повторить;
- `Learn`: можно повторить и заменить текущий code preview.

#### Saved

- команда появляется в command grid без reload страницы;
- текущий selection сохраняется;
- UI показывает короткий success status без modal.

### 11.4 Ошибки и empty states

UI должен отображать error code и человекочитаемое сообщение отдельно. Error code нужен для диагностики и support, сообщение — для пользователя.

Минимальные состояния:

- transmitter не настроен;
- ZHA device не найден;
- cluster `0xE004` не найден;
- code empty;
- learn timeout;
- send failed;
- storage error;
- registry пустой.

Для пустого registry UI должен предлагать создать первый location и IR-устройство. Для пустого command list UI должен предлагать создать или обучить первую команду.

### 11.5 Управление registry

UI должен поддерживать:

- создание / переименование / удаление location;
- создание / переименование / удаление IR-device;
- создание / переименование / удаление command;
- переобучение существующей command через `save_command` upsert.

Удаление location или IR-device требует confirmation dialog, потому что удаляет вложенные элементы. Dialog должен показывать количество затронутых devices / commands.

Переименование меняет только display name. Stable ID не меняется автоматически, чтобы не ломать automations. Если в будущем понадобится rename ID, это должна быть отдельная операция миграции ссылок.

### 11.6 Responsive layout

Desktop layout:

```text
┌───────────────┬──────────────────────────┐
│ Navigator     │ Learning workspace        │
│               │ Command grid              │
└───────────────┴──────────────────────────┘
```

Mobile layout:

```text
Transmitter status
Navigator
Learning workspace
Command grid
```

На mobile основные действия `Learn`, `Test`, `Save` должны оставаться доступными без горизонтального скролла. Длинные base64-коды не должны расширять layout.

### 11.7 Non-goals UI MVP

В MVP UI не обязан поддерживать:

- drag-and-drop сортировку команд;
- импорт / экспорт registry;
- SmartIR export;
- несколько transmitters;
- сложные иконки типов устройств;
- cloud sync.

## 12. MVP

### MVP-0: backend-чтение ZHA attribute 0

До реализации основного backend нужно подтвердить, что custom integration может прочитать attribute `0` из Python-кода.

Критерии готовности:

- custom integration запускает learn;
- пользователь нажимает кнопку физического пульта;
- custom integration получает непустой base64-код;
- если прямой backend-доступ к ZHA WebSocket API невозможен, подтверждён fallback через ZHA gateway/device proxy / zigpy object без monkey patching;
- Milestone 0 документирует фактически рабочий Python API чтения attribute `0` для HA 2026.6.1.

### MVP-1: backend integration + services + storage

Минимальная первая версия должна уметь:

1. Настроить один TS1201 через config flow.
2. Запустить обучение.
3. Прочитать последний выученный IR-код через `read_last_code` или `learn_and_read`.
4. Отправить код для теста.
5. Сохранить команду в registry.
6. Отправить сохранённую команду через HA service.
7. Получить список сохранённых команд через `list_commands`.
8. Не потерять registry после перезапуска Home Assistant.

### MVP-2: Lovelace card / panel

Вторым этапом добавить UI:

1. мастер Learn / Read / Test / Save;
2. список сохранённых команд;
3. button grid для отправки сохранённых команд.

Без красивого интерфейса на первом этапе допустимо управление через services Home Assistant. UI можно добавить вторым этапом.

## 13. Критерии готовности MVP

MVP считается готовым, если:

- команда `learn` переводит TS1201 в режим обучения;
- после нажатия кнопки физического пульта система получает непустой base64-код;
- `learn_and_read` возвращает новый код или ошибку `learn_timeout`;
- команда `test_code` отправляет этот код обратно;
- управляемое устройство реагирует на тестовую команду;
- команда сохраняется в registry;
- `send_command` отправляет сохранённую команду;
- `list_commands` возвращает сохранённые locations/devices/commands;
- команда доступна для automations через HA service;
- после перезапуска Home Assistant сохранённая команда всё ещё отправляется.

## 14. Проверка агентом Home Assistant

Агент должен проверить последовательно:

### Шаг 1. Проверить устройство ZHA

Проверить, что существует устройство:

```text
IEEE: b0:e8:e8:ff:fe:16:ef:35
Manufacturer: _TZ3290_ot6ewjvmejq5ekhl
Model: TS1201
Quirk: zhaquirks.tuya.ts1201.ZosungIRBlaster
```

Критерий успеха: устройство найдено, quirk активен.

### Шаг 2. Проверить cluster

Проверить наличие cluster:

```text
0xE004 / 57348
```

Критерий успеха: cluster присутствует на endpoint `1`.

### Шаг 3. Проверить learn

Вызвать:

```yaml
action: zha.issue_zigbee_cluster_command
data:
  ieee: "b0:e8:e8:ff:fe:16:ef:35"
  endpoint_id: 1
  cluster_id: 57348
  cluster_type: in
  command: 1
  command_type: server
  params:
    on_off: "true"
```

Критерий успеха: сервис возвращает `[]`, LED устройства переходит в режим обучения.

### Шаг 4. Проверить чтение кода

После нажатия кнопки физического пульта прочитать attribute `0` через:

```text
zha/devices/clusters/attributes/value
```

Критерий успеха: возвращается непустая base64-строка.

### Шаг 5. Проверить send

Отправить полученный код:

```yaml
action: zha.issue_zigbee_cluster_command
data:
  ieee: "b0:e8:e8:ff:fe:16:ef:35"
  endpoint_id: 1
  cluster_id: 57348
  cluster_type: in
  command: 2
  command_type: server
  params:
    code: "<base64>"
```

Критерий успеха: сервис возвращает `[]`, устройство реагирует.

### Шаг 6. Проверить сохранение и повторную отправку

Сохранить тестовую команду `open_close`, перезапустить Home Assistant и отправить команду через `ir_learning_hub.send_command`.

Критерий успеха: сохранённая команда переживает перезапуск и устройство реагирует.

### Шаг 7. Проверить list_commands

Вызвать `ir_learning_hub.list_commands`.

Критерий успеха: service response data содержит сохранённую команду `open_close`.

## 15. Риски и ограничения

- Нужно подтвердить, что backend custom integration может читать `zha/devices/clusters/attributes/value`, а не только frontend/WebSocket client.
- Если backend не может вызвать этот API напрямую, нужен fallback через ZHA device proxy / zigpy object.
- Native `infrared` domain в HA 2026.6.1 не работает с TS1201 как готовая entity.
- Native `remote` domain присутствует, но TS1201 не представлен как `remote.*`.
- IR Wrapper несовместим с HA 2026.6.1 и не должен использоваться.
- SmartIR не нужен для MVP и не должен блокировать native ZHA runtime.
- Attribute `0` может вернуть старый код, если новое обучение не завершилось. Митигируется сравнением с previous value и timeout/polling поведением.

## 16. Отложенные возможности

- SmartIR-compatible export.
- Export/import registry или простой backup JSON.
- `remote` entity bridge.
- Несколько IR-передатчиков.
- Полноценная climate entity.
- `climate_ir`: одно состояние кондиционера = один IR-код.
- HACS-публикация.
- Автоматическая база готовых IR-кодов.

Экспорт registry в SmartIR-compatible JSON или простой backup JSON не означает, что SmartIR сможет отправлять эти команды через TS1201 без отдельного controller backend.

## 17. Необходимый результат

В результате должен появиться локальный native ZHA IR hub:

```text
физический ИК-пульт → TS1201 через ZHA → base64-код → test → save → send через ZHA из UI/service/automation
```

Основной принцип: минимум зависимостей, максимум пользы. Не строить мост к SmartIR, пока native ZHA полностью закрывает runtime.