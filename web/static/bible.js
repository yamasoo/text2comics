// 視覺聖經（#/bible、#/bible/:kind/:id）：草稿確認入庫、卡片編輯（本文的原文引文並排）、定裝圖候選與挑選、抽取與出圖任務。
// 規則（docs/02_資料格式.md 第 3 節）：look_en 定案後不要改；改了會讓挑好的定裝圖「過期」。
(function () {
  "use strict";
  const { h, PAGES } = FE;
  const KIND = { character: "角色", location: "地點" };
  const STATE = { ok: ["✓ 已挑", "ok"], stale: ["⚠ 過期", "warn"], none: ["－ 未挑", ""], missing: ["✗ 缺卡", "err"] };
  const stripFront = (text) => String(text || "").replace(/^---\s*\n[\s\S]*?\n---\s*\n?/, "");
  const cardHash = (c) => FE.hash("bible", c.kind, c.id, c.draft ? { draft: 1 } : {});

  function extractDialog() {
    const min = T2C.num(2, { min: 1, max: 99 });
    const only = h("input", { type: "text", placeholder: "只做這些人物或地點（名字，用頓號或逗號分開；留空＝依章數自動挑）" });
    const notes = h("input", { type: "text", class: "grow", placeholder: "作者的設定檔資料夾或檔案（可留空）" });
    const force = h("input", { type: "checkbox" });
    const browse = async () => { const p = await FE.filepicker.open({ mode: "dir", title: "選擇作者的設定檔資料夾" }); if (p) notes.value = p; };
    FE.modal({
      title: "掃描原著＋成卡",
      body: h("div", { class: "stack" },
        h("p", { class: "muted" }, "讀專案 source/ 的每一章，找出角色與地點、原文怎麼描寫外觀（每條都附原文引文），再替出現夠多章的寫卡片草稿。草稿要你看過、改過才確認入庫。"),
        h("label", { class: "row t2c-inline" }, "至少出現幾章", min), only,
        h("div", { class: "row" }, notes, h("button", { class: "btn", type: "button", onclick: browse }, "瀏覽…")),
        h("label", { class: "check" }, force, "重新掃描全部章節、覆蓋已有的草稿")),
      foot: (done) => [
        h("button", { class: "btn", type: "button", onclick: () => done() }, "取消"),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => {
          done();
          T2C.run("/api/task/bible_extract", { min_chapters: Number(min.value) || 2, only: only.value.split(/[、，,]/).map((s) => s.trim()).filter(Boolean),
            notes: notes.value.trim() ? [notes.value.trim()] : [], force: force.checked });
        } }, "開始"),
      ],
    });
  }

  function sheetDialog(ids, env) {
    const full = h("input", { type: "checkbox", checked: true });
    const bust = h("input", { type: "checkbox" });
    const count = T2C.num("", { min: 1, max: 8, placeholder: "依 project.yaml" });
    const more = T2C.num("", { min: 1, max: 8, placeholder: "－" });
    const presets = (env && env.presets) || [];
    const preset = h("select", {}, presets.map((p) => h("option", { value: p, selected: p === (env && env.default_preset) }, p)));
    FE.modal({
      title: ids && ids.length ? `定裝圖：${ids.join("、")}` : "定裝圖：全部定案的角色與地點",
      body: h("div", { class: "stack" },
        h("p", { class: "muted" }, "角色每套服裝一張（3:4），地點一張空鏡（4:3）。已經有的跳過；「加畫」會用新的 seed 再多畫幾張。"),
        h("div", { class: "row" }, h("label", { class: "check" }, full, "全身"), h("label", { class: "check" }, bust, "胸像")),
        h("div", { class: "row" }, h("label", { class: "row t2c-inline" }, "每張幾個候選", count), h("label", { class: "row t2c-inline" }, "或加畫", more),
          presets.length ? h("label", { class: "row t2c-inline" }, "出圖預設", preset) : null)),
      foot: (done) => [
        h("button", { class: "btn", type: "button", onclick: () => done() }, "取消"),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => {
          const views = [full.checked && "full", bust.checked && "bust"].filter(Boolean);
          if (!views.length) return FE.toast("至少選一種視角", "warn");
          done();
          T2C.run("/api/task/bible_sheet", { ids: ids || [], views, candidates: count.value ? Number(count.value) : null,
            more: more.value ? Number(more.value) : 0, preset: preset.value || null });
        } }, "出圖"),
      ],
    });
  }

  async function withEnv(ctx, fn) {
    let env = null;
    try { env = await FE.api("/api/env", { signal: ctx.signal }); } catch (error) { if (error.name === "AbortError") return; }
    fn(env);
  }

  function newCardDialog(name, kind) {
    const id = h("input", { type: "text", placeholder: "id（英文小寫、數字、底線，例如 lao_zhou）" });
    const nm = h("input", { type: "text", value: name || "" });
    const kd = h("select", {}, Object.entries(KIND).map(([k, v]) => h("option", { value: k, selected: k === (kind || "character") }, v)));
    FE.modal({
      title: "新增卡片（草稿）",
      body: h("div", { class: "stack" }, h("label", { class: "field" }, "類別", kd), h("label", { class: "field" }, "名字", nm), h("label", { class: "field" }, "id", id)),
      foot: (done) => [
        h("button", { class: "btn", type: "button", onclick: () => done() }, "取消"),
        h("button", { class: "btn btn-primary", type: "button", onclick: async () => {
          try {
            const r = await T2C.post("/api/bible/new", { kind: kd.value, id: id.value.trim(), name: nm.value.trim() });
            done();
            FE.go(FE.hash("bible", kd.value, r.id, { draft: 1 }));
          } catch (error) { FE.fail(error); }
        } }, "建立"),
      ],
    });
  }

  PAGES.bible = async (ctx) => {
    if (!T2C.need(ctx, "視覺聖經")) return;
    ctx.crumbs([{ label: "專案", href: "#/" }, { label: "視覺聖經" }]);
    const data = await T2C.get("/api/bible", {}, ctx);
    const drafts = data.cards.filter((c) => c.draft);
    const st = data.status;
    const errs = (c) => c.issues.filter((i) => i.level === "error").length;
    const ready = drafts.filter((c) => !errs(c));

    const acceptAll = async () => {
      if (!(await FE.confirm(`確認入庫 ${ready.length} 張沒有錯誤的草稿：${ready.map((c) => c.name).join("、")}？\n入庫後 look_en 就是定案，之後每一格都照它畫。`, { ok: "確認入庫" }))) return;
      try {
        const r = await T2C.post("/api/bible/accept", { ids: ready.map((c) => c.id) }, ctx);
        FE.toast(`已入庫 ${r.moved.length} 張`, "ok");
        FE.route();
      } catch (error) { FE.fail(error); }
    };

    const draftList = drafts.length ? h("section", { class: "card stack" },
      h("div", { class: "row" }, h("h2", { class: "card-title grow" }, `草稿（${drafts.length}）`),
        ready.length ? h("button", { class: "btn btn-primary", type: "button", onclick: acceptAll }, `沒有錯誤的 ${ready.length} 張全部確認入庫`) : null),
      h("p", { class: "muted" }, "草稿不會被分鏡使用。打開每一張看「待確認」：哪些外觀是模型補的、哪裡和作者設定衝突；改好 look_en 再確認入庫。"),
      h("table", { class: "table" }, h("tbody", {}, drafts.map((c) => h("tr", {},
        h("td", {}, KIND[c.kind]), h("td", {}, h("a", { href: cardHash(c) }, c.name), h("span", { class: "muted" }, `（${c.id}）`)),
        h("td", { class: "bb-look" }, c.look_en || h("span", { class: "t2c-err" }, "（沒有 look_en）")),
        h("td", {}, errs(c) ? T2C.chip(`${errs(c)} 個錯誤`, "err") : T2C.chip("可入庫", "ok"), c.pending ? T2C.chip("有待確認", "warn") : null)))))) : null;

    const statusOf = (cid) => st.characters.find((r) => r.id === cid);
    const placeOf = (lid) => st.locations.find((r) => r.id === lid);
    const card = (c) => {
      const s = c.kind === "character" ? statusOf(c.id) : placeOf(c.id);
      const image = c.kind === "character" ? ((s && s.outfits.find((o) => o.image)) || {}).image : s && s.image;
      return h("article", { class: "card card-flat bb-card" },
        h("a", { class: "bb-thumb", href: cardHash(c) }, image ? h("img", { src: T2C.img(`renders/bible/${image}`, 240), alt: c.name, loading: "lazy" }) : h("span", { class: "muted" }, "沒有定裝圖")),
        h("div", { class: "stack t2c-tight" },
          h("div", { class: "row" }, h("a", { class: "bb-name", href: cardHash(c) }, c.name), h("code", { class: "t2c-small" }, c.id), errs(c) ? T2C.chip(`${errs(c)} 個錯誤`, "err") : null),
          h("p", { class: "t2c-small bb-look" }, c.look_en),
          c.kind === "character" && s ? h("div", { class: "row t2c-tight" }, s.outfits.map((o) => {
            const [label, kind] = STATE[o.state] || [o.state, ""];
            const used = Object.entries(o.used || {}).map(([ch, k]) => `第${ch}章×${k}`).join(" ");
            return h("span", { class: "bb-outfit", title: `${o.note || ""} ${used}`.trim() }, h("code", {}, o.id), T2C.chip(label, kind));
          })) : s ? T2C.chip(...(STATE[s.state] || [s.state, ""])) : null));
    };
    const confirmed = (kind) => data.cards.filter((c) => !c.draft && c.kind === kind);
    const unlisted = Object.entries(st.unlisted || {});

    ctx.view(h("div", { class: "stack t2c-page" },
      h("div", { class: "row" }, h("h1", { class: "t2c-title grow" }, "視覺聖經"),
        h("button", { class: "btn", type: "button", onclick: () => newCardDialog() }, "新增卡片…"),
        h("button", { class: "btn", type: "button", onclick: extractDialog }, "掃描原著＋成卡…"),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => withEnv(ctx, (env) => sheetDialog([], env)) }, "定裝圖出圖…")),
      h("p", { class: "muted" }, "角色外觀只有一個來源：這裡的 look_en 與服裝。分鏡只寫角色 id，編譯時逐字貼上。"),
      draftList,
      unlisted.length ? h("div", { class: "alert alert-warn stack t2c-tight" }, "改編規劃裡出現、但還沒有卡片的人物：",
        h("div", { class: "row t2c-tight" }, unlisted.map(([name, chs]) => h("button", { class: "btn btn-sm", type: "button", onclick: () => newCardDialog(name) }, `${name}（第 ${chs.join("、")} 章）＋`)))) : null,
      h("h2", { class: "t2c-h2" }, `角色（${confirmed("character").length}）`),
      h("div", { class: "bb-grid" }, confirmed("character").map(card)),
      h("h2", { class: "t2c-h2" }, `地點（${confirmed("location").length}）`),
      h("div", { class: "bb-grid" }, confirmed("location").map(card))));
    T2C.onJobEnd(ctx, (job, r) => { if ((r.refresh || []).includes("bible") && !FE.dirty.is()) FE.route(); });
  };

  PAGES["bible/:kind/:id"] = async (ctx) => {
    if (!T2C.need(ctx, "視覺聖經")) return;
    const { kind, id } = ctx.params;
    const draft = ctx.query.draft === "1";
    ctx.crumbs([{ label: "專案", href: "#/" }, { label: "視覺聖經", href: "#/bible" }, { label: `${KIND[kind] || kind} ${id}${draft ? "（草稿）" : ""}` }]);
    const [card] = await Promise.all([T2C.get("/api/bible/card", { kind, id, draft }, ctx), FE.md.load()]);
    const renders = draft ? { files: [] } : await T2C.get("/api/bible/renders", { kind, id }, ctx);

    const issuesEl = h("div", {}, T2C.issues(card.issues, { title: "規則檢查", ok: "規則檢查通過" }));
    const bodyEl = h("div", { class: "bb-body" }, FE.md.render(card.body));
    const editor = T2C.editor(card.text, { rows: 26, mono: true, onsave: () => save(), oninput: (v) => bodyEl.replaceChildren(FE.md.render(stripFront(v))) });
    async function save() {
      if (!draft && card.signature_used && !(await FE.confirm("這張卡片已經挑過定裝圖、可能已經用在分鏡出圖。改 look_en 或服裝之後，之後每一格的外觀都會變，挑好的定裝圖也會過期。確定要存？", { ok: "存檔", danger: true }))) return;
      try {
        const r = await T2C.post("/api/bible/card", { kind, id, draft, text: editor.value }, ctx);
        FE.dirty.set(false);
        issuesEl.replaceChildren(T2C.issues(r.issues, { title: "規則檢查", ok: "規則檢查通過" }) || "");
        FE.toast(r.stale ? "已存檔；定裝圖已過期，請重畫重挑" : "已存檔", r.stale ? "warn" : "ok");
      } catch (error) { FE.fail(error); }
    }
    async function accept() {
      if (FE.dirty.is()) await save();
      if (!(await FE.confirm(`確認入庫「${id}」？入庫後 look_en 就是定案。`, { ok: "確認入庫" }))) return;
      try {
        await T2C.post("/api/bible/accept", { ids: [id], kind }, ctx);
        FE.dirty.set(false);
        FE.toast("已確認入庫", "ok");
        FE.go(FE.hash("bible", kind, id));
      } catch (error) { FE.fail(error); }
    }
    async function pick(file) {
      try {
        await T2C.post("/api/bible/pick", { image: file }, ctx);
        FE.route();
      } catch (error) { FE.fail(error); }
    }

    const groups = {};
    const groupLabel = (f) => `${f.outfit || "地點"}／${{ full: "全身", bust: "胸像" }[f.view] || "空鏡"}`;
    for (const f of renders.files) (groups[groupLabel(f)] = groups[groupLabel(f)] || []).push(f);
    const sheets = draft ? h("div", { class: "alert alert-info" }, "草稿還不能出定裝圖：確認入庫之後再出。")
      : h("section", { class: "stack" },
        h("div", { class: "row" }, h("h2", { class: "t2c-h2 grow" }, "定裝圖"),
          h("button", { class: "btn btn-primary", type: "button", onclick: () => withEnv(ctx, (env) => sheetDialog([id], env)) }, "出圖…")),
        renders.files.length ? Object.entries(groups).map(([label, files]) => h("div", { class: "stack t2c-tight" }, h("b", {}, label),
          h("div", { class: "pn-cands" }, files.map((f) => h("figure", { class: ["pn-cand", f.picked && "pn-picked"] },
            h("button", { class: "pn-thumb", type: "button", title: "選這張", onclick: () => pick(f.file) }, h("img", { src: T2C.img(f.path, 260), alt: f.file, loading: "lazy" })),
            h("figcaption", { class: "row t2c-tight" }, h("span", { class: "grow t2c-small" }, `s${f.seed}`, f.picked ? T2C.chip("已選", "ok") : null),
              h("a", { class: "btn btn-sm btn-ghost", href: T2C.img(f.path), target: "_blank", rel: "noopener" }, "原圖")))))))
          : h("div", { class: "empty" }, "還沒有定裝圖。"));

    ctx.view(h("div", { class: "stack t2c-page" },
      h("div", { class: "row" }, h("h1", { class: "t2c-title grow" }, `${KIND[kind] || kind}：${id}`, draft ? T2C.chip("草稿", "warn") : T2C.chip("定案", "ok")),
        h("button", { class: "btn", type: "button", onclick: save }, "存檔"),
        draft ? h("button", { class: "btn btn-primary", type: "button", onclick: accept }, "確認入庫") : null),
      h("p", { class: "muted t2c-small" }, card.path),
      issuesEl,
      h("div", { class: "bb-split" },
        h("div", { class: "stack" }, h("b", {}, "卡片（frontmatter 給程式，本文給人看）"), editor),
        h("div", { class: "stack" }, h("b", {}, "本文：待確認、原文依據"), bodyEl)),
      sheets));
    T2C.onJobEnd(ctx, (job, r) => { if ((r.refresh || []).includes("bible") && !FE.dirty.is()) FE.route(); });
  };
})();
