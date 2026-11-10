// 視覺聖經（#/bible、#/bible/:kind/:id）：草稿確認入庫、卡片編輯（本文的原文引文並排）、定裝圖候選與挑選、抽取與出圖任務。
// 規則（docs/02_資料格式.md 第 3 節）：look_en 定案後不要改；改了會讓挑好的定裝圖「過期」。
(function () {
  "use strict";
  const { h, PAGES } = FE;
  const KIND = { character: "角色", location: "地點" };
  const STATE = { ok: ["✓ 已挑", "ok"], stale: ["⚠ 過期", "warn"], none: ["－ 未挑", ""], missing: ["✗ 缺卡", "err"] };
  const stripFront = (text) => String(text || "").replace(/^---\s*\n[\s\S]*?\n---\s*\n?/, "");
  // 反推的 state.updated 是 time.time()（秒）；顯示成本地時間，不需要看秒。
  const stamp = (ts) => {
    const d = new Date(Number(ts) * 1000);
    if (!isFinite(d.getTime())) return "";
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  const cardHash = (c) => FE.hash("bible", c.kind, c.id, c.draft ? { draft: 1 } : {});
  // 出圖 profile（F2）：一組 profile＝ComfyUI 上的一組模型；文字顯示「<kind> · <unet 檔名>」，值是名稱。
  const profileList = (env) => ((env && env.comfy && env.comfy.profiles) || [])
    .map((p) => (typeof p === "string" ? { name: p, kind: p, unet: "" } : p)).filter((p) => p && p.name);
  const profileLabel = (p) => `${p.kind || p.name} · ${p.unet || "（沒有指定模型）"}`;

  /* ── 分段卡片（docs/07_微調簡報 步驟 2）：段名與「這一格用哪幾段」都照 t2c/look.py ── */
  // t2c/look.py 的 SECTIONS／SECTION_TEXT／OUTFIT_PARTS／OUTFIT_TEXT。
  const SECTION_NAMES = ["head", "body", "upper", "lower", "accessory"];
  const SECTION_TEXT = { head: "頭部", body: "身形", upper: "上半身", lower: "下半身", accessory: "飾品" };
  const OUTFIT_PARTS = ["top", "bottom", "set"];
  const OUTFIT_TEXT = { top: "上著", bottom: "下著", set: "套裝" };
  const LEGACY_TEXT = "這張卡片是舊格式（只有 look_en），存一次分段就會轉成新格式";
  // 來源：t2c/look.py 的 SHOT_SECTIONS／SHOT_OUTFIT。前端沒有 YAML／Python，這張對照表直接寫死在頁面上；
  // 核心改了分段規則就要同步改這裡。
  const SHOT_TABLE = [
    ["extreme_close", "特寫", "頭部"],
    ["close", "近景", "頭部＋飾品"],
    ["medium", "中景", "頭部＋上半身＋飾品＋上著"],
    ["full", "全身", "頭部＋身形＋上半身＋下半身＋飾品＋上著＋下著"],
    ["wide", "遠景", "頭部＋身形＋上半身＋下半身＋飾品＋上著＋下著"],
    ["extreme_wide", "大遠景", "全部（五段＋上著／下著／套裝）"],
  ];

  /* 只認得 frontmatter 的 sections 與 outfits 兩塊的最小解析器（bible.render_card 的寫法）：
     兩格縮排是段名／服裝 id、四格是 top／bottom／set 或清單項目、六格是服裝的清單項目；
     清單可以是縮排的「- …」或行內的 ["…"]。刻意不做通用 YAML：前端只需要這兩塊，
     解析不到 sections 就回 sections: null，讓呼叫端顯示「舊格式」提示。
     回 {sections: {段名: [短語]} | null, outfits: {id: {top, bottom, set, notes, legacy}}}。 */
  function parseSections(text) {
    const unquote = (raw) => {
      const t = String(raw || "").trim();
      if (t.length > 1 && t[0] === '"' && t[t.length - 1] === '"') {
        try { return JSON.parse(t); } catch (error) { return t.slice(1, -1); }
      }
      if (t.length > 1 && t[0] === "'" && t[t.length - 1] === "'") return t.slice(1, -1);
      return t;
    };
    const flow = (raw) => {
      const inner = String(raw || "").trim().replace(/^\[/, "").replace(/\]$/, "").trim();
      return inner ? inner.split(/,\s*/).map(unquote).filter(Boolean) : [];
    };
    const itemOf = (line) => { const m = /^\s*-\s+(.*)$/.exec(line); return m ? unquote(m[1]) : ""; };
    const KEY = /^([A-Za-z0-9_-]+):\s*(.*)$/;
    const out = { sections: null, outfits: {} };
    let inside = false, block = null, id = null, part = null, fold = false;
    for (const line of String(text || "").split(/\r?\n/)) {
      if (/^---\s*$/.test(line)) { if (inside) break; inside = true; continue; }
      if (!inside || !line.trim()) continue;
      const indent = line.length - line.replace(/^ +/, "").length;
      if (indent === 0) {
        block = /^sections:/.test(line) ? "sections" : /^outfits:/.test(line) ? "outfits" : null;
        if (block === "sections") out.sections = {};
        id = null; part = null; fold = false;
        continue;
      }
      if (!block) continue;
      const m = KEY.exec(line.trim());
      if (indent === 2) {
        if (!m) continue;
        id = m[1]; part = null; fold = false;
        if (block === "sections") { out.sections[id] = flow(m[2]); continue; }
        out.outfits[id] = { top: [], bottom: [], set: [], notes: "", legacy: "" };
        const value = m[2].trim();
        if (/^[>|][-+]?$/.test(value)) fold = true;            // 舊格式的整句寫成 >- 折行
        else if (value && value !== "[]") out.outfits[id].legacy = unquote(value);
        continue;
      }
      if (!id) continue;
      if (block === "sections") { const item = itemOf(line); if (item) out.sections[id].push(item); continue; }
      if (m && OUTFIT_PARTS.indexOf(m[1]) >= 0) { part = m[1]; fold = false; out.outfits[id][part] = flow(m[2]); continue; }
      if (m && m[1] === "notes") { out.outfits[id].notes = unquote(m[2]); continue; }
      if (fold) { out.outfits[id].legacy = `${out.outfits[id].legacy} ${line.trim()}`.trim(); continue; }
      const item = itemOf(line);
      if (item && part) out.outfits[id][part].push(item);
    }
    return out;
  }

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

  /* 反推設定（docs/07_微調簡報 步驟 4）：整本掃描＋成卡草稿。服務層是 server/tasks.py 的 reverse_task，
     進度與批次快取都在 build/reverse/，中斷後再跑一次就從沒掃過的章接上。 */
  function reverseDialog() {
    const upto = T2C.num("", { min: 1, max: 9999, placeholder: "全部" });
    const minChapters = T2C.num(2, { min: 1, max: 99 });
    const budget = T2C.num("", { min: 1024, max: 200000, step: 1024, placeholder: "32768" });
    const force = h("input", { type: "checkbox" });
    const numOf = (el) => (String(el.value || "").trim() ? Number(el.value) : null);   // 空字串不要送，交給後端用預設
    FE.modal({
      title: "反推設定（整本掃描＋成卡）",
      body: h("div", { class: "stack" },
        h("p", { class: "muted" }, "讀專案 source/ 的每一章，分批掃描、累積證據，最後替出現夠多章的角色與地點寫卡片草稿。可以中斷，下次接著跑（build/reverse/）。"),
        h("div", { class: "row t2c-tight" },
          h("label", { class: "row t2c-inline" }, "到第幾章", upto),
          h("label", { class: "row t2c-inline" }, "每批 token 預算", budget)),
        h("label", { class: "row t2c-inline" }, "至少出現幾章才成卡", minChapters),
        h("p", { class: "muted t2c-small" }, "「到第幾章」留空＝全部；「至少出現幾章才成卡」填 1＝只出現一章的配角也成卡；「每批 token 預算」留空＝32768（越大一批塞越多章，每次呼叫也越貴）。"),
        h("label", { class: "check" }, force, "重新掃描全部章節（覆蓋已有的掃描快取）")),
      foot: (done) => [
        h("button", { class: "btn", type: "button", onclick: () => done() }, "取消"),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => {
          done();
          T2C.run("/api/task/reverse", { upto: numOf(upto), min_chapters: numOf(minChapters), budget: numOf(budget), force: force.checked });
        } }, "開始"),
      ],
    });
  }

  function sheetDialog(ids, env, ctx) {
    const full = h("input", { type: "checkbox", checked: true });
    const bust = h("input", { type: "checkbox" });
    const count = T2C.num("", { min: 1, max: 8, placeholder: "依 project.yaml" });
    const more = T2C.num("", { min: 1, max: 8, placeholder: "－" });
    // 出圖預設是「這一組 profile 自己的」：換 profile 要重填清單，不然會送出別組的 preset（伺服器會擋）。
    const presetHost = h("div", { class: "stack t2c-tight" });
    const preset = h("select", { "aria-label": "出圖預設" });
    let presetList = [];
    let presetDefault = "";
    function fillPresets(list, def) {
      presetList = Array.isArray(list) ? list : [];
      presetDefault = def || "";
      const value = presetList.indexOf(preset.value) >= 0 ? preset.value : (presetDefault || presetList[0] || "");
      preset.replaceChildren(...(presetList.length
        ? presetList.map((p) => h("option", { value: p, selected: p === value }, p === presetDefault ? p + "（預設）" : p))
        : [h("option", { value: "" }, "（這一組沒有 presets）")]));
      presetHost.replaceChildren(...(presetList.length
        ? [h("label", { class: "field" }, h("span", { class: "t2c-small" }, "出圖預設（步數／cfg）"), preset)]
        : [h("span", { class: "muted t2c-small" }, "這一組沒有 presets，出圖會用 workflow 自己的取樣設定。")]));
    }
    fillPresets((env && env.presets) || [], (env && env.default_preset) || "");
    // 出圖 profile：同一臺 ComfyUI 一次只掛一組模型，換 profile 就要先去 ComfyUI 換成那一組的模型。
    const profs = profileList(env);
    const profNow = (env && env.comfy && env.comfy.profile) || "";
    const profNote = h("p", { class: "muted t2c-small" });
    const profile = h("select", { "aria-label": "出圖 profile", onchange: () => { loadProfile(); } },
      profs.map((p) => h("option", { value: p.name, selected: p.name === profNow }, profileLabel(p))));
    const pickedProf = () => profs.find((p) => p.name === profile.value) || profs[0] || null;
    function syncProfNote() {
      const p = pickedProf();
      const missing = p && !p.unet;
      profNote.textContent = (missing ? "⚠ 這一組還沒有填 unet 模型檔名，出圖會失敗（先到設定頁補）。" : "")
        + "同一臺 ComfyUI 一次只掛一組模型：換 profile 就要先在 ComfyUI 換成那一組的模型。"
        + (p ? "目前：" + profileLabel(p) + "。" : "");
    }
    async function loadProfile() {
      syncProfNote();
      const next = profile.value;
      if (!next) return;
      try {
        const fresh = await T2C.get("/api/env", { profile: next }, ctx);
        fillPresets(fresh.presets || [], fresh.default_preset || "");
      } catch (error) {
        if (error.name === "AbortError") throw error;
        FE.fail(error);
      }
    }
    syncProfNote();
    FE.modal({
      title: ids && ids.length ? `定裝圖：${ids.join("、")}` : "定裝圖：全部定案的角色與地點",
      body: h("div", { class: "stack" },
        h("p", { class: "muted" }, "角色每套服裝一張（3:4），地點一張空鏡（4:3）。已經有的跳過；「加畫」會用新的 seed 再多畫幾張。"),
        h("div", { class: "row" }, h("label", { class: "check" }, full, "全身"), h("label", { class: "check" }, bust, "胸像")),
        h("div", { class: "row" }, h("label", { class: "row t2c-inline" }, "每張幾個候選", count), h("label", { class: "row t2c-inline" }, "或加畫", more)),
        // 先選 profile（哪一組模型），再選預設（步數／cfg）：預設清單是那一組 profile 自己的。
        profs.length ? h("div", { class: "stack t2c-tight" },
          h("label", { class: "field" }, h("span", { class: "t2c-small" }, "出圖 profile（哪一組模型）"), profile), profNote) : null,
        presetHost),
      foot: (done) => [
        h("button", { class: "btn", type: "button", onclick: () => done() }, "取消"),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => {
          const views = [full.checked && "full", bust.checked && "bust"].filter(Boolean);
          if (!views.length) return FE.toast("至少選一種視角", "warn");
          done();
          T2C.run("/api/task/bible_sheet", { ids: ids || [], views, candidates: count.value ? Number(count.value) : null,
            more: more.value ? Number(more.value) : 0, preset: presetList.length ? (preset.value || null) : null,
            profile: profs.length ? (profile.value || null) : null });
        } }, "出圖"),
      ],
    });
  }

  async function withEnv(ctx, fn) {
    let env = null;
    try { env = await T2C.get("/api/env", {}, ctx); } catch (error) { if (error.name === "AbortError") return; }
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

  /* 反推進度（GET /api/bible/reverse）：state 是空的＝沒跑過，只寫一句它會做什麼；
     跑過就寫章數、批次、跳過的章、草稿與最後更新時間，草稿 id 連到卡片頁（draft=1）。
     端點回不來只顯示一行錯誤，不能讓整頁掛掉。 */
  function reverseCard(rev, cards) {
    if (rev.error) return h("div", { class: "alert alert-warn" }, `反推進度讀不到：${rev.error}`);
    const state = rev.state || {};
    const drafts = Array.isArray(rev.drafts) ? rev.drafts : [];
    const chapters = Array.isArray(rev.chapters) ? rev.chapters : [];
    if (!Object.keys(state).length) return h("section", { class: "card stack t2c-tight" },
      h("h2", { class: "card-title" }, "反推設定"),
      h("p", { class: "muted" }, "還沒跑過反推。按右上角的「反推設定（整本掃描＋成卡）…」：它會分批讀 source/ 的每一章，替出現夠多章的角色與地點寫卡片草稿。草稿不算定案，要你看過、改過才確認入庫。"));
    // 草稿的類別要看卡片本身；對不到的 id 當角色（草稿通常是角色）。
    const cardOf = (id) => (cards || []).find((c) => c.draft && c.id === id) || (cards || []).find((c) => c.id === id);
    return h("section", { class: "card stack" },
      h("h2", { class: "card-title" }, "反推設定（整本掃描＋成卡）"),
      h("div", { class: "row t2c-tight" },
        T2C.chip(`已完成 ${chapters.length} 章`, "ok"),
        T2C.chip(`${state.batches || 0} 批`),
        state.skipped ? T2C.chip(`跳過 ${state.skipped} 章（上次已掃過）`) : null,
        T2C.chip(`草稿 ${drafts.length} 張`, drafts.length ? "warn" : ""),
        state.upto ? T2C.chip(`只掃到第 ${state.upto} 章`) : null,
        state.stopped ? T2C.chip("上次被停止，可以接著跑", "warn") : null,
        state.updated ? h("span", { class: "muted t2c-small" }, `最後更新 ${stamp(state.updated)}`) : null),
      h("p", { class: "muted t2c-small" }, chapters.length ? `掃過：第 ${chapters.join("、")} 章。再跑一次會跳過這些章，只掃後面的；要重掃就勾「重新掃描全部章節」。` : "還沒有任何一批掃描完成。"),
      drafts.length ? h("div", { class: "stack t2c-tight" },
        h("b", { class: "t2c-small" }, "草稿（點開看「待確認」與原文依據，改好再確認入庫）"),
        h("div", { class: "row t2c-tight bb-rev-drafts" }, drafts.map((id) => {
          const c = cardOf(id);
          return h("a", { class: "btn btn-sm btn-ghost", href: FE.hash("bible", (c && c.kind) || "character", id, { draft: 1 }) },
            c ? `${c.name}（${id}）` : id);
        })))
        : h("p", { class: "muted t2c-small" }, "還沒有草稿。"));
  }

  PAGES.bible = async (ctx) => {
    if (!T2C.need(ctx, "視覺聖經")) return;
    ctx.crumbs([{ label: "總覽", href: "#/project" }, { label: "視覺聖經" }]);
    // 過期格（docs/07_微調簡報 步驟 2）：卡片的分段或服裝改了，已經出過圖的格要重畫。
    // 端點回不來只提示一行，不能讓整頁開不起來。
    const [data, stale, rev] = await Promise.all([
      T2C.get("/api/bible", {}, ctx),
      T2C.get("/api/bible/stale", {}, ctx).catch((error) => {
        if (error.name === "AbortError") throw error;
        return { error: (error && error.message) || String(error) };
      }),
      T2C.get("/api/bible/reverse", {}, ctx).catch((error) => {
        if (error.name === "AbortError") throw error;
        return { error: (error && error.message) || String(error) };
      }),
    ]);
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

    // 只重畫過期格：一次一章（/api/task/render 帶 stale: true，沒有過期時任務自己正常結束）。
    async function rerenderStale(ch) {
      if (!(await FE.confirm(`第 ${ch.chapter} 章有 ${ch.count} 格過期：只重畫這 ${ch.count} 格？\n其他格不動；這幾格原本的候選圖會被新的蓋掉（已經選的圖還在，但要自己重挑）。`, { ok: "只重畫這些格" }))) return;
      T2C.run("/api/task/render", { chapter: ch.chapter, stale: true });
    }
    // level＝warn 是「臉或整段外觀變了」，比換衣服嚴重，前面加一個記號（t2c/stale.py 的 compare）。
    const staleReason = (p) => {
      const list = p.reasons || [];
      const text = list.map((r) => r.message).filter(Boolean).join("；");
      return text ? (list.some((r) => r.level === "warn") ? `⚠ ${text}` : text) : "（沒有寫原因）";
    };
    function staleCard() {
      if (stale.error) return h("div", { class: "alert alert-warn" }, `過期格讀不到：${stale.error}`);
      if (!stale.total) return h("section", { class: "card stack t2c-tight" },
        h("h2", { class: "card-title" }, "過期格"), h("p", { class: "muted" }, "沒有過期的格"));
      return h("section", { class: "card stack" },
        h("h2", { class: "card-title" }, `過期格（有 ${stale.total} 格過期）`),
        h("p", { class: "muted" }, "卡片的外觀（分段或服裝）改了：這些格當初貼的是舊句子，重畫才會換成新的。同一格用同一個 seed，重畫會蓋掉那些格原本的候選圖。"),
        (stale.chapters || []).map((ch) => h("div", { class: "stack t2c-tight" },
          h("div", { class: "row" }, h("b", { class: "grow" }, `第 ${ch.chapter} 章${ch.title ? "｜" + ch.title : ""}：${ch.count} 格`),
            ch.error ? T2C.chip("分鏡讀不懂，這一章算不出來", "err") : null,
            h("button", { class: "btn btn-sm", type: "button", onclick: () => rerenderStale(ch), disabled: !!ch.error }, "只重畫這些格…")),
          h("table", { class: "table bb-stale" }, h("tbody", {}, (ch.panels || []).map((p) => h("tr", {},
            h("td", { class: "t2c-small" }, `第 ${p.page} 頁第 ${p.slot} 格`),
            h("td", {}, h("code", {}, p.id)),
            h("td", { class: "t2c-small" }, staleReason(p)),
            h("td", { class: "t2c-small" }, `${(p.files || []).length} 張候選`))))))));
    }

    ctx.view(h("div", { class: "stack t2c-page" },
      h("div", { class: "row" }, h("h1", { class: "t2c-title grow" }, "視覺聖經"),
        h("button", { class: "btn", type: "button", onclick: () => newCardDialog() }, "新增卡片…"),
        h("button", { class: "btn", type: "button", onclick: extractDialog }, "掃描原著＋成卡…"),
        h("button", { class: "btn", type: "button", onclick: reverseDialog }, "反推設定（整本掃描＋成卡）…"),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => withEnv(ctx, (env) => sheetDialog([], env, ctx)) }, "定裝圖出圖…")),
      h("p", { class: "muted" }, "角色外觀只有一個來源：這裡的 look_en 與服裝。分鏡只寫角色 id，編譯時逐字貼上。"),
      staleCard(),
      reverseCard(rev, data.cards),
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
    ctx.crumbs([{ label: "總覽", href: "#/project" }, { label: "視覺聖經", href: "#/bible" }, { label: `${KIND[kind] || kind} ${id}${draft ? "（草稿）" : ""}` }]);
    const [card] = await Promise.all([T2C.get("/api/bible/card", { kind, id, draft }, ctx), FE.md.load()]);
    const renders = draft ? { files: [] } : await T2C.get("/api/bible/renders", { kind, id }, ctx);

    const issuesEl = h("div", {}, T2C.issues(card.issues, { title: "規則檢查", ok: "規則檢查通過" }));
    const bodyEl = h("div", { class: "bb-body" }, FE.md.render(card.body));
    const editor = T2C.editor(card.text, { rows: 26, mono: true, onsave: () => save(), oninput: (v) => bodyEl.replaceChildren(FE.md.render(stripFront(v))) });

    /* ── 分段編輯器（docs/07_微調簡報 步驟 2）：五段＋每套服裝一張小卡，放在 YAML 文字框上面 ──
       存檔走 POST /api/bible/card/sections，frontmatter 由後端改寫；前端不拼 YAML，只送結構化的資料。 */
    const secErr = h("p", { class: "t2c-err t2c-small" });
    const parsed = parseSections(card.text);
    const boxes = {};
    const fits = [];
    const lines = (value) => String(value || "").split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
    /** 分段的多行輸入框：一行一個英文短語。 */
    function secText(value) {
      const el = h("textarea", { class: "bb-sec-text", spellcheck: "false", oninput: () => FE.dirty.set(true) });
      el.value = value || "";
      return el;
    }
    async function saveSections() {
      const sections = {};
      for (const name of SECTION_NAMES) sections[name] = lines(boxes[name].value);
      if (!SECTION_NAMES.some((name) => sections[name].length)) {
        FE.toast("五段都空：至少要填一段，不然這張卡片就沒有外觀了（舊的 look_en 會被取代）", "warn");
        return;
      }
      const outfits = {};
      for (const row of fits) outfits[row.id] = { top: lines(row.top.value), bottom: lines(row.bottom.value),
        set: lines(row.set.value), notes: row.notes.value.trim() };
      secErr.textContent = "";
      try {
        const r = await T2C.post("/api/bible/card/sections", { kind, id, draft, sections, outfits }, ctx);
        FE.dirty.set(false);
        FE.toast(r.stale ? "已存分段；定裝圖已過期，請重畫重挑" : "已存分段", r.stale ? "warn" : "ok");
        FE.route();                                   // 重載頁面：YAML 文字框與檢查結果才是新的 frontmatter
      } catch (error) {
        secErr.textContent = (error && error.message) || String(error);   // 後端的訊息照顯示，不要吞掉
        FE.fail(error);
      }
    }
    /** 舊卡片：請後端用文字規則拆成分段草稿，填進下面的輸入框（不寫檔，人看過再存）。 */
    async function splitLegacy() {
      secErr.textContent = "";
      try {
        const r = await T2C.post("/api/bible/card/split", { kind, id, draft }, ctx);
        for (const name of SECTION_NAMES) boxes[name].value = ((r.sections || {})[name] || []).join("\n");
        const list = r.outfits || {};
        for (const row of fits) {
          const fit = list[row.id];
          if (!fit) continue;
          for (const part of OUTFIT_PARTS) row[part].value = (fit[part] || []).join("\n");
          if (fit.notes) row.notes.value = fit.notes;
        }
        FE.dirty.set(true);
        FE.toast((r.note || "已拆成分段草稿") + "；看過再按「儲存分段」", "ok");
      } catch (error) {
        secErr.textContent = (error && error.message) || String(error);
        FE.fail(error);
      }
    }

    const secGrid = h("div", { class: "bb-sec" }, SECTION_NAMES.map((name) => {
      boxes[name] = secText(((parsed.sections || {})[name] || []).join("\n"));
      return h("label", { class: "field" }, h("span", { class: "t2c-small" }, `${SECTION_TEXT[name]}（${name}）`), boxes[name]);
    }));
    const fitIds = Object.keys(parsed.outfits).length ? Object.keys(parsed.outfits) : ["default"];
    const fitCards = fitIds.map((oid) => {
      const fit = parsed.outfits[oid] || { top: [], bottom: [], set: [], notes: "", legacy: "" };
      const row = { id: oid, notes: h("input", { type: "text", class: "grow", placeholder: "中文說明：什麼時候穿（給人看）",
        oninput: () => FE.dirty.set(true) }) };
      for (const part of OUTFIT_PARTS) row[part] = secText((fit[part] || []).join("\n"));
      if (fit.legacy) row.top.value = fit.legacy;       // 舊格式的整句先放進上著，存檔才不會無聲消失
      row.notes.value = fit.notes || "";
      fits.push(row);
      return h("div", { class: "bb-outfit-card stack t2c-tight" },
        h("div", { class: "row" }, h("b", {}, "服裝"), h("code", {}, oid), fit.legacy ? T2C.chip("舊格式：整句", "warn") : null),
        fit.legacy ? h("p", { class: "muted t2c-small" }, `原本是一整句：「${fit.legacy}」——已經先放進上著，存分段就換成新格式。`) : null,
        h("div", { class: "bb-sec" }, OUTFIT_PARTS.map((part) => h("label", { class: "field" },
          h("span", { class: "t2c-small" }, `${OUTFIT_TEXT[part]}（${part}）`), row[part]))),
        h("label", { class: "field" }, h("span", { class: "t2c-small" }, "中文說明（notes）"), row.notes));
    });
    const shotTable = h("table", { class: "table bb-shots" }, h("tbody", {}, SHOT_TABLE.map(([key, label, text]) =>
      h("tr", {}, h("td", {}, label, " ", h("code", { class: "t2c-small" }, key)), h("td", { class: "t2c-small" }, text)))));
    const secBlock = kind === "character"
      ? h("section", { class: "card stack t2c-tight" },
        h("div", { class: "row" }, h("b", { class: "grow" }, "分段（一行一個英文短語）"),
          h("button", { class: "btn btn-sm btn-primary", type: "button", onclick: saveSections }, "儲存分段")),
        parsed.sections ? null : h("div", { class: "alert alert-warn row t2c-tight" },
          h("span", { class: "grow" }, LEGACY_TEXT),
          h("button", { class: "btn btn-sm", type: "button", title: "用文字規則把 look_en 與整句服裝拆進下面五段（不會直接存檔）", onclick: splitLegacy }, "拆成分段（草稿）")),
        h("p", { class: "muted t2c-small" }, "有分段就用分段，沒有才退回 look_en（t2c/look.py）。分鏡的 shot 決定這一格貼哪幾段："),
        shotTable, secGrid,
        fitCards.length ? h("div", { class: "stack t2c-tight" }, h("b", { class: "t2c-small" }, "服裝（outfits）"), fitCards) : null,
        secErr)
      : h("section", { class: "card stack t2c-tight" }, h("b", {}, "分段"),
        h("p", { class: "muted t2c-small" }, "地點不分段：地點只有一張空鏡，外觀照 look_en 貼（t2c/look.py 的 sections／outfits 只用在角色）。"));
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
          h("button", { class: "btn btn-primary", type: "button", onclick: () => withEnv(ctx, (env) => sheetDialog([id], env, ctx)) }, "出圖…")),
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
        h("div", { class: "stack" }, secBlock, h("b", {}, "卡片（frontmatter 給程式，本文給人看）"), editor),
        h("div", { class: "stack" }, h("b", {}, "本文：待確認、原文依據"), bodyEl)),
      sheets));
    T2C.onJobEnd(ctx, (job, r) => { if ((r.refresh || []).includes("bible") && !FE.dirty.is()) FE.route(); });
  };
})();
