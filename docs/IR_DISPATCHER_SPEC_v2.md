# IR Learning Hub - IR Dispatcher Spec v2

## Защита IR-отправки от устаревших команд и честные статусы Zigbee dispatch

**Статус:** post-implementation spec review для dispatcher release.  
**Baseline:** published `ir_learning_hub` v0.3.4.  
**Working tree:** prepared unreleased dispatcher metadata `0.4.0`.

---

## 1. Цель

Сделать отправку IR-команд безопасной при деградации Zigbee-сети:

- не исполнять пользовательские команды через минуты после клика;
- не позволять очередям расти без ограничений;
- честно различать "передано в ZHA" и подтвержденную физическую IR-доставку;
- изолировать очереди разных физических transmitters;
- сделать модель `mute` / `unmute` / `mute_toggle` семантически корректной.

## 2. Не цели

- Не подтверждать, что Sony, Denon или другое AV-устройство приняло IR-сигнал.
- Не исправлять Zigbee routing, батарею или качество радиолинии.
- Не менять learning flow, кроме изоляции private ZHA API для чтения learned code и discovery.
- Не вводить глобальную очередь для всех transmitters.
- Не отменять уже переданные Zigbee-команды; можно отменять только commands, еще не начавшие dispatch.

---

## 3. Historical baseline v0.3.4: подтвержденные факты до dispatcher

Этот раздел описывает опубликованный baseline `v0.3.4`, а не текущее состояние
working tree после реализации спеки.

### 3.1 Consumer entity path

```text
consumer.async_send_registry_command()
-> infrared.async_send_command()
-> IRLearningHubInfraredEmitter.async_send_command()
-> ZHAAdapter.async_send()
-> zha.issue_zigbee_cluster_command(..., blocking=True)
```

### 3.2 Direct service path

```text
ir_learning_hub.send_command
ir_learning_hub.test_code
-> ZHAAdapter.async_send()
```

На обоих send-path в baseline `v0.3.4` отсутствовали:

- очередь на transmitter;
- TTL команды;
- отмена устаревших commands;
- debounce/coalescing;
- ограничение backlog.

### 3.3 Статус отправки

`IRLearningHubInfraredEmitter` прямо логирует:

```text
IR send dispatched to ZHA (delivery not confirmed)
```

Но direct services возвращают:

```json
{"status": "sent"}
```

А global status sensor после успешного вызова может показывать:

```text
state: idle
last_error: null
```

Это создает ложное впечатление подтвержденной физической доставки.

### 3.4 Status sensor

Сейчас поддерживаются только состояния:

```text
idle
learning
sending
code_received
error
```

Сенсор один на весь hub. При параллельных transmitters он может отражать только **последнее событие**, а не состояние каждой отдельной команды.

### 3.5 Mute

Код поддерживает feature roles:

```text
mute
unmute
mute_toggle
```

В baseline `media_player.async_mute_volume(False)` допускал fallback на `mute`.
Для физического toggle-кода это семантически неверно.

### 3.6 ZHA compatibility

Private helper:

```python
homeassistant.components.zha.helpers.async_get_zha_device_proxy
```

в baseline импортировался напрямую в двух местах:

- `zha_adapter.py` - чтение последнего learned code;
- `config_flow.py` - discovery ZHA transmitters.

Это риск поломки после обновления Home Assistant. Compatibility layer должен закрыть оба места, но поведение ошибок для них разное: transport/read path должен давать явную integration error, а config flow discovery может fail-soft и оставить manual setup.

---

# P0 - Per-transmitter dispatcher, TTL и bounded backlog

## 4. Новый модуль

Создать:

```text
custom_components/ir_learning_hub/dispatcher.py
```

Основные сущности:

```python
IRCommandDispatcher
QueuedIRCommand
CommandContext
CommandDispatchResult
```

### 4.1 CommandContext

Dispatcher используется как entity path, так и service path. Контекст нужен для диагностики без логирования raw IR code:

