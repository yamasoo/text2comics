// 章節頁的「出圖」分頁：一格一張卡片，列出候選縮圖。點縮圖＝選圖（立刻寫 picks/）；裁切（焦點、放大）；
// 出圖任務：整章／整頁／一格、加畫 N 張（新 seed，見 docs/05_介面設計.md 第 3 節）、同 seed 重畫。
(function () {
  "use strict";
  const { h, svg } = FE;
  const THUMB = 220;
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const r3 = (v) => Math.round(v * 1000) / 1000;
  // 探索用：這一格有角色還沒有卡片，後端照「猜的」外觀出圖，這一格不進 picks（見 docs/07_微調簡報 步驟 2）。
  const exploreOf = (p) => (Array.isArray(p.explore) ? p.explore : []);

  /** compose.crop_window 的同一套算法（比例）：回傳 [x0, y0, x1, y1]。 */
  function cropWindow(src, cell, focus, zoom) {
    const scale = Math.max(cell[0] / src[0], cell[1] / src[1]) * zoom;
    const cw = cell[0] / scale, ch = cell[1] / scale;
    const left = clamp(focus[0] * src[0] - cw / 2, 0, src[0] - cw);
    const top = clamp(focus[1] * src[1] - ch / 2, 0, src[1] - ch);
    return [left / src[0], top / src[1], (left + cw) / src[0], (top + ch) / src[1]];
  }

  T2C.tabs.panels = async (ctx, body, { n }) => {
    // 出圖 profile（N4）：project.yaml 的 comfy_profile 是這一章的預設，介面可以臨時換一組；
    // 換了就要重新抓一次資料，presets／default_preset 才是那一組的。
    const presetKey = "render.preset";
    const profileKey = "render.profile";
    const storedProfile = FE.store.get(profileKey, "");
    let data;
    try {
      data = await T2C.get("/api/chapter/panels", { chapter: n, profile: storedProfile || "" }, ctx);
    } catch (error) {
      if (error.name === "AbortError") throw error;
      body.replaceChildren(h("div", { class: "stack" }, h("div", { class: "alert alert-err" }, error.message),
        h("p", {}, "先到「分鏡」分頁把分鏡修到能編譯。")));
      return;
    }
    const storedPreset = FE.store.get(presetKey, "");
    const presetValue = data.presets.includes(storedPreset) ? storedPreset : data.default_preset;
    const preset = h("select", { "aria-label": "出圖預設", onchange: () => FE.store.set(presetKey, preset.value) },
      data.presets.map((p) => h("option", { value: p, selected: p === presetValue }, p === data.default_preset ? `${p}（預設）` : p)));
    const profiles = data.profiles || [];
    // 顯示文字來自 data.profile_info（[{name, kind, unet}]）：一組 profile＝ComfyUI 上的一組模型。
    // value 仍是 profile 名稱，送出與 FE.store 的行為不變。
    const profileInfo = data.profile_info || [];
    const infoOf = (name) => profileInfo.find((x) => x.name === name) || null;
    const unetOf = (x) => (x && x.unet) || "沒有指定模型";
    const profileText = (name) => {
      const x = infoOf(name);
      const text = x ? `${x.kind || name} · ${unetOf(x)}` : name;
      return name === data.project_profile ? `${text}（這一章）` : text;
    };
    const profile = h("select", { "aria-label": "出圖 profile",
      title: `這一章預設用 ${data.project_profile}；同一臺 ComfyUI 一次只掛一組模型，換 profile 請先在 ComfyUI 換模型。`,
      onchange: () => {
        FE.toast(`${profile.value}：請先在 ComfyUI 換成這一組的模型（${unetOf(infoOf(profile.value))}）`, "warn");
        FE.store.set(profileKey, profile.value);
        FE.route();
      } },
      profiles.map((p) => h("option", { value: p, selected: p === data.profile }, profileText(p))));
    // body2 的 profile 會蓋掉下拉的（候選圖的「重畫」要用那一張自己的 profile）。
    const render = (body2, label) => T2C.run("/api/task/render", Object.assign({ chapter: n, preset: preset.value || null, profile: profile.value || null }, body2));
    const rendered = data.panels.filter((p) => p.candidates.length).length;
    const picked = data.panels.filter((p) => p.pick).length;
    const unpicked = data.panels.filter((p) => p.candidates.length && !p.pick && !exploreOf(p).length);

    async function pickAll() {
      try {
        for (const p of unpicked) await T2C.post("/api/chapter/pick", { chapter: n, panel: p.id, image: p.candidates[0].file }, ctx);
        FE.route();
      } catch (error) { FE.fail(error); }
    }

    /* ── 篩選（docs/07_微調簡報 步驟 2）：全部／過期／探索用／已選。只換清單，不重打 API。 ── */
    const filterKey = "render.filter";
    const FILTERS = [["", "全部"], ["stale", "只看過期"], ["explore", "只看探索用"], ["picked", "只看已選"]];
    const counts = { "": data.panels.length, stale: data.panels.filter((p) => p.stale).length,
      explore: data.panels.filter((p) => exploreOf(p).length).length, picked };
    const stored = FE.store.get(filterKey, "");
    let filter = FILTERS.some(([value]) => value === stored) ? stored : "";
    const filterSelect = h("select", { "aria-label": "篩選格子",
      title: "過期＝卡片的外觀改了、這一格要重畫；探索用＝有角色還沒有卡片，不進 picks。",
      onchange: () => { filter = filterSelect.value; FE.store.set(filterKey, filter); draw(); } },
      FILTERS.map(([value, label]) => h("option", { value, selected: value === filter }, `${label}（${counts[value]}）`)));
    const listHost = h("div", { class: "stack" });
    const matches = (p) => (filter === "stale" ? !!p.stale : filter === "explore" ? exploreOf(p).length > 0 : filter === "picked" ? !!p.pick : true);
    function draw() {
      const rows = data.panels.filter(matches);
      if (!rows.length) { listHost.replaceChildren(h("div", { class: "empty" }, filter ? "這個篩選沒有符合的格。" : "這一章還沒有格子。")); return; }
      const pages = filter ? [...new Set(rows.map((p) => p.page))].sort((a, b) => a - b) : data.pages;
      listHost.replaceChildren(...pages.map((page) => h("section", { class: "stack" },
        h("div", { class: "row" }, h("h2", { class: "t2c-h2 grow" }, `第 ${page} 頁`),
          h("button", { class: "btn btn-sm", type: "button", onclick: () => render({ page }) }, "出這一頁（補沒畫的）")),
        h("div", { class: "pn-grid" }, rows.filter((p) => p.page === page).map((p) => panelCard(p))))));
    }

    // 順序：先選出圖 profile（哪一組模型），再選出圖預設（步數／cfg）——預設清單是那一組 profile 自己的。
    // 兩者各自一行，不跟狀態文字與按鈕擠在同一列。
    body.replaceChildren(h("div", { class: "stack" },
      h("p", { class: "pn-status" }, `已出圖 ${rendered}／${data.panels.length} 格，已選圖 ${picked}／${data.panels.length} 格。`,
        h("span", { class: "muted" }, "　點縮圖就是選它；沒選的格組版時暫用第一張。")),
      h("div", { class: "pn-controls stack t2c-tight" },
        profiles.length ? h("label", { class: "field" }, h("span", { class: "t2c-small" }, "出圖 profile（哪一組模型）"), profile) : null,
        profiles.length ? h("p", { class: "muted t2c-small" }, "同一臺 ComfyUI 一次只掛一組模型；換 profile 請先在 ComfyUI 換模型。") : null,
        data.presets.length ? h("label", { class: "field" }, h("span", { class: "t2c-small" }, "出圖預設（步數／cfg，清單跟著 profile 換）"), preset) : null),
      h("div", { class: "row" },
        h("button", { class: "btn btn-primary", type: "button", onclick: () => render({}) }, "整章出圖（補沒畫的）"),
        unpicked.length ? h("button", { class: "btn", type: "button", onclick: pickAll }, `沒選的 ${unpicked.length} 格先選第一張`) : null,
        h("label", { class: "row t2c-inline" }, "篩選", filterSelect),
        h("a", { class: "btn", href: FE.hash("chapter", n, { tab: "pages" }) }, "下一步：頁面 →")),
      listHost));
    draw();

    function panelCard(p) {
      const more = h("select", { "aria-label": "加畫張數" }, [1, 2, 3, 4].map((k) => h("option", { value: k }, `加畫 ${k} 張`)));
      const chosen = p.pick && p.pick.image;
      const explore = exploreOf(p);
      const locked = explore.length > 0;          // 探索用不進 picks：這一格的角色還沒有卡片
      const thumbs = p.candidates.map((c) => h("figure", { class: ["pn-cand", c.file === chosen && "pn-picked"] },
        h("button", { class: "pn-thumb", type: "button", disabled: locked,
          title: locked ? "探索用：這一格不能選圖（先把這幾張卡片做出來，再重畫這一格）"
            : `選這張（seed ${c.seed}${c.preset ? "，" + c.preset : ""}${c.profile ? "，profile " + c.profile : ""}）`,
          onclick: locked ? null : () => choose(p, c.file) },
          h("img", { src: T2C.img(`${data.renders}/${c.file}`, THUMB), alt: c.file, loading: "lazy" })),
        h("figcaption", { class: "row t2c-tight" },
          h("span", { class: "grow t2c-small" }, `s${c.seed}`, c.preset ? h("span", { class: "chip" }, c.preset) : null,
            c.profile ? h("span", { class: "chip chip-info", title: `出圖 profile：${c.profile}` }, c.profile) : null,
            c.file === chosen ? T2C.chip("已選", "ok") : null),
          h("a", { class: "btn btn-sm btn-ghost", href: T2C.img(`${data.renders}/${c.file}`), target: "_blank", rel: "noopener", title: "看原圖" }, "原圖"),
          h("button", { class: "btn btn-sm btn-ghost", type: "button", title: "用同一個 seed 重畫（覆蓋這張）",
            onclick: async () => { if (await FE.confirm(`用 seed ${c.seed} 重畫並覆蓋 ${c.file}？`, { ok: "重畫" })) render({ panel: p.id, seed: c.seed, preset: c.preset || null, profile: c.profile || null }); } }, "重畫"))));
      return h("article", { class: ["card card-flat stack t2c-tight pn-card", !p.candidates.length && "pn-empty"] },
        h("div", { class: "row" }, h("b", {}, `第 ${p.slot} 格`), h("code", { class: "t2c-small" }, p.id),
          h("span", { class: "muted t2c-small grow" }, `${p.gen_size[0]}×${p.gen_size[1]}`),
          p.stale ? T2C.chip("過期：要重畫", "warn") : null,
          p.pick ? h("button", { class: "btn btn-sm", type: "button", onclick: () => cropDialog(p) }, `裁切${p.pick.zoom > 1 || p.pick.focus[0] !== 0.5 || p.pick.focus[1] !== 0.5 ? "（已調）" : ""}`) : null),
        locked ? h("div", { class: "row t2c-tight" }, explore.map((cid) => T2C.chip(`探索用：還沒有 ${cid} 的卡片`, "warn"))) : null,
        locked ? h("p", { class: "t2c-small muted" }, "探索用不進 picks（選圖先停用）：先把上面這幾張卡片做出來，再重畫這一格，外觀才會是定案的那一份。") : null,
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
