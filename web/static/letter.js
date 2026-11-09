// 嵌字微調頁（#/letter）：在組好的頁面上拖對話框、尾巴、臉框、狀聲詞，存進 letters/chNNN.json。
// 資料格式見 docs/02_資料格式.md 第 10 節。座標：伺服器回傳整頁像素；存檔用「格子比例」。
(function () {
  "use strict";
  const { h, svg, PAGES } = FE;

  const KIND_LABEL = { speech: "對話", thought: "心聲", shout: "喊叫", whisper: "悄悄話", radio: "通訊（電子音）", narration: "旁白" };
  const clamp01 = (v) => Math.min(1, Math.max(0, v));
  const r4 = (v) => Math.round(v * 10000) / 10000;
  const copy = (v) => JSON.parse(JSON.stringify(v));

  PAGES.letter = async (ctx) => {
    const q = ctx.query;
    if (!q.project && !T2C.need(ctx, "嵌字")) return;
    const st = {
      project: q.project || T2C.project(),
      chapter: parseInt(q.chapter || String(FE.store.get("chapter", 1) || 1), 10) || 1,
      page: parseInt(q.page || "1", 10) || 1,
      plan: null,
      pages: [],
      draft: {},          // {格 id: {faces?, bubbles?, sfx?}}：這一頁的微調（和存檔的格式相同）
      sel: null,          // {type: "bubble"|"face"|"sfx", pid, index}
      guides: FE.store.get("letter.guides", true) !== false,
      busy: 0,
      timer: null,
    };
    ctx.crumbs([{ label: "專案", href: "#/" }, { label: `第 ${st.chapter} 章`, href: FE.hash("chapter", st.chapter, { tab: "pages" }) }, { label: `嵌字（第 ${st.page} 頁）` }]);

    const data = await FE.api("/api/letter/plan", { query: { project: st.project, chapter: st.chapter, page: st.page }, signal: ctx.signal });
    st.project = data.project;
    st.pages = data.pages;
    st.plan = data.plan;
    st.draft = copy(data.letters || {});

    /* ── 畫面骨架 ── */
    const [pw, ph] = st.plan.size;
    const img = h("img", { class: "lt-img", alt: "頁面預覽", width: pw, height: ph, draggable: "false" });
    const overlay = svg("svg", { class: "lt-overlay", viewBox: `0 0 ${pw} ${ph}`, preserveAspectRatio: "none" });
    const stage = h("div", { class: "lt-stage", style: { "--page-ratio": String(pw / ph) } }, img, overlay);
    const side = h("div", { class: "stack lt-side" });
    const status = h("span", { class: "muted lt-status" });

    const pageSelect = h("select", {
      "aria-label": "頁",
      onchange: (event) => goto({ page: event.target.value }),
    }, st.pages.map((n) => h("option", { value: n, selected: n === st.page }, `第 ${n} 頁`)));
    const chapterInput = h("input", {
      type: "number", min: 1, value: st.chapter, "aria-label": "章", class: "lt-num",
      onchange: (event) => goto({ chapter: event.target.value, page: 1 }),
    });

    ctx.view(h("div", { class: "stack" },
      h("div", { class: "row" },
        h("h1", { class: "lt-title" }, "嵌字"),
        h("label", { class: "row lt-inline" }, "章", chapterInput),
        h("label", { class: "row lt-inline" }, "頁", pageSelect),
        h("label", { class: "check" },
          h("input", {
            type: "checkbox", checked: st.guides,
            onchange: (event) => { st.guides = event.target.checked; FE.store.set("letter.guides", st.guides); drawOverlay(); },
          }), "顯示輔助框"),
        h("span", { class: "grow" }),
        status,
        h("button", { class: "btn", type: "button", onclick: () => resetAll() }, "本頁全部回到自動"),
        h("button", { class: "btn", type: "button", onclick: () => discard() }, "放棄修改"),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => save() }, "存檔")),
      h("p", { class: "muted lt-path" }, st.project),
      h("div", { class: "lt-wrap" }, stage, side)));

    function goto(change) {
      const next = Object.assign({ project: st.project, chapter: st.chapter, page: st.page }, change);
      FE.go(FE.hash("letter", next));
    }

    /* ── 座標換算 ── */
    const panelOf = (pid) => st.plan.panels.find((p) => p.id === pid);
    function toRatio(panel, x, y) {
      const [x0, y0, x1, y1] = panel.rect;
      return [r4(clamp01((x - x0) / (x1 - x0))), r4(clamp01((y - y0) / (y1 - y0)))];
    }
    function boxRatio(panel, box) {
      const a = toRatio(panel, box[0], box[1]);
      const b = toRatio(panel, box[2], box[3]);
      return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
    }
    function svgPoint(event) {
      const pt = overlay.createSVGPoint();
      pt.x = event.clientX;
      pt.y = event.clientY;
      return pt.matrixTransform(overlay.getScreenCTM().inverse());
    }
    const unit = () => pw / Math.max(overlay.getBoundingClientRect().width, 1);   // 1 螢幕像素 = 幾個頁面像素

    /* ── 草稿 ── */
    const entry = (pid) => (st.draft[pid] = st.draft[pid] || {});
    function listItem(pid, key, index) {
      const e = entry(pid);
      e[key] = e[key] || [];
      while (e[key].length <= index) e[key].push({});
      e[key][index] = e[key][index] || {};
      return e[key][index];
    }
    function bubbleOver(pid, index) {
      const over = listItem(pid, "bubbles", index);
      const b = panelOf(pid).bubbles[index];
      if (b) over.text = b.text;                       // 存檔時記下台詞，之後分鏡改台詞會警告
      return over;
    }
    function tidy() {
      for (const pid of Object.keys(st.draft)) {
        const e = st.draft[pid];
        for (const key of ["bubbles", "sfx"]) {
          if (!e[key]) continue;
          e[key] = e[key].map((item) => {
            const keys = Object.keys(item || {}).filter((k) => k !== "text");
            return keys.length ? item : {};
          });
          while (e[key].length && !Object.keys(e[key][e[key].length - 1]).length) e[key].pop();
          if (!e[key].length) delete e[key];
        }
        if (!Object.keys(e).length) delete st.draft[pid];
      }
    }
    function changed() {
      tidy();
      FE.dirty.set(true);
      clearTimeout(st.timer);
      st.timer = setTimeout(refresh, 150);
    }

    /* ── 和伺服器同步 ── */
    async function refresh() {
      const seq = ++st.busy;
      status.textContent = "更新中…";
      try {
        const result = await FE.api("/api/letter/plan", {
          body: { project: st.project, chapter: st.chapter, page: st.page, panels: st.draft },
          signal: ctx.signal,
        });
        if (seq !== st.busy || !ctx.active()) return;
        st.plan = result.plan;
        drawOverlay();
        drawSide();
        loadImage();
      } catch (error) {
        if (error && error.name === "AbortError") return;
        status.textContent = "";
        FE.fail(error);
      }
    }
    function previewUrl() {
      const params = new URLSearchParams({ project: st.project, chapter: st.chapter, page: st.page, draft: JSON.stringify(st.draft) });
      return `/api/letter/preview.jpg?${params}`;
    }
    function loadImage() {
      const url = previewUrl();
      const next = new Image();
      next.onload = () => { if (ctx.active()) { img.src = url; status.textContent = FE.dirty.is() ? "尚未存檔" : ""; } };
      next.onerror = () => { status.textContent = "預覽載入失敗"; };
      next.src = url;
    }
    async function save() {
      try {
        const result = await FE.api("/api/letter/save", {
          body: { project: st.project, chapter: st.chapter, page: st.page, panels: st.draft },
          signal: ctx.signal,
        });
        FE.dirty.set(false);
        status.textContent = "";
        FE.toast(`已存檔：${result.letters}`, "ok");
      } catch (error) {
        if (!(error && error.name === "AbortError")) FE.fail(error);
      }
    }
    async function discard() {
      if (!(await FE.dirty.confirm())) return;
      FE.route();
    }
    async function resetAll() {
      const ok = await FE.confirm("這一頁的所有微調都會清掉，回到自動排版（要按「存檔」才會寫入）。", { title: "全部回到自動", ok: "清掉" });
      if (!ok) return;
      st.draft = {};
      st.sel = null;
      changed();
    }

    /* ── 拖曳 ── */
    function draggable(el, handlers) {
      el.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        el.setPointerCapture(event.pointerId);
        pick(handlers.sel, handlers.mark || el);       // 只換外觀，不重畫（重畫會把正在拖的節點換掉）
        const start = svgPoint(event);
        let last = start;
        let moved = false;
        const move = (ev) => {
          last = svgPoint(ev);
          if (!moved && Math.hypot(last.x - start.x, last.y - start.y) < 3 * unit()) return;
          moved = true;
          handlers.preview(last.x - start.x, last.y - start.y, last);
        };
        const up = () => {
          el.removeEventListener("pointermove", move);
          el.removeEventListener("pointerup", up);
          el.removeEventListener("pointercancel", up);
          if (moved) handlers.drop(last.x - start.x, last.y - start.y, last);
        };
        el.addEventListener("pointermove", move);
        el.addEventListener("pointerup", up);
        el.addEventListener("pointercancel", up);
      });
    }
    function pick(sel, mark) {
      st.sel = sel;
      for (const node of overlay.querySelectorAll(".lt-sel")) node.classList.remove("lt-sel");
      if (mark) mark.classList.add("lt-sel");
      drawSide();
    }
    const isSel = (type, pid, index) => st.sel && st.sel.type === type && st.sel.pid === pid && st.sel.index === index;

    /* ── 疊在圖上的框 ── */
    function drawOverlay() {
      const u = unit();
      const nodes = [];
      overlay.classList.toggle("lt-quiet", !st.guides);
      for (const panel of st.plan.panels) {
        const [x0, y0, x1, y1] = panel.rect;
        nodes.push(svg("rect", { class: "lt-panel", x: x0, y: y0, width: x1 - x0, height: y1 - y0, "vector-effect": "non-scaling-stroke" }));
        panel.faces.forEach((face, index) => nodes.push(faceNode(panel, face, index, u)));
        panel.sfx.forEach((s) => nodes.push(sfxNode(panel, s, u)));
        panel.bubbles.forEach((b) => nodes.push(bubbleNode(panel, b, u)));
      }
      overlay.replaceChildren(...nodes);
    }

    function handle(x, y, u, cls) {
      const s = 12 * u;
      return svg("rect", { class: `lt-handle ${cls || ""}`, x: x - s / 2, y: y - s / 2, width: s, height: s, "vector-effect": "non-scaling-stroke" });
    }

    function faceNode(panel, face, index, u) {
      const [x0, y0, x1, y1] = face;
      const box = svg("rect", { class: ["lt-face", isSel("face", panel.id, index) && "lt-sel"], x: x0, y: y0, width: x1 - x0, height: y1 - y0, "vector-effect": "non-scaling-stroke" });
      const corner = handle(x1, y1, u);
      const group = svg("g", {}, box, corner,
        svg("title", {}, panel.faces_auto ? "自動推估的臉框（拖曳或縮放後改成手動）" : "臉框"));
      const commit = (next) => {
        const faces = panel.faces.map((f, i) => boxRatio(panel, i === index ? next : f));
        entry(panel.id).faces = faces;
        changed();
      };
      const sel = { type: "face", pid: panel.id, index };
      draggable(box, {
        sel,
        preview: (dx, dy) => group.setAttribute("transform", `translate(${dx} ${dy})`),
        drop: (dx, dy) => commit([x0 + dx, y0 + dy, x1 + dx, y1 + dy]),
      });
      draggable(corner, {
        sel, mark: box,
        preview: (dx, dy) => {
          box.setAttribute("width", Math.max(10, x1 - x0 + dx));
          box.setAttribute("height", Math.max(10, y1 - y0 + dy));
          corner.setAttribute("transform", `translate(${dx} ${dy})`);
        },
        drop: (dx, dy) => commit([x0, y0, Math.max(x0 + 10, x1 + dx), Math.max(y0 + 10, y1 + dy)]),
      });
      return group;
    }

    function bubbleNode(panel, b, u) {
      const [cx, cy] = b.center;
      const selected = isSel("bubble", panel.id, b.index);
      const shape = b.kind === "narration"
        ? svg("rect", { x: cx - b.rx, y: cy - b.ry, width: 2 * b.rx, height: 2 * b.ry })
        : svg("ellipse", { cx, cy, rx: b.rx, ry: b.ry });
      shape.setAttribute("class", ["lt-bubble", selected && "lt-sel", b.order_issue && "lt-order"].filter(Boolean).join(" "));
      shape.setAttribute("vector-effect", "non-scaling-stroke");
      const tip = `${KIND_LABEL[b.kind] || b.kind}：${b.text}${b.order_issue ? `\n⚠ 會比第 ${b.order_issue} 個先讀到（右翻：右邊、上面的先讀）` : ""}`;
      const body = svg("g", {}, shape, svg("title", {}, tip));
      const group = svg("g", {}, body);
      const sel = { type: "bubble", pid: panel.id, index: b.index };
      draggable(shape, {
        sel,
        preview: (dx, dy) => body.setAttribute("transform", `translate(${dx} ${dy})`),
        drop: (dx, dy) => { bubbleOver(panel.id, b.index).center = toRatio(panel, cx + dx, cy + dy); changed(); },
      });
      if (b.tail) {
        const [tx, ty] = b.tail;
        const line = svg("line", { class: "lt-tail-line", x1: cx, y1: cy, x2: tx, y2: ty, "vector-effect": "non-scaling-stroke" });
        const dot = svg("circle", { class: ["lt-tail", b.auto_tail ? "" : "lt-manual"], cx: tx, cy: ty, r: 8 * u, "vector-effect": "non-scaling-stroke" },
          svg("title", {}, "尾巴尖端：拖曳改方向"));
        group.prepend(line);
        group.append(dot);
        draggable(dot, {
          sel, mark: shape,
          preview: (dx, dy) => {
            dot.setAttribute("cx", tx + dx);
            dot.setAttribute("cy", ty + dy);
            line.setAttribute("x2", tx + dx);
            line.setAttribute("y2", ty + dy);
          },
          drop: (dx, dy) => { bubbleOver(panel.id, b.index).tail = toRatio(panel, tx + dx, ty + dy); changed(); },
        });
      }
      return group;
    }

    function sfxNode(panel, s, u) {
      const [x0, y0, x1, y1] = s.box;
      const box = svg("rect", { class: ["lt-sfx", isSel("sfx", panel.id, s.index) && "lt-sel"], x: x0, y: y0, width: x1 - x0, height: y1 - y0, "vector-effect": "non-scaling-stroke" });
      const corner = handle(x1, y1, u, "lt-handle-sfx");
      const group = svg("g", {}, box, corner, svg("title", {}, `狀聲詞：${s.text}`));
      const sel = { type: "sfx", pid: panel.id, index: s.index };
      const commit = (next) => { listItem(panel.id, "sfx", s.index).box = boxRatio(panel, next); changed(); };
      draggable(box, {
        sel,
        preview: (dx, dy) => group.setAttribute("transform", `translate(${dx} ${dy})`),
        drop: (dx, dy) => commit([x0 + dx, y0 + dy, x1 + dx, y1 + dy]),
      });
      draggable(corner, {
        sel, mark: box,
        preview: (dx, dy) => {
          box.setAttribute("width", Math.max(10, x1 - x0 + dx));
          box.setAttribute("height", Math.max(10, y1 - y0 + dy));
          corner.setAttribute("transform", `translate(${dx} ${dy})`);
        },
        drop: (dx, dy) => commit([x0, y0, Math.max(x0 + 10, x1 + dx), Math.max(y0 + 10, y1 + dy)]),
      });
      return group;
    }

    /* ── 右側：選取項目的設定 ── */
    function drawSide() {
      const parts = [];
      const sel = st.sel;
      const panel = sel && panelOf(sel.pid);
      if (!sel || !panel) {
        parts.push(h("div", { class: "card card-flat stack" },
          h("p", { class: "card-title" }, "怎麼調"),
          h("p", { class: "muted" }, "點對話框、臉框（紅）或狀聲詞（橘）來選取。拖曳可以移動；拖右下角的小方塊縮放；拖尾巴的圓點改方向。"),
          h("p", { class: "muted" }, "改完按「存檔」：寫進 letters 檔，並重新輸出頁面 PNG。")));
      } else if (sel.type === "bubble") {
        parts.push(bubbleCard(panel, panel.bubbles[sel.index]));
      } else if (sel.type === "face") {
        parts.push(faceCard(panel));
      } else if (sel.type === "sfx") {
        parts.push(sfxCard(panel, panel.sfx.find((s) => s.index === sel.index)));
      }
      if (panel) parts.push(panelCard(panel));
      if (st.plan.warnings.length) {
        parts.push(h("div", { class: "alert alert-warn stack" },
          h("strong", {}, "提醒"),
          h("ul", { class: "lt-warnings" }, st.plan.warnings.map((w) => h("li", {}, w)))));
      }
      side.replaceChildren(...parts);
    }

    function bubbleCard(panel, b) {
      if (!b) return h("p", { class: "muted" }, "找不到這個對話框。");
      const over = ((entry(panel.id).bubbles || [])[b.index]) || {};
      const scaleLabel = h("span", {}, `${Math.round((over.scale || 1) * 100)}%`);
      const set = (fn) => { fn(bubbleOver(panel.id, b.index)); changed(); };
      return h("div", { class: "card card-flat stack" },
        h("p", { class: "card-title" }, `${KIND_LABEL[b.kind] || b.kind}（${panel.id} 第 ${b.index + 1} 個）`),
        h("p", { class: "lt-quote" }, b.text),
        b.speaker ? h("p", { class: "muted" }, `說話的人：${b.speaker}${b.offscreen ? "（畫面外）" : ""}`) : null,
        h("div", { class: "field" },
          h("label", {}, "字級 ", scaleLabel),
          h("input", {
            type: "range", min: 0.5, max: 2, step: 0.05, value: over.scale || 1,
            oninput: (event) => { scaleLabel.textContent = `${Math.round(event.target.value * 100)}%`; },
            onchange: (event) => set((o) => { const v = parseFloat(event.target.value); if (Math.abs(v - 1) < 0.001) delete o.scale; else o.scale = v; }),
          })),
        h("div", { class: "field" },
          h("label", {}, b.vertical ? "每欄最多幾個字" : "每行最多幾個字"),
          h("input", {
            type: "number", min: 1, max: 40, value: over.rows || "", placeholder: "自動",
            onchange: (event) => set((o) => {
              const v = parseInt(event.target.value, 10);
              if (v >= 1 && v <= 40) o.rows = v; else delete o.rows;
            }),
          }),
          h("span", { class: "field-hint" }, "改這個可以讓對話框變瘦長或矮胖；空白＝自動。")),
        h("div", { class: "row" },
          h("button", { class: "btn btn-sm", type: "button", disabled: b.auto_center, onclick: () => set((o) => delete o.center) }, "位置回到自動"),
          b.kind === "narration" ? null : h("button", { class: "btn btn-sm", type: "button", disabled: b.auto_tail, onclick: () => set((o) => delete o.tail) }, "尾巴回到自動"),
          b.kind === "narration" ? null : (b.tail
            ? h("button", { class: "btn btn-sm", type: "button", onclick: () => set((o) => { o.tail = null; }) }, "不要尾巴")
            : h("button", {
              class: "btn btn-sm", type: "button",
              onclick: () => set((o) => { o.tail = toRatio(panel, b.center[0], b.center[1] + b.ry * 1.6); }),
            }, "加尾巴"))),
        h("button", {
          class: "btn btn-sm btn-ghost", type: "button",
          onclick: () => set((o) => { for (const k of Object.keys(o)) delete o[k]; }),
        }, "這個對話框全部回到自動"));
    }

    function faceCard(panel) {
      const index = st.sel.index;
      return h("div", { class: "card card-flat stack" },
        h("p", { class: "card-title" }, `臉框（${panel.id} 第 ${index + 1} 個）`),
        h("p", { class: "muted" }, panel.faces_auto ? "這是從分鏡角色框推估的位置；拖曳或縮放後，這一格的臉框就改成手動。" : "手動標的臉框。"),
        h("button", {
          class: "btn btn-sm btn-danger", type: "button",
          onclick: () => {
            entry(panel.id).faces = panel.faces.filter((_, i) => i !== index).map((f) => boxRatio(panel, f));
            st.sel = null;
            changed();
          },
        }, "刪除這個臉框"));
    }

    function sfxCard(panel, s) {
      if (!s) return h("p", { class: "muted" }, "找不到這個狀聲詞。");
      const set = (fn) => { fn(listItem(panel.id, "sfx", s.index)); changed(); };
      const over = ((entry(panel.id).sfx || [])[s.index]) || {};
      const mode = over.vertical === undefined ? "auto" : over.vertical ? "v" : "h";
      return h("div", { class: "card card-flat stack" },
        h("p", { class: "card-title" }, `狀聲詞（${panel.id}）`),
        h("p", { class: "lt-quote" }, s.text),
        h("div", { class: "field" },
          h("label", {}, "傾斜角度（度，正數逆時針）"),
          h("input", {
            type: "number", min: -45, max: 45, step: 1, value: s.angle,
            onchange: (event) => set((o) => {
              const v = parseFloat(event.target.value);
              if (Number.isFinite(v) && Math.abs(v) <= 45) o.angle = v; else delete o.angle;
            }),
          })),
        h("div", { class: "field" },
          h("label", {}, "方向"),
          h("select", {
            value: mode,
            onchange: (event) => set((o) => {
              if (event.target.value === "auto") delete o.vertical; else o.vertical = event.target.value === "v";
            }),
          }, h("option", { value: "auto" }, "自動"), h("option", { value: "v" }, "直排"), h("option", { value: "h" }, "橫排"))),
        h("button", {
          class: "btn btn-sm btn-ghost", type: "button",
          onclick: () => set((o) => { for (const k of Object.keys(o)) delete o[k]; }),
        }, "回到自動"));
    }

    function panelCard(panel) {
      return h("div", { class: "card card-flat stack" },
        h("p", { class: "card-title" }, `這一格（${panel.id}）`),
        h("div", { class: "row" },
          h("button", {
            class: "btn btn-sm", type: "button",
            onclick: () => {
              const faces = panel.faces.map((f) => boxRatio(panel, f));
              faces.push([0.4, 0.2, 0.6, 0.45]);
              entry(panel.id).faces = faces;
              st.sel = { type: "face", pid: panel.id, index: faces.length - 1 };
              changed();
            },
          }, "新增臉框"),
          h("button", {
            class: "btn btn-sm", type: "button", disabled: panel.faces_auto,
            onclick: () => { delete entry(panel.id).faces; st.sel = null; changed(); },
          }, "臉框回到自動")));
    }

    overlay.addEventListener("pointerdown", (event) => {
      if (event.target === overlay) pick(null, null);
    });
    window.addEventListener("resize", () => { if (ctx.active()) drawOverlay(); }, { signal: ctx.signal });
    img.addEventListener("load", () => { if (ctx.active()) drawOverlay(); }, { once: true });

    img.src = previewUrl();
    drawOverlay();
    drawSide();
  };
})();
