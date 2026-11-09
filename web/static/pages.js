// 章節頁的「頁面」分頁：每頁即時預覽（組版＋嵌字，不寫檔）、到嵌字頁微調、「輸出頁面」任務（寫 pages/chNNN/）。
(function () {
  "use strict";
  const { h } = FE;

  T2C.tabs.pages = async (ctx, body, { n }) => {
    let data;
    try {
      data = await T2C.get("/api/chapter/pages", { chapter: n }, ctx);
    } catch (error) {
      if (error.name === "AbortError") throw error;
      body.replaceChildren(h("div", { class: "alert alert-err" }, error.message));
      return;
    }
    const live = FE.store.get("pages.live", true) !== false;
    const toggle = h("input", { type: "checkbox", checked: live, onchange: () => { FE.store.set("pages.live", toggle.checked); FE.route(); } });
    const exported = data.pages.filter((p) => p.png).length;
    const single = FE.store.get("pages.single", false) === true;
    const singleBox = h("input", { type: "checkbox", checked: single, onchange: () => { FE.store.set("pages.single", singleBox.checked); FE.route(); } });
    /** 下載連結：整章或單頁的 PDF／CBZ（右翻）；頁面 PNG 還沒齊就不能按。 */
    const download = (format, label, page) => {
      const q = { project: T2C.project(), chapter: n, format };
      if (page) q.page = page;
      if (single && format === "pdf") q.single = "true";
      return data.export.ready
        ? h("a", { class: "btn btn-sm", href: `/api/chapter/export?${new URLSearchParams(q)}`, download: "" }, label)
        : h("button", { class: "btn btn-sm", type: "button", disabled: true, title: data.export.message }, label);
    };
    body.replaceChildren(h("div", { class: "stack" },
      h("div", { class: "row" },
        h("span", { class: "grow" }, "下載（右翻）：",
          h("span", { class: "muted" }, data.export.ready ? "　用已輸出的頁面 PNG 打包，同時存在專案的 out/。" : `　${data.export.message}`)),
        h("label", { class: "check" }, singleBox, "PDF 用單頁檢視開啟"),
        download("pdf", "整章 PDF"), download("cbz", "整章 CBZ")),
      data.export.warnings.length ? h("div", { class: "alert alert-warn" }, data.export.warnings.join("；")) : null,
      h("div", { class: "row" },
        h("span", { class: "grow" }, `${data.pages.length} 頁，已輸出 ${exported} 頁。`,
          h("span", { class: "muted" }, "　預覽是用目前的選圖與嵌字即時組的；按「輸出頁面」才會寫成 PNG。")),
        h("label", { class: "check" }, toggle, "即時預覽（關掉就看已輸出的 PNG）"),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => T2C.run("/api/task/pages", { chapter: n }) }, "輸出整章頁面")),
      h("div", { class: "pg-grid" }, data.pages.map((p) => {
        const src = live
          ? `/api/letter/preview.jpg?${new URLSearchParams({ project: T2C.project(), chapter: n, page: p.page })}`
          : p.png ? T2C.img(p.png, 900, Math.round(p.mtime)) : "";
        return h("figure", { class: "card card-flat stack t2c-tight pg-page" },
          h("div", { class: "row" }, h("b", { class: "grow" }, `第 ${p.page} 頁`), T2C.chip(`模板 ${p.template}・${p.panels} 格`),
            p.png ? T2C.chip("已輸出", "ok") : T2C.chip("未輸出")),
          src ? h("a", { href: live ? src : T2C.img(p.png), target: "_blank", rel: "noopener", title: "開大圖" },
            h("img", { class: "pg-img", src, alt: `第 ${p.page} 頁`, loading: "lazy", style: { "aspect-ratio": `${data.size[0]} / ${data.size[1]}` } }))
            : h("div", { class: "empty" }, "還沒有輸出"),
          h("div", { class: "row t2c-tight" },
            h("a", { class: "btn btn-sm", href: FE.hash("letter", { project: T2C.project(), chapter: n, page: p.page }) }, "嵌字微調"),
            h("button", { class: "btn btn-sm", type: "button", onclick: () => T2C.run("/api/task/pages", { chapter: n, page: p.page }) }, "只輸出這一頁"),
            p.png ? h("a", { class: "btn btn-sm", download: "", href: `/api/chapter/export?${new URLSearchParams({ project: T2C.project(), chapter: n, format: "pdf", page: p.page })}` }, "這頁 PDF") : null));
      }))));
  };
})();