```python
@dataclass(frozen=True)
class CommandContext:
    request_id: str
    transmitter_id: str
    location_id: str | None
    ir_device_id: str | None
    command_id: str | None
    source: Literal["entity", "service"]
```

Для entity path registry metadata не доходит до emitter через стандартный HA infrared API автоматически. Чтобы сохранить `location_id`, `ir_device_id` и `command_id`, расширить `ZosungCommand` безопасными optional metadata либо передавать dispatcher context до вызова HA infrared helper. Если команда пришла в emitter от внешнего caller без metadata, эти поля остаются `None`.

### 4.2 CommandDispatchResult

Минимальный result, который удобно возвращать service path и использовать в status:

```python
@dataclass(frozen=True)
class CommandDispatchResult:
    request_id: str
    status: Literal["dispatched_unconfirmed"]
    delivery_confirmed: Literal[False]
    transmitter_id: str
    queue_wait_ms: int
    command_age_ms: int
    queue_depth: int
```

Ошибочные финалы должны быть исключениями с integration error code, а не success-shaped result.

### 4.3 Ключ очереди

Использовать canonical transmitter key из registry:

```python
transmitter_id_for_store_item(...)
```

Сейчас это normalized IEEE, например:

```text
b0e8e8fffe16ef35
```

Не использовать название комнаты, virtual entity ID или имя устройства.

### 4.4 Lifecycle

Создавать dispatcher в `async_setup_entry()` рядом с уже существующими shared resources:

```python
domain_data["store"]
domain_data["status"]
domain_data["adapter"]
domain_data["learn_tasks"]
domain_data["dispatcher"]
```

В `_teardown_domain()` dispatcher должен:

- остановить workers;
- отменить pending futures;
- очистить per-transmitter state;
- завершить pending/not-started requests ошибкой `dispatcher_stopped`;
- не отменять active command, уже переданную в `adapter.async_send()` / ZHA; ее
  результат остается `dispatched_unconfirmed` или transport error после
  завершения active dispatch.

Не удалять dispatcher при unload отдельной platform; teardown выполняется только после выгрузки hub entry / последнего владельца domain resources.

## 5. Поведение очереди

Для каждого physical transmitter:

```text
не более одной активной ZHA send-команды;
отдельная очередь pending-команд;
никакой integration-level сериализации между разными transmitters.
```

Dispatcher допускает параллельную работу разных transmitters, но не гарантирует параллелизм низкоуровневого Zigbee radio stack.

### 5.1 Время

При enqueue сохранить оба времени:

```python
created_monotonic = time.monotonic()
created_at = dt_util.utcnow()
```

TTL вычислять только через `time.monotonic()`.

### 5.2 Defaults

```text
ttl_seconds: 3
max_backlog: 8
```

`max_backlog` означает:

```text
active command + pending commands <= 8
```

При переполнении новую command не принимать:

```text
IRLearningHubError("queue_full", ...)
```

В первой версии не использовать silent drop policy.

### 5.3 TTL

Worker обязан проверить возраст command непосредственно перед:

```python
adapter.async_send(...)
```

Если:

```text
now_monotonic - created_monotonic > ttl_seconds
```

то command:

- не вызывает `adapter.async_send()`;
- завершается ошибкой `command_expired`;
- записывает status `expired`.

### 5.4 Финальные результаты

Переходные статусы:

```text
queued
-> dispatching
```

Единственный финальный success result:

```text
dispatched_unconfirmed
```

Финальные error status values:

```text
expired
queue_full
delivery_failed
dispatcher_stopped
```

Соответствующие error codes для исключений:

```text
command_expired
queue_full
send_failed
dispatcher_stopped
```

`queued` и `dispatching` не являются финальными `CommandDispatchResult`, если entity/service ожидает completion dispatcher.

## 6. Интеграция в send-path

### 6.1 Entity path

Изменить:

```python
IRLearningHubInfraredEmitter.async_send_command()
```

чтобы он вызывал dispatcher, а не `adapter.async_send()` напрямую.

Так consumer flow автоматически получает защиту, так как уже проходит через:

```python
infrared.async_send_command(...)
```

