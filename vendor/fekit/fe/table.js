/* fekit table.js — 互動表格（Tabulator 包裝）。介面與合約見 docs/02_API合約.md 第 9.5 節。
 *
 * Tabulator 的欄位標題、空表格提示、下拉選項預設都用 innerHTML 顯示，這裡一律換成純文字節點，
 * 所以資料或標題裡有 HTML 也只會被當成文字。只加上 FE.table；載入本身不動 DOM。 */
(function () {
  "use strict";

  const FE = window.FE;
  if (!FE) {
    console.error("fekit：table.js 要在 core.js 之後載入");
    return;
  }
  if (FE.table) {
    console.warn("fekit：table.js 被載入了兩次，第二次已略過");
    return;
  }

  const { h } = FE;
  const SELF_URL = (document.currentScript && document.currentScript.src) || "";

  const LANG = {
    "zh-tw": {
      data: { loading: "載入中", error: "發生錯誤" },
      groups: { item: "項", items: "項" },
      pagination: {
        page_size: "每頁筆數", page_title: "顯示頁面", first: "第一頁", first_title: "第一頁",
        last: "最後一頁", last_title: "最後一頁", prev: "上一頁", prev_title: "上一頁",
        next: "下一頁", next_title: "下一頁", all: "全部",
        counter: { showing: "顯示", of: "／共", rows: "列", pages: "頁" },
      },
      headerFilters: { default: "篩選…", columns: {} },
    },
  };

  /* ──────────────── 載入 Tabulator 與樣式 ──────────────── */

  let loading = null;

  function assetUrl(path) {
    if (SELF_URL) return new URL(path, SELF_URL).href;
    const mine = Array.from(document.scripts).find((node) => /\/table\.js(\?|$)/.test(node.src));
    return new URL(path, mine ? mine.src : document.baseURI).href;
  }

  function loadStyle(href) {
    const existing = Array.from(document.querySelectorAll('link[rel="stylesheet"]')).find((node) => node.href === href);
    if (existing) return Promise.resolve();
    return new Promise((done, fail) => {
      const node = document.createElement("link");
      node.rel = "stylesheet";
      node.href = href;
      node.onload = () => done();
      node.onerror = () => fail(new Error(`FE.table：載入樣式失敗（${href}）`));
      document.head.append(node);
    });
  }

  function loadScript(src) {
    if (window.Tabulator) return Promise.resolve();
    return new Promise((done, fail) => {
      const node = document.createElement("script");
      node.src = src;
      node.onload = () => (window.Tabulator ? done() : fail(new Error("FE.table：Tabulator 載入後找不到 window.Tabulator")));
      node.onerror = () => fail(new Error(`FE.table：載入 Tabulator 失敗（${src}）`));
      document.head.append(node);
    });
  }

  function load(options = {}) {
    if (loading) return loading;
    // 順序固定：Tabulator 的樣式在前，table.css 在後才蓋得過去。
    loading = loadStyle(options.css || assetUrl("../vendor/tabulator/tabulator.min.css"))
      .then(() => loadStyle(options.theme || assetUrl("../css/table.css")))
      .then(() => loadScript(options.src || assetUrl("../vendor/tabulator/tabulator.min.js")))
      .catch((error) => {
        loading = null;
        throw error;
      });
    return loading;
  }

  /* ──────────────── 欄位 ──────────────── */

  const textNode = (text) => {
    // 回傳節點：Tabulator 收到字串會當 HTML，收到節點才當成內容原樣放進去。
    const span = document.createElement("span");
    span.textContent = text === undefined || text === null ? "" : String(text);
    return span;
  };

  function toColumn(col) {
    if (!col || !col.field) throw new TypeError("FE.table：每個欄位都要有 field");
    const type = col.type || "text";
    const out = {
      field: col.field,
      title: col.title === undefined ? col.field : col.title,
      titleFormatter: (cell) => textNode(cell.getValue()),
      headerSort: col.sort !== false,
    };
    if (col.width) out.width = col.width;
    if (col.align) out.hozAlign = col.align;

    const safeItems = { itemFormatter: (label) => textNode(label) };

    if (type === "number") {
      out.sorter = "number";
      out.hozAlign = col.align || "right";
      if (col.edit) out.editor = "number";
      if (col.filter) Object.assign(out, { headerFilter: "number", headerFilterFunc: "=" });
    } else if (type === "bool") {
      out.formatter = "tickCross";
      out.sorter = "boolean";
      out.hozAlign = col.align || "center";
      if (col.edit) Object.assign(out, { editor: "tickCross", editorParams: { tristate: false } });
      if (col.filter) {
        Object.assign(out, {
          headerFilter: "tickCross",
          headerFilterParams: { tristate: true },
          headerFilterEmptyCheck: (value) => value === null,
        });
      }
    } else if (type === "select") {
      const values = Array.isArray(col.values) ? col.values.map(String) : [];
      if (col.edit) Object.assign(out, { editor: "list", editorParams: { values, autocomplete: false, clearable: false, ...safeItems } });
      if (col.filter) {
        Object.assign(out, {
          headerFilter: "list",
          headerFilterParams: { values, clearable: true, ...safeItems },
          headerFilterFunc: "=",
        });
      }
    } else {
      if (col.edit) out.editor = "input";
      if (col.filter) out.headerFilter = "input";
    }

    if (typeof col.render === "function") {
      out.formatter = (cell) => {
        const result = col.render(cell.getValue(), cell.getRow().getData());
        return result && result.nodeType ? result : textNode(result);
      };
    }
    return out;
  }

  /* ──────────────── 掛載 ──────────────── */

  function mount(el, options = {}) {
    if (!window.Tabulator) throw new Error("FE.table：還沒載入 Tabulator，請先 await FE.table.load()");
    const target = typeof el === "string" ? document.querySelector(el) : el;
    if (!target) throw new Error("FE.table.mount()：找不到容器");
    if (!Array.isArray(options.columns) || !options.columns.length) throw new TypeError("FE.table.mount()：需要 columns");

    const index = options.index || "id";
    const heightOpt = options.height === undefined ? "20rem" : options.height;
    const config = {
      data: Array.isArray(options.data) ? options.data : [],
      index,
      columns: options.columns.map(toColumn),
      layout: "fitColumns",
      locale: "zh-tw",
      langs: LANG,
      placeholder: h("div", { class: "empty" }, options.empty || "沒有資料"),
      selectableRows: options.select ? true : false,
      movableColumns: false,
    };
    if (heightOpt === null) {
      Object.assign(config, { pagination: true, paginationMode: "local", paginationSize: 25, paginationSizeSelector: [10, 25, 50, 100] });
    } else {
      config.height = typeof heightOpt === "number" ? `${heightOpt}px` : heightOpt;
    }

    const table = new window.Tabulator(target, config);
    let destroyed = false;
    const filters = new Map();   // set_filter 目前套用的篩選，換掉時要精確移除舊的
    const ready = new Promise((done) => table.on("tableBuilt", () => done()));

    // 儲存格改完：交給 on_edit；它說「不行」就把值還原。
    table.on("cellEdited", (cell) => {
      if (!options.on_edit) return;
      const row = { ...cell.getRow().getData() };
      const field = cell.getField();
      const value = cell.getValue();
      const old = cell.getOldValue();
      const undo = (error) => {
        if (destroyed) return;
        cell.restoreOldValue();
        if (error) FE.fail(error);
      };
      let result;
      try {
        result = options.on_edit(row, field, value, old);
      } catch (error) {
        undo(error);
        return;
      }
      if (result === false) {
        undo();
      } else if (result && typeof result.then === "function") {
        result.then((outcome) => outcome === false && undo(), undo);
      }
    });

    if (options.select && options.on_select) {
      table.on("rowSelectionChanged", (data) => options.on_select(data.map((row) => ({ ...row }))));
    }

    return {
      table,
      ready,
      data: () => table.getData().map((row) => ({ ...row })),
      set_data: (rows) => table.setData(Array.isArray(rows) ? rows : []),
      add: (row) => table.addRow(row),
      remove: (key) => table.deleteRow(key),
      selected: () => table.getSelectedData().map((row) => ({ ...row })),
      set_filter(field, value) {
        if (filters.has(field)) table.removeFilter(field, "like", filters.get(field));
        filters.delete(field);
        if (value === undefined || value === null || value === "") return;
        filters.set(field, value);
        table.addFilter(field, "like", value);
      },
      redraw: () => table.redraw(true),
      destroy() {
        if (destroyed) return;
        destroyed = true;
        table.destroy();
      },
    };
  }

  FE.table = { load, mount };
})();
