// 設定頁（N1／N6）：改 config.json 的 providers／金鑰來源／comfy profile／lettering。
// 存檔會先備份成 config.json.bak 再整份寫回；金鑰只進系統金鑰庫，不寫檔。
// 出圖 profile（F4）：一組一張卡；沒有 comfy.profiles 的舊設定在畫面上等於一組 moss，
// 存檔就升級成新格式（comfy.profiles ＋ comfy.default_profile）。
(function () {
  "use strict";
  const { h, PAGES } = FE;

  const KINDS = ["moss", "anima"];
  const KIND_TEXT = { moss: "moss（MOSS-Image）", anima: "anima（Anima）" };
  // 內建的 workflow 檔（隨套件附，不用另外下載）；workflow 留空就是用這裡的
  const BUILTIN_WORKFLOW = { moss: "t2c/data/moss_layout.api.json", anima: "t2c/data/anima.api.json" };
  const WORKFLOW_HINT = "這是 workflow 不是 profiles；workflow 請填 profile.workflow 路徑或留空用內建";
  const RESTART_HINT = "provider／模型／網址改完即生效，只有行程環境變數要重啟。";
  const KEYRING_HINT = "沒有安裝 keyring：請在 .venv 執行 pip install keyring（裝完重啟伺服器），這裡才能存金鑰。";
  const KEY_PLACEHOLDER = "貼金鑰（只存進系統金鑰庫，不寫檔）";
  const MODELS_HINT = "同一臺 ComfyUI 一次只掛一組模型：換 profile 就要先在 ComfyUI 換成那一組的模型；專案用哪一組由 project.yaml 的 comfy_profile 決定。";
  const DL = { unet: "t2c-dl-unet", clip: "t2c-dl-clip", vae: "t2c-dl-vae", sampler: "t2c-dl-sampler", scheduler: "t2c-dl-scheduler", lora: "t2c-dl-lora" };
  const LIST_KEYS = ["unet", "clip", "vae", "lora", "sampler", "scheduler"];
  // stage_providers 的六個鍵（t2c/settings.py 的 STAGES）中文名：環境卡的「用在」那一欄用
  const STAGE_TEXT = { adapt: "改編規劃", script: "劇本", storyboard: "分鏡", bible: "視覺聖經", annotate: "切對話", plan: "頁數規劃" };

  const isDict = (value) => !!value && typeof value === "object" && !Array.isArray(value);
  const namesOf = (table) => Object.keys(table || {}).filter((key) => !key.startsWith("_"));

  const text = (value, oninput, attrs) => h("input", Object.assign({
    value: value == null ? "" : String(value),
    oninput: (e) => oninput(e.target.value),
  }, attrs || {}));

  const nums = (value, oninput, attrs) => h("input", Object.assign({
    type: "number", step: "any", value: value == null ? "" : String(value),
    oninput: (e) => oninput(e.target.value),
  }, attrs || {}));

  /** 空字串就從物件拿掉（送給後端時等於「沒指定」），不然留原值。 */
  const setStr = (obj, key, value) => {
    if (value === "") delete obj[key];
    else obj[key] = value;
  };

  const setNum = (obj, key, value) => {
    const raw = String(value == null ? "" : value).trim();
    if (raw === "") delete obj[key];
    else obj[key] = Number(raw);
  };

  const chip = (label, kind, title) => {
    const el = T2C.chip(label, kind);
    if (title) el.title = title;
    return el;
  };

  /** 物件換鍵名但保留順序與內容（profile 與 preset 都用）。 */
  function renameKey(table, from, to) {
    const next = {};
    for (const [key, value] of Object.entries(table)) next[key === from ? to : key] = value;
    return next;
  }

  /** 舊設定相容：comfy 沒有 profiles（或只有 _ 說明、或是空的 {}）時，等於只有一組 moss。 */
  function upgradeComfy(comfy) {
    if (isDict(comfy.profiles) && namesOf(comfy.profiles).length) return;
    const kept = {};
    if (isDict(comfy.profiles)) {
      for (const [key, value] of Object.entries(comfy.profiles)) if (key.startsWith("_")) kept[key] = value;
    }
    const profile = {
      kind: "moss",
      workflow: String(comfy.workflow || ""),
      models: isDict(comfy.models) ? comfy.models : {},
      presets: isDict(comfy.presets) ? comfy.presets : {},
      negative: String(comfy.negative || ""),
      default_preset: String(comfy.default_preset || ""),
    };
    comfy.profiles = Object.assign(kept, { moss: profile });
    comfy.default_profile = "moss";
    // 這幾個舊欄位搬進 profile 了，頂層留著只會變成第二個真相。
    delete comfy.models;
    delete comfy.presets;
    delete comfy.default_preset;
    delete comfy.workflow;
    delete comfy.negative;
  }

  /** F1：把貼進來的文字驗成 profiles。失敗回 { error }，成功回 { profiles }。驗不過就不動 draft。 */
  function checkProfiles(raw) {
    let parsed;
    try {
      parsed = JSON.parse(String(raw || "").trim() || "{}");
    } catch (error) {
      return { error: "JSON 有錯，還不會存：" + error.message };
    }
    if (!isDict(parsed)) return { error: "最外層要是物件（{名稱: {kind、workflow、models、presets}}），不是陣列或數字" };
    const keys = Object.keys(parsed);
    const numeric = keys.length > 0 && keys.every((key) => /^\d+$/.test(key));
    if (numeric || keys.some((key) => isDict(parsed[key]) && "class_type" in parsed[key])) return { error: WORKFLOW_HINT };
    const names = keys.filter((key) => !key.startsWith("_"));
    if (!names.length) return { error: "至少要有一組 profile（名稱對到 {kind、workflow、models、presets}）" };
    for (const name of names) {
      const entry = parsed[name];
      if (!isDict(entry)) return { error: "comfy.profiles." + name + " 要是物件" };
      const kind = String(entry.kind || "").trim();
      if (KINDS.indexOf(kind) < 0) return { error: "comfy.profiles." + name + " 的 kind 要是 moss 或 anima" };
    }
    return { profiles: parsed };
  }

  PAGES.settings = async (ctx) => {
    ctx.crumbs([{ label: "設定" }]);

    let data = null;                 // GET /api/settings
    let env = null;                  // GET /api/env（ComfyUI 現在連得上嗎、這一章用哪一組）
    let envError = "";               // /api/env 失敗的那句話
    let draft = null;                // data.settings，就地編輯
    let modelLists = null;           // GET /api/comfy/models 抓到的清單（datalist 用）
    let savedNote = "";              // 存檔後顯示在頁面上的那句話
    const probes = {};               // provider id → { state, models, message }
    const keyringOn = {};            // provider id → 這一次已經把金鑰存進金鑰庫

    let cardsHost = null;            // profile 卡片（含預設 profile 下拉）
    let listsHost = null;            // datalist
    let keysHost = null;             // 金鑰來源唯讀表
    let jsonBox = null;              // details 裡的 profiles JSON
    let jsonError = null;
    let jsonDetails = null;

    const profiles = () => (isDict(draft.comfy.profiles) ? draft.comfy.profiles : (draft.comfy.profiles = {}));
    const profileNames = () => namesOf(profiles());
    const stageKeys = () => (Array.isArray(data.stages) ? data.stages : []);
    const keyRow = (id) => (data.keys || []).find((row) => String(row.id) === String(id)) || {};
    const keyringOk = () => !!(data.keyring && data.keyring.available);
    const service = () => (data.keyring && data.keyring.service) || "novel-studio";

    function adoptDefault() {
      const names = profileNames();
      if (!names.length) return;
      if (names.indexOf(String(draft.comfy.default_profile || "")) < 0) draft.comfy.default_profile = names[0];
    }

    /** 卡片改完就把 JSON 框的內容跟上（正在打 JSON 時不蓋掉）。 */
    function syncJson() {
      if (!jsonBox || jsonBox === document.activeElement) return;
      jsonBox.value = JSON.stringify(profiles(), null, 2);
      if (jsonError) jsonError.textContent = "";
    }

    function rememberLists(result) {
      if (!result) return;
      const lists = Object.assign({}, modelLists || {});
      let changed = false;
      for (const key of LIST_KEYS) {
        if (Array.isArray(result[key])) { lists[key] = result[key]; changed = true; }
      }
      if (changed) { modelLists = lists; drawLists(); }
    }

    function drawLists() {
      if (!listsHost) return;
      const lists = modelLists || {};
      const one = (key) => {
        const items = Array.isArray(lists[key]) ? lists[key] : [];
        return items.length ? h("datalist", { id: DL[key] }, items.map((item) => h("option", { value: String(item) }))) : null;
      };
      listsHost.replaceChildren(...LIST_KEYS.map((key) => one(key)).filter(Boolean));
    }

    /* ── ComfyUI profile 卡片（F4）── */

    function copyProfile(name) {
      const table = profiles();
      const stem = name + "_copy";
      let target = stem;
      let i = 2;
      while (table[target]) { target = stem + "_" + i; i += 1; }
      const next = {};
      for (const [key, value] of Object.entries(table)) {
        next[key] = value;
        if (key === name) next[target] = JSON.parse(JSON.stringify(value));
      }
      draft.comfy.profiles = next;
      drawCards();
      FE.toast("已複製成「" + target + "」（還沒存檔）", "ok");
    }

    /** 新增一組 profile：名稱直接用 kind（anima、anima2…），並順手依 kind 自動挑模型。 */
    async function addProfile() {
      const table = profiles();
      let target = "anima";
      let i = 2;
      while (table[target]) { target = "anima" + i; i += 1; }
      table[target] = { kind: "anima", workflow: "", models: {}, presets: {}, negative: "", default_preset: "" };
      draft.comfy.profiles = table;
      adoptDefault();
      syncJson();
      drawCards();
      FE.toast("已新增「" + target + "」（kind anima）：正在依 kind 自動挑模型…", "ok");
      try {
        const result = await FE.api("/api/comfy/models", { query: { kind: "anima" }, signal: ctx.signal });
        rememberLists(result);
        if (!result || result.ok === false) {
          FE.toast("ComfyUI 沒有回應，模型欄位請自己選：" + ((result && result.message) || ""), "warn");
          return;
        }
        const guessed = result.guessed || {};
        const filled = {};
        for (const key of ["unet", "clip", "vae"]) {
          const value = String(guessed[key] || "").trim();
          if (value) filled[key] = value;
        }
        if (!Object.keys(filled).length) {
          FE.toast("ComfyUI 現在沒有可以用來猜的檔名，模型欄位請自己選", "warn");
          return;
        }
        const card = profiles()[target];
        if (isDict(card)) card.models = Object.assign(isDict(card.models) ? card.models : {}, filled);
        syncJson();
        drawCards();
      } catch (error) {
        if (error.name === "AbortError") throw error;
        FE.fail(error);
      }
    }

    function removeProfile(name) {
      if (profileNames().length <= 1) { FE.toast("至少要留一組 profile，這一組不能刪", "warn"); return; }
      const next = {};
      for (const [key, value] of Object.entries(profiles())) if (key !== name) next[key] = value;
      draft.comfy.profiles = next;
      if (String(draft.comfy.default_profile || "") === name) delete draft.comfy.default_profile;
      adoptDefault();
      drawCards();
    }

    function profileCard(name) {
      const raw = profiles()[name];
      if (!isDict(raw)) {
        return h("section", { class: "card card-flat stack" },
          h("p", { class: "t2c-small t2c-err" }, "comfy.profiles." + name + " 要是物件（kind、workflow、models、presets）——請用下面的「進階：直接編輯 JSON」修。"));
      }
      const entry = raw;
      const models = isDict(entry.models) ? entry.models : (entry.models = {});
      const presets = isDict(entry.presets) ? entry.presets : (entry.presets = {});
      const presetNames = () => namesOf(presets);
      const kindText = () => (KINDS.indexOf(String(entry.kind || "")) >= 0 ? String(entry.kind) : "moss");
      // 使用者要知道「這一組實際會用哪一份 workflow」——內建檔在哪、填了路徑會用哪一份
      const workflowNote = () => {
        const raw = String(entry.workflow || "").trim().replace(/\\/g, "/");
        const builtin = BUILTIN_WORKFLOW[kindText()] || BUILTIN_WORKFLOW.moss;
        if (!raw) return "留空＝內建 " + builtin + "（隨套件附，不用另外下載）";
        if (raw.endsWith("moss_layout.api.json") || raw.endsWith("anima.api.json"))
          return "舊寫法，照樣用內建 " + builtin + "；要換別的 workflow 才需要改這裡";
        return "用這一份（相對 config.json）：" + raw;
      };

      const nameInput = h("input", {
        value: name, style: "flex:0 1 170px;min-width:120px", "aria-label": "profile 名稱",
        title: "改名會保留內容；名稱就是 project.yaml 的 comfy_profile 可以指定的值",
        onchange: () => {
          const next = nameInput.value.trim();
          if (next === name) { nameInput.value = name; return; }
          if (!next) { nameInput.value = name; FE.toast("profile 名稱不能空白", "warn"); return; }
          if (profiles()[next]) { nameInput.value = name; FE.toast("已經有一組叫「" + next + "」", "warn"); return; }
          draft.comfy.profiles = renameKey(profiles(), name, next);
          if (String(draft.comfy.default_profile || "") === name) draft.comfy.default_profile = next;
          drawCards();
        },
      });

      const kind = h("select", { "aria-label": "kind", style: "width:auto" },
        KINDS.map((k) => h("option", { value: k, selected: String(entry.kind) === k, title: KIND_TEXT[k] }, k)));
      kind.addEventListener("change", () => {
        const before = String(entry.kind || "").trim();
        entry.kind = kind.value;
        if (before !== entry.kind) {
          // 換模型家族就別沿用另一邊的 workflow（moss_layout.api.json 套到 anima 會出錯）
          const raw = String(entry.workflow || "").trim().replace(/\\/g, "/");
          if (!raw || raw.endsWith("moss_layout.api.json") || raw.endsWith("anima.api.json")) delete entry.workflow;
          syncJson();
          autoGuess();
        }
        drawCards();
      });

      const workflow = text(entry.workflow, (v) => { setStr(entry, "workflow", v); syncJson(); },
        { placeholder: "（留空＝內建）", style: "width:min(340px,100%)" });

      const guessHost = h("span", { class: "row t2c-tight" });
      const autoBtn = h("button", {
        class: "btn btn-sm", type: "button", title: "照 ComfyUI 現在的檔名猜這一組的 unet／clip／vae，猜到的才填進去",
        onclick: () => autoGuess(),
      }, "依 kind 自動挑");

      async function autoGuess() {
        autoBtn.disabled = true;
        guessHost.replaceChildren(chip("抓取中…"));
        try {
          const result = await FE.api("/api/comfy/models", { query: { kind: kindText() }, signal: ctx.signal });
          rememberLists(result);
          if (!result || result.ok === false) {
            guessHost.replaceChildren(h("span", { class: "t2c-small t2c-warn" }, (result && result.message) || "ComfyUI 沒有回應"));
            return;
          }
          const guessed = result.guessed || {};
          let filled = 0;
          for (const key of ["unet", "clip", "vae"]) {
            const value = String(guessed[key] || "").trim();
            if (value) { models[key] = value; filled += 1; }
          }
          if (!filled) { guessHost.replaceChildren(chip("ComfyUI 沒有猜到，請自己選", "warn")); return; }
          syncJson();
          drawCards();
          FE.toast("依 " + kindText() + " 填了 " + filled + " 個模型檔名（還沒存檔）", "ok");
        } catch (error) {
          if (error.name === "AbortError") throw error;
          guessHost.replaceChildren(chip("✗ 抓不到", "err", error.message));
          FE.fail(error);
        } finally {
          autoBtn.disabled = false;
        }
      }

      const modelInput = (key, label) => h("span", { class: "row t2c-tight" }, label,
        text(models[key], (v) => { setStr(models, key, v); syncJson(); },
          { list: DL[key], style: "width:min(240px,100%)", placeholder: "（空的＝不指定）" }));

      function presetRow(presetName) {
        const preset = isDict(presets[presetName]) ? presets[presetName] : (presets[presetName] = {});
        const cell = (child) => h("td", { style: "white-space:nowrap" }, child);
        const nameField = h("input", {
          value: presetName, style: "width:110px;min-width:110px", "aria-label": "預設名稱",
          onchange: () => {
            const next = nameField.value.trim();
            if (next === presetName) { nameField.value = presetName; return; }
            if (!next) { nameField.value = presetName; FE.toast("預設名稱不能空白", "warn"); return; }
            if (presets[next]) { nameField.value = presetName; FE.toast("這一組已經有「" + next + "」", "warn"); return; }
            entry.presets = renameKey(presets, presetName, next);
            if (String(entry.default_preset || "") === presetName) entry.default_preset = next;
            syncJson();
            drawCards();
          },
        });
        return h("tr", {},
          cell(nameField),
          cell(nums(preset.steps, (v) => { setNum(preset, "steps", v); syncJson(); }, { style: "width:72px;min-width:72px" })),
          cell(nums(preset.cfg, (v) => { setNum(preset, "cfg", v); syncJson(); }, { style: "width:72px;min-width:72px" })),
          cell(text(preset.sampler, (v) => { setStr(preset, "sampler", v); syncJson(); }, { list: DL.sampler, style: "width:112px;min-width:112px" })),
          cell(text(preset.scheduler, (v) => { setStr(preset, "scheduler", v); syncJson(); }, { list: DL.scheduler, style: "width:104px;min-width:104px" })),
          cell(text(preset.lora, (v) => { setStr(preset, "lora", v); syncJson(); }, { list: DL.lora, style: "width:200px;min-width:200px", placeholder: "（不用就留空）" })),
          cell(nums(preset.lora_strength, (v) => { setNum(preset, "lora_strength", v); syncJson(); }, { style: "width:80px;min-width:80px" })),
          cell(h("button", { class: "btn btn-sm btn-ghost", type: "button", onclick: () => removePreset(presetName) }, "刪除列")));
      }

      function removePreset(presetName) {
        delete presets[presetName];
        if (String(entry.default_preset || "") === presetName) delete entry.default_preset;
        syncJson();
        drawCards();
      }

      function addPreset() {
        let target = "preset";
        let i = 2;
        while (presets[target]) { target = "preset" + i; i += 1; }
        presets[target] = { steps: 20, cfg: 7 };
        syncJson();
        drawCards();
      }

      const defaultPreset = h("select", { "aria-label": "這一組的預設 preset" },
        h("option", { value: "" }, "（不指定；用 ComfyUI 的預設）"),
        presetNames().map((presetName) => h("option", { value: presetName, selected: String(entry.default_preset || "") === presetName }, presetName)));
      defaultPreset.addEventListener("change", () => {
        if (defaultPreset.value) entry.default_preset = defaultPreset.value;
        else delete entry.default_preset;
        syncJson();
      });

      return h("section", { class: "card card-flat stack" },
        h("div", { class: "row t2c-tight", style: "flex-wrap:nowrap" },
          h("b", { style: "white-space:nowrap" }, "profile"), nameInput,
          String(draft.comfy.default_profile || "") === name ? chip("預設", "ok", "comfy.default_profile：project.yaml 沒寫 comfy_profile 時用這一組") : null,
          h("span", { class: "row t2c-tight", style: "margin-left:auto;flex-wrap:nowrap;flex:0 0 auto" },
            h("span", { style: "white-space:nowrap" }, "kind：", kind),
            h("button", { class: "btn btn-sm", type: "button", style: "white-space:nowrap", onclick: () => copyProfile(name) }, "複製這組"),
            h("button", {
              class: "btn btn-sm btn-ghost", type: "button", style: "white-space:nowrap", disabled: profileNames().length <= 1,
              title: profileNames().length <= 1 ? "至少要留一組 profile" : "這一組從清單拿掉（還沒存檔前都還原得回來）",
              onclick: () => removeProfile(name),
            }, "刪除這組"))),
        h("div", { class: "row t2c-tight" }, h("span", { style: "white-space:nowrap" }, "workflow："), workflow,
          h("span", { class: "muted t2c-small" }, workflowNote())),
        h("div", { class: "row t2c-tight" },
          modelInput("unet", "unet："), modelInput("clip", "clip："), modelInput("vae", "vae："), autoBtn, guessHost),
        h("div", { class: "row t2c-tight" }, h("span", {}, "negative："),
          text(entry.negative, (v) => { setStr(entry, "negative", v); syncJson(); },
            { style: "width:min(520px,100%)", placeholder: "（留空＝不送負向提示詞）" })),
        h("div", { class: "row t2c-tight" }, h("span", {}, "預設 preset："), defaultPreset,
          h("span", { class: "muted t2c-small" }, "presets 是這一組自己的，別組的同名 preset 互不影響。")),
        h("div", { class: "table-wrap", style: "overflow-x:auto" }, h("table", { class: "table", style: "table-layout:auto" },
          h("thead", {}, h("tr", {}, ["預設名稱", "steps", "cfg", "sampler", "scheduler", "lora", "lora_strength", ""].map((label) => h("th", {}, label)))),
          h("tbody", {}, presetNames().map((presetName) => presetRow(presetName))))),
        h("div", { class: "row t2c-tight" },
          h("button", { class: "btn btn-sm", type: "button", onclick: addPreset }, "新增預設列"),
          h("span", { class: "muted t2c-small" }, "欄位：steps、cfg、sampler、scheduler、lora、lora_strength。"),
          h("span", { class: "muted t2c-small" }, "這一組的 loras 陣列不畫在卡片上，只在下面的 JSON 編輯。")));
    }

    function drawCards() {
      if (!cardsHost) return;
      const names = profileNames();
      adoptDefault();
      const pick = h("select", { "aria-label": "預設 profile" },
        names.map((name) => h("option", { value: name, selected: name === String(draft.comfy.default_profile || "") }, name)));
      pick.addEventListener("change", () => { draft.comfy.default_profile = pick.value; syncJson(); drawCards(); });
      cardsHost.replaceChildren(h("div", { class: "stack" },
        h("div", { class: "row t2c-tight" }, h("span", { style: "white-space:nowrap" }, "預設 profile："), pick,
          h("button", { class: "btn btn-sm", type: "button", style: "white-space:nowrap", onclick: () => addProfile() }, "新增一組"),
          h("span", { class: "muted t2c-small" }, "存檔後寫進 comfy.default_profile。")),
        names.length <= 1 ? h("p", { class: "muted t2c-small" },
          "只有一組 profile。要加另一種模型（例如 Anima）：按「新增一組」→ 名稱改成 anima、kind 選 anima → 按「依 kind 自動挑」→ workflow 留空＝內建 anima 的 workflow → 儲存。") : null,
        names.length ? h("div", { class: "stack" }, names.map((name) => profileCard(name)))
          : h("p", { class: "muted" }, "沒有 profile：下面「進階：直接編輯 JSON」貼一組進來。")));
    }

    /* ── 金鑰（F5b）── */

    function keyState(p) {
      const row = keyRow(p.id);
      const envSet = !!row.env_set;
      const stored = !!row.keyring || !!keyringOn[p.id];
      if (envSet) return { label: "環境變數", kind: "ok", title: "環境變數 " + row.key_env + " 有設，優先於系統金鑰庫" };
      if (stored) return { label: "金鑰庫：有", kind: "ok", title: "已存進系統金鑰庫（服務 " + service() + "、帳號＝provider id），不用重啟就生效" };
      return { label: "－ 未設", kind: "warn", title: "環境變數沒設、金鑰庫也沒有：呼叫時會失敗" };
    }

    function keyCell(p) {
      const host = h("td", { style: "white-space:nowrap" });
      const input = h("input", { type: "password", placeholder: KEY_PLACEHOLDER, autocomplete: "off", style: "width:160px;min-width:160px", disabled: !keyringOk() });
      const statusHost = h("span", {});
      const button = h("button", {
        class: "btn btn-sm", type: "button", disabled: !keyringOk(),
        title: keyringOk() ? "只存進系統金鑰庫，不寫任何檔案" : KEYRING_HINT,
        onclick: () => storeKey(),
      }, "存進金鑰庫");

      function paint() {
        const state = keyState(p);
        statusHost.replaceChildren(chip(state.label, state.kind, state.title));
      }

      async function storeKey() {
        const key = input.value.trim();
        if (!key) { FE.toast("先把金鑰貼進左邊的框", "warn"); return; }
        button.disabled = true;
        try {
          const result = await FE.api("/api/llm/key", { body: { provider: p.id, key: key }, signal: ctx.signal });
          if (result && result.ok) {
            input.value = "";
            keyringOn[p.id] = true;
            paint();
            drawKeys();
            FE.toast(result.message || "已存進系統金鑰庫", "ok");
          } else {
            FE.toast((result && result.message) || "存不進系統金鑰庫", "err");
          }
        } catch (error) {
          if (error.name === "AbortError") throw error;
          FE.fail(error);
        } finally {
          button.disabled = !keyringOk();
        }
      }

      paint();
      host.append(h("div", { class: "stack t2c-tight" }, h("div", { class: "row t2c-tight" }, input, button), statusHost));
      return host;
    }

    function drawKeys() {
      if (!keysHost) return;
      const rows = data.keys || [];
      if (!rows.length) { keysHost.replaceChildren(h("p", { class: "muted" }, "沒有 provider。")); return; }
      keysHost.replaceChildren(h("table", { class: "table" },
        h("thead", {}, h("tr", {}, h("th", {}, "provider"), h("th", {}, "金鑰環境變數"), h("th", {}, "狀態"))),
        h("tbody", {}, rows.map((row) => {
          const envSet = !!row.env_set;
          const stored = !!row.keyring || !!keyringOn[row.id];
          return h("tr", {},
            h("td", {}, String(row.id)),
            h("td", {}, row.key_env || "（沒有）"),
            h("td", {}, envSet ? chip("環境變數", "ok", "環境變數 " + row.key_env + " 有設，優先於系統金鑰庫")
              : stored ? chip("金鑰庫", "ok", "系統金鑰庫有這一筆（服務 " + service() + "、帳號＝provider id）")
              : chip("沒有（會去讀系統金鑰庫）", "warn", "環境變數沒設，金鑰庫也沒有：呼叫時會失敗")));
        }))));
    }

    /* ── 語言模型（F5a）：連線測試（每次按下才打 /api/llm/probe）── */

    function netCell(p) {
      const host = h("td", { style: "white-space:nowrap" });
      function paint() {
        const state = probes[p.id] || { state: "none" };
        const button = h("button", {
          class: "btn btn-sm", type: "button", disabled: state.state === "testing",
          title: "用這一列的 base_url／model 與金鑰打一次 models 清單，不寫檔",
          onclick: () => probe(),
        }, "測試連線");
        const status = state.state === "ok" ? chip("✓ 共 " + state.models.length + " 個模型", "ok", state.models.join("、"))
          : state.state === "fail" ? chip("✗ 失敗", "err", state.message || "")
          : state.state === "testing" ? chip("測試中…")
          : chip("－ 未測");
        host.replaceChildren(h("div", { class: "row t2c-tight" }, button, status));
      }

      async function probe() {
        probes[p.id] = { state: "testing" };
        paint();
        try {
          const result = await FE.api("/api/llm/probe", { body: { provider: p.id }, signal: ctx.signal });
          probes[p.id] = result && result.ok
            ? { state: "ok", models: Array.isArray(result.models) ? result.models : [] }
            : { state: "fail", message: (result && result.message) || "測試失敗" };
        } catch (error) {
          if (error.name === "AbortError") throw error;
          probes[p.id] = { state: "fail", message: error.message };
          FE.fail(error);
        }
        paint();
      }

      paint();
      return host;
    }

    function providerTable() {
      if (!draft.providers.length) return h("p", { class: "muted" }, "還沒有 provider。");
      // 八欄比卡片寬：外面一定包一層可橫向捲動的框，不然右邊的「連線／金鑰／刪除」看不到也點不到。
      return h("div", { class: "table-wrap", style: "overflow-x:auto" }, h("table", { class: "table", style: "table-layout:auto" },
        h("thead", {}, h("tr", {},
          h("th", {}, "id"), h("th", {}, "名稱"), h("th", {}, "base_url"), h("th", {}, "model"),
          h("th", {}, "金鑰環境變數"), h("th", {}, "連線"), h("th", {}, "金鑰"), h("th", {}, ""))),
        h("tbody", {}, draft.providers.map((p, i) => h("tr", {},
          h("td", { style: "white-space:nowrap" }, String(p.id)),
          h("td", {}, text(p.name, (v) => { p.name = v; }, { style: "width:130px;min-width:130px" })),
          h("td", {}, text(p.base_url, (v) => { p.base_url = v; }, { style: "width:220px;min-width:220px" })),
          h("td", {}, text(p.model, (v) => { p.model = v; }, { style: "width:160px;min-width:160px" })),
          h("td", {}, text(p.key_env, (v) => { p.key_env = v; }, { style: "width:180px;min-width:180px" })),
          netCell(p),
          keyCell(p),
          h("td", {}, h("button", {
            class: "btn btn-sm btn-ghost", type: "button", title: "從清單拿掉（還沒存檔前都還原得回來）",
            onclick: () => { draft.providers.splice(i, 1); draw(); },
          }, "刪除")))))));
    }

    function addProviderRow() {
      const newId = h("input", { placeholder: "llamacpp", style: "width:110px" });
      const newUrl = h("input", { placeholder: "http://127.0.0.1:8080/v1", style: "width:min(320px,100%)" });
      const newModel = h("input", { placeholder: "模型名稱", style: "width:150px" });
      const newKey = h("input", { placeholder: "KEY_ENV（可留空）", style: "width:150px" });
      return h("div", { class: "row t2c-tight" }, h("span", {}, "新增 provider："), newId, newUrl, newModel, newKey,
        h("button", {
          class: "btn btn-sm", type: "button",
          onclick: () => {
            const id = newId.value.trim();
            if (!id) { FE.fail(new Error("要給 id")); return; }
            if (draft.providers.some((p) => String(p.id) === id)) { FE.fail(new Error("id 重複：" + id)); return; }
            if (!newUrl.value.trim()) { FE.fail(new Error("要給 base_url")); return; }
            draft.providers.push({
              id: id, type: "openai", name: id, base_url: newUrl.value.trim(), model: newModel.value.trim(),
              key_env: newKey.value.trim(), context_tokens: 32768, max_output: 8192, temperature: 0.8, json_mode: true,
            });
            draw();
          },
        }, "新增"));
    }

    function stageSelect(key) {
      const select = h("select", { "aria-label": "階段 " + key + " 用哪個 provider" },
        h("option", { value: "" }, "（用 default_provider）"),
        draft.providers.map((p) => h("option", {
          value: String(p.id), selected: String(draft.stage_providers[key] || "") === String(p.id),
        }, String(p.id))));
      select.addEventListener("change", () => { draft.stage_providers[key] = select.value; });
      return select;
    }

    async function save() {
      try {
        const result = await FE.api("/api/settings", { body: { settings: draft }, signal: ctx.signal });
        savedNote = "已寫入 " + result.path + "（舊檔備份成 " + (result.backup || result.path + ".bak") + "）。";
        FE.toast("已寫入設定", "ok");
        await refresh();
      } catch (error) {
        if (error.name === "AbortError") throw error;
        FE.fail(error);
      }
    }

    /* ── 讀資料、畫頁面（存檔後會再跑一次）── */

    async function load() {
      const next = await FE.api("/api/settings", { signal: ctx.signal });
      let nextEnv = null;
      let nextEnvError = "";
      try {
        nextEnv = await T2C.get("/api/env", {}, ctx);
      } catch (error) {
        if (error.name === "AbortError") throw error;
        nextEnvError = error.message;
      }
      return { data: next, env: nextEnv, envError: nextEnvError };
    }

    function apply(loaded) {
      data = loaded.data;
      env = loaded.env;
      envError = loaded.envError;
      draft = data.settings;
      draft.providers = Array.isArray(draft.providers) ? draft.providers : [];
      draft.stage_providers = isDict(draft.stage_providers) ? draft.stage_providers : {};
      draft.comfy = isDict(draft.comfy) ? draft.comfy : {};
      draft.lettering = isDict(draft.lettering) ? draft.lettering : {};
      upgradeComfy(draft.comfy);
    }

    async function refresh() {
      apply(await load());
      draw();
    }

    function onJsonInput() {
      const result = checkProfiles(jsonBox.value);
      if (result.error) { jsonError.textContent = result.error; return; }
      jsonError.textContent = "";
      draft.comfy.profiles = result.profiles;
      adoptDefault();
      drawCards();
    }

    function comfyStatus() {
      if (envError) return h("span", { class: "t2c-small t2c-warn" }, "讀不到環境檢查：" + envError);
      if (!env || !env.comfy) return null;
      const block = env.comfy;
      return h("span", { class: "row t2c-tight" },
        block.ok ? chip("ComfyUI 連得上", "ok", block.url || "") : chip("ComfyUI 沒回應", "warn", block.url || ""),
        block.vram ? h("span", { class: "muted t2c-small" }, block.vram) : null,
        block.profile ? h("span", { class: "muted t2c-small" }, "這一章用 profile：" + block.profile + (block.kind ? "（" + block.kind + "）" : "")) : null);
    }

    /** 環境：ComfyUI 連不連得上、每個 provider 有沒有金鑰、設定檔在哪（原本是總覽頁的卡片）。 */
    function envCard() {
      let body;
      if (envError) {
        body = h("div", { class: "alert alert-warn" }, "讀不到環境檢查：" + envError);
      } else if (!env || !env.comfy) {
        body = h("p", { class: "muted" }, "沒有環境資料；按「重新檢查」再試一次。");
      } else {
        const block = env.comfy;
        body = h("div", { class: "stack" },
          h("div", { class: "row" }, block.ok ? chip("ComfyUI 已連線", "ok", block.url || "") : chip("ComfyUI 沒有回應", "warn", block.url || ""),
            h("span", { class: "muted" }, block.url || ""), block.vram ? h("span", {}, block.vram) : null),
          h("table", { class: "table" },
            h("thead", {}, h("tr", {}, ["模型", "型號", "狀態", "用在"].map((t) => h("th", {}, t)))),
            h("tbody", {}, (env.providers || []).map((p) => {
              const used = Object.entries(env.stages || {}).filter(([, id]) => id === p.id).map(([s]) => STAGE_TEXT[s] || s);
              const state = p.local
                ? chip(p.running ? "執行中（佔 VRAM）" : "沒有執行", p.running ? "info" : "")
                : chip(p.has_key ? "有金鑰" : "沒有金鑰（環境變數 " + (p.key_env || "－") + "）", p.has_key ? "ok" : "err");
              return h("tr", {}, h("td", {}, p.name), h("td", {}, p.model || h("span", { class: "muted" }, "預設")), h("td", {}, state), h("td", {}, used.join("、") || "－"));
            }))),
          h("p", { class: "muted t2c-small" },
            "設定檔：" + (env.config_path || data.path) + "；出圖預設：" + ((env.presets || []).join("、") || "（workflow 預設）") + "（預設 " + (env.default_preset || "－") + "）"));
      }
      return h("section", { class: "card stack" },
        h("div", { class: "row" }, h("h2", { class: "card-title grow" }, "環境"), h("button", { class: "btn btn-sm", type: "button", onclick: () => refresh() }, "重新檢查")),
        body);
    }

    function draw() {
      adoptDefault();

      const note = h("div", { class: "muted" }, savedNote || ("改完按最下面的「儲存」，會整份寫回 " + data.path + "（舊檔先備份成 " + (data.backup || data.path + ".bak") + "）。"));
      const canStore = keyringOk();

      const defaultSelect = h("select", { "aria-label": "預設 provider" },
        draft.providers.map((p) => h("option", { value: String(p.id), selected: String(draft.default_provider || "") === String(p.id) }, String(p.id))));
      defaultSelect.addEventListener("change", () => { draft.default_provider = defaultSelect.value; });

      /* ComfyUI：位址、抓模型清單、datalist */
      const listStatus = h("span", { class: "row t2c-tight" }, modelLists
        ? chip("✓ " + (modelLists.unet || []).length + " 個 unet／" + (modelLists.lora || []).length + " 個 lora", "ok")
        : chip("－ 還沒抓"));
      const fetchBtn = h("button", { class: "btn btn-sm", type: "button", title: "用存檔裡的位址問 ComfyUI", onclick: () => fetchModels() }, "從 ComfyUI 抓模型清單");

      async function fetchModels() {
        fetchBtn.disabled = true;
        listStatus.replaceChildren(chip("抓取中…"));
        try {
          const result = await FE.api("/api/comfy/models", { signal: ctx.signal });
          rememberLists(result);
          if (result && result.ok) {
            const count = (key) => (Array.isArray(result[key]) ? result[key].length : 0);
            listStatus.replaceChildren(chip("✓ " + count("unet") + " 個 unet／" + count("lora") + " 個 lora", "ok",
              "unet／clip／vae／lora／sampler／scheduler 的清單都進了卡片的下拉"));
          } else {
            listStatus.replaceChildren(h("span", { class: "t2c-small t2c-warn" }, (result && result.message) || "ComfyUI 沒有回應"));
          }
        } catch (error) {
          if (error.name === "AbortError") throw error;
          listStatus.replaceChildren(chip("✗ 抓不到", "err", error.message));
          FE.fail(error);
        } finally {
          fetchBtn.disabled = false;
        }
      }

      listsHost = h("div", {});
      drawLists();

      cardsHost = h("div", {});
      jsonError = h("div", { class: "t2c-small t2c-err" });
      jsonBox = h("textarea", { rows: 14, spellcheck: "false", style: "width:100%;font-family:monospace" });
      jsonBox.value = JSON.stringify(profiles(), null, 2);
      jsonBox.addEventListener("input", () => onJsonInput());
      jsonDetails = h("details", {},
        h("summary", {}, "進階：直接編輯 JSON"),
        h("p", { class: "muted t2c-small" }, "整包 comfy.profiles。打到一半不算：驗證過了才會套用到卡片，沒過就保留上一次有效的內容。"),
        jsonBox, jsonError);
      jsonDetails.addEventListener("toggle", () => { if (jsonDetails.open) syncJson(); });
      drawCards();

      keysHost = h("div", {});
      drawKeys();

      const vertical = h("input", { type: "checkbox", checked: draft.lettering.vertical !== false });
      vertical.addEventListener("change", () => { draft.lettering.vertical = vertical.checked; });

      ctx.view(h("div", { class: "stack t2c-page" },
        h("h1", { class: "t2c-title" }, "設定"),
        h("p", { class: "muted" }, "這裡改的是工具自己的 config.json（不進版控）。金鑰不會寫進任何檔案：先讀環境變數，沒有再讀系統金鑰庫（服務 " + service() + "）。"),
        h("p", { class: "muted" }, RESTART_HINT),
        note,

        envCard(),

        h("section", { class: "card stack" },
          h("h2", { class: "card-title" }, "語言模型（provider）"),
          h("div", { class: "row t2c-tight" }, h("span", {}, "預設 provider："), defaultSelect,
            h("span", { class: "muted t2c-small" }, "沒有指定階段 provider 時用它。")),
          h("div", { class: "row t2c-tight" }, stageKeys().map((key) => h("span", {}, key + "：", stageSelect(key)))),
          h("p", { class: "muted t2c-small" }, "階段清單由伺服器回報（含 annotate 與 plan），這裡不寫死。"),
          providerTable(),
          addProviderRow(),
          h("p", { class: "muted t2c-small" }, "「測試連線」按了才打一次 API，不會寫檔；金鑰只會存進系統金鑰庫（服務 " + service() + "、帳號＝provider id），不寫進任何檔案。環境變數優先於系統金鑰庫：key_env 有設就用它。"),
          canStore ? null : h("div", { class: "alert alert-warn" }, KEYRING_HINT)),

        h("section", { class: "card stack" },
          h("h2", { class: "card-title" }, "ComfyUI"),
          h("div", { class: "row t2c-tight" }, h("span", {}, "位址："),
            text(draft.comfy.url, (v) => { draft.comfy.url = v; }, { placeholder: "http://127.0.0.1:8188", style: "width:min(320px,100%)" }),
            fetchBtn, listStatus),
          h("p", { class: "muted t2c-small" }, MODELS_HINT),
          comfyStatus(),
          listsHost,
          cardsHost,
          jsonDetails),

        h("section", { class: "card stack" },
          h("h2", { class: "card-title" }, "嵌字"),
          h("div", { class: "row t2c-tight" },
            h("label", { class: "check" }, vertical, "直排"),
            h("span", {}, "對話字級：", nums(draft.lettering.dialogue_pt, (v) => { setNum(draft.lettering, "dialogue_pt", v); })),
            h("span", {}, "旁白字級：", nums(draft.lettering.narration_pt, (v) => { setNum(draft.lettering, "narration_pt", v); }))),
          h("p", { class: "muted" }, "字型路徑留空＝自動找（Noto CJK TC、思源、微軟正黑體）。字型不隨專案發佈。"),
          ["dialogue_font", "shout_font", "narration_font", "sfx_font"].map((key) => h("div", { class: "row t2c-tight" },
            h("span", {}, key + "："),
            text(draft.lettering[key], (v) => { draft.lettering[key] = v; }, { style: "width:min(520px,100%)" })))),

        h("section", { class: "card stack" },
          h("h2", { class: "card-title" }, "金鑰來源（唯讀）"),
          keysHost,
          h("p", { class: "muted t2c-small" }, "環境變數優先於系統金鑰庫：key_env 有設就用它，沒有才去讀系統金鑰庫（服務 " + service() + "、帳號＝provider id）。這裡不寫金鑰，也不顯示金鑰內容。")),

        h("div", { class: "row" },
          h("button", { class: "btn btn-primary", type: "button", onclick: () => save() }, "儲存"),
          h("button", { class: "btn", type: "button", onclick: () => FE.route() }, "放棄修改"))));
    }

    let loaded;
    try {
      loaded = await load();
    } catch (error) {
      if (error.name === "AbortError") throw error;
      ctx.view(h("div", { class: "alert alert-err" }, error.message));
      return;
    }
    apply(loaded);
    draw();
  };
})();