Для диагностики registry-backed consumer flow должен сохранить metadata команды до перехода через HA infrared helper. Практичный вариант: расширить `ZosungCommand` optional полями `location_id`, `ir_device_id`, `command_id`.

### 6.2 Service path

Перевести на dispatcher:

```text
ir_learning_hub.send_command
ir_learning_hub.test_code
```

Не переводить на dispatcher:

```text
learn
learn_and_read
read_last_code
```

`ZHAAdapter.async_send()` остается низкоуровневым transport API. Его должен вызывать dispatcher и специализированные flow, которым очередь сознательно не нужна.

## 7. Acceptance criteria P0

- На одном transmitter одновременно выполняется не более одного `adapter.async_send()`.
- Commands разных transmitters не блокируют друг друга уровнем integration dispatcher.
- Command старше TTL не вызывает `adapter.async_send()`.
- При переполненном backlog caller получает понятный `queue_full`.
- Transport exception дает `delivery_failed` status и пробрасывается caller как `send_failed`.
- Idle worker/state удаляется после drain либо при teardown.
- Нет broad catch, превращающего ошибку в success-shaped fallback.

---

# P1 - Честные статусы и service responses

## 8. Новые status states

Сохранить существующие states для compatibility:

```text
idle
learning
sending
code_received
error
```

Добавить:

```text
queued
dispatching
dispatched_unconfirmed
delivery_failed
expired
queue_full
dispatcher_stopped
```

`STATUS_SENDING` допустимо сохранить временно, но новый send-path должен использовать конкретные состояния dispatcher.

## 9. Status attributes

Добавить в `HubStatus`:

```text
last_request_id
last_dispatch_status
last_transmitter_id
last_queue_wait_ms
last_command_age_ms
last_queue_depth
delivery_confirmed
```

Для `dispatched_unconfirmed`:

```text
delivery_confirmed: false
```

### Ограничение global sensor

`sensor.ir_learning_hub_status` - один на весь hub. Его state и attributes отражают только последнее событие. Service response с `request_id` - результат конкретного request и является более точным источником информации.

## 10. Service responses

Успешный dispatch возвращает:

```json
{
  "status": "dispatched_unconfirmed",
  "delivery_confirmed": false,
  "request_id": "..."
}
```

Не возвращать:

```json
{"status": "sent"}
```

Ошибки должны быть HA service errors, а не success responses:

```text
command_expired
queue_full
send_failed
dispatcher_stopped
```

## 11. UI wording

Обновить user-visible labels/messages для существующих ключей `sent` /
`sentToDevice` на формулировку уровня. Переименование ключей не требуется:

```text
Передано в Zigbee.
Физическая IR-доставка целевому устройству не подтверждается.
```

Обновить:

- `custom_components/ir_learning_hub/www/ir-learning-hub-card.js`;
- `custom_components/ir_learning_hub/strings.json`;
- `custom_components/ir_learning_hub/translations/en.json`;
- `custom_components/ir_learning_hub/translations/ru.json`;
- `custom_components/ir_learning_hub/translations/uk.json`.

## 12. Acceptance criteria P1

- Переход `queued -> dispatching -> dispatched_unconfirmed` отражается в status.
- TTL expiry дает `state=expired`, `last_error=command_expired`.
- Queue overflow дает `state=queue_full`, `last_error=queue_full`.
- Transport exception дает `state=delivery_failed`, `last_error=send_failed`.
- Teardown pending request дает `state=dispatcher_stopped`, `last_error=dispatcher_stopped`.
- `sensor.py` включает новые enum options.
- `translations/en.json`, `translations/ru.json`, `translations/uk.json` содержат labels новых status values и attributes.

---

# P2 - Корректная модель mute / unmute / mute_toggle

## 13. Семантика feature roles

```text
mute         = дискретно включить mute
unmute       = дискретно выключить mute
mute_toggle  = переключить mute; итоговое состояние без feedback неизвестно
```

## 14. Capability rule

В `capabilities._infer_media_features()` добавлять media mute capability только если:

```python
{"mute", "unmute"} <= features or "mute_toggle" in features
```

