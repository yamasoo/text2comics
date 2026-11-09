// 章節頁的「出圖」分頁：一格一張卡片，列出候選縮圖。點縮圖＝選圖（立刻寫 picks/）；裁切（焦點、放大）；
// 出圖任務：整章／整頁／一格、加畫 N 張（新 seed，見 docs/05_介面設計.md 第 3 節）、同 seed 重畫。
(function () {
  "use strict";
  const { h, svg } = FE;
  const THUMB = 220;
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const r3 = (v) => Math.round(v * 1000) / 1000;

  /** compose.crop_window 的同一套算法（比例）：回傳 [x0, y0, x1, y1]。 */
  function cropWindow(src, cell, focus, zoom) {
    const scale = Math.max(cell[0] / src[0], cell[1] / src[1]) * zoom;
    const cw = cell[0] / scale, ch = cell[1] / scale;
    const left = clamp(focus[0] * src[0] - cw / 2, 0, src[0] - cw);
    const top = clamp(focus[1] * src[1] - ch / 2, 0, src[1] - ch);
    return [left / src[0], top / src[1], (left + cw) / src[0], (top + ch) / src[1]];
  }

  T2C.tabs.panels = async (ctx, body, { n }) => {
    let data;
    try {
      data = await T2C.get("/api/chapter/panels", { chapter: n }, ctx);
    } catch (error) {
      if (error.name === "AbortError") throw error;
      body.replaceChildren(h("div", { class: "stack" }, h("div", { class: "alert alert-err" }, error.message),
        h("p", {}, "先到「分鏡」分頁把分鏡修到能編譯。")));
      return;
    }
    const presetKey = "render.preset";
    const preset = h("select", { "aria-label": "出圖預設", onchange: () => FE.store.set(presetKey, preset.value) },
      data.presets.map((p) => h("option", { value: p, selected: p === (FE.store.get(presetKey, "") || data.default_preset) }, p === data.default_preset ? `${p}（預設）` : p)));
    const render = (body2, label) => T2C.run("/api/task/render", Object.assign({ chapter: n, preset: preset.value || null }, body2));
    const rendered = data.panels.filter((p) => p.candidates.length).length;
    const picked = data.panels.filter((p) => p.pick).length;
    const unpicked = data.panels.filter((p) => p.candidates.length && !p.pick);

    async function pickAll() {
      try {
        for (const p of unpicked) await T2C.post("/api/chapter/pick", { chapter: n, panel: p.id, image: p.candidates[0].file }, ctx);
        FE.route();
      } catch (error) { FE.fail(error); }
    }

    body.replaceChildren(h("div", { class: "stack" },
      h("div", { class: "row" },
        h("span", { class: "grow" }, `已出圖 ${rendered}／${data.panels.length} 格，已選圖 ${picked}／${data.panels.length} 格。`,
          h("span", { class: "muted" }, "　點縮圖就是選它；沒選的格組版時暫用第一張。")),
        data.presets.length ? h("label", { class: "row t2c-inline" }, "出圖預設", preset) : null,
        h("button", { class: "btn btn-primary", type: "button", onclick: () => render({}) }, "整章出圖（補沒畫的）"),
        unpicked.length ? h("button", { class: "btn", type: "button", onclick: pickAll }, `沒選的 ${unpicked.length} 格先選第一張`) : null,
        h("a", { class: "btn", href: FE.hash("chapter", n, { tab: "pages" }) }, "下一步：頁面 →")),
      data.pages.map((page) => h("section", { class: "stack" },
        h("div", { class: "row" }, h("h2", { class: "t2c-h2 grow" }, `第 ${page} 頁`),
          h("button", { class: "btn btn-sm", type: "button", onclick: () => render({ page }) }, "出這一頁（補沒畫的）")),
        h("div", { class: "pn-grid" }, data.panels.filter((p) => p.page === page).map((p) => panelCard(p)))))));

    function panelCard(p) {
      const more = h("select", { "aria-label": "加畫張數" }, [1, 2, 3, 4].map((k) => h("option", { value: k }, `加畫 ${k} 張`)));
      const chosen = p.pick && p.pick.image;
      const thumbs = p.candidates.map((c) => h("figure", { class: ["pn-cand", c.file === chosen && "pn-picked"] },
        h("button", { class: "pn-thumb", type: "button", title: `選這張（seed ${c.seed}${c.preset ? "，" + c.preset : ""}）`, onclick: () => choose(p, c.file) },
          h("img", { src: T2C.img(`${data.renders}/${c.file}`, THUMB), alt: c.file, loading: "lazy" })),
        h("figcaption", { class: "row t2c-tight" },
          h("span", { class: "grow t2c-small" }, `s${c.seed}`, c.preset ? h("span", { class: "chip" }, c.preset) : null, c.file === chosen ? T2C.chip("已選", "ok") : null),
          h("a", { class: "btn btn-sm btn-ghost", href: T2C.img(`${data.renders}/${c.file}`), target: "_blank", rel: "noopener", title: "看原圖" }, "原圖"),
          h("button", { class: "btn btn-sm btn-ghost", type: "button", title: "用同一個 seed 重畫（覆蓋這張）",
            onclick: async () => { if (await FE.confirm(`用 seed ${c.seed} 重畫並覆蓋 ${c.file}？`, { ok: "重畫" })) render({ panel: p.id, seed: c.seed, preset: c.preset || null }); } }, "重畫"))));
      return h("article", { class: ["card card-flat stack t2c-tight pn-card", !p.candidates.length && "pn-empty"] },
        h("div", { class: "row" }, h("b", {}, `第 ${p.slot} 格`), h("code", { class: "t2c-small" }, p.id),
          h("span", { class: "muted t2c-small grow" }, `${p.gen_size[0]}×${p.gen_size[1]}`),
          p.pick ? h("button", { class: "btn btn-sm", type: "button", onclick: () => cropDialog(p) }, `裁切${p.pick.zoom > 1 || p.pick.focus[0] !== 0.5 || p.pick.focus[1] !== 0.5 ? "（已調）" : ""}`) : null),
        h("p", { class: "t2c-small pn-scene" }, p.scene),
        p.lines.length ? h("p", { class: "t2c-small muted" }, p.lines.map((t) => `「${t.replace(/\n/g, "")}」`).join("")) : null,
        p.candidates.length ? h("div", { class: "pn-cands" }, thumbs) : h("div", { class: "empty" }, "還沒有出圖"),
        h("div", { class: "row t2c-tight" },
          p.candidates.length ? [more, h("button", { class: "btn btn-sm", type: "button", onclick: () => render({ panel: p.id, more: Number(more.value) }) }, "出圖")]
            : h("button", { class: "btn btn-sm btn-primary", type: "button", onclick: () => render({ panel: p.id }) }, `出這一格（${p.seeds.length} 張）`)));
    }

    async function choose(p, file) {
      try {
        await T2C.post("/api/chapter/pick", { chapter: n, panel: p.id, image: file }, ctx);
        FE.route();
      } catch (error) { FE.fail(error); }
    }

    /* ── 裁切 ── */
    function cropDialog(p) {
      const st = { focus: p.pick.focus.slice(), zoom: p.pick.zoom, src: null };
      const imgUrl = T2C.img(`${data.renders}/${p.pick.image}`, 900);
      const img = h("img", { src: imgUrl, class: "pn-crop-img", alt: p.pick.image, draggable: "false" });
      const overlay = svg("svg", { class: "pn-crop-overlay", viewBox: "0 0 1000 1000", preserveAspectRatio: "none" });
      const stage = h("div", { class: "pn-crop-stage" }, img, overlay);
      const preview = h("img", { class: "pn-crop-preview", alt: "裁切後" });
      const zoom = h("input", { type: "range", min: 1, max: 4, step: 0.05, value: st.zoom, oninput: () => { st.zoom = Number(zoom.value); zoomLabel.textContent = `${st.zoom.toFixed(2)}×`; draw(); } });
      const zoomLabel = h("span", {}, `${st.zoom.toFixed(2)}×`);
      let timer = null;
      function draw() {
        if (!st.src) return;
        const [x0, y0, x1, y1] = cropWindow(st.src, p.cell_size, st.focus, st.zoom);
        overlay.replaceChildren(
          svg("path", { class: "pn-crop-shade", d: `M0 0H1000V1000H0Z M${x0 * 1000} ${y0 * 1000}V${y1 * 1000}H${x1 * 1000}V${y0 * 1000}Z`, "fill-rule": "evenodd" }),
          svg("rect", { class: "pn-crop-rect", x: x0 * 1000, y: y0 * 1000, width: (x1 - x0) * 1000, height: (y1 - y0) * 1000 }),
          svg("circle", { class: "pn-crop-focus", cx: st.focus[0] * 1000, cy: st.focus[1] * 1000, r: 8 }));
        clearTimeout(timer);
        timer = setTimeout(() => {
          preview.src = `/api/chapter/crop.jpg?${new URLSearchParams({ project: T2C.project(), chapter: n, panel: p.id, image: p.pick.image, fx: st.focus[0], fy: st.focus[1], zoom: st.zoom, w: 420 })}`;
        }, 150);
      }
      img.addEventListener("load", () => { st.src = [img.naturalWidth, img.naturalHeight]; draw(); });
      const setFocus = (e) => {
        const r = overlay.getBoundingClientRect();
        st.focus = [r3(clamp((e.clientX - r.left) / r.width, 0, 1)), r3(clamp((e.clientY - r.top) / r.height, 0, 1))];
        draw();
      };
      overlay.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        setFocus(e);
        const move = (ev) => setFocus(ev);
        const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
      });
      FE.modal({
        title: `裁切：第 ${p.page} 頁第 ${p.slot} 格`,
        wide: true,
        body: h("div", { class: "pn-crop" },
          h("div", { class: "stack" }, stage, h("p", { class: "muted t2c-small" }, "點或拖曳選焦點（框會盡量以它為中心）；框外的部分不會出現在頁面上。")),
          h("div", { class: "stack" }, h("b", {}, "格子裡的樣子"), preview,
            h("label", { class: "row t2c-inline" }, "放大", zoom, zoomLabel))),
        foot: (done) => [
          h("button", { class: "btn", type: "button", onclick: () => { st.focus = [0.5, 0.5]; st.zoom = 1; zoom.value = 1; zoomLabel.textContent = "1.00×"; draw(); } }, "回到預設"),
          h("button", { class: "btn", type: "button", onclick: () => done(null) }, "取消"),
          h("button", { class: "btn btn-primary", type: "button", onclick: async () => {
            try {
              await T2C.post("/api/chapter/pick", { chapter: n, panel: p.id, focus: st.focus, zoom: st.zoom }, ctx);
              done(true);
              FE.route();
            } catch (error) { FE.fail(error); }
          } }, "存檔"),
        ],
      });
    }
  };
})();
