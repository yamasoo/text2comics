// 章節頁的「分鏡」分頁：一頁一張表、一格一列；點一列打開這一格的編輯區（欄位＋框編輯器＋送給 MOSS 的提示詞）。
// 座標一律是比例 [x0, y0, x1, y1]（相對於這一格生成的圖），見 docs/02_資料格式.md 第 5 節。
// 存檔先過 compile_chapter（不過就擋），其他檢查列成提醒（docs/05_介面設計.md 原則 5）。
(function () {
  "use strict";
  const { h, svg } = FE;
  const r3 = (v) => Math.round(v * 1000) / 1000;
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const copy = (v) => JSON.parse(JSON.stringify(v));
  const pid = (page, panel) => panel.id || `p${String(page.page).padStart(3, "0")}_k${panel.slot}`;
  const MIN = 0.03;

  T2C.tabs.storyboard = async (ctx, body, { n, status }) => {
    const data = await T2C.get("/api/chapter/storyboard", { chapter: n }, ctx);
    const vocab = data.vocab;
    const pageSel = h("select", {}, h("option", { value: "" }, "整章"),
      ((data.storyboard && data.storyboard.pages) || []).map((p) => h("option", { value: p.page }, `只重做第 ${p.page} 頁`)));
    const generate = async () => {
      const page = pageSel.value ? Number(pageSel.value) : null;
      const exists = !!data.storyboard;
      if (exists && !page && !(await FE.confirm("重新產生整章分鏡會覆蓋目前的分鏡（你改過的也會蓋掉）。挑圖紀錄以格子 id 對應，格子不變就還能用。", { ok: "覆蓋並重新產生", danger: true }))) return;
      T2C.run("/api/task/adapt", { chapter: n, stage: "storyboard", page, force: exists && !page });
    };
    const genRow = h("div", { class: "row" }, data.storyboard ? pageSel : null,
      h("button", { class: data.storyboard ? "btn" : "btn btn-primary", type: "button", onclick: generate }, data.storyboard ? "重新產生" : "產生分鏡"));

    if (!data.storyboard) {
      body.replaceChildren(h("div", { class: "stack" },
        data.compile_error ? h("div", { class: "alert alert-err" }, data.compile_error) : null,
        status && status.script_pages !== null ? h("p", {}, "LLM 依劇本逐頁寫分鏡 JSON（每格的畫面、角色位置、對話框），通過編譯檢查才會存檔。")
          : h("div", { class: "alert alert-warn" }, "還沒有劇本：先到「劇本」分頁產生。"),
        genRow));
      return;
    }

    /* ── 狀態 ── */
    const st = {
      board: copy(data.storyboard),
      issues: data.issues,
      compileError: data.compile_error,
      sel: null,              // {pi, ki}
      item: null,             // 框編輯器裡選中的 {type: "char"|"obj"|"sfx"|"bubble", index}
      picks: {},              // 格 id → 選圖檔名（框編輯器的底圖）
      prompt: null,
      promptTimer: null,
    };
    try {
      const pn = await T2C.get("/api/chapter/panels", { chapter: n }, ctx);
      for (const p of pn.panels) {
        const name = (p.pick && p.pick.image) || (p.candidates[0] && p.candidates[0].file);
        if (name) st.picks[p.id] = `${pn.renders}/${name}`;
      }
    } catch (error) { if (error.name === "AbortError") throw error; }

    const charName = (id) => (vocab.characters.find((c) => c.id === id) || { name: id }).name;
    const locName = (id) => (vocab.locations.find((c) => c.id === id) || { name: id }).name;
    const changed = (opts = {}) => {
      FE.dirty.set(true);
      statusEl.textContent = "尚未存檔";
      if (opts.table !== false) drawTables();
      if (opts.editor) drawEditor();
      else if (opts.canvas) drawCanvas();
      schedulePrompt();
    };

    /* ── 骨架 ── */
    const statusEl = h("span", { class: "muted" });
    const issuesEl = h("div");
    const tablesEl = h("div", { class: "stack" });
    const editorEl = h("div", { class: "stack sb-editor" });
    body.replaceChildren(h("div", { class: "stack" },
      h("div", { class: "row" },
        h("span", { class: "muted grow" }, data.path),
        statusEl,
        h("button", { class: "btn", type: "button", onclick: () => discard() }, "放棄修改"),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => save() }, "存檔"),
        h("a", { class: "btn btn-primary", href: FE.hash("chapter", n, { tab: "panels" }) }, "下一步：出圖 →")),
      issuesEl,
      h("div", { class: "sb-wrap" }, tablesEl, editorEl),
      h("details", { class: "card card-flat" }, h("summary", {}, "重新產生"), genRow)));
    drawIssues();
    drawTables();
    drawEditor();

    function drawIssues() {
      issuesEl.replaceChildren(
        st.compileError ? h("div", { class: "alert alert-err" }, `無法編譯：${st.compileError}`) : null,
        T2C.issues(st.issues, { title: "分鏡檢查", open: false }));
    }

    /* ── 表格 ── */
    function drawTables() {
      tablesEl.replaceChildren(...st.board.pages.map((page, pi) => {
        const tpl = vocab.templates[page.template];
        return h("section", { class: "card card-flat stack t2c-tight" },
          h("div", { class: "row" }, h("b", {}, `第 ${page.page} 頁`),
            h("select", { "aria-label": "模板", onchange: (e) => changeTemplate(pi, e.target.value) },
              Object.entries(vocab.templates).map(([k, t]) => h("option", { value: k, selected: k === page.template }, `${k}：${t.name}（${t.panels.length} 格）`))),
            h("span", { class: "grow" }),
            pi === st.board.pages.length - 1 && st.board.pages.length > 1
              ? h("button", { class: "btn btn-sm btn-ghost", type: "button", onclick: () => removeLastPage() }, "刪除這一頁") : null),
          h("div", { class: "sb-pagewrap" }, tpl ? miniPage(page, pi, tpl) : null,
            h("table", { class: "table sb-table" },
              h("thead", {}, h("tr", {}, ["格", "鏡頭", "地點", "畫面", "角色", "台詞"].map((t) => h("th", {}, t)))),
              h("tbody", {}, page.panels.map((panel, ki) => h("tr", {
                class: ["sb-row", st.sel && st.sel.pi === pi && st.sel.ki === ki && "sb-sel"],
                onclick: () => select(pi, ki),
              },
                h("td", { class: "num" }, panel.slot),
                h("td", {}, `${T2C.shot[panel.shot || "medium"] || panel.shot}${panel.angle && panel.angle !== "eye" ? "・" + (T2C.angle[panel.angle] || panel.angle) : ""}`),
                h("td", {}, panel.location ? locName(panel.location) : h("span", { class: "muted" }, "－")),
                h("td", {}, h("div", { class: "sb-scene" }, panel.scene || h("span", { class: "t2c-err" }, "（缺畫面）"))),
                h("td", {}, (panel.characters || []).map((c) => charName(c.id)).join("、")),
                h("td", { class: "sb-lines" }, (panel.bubbles || []).map((b) => h("div", {}, h("span", { class: "muted" }, `${T2C.kind[b.kind || "speech"]}${b.speaker ? "・" + charName(b.speaker) : ""}：`), String(b.text || "").replace(/\n/g, "／"))))))))));
      }), h("div", { class: "row" }, h("button", { class: "btn btn-sm", type: "button", onclick: addPage }, "＋ 新增一頁")));
    }

    function miniPage(page, pi, tpl) {
      const W = 100, H = 100 * vocab.page.height_mm / vocab.page.width_mm;
      return svg("svg", { class: "sb-mini", viewBox: `0 0 ${W} ${H}`, "aria-label": "格子配置（右翻）" },
        tpl.panels.map((b, i) => {
          const ki = page.panels.findIndex((p) => p.slot === i + 1);
          const sel = st.sel && st.sel.pi === pi && st.sel.ki === ki;
          return svg("g", { class: ["sb-mini-cell", sel && "sb-sel"], onclick: () => ki >= 0 && select(pi, ki) },
            svg("rect", { x: b[0] * W + 1, y: b[1] * H + 1, width: (b[2] - b[0]) * W - 2, height: (b[3] - b[1]) * H - 2 }),
            svg("text", { x: (b[0] + b[2]) / 2 * W, y: (b[1] + b[3]) / 2 * H + 3 }, String(i + 1)));
        }));
    }

    function changeTemplate(pi, key) {
      const page = st.board.pages[pi];
      const count = vocab.templates[key].panels.length;
      if (page.panels.length > count && !window.confirm(`模板「${key}」只有 ${count} 格，第 ${count + 1} 格以後會被刪掉。確定嗎？`)) return drawTables();
      page.template = key;
      page.panels = page.panels.slice(0, count);
      for (let s = page.panels.length + 1; s <= count; s += 1) {
        page.panels.push({ slot: s, id: `p${String(page.page).padStart(3, "0")}_k${s}`, shot: "medium", angle: "eye", scene: "", characters: [], bubbles: [] });
      }
      if (st.sel && st.sel.pi === pi && st.sel.ki >= count) st.sel = null;
      changed({ editor: true });
    }
    function addPage() {
      const no = st.board.pages.length ? Math.max(...st.board.pages.map((p) => p.page)) + 1 : 1;
      st.board.pages.push({ page: no, template: "1", panels: [{ slot: 1, id: `p${String(no).padStart(3, "0")}_k1`, shot: "medium", angle: "eye", scene: "", characters: [], bubbles: [] }] });
      st.sel = { pi: st.board.pages.length - 1, ki: 0 };
      changed({ editor: true });
    }
    function removeLastPage() {
      if (!window.confirm(`刪除第 ${st.board.pages[st.board.pages.length - 1].page} 頁？（存檔後才生效）`)) return;
      st.board.pages.pop();
      st.sel = null;
      changed({ editor: true });
    }

    function select(pi, ki) {
      st.sel = { pi, ki };
      st.item = null;
      st.prompt = null;
      drawTables();
      drawEditor();
      schedulePrompt(0);
      if (getComputedStyle(editorEl).position !== "sticky") editorEl.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    function current() { return st.sel ? st.board.pages[st.sel.pi].panels[st.sel.ki] : null; }
    function currentId() { return st.sel ? pid(st.board.pages[st.sel.pi], current()) : ""; }

    /* ── 一格的編輯區 ── */
    var canvasEl = null;     // var：上面先呼叫 drawEditor()，宣告要提升
    var promptEl = null;
    function drawEditor() {
      const panel = current();
      if (!panel) {
        editorEl.replaceChildren(h("div", { class: "empty" }, "點表格的一列，編輯那一格。"));
        return;
      }
      const field = (label, input, hint) => h("label", { class: "field" }, label, input, hint ? h("span", { class: "field-hint" }, hint) : null);
      const select = (value, options, onchange, empty) => h("select", { onchange: (e) => onchange(e.target.value) },
        empty !== undefined ? h("option", { value: "" }, empty) : null,
        options.map(([v, label]) => h("option", { value: v, selected: v === value }, label)));
      const text = (value, oninput, opts = {}) => h(opts.multi ? "textarea" : "input", Object.assign({
        type: opts.multi ? undefined : "text", rows: opts.rows, value: opts.multi ? undefined : value || "",
        oninput: (e) => { oninput(e.target.value); changed(); },
      }, opts.attrs || {}), opts.multi ? value || "" : null);
      const present = (panel.characters || []).map((c) => c.id);

      canvasEl = h("div", { class: "sb-canvas-wrap" });
      promptEl = h("div", { class: "sb-prompt" });
      const lists = h("div", { class: "stack" });
      const list = (title, key, row, add) => h("section", { class: "stack t2c-tight" },
        h("div", { class: "row" }, h("b", { class: "grow" }, title), h("button", { class: "btn btn-sm", type: "button", onclick: add }, "＋ 新增")),
        (panel[key] || []).map((item, i) => h("div", { class: ["sb-item", st.item && st.item.key === key && st.item.index === i && "sb-sel"], onclick: (e) => { if (e.target === e.currentTarget) pickItem(key, i); } },
          row(item, i),
          h("div", { class: "row t2c-tight" },
            i > 0 ? h("button", { class: "btn btn-sm btn-ghost", type: "button", title: "往前", onclick: () => move(key, i, -1) }, "↑") : null,
            h("button", { class: "btn btn-sm btn-ghost", type: "button", onclick: () => pickItem(key, i) }, "在圖上選取"),
            h("button", { class: "btn btn-sm btn-ghost", type: "button", onclick: () => { panel[key].splice(i, 1); st.item = null; changed({ editor: true }); } }, "刪除")))));

      lists.append(
        list("角色", "characters", (c) => h("div", { class: "sb-grid" },
          field("角色", select(c.id, vocab.characters.map((x) => [x.id, `${x.name}（${x.id}）`]), (v) => { c.id = v; c.outfit = "default"; changed({ editor: true }); })),
          field("服裝", select(c.outfit || "default", ((vocab.characters.find((x) => x.id === c.id) || {}).outfits || ["default"]).map((o) => [o, o]), (v) => { c.outfit = v; changed(); })),
          field("姿勢（英文）", text(c.pose, (v) => { c.pose = v; })),
          field("表情（英文）", text(c.expression, (v) => { c.expression = v; })),
          h("div", { class: "muted t2c-small sb-box" }, `框 ${(c.box || [0.25, 0.1, 0.75, 1]).join(", ")}`)),
        () => {
          const free = vocab.characters.find((x) => !present.includes(x.id));
          if (!free) return FE.toast("聖經裡的角色都已經在這一格了", "warn");
          panel.characters = panel.characters || [];
          panel.characters.push({ id: free.id, outfit: "default", pose: "", expression: "", box: [0.3, 0.1, 0.7, 1] });
          st.item = { key: "characters", index: panel.characters.length - 1 };
          changed({ editor: true });
        }),
        list("對話框（依閱讀順序）", "bubbles", (b) => h("div", { class: "sb-grid" },
          field("種類", select(b.kind || "speech", Object.entries(T2C.kind), (v) => { b.kind = v; if (v === "narration") delete b.speaker; changed({ editor: true }); })),
          (b.kind || "speech") !== "narration"
            ? field("說話的人", select(b.speaker || "", present.map((id) => [id, charName(id)]), (v) => { b.speaker = v; changed(); }, "（選一個在場的角色）")) : h("span"),
          h("div", { class: "sb-span" }, field("台詞", text(b.text, (v) => { b.text = v; }, { multi: true, rows: 2 }), "要換行就直接按 Enter（每行 12 字內；旁白 16 字）")),
          h("div", { class: "muted t2c-small sb-box" }, `位置 ${(b.anchor || [0.5, 0.2]).join(", ")}`)),
        () => {
          panel.bubbles = panel.bubbles || [];
          panel.bubbles.push(present.length ? { kind: "speech", speaker: present[0], text: "", anchor: [0.5, 0.15] } : { kind: "narration", text: "", anchor: [0.85, 0.1] });
          st.item = { key: "bubbles", index: panel.bubbles.length - 1 };
          changed({ editor: true });
        }),
        list("物件", "objects", (o) => h("div", { class: "sb-grid" },
          h("div", { class: "sb-span" }, field("描述（英文）", text(o.caption, (v) => { o.caption = v; }))),
          h("div", { class: "muted t2c-small sb-box" }, `框 ${(o.box || []).join(", ")}`)),
        () => { panel.objects = panel.objects || []; panel.objects.push({ caption: "", box: [0.4, 0.4, 0.6, 0.6] }); st.item = { key: "objects", index: panel.objects.length - 1 }; changed({ editor: true }); }),
        list("狀聲詞", "sfx", (s) => h("div", { class: "sb-grid" },
          field("字", text(s.text, (v) => { s.text = v; })),
          h("div", { class: "muted t2c-small sb-box" }, `框 ${(s.box || []).join(", ")}`)),
        () => { panel.sfx = panel.sfx || []; panel.sfx.push({ text: "", box: [0.7, 0.05, 0.95, 0.4] }); st.item = { key: "sfx", index: panel.sfx.length - 1 }; changed({ editor: true }); }));

      editorEl.replaceChildren(
        h("div", { class: "row" }, h("h3", { class: "t2c-h2 grow" }, `第 ${st.board.pages[st.sel.pi].page} 頁第 ${panel.slot} 格`), h("code", {}, currentId())),
        h("div", { class: "sb-grid" },
          field("鏡頭", select(panel.shot || "medium", vocab.shots.map((k) => [k, `${T2C.shot[k]}（${k}）`]), (v) => { panel.shot = v; changed(); })),
          field("角度", select(panel.angle || "eye", vocab.angles.map((k) => [k, `${T2C.angle[k]}（${k}）`]), (v) => { panel.angle = v; changed(); })),
          field("地點", select(panel.location || "", vocab.locations.map((x) => [x.id, `${x.name}（${x.id}）`]), (v) => { if (v) panel.location = v; else delete panel.location; changed(); }, "（不指定）")),
          h("div", { class: "sb-span" }, field("畫面（英文，不寫角色外觀）", text(panel.scene, (v) => { panel.scene = v; }, { multi: true, rows: 3 })))),
        canvasEl,
        lists,
        h("details", { class: "card card-flat", open: FE.store.get("sb.prompt", false), ontoggle: (e) => FE.store.set("sb.prompt", e.target.open) },
          h("summary", {}, "送給 MOSS 的提示詞（依目前的編輯即時編譯）"), promptEl));
      drawCanvas();
      drawPrompt();
    }

    function move(key, i, d) {
      const list = current()[key];
      [list[i + d], list[i]] = [list[i], list[i + d]];
      st.item = { key, index: i + d };
      changed({ editor: true });
    }
    function pickItem(key, index) {
      st.item = { key, index };
      drawEditor();
    }

    /* ── 框編輯器 ── */
    function aspect() {
      if (st.prompt && st.prompt.id === currentId()) return st.prompt.width / st.prompt.height;
      const page = st.board.pages[st.sel.pi];
      const b = (vocab.templates[page.template] || { panels: [] }).panels[current().slot - 1] || [0, 0, 1, 1];
      return ((b[2] - b[0]) * vocab.page.width_mm) / ((b[3] - b[1]) * vocab.page.height_mm);
    }
    function drawCanvas() {
      if (!canvasEl || !current()) return;
      const panel = current();
      const W = 1000, H = Math.round(1000 / aspect());
      const bg = st.picks[currentId()];
      const root = svg("svg", { class: "sb-canvas", viewBox: `0 0 ${W} ${H}` });
      if (bg) root.append(svg("image", { href: T2C.img(bg, 800), x: 0, y: 0, width: W, height: H, preserveAspectRatio: "none", opacity: 0.55 }));
      else root.append(svg("rect", { x: 0, y: 0, width: W, height: H, class: "sb-bg" }));
      const boxes = [["characters", "sb-char", (c) => charName(c.id)], ["objects", "sb-obj", (o) => o.caption || "物件"], ["sfx", "sb-sfx", (s) => s.text || "狀聲詞"]];
      for (const [key, cls, label] of boxes) {
        (panel[key] || []).forEach((item, index) => {
          if (key === "characters" && !item.box) item.box = [0.25, 0.1, 0.75, 1];
          if (!item.box) return;
          const [x0, y0, x1, y1] = item.box;
          const sel = st.item && st.item.key === key && st.item.index === index;
          const g = svg("g", { class: [cls, sel && "sb-sel"] },
            svg("rect", { x: x0 * W, y: y0 * H, width: (x1 - x0) * W, height: (y1 - y0) * H, class: "sb-rect" }),
            svg("text", { x: x0 * W + 8, y: y0 * H + 30, class: "sb-label" }, label(item)),
            svg("rect", { x: x1 * W - 14, y: y1 * H - 14, width: 28, height: 28, class: "sb-handle" }));
          g.addEventListener("pointerdown", (e) => startDrag(e, key, index, e.target.classList.contains("sb-handle") ? "resize" : "move", W, H));
          root.append(g);
        });
      }
      (panel.bubbles || []).forEach((b, index) => {
        if (!b.anchor) b.anchor = [0.5, 0.2];
        const sel = st.item && st.item.key === "bubbles" && st.item.index === index;
        const g = svg("g", { class: ["sb-bubble", sel && "sb-sel"] },
          svg("circle", { cx: b.anchor[0] * W, cy: b.anchor[1] * H, r: 22 }),
          svg("text", { x: b.anchor[0] * W, y: b.anchor[1] * H + 9, class: "sb-num" }, String(index + 1)));
        g.addEventListener("pointerdown", (e) => startDrag(e, "bubbles", index, "anchor", W, H));
        root.append(g);
      });
      canvasEl.replaceChildren(root, h("p", { class: "muted t2c-small" },
        bg ? "底圖是目前選的（或第一張）候選圖。" : "還沒有出圖，底圖是空白。",
        " 拖框移動、拖右下角改大小；藍點是對話框的希望位置（數字是閱讀順序）。框只是建議位置，MOSS 不一定照畫。"));
    }

    function startDrag(e, key, index, mode, W, H) {
      e.preventDefault();
      e.stopPropagation();
      const root = e.currentTarget.ownerSVGElement;
      const item = current()[key][index];
      const start = toRatio(root, e, W, H);
      const orig = mode === "anchor" ? item.anchor.slice() : item.box.slice();
      st.item = { key, index };
      root.setPointerCapture && e.target.setPointerCapture && e.target.setPointerCapture(e.pointerId);
      const onMove = (ev) => {
        const p = toRatio(root, ev, W, H);
        const dx = p[0] - start[0], dy = p[1] - start[1];
        if (mode === "anchor") {
          item.anchor = [r3(clamp(orig[0] + dx, 0, 1)), r3(clamp(orig[1] + dy, 0, 1))];
        } else if (mode === "move") {
          const w = orig[2] - orig[0], hgt = orig[3] - orig[1];
          const x0 = clamp(orig[0] + dx, 0, 1 - w), y0 = clamp(orig[1] + dy, 0, 1 - hgt);
          item.box = [r3(x0), r3(y0), r3(x0 + w), r3(y0 + hgt)];
        } else {
          item.box = [orig[0], orig[1], r3(clamp(orig[2] + dx, orig[0] + MIN, 1)), r3(clamp(orig[3] + dy, orig[1] + MIN, 1))];
        }
        drawCanvas();
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        changed({ editor: true });
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    }
    function toRatio(root, e, W, H) {
      const pt = root.createSVGPoint();
      pt.x = e.clientX;
      pt.y = e.clientY;
      const p = pt.matrixTransform(root.getScreenCTM().inverse());
      return [p.x / W, p.y / H];
    }

    /* ── 提示詞預覽 ── */
    function schedulePrompt(delay = 400) {
      clearTimeout(st.promptTimer);
      if (!st.sel) return;
      st.promptTimer = setTimeout(loadPrompt, delay);
    }
    async function loadPrompt() {
      const id = currentId();
      try {
        const result = await T2C.post("/api/chapter/prompt", { chapter: n, panel: id, storyboard: st.board }, ctx);
        if (id !== currentId()) return;
        const sizeChanged = !st.prompt || st.prompt.width !== result.width || st.prompt.height !== result.height;
        st.prompt = Object.assign(result, { error: "" });
        if (sizeChanged) drawCanvas();
      } catch (error) {
        if (error.name === "AbortError") return;
        st.prompt = { id, error: error.message };
      }
      drawPrompt();
    }
    function drawPrompt() {
      if (!promptEl) return;
      const p = st.prompt;
      if (!p) return promptEl.replaceChildren(h("p", { class: "muted" }, "編譯中…"));
      if (p.error) return promptEl.replaceChildren(h("div", { class: "alert alert-err" }, p.error));
      promptEl.replaceChildren(
        h("p", { class: "muted t2c-small" }, `生圖 ${p.width}×${p.height}　seeds ${p.seeds.join("、")}`),
        h("p", { class: "sb-caption" }, p.layout.summary.caption),
        h("ul", { class: "t2c-small" }, p.layout.items.map((it) => h("li", {}, h("b", {}, `${it.label}　`), it.caption, it.text ? `「${it.text}」` : ""))));
    }

    /* ── 存檔 ── */
    async function save() {
      try {
        const result = await T2C.post("/api/chapter/storyboard", { chapter: n, storyboard: st.board }, ctx);
        st.board = copy(result.storyboard);
        st.issues = result.issues;
        st.compileError = "";
        FE.dirty.set(false);
        statusEl.textContent = "";
        drawIssues();
        drawTables();
        drawEditor();
        const errs = result.issues.filter((i) => i.level === "error").length;
        FE.toast(errs ? `已存檔（${errs} 個檢查問題，見上方）` : "已存檔", errs ? "warn" : "ok");
      } catch (error) { FE.fail(error); }
    }
    async function discard() {
      if (!(await FE.dirty.confirm())) return;
      FE.route();
    }
  };
})();
