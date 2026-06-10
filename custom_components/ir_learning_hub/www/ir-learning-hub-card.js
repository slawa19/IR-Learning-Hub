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
    this._newCmd = null;      // { id, name }
    this._busy = false;
    this._msg = "";
    this._err = "";
    this._lastStatus = undefined; // last status-entity state we rendered
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
      this._render();
    }
  }

  getCardSize() { return 8; }

  disconnectedCallback() {
    this._wizardSeq++;
    clearInterval(this._countdownTimer);
    this._countdownTimer = null;
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

  _startWizard(cmdId, cmdName) {
    const seq = ++this._wizardSeq;
    this._wizard = {
      step: 1,
      seq,
      locationId: this._selLoc,
      irDeviceId: this._selDev,
      cmdId,
      cmdName,
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
    const cmd = this._cmds()[cmdId];
    if (cmd?.verified === false && !confirm(this._t("confirmUnverified", { name: cmd.name || cmdId }))) return;
    await this._run(async () => {
      await this._call("send_command", {
        location_id: this._selLoc, ir_device_id: this._selDev, command_id: cmdId,
      });
      this._msg = this._t("sent");
    });
  }

  // ── Render: sidebar ───────────────────────────────────────────────────────

  _renderSidebar() {
    const locs = this._registry.locations || {};
    let tree = "";

    for (const [locId, loc] of Object.entries(locs)) {
      const exp = this._expanded[locId] !== false;
      const devs = loc.devices || {};
      tree += `
        <div class="loc-row" data-toggle="${this._x(locId)}">
          <span class="arrow">${exp ? "▾" : "▸"}</span>
          <span class="loc-name">${this._x(loc.name || locId)}</span>
        </div>`;
      if (exp) {
        tree += `<div class="devs">`;
        for (const [dId, d] of Object.entries(devs)) {
          const sel = dId === this._selDev && locId === this._selLoc;
          tree += `
            <div class="dev${sel ? " sel" : ""}" data-sel="${this._x(locId)}||${this._x(dId)}">
              ${this._x(d.name || dId)}
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

    if (!this._selDev) {
      return `<div class="empty">${this._x(this._t("selectDevice"))}<br><span class="hint">${this._x(this._t("orCreateNew"))}</span></div>`;
    }

    const dev = this._dev();
    const cmds = this._cmds();
    const cmdEntries = Object.entries(cmds);

    const grid = cmdEntries.length
      ? cmdEntries.map(([id, cmd]) => {
          const unv = cmd.verified === false;
          return `
            <div class="cmd-card${unv ? " unv" : ""}">
              <button class="cmd-send" data-send="${this._x(id)}" title="${this._x(this._t("send"))}">
                ${this._x(cmd.name || id)}
              </button>
              <button class="cmd-relearn" data-relearn="${this._x(id)}" title="${this._x(this._t("relearn"))}" aria-label="${this._x(this._t("relearn"))}">
                <ha-icon icon="mdi:backup-restore"></ha-icon>
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
      <div class="remote-head">${this._x(dev?.name || this._selDev)}</div>
      <div class="cmd-grid">${grid}</div>
      <div class="remote-foot">${footer}</div>`;
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
    const dotClass = { idle: "dot-idle", learning: "dot-busy", sending: "dot-busy", code_received: "dot-ok", error: "dot-err" }[state] || "dot-idle";

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        <div class="header">
          <img class="brand-icon" src="/ir_learning_hub/icon.png" alt="" />
          <span class="title">${this._x(this._config.title || "IR Learning Hub")}</span>
          <span class="status-dot ${dotClass}"></span>
          <button class="btn icon-only" data-act="refresh" title="${this._x(this._t("refresh"))}" aria-label="${this._x(this._t("refresh"))}">
            <ha-icon icon="mdi:refresh"></ha-icon>
          </button>
        </div>
        <div class="body">
          <div class="sidebar">${this._renderSidebar()}</div>
          <div class="main">
            ${this._renderMain()}
            ${this._err ? `<div class="toast err">${this._x(this._err)}</div>` : ""}
            ${this._msg && !this._err ? `<div class="toast ok">${this._x(this._msg)}</div>` : ""}
          </div>
        </div>
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
      el.addEventListener("click", () => this._send(el.dataset.send))
    );

    root.querySelectorAll("[data-relearn]").forEach(el =>
      el.addEventListener("click", () => {
        const cmdId = el.dataset.relearn;
        const cmdName = this._cmds()[cmdId]?.name || cmdId;
        this._startWizard(cmdId, cmdName);
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

    const acts = {
      refresh: () => { this._msg = ""; this._err = ""; this._loadRegistry(); },
      showAddLoc: () => { this._addForm = { type: "location", id: "", name: "", idTouched: false }; this._render(); },
      submitAdd: () => this._submitAdd(),
      cancelAdd: () => { this._addForm = null; this._render(); },
      showNewCmd: () => { this._newCmd = { id: "", name: "", idTouched: false }; this._render(); },
      cancelNewCmd: () => { this._newCmd = null; this._render(); },
      startLearnNew: () => {
        const f = this._newCmd;
        if (!f?.id.trim()) { this._err = this._t("commandIdRequired"); this._render(); return; }
        this._startWizard(f.id.trim(), f.name.trim() || f.id.trim());
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
    refresh: "Refresh",
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
    refresh: "Обновить",
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
    refresh: "Оновити",
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
  ha-card { overflow: hidden; }

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
    display: flex; align-items: center; gap: 5px;
    padding: 6px 6px; border-radius: 5px; cursor: pointer;
    font-weight: 600; user-select: none;
  }
  .loc-row:hover { background: var(--secondary-background-color); }
  .arrow { font-size: 11px; color: var(--secondary-text-color); width: 10px; }
  .loc-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .devs { margin-left: 15px; border-left: 2px solid var(--divider-color); padding-left: 6px; }
  .dev {
    padding: 5px 7px; border-radius: 4px; cursor: pointer;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    margin-bottom: 1px;
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
  .cmd-card.unv { border-style: dashed; }
  .cmd-send {
    flex: 1; min-height: 44px; padding: 8px 28px 8px 10px;
    background: var(--secondary-background-color);
    color: var(--primary-text-color); border: none;
    font: inherit; font-size: 13px; font-weight: 500;
    cursor: pointer; text-align: left; line-height: 1.3;
    transition: background 0.12s;
  }
  .cmd-send:hover { background: var(--primary-color); color: var(--text-primary-color); }
  .cmd-card.unv .cmd-send { color: var(--warning-color, orange); }
  .cmd-relearn {
    position: absolute; top: 4px; right: 4px;
    width: 20px; height: 20px; padding: 0;
    background: none; border: none; cursor: pointer;
    font-size: 12px; color: var(--secondary-text-color);
    opacity: 0; transition: opacity 0.15s;
    display: flex; align-items: center; justify-content: center;
    border-radius: 4px;
  }
  .cmd-relearn ha-icon { --mdc-icon-size: 14px; }
  .cmd-card:hover .cmd-relearn { opacity: 1; }
  @media (hover: none) { .cmd-relearn { opacity: 1; } }
  .cmd-relearn:hover { background: var(--secondary-background-color); color: var(--primary-color); }

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

customElements.define("ir-learning-hub-card", IRLearningHubCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "ir-learning-hub-card",
  name: "IR Learning Hub",
  description: "Learn, test, save, and send IR commands through IR Learning Hub.",
});
