const IR_LEARNING_HUB_CARD_VERSION = "0.3.3";

class IRLearningHubCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._registry = { locations: {} };
    this._selLoc = "";
    this._selDev = "";
    this._expanded = {};      // loc_id → bool
    this._wizard = null;      // Active learn/save wizard state.
    this._wizardSeq = 0;
    this._currentCode = "";
    this._countdown = 0;
    this._countdownTimer = null;
    this._addForm = null;     // { type:"location"|"device", id, name }
    this._newCmd = null;      // { id, name, feature }
    this._menu = null;        // { kind:"loc"|"dev"|"cmd", locId, devId, cmdId }
    this._rename = null;      // { kind, locId, devId, cmdId, name }
    this._iconEdit = null;    // { locId, devId, cmdId, icon }
    this._panel = null;       // { mode:"export"|"import", text }
    this._busy = false;
    this._msg = "";
    this._err = "";
    this._lastStatus = undefined; // last status-entity state we rendered
    this._sendFeedbackTimers = new WeakMap();
  }

  setConfig(config) { this._config = config || {}; this._render(); }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;

    // HA reassigns `hass` on every global state change (several times per
    // second). Re-rendering the whole shadow DOM each time tears down the
    // element under the cursor, which causes hover flicker, dropped clicks,
    // and lost input focus. Only re-render when something we actually display
    // (the status entity) changed; every other update is user-driven and
    // already calls _render() explicitly.
    const statusEntity =
      this._config.status_entity || "sensor.ir_learning_hub_status";
    const status = hass?.states?.[statusEntity]?.state;

    if (first) {
      this._lastStatus = status;
      this._loadRegistry();
      return;
    }
    if (status !== this._lastStatus) {
      this._lastStatus = status;
      this._updateStatusIndicator(status);
    }
  }

  getCardSize() { return 8; }

  disconnectedCallback() {
    this._wizardSeq++;
    clearInterval(this._countdownTimer);
    this._countdownTimer = null;
  }

  _statusDotClass(state) {
    return {
      idle: "dot-idle",
      learning: "dot-busy",
      sending: "dot-busy",
      code_received: "dot-ok",
      error: "dot-err",
    }[state] || "dot-idle";
  }

  _updateStatusIndicator(state) {
    const dot = this.shadowRoot?.querySelector("[data-status-dot]");
    if (!dot) return;
    const label = `${this._t("status")}: ${state || "idle"}`;
    dot.className = `status-dot ${this._statusDotClass(state || "idle")}`;
    dot.title = label;
    dot.setAttribute("aria-label", label);
  }

  _x(v) {
    return String(v ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  _slugify(v) {
    const ru = {
      а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh",
      з: "z", и: "i", й: "y", к: "k", л: "l", м: "m", н: "n", о: "o",
      п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "ts",
      ч: "ch", ш: "sh", щ: "sch", ъ: "", ы: "y", ь: "", э: "e", ю: "yu",
      я: "ya", є: "ye", і: "i", ї: "yi", ґ: "g",
    };
    return String(v ?? "")
      .trim()
      .toLowerCase()
      .replace(/\+/g, " plus ")
      .replace(/&/g, " and ")
      .split("")
      .map(ch => ru[ch] ?? ch)
      .join("")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/_+/g, "_")
      .replace(/^_+|_+$/g, "");
  }

  _isValidId(v) {
    return /^[a-z0-9_]+$/.test(String(v || ""));
  }

  _featureOptions() {
    return [
      ["", this._t("featureNone")],
      ["power_on", this._t("featurePowerOn")],
      ["power_off", this._t("featurePowerOff")],
      ["power_toggle", this._t("featurePowerToggle")],
      ["play", this._t("featurePlay")],
      ["pause", this._t("featurePause")],
      ["play_pause_toggle", this._t("featurePlayPauseToggle")],
      ["stop", this._t("featureStop")],
      ["next", this._t("featureNext")],
      ["previous", this._t("featurePrevious")],
      ["fast_forward", this._t("featureFastForward")],
      ["rewind", this._t("featureRewind")],
      ["volume_up", this._t("featureVolumeUp")],
      ["volume_down", this._t("featureVolumeDown")],
      ["mute", this._t("featureMute")],
      ["unmute", this._t("featureUnmute")],
      ["mute_toggle", this._t("featureMuteToggle")],
      ["source", this._t("featureSource")],
    ];
  }

  _featureSelect(value, attr) {
    return `
      <select class="fi" ${attr}>
        ${this._featureOptions().map(([v, label]) => `
          <option value="${this._x(v)}"${v === (value || "") ? " selected" : ""}>${this._x(label)}</option>
        `).join("")}
      </select>`;
  }

  _t(key, vars = {}) {
    const lang = (this._hass?.locale?.language || "en").split("-")[0];
    const value = TRANSLATIONS[lang]?.[key] || TRANSLATIONS.en[key] || key;
    return value.replace(/\{(\w+)\}/g, (_, name) => vars[name] ?? "");
  }

  // ── Services ──────────────────────────────────────────────────────────────

  async _call(service, data = {}, response = false) {
    if (!this._hass) return null;
    if (this._config.transmitter_id)
      data = { transmitter_id: this._config.transmitter_id, ...data };
    if (!response)
      return this._hass.callService("ir_learning_hub", service, data);
    return this._hass.callWS({
      type: "call_service", domain: "ir_learning_hub",
      service, service_data: data, return_response: response,
    });
  }

  async _run(fn) {
    this._busy = true; this._msg = ""; this._err = "";
    this._render();
    try { return await fn(); }
    catch (e) { this._err = this._errText(e); }
    finally { this._busy = false; this._render(); }
  }

  _errText(e) {
    return e?.message || e?.body?.message || e?.error || String(e);
  }

  // ── Registry ──────────────────────────────────────────────────────────────

  async _loadRegistry() {
    try {
      const r = await this._call("list_commands", {}, true);
      this._registry = r?.response || r || { locations: {} };
      this._syncSel();
    } catch (e) {
      this._err = this._errText(e);
    }
    this._render();
  }

  _syncSel() {
    const locs = this._registry.locations || {};
    if (!locs[this._selLoc]) {
      this._selLoc = Object.keys(locs)[0] || "";
      this._selDev = "";
    }
    if (this._selLoc) this._expanded[this._selLoc] = true;
    if (!((locs[this._selLoc]?.devices) || {})[this._selDev])
      this._selDev = "";
  }

  _loc() { return (this._registry.locations || {})[this._selLoc]; }
  _dev() { return (this._loc()?.devices || {})[this._selDev]; }
  _cmds() { return this._dev()?.commands || {}; }
  _registryTransmitters() { return this._registry.transmitters || []; }

  _showTransmitterPicker(dev) {
    const transmitters = this._registryTransmitters();
    return transmitters.length > 1 || !!dev?.transmitter_id;
  }

  _transmitterSelect(value) {
    return `
      <select class="fi" data-device-transmitter>
        <option value="">${this._x(this._t("transmitterAuto"))}</option>
        ${this._registryTransmitters().map((tx) => `
          <option value="${this._x(tx.key)}"${tx.key === (value || "") ? " selected" : ""}>
            ${this._x(tx.name || tx.entity_id || tx.key)}
          </option>
        `).join("")}
      </select>`;
  }

  // ── Add forms ─────────────────────────────────────────────────────────────

  async _submitAdd() {
    const f = this._addForm;
    if (!f?.id.trim()) { this._err = this._t("idRequired"); this._render(); return; }
    await this._run(async () => {
      if (f.type === "location") {
        await this._call("add_location", {
          location_id: f.id.trim(), name: f.name.trim() || f.id.trim(),
        });
        this._selLoc = f.id.trim();
        this._expanded[f.id.trim()] = true;
        await this._loadRegistry();
      } else {
        await this._call("add_device", {
          location_id: this._selLoc, ir_device_id: f.id.trim(),
          name: f.name.trim() || f.id.trim(), type: "generic",
        });
        this._selDev = f.id.trim();
        await this._loadRegistry();
      }
      this._addForm = null;
      this._msg = this._t("saved");
    });
  }

  // ── Wizard ────────────────────────────────────────────────────────────────

  _startWizard(cmdId, cmdName, cmdFeature = "") {
    const seq = ++this._wizardSeq;
    this._wizard = {
      step: 1,
      seq,
      locationId: this._selLoc,
      irDeviceId: this._selDev,
      cmdId,
      cmdName,
      cmdFeature,
      tested: false,
    };
    this._currentCode = ""; this._err = ""; this._msg = "";
    this._countdown = this._config.timeout || 60;
    clearInterval(this._countdownTimer);
    this._countdownTimer = null;
    this._countdownTimer = setInterval(() => {
      this._countdown = Math.max(0, this._countdown - 1);
      this._render();
    }, 1000);
    this._render();
    this._doLearnAndRead(seq);
  }

  async _doLearnAndRead(seq) {
    try {
      const r = await this._call("learn_and_read", {
        timeout: this._config.timeout || 60,
        poll_interval: this._config.poll_interval || 2,
      }, true);
      if (!this._wizard || this._wizard.seq !== seq) return;
      clearInterval(this._countdownTimer);
      this._countdownTimer = null;
      const code = r?.response?.code || r?.code || "";
      if (code) {
        this._currentCode = code;
        this._wizard = { ...this._wizard, step: 2 };
      } else {
        this._err = this._t("codeNotReceived");
        this._wizard = null;
      }
    } catch (e) {
      if (!this._wizard || this._wizard.seq !== seq) return;
      clearInterval(this._countdownTimer);
      this._countdownTimer = null;
      this._err = this._errText(e);
      this._wizard = null;
    }
    this._render();
  }

  async _testCode() {
    const seq = this._wizard?.seq;
    await this._run(async () => {
      await this._call("test_code", { code: this._currentCode });
      if (!this._wizard || this._wizard.seq !== seq) return;
      this._wizard = { ...this._wizard, step: 3, tested: true };
      this._msg = this._t("sentToDevice");
    });
  }

  async _saveCode() {
    const w = this._wizard;
    await this._run(async () => {
      await this._call("save_command", {
        location_id: w.locationId,
        ir_device_id: w.irDeviceId,
        command_id: w.cmdId,
        name: w.cmdName,
        code: this._currentCode,
        verified: w.tested,
        feature: w.cmdFeature || "",
      });
      await this._loadRegistry();
      this._wizard = null;
      this._newCmd = null;
      this._msg = this._t("commandSaved");
    });
  }

  _cancelWizard() {
    this._wizardSeq++;
    clearInterval(this._countdownTimer);
    this._countdownTimer = null;
    this._wizard = null;
    this._render();
  }

  // ── Send ──────────────────────────────────────────────────────────────────

  async _send(cmdId) {
    let button = null;
    if (arguments.length > 1) button = arguments[1];
    const cmd = this._cmds()[cmdId];
    if (cmd?.verified === false && !confirm(this._t("confirmUnverified", { name: cmd.name || cmdId }))) return;
    try {
      await this._call("send_command", {
        location_id: this._selLoc, ir_device_id: this._selDev, command_id: cmdId,
      });
      this._flashCommandSent(button);
    } catch (e) {
      this._err = this._errText(e);
      this._render();
    }
  }

  _flashCommandSent(button) {
    if (!button) return;
    const previous = this._sendFeedbackTimers.get(button);
    if (previous) clearTimeout(previous);
    button.classList.add("is-sent");
    const timer = setTimeout(() => {
      button.classList.remove("is-sent");
      this._sendFeedbackTimers.delete(button);
    }, 700);
    this._sendFeedbackTimers.set(button, timer);
  }

  // ── Render: sidebar ───────────────────────────────────────────────────────

  _renderSidebar() {
    const locs = this._registry.locations || {};
    let tree = "";

    for (const [locId, loc] of Object.entries(locs)) {
      const exp = this._expanded[locId] !== false;
      const devs = loc.devices || {};

      if (this._rename?.kind === "loc" && this._rename.locId === locId) {
        tree += `<div class="loc-row editing">${this._renameInput()}</div>`;
      } else {
        const menuOpen = this._menuOpen("loc", locId);
        tree += `
          <div class="loc-row${menuOpen ? " menu-open" : ""}">
            <span class="arrow" data-toggle="${this._x(locId)}">${exp ? "▾" : "▸"}</span>
            <span class="loc-name" data-toggle="${this._x(locId)}">${this._x(loc.name || locId)}</span>
            <button class="kebab" data-menu="loc" data-loc="${this._x(locId)}" title="${this._x(this._t("actions"))}" aria-label="${this._x(this._t("actions"))}">
              <ha-icon icon="mdi:dots-vertical"></ha-icon>
            </button>
          </div>`;
      }

      if (exp) {
        tree += `<div class="devs">`;
        for (const [dId, d] of Object.entries(devs)) {
          if (this._rename?.kind === "dev" && this._rename.locId === locId && this._rename.devId === dId) {
            tree += `<div class="dev editing">${this._renameInput()}</div>`;
            continue;
          }
          const sel = dId === this._selDev && locId === this._selLoc;
          const menuOpen = this._menuOpen("dev", locId, dId);
          tree += `
            <div class="dev${sel ? " sel" : ""}${menuOpen ? " menu-open" : ""}">
              <span class="dev-name" data-sel="${this._x(locId)}||${this._x(dId)}">${this._x(d.name || dId)}</span>
              <button class="kebab" data-menu="dev" data-loc="${this._x(locId)}" data-dev="${this._x(dId)}" title="${this._x(this._t("actions"))}" aria-label="${this._x(this._t("actions"))}">
                <ha-icon icon="mdi:dots-vertical"></ha-icon>
              </button>
            </div>`;
        }
        if (this._addForm?.type === "device" && this._selLoc === locId) {
          tree += this._renderInlineForm();
        } else {
          tree += `
            <button class="text-action" data-add-dev="${this._x(locId)}">
              <ha-icon icon="mdi:plus"></ha-icon>
              <span>${this._x(this._t("addDevice"))}</span>
            </button>`;
        }
        tree += `</div>`;
      }
    }

    if (this._addForm?.type === "location") {
      tree += this._renderInlineForm();
    } else {
      tree += `
        <button class="text-action loc-link" data-act="showAddLoc">
          <ha-icon icon="mdi:plus"></ha-icon>
          <span>${this._x(this._t("addLocation"))}</span>
        </button>`;
    }

    return tree;
  }

  // ── Menus, rename, icon helpers ───────────────────────────────────────────

  _menuOpen(kind, locId, devId, cmdId) {
    const m = this._menu;
    return !!m && m.kind === kind && m.locId === locId
      && (devId === undefined || m.devId === devId)
      && (cmdId === undefined || m.cmdId === cmdId);
  }

  _menuItems(m) {
    if (m.kind === "loc")
      return [
        ["rename", "mdi:pencil", this._t("rename")],
        ["delete", "mdi:delete", this._t("delete"), true],
      ];
    if (m.kind === "dev")
      return [
        ["rename", "mdi:pencil", this._t("rename")],
        ["export", "mdi:content-copy", this._t("exportProfile")],
        ["import", "mdi:tray-arrow-down", this._t("importProfile")],
        ["delete", "mdi:delete", this._t("delete"), true],
      ];
    return [
      ["relearn", "mdi:backup-restore", this._t("relearn")],
      ["rename", "mdi:pencil", this._t("rename")],
      ["icon", "mdi:shape-outline", this._t("iconLabel")],
      ["delete", "mdi:delete", this._t("delete"), true],
    ];
  }

  _dropdown(items, attrs = "") {
    return `<div class="menu" ${attrs}>${items.map(([act, icon, label, danger]) => `
      <button class="menu-item${danger ? " danger" : ""}" data-mact="${act}">
        <ha-icon icon="${icon}"></ha-icon><span>${this._x(label)}</span>
      </button>`).join("")}</div>`;
  }

  _renderMenuOverlay() {
    if (!this._menu) return "";
    const left = Number.isFinite(this._menu.left) ? this._menu.left : 8;
    const top = Number.isFinite(this._menu.top) ? this._menu.top : 40;
    return this._dropdown(
      this._menuItems(this._menu),
      `style="left:${left}px;top:${top}px"`
    );
  }

  _renameInput() {
    return `
      <input class="fi rename-fi" data-rename-input value="${this._x(this._rename.name)}" />
      <button class="kebab-btn ok" data-act="renameSave" title="${this._x(this._t("save"))}" aria-label="${this._x(this._t("save"))}">
        <ha-icon icon="mdi:check"></ha-icon>
      </button>
      <button class="kebab-btn" data-act="renameCancel" title="${this._x(this._t("cancel"))}" aria-label="${this._x(this._t("cancel"))}">
        <ha-icon icon="mdi:close"></ha-icon>
      </button>`;
  }

  _closeEditors() {
    this._menu = null;
    this._rename = null;
    this._iconEdit = null;
    this._panel = null;
  }

  _nameOf(m) {
    const loc = (this._registry.locations || {})[m.locId];
    if (m.kind === "loc") return loc?.name || m.locId;
    const dev = (loc?.devices || {})[m.devId];
    if (m.kind === "dev") return dev?.name || m.devId;
    return (dev?.commands || {})[m.cmdId]?.name || m.cmdId;
  }

  _suggestIcons(name) {
    const n = (name || "").toLowerCase();
    const rules = [
      [/(вкл|вык|пита|on\s*\/?\s*off|power|живл)/, "mdi:power"],
      [/(play|воспро|відтвор|пуск|играть)/, "mdi:play"],
      [/(pause|пауза)/, "mdi:pause"],
      [/(stop|стоп|зупин)/, "mdi:stop"],
      [/(forward|next|вперёд|вперед|вперёд|перемот.*впер|fwd|>>)/, "mdi:skip-next"],
      [/(backward|back|rewind|назад|перемот.*наз|<<)/, "mdi:skip-previous"],
      [/(eject|open|close|откр|закр|відкр|tray|лоток)/, "mdi:eject"],
      [/(vol.*\+|громч|гучн|volume up|vol up)/, "mdi:volume-plus"],
      [/(vol.*-|тиш|тих|volume down|vol down)/, "mdi:volume-minus"],
      [/(mute|без звук|тиша)/, "mdi:volume-mute"],
      [/(menu|меню)/, "mdi:menu"],
      [/(home|домой|додом)/, "mdi:home"],
      [/(ok|enter|ввод|select|вибр)/, "mdi:circle-slice-8"],
      [/(up|вверх|вгору)/, "mdi:chevron-up"],
      [/(down|вниз)/, "mdi:chevron-down"],
      [/(left|влев|ліво)/, "mdi:chevron-left"],
      [/(right|вправ|право)/, "mdi:chevron-right"],
      [/(channel|канал|ch)/, "mdi:television"],
      [/(record|запис|rec)/, "mdi:record-circle"],
      [/(light|свет|світл|ламп)/, "mdi:lightbulb"],
      [/(temp|темпер|°|град)/, "mdi:thermometer"],
      [/(fan|вентил|обдув)/, "mdi:fan"],
      [/(mode|режим)/, "mdi:tune"],
      [/(timer|таймер)/, "mdi:timer-outline"],
    ];
    const out = [];
    for (const [re, icon] of rules)
      if (re.test(n) && !out.includes(icon)) out.push(icon);
    for (const g of ["mdi:remote", "mdi:gesture-tap-button", "mdi:power", "mdi:play", "mdi:cog"])
      if (!out.includes(g)) out.push(g);
    return out.slice(0, 6);
  }

  _renderInlineForm() {
    const f = this._addForm;
    return `
      <div class="inline-form">
        <div class="cform">
          <input class="fi" data-ff="name" value="${this._x(f.name)}" placeholder="${this._x(this._t("name"))}" />
          <div class="field-row">
            <input class="fi" data-ff="id" value="${this._x(f.id)}" placeholder="${this._x(this._t("idPlaceholder"))}" aria-describedby="add-id-helper" />
            <span class="field-hint" id="add-id-helper" title="${this._x(this._t("idHelper"))}" aria-label="${this._x(this._t("idHelper"))}" role="img">
              <ha-icon icon="mdi:help-circle-outline"></ha-icon>
            </span>
          </div>
        </div>
        <div class="form-row">
          <button class="btn p icon-only" data-act="submitAdd" ${this._busy ? "disabled" : ""} title="${this._x(this._t("add"))}" aria-label="${this._x(this._t("add"))}">
            <ha-icon icon="mdi:check"></ha-icon>
          </button>
          <button class="btn icon-only" data-act="cancelAdd" title="${this._x(this._t("cancel"))}" aria-label="${this._x(this._t("cancel"))}">
            <ha-icon icon="mdi:close"></ha-icon>
          </button>
        </div>
      </div>`;
  }

  // ── Render: right panel ───────────────────────────────────────────────────

  _renderMain() {
    if (this._wizard) return this._renderWizard();

    // Icon/profile panels are opened from per-item menus and act on their own
    // device context, so they render regardless of the current sidebar selection.
    if (this._iconEdit) return this._panelHead(this._iconEdit) + this._renderIconPanel();
    if (this._panel) return this._panelHead(this._panel) + this._renderProfilePanel();

    if (!this._selDev) {
      return `<div class="empty">${this._x(this._t("selectDevice"))}<br><span class="hint">${this._x(this._t("orCreateNew"))}</span></div>`;
    }

    const dev = this._dev();
    const head = `<div class="remote-head">${this._x(dev?.name || this._selDev)}</div>`;
    const settings = this._showTransmitterPicker(dev) ? `
      <div class="device-settings">
        <div class="panel-title">${this._x(this._t("transmitterLabel"))}</div>
        <div class="device-settings-row">
          ${this._transmitterSelect(dev?.transmitter_id || "")}
          <button class="btn p icon-only" data-act="saveDeviceTransmitter" ${this._busy ? "disabled" : ""} title="${this._x(this._t("save"))}" aria-label="${this._x(this._t("save"))}">
            <ha-icon icon="mdi:check"></ha-icon>
          </button>
        </div>
      </div>` : "";

    const cmds = this._cmds();
    const cmdEntries = Object.entries(cmds);

    const grid = cmdEntries.length
      ? cmdEntries.map(([id, cmd]) => {
          if (this._rename?.kind === "cmd" && this._rename.cmdId === id)
            return `<div class="cmd-card editing">${this._renameInput()}</div>`;
          const unv = cmd.verified === false;
          const menuOpen = this._menuOpen("cmd", this._selLoc, this._selDev, id);
          const baseIcon = cmd.icon || "mdi:circle-medium";
          return `
            <div class="cmd-card${unv ? " unv" : ""}${menuOpen ? " menu-open" : ""}">
              <button class="cmd-send" data-send="${this._x(id)}" title="${this._x(this._t("send"))}">
                <span class="cmd-icon-stack${cmd.icon ? "" : " no-icon"}" aria-hidden="true">
                  <ha-icon class="cmd-icon cmd-icon-base" icon="${this._x(baseIcon)}"></ha-icon>
                  <ha-icon class="cmd-icon cmd-icon-sent" icon="mdi:access-point"></ha-icon>
                </span>
                <span class="cmd-name">${this._x(cmd.name || id)}</span>
              </button>
              <button class="kebab on-tile" data-menu="cmd" data-loc="${this._x(this._selLoc)}" data-dev="${this._x(this._selDev)}" data-cmd="${this._x(id)}" title="${this._x(this._t("actions"))}" aria-label="${this._x(this._t("actions"))}">
                <ha-icon icon="mdi:dots-vertical"></ha-icon>
              </button>
            </div>`;
        }).join("")
      : `<div class="empty-cmds">${this._x(this._t("noCommands"))}</div>`;

    const footer = this._newCmd !== null
      ? `<div class="new-cmd-form">
          <div class="new-cmd-title">${this._x(this._t("newCommand"))}</div>
          <div class="cform">
            <input class="fi" data-nc="name" value="${this._x(this._newCmd.name)}" placeholder="${this._x(this._t("name"))}" />
            <div class="field-row">
              <input class="fi" data-nc="id" value="${this._x(this._newCmd.id)}" placeholder="${this._x(this._t("idPlaceholder"))}" aria-describedby="new-command-id-helper" />
              <span class="field-hint" id="new-command-id-helper" title="${this._x(this._t("idHelper"))}" aria-label="${this._x(this._t("idHelper"))}" role="img">
                <ha-icon icon="mdi:help-circle-outline"></ha-icon>
              </span>
            </div>
            ${this._featureSelect(this._newCmd.feature || "", "data-nc=\"feature\"")}
          </div>
          <div class="form-row">
            <button class="btn p icon-only" data-act="startLearnNew" ${this._busy ? "disabled" : ""} title="${this._x(this._t("learn"))}" aria-label="${this._x(this._t("learn"))}">
              <ha-icon icon="mdi:record-circle-outline"></ha-icon>
            </button>
            <button class="btn icon-only" data-act="cancelNewCmd" title="${this._x(this._t("cancel"))}" aria-label="${this._x(this._t("cancel"))}">
              <ha-icon icon="mdi:close"></ha-icon>
            </button>
          </div>
        </div>`
      : `<button class="btn add-cmd-btn" data-act="showNewCmd">
          <ha-icon icon="mdi:plus"></ha-icon>
          <span>${this._x(this._t("addCommand"))}</span>
        </button>`;

    return `
      ${head}
      ${settings}
      <div class="cmd-grid">${grid}</div>
      <div class="remote-foot">${footer}</div>`;
  }

  _deviceOf(ctx) {
    const loc = (this._registry.locations || {})[ctx.locId] || {};
    return (loc.devices || {})[ctx.devId] || {};
  }

  _panelHead(ctx) {
    const dev = this._deviceOf(ctx);
    return `<div class="remote-head">${this._x(dev.name || ctx.devId || this._selDev)}</div>`;
  }

  _renderIconPanel() {
    const e = this._iconEdit;
    const cmd = (this._deviceOf(e).commands || {})[e.cmdId] || {};
    const chips = this._suggestIcons(cmd.name || e.cmdId).map(ic => `
      <button class="chip${e.icon === ic ? " sel" : ""}" data-act="pickIcon" data-icon="${this._x(ic)}" title="${this._x(ic)}">
        <ha-icon icon="${this._x(ic)}"></ha-icon>
      </button>`).join("");
    return `
      <div class="panel">
        <div class="panel-title">${this._x(this._t("chooseIcon"))} · ${this._x(cmd.name || e.cmdId)}</div>
        <div class="chips">${chips}</div>
        <div class="panel-title">${this._x(this._t("featureLabel"))}</div>
        ${this._featureSelect(e.feature || "", "data-feature-input")}
        <div class="field-row">
          <span class="icon-preview" data-icon-preview><ha-icon icon="${this._x(e.icon || "mdi:remote")}"></ha-icon></span>
          <input class="fi" data-icon-input value="${this._x(e.icon)}" placeholder="mdi:play" />
        </div>
        <div class="form-row">
          <button class="btn p icon-only" data-act="saveIcon" ${this._busy ? "disabled" : ""} title="${this._x(this._t("save"))}" aria-label="${this._x(this._t("save"))}">
            <ha-icon icon="mdi:check"></ha-icon>
          </button>
          <button class="btn icon-only" data-act="clearIcon" ${this._busy ? "disabled" : ""} title="${this._x(this._t("clearIcon"))}" aria-label="${this._x(this._t("clearIcon"))}">
            <ha-icon icon="mdi:eraser-variant"></ha-icon>
          </button>
          <button class="btn icon-only" data-act="cancelPanel" title="${this._x(this._t("cancel"))}" aria-label="${this._x(this._t("cancel"))}">
            <ha-icon icon="mdi:close"></ha-icon>
          </button>
        </div>
      </div>`;
  }

  _renderProfilePanel() {
    const p = this._panel;
    const isExport = p.mode === "export";
    return `
      <div class="panel">
        <div class="panel-title">${this._x(isExport ? this._t("exportProfile") : this._t("importProfile"))}</div>
        <div class="panel-hint">${this._x(isExport ? this._t("exportHint") : this._t("importHint"))}</div>
        <textarea class="ta" data-panel-text wrap="off" ${isExport ? "readonly" : ""} placeholder="${isExport ? "" : this._x(this._t("pasteJson"))}">${this._x(p.text)}</textarea>
        <div class="form-row">
          ${isExport ? `
            <button class="btn p icon-only" data-act="copyProfile" title="${this._x(this._t("copy"))}" aria-label="${this._x(this._t("copy"))}"><ha-icon icon="mdi:content-copy"></ha-icon></button>
            <button class="btn icon-only" data-act="downloadProfile" title="${this._x(this._t("download"))}" aria-label="${this._x(this._t("download"))}"><ha-icon icon="mdi:download"></ha-icon></button>
          ` : `
            <button class="btn p icon-only" data-act="runImport" ${this._busy ? "disabled" : ""} title="${this._x(this._t("import"))}" aria-label="${this._x(this._t("import"))}"><ha-icon icon="mdi:tray-arrow-down"></ha-icon></button>
          `}
          <button class="btn icon-only" data-act="cancelPanel" title="${this._x(this._t("cancel"))}" aria-label="${this._x(this._t("cancel"))}">
            <ha-icon icon="mdi:close"></ha-icon>
          </button>
        </div>
      </div>`;
  }

  // ── Actions: rename / delete / icon / profile ─────────────────────────────

  _openMenu(ds, trigger) {
    this._closeEditors();
    const cardRect = this.shadowRoot.querySelector("ha-card")?.getBoundingClientRect();
    const triggerRect = trigger?.getBoundingClientRect();
    const menuWidth = 180;
    let left = 8;
    let top = 40;
    if (cardRect && triggerRect) {
      left = Math.max(
        8,
        Math.min(
          triggerRect.right - cardRect.left - menuWidth,
          cardRect.width - menuWidth - 8
        )
      );
      top = triggerRect.bottom - cardRect.top + 4;
    }
    this._menu = {
      kind: ds.menu,
      locId: ds.loc,
      devId: ds.dev,
      cmdId: ds.cmd,
      left,
      top,
    };
    this._render();
  }

  _runMenuAction(act) {
    const m = this._menu;
    this._menu = null;
    if (!m) return;
    if (act === "rename") {
      this._rename = { kind: m.kind, locId: m.locId, devId: m.devId, cmdId: m.cmdId, name: this._nameOf(m) };
      this._render();
    } else if (act === "delete") {
      this._doDelete(m);
    } else if (act === "relearn") {
      const cmd = this._cmds()[m.cmdId] || {};
      const cmdName = cmd.name || m.cmdId;
      this._render();
      this._startWizard(m.cmdId, cmdName, cmd.feature || "");
    } else if (act === "icon") {
      const cmd = this._cmds()[m.cmdId] || {};
      this._iconEdit = {
        locId: m.locId,
        devId: m.devId,
        cmdId: m.cmdId,
        icon: cmd.icon || "",
        feature: cmd.feature || "",
      };
      this._render();
    } else if (act === "export") {
      this._selLoc = m.locId; this._selDev = m.devId; this._expanded[m.locId] = true;
      this._exportProfile(m);
    } else if (act === "import") {
      this._selLoc = m.locId; this._selDev = m.devId; this._expanded[m.locId] = true;
      this._panel = { mode: "import", text: "", locId: m.locId, devId: m.devId };
      this._render();
    }
  }

  async _renameSave() {
    const r = this._rename;
    const name = (r?.name || "").trim();
    if (!r || !name) { this._rename = null; this._render(); return; }
    await this._run(async () => {
      if (r.kind === "loc")
        await this._call("rename_location", { location_id: r.locId, name });
      else if (r.kind === "dev")
        await this._call("rename_device", { location_id: r.locId, ir_device_id: r.devId, name });
      else
        await this._call("rename_command", { location_id: r.locId, ir_device_id: r.devId, command_id: r.cmdId, name });
      this._rename = null;
      await this._loadRegistry();
      this._msg = this._t("saved");
    });
  }

  async _doDelete(m) {
    if (!confirm(this._t("confirmDelete", { name: this._nameOf(m) }))) return;
    await this._run(async () => {
      if (m.kind === "loc") {
        await this._call("delete_location", { location_id: m.locId, confirm: true });
        if (this._selLoc === m.locId) { this._selLoc = ""; this._selDev = ""; }
      } else if (m.kind === "dev") {
        await this._call("delete_device", { location_id: m.locId, ir_device_id: m.devId, confirm: true });
        if (this._selDev === m.devId) this._selDev = "";
      } else {
        await this._call("delete_command", { location_id: m.locId, ir_device_id: m.devId, command_id: m.cmdId });
      }
      await this._loadRegistry();
      this._msg = this._t("deleted");
    });
  }

  async _saveIcon() {
    const e = this._iconEdit;
    if (!e) return;
    await this._run(async () => {
      await this._call("update_command", {
        location_id: e.locId, ir_device_id: e.devId, command_id: e.cmdId,
        icon: (e.icon || "").trim(),
        feature: e.feature || "",
      });
      this._iconEdit = null;
      await this._loadRegistry();
      this._msg = this._t("saved");
    });
  }

  _exportProfile(m) {
    const loc = (this._registry.locations || {})[m.locId] || {};
    const dev = (loc.devices || {})[m.devId] || {};
    const profile = {
      _profile: "ir_learning_hub",
      version: 1,
      name: dev.name || m.devId,
      type: dev.type || "generic",
      commands: dev.commands || {},
    };
    this._panel = { mode: "export", text: JSON.stringify(profile, null, 2), locId: m.locId, devId: m.devId };
    this._render();
  }

  async _copyProfile() {
    const textarea = this.shadowRoot.querySelector("[data-panel-text]");
    const text = textarea?.value || this._panel?.text || "";
    try {
      if (navigator.clipboard?.writeText && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        if (!textarea) throw new Error("Clipboard text is not available");
        textarea.focus();
        textarea.select();
        textarea.setSelectionRange(0, textarea.value.length);
        if (!document.execCommand("copy")) {
          throw new Error("Copy command was rejected");
        }
        textarea.setSelectionRange(0, 0);
        textarea.blur();
      }
      this._msg = this._t("copied"); this._render();
    } catch (e) {
      this._err = this._errText(e); this._render();
    }
  }

  _downloadProfile() {
    const blob = new Blob([this._panel?.text || ""], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${this._panel?.devId || this._selDev || "profile"}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  async _runImport() {
    const raw = this.shadowRoot.querySelector("[data-panel-text]")?.value || this._panel?.text || "";
    let data;
    try {
      data = JSON.parse(raw);
    } catch (e) {
      this._err = this._t("invalidJson"); this._render(); return;
    }
    const commands = data?.commands || (data?._profile ? {} : data);
    const entries = Object.entries(commands || {}).filter(([, cmd]) => cmd?.code);
    if (!entries.length) { this._err = this._t("noCommandsInJson"); this._render(); return; }
    const invalid = entries.find(([cmdId]) => !this._isValidId(cmdId));
    if (invalid) {
      this._err = this._t("invalidCommandId", { id: invalid[0] });
      this._render();
      return;
    }
    const locId = this._panel?.locId || this._selLoc;
    const devId = this._panel?.devId || this._selDev;
    await this._run(async () => {
      let count = 0;
      for (const [cmdId, cmd] of entries) {
        const payload = {
          location_id: locId,
          ir_device_id: devId,
          command_id: cmdId,
          name: cmd.name || cmdId,
          code: cmd.code,
          verified: cmd.verified !== false,
        };
        if (cmd.source && typeof cmd.source === "object" && !Array.isArray(cmd.source))
          payload.source = cmd.source;
        if (typeof cmd.feature === "string")
          payload.feature = cmd.feature;
        await this._call("save_command", payload);
        // Only carry icons the backend will accept, so one malformed icon in a
        // hand-edited profile does not abort the rest of the import.
        const icon = typeof cmd.icon === "string" && cmd.icon.startsWith("mdi:") ? cmd.icon : "";
        if (icon)
          await this._call("update_command", {
            location_id: locId, ir_device_id: devId,
            command_id: cmdId, icon,
          });
        count++;
      }
      this._panel = null;
      await this._loadRegistry();
      this._msg = this._t("imported", { count: String(count) });
    });
  }

  async _saveDeviceTransmitter() {
    const select = this.shadowRoot.querySelector("[data-device-transmitter]");
    if (!select) return;
    await this._run(async () => {
      await this._call("update_device", {
        location_id: this._selLoc,
        ir_device_id: this._selDev,
        transmitter_id: select.value,
      });
      await this._loadRegistry();
      this._msg = this._t("saved");
    });
  }

  _renderWizard() {
    const w = this._wizard;
    const timeout = this._config.timeout || 60;

    if (w.step === 1) {
      const pct = Math.round(((timeout - this._countdown) / timeout) * 100);
      return `
        <div class="wizard">
          <div class="w-steps"><span class="w-step active"></span><span class="w-step"></span><span class="w-step"></span></div>
          <div class="w-label">${this._x(this._t("stepRecord"))}</div>
          <div class="w-title">${this._x(this._t("pointRemote"))}</div>
          <div class="w-hint">${this._x(this._t("pressButtonPrefix"))} <strong>${this._x(w.cmdName)}</strong></div>
          <div class="w-progress"><div class="w-bar" style="width:${pct}%"></div></div>
          <div class="w-countdown">${this._countdown}${this._x(this._t("secondsShort"))}</div>
          <button class="btn icon-only" data-act="cancelWizard" title="${this._x(this._t("cancel"))}" aria-label="${this._x(this._t("cancel"))}">
            <ha-icon icon="mdi:close"></ha-icon>
          </button>
        </div>`;
    }

    if (w.step === 2) {
      return `
        <div class="wizard">
          <div class="w-steps"><span class="w-step done"></span><span class="w-step active"></span><span class="w-step"></span></div>
          <div class="w-label">${this._x(this._t("stepTest"))}</div>
          <div class="w-title">${this._x(this._t("codeReceived"))}</div>
          <div class="w-hint">${this._x(this._t("testHint"))}</div>
          <div class="w-actions">
            <button class="btn p" data-act="testCode" ${this._busy ? "disabled" : ""}>
              <ha-icon icon="mdi:send"></ha-icon>
              <span>${this._x(this._busy ? this._t("sending") : this._t("test"))}</span>
            </button>
            <button class="btn" data-act="skipSave" ${this._busy ? "disabled" : ""}>
              <span>${this._x(this._t("skip"))}</span>
              <ha-icon icon="mdi:chevron-right"></ha-icon>
            </button>
          </div>
          <button class="btn icon-only sm" data-act="cancelWizard" title="${this._x(this._t("cancel"))}" aria-label="${this._x(this._t("cancel"))}">
            <ha-icon icon="mdi:close"></ha-icon>
          </button>
        </div>`;
    }

    if (w.step === 3) {
      return `
        <div class="wizard">
          <div class="w-steps"><span class="w-step done"></span><span class="w-step done"></span><span class="w-step active"></span></div>
          <div class="w-label">${this._x(this._t("stepSave"))}</div>
          <div class="w-title">${this._x(w.tested ? this._t("tested") : this._t("notTested"))}</div>
          <div class="wizard-field">
            <input class="w-name-input" data-wname value="${this._x(w.cmdName)}" placeholder="${this._x(this._t("commandName"))}" />
            ${this._featureSelect(w.cmdFeature || "", "data-wfeature")}
          </div>
          <div class="w-actions">
            <button class="btn p" data-act="saveCode" ${this._busy ? "disabled" : ""}>
              <ha-icon icon="mdi:content-save"></ha-icon>
              <span>${this._x(this._busy ? this._t("saving") : this._t("save"))}</span>
            </button>
            <button class="btn icon-only" data-act="cancelWizard" ${this._busy ? "disabled" : ""} title="${this._x(this._t("cancel"))}" aria-label="${this._x(this._t("cancel"))}">
              <ha-icon icon="mdi:close"></ha-icon>
            </button>
          </div>
        </div>`;
    }
  }

  // ── Render: full card ─────────────────────────────────────────────────────

  _render() {
    if (!this.shadowRoot) return;

    const statusEntity = this._config.status_entity || "sensor.ir_learning_hub_status";
    const state = this._hass?.states?.[statusEntity]?.state || "idle";
    const dotClass = this._statusDotClass(state);

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        <div class="header">
          <img class="brand-icon" src="/ir_learning_hub/icon.png" alt="" />
          <span class="title">${this._x(this._config.title || "IR Learning Hub")}</span>
          <span class="status-dot ${dotClass}" data-status-dot title="${this._x(this._t("status"))}: ${this._x(state)}" aria-label="${this._x(this._t("status"))}: ${this._x(state)}" role="status"></span>
        </div>
        <div class="body">
          <div class="sidebar">${this._renderSidebar()}</div>
          <div class="main">
            ${this._renderMain()}
            ${this._err ? `<div class="toast err">${this._x(this._err)}</div>` : ""}
            ${this._msg && !this._err ? `<div class="toast ok">${this._x(this._msg)}</div>` : ""}
          </div>
        </div>
        ${this._menu ? `<div class="scrim" data-act="closeMenus"></div>${this._renderMenuOverlay()}` : ""}
      </ha-card>`;

    this._bind();
  }

  // ── Events ────────────────────────────────────────────────────────────────

  _bind() {
    const root = this.shadowRoot;

    root.querySelectorAll("[data-toggle]").forEach(el =>
      el.addEventListener("click", () => {
        const id = el.dataset.toggle;
        this._expanded[id] = this._expanded[id] === false;
        this._menu = null;
        this._render();
      })
    );

    root.querySelectorAll("[data-sel]").forEach(el =>
      el.addEventListener("click", () => {
        const [locId, devId] = el.dataset.sel.split("||");
        this._selLoc = locId; this._selDev = devId;
        this._expanded[locId] = true;
        this._wizardSeq++;
        clearInterval(this._countdownTimer);
        this._countdownTimer = null;
        this._wizard = null; this._msg = ""; this._err = "";
        this._closeEditors();
        this._render();
      })
    );

    root.querySelectorAll("[data-add-dev]").forEach(el =>
      el.addEventListener("click", () => {
        this._selLoc = el.dataset.addDev;
        this._addForm = { type: "device", id: "", name: "", idTouched: false };
        this._render();
      })
    );

    root.querySelectorAll("[data-send]").forEach(el =>
      el.addEventListener("click", (event) => {
        const button = event.currentTarget?.closest(".cmd-send");
        this._send(el.dataset.send, button);
      })
    );

    root.querySelectorAll("[data-ff]").forEach(el =>
      el.addEventListener("input", () => {
        if (!this._addForm) return;
        const field = el.dataset.ff;
        this._addForm[field] = el.value;
        if (field === "id") this._addForm.idTouched = true;
        if (field === "name" && !this._addForm.idTouched) {
          this._addForm.id = this._slugify(el.value);
          const idInput = root.querySelector('[data-ff="id"]');
          if (idInput) idInput.value = this._addForm.id;
        }
      })
    );

    root.querySelectorAll("[data-nc]").forEach(el =>
      el.addEventListener("input", () => {
        if (!this._newCmd) return;
        const field = el.dataset.nc;
        this._newCmd[field] = el.value;
        if (field === "id") this._newCmd.idTouched = true;
        if (field === "name" && !this._newCmd.idTouched) {
          this._newCmd.id = this._slugify(el.value);
          const idInput = root.querySelector('[data-nc="id"]');
          if (idInput) idInput.value = this._newCmd.id;
        }
      })
    );

    const wname = root.querySelector("[data-wname]");
    if (wname) wname.addEventListener("input", () => {
      if (this._wizard) this._wizard = { ...this._wizard, cmdName: wname.value };
    });

    const wfeature = root.querySelector("[data-wfeature]");
    if (wfeature) wfeature.addEventListener("input", () => {
      if (this._wizard) this._wizard = { ...this._wizard, cmdFeature: wfeature.value };
    });

    root.querySelectorAll("[data-menu]").forEach(el =>
      el.addEventListener("click", (e) => { e.stopPropagation(); this._openMenu(el.dataset, el); })
    );

    root.querySelectorAll("[data-mact]").forEach(el =>
      el.addEventListener("click", (e) => { e.stopPropagation(); this._runMenuAction(el.dataset.mact); })
    );

    const rin = root.querySelector("[data-rename-input]");
    if (rin) {
      rin.focus();
      rin.addEventListener("input", () => { if (this._rename) this._rename.name = rin.value; });
      rin.addEventListener("keydown", (e) => {
        if (e.key === "Enter") this._renameSave();
        else if (e.key === "Escape") { this._rename = null; this._render(); }
      });
    }

    const iin = root.querySelector("[data-icon-input]");
    if (iin) iin.addEventListener("input", () => {
      if (!this._iconEdit) return;
      this._iconEdit.icon = iin.value;
      const prev = root.querySelector("[data-icon-preview] ha-icon");
      if (prev) prev.setAttribute("icon", iin.value || "mdi:remote");
    });

    const fin = root.querySelector("[data-feature-input]");
    if (fin) fin.addEventListener("input", () => {
      if (this._iconEdit) this._iconEdit.feature = fin.value;
    });

    root.querySelectorAll('[data-act="pickIcon"]').forEach(el =>
      el.addEventListener("click", () => {
        if (!this._iconEdit) return;
        this._iconEdit.icon = el.dataset.icon;
        this._render();
      })
    );

    const pta = root.querySelector("[data-panel-text]");
    if (pta) pta.addEventListener("input", () => { if (this._panel) this._panel.text = pta.value; });

    const acts = {
      closeMenus: () => { this._menu = null; this._render(); },
      renameSave: () => this._renameSave(),
      renameCancel: () => { this._rename = null; this._render(); },
      saveIcon: () => this._saveIcon(),
      clearIcon: () => { if (this._iconEdit) { this._iconEdit.icon = ""; this._saveIcon(); } },
      cancelPanel: () => { this._iconEdit = null; this._panel = null; this._render(); },
      copyProfile: () => this._copyProfile(),
      downloadProfile: () => this._downloadProfile(),
      runImport: () => this._runImport(),
      saveDeviceTransmitter: () => this._saveDeviceTransmitter(),
      showAddLoc: () => { this._addForm = { type: "location", id: "", name: "", idTouched: false }; this._render(); },
      submitAdd: () => this._submitAdd(),
      cancelAdd: () => { this._addForm = null; this._render(); },
      showNewCmd: () => { this._newCmd = { id: "", name: "", feature: "", idTouched: false }; this._render(); },
      cancelNewCmd: () => { this._newCmd = null; this._render(); },
      startLearnNew: () => {
        const f = this._newCmd;
        if (!f?.id.trim()) { this._err = this._t("commandIdRequired"); this._render(); return; }
        this._startWizard(f.id.trim(), f.name.trim() || f.id.trim(), f.feature || "");
      },
      testCode: () => this._testCode(),
      skipSave: () => { this._wizard = { ...this._wizard, step: 3 }; this._render(); },
      saveCode: () => this._saveCode(),
      cancelWizard: () => this._cancelWizard(),
    };

    root.querySelectorAll("[data-act]").forEach(el =>
      el.addEventListener("click", () => acts[el.dataset.act]?.())
    );
  }
}

// ── Styles ────────────────────────────────────────────────────────────────────

const TRANSLATIONS = {
  en: {
    add: "Add",
    addCommand: "Add command",
    addDevice: "Add device",
    addLocation: "Add location",
    cancel: "Cancel",
    codeNotReceived: "No code received. Try again.",
    codeReceived: "Code received",
    commandIdRequired: "Enter a command ID",
    commandName: "Command name",
    commandSaved: "Command saved",
    confirmUnverified: "Send unverified command \"{name}\"?",
    actions: "Actions",
    chooseIcon: "Choose icon",
    clearIcon: "Clear icon",
    confirmDelete: "Delete \"{name}\"?",
    copied: "Copied",
    copy: "Copy",
    delete: "Delete",
    deleted: "Deleted",
    download: "Download",
    exportHint: "Copy or download this device's commands as JSON.",
    exportProfile: "Export profile",
    featureLabel: "Role",
    featureNone: "No role",
    featurePowerOn: "Power on",
    featurePowerOff: "Power off",
    featurePowerToggle: "Power toggle",
    featurePlay: "Play",
    featurePause: "Pause",
    featurePlayPauseToggle: "Play/pause toggle",
    featureStop: "Stop",
    featureNext: "Next",
    featurePrevious: "Previous",
    featureFastForward: "Fast forward",
    featureRewind: "Rewind",
    featureVolumeUp: "Volume up",
    featureVolumeDown: "Volume down",
    featureMute: "Mute",
    featureUnmute: "Unmute",
    featureMuteToggle: "Mute toggle",
    featureSource: "Source",
    transmitterAuto: "Automatic",
    transmitterLabel: "Transmitter",
    iconLabel: "Icon",
    import: "Import",
    importHint: "Paste a profile JSON to add its commands to this device.",
    importProfile: "Import profile",
    imported: "Imported {count} command(s)",
    invalidCommandId: "Invalid command ID: {id}",
    invalidJson: "Invalid JSON",
    noCommandsInJson: "No commands found in the JSON",
    pasteJson: "Paste profile JSON here",
    rename: "Rename",
    id: "ID",
    idHelper: "Lowercase letters, numbers, and underscores",
    idPlaceholder: "tv_power",
    idRequired: "ID is required",
    learn: "Learn",
    name: "Name",
    newCommand: "New command",
    noCommands: "No commands yet",
    notTested: "Not tested",
    orCreateNew: "or create a new one",
    pointRemote: "Point the remote at the device",
    pressButtonPrefix: "and press",
    relearn: "Relearn",
    save: "Save",
    saved: "Saved",
    saving: "Saving...",
    secondsShort: "s",
    selectDevice: "Select a device",
    send: "Send",
    sending: "Sending...",
    sent: "Sent",
    sentToDevice: "Sent to device",
    skip: "Skip",
    status: "Status",
    stepRecord: "Step 1 of 3 · Record",
    stepSave: "Step 3 of 3 · Save",
    stepTest: "Step 2 of 3 · Test",
    test: "Test",
    tested: "Tested",
    testHint: "Send the command and confirm the device responds",
  },
  ru: {
    add: "Добавить",
    addCommand: "Добавить команду",
    addDevice: "Добавить устройство",
    addLocation: "Добавить локацию",
    cancel: "Отмена",
    codeNotReceived: "Код не получен. Попробуйте ещё раз.",
    codeReceived: "Код получен",
    commandIdRequired: "Введите ID команды",
    commandName: "Название команды",
    commandSaved: "Команда сохранена",
    confirmUnverified: "Отправить непроверенную команду \"{name}\"?",
    actions: "Действия",
    chooseIcon: "Выбор иконки",
    clearIcon: "Убрать иконку",
    confirmDelete: "Удалить «{name}»?",
    copied: "Скопировано",
    copy: "Копировать",
    delete: "Удалить",
    deleted: "Удалено",
    download: "Скачать",
    exportHint: "Скопируйте или скачайте команды этого устройства в JSON.",
    exportProfile: "Экспорт профиля",
    featureLabel: "Роль",
    featureNone: "Без роли",
    featurePowerOn: "Включение",
    featurePowerOff: "Выключение",
    featurePowerToggle: "Переключение питания",
    featurePlay: "Play",
    featurePause: "Pause",
    featurePlayPauseToggle: "Play/Pause",
    featureStop: "Stop",
    featureNext: "Следующий",
    featurePrevious: "Предыдущий",
    featureFastForward: "Перемотка вперёд",
    featureRewind: "Перемотка назад",
    featureVolumeUp: "Громче",
    featureVolumeDown: "Тише",
    featureMute: "Mute",
    featureUnmute: "Unmute",
    featureMuteToggle: "Mute toggle",
    featureSource: "Источник",
    transmitterAuto: "Автоматически",
    transmitterLabel: "Передатчик",
    iconLabel: "Иконка",
    import: "Импорт",
    importHint: "Вставьте JSON профиля, чтобы добавить его команды в это устройство.",
    importProfile: "Импорт профиля",
    imported: "Импортировано команд: {count}",
    invalidCommandId: "Некорректный ID команды: {id}",
    invalidJson: "Некорректный JSON",
    noCommandsInJson: "В JSON нет команд",
    pasteJson: "Вставьте JSON профиля сюда",
    rename: "Переименовать",
    id: "ID",
    idHelper: "Строчные латинские буквы, цифры и подчёркивания",
    idPlaceholder: "tv_power",
    idRequired: "ID обязателен",
    learn: "Учить",
    name: "Название",
    newCommand: "Новая команда",
    noCommands: "Команд пока нет",
    notTested: "Без проверки",
    orCreateNew: "или создайте новое",
    pointRemote: "Направьте пульт на устройство",
    pressButtonPrefix: "и нажмите",
    relearn: "Перезаписать",
    save: "Сохранить",
    saved: "Сохранено",
    saving: "Сохраняю...",
    secondsShort: "с",
    selectDevice: "Выберите устройство",
    send: "Отправить",
    sending: "Отправляю...",
    sent: "Отправлено",
    sentToDevice: "Отправлено на устройство",
    skip: "Пропустить",
    status: "Статус",
    stepRecord: "Шаг 1 из 3 · Запись",
    stepSave: "Шаг 3 из 3 · Сохранение",
    stepTest: "Шаг 2 из 3 · Проверка",
    test: "Проверить",
    tested: "Проверено",
    testHint: "Отправьте команду и убедитесь, что устройство реагирует",
  },
  uk: {
    add: "Додати",
    addCommand: "Додати команду",
    addDevice: "Додати пристрій",
    addLocation: "Додати локацію",
    cancel: "Скасувати",
    codeNotReceived: "Код не отримано. Спробуйте ще раз.",
    codeReceived: "Код отримано",
    commandIdRequired: "Введіть ID команди",
    commandName: "Назва команди",
    commandSaved: "Команду збережено",
    confirmUnverified: "Надіслати неперевірену команду \"{name}\"?",
    actions: "Дії",
    chooseIcon: "Вибір іконки",
    clearIcon: "Прибрати іконку",
    confirmDelete: "Видалити «{name}»?",
    copied: "Скопійовано",
    copy: "Копіювати",
    delete: "Видалити",
    deleted: "Видалено",
    download: "Завантажити",
    exportHint: "Скопіюйте або завантажте команди цього пристрою у JSON.",
    exportProfile: "Експорт профілю",
    featureLabel: "Роль",
    featureNone: "Без ролі",
    featurePowerOn: "Увімкнення",
    featurePowerOff: "Вимкнення",
    featurePowerToggle: "Перемикання живлення",
    featurePlay: "Play",
    featurePause: "Pause",
    featurePlayPauseToggle: "Play/Pause",
    featureStop: "Stop",
    featureNext: "Наступний",
    featurePrevious: "Попередній",
    featureFastForward: "Перемотування вперед",
    featureRewind: "Перемотування назад",
    featureVolumeUp: "Гучніше",
    featureVolumeDown: "Тихіше",
    featureMute: "Mute",
    featureUnmute: "Unmute",
    featureMuteToggle: "Mute toggle",
    featureSource: "Джерело",
    transmitterAuto: "Автоматично",
    transmitterLabel: "Передавач",
    iconLabel: "Іконка",
    import: "Імпорт",
    importHint: "Вставте JSON профілю, щоб додати його команди до цього пристрою.",
    importProfile: "Імпорт профілю",
    imported: "Імпортовано команд: {count}",
    invalidCommandId: "Некоректний ID команди: {id}",
    invalidJson: "Некоректний JSON",
    noCommandsInJson: "У JSON немає команд",
    pasteJson: "Вставте JSON профілю сюди",
    rename: "Перейменувати",
    id: "ID",
    idHelper: "Малі латинські літери, цифри та підкреслення",
    idPlaceholder: "tv_power",
    idRequired: "ID обов'язковий",
    learn: "Навчити",
    name: "Назва",
    newCommand: "Нова команда",
    noCommands: "Команд ще немає",
    notTested: "Без перевірки",
    orCreateNew: "або створіть новий",
    pointRemote: "Спрямуйте пульт на пристрій",
    pressButtonPrefix: "і натисніть",
    relearn: "Перезаписати",
    save: "Зберегти",
    saved: "Збережено",
    saving: "Зберігаю...",
    secondsShort: "с",
    selectDevice: "Виберіть пристрій",
    send: "Надіслати",
    sending: "Надсилаю...",
    sent: "Надіслано",
    sentToDevice: "Надіслано на пристрій",
    skip: "Пропустити",
    status: "Статус",
    stepRecord: "Крок 1 з 3 · Запис",
    stepSave: "Крок 3 з 3 · Збереження",
    stepTest: "Крок 2 з 3 · Перевірка",
    test: "Перевірити",
    tested: "Перевірено",
    testHint: "Надішліть команду й переконайтеся, що пристрій реагує",
  },
};

const STYLES = `
  :host { display: block; color: var(--primary-text-color); }
  ha-card { position: relative; overflow: visible; }
  .header { border-radius: var(--ha-card-border-radius, 12px) var(--ha-card-border-radius, 12px) 0 0; }

  /* Header */
  .header {
    display: flex; align-items: center; gap: 8px;
    padding: 14px 16px; border-bottom: 1px solid var(--divider-color);
  }
  .brand-icon { width: 24px; height: 24px; object-fit: contain; flex-shrink: 0; }
  .title { font-size: 15px; font-weight: 600; flex: 1; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .dot-idle { background: var(--disabled-color, #9e9e9e); }
  .dot-busy { background: var(--warning-color, #ff9800); }
  .dot-ok   { background: var(--success-color, #4caf50); }
  .dot-err  { background: var(--error-color, #f44336); }
  /* Layout */
  .body { display: grid; grid-template-columns: 185px 1fr; min-height: 340px; }
  @media (max-width: 480px) { .body { grid-template-columns: 1fr; } }

  /* Sidebar */
  .sidebar {
    border-right: 1px solid var(--divider-color);
    padding: 10px 8px; overflow-y: auto;
    font-size: 13px;
  }
  .loc-row {
    position: relative;
    display: flex; align-items: center; gap: 5px;
    padding: 6px 6px; border-radius: 5px;
    font-weight: 600; user-select: none;
  }
  .loc-row:hover { background: var(--secondary-background-color); }
  .loc-row.menu-open { overflow: visible; z-index: 60; }
  .arrow { font-size: 11px; color: var(--secondary-text-color); width: 10px; cursor: pointer; }
  .loc-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
  .devs { margin-left: 15px; border-left: 2px solid var(--divider-color); padding-left: 6px; }
  .dev {
    position: relative;
    display: flex; align-items: center;
    padding: 5px 7px; border-radius: 4px;
    margin-bottom: 1px;
  }
  .dev.menu-open { overflow: visible; z-index: 60; }
  .dev-name {
    flex: 1; cursor: pointer;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .dev:hover { background: var(--secondary-background-color); }
  .dev.sel {
    background: var(--primary-color); color: var(--text-primary-color);
    font-weight: 600;
  }
  .text-action {
    display: inline-flex; align-items: center; gap: 4px;
    width: 100%; min-height: 28px; padding: 0 6px;
    border: 0; border-radius: 4px; background: transparent;
    color: var(--secondary-text-color); cursor: pointer;
    font: inherit; font-size: 12px; text-align: left;
  }
  .text-action ha-icon { --mdc-icon-size: 16px; }
  .text-action:hover { color: var(--primary-color); background: var(--secondary-background-color); }
  .loc-link { margin-top: 10px; padding-left: 3px; }

  /* Inline form */
  .inline-form {
    margin: 6px 0; padding: 8px;
    background: var(--secondary-background-color); border-radius: 6px;
  }
  .fi {
    display: block;
    width: 100%;
    box-sizing: border-box;
    min-height: 38px;
    padding: 8px 10px;
    border: 1px solid var(--divider-color);
    border-radius: 6px;
    background: var(--card-background-color);
    color: var(--primary-text-color);
    font: inherit;
    font-size: 13px;
  }
  .fi::placeholder { color: var(--secondary-text-color); opacity: 0.7; }
  .fi:focus,
  .w-name-input:focus {
    outline: 0;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 1px var(--primary-color);
  }

  /* Compact fields: placeholder hints + trailing "?" tooltip */
  .cform { display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }
  .field-row { display: flex; align-items: center; gap: 6px; }
  .field-row .fi { flex: 1; min-width: 0; }
  .field-hint {
    display: inline-flex; align-items: center; justify-content: center;
    color: var(--secondary-text-color); cursor: help; flex-shrink: 0;
  }
  .field-hint ha-icon { --mdc-icon-size: 18px; }
  .field-hint:hover { color: var(--primary-color); }

  .form-row { display: flex; gap: 8px; align-items: center; justify-content: flex-end; }

  /* Main */
  .main {
    padding: 16px; display: flex; flex-direction: column; gap: 12px;
    min-width: 0;
  }
  .empty {
    flex: 1; display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    text-align: center; color: var(--secondary-text-color);
    font-size: 14px; line-height: 1.8;
  }
  .hint { font-size: 12px; opacity: 0.7; }

  /* Remote */
  .remote-head { font-size: 15px; font-weight: 600; }
  .device-settings {
    padding: 12px;
    border: 1px solid var(--divider-color);
    border-radius: 8px;
    background: var(--secondary-background-color);
  }
  .device-settings-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 36px;
    gap: 8px;
    align-items: center;
  }
  .cmd-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
    gap: 8px;
  }
  .empty-cmds { color: var(--secondary-text-color); font-size: 13px; }
  .cmd-card {
    position: relative; border: 1px solid var(--divider-color);
    border-radius: 8px; overflow: hidden;
    display: flex;
  }
  .cmd-card.menu-open { overflow: visible; z-index: 60; }
  .cmd-card.editing { padding: 4px; gap: 4px; align-items: center; }
  .cmd-card.unv { border-style: dashed; }
  .cmd-send {
    flex: 1; min-height: 44px; padding: 8px 28px 8px 10px;
    background: var(--secondary-background-color);
    color: var(--primary-text-color); border: none;
    font: inherit; font-size: 13px; font-weight: 500;
    cursor: pointer; text-align: left; line-height: 1.3;
    transition: background 0.12s;
    display: flex; align-items: center; gap: 8px; min-width: 0;
  }
  .cmd-send:hover { background: var(--primary-color); color: var(--text-primary-color); }
  .cmd-card.unv .cmd-send { color: var(--warning-color, orange); }
  .cmd-icon-stack {
    position: relative;
    width: 18px;
    height: 18px;
    flex-shrink: 0;
  }
  .cmd-icon { --mdc-icon-size: 18px; }
  .cmd-icon-base,
  .cmd-icon-sent {
    position: absolute;
    inset: 0;
    transition: opacity 0.15s ease;
  }
  .cmd-icon-base { opacity: 1; }
  .cmd-icon-sent { opacity: 0; }
  .cmd-icon-stack.no-icon .cmd-icon-base { opacity: 0; }
  .cmd-send.is-sent .cmd-icon-base { opacity: 0; }
  .cmd-send.is-sent .cmd-icon-sent { opacity: 1; }
  .cmd-name { overflow: hidden; text-overflow: ellipsis; }

  /* Kebab overflow trigger (commands, devices, locations) */
  .kebab {
    background: none; border: none; cursor: pointer; padding: 0;
    color: var(--secondary-text-color); border-radius: 4px;
    width: 24px; height: 24px; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    opacity: 0; transition: opacity 0.12s;
  }
  .kebab ha-icon { --mdc-icon-size: 18px; }
  .kebab:hover { color: var(--primary-color); background: var(--secondary-background-color); }
  .kebab.on-tile { position: absolute; top: 3px; right: 3px; }
  .loc-row:hover .kebab,
  .dev:hover .kebab,
  .cmd-card:hover .kebab,
  .menu-open .kebab { opacity: 1; }
  @media (hover: none) { .kebab { opacity: 1; } }

  /* Dropdown menu */
  .menu {
    position: absolute; z-index: 61;
    min-width: 168px; padding: 4px;
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color); border-radius: 8px;
    box-shadow: 0 4px 18px rgba(0, 0, 0, 0.28);
  }
  .menu-item {
    display: flex; align-items: center; gap: 10px;
    width: 100%; padding: 8px 10px; border: none; border-radius: 6px;
    background: none; color: var(--primary-text-color);
    font: inherit; font-size: 13px; text-align: left; cursor: pointer;
  }
  .menu-item ha-icon { --mdc-icon-size: 18px; color: var(--secondary-text-color); }
  .menu-item:hover { background: var(--secondary-background-color); }
  .menu-item.danger { color: var(--error-color, #f44336); }
  .menu-item.danger ha-icon { color: var(--error-color, #f44336); }

  /* Click-away scrim for open menus */
  .scrim { position: absolute; inset: 0; z-index: 50; background: transparent; }

  /* Inline rename row */
  .kebab-btn {
    background: none; border: none; cursor: pointer; padding: 0;
    color: var(--secondary-text-color); border-radius: 4px; flex-shrink: 0;
    width: 26px; height: 26px; display: flex; align-items: center; justify-content: center;
  }
  .kebab-btn ha-icon { --mdc-icon-size: 18px; }
  .kebab-btn:hover { background: var(--secondary-background-color); }
  .kebab-btn.ok { color: var(--primary-color); }
  .rename-fi { min-height: 30px; padding: 4px 8px; font-size: 13px; }
  .loc-row.editing, .dev.editing { gap: 4px; }

  /* Icon picker panel + profile panel */
  .panel {
    padding: 12px; background: var(--secondary-background-color);
    border-radius: 8px; display: flex; flex-direction: column; gap: 10px;
  }
  .panel-title { font-size: 12px; font-weight: 600; text-transform: uppercase; color: var(--secondary-text-color); }
  .panel-hint { font-size: 12px; color: var(--secondary-text-color); line-height: 1.4; margin-top: -4px; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip {
    width: 40px; height: 40px; border-radius: 8px; cursor: pointer;
    border: 1px solid var(--divider-color); background: var(--card-background-color);
    color: var(--primary-text-color);
    display: flex; align-items: center; justify-content: center;
  }
  .chip ha-icon { --mdc-icon-size: 22px; }
  .chip:hover { border-color: var(--primary-color); color: var(--primary-color); }
  .chip.sel { border-color: var(--primary-color); background: var(--primary-color); color: var(--text-primary-color); }
  .icon-preview {
    width: 40px; height: 40px; flex-shrink: 0; border-radius: 8px;
    border: 1px solid var(--divider-color);
    display: flex; align-items: center; justify-content: center;
    color: var(--primary-text-color);
  }
  .icon-preview ha-icon { --mdc-icon-size: 24px; }
  .ta {
    width: 100%; box-sizing: border-box; min-height: 150px; max-height: 320px;
    resize: vertical;
    padding: 10px; border: 1px solid var(--divider-color); border-radius: 6px;
    background: var(--card-background-color); color: var(--primary-text-color);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px;
    line-height: 1.45; white-space: pre; overflow: auto; tab-size: 2;
  }
  .ta:focus { outline: 0; border-color: var(--primary-color); box-shadow: 0 0 0 1px var(--primary-color); }
  .panel .form-row { justify-content: flex-start; flex-wrap: wrap; }

  .remote-foot { margin-top: 4px; }
  .add-cmd-btn {
    width: 100%; background: none;
    border: 1.5px dashed var(--divider-color);
    color: var(--secondary-text-color);
  }
  .add-cmd-btn:hover { border-color: var(--primary-color); color: var(--primary-color); background: none; }

  /* New command form */
  .new-cmd-form {
    padding: 12px; background: var(--secondary-background-color);
    border-radius: 8px;
  }
  .new-cmd-title { font-size: 12px; font-weight: 600; text-transform: uppercase; color: var(--secondary-text-color); margin-bottom: 8px; }

  /* Wizard */
  .wizard {
    flex: 1; display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    text-align: center; padding: 8px 16px;
    min-height: 220px;
  }
  .w-steps { display: flex; gap: 6px; margin-bottom: 8px; }
  .w-step {
    width: 28px; height: 4px; border-radius: 2px;
    background: var(--divider-color);
  }
  .w-step.active { background: var(--primary-color); }
  .w-step.done { background: var(--success-color, #4caf50); }
  .w-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--secondary-text-color); margin-bottom: 12px; }
  .w-title { font-size: 18px; font-weight: 600; margin-bottom: 8px; }
  .w-hint { font-size: 13px; color: var(--secondary-text-color); margin-bottom: 18px; line-height: 1.5; }
  .w-progress {
    width: 100%; max-width: 200px; height: 4px;
    background: var(--divider-color); border-radius: 2px;
    margin-bottom: 10px; overflow: hidden;
  }
  .w-bar { height: 100%; background: var(--primary-color); transition: width 1s linear; border-radius: 2px; }
  .w-countdown { font-size: 28px; font-weight: 300; color: var(--secondary-text-color); margin-bottom: 18px; }
  .w-actions { display: flex; gap: 8px; justify-content: center; margin-bottom: 6px; }
  .w-name-input {
    width: 100%;
    box-sizing: border-box;
    min-height: 40px;
    padding: 8px 12px;
    border: 1px solid var(--divider-color);
    border-radius: 6px;
    background: var(--card-background-color);
    color: var(--primary-text-color);
    font: inherit;
    font-size: 14px;
    text-align: center;
  }
  .wizard-field { width: 100%; max-width: 260px; margin-bottom: 16px; }

  /* Buttons */
  .btn {
    min-height: 36px; padding: 0 14px;
    border: 1px solid var(--divider-color); border-radius: 6px;
    background: var(--secondary-background-color);
    color: var(--primary-text-color);
    font: inherit; font-size: 13px; font-weight: 500;
    cursor: pointer; white-space: nowrap;
    display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  }
  .btn ha-icon { --mdc-icon-size: 18px; flex-shrink: 0; }
  .btn:disabled { opacity: 0.4; cursor: default; }
  .btn:hover:not(:disabled) { filter: brightness(1.08); }
  .btn.p {
    background: var(--primary-color); color: var(--text-primary-color);
    border-color: var(--primary-color);
  }
  .btn.icon-only {
    width: 36px; min-width: 36px; min-height: 36px; padding: 0;
  }
  .btn.sm { width: 32px; min-width: 32px; min-height: 32px; opacity: 0.72; }

  /* Toast */
  .toast {
    font-size: 13px; padding: 8px 12px;
    border-radius: 6px; margin-top: auto;
  }
  .toast.err { color: var(--error-color); background: color-mix(in srgb, var(--error-color) 12%, transparent); }
  .toast.ok  { color: var(--success-color, #4caf50); }
`;

if (!customElements.get("ir-learning-hub-card"))
  customElements.define("ir-learning-hub-card", IRLearningHubCard);
window.customCards = window.customCards || [];
if (!window.customCards.some(card => card.type === "ir-learning-hub-card"))
  window.customCards.push({
    type: "ir-learning-hub-card",
    name: "IR Learning Hub",
    description: "Learn, test, save, and send IR commands through IR Learning Hub.",
    version: IR_LEARNING_HUB_CARD_VERSION,
  });
console.info(
  `%c IR-LEARNING-HUB-CARD %c ${IR_LEARNING_HUB_CARD_VERSION} `,
  "color:#fff;background:#03a9f4;border-radius:3px 0 0 3px;padding:2px 4px",
  "color:#03a9f4;background:#222;border-radius:0 3px 3px 0;padding:2px 4px",
);
