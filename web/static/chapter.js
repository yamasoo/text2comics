// 章節頁（#/chapter/:n?tab=…）：頂端是章名、各階段狀態與「整章批次」；分頁：原著、切對話、規劃、劇本、分鏡、出圖、頁面。
// 分鏡、出圖、頁面三個分頁在 storyboard.js、panels.js、pages.js（T2C.tabs.<key>）。
(function () {
  "use strict";
  const { h, PAGES } = FE;
  const TABS = [["source", "原著"], ["annotate", "切對話"], ["plan", "規劃"], ["script", "劇本"], ["storyboard", "分鏡"], ["panels", "出圖"], ["pages", "頁面"]];
  // 任務結束時，哪些分頁要重新載入
  const REFRESH = { plan: ["plan"], script: ["script", "plan"], storyboard: ["storyboard", "script"], panels: ["panels", "render", "storyboard"], pages: ["pages", "panels", "render"] };
  T2C.tabs = T2C.tabs || {};

  const stripFront = (text) => String(text || "").replace(/^---\s*\n[\s\S]*?\n---\s*\n?/, "");

  function defaultTab(st) {
    if (!st || st.source_chars === null) return "source";
    if (st.storyboard_pages !== null) return st.rendered < st.panels ? "panels" : st.picked < st.panels ? "panels" : "pages";
    if (st.script_pages !== null) return "script";
    if (st.plan_pages !== null) return "plan";
    return "annotate";     // 有原著、還沒規劃：下一個要做的階段就是切對話
  }

  function stageChips(st) {
    const mark = (ok, label) => T2C.chip(`${ok ? "✓" : "－"} ${label}`, ok ? "ok" : "");
    if (!st) return [];
    return [mark(st.source_chars !== null, "原著"), mark(st.plan_pages !== null, "規劃"), mark(st.script_pages !== null, "劇本"),
      mark(st.storyboard_pages !== null, "分鏡"),
      T2C.chip(`出圖 ${st.rendered}／${st.panels}`, st.panels && st.rendered >= st.panels ? "ok" : ""),
      T2C.chip(`選圖 ${st.picked}／${st.panels}`, st.panels && st.picked >= st.panels ? "ok" : ""),
      T2C.chip(`頁面 ${st.pages_out}`, st.pages_out ? "ok" : "")];
  }

  PAGES["chapter/:n"] = async (ctx) => {
    if (!T2C.need(ctx, "章節")) return;
    const n = parseInt(ctx.params.n, 10);
    if (!(n > 0 && n < 1000)) throw new Error("章節編號要是 1–999");
    FE.store.set("chapter", n);
    const overview = await FE.api("/api/project", { query: { project: T2C.project() }, signal: ctx.signal });
    const st = overview.chapters.find((c) => c.chapter === n) || null;
    const tab = TABS.some(([k]) => k === ctx.query.tab) ? ctx.query.tab : defaultTab(st);
    const numbers = overview.chapters.map((c) => c.chapter);
    ctx.crumbs([{ label: `《${overview.title}》`, href: "#/project" }, { label: `第 ${n} 章` }, { label: TABS.find(([k]) => k === tab)[1] }]);

    const body = h("div", { class: "tab-panel" });
    const prev = numbers.filter((x) => x < n).pop();
    const next = numbers.find((x) => x > n);
    const batch = async () => {
      let env = null;
      try { env = await T2C.get("/api/env", {}, ctx); } catch (error) { if (error.name === "AbortError") return; }
      T2C.batchDialog(n, env);
    };
    ctx.view(h("div", { class: "stack t2c-page" },
      h("div", { class: "row" },
        h("h1", { class: "t2c-title grow" }, `第 ${n} 章`, st && st.title ? `　${st.title}` : ""),
        prev ? h("a", { class: "btn btn-sm btn-ghost", href: FE.hash("chapter", prev, { tab }) }, `← 第 ${prev} 章`) : null,
        next ? h("a", { class: "btn btn-sm btn-ghost", href: FE.hash("chapter", next, { tab }) }, `第 ${next} 章 →`) : null,
        h("button", { class: "btn", type: "button", onclick: batch, title: "規劃 → 劇本 → 分鏡 → 出圖 → 輸出頁面" }, "整章批次…")),
      h("div", { class: "row t2c-tight" }, stageChips(st)),
      h("nav", { class: "tabs", role: "tablist" }, TABS.map(([key, label]) => h("a", {
        class: ["tab", key === tab && "active"], role: "tab", "aria-selected": key === tab ? "true" : "false",
        href: FE.hash("chapter", n, { tab: key }),
      }, label))),
      body));

    T2C.onJobEnd(ctx, (job, r) => {
      if (!(r.refresh || []).length) return;
      if (REFRESH[tab] && !r.refresh.some((k) => REFRESH[tab].includes(k)) && tab !== "source") return;
      if (FE.dirty.is()) FE.toast("任務完成；存檔或放棄修改後再重新整理，才看得到新結果", "warn");
      else FE.route();
    }, n);

    await T2C.tabs[tab](ctx, body, { n, status: st, overview });
  };

  /* ──────────────── 原著 ──────────────── */
  T2C.tabs.source = async (ctx, body, { n }) => {
    const data = await T2C.get("/api/chapter/source", { chapter: n }, ctx);
    const stats = h("span", { class: "muted" });
    const showStats = (text) => {
      const plain = stripFront(text).trim();
      stats.textContent = `${plain.length} 字（儲存後估算 token：約 ${data.tokens}）`;
    };
    const editor = T2C.editor(data.text, { rows: 28, oninput: showStats, onsave: () => save() });
    showStats(data.text);
    async function save() {
      try {
        await T2C.post("/api/chapter/source", { chapter: n, text: editor.value }, ctx);
        FE.dirty.set(false);
        FE.toast("已存檔", "ok");
        FE.route();
      } catch (error) { FE.fail(error); }
    }
    async function importFile() {
      const path = await FE.filepicker.open({ mode: "file", exts: [".txt", ".md"], title: "選擇原著（UTF-8 的 .txt 或 .md）" });
      if (!path) return;
      if (data.exists && !(await FE.confirm(`要用 ${path} 取代目前的原著嗎？`, { ok: "取代" }))) return;
      try {
        await T2C.post("/api/chapter/source", { chapter: n, path }, ctx);
        FE.dirty.set(false);
        FE.route();
      } catch (error) { FE.fail(error); }
    }
    body.replaceChildren(h("div", { class: "stack" },
      h("div", { class: "row" },
        h("span", { class: "muted grow" }, data.exists ? data.path : `還沒有原著；貼上後按「存檔」會寫到 ${data.path}`),
        stats,
        h("button", { class: "btn", type: "button", onclick: importFile }, "從檔案匯入…"),
        h("button", { class: "btn btn-primary", type: "button", onclick: save }, "存檔")),
      editor,
      data.exists ? h("div", { class: "row" }, h("a", { class: "btn", href: FE.hash("chapter", n, { tab: "plan" }) }, "下一步：改編規劃 →")) : null));
  };

  /* ──────────────── 切對話 ──────────────── */
  const LINE_TYPE = { narration: "旁白", dialogue: "對話", action: "演出" };

  T2C.tabs.annotate = async (ctx, body, { n, status, overview }) => {
    const [data] = await Promise.all([T2C.get("/api/chapter/scenes", { chapter: n }, ctx), FE.md.load()]);
    T2C.onJobEnd(ctx, (job, r) => { if ((r.refresh || []).includes("annotate") && !FE.dirty.is()) FE.route(); });
    const names = Object.fromEntries((((overview || {}).bible || {}).characters || []).map((c) => [c.id, c.name]));
    const generate = async (force) => {
      const ok = await FE.confirm(force
        ? `重新切一份要呼叫語言模型，而且會覆蓋 ${data.path}（你手改過的部分也會蓋掉）。`
        : "切對話要呼叫語言模型：它把這一章切成幾場，再把每一句分成旁白、對話、演出。要開始嗎？",
        { ok: force ? "覆蓋並重新切" : "開始切對話", danger: !!force });
      if (!ok) return;
      T2C.run("/api/task/adapt", { chapter: n, stage: "annotate", force });
    };
    const genBtn = h("button", { class: data.exists ? "btn" : "btn btn-primary", type: "button", onclick: () => generate(!!data.exists) },
      data.exists ? "重新切一份（覆蓋）" : "產生切對話（模型）…");

    if (!data.exists) {
      body.replaceChildren(h("div", { class: "stack" },
        status && status.source_chars !== null
          ? h("p", {}, "小說 → 場 → 旁白／對話／演出：語言模型把這一章切成幾場，每一句都回指原著的段落。台詞逐字保留，漏掉的句子程式會自動補回來。")
          : h("div", { class: "alert alert-warn" }, "還沒有原著：先到「原著」分頁貼上這一章。"),
        h("div", { class: "row" }, genBtn)));
      return;
    }

    const doc = data.scenes || {};
    const scenes = doc.scenes || [];
    const sceneBlock = (scene, index) => {
      const lines = (scene && scene.lines) || [];
      return h("details", { class: "card card-flat", open: index === 0 },
        h("summary", {}, h("b", {}, `第 ${index + 1} 場`), (scene && scene.title) ? `　${scene.title}` : "", " ", T2C.chip(`${lines.length} 行`)),
        h("ul", { class: "stack t2c-tight" }, lines.map((line) => h("li", { class: "row t2c-tight" },
          T2C.chip(LINE_TYPE[line.type] || line.type, line.type === "dialogue" ? "ok" : ""),
          line.speaker ? h("span", {}, names[line.speaker] || line.speaker) : null,
          h("span", { class: "grow" }, line.text),
          typeof line.source_para === "number" ? h("span", { class: "muted t2c-small" }, `原文第 ${line.source_para} 段`) : null))));
    };

    body.replaceChildren(h("div", { class: "stack" },
      h("div", { class: "row" },
        h("h2", { class: "t2c-h2" }, doc.title ? `《${doc.title}》` : "切對話"),
        h("span", { class: "muted t2c-small grow" }, `${scenes.length} 場　${data.path}`),
        genBtn),
      data.fidelity ? h("details", { class: "card card-flat" }, h("summary", {}, "忠實度報告"), FE.md.render(data.fidelity)) : null,
      scenes.map(sceneBlock),
      h("div", { class: "row" }, h("a", { class: "btn btn-primary", href: FE.hash("chapter", n, { tab: "plan" }) }, "下一步：改編規劃 →"))));
  };

  /* ──────────────── 規劃 ──────────────── */
  T2C.tabs.plan = async (ctx, body, { n, status, overview }) => {
    const data = await T2C.get("/api/chapter/plan", { chapter: n }, ctx);
    const pages = T2C.num("", { min: 1, max: 60, placeholder: "自動" });
    const title = h("input", { type: "text", placeholder: "章名（留空沿用原著）" });
    const generate = async (force) => {
      if (force && !(await FE.confirm("重新產生會覆蓋目前的規劃（plan/ch%03d.json）。之後的劇本、分鏡不會自動跟著改。".replace("%03d", String(n).padStart(3, "0")), { ok: "覆蓋並重新產生", danger: true }))) return;
      T2C.run("/api/task/adapt", { chapter: n, stage: "plan", pages: pages.value ? Number(pages.value) : null, title: title.value.trim(), force });
    };
    const genRow = h("div", { class: "row" },
      h("label", { class: "row t2c-inline" }, "頁數", pages), title,
      h("button", { class: data.plan ? "btn" : "btn btn-primary", type: "button", onclick: () => generate(!!data.plan) }, data.plan ? "重新產生（覆蓋）" : "產生改編規劃"));
    if (!data.plan) {
      body.replaceChildren(h("div", { class: "stack" },
        status && status.source_chars !== null
          ? h("p", {}, "LLM 讀整章原著，決定分幾頁、每頁用哪個格子模板、每格演什麼。")
          : h("div", { class: "alert alert-warn" }, "還沒有原著：先到「原著」分頁貼上這一章。"),
        T2C.issues(data.issues), genRow));
      return;
    }
    const plan = data.plan;
    const names = Object.fromEntries((overview.bible.characters || []).map((c) => [c.id, c.name]));
    const charName = (id) => names[id] || id;
    const pageCards = plan.pages.map((p) => h("section", { class: "card card-flat stack t2c-tight" },
      h("div", { class: "row" }, h("b", {}, `第 ${p.page} 頁`), T2C.chip(`模板 ${p.template}${data.templates[p.template] ? "：" + data.templates[p.template].name : ""}`),
        h("span", { class: "grow" }, p.purpose || ""), p.hook ? h("span", { class: "muted" }, `翻頁點：${p.hook}`) : null),
      h("table", { class: "table" },
        h("thead", {}, h("tr", {}, ["格", "節拍", "角色", "地點", "原著依據"].map((t) => h("th", {}, t)))),
        h("tbody", {}, (p.panels || []).map((k) => h("tr", {},
          h("td", { class: "num" }, k.slot), h("td", {}, k.beat), h("td", {}, (k.characters || []).map(charName).join("、")),
          h("td", {}, k.location || ""), h("td", { class: "muted" }, k.source || "")))))));
    const raw = T2C.editor(JSON.stringify(plan, null, 2), { rows: 30, mono: true, onsave: () => saveRaw() });
    async function saveRaw() {
      let parsed;
      try { parsed = JSON.parse(raw.value); } catch (error) { return FE.toast(`不是合法的 JSON：${error.message}`, "err"); }
      try {
        const result = await T2C.post("/api/chapter/plan", { chapter: n, plan: parsed }, ctx);
        FE.dirty.set(false);
        FE.toast(result.issues.length ? `已存檔（${result.issues.length} 則提醒）` : "已存檔", "ok");
        FE.route();
      } catch (error) { FE.fail(error); }
    }
    body.replaceChildren(h("div", { class: "stack" },
      h("div", { class: "row" }, h("h2", { class: "grow t2c-h2" }, `《${plan.title}》${plan.pages.length} 頁`),
        h("a", { class: "btn btn-primary", href: FE.hash("chapter", n, { tab: "script" }) }, "下一步：劇本 →")),
      plan.summary ? h("p", {}, plan.summary) : null,
      T2C.issues(data.issues),
      plan.unlisted_characters && plan.unlisted_characters.length
        ? h("div", { class: "alert alert-warn" }, `聖經沒有卡片的人物：${plan.unlisted_characters.join("、")}。他們只能當旁白或刪掉；要入鏡請先到 `, h("a", { href: "#/bible" }, "視覺聖經"), " 新增卡片。")
        : null,
      pageCards,
      plan.omitted && plan.omitted.length ? h("details", { class: "card card-flat" }, h("summary", {}, `刪減的原著內容（${plan.omitted.length}）`),
        h("ul", {}, plan.omitted.map((x) => h("li", {}, x)))) : null,
      h("details", { class: "card card-flat" }, h("summary", {}, "直接編輯 JSON（進階）"),
        h("div", { class: "stack" }, raw, h("div", { class: "row" }, h("button", { class: "btn btn-primary", type: "button", onclick: saveRaw }, "存檔（先過檢查）")))),
      h("details", { class: "card card-flat" }, h("summary", {}, "重新產生"), genRow)));
  };

  /* ──────────────── 劇本 ──────────────── */
  T2C.tabs.script = async (ctx, body, { n, status }) => {
    const [data] = await Promise.all([T2C.get("/api/chapter/script", { chapter: n }, ctx), FE.md.load()]);
    const pageSel = h("select", {}, h("option", { value: "" }, "整章"), (data.pages || []).map((p) => h("option", { value: p.page }, `只重寫第 ${p.page} 頁`)));
    const generate = async () => {
      const page = pageSel.value ? Number(pageSel.value) : null;
      if (data.exists && !page && !(await FE.confirm("重新產生整章劇本會覆蓋 script/ch%03d.md（你改過的也會蓋掉）。".replace("%03d", String(n).padStart(3, "0")), { ok: "覆蓋並重新產生", danger: true }))) return;
      T2C.run("/api/task/adapt", { chapter: n, stage: "script", page, force: data.exists && !page });
    };
    const genRow = h("div", { class: "row" }, data.exists ? pageSel : null,
      h("button", { class: data.exists ? "btn" : "btn btn-primary", type: "button", onclick: generate }, data.exists ? "重新產生" : "產生劇本"));
    if (!data.exists) {
      body.replaceChildren(h("div", { class: "stack" },
        status && status.plan_pages !== null ? h("p", {}, "LLM 依改編規劃逐頁寫漫畫劇本（台詞、旁白、鏡頭）。寫好之後可以直接在這裡改。")
          : h("div", { class: "alert alert-warn" }, "還沒有改編規劃：先到「規劃」分頁產生。"),
        genRow));
      return;
    }
    let editing = ctx.query.edit === "1";
    const editor = T2C.editor(data.text, { rows: 34, onsave: () => save() });
    async function save() {
      try {
        const result = await T2C.post("/api/chapter/script", { chapter: n, text: editor.value }, ctx);
        FE.dirty.set(false);
        const errs = result.issues.filter((i) => i.level === "error").length;
        FE.toast(errs ? `已存檔，但有 ${errs} 個問題（分鏡階段會被擋）` : "已存檔", errs ? "warn" : "ok");
        FE.go(FE.hash("chapter", n, { tab: "script" }));
      } catch (error) { FE.fail(error); }
    }
    const view = h("div", { class: "t2c-script" }, FE.md.render(stripFront(data.text)));
    const holder = h("div", {}, editing ? editor : view);
    const toggle = h("button", { class: "btn", type: "button", onclick: async () => {
      if (editing && FE.dirty.is() && !(await FE.dirty.confirm())) return;
      editing = !editing;
      holder.replaceChildren(editing ? editor : view);
      toggle.textContent = editing ? "檢視" : "編輯";
      saveBtn.style.display = editing ? "" : "none";
    } }, editing ? "檢視" : "編輯");
    const saveBtn = h("button", { class: "btn btn-primary", type: "button", style: { display: editing ? "" : "none" }, onclick: save }, "存檔");
    body.replaceChildren(h("div", { class: "stack" },
      h("div", { class: "row" }, h("span", { class: "muted grow t2c-small" }, `${data.pages.length} 頁　${data.path}`), toggle, saveBtn,
        h("a", { class: "btn btn-primary", href: FE.hash("chapter", n, { tab: "storyboard" }) }, "下一步：分鏡 →")),
      T2C.issues(data.issues, { title: "劇本檢查" }),
      holder,
      data.fidelity ? h("details", { class: "card card-flat" }, h("summary", {}, "忠實度報告（台詞和原著的對照）"), FE.md.render(data.fidelity)) : null,
      h("details", { class: "card card-flat" }, h("summary", {}, "重新產生"), genRow)));
  };
})();