Не рекламировать `VOLUME_MUTE` для `mute` без `unmute`: иначе HA UI предлагает unmute, которого устройство выполнять не умеет.

## 15. async_mute_volume semantics

### Discrete mute + unmute

```text
True  -> mute
False -> unmute
```

Состояние local optimistic, но модель команд корректна.

### Только mute_toggle

```text
True  -> mute_toggle
False -> mute_toggle
```

Добавить entity attribute:

```text
mute_state_assumed: true
```

`is_volume_muted` остается локальным optimistic state, а не утверждением о фактическом состоянии receiver.

### Только mute

```text
True  -> mute
False -> ServiceValidationError
```

Для `mute only` capability `VOLUME_MUTE` не должен рекламироваться, поэтому штатный HA UI не должен предлагать unmute. Если метод все же вызван напрямую, нельзя использовать `mute` как fallback для unmute.

## 16. Sony SIRC migration / UX

В current code нет отдельного Sony profile, автоматически назначающего feature: есть generic Sony SIRC generator и `save_command`/`update_command`.

Миграция реализована узко и idempotent в storage v5 (`migrate_v4_to_v5`):

```text
source.type == "protocol"
source.protocol == "sony_sirc"
source.params.command == 20
feature == "mute"
```

Такие records преобразуются в:

```text
feature: mute_toggle
```

Records, уже исправленные вручную до `feature: mute_toggle`, migration должна пропустить.

## 17. Acceptance criteria P2

- `mute + unmute`: независимое управление.
- `mute_toggle only`: обе операции отправляют toggle; присутствует `mute_state_assumed=true`.
- `mute only`: `VOLUME_MUTE` не рекламируется; unmute не отправляет mute.
- Sony SIRC command `20` не классифицируется как discrete `mute`.
- UI описывает разницу трех feature roles.

---

# P3 - ZHA compatibility layer

## 18. Новый модуль

Создать:

```text
custom_components/ir_learning_hub/zha_compat.py
```

Минимальный public surface:

```python
get_zha_device_proxy(hass, device_id)
iter_zha_nested_devices(zha_device_proxy)
find_zha_cluster(zha_device_proxy, endpoint_id, cluster_id, ieee=None)
detect_ir_control_cluster(zha_device_proxy, profile_id)
```

`find_zha_cluster(...)` нужен `zha_adapter.py`, а `detect_ir_control_cluster(...)` нужен `config_flow.py`. Если оставить detection в `config_flow.py`, traversal nested proxy/device все равно должен переехать в compatibility layer, чтобы private/proxy-shape знания жили в одном месте.

## 19. Ошибки

Для transport/read path при отсутствии private helper или несовместимой proxy shape:

```text
IRLearningHubError(ERROR_ZHA_UNAVAILABLE, ...)
```

с понятным сообщением о несовместимой версии Home Assistant.

Для config flow discovery:

- отсутствие helper или proxy error не должно ломать форму;
- discovery возвращает пустой список или пропускает проблемное устройство;
- manual setup остается доступным.

`zha_adapter.py` и `config_flow.py` не должны импортировать private helper напрямую.

## 20. Acceptance criteria P3

- Private helper недоступен в read path -> явный `zha_unavailable`.
- Helper бросает exception в read path -> нормализованная integration error.
- Helper недоступен в config flow discovery -> discovery fail-soft, manual setup доступен.
- Cluster не найден -> существующий `cluster_not_found`.
- Current supported proxy shape работает.
- Private import расположен только в `zha_compat.py`.

---

# 21. Тесты

В текущем репозитории тесты уже есть, поэтому задача - добавить новые targeted tests и расширить существующие suites:

```text
tests/test_dispatcher.py
tests/test_remote_platform.py
tests/test_config_flow.py
tests/test_zha_compat.py
tests/test_capabilities.py
tests/test_media_switch_platform.py
```

Status coverage находится в `tests/test_dispatcher.py`, где проверяются status
events и request/timing metadata. Если status или media-player tests станут
слишком крупными, можно выделить их в новые файлы:

```text
tests/test_status.py
tests/test_media_player.py
```

## Dispatcher

- serial execution для одного transmitter;
- isolation разных transmitters;
- TTL expiry до adapter call;
- backlog overflow;
- adapter exception;
- idle worker cleanup;
- teardown завершает pending futures ошибкой.

## Status

- `queued -> dispatching -> dispatched_unconfirmed`;
- TTL expiry;
- queue full;
- transport failure;
- request ID и timing metadata.

## Media player

- discrete `mute + unmute`;
- `mute_toggle only`;
- `mute only`;
- capability visibility;
- `mute_state_assumed`.

## Compatibility

- Helper available;
- helper unavailable in read path;
- helper unavailable in config flow discovery;
- helper raises;
- cluster missing.

---

# 22. Порядок реализации

```text
P0 dispatcher
+ P1 honest statuses
-> P2 mute semantics
-> P3 ZHA compatibility isolation
```

P0 и P1 выпускать одним PR: dispatcher без диагностируемого статуса трудно сопровождать, а честные статусы без dispatcher не защищают от выполнения устаревших команд.

---

# 23. Release / HACS gate

## 23.1 Почему это важно

Для этого репозитория HACS должен видеть новые версии через GitHub Releases. Каноничное правило HACS: если repository uses GitHub releases, remote version берется из tag name последнего GitHub Release; одного `git tag` недостаточно.

HACS-visible latest published release:

```text
tag: v0.3.4
GitHub Release: https://github.com/slawa19/IR-Learning-Hub/releases/tag/v0.3.4
manifest.json version: 0.3.4
Lovelace card version: 0.3.4
```

Prepared unreleased working tree metadata:

```text
target tag: v0.4.0
manifest.json version: 0.4.0
Lovelace card version: 0.4.0
GitHub Release: not published yet
```

Исторический anti-pattern из этой ветки: `v0.3.3` был помечен не на release commit с обновленными файлами, поэтому HACS мог установить старую сборку под новым именем. Перед следующим выпуском обязательно проверять не только имя tag/release, но и commit, на который указывает tag.

## 23.2 Release checklist для реализации этой спеки

Перед публикацией dispatcher release:

- выбрать новый SemVer-like version, например `0.4.0` для dispatcher/status изменения;
- обновить `custom_components/ir_learning_hub/manifest.json`;
- обновить `IR_LEARNING_HUB_CARD_VERSION` в `custom_components/ir_learning_hub/www/ir-learning-hub-card.js`, если менялся frontend или wording;
- обновить `CHANGELOG.md`, включая user-visible breaking/behavior changes;
- обновить README и `docs/INSTALLATION.md` так, чтобы они не называли новую
  версию HACS-installable до публикации GitHub Release; в момент публикации
  release tag и manifest examples должны совпадать с новой версией;
- убедиться, что `hacs.json` остается в корне repository и `hide_default_branch: true` не скрывает единственный installable target без release;
- recommended project convention: commit title уровня `Release vX.Y.Z`;
- создать и push tag `vX.Y.Z` на тот же commit, где уже обновлены manifest/card/docs/changelog;
- проверить локально `git log --oneline --decorate -n 3` или `git rev-list -n 1 vX.Y.Z`, что tag указывает на release commit;
- создать GitHub Release `vX.Y.Z` из этого tag, не draft, не prerelease для обычного стабильного выпуска;
- проверить GitHub API `/repos/slawa19/IR-Learning-Hub/releases/latest`: `tag_name`, `name`, `draft=false`, `prerelease=false`;
- после публикации обновить/перезагрузить HACS data и проверить, что HACS предлагает новый release, а не default branch или старый tag.

## 23.3 Acceptance criteria release

- At publication time, `manifest.json` version, card version, README examples,
  installation docs, changelog heading, git tag and GitHub Release all match.
- The tag resolves to the release metadata commit, not an older feature or previous-release commit.
- The latest GitHub Release exists; a local tag without GitHub Release is not considered released for HACS.
- HACS installs from the release tag and downloads files containing the same version advertised by the release.
