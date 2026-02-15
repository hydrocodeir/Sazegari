// Advanced Form Builder (Graphical) - builds schema_text
const FIELD_TYPES = ["text","number","textarea","date","select","multiselect","file"];

function addFieldRow(prefill){
  const tbody = document.getElementById("fieldsBody");
  if(!tbody) return;
  const tr = document.createElement("tr");

  const name = document.createElement("input");
  name.className = "form-control form-control-sm";
  name.placeholder = "key (e.g. year)";
  name.value = prefill?.name || "";

  const label = document.createElement("input");
  label.className = "form-control form-control-sm";
  label.placeholder = "برچسب";
  label.value = prefill?.label || "";

  const type = document.createElement("select");
  type.className = "form-select form-select-sm";
  FIELD_TYPES.forEach(t=>{
    const opt = document.createElement("option");
    opt.value = t; opt.textContent = t;
    type.appendChild(opt);
  });
  type.value = prefill?.type || "text";

  const required = document.createElement("input");
  required.type = "checkbox";
  required.className = "form-check-input";
  required.checked = !!prefill?.required;

  const regex = document.createElement("input");
  regex.className = "form-control form-control-sm";
  regex.placeholder = "regex (اختیاری)";
  regex.value = prefill?.regex || "";

  const options = document.createElement("input");
  options.className = "form-control form-control-sm";
  options.placeholder = "options: a,b,c (برای select/multiselect)";
  options.value = (prefill?.options || []).join(",");

  const delBtn = document.createElement("button");
  delBtn.type = "button";
  delBtn.className = "btn btn-sm btn-outline-danger";
  delBtn.textContent = "حذف";
  delBtn.onclick = ()=>{ tr.remove(); syncSchemaFromBuilder(); };

  function td(el){
    const td = document.createElement("td");
    td.appendChild(el);
    return td;
  }

  tr.appendChild(td(name));
  tr.appendChild(td(label));
  tr.appendChild(td(type));

  const tdReq = document.createElement("td");
  const div = document.createElement("div");
  div.className = "form-check";
  div.appendChild(required);
  tdReq.appendChild(div);
  tr.appendChild(tdReq);

  tr.appendChild(td(regex));
  tr.appendChild(td(options));

  const tdDel = document.createElement("td");
  tdDel.appendChild(delBtn);
  tr.appendChild(tdDel);

  [name,label,type,required,regex,options].forEach(el=>{
    el.addEventListener("change", syncSchemaFromBuilder);
    el.addEventListener("keyup", syncSchemaFromBuilder);
  });

  tbody.appendChild(tr);
  syncSchemaFromBuilder();
}

function syncSchemaFromBuilder(){
  const tbody = document.getElementById("fieldsBody");
  if(!tbody) return;
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const fields = rows.map(r=>{
    const els = r.querySelectorAll("input,select");
    const name = els[0].value.trim();
    const label = els[1].value.trim();
    const type = els[2].value;
    const required = els[3].checked;
    const regex = els[4].value.trim();
    const optionsRaw = els[5].value.trim();
    const options = optionsRaw ? optionsRaw.split(",").map(x=>x.trim()).filter(Boolean) : [];
    const f = {name, label, type, required};
    if(regex) f.regex = regex;
    if((type==="select" || type==="multiselect") && options.length) f.options = options;
    return f;
  }).filter(f=>f.name);

  const schema = {fields};

  // Optional layout builder (rows/columns)
  const layoutRows = document.getElementById("layoutRows");
  if(layoutRows){
    schema.layout = readLayoutFromDom();
    refreshLayoutUI(fields);
    renderLayoutPreview(schema);
  }

  const jsonText = JSON.stringify(schema, null, 2);

  const hidden = document.getElementById("schema_text");
  if(hidden) hidden.value = jsonText;

  const preview = document.getElementById("schema_text_preview");
  if(preview && document.activeElement !== preview){
    preview.value = jsonText;
  }
}

// ----------------------------
// Layout Builder (Rows/Columns) + Live Preview
// Schema format:
// {
//   fields: [...],
//   layout: [ {columns: 2, fields: ["year","status"]}, ... ]
// }
// Notes:
// - Order of fields in each row determines right/left placement (RTL).
// - Any field not placed in layout will still be shown under "فیلدهای بدون چیدمان" in preview and in real form.
// ----------------------------

function _uid(prefix="row"){
  return `${prefix}_${Date.now()}_${Math.floor(Math.random()*1e6)}`;
}

function _getFieldsFromBuilderTable(){
  const tbody = document.getElementById("fieldsBody");
  if(!tbody) return [];
  const rows = Array.from(tbody.querySelectorAll("tr"));
  return rows.map(r=>{
    const els = r.querySelectorAll("input,select");
    const name = (els[0]?.value || "").trim();
    const label = (els[1]?.value || "").trim();
    const type = els[2]?.value || "text";
    const required = !!els[3]?.checked;
    const regex = (els[4]?.value || "").trim();
    const optionsRaw = (els[5]?.value || "").trim();
    const options = optionsRaw ? optionsRaw.split(",").map(x=>x.trim()).filter(Boolean) : [];
    const f = {name, label, type, required};
    if(regex) f.regex = regex;
    if((type==="select" || type==="multiselect") && options.length) f.options = options;
    return f;
  }).filter(f=>f.name);
}

function _fieldTitle(f){
  return (f.label && f.label.trim()) ? f.label.trim() : f.name;
}

function _colClass(columns){
  if(columns === 1) return "col-12";
  if(columns === 3) return "col-12 col-md-4";
  return "col-12 col-md-6";
}

function initLayoutBuilderFromSchema(layout){
  const rowsEl = document.getElementById("layoutRows");
  if(!rowsEl) return;
  rowsEl.innerHTML = "";
  const fields = _getFieldsFromBuilderTable();
  refreshLayoutUI(fields);

  if(Array.isArray(layout) && layout.length){
    layout.forEach(r=>{
      const cols = parseInt(r?.columns, 10);
      const rf = Array.isArray(r?.fields) ? r.fields : [];
      addLayoutRow({columns: (cols>=1 && cols<=3) ? cols : 2, fields: rf});
    });
  }else{
    // default auto layout
    autoLayout(false);
  }
  syncSchemaFromBuilder();
}

function rebuildFieldPalette(fields){
  const pal = document.getElementById("fieldPalette");
  if(!pal) return;
  pal.innerHTML = "";
  fields.forEach(f=>{
    const chip = document.createElement("span");
    chip.className = "badge rounded-pill text-bg-primary field-chip";
    chip.textContent = _fieldTitle(f);
    chip.setAttribute("draggable","true");
    chip.dataset.field = f.name;
    chip.addEventListener("dragstart", (e)=>{
      e.dataTransfer.setData("text/plain", f.name);
      e.dataTransfer.effectAllowed = "copy";
    });
    pal.appendChild(chip);
  });
}

function _updateCellSelectOptions(selectEl, fields){
  if(!selectEl) return;
  const current = selectEl.value || "";
  selectEl.innerHTML = "";
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = "— خالی —";
  selectEl.appendChild(empty);
  fields.forEach(f=>{
    const opt = document.createElement("option");
    opt.value = f.name;
    opt.textContent = `${_fieldTitle(f)} (${f.name})`;
    selectEl.appendChild(opt);
  });
  selectEl.value = current;
  if(selectEl.value !== current){
    // if removed field, reset
    selectEl.value = "";
  }
}

function _mkLayoutRowElement(prefill){
  const id = _uid("layout");
  const rowWrap = document.createElement("div");
  rowWrap.className = "layout-row border rounded-4 p-2 bg-white";
  rowWrap.dataset.rowId = id;

  const header = document.createElement("div");
  header.className = "d-flex flex-wrap align-items-center justify-content-between gap-2";

  const left = document.createElement("div");
  left.className = "d-flex align-items-center gap-2";
  left.innerHTML = `<span class="text-muted small">ردیف</span>`;

  const colsSel = document.createElement("select");
  colsSel.className = "form-select form-select-sm";
  colsSel.style.width = "140px";
  colsSel.innerHTML = `
    <option value="1">۱ ستون</option>
    <option value="2">۲ ستون</option>
    <option value="3">۳ ستون</option>
  `;
  colsSel.value = String(prefill?.columns || 2);
  colsSel.addEventListener("change", ()=>{
    const cols = parseInt(colsSel.value,10) || 2;
    _renderRowCells(rowWrap, cols);
    syncSchemaFromBuilder();
  });

  left.appendChild(colsSel);
  header.appendChild(left);

  const actions = document.createElement("div");
  actions.className = "d-flex gap-2";
  actions.innerHTML = `
    <button type="button" class="btn btn-sm btn-outline-secondary" title="بالا" data-act="up"><i class="bi bi-arrow-up"></i></button>
    <button type="button" class="btn btn-sm btn-outline-secondary" title="پایین" data-act="down"><i class="bi bi-arrow-down"></i></button>
    <button type="button" class="btn btn-sm btn-outline-danger" title="حذف" data-act="del"><i class="bi bi-trash"></i></button>
  `;
  actions.querySelector('[data-act="up"]').addEventListener("click", ()=>moveLayoutRow(rowWrap, -1));
  actions.querySelector('[data-act="down"]').addEventListener("click", ()=>moveLayoutRow(rowWrap, +1));
  actions.querySelector('[data-act="del"]').addEventListener("click", ()=>{ rowWrap.remove(); syncSchemaFromBuilder(); });
  header.appendChild(actions);
  rowWrap.appendChild(header);

  const cells = document.createElement("div");
  cells.className = "row g-2 mt-2";
  cells.dataset.cells = "true";
  rowWrap.appendChild(cells);

  // initial render
  _renderRowCells(rowWrap, parseInt(colsSel.value,10) || 2, prefill?.fields || []);
  return rowWrap;
}

function _renderRowCells(rowWrap, columns, selectedFields=[]){
  const cellsWrap = rowWrap.querySelector('[data-cells="true"]');
  if(!cellsWrap) return;
  const prev = Array.from(cellsWrap.querySelectorAll('select[data-cell="true"]')).map(s=>s.value);
  const keep = (selectedFields && selectedFields.length) ? selectedFields : prev;
  cellsWrap.innerHTML = "";

  const fields = _getFieldsFromBuilderTable();
  for(let i=0;i<columns;i++){
    const col = document.createElement("div");
    col.className = _colClass(columns);

    const box = document.createElement("div");
    box.className = "layout-drop border rounded-4 p-2 bg-body-tertiary";
    box.dataset.drop = "true";

    const label = document.createElement("div");
    label.className = "small text-muted mb-1";
    const pos = (columns===1) ? "تمام عرض" : (i===0 ? "ستون ۱ (راست)" : (i===1 ? (columns===2 ? "ستون ۲ (چپ)" : "ستون ۲ (وسط)") : "ستون ۳ (چپ)"));
    label.textContent = pos;
    box.appendChild(label);

    const sel = document.createElement("select");
    sel.className = "form-select form-select-sm";
    sel.dataset.cell = "true";
    _updateCellSelectOptions(sel, fields);
    sel.value = keep[i] || "";
    sel.addEventListener("change", syncSchemaFromBuilder);
    box.appendChild(sel);

    // Drag & drop support
    box.addEventListener("dragover", (e)=>{ e.preventDefault(); box.classList.add("dragover"); });
    box.addEventListener("dragleave", ()=>box.classList.remove("dragover"));
    box.addEventListener("drop", (e)=>{
      e.preventDefault();
      box.classList.remove("dragover");
      const fname = e.dataTransfer.getData("text/plain");
      if(fname){
        sel.value = fname;
        syncSchemaFromBuilder();
      }
    });

    col.appendChild(box);
    cellsWrap.appendChild(col);
  }
}

function addLayoutRow(prefill=null){
  const rowsEl = document.getElementById("layoutRows");
  if(!rowsEl) return;
  const rowEl = _mkLayoutRowElement(prefill || {columns: 2, fields: []});
  rowsEl.appendChild(rowEl);
  syncSchemaFromBuilder();
}

function moveLayoutRow(rowEl, delta){
  const rowsEl = document.getElementById("layoutRows");
  if(!rowsEl || !rowEl) return;
  const kids = Array.from(rowsEl.children);
  const idx = kids.indexOf(rowEl);
  if(idx < 0) return;
  const nidx = idx + delta;
  if(nidx < 0 || nidx >= kids.length) return;
  if(delta < 0){
    rowsEl.insertBefore(rowEl, kids[nidx]);
  }else{
    rowsEl.insertBefore(rowEl, kids[nidx].nextSibling);
  }
  syncSchemaFromBuilder();
}

function autoLayout(reset=true){
  const rowsEl = document.getElementById("layoutRows");
  if(!rowsEl) return;
  if(reset) rowsEl.innerHTML = "";
  const fields = _getFieldsFromBuilderTable();
  if(!fields.length){
    if(reset) addLayoutRow({columns: 1, fields: []});
    return;
  }
  const cols = 2;
  for(let i=0;i<fields.length;i+=cols){
    const slice = fields.slice(i, i+cols).map(f=>f.name);
    addLayoutRow({columns: cols, fields: slice});
  }
  syncSchemaFromBuilder();
}

function readLayoutFromDom(){
  const rowsEl = document.getElementById("layoutRows");
  if(!rowsEl) return [];
  const rows = Array.from(rowsEl.querySelectorAll('.layout-row'));
  return rows.map(r=>{
    const colsSel = r.querySelector('select.form-select');
    const columns = Math.min(3, Math.max(1, parseInt(colsSel?.value, 10) || 2));
    const cells = Array.from(r.querySelectorAll('select[data-cell="true"]')).slice(0, columns);
    const fields = cells.map(s=>s.value || "");
    return {columns, fields};
  });
}

function refreshLayoutUI(fields){
  rebuildFieldPalette(fields);

  // refresh each cell's options to match current fields
  const rowsEl = document.getElementById("layoutRows");
  if(rowsEl){
    rowsEl.querySelectorAll('select[data-cell="true"]').forEach(sel=>_updateCellSelectOptions(sel, fields));
  }

  // warnings: unplaced + duplicates
  const warningsEl = document.getElementById("layoutWarnings");
  if(!warningsEl) return;

  const layout = readLayoutFromDom();
  const placed = [];
  layout.forEach(r=> (r.fields || []).forEach(f=>{ if(f) placed.push(f); }));
  const placedSet = new Set(placed);
  const dup = placed.filter((x, i)=>placed.indexOf(x)!==i);
  const unplaced = fields.filter(f=>!placedSet.has(f.name));

  let html = "";
  if(dup.length){
    html += `<div class="alert alert-warning py-2 mb-2"><b>هشدار:</b> برخی فیلدها چندبار در چیدمان استفاده شده‌اند: <code>${Array.from(new Set(dup)).join(', ')}</code></div>`;
  }
  if(unplaced.length){
    html += `<div class="alert alert-info py-2 mb-0"><b>توجه:</b> این فیلدها هنوز در چیدمان انتخاب نشده‌اند و در انتهای فرم به صورت سطری (یک‌ستونه) اضافه می‌شوند: <code>${unplaced.map(f=>f.name).join(', ')}</code></div>`;
  }
  warningsEl.innerHTML = html;
}

function _previewInputHtml(f){
  const label = _fieldTitle(f);
  const req = f.required ? '<span class="text-danger">*</span>' : '';
  const t = (f.type || "text").toLowerCase();

  let input = '';
  if(t === 'textarea'){
    input = `<textarea class="form-control" rows="3" disabled placeholder="${label}"></textarea>`;
  }else if(t === 'number'){
    input = `<input class="form-control ltr" type="number" disabled placeholder="${label}">`;
  }else if(t === 'date'){
    input = `<input class="form-control ltr" type="date" disabled>`;
  }else if(t === 'select' || t === 'multiselect'){
    const opts = (f.options || []).slice(0,5).map(o=>`<option>${o}</option>`).join('');
    const mult = (t === 'multiselect') ? 'multiple' : '';
    input = `<select class="form-select" ${mult} disabled><option>-- انتخاب --</option>${opts}</select>`;
  }else if(t === 'file'){
    input = `<input class="form-control" type="file" disabled>`;
  }else{
    input = `<input class="form-control" type="text" disabled placeholder="${label}">`;
  }
  return `
    <label class="form-label">${label} ${req}</label>
    ${input}
  `;
}

function renderLayoutPreview(schema){
  const previewEl = document.getElementById("layoutPreview");
  if(!previewEl) return;
  const fields = (schema?.fields || []);
  const fieldMap = {};
  fields.forEach(f=>{ fieldMap[f.name] = f; });

  const layout = Array.isArray(schema?.layout) ? schema.layout : readLayoutFromDom();

  // gather placed
  const placed = new Set();
  (layout || []).forEach(r=> (r.fields || []).forEach(n=>{ if(n) placed.add(n); }));
  const unplaced = fields.filter(f=>!placed.has(f.name));

  let html = '';
  (layout || []).forEach(r=>{
    const cols = Math.min(3, Math.max(1, parseInt(r.columns,10) || 2));
    const names = Array.isArray(r.fields) ? r.fields.slice(0, cols) : [];
    html += `<div class="row g-3 mb-2">`;
    for(let i=0;i<cols;i++){
      const name = names[i] || '';
      const f = fieldMap[name];
      html += `<div class="${_colClass(cols)}">`;
      html += `<div class="p-2">${f ? _previewInputHtml(f) : '<div class="text-muted small">(خانه خالی)</div>'}</div>`;
      html += `</div>`;
    }
    html += `</div>`;
  });

  if(unplaced.length){
    html += `<hr class="my-3">`;
    html += `<div class="text-muted small mb-2">فیلدهای انتخاب‌نشده (به صورت یک‌ستونه در انتهای فرم)</div>`;
    unplaced.forEach((f)=>{
      html += `<div class="row g-3 mb-2">`;
      html += `<div class="col-12"><div class="p-2">${_previewInputHtml(f)}</div></div>`;
      html += `</div>`;
    });
  }

  if(!html){
    html = '<div class="text-muted">هنوز هیچ فیلدی اضافه نشده است.</div>';
  }
  previewEl.innerHTML = html;
}

// If preview edited manually, it overrides hidden value on submit
document.addEventListener("submit", function(e){
  const preview = document.getElementById("schema_text_preview");
  const hidden = document.getElementById("schema_text");
  if(preview && hidden){
    hidden.value = preview.value || "{}";
  }
});

document.addEventListener("DOMContentLoaded", ()=>{
  const tbody = document.getElementById("fieldsBody");
  if(tbody && tbody.children.length === 0){
    addFieldRow({name:"year", label:"سال", type:"number", required:true});
    addFieldRow({name:"status", label:"وضعیت", type:"select", required:true, options:["A","B","C"]});
  }

  // If layout builder exists on this page, initialize a default layout once
  const layoutRows = document.getElementById("layoutRows");
  if(layoutRows && layoutRows.children.length === 0){
    // Use schema_text_preview (if any) as source
    const preview = document.getElementById("schema_text_preview");
    let obj = null;
    try{ obj = JSON.parse(preview?.value || "{}"); }catch(e){ obj = null; }
    if(typeof initLayoutBuilderFromSchema === "function"){
      initLayoutBuilderFromSchema(obj && obj.layout ? obj.layout : null);
    }
  }

  // Enhance table header if exists in forms/index
  const thead = document.querySelector("#formBuilder table thead tr");
  if(thead && thead.children.length < 7){
    thead.innerHTML = `
      <th>کلید (English)</th>
      <th>برچسب</th>
      <th>نوع</th>
      <th>الزامی</th>
      <th>regex</th>
      <th>options</th>
      <th></th>
    `;
  }
});


// ----------------------------
// Global UI helpers (Toast)
// ----------------------------
function showToast(message, variant="success"){
  try{
    const container = document.getElementById("toastContainer");
    if(!container){ return; }

    const toastEl = document.createElement("div");
    toastEl.className = `toast align-items-center text-bg-${variant} border-0`;
    toastEl.setAttribute("role","alert");
    toastEl.setAttribute("aria-live","assertive");
    toastEl.setAttribute("aria-atomic","true");

    toastEl.innerHTML = `
      <div class="d-flex">
        <div class="toast-body">${message}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    `;
    container.appendChild(toastEl);
    const t = new bootstrap.Toast(toastEl, {delay: 2500});
    t.show();
    toastEl.addEventListener("hidden.bs.toast", ()=>{ toastEl.remove(); });
  }catch(e){
    // fallback
    console.log(message);
  }
}

// ----------------------------
// Global connectivity/session handling
// ----------------------------
let disconnectModal = null;
let disconnectState = "";

function currentRelativeUrl(){
  const path = window.location.pathname || "/";
  const query = window.location.search || "";
  return `${path}${query}`;
}

function buildLoginUrl(nextUrl){
  const n = nextUrl || currentRelativeUrl();
  return `/login?redirect_url=${encodeURIComponent(n)}`;
}

function ensureDisconnectModal(){
  const modalEl = document.getElementById("disconnectModal");
  if(!modalEl || typeof bootstrap === "undefined") return null;
  if(!disconnectModal){
    disconnectModal = new bootstrap.Modal(modalEl, {backdrop: "static", keyboard: false});
  }
  return disconnectModal;
}

function showDisconnectModal({reason, message, loginUrl="", allowLogin=false, allowRetry=true}){
  const modalEl = document.getElementById("disconnectModal");
  if(!modalEl){
    showToast(message || "ارتباط با سامانه قطع شد.", "danger");
    return;
  }

  if(disconnectState === reason) return;
  disconnectState = reason || "disconnected";

  const textEl = document.getElementById("disconnectModalText");
  if(textEl) textEl.textContent = message || "ارتباط با سامانه قطع شده است.";

  const loginBtn = document.getElementById("disconnectLoginBtn");
  if(loginBtn){
    loginBtn.href = loginUrl || buildLoginUrl(currentRelativeUrl());
    loginBtn.classList.toggle("d-none", !allowLogin);
  }

  const retryBtn = document.getElementById("disconnectRetryBtn");
  if(retryBtn){
    retryBtn.classList.toggle("d-none", !allowRetry);
    retryBtn.onclick = ()=>window.location.reload();
  }

  const m = ensureDisconnectModal();
  if(m) m.show();
}

function handleSessionExpired(loginUrl){
  const target = loginUrl || buildLoginUrl(currentRelativeUrl());
  showToast("نشست شما منقضی شده و ارتباط کاربر قطع شده است. دوباره وارد شوید.", "warning");
  showDisconnectModal({
    reason: "session_expired",
    message: "نشست شما منقضی شده است. برای ادامه، دوباره وارد شوید.",
    loginUrl: target,
    allowLogin: true,
    allowRetry: false,
  });
}

function handleConnectionLost(){
  showToast("ارتباط با سرور قطع شده است.", "danger");
  showDisconnectModal({
    reason: "connection_lost",
    message: "اتصال شما به سرور قطع شده است. پس از برقراری ارتباط، دوباره تلاش کنید.",
    allowLogin: false,
    allowRetry: true,
  });
}

function getXhrHeader(xhr, name){
  try{
    return xhr?.getResponseHeader?.(name) || "";
  }catch(e){
    return "";
  }
}

document.body.addEventListener("htmx:responseError", (e)=>{
  const xhr = e?.detail?.xhr;
  const status = Number(xhr?.status || 0);
  const sessionHeader = getXhrHeader(xhr, "X-Session-Expired");
  if(status === 401 || sessionHeader === "1"){
    const loginUrl = buildLoginUrl(currentRelativeUrl());
    handleSessionExpired(loginUrl);
    return;
  }
  showToast("خطا در ارتباط با سرور", "danger");
});

document.body.addEventListener("htmx:sendError", ()=>{
  handleConnectionLost();
});

window.addEventListener("offline", ()=>{
  handleConnectionLost();
});

(function setupFetchSessionGuard(){
  if(typeof window.fetch !== "function") return;
  const originalFetch = window.fetch.bind(window);
  window.fetch = async function(input, init={}){
    const req = Object.assign({}, init || {});
    const rawUrl = (typeof input === "string") ? input : (input?.url || "");
    let isSameOrigin = true;
    try{
      const u = new URL(rawUrl, window.location.origin);
      isSameOrigin = (u.origin === window.location.origin);
    }catch(e){
      isSameOrigin = true;
    }

    const headers = new Headers(req.headers || {});
    if(isSameOrigin && !headers.has("X-Requested-With")){
      headers.set("X-Requested-With", "fetch");
    }
    req.headers = headers;
    if(isSameOrigin && !req.credentials){
      req.credentials = "same-origin";
    }

    let response;
    try{
      response = await originalFetch(input, req);
    }catch(err){
      handleConnectionLost();
      throw err;
    }

    const sessionHeader = response.headers.get("X-Session-Expired");
    if(response.status === 401 || sessionHeader === "1"){
      handleSessionExpired(buildLoginUrl(currentRelativeUrl()));
    }

    return response;
  };
})();

// ----------------------------
// Real-time session monitor (WebSocket + health endpoints)
// ----------------------------
let sessionWs = null;
let wsReconnectTimer = null;
let authHealthTimer = null;
let wsBackoffMs = 2000;
let pageUnloading = false;

function isAuthenticatedPage(){
  const authed = !!window.__IS_AUTHENTICATED__;
  const path = window.location.pathname || "";
  return authed && !path.startsWith("/login");
}

function getSessionWsUrl(){
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/session`;
}

function connectSessionSocket(){
  if(!isAuthenticatedPage()) return;
  if(disconnectState === "session_expired") return;
  if(sessionWs && (sessionWs.readyState === WebSocket.OPEN || sessionWs.readyState === WebSocket.CONNECTING)) return;

  try{
    sessionWs = new WebSocket(getSessionWsUrl());
  }catch(e){
    handleConnectionLost();
    return;
  }

  sessionWs.onopen = ()=>{
    wsBackoffMs = 2000;
  };

  sessionWs.onmessage = (event)=>{
    let data = null;
    try{
      data = JSON.parse(event.data || "{}");
    }catch(e){
      return;
    }
    if(data && data.type === "error" && (data.reason === "session_expired" || data.reason === "unauthorized")){
      handleSessionExpired(buildLoginUrl(currentRelativeUrl()));
      try{ sessionWs.close(); }catch(e){}
    }
  };

  sessionWs.onclose = (event)=>{
    sessionWs = null;
    if(pageUnloading) return;
    if(!isAuthenticatedPage()) return;
    if(disconnectState === "session_expired") return;
    if(event.code === 4401){
      handleSessionExpired(buildLoginUrl(currentRelativeUrl()));
      return;
    }
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(connectSessionSocket, wsBackoffMs);
    wsBackoffMs = Math.min(Math.floor(wsBackoffMs * 1.5), 20000);
  };

  sessionWs.onerror = ()=>{
    // onclose handles reconnect/backoff.
  };
}

async function pollHealthEndpoints(){
  if(!isAuthenticatedPage()) return;
  if(disconnectState === "session_expired") return;

  try{
    const healthRes = await fetch(`/health?_=${Date.now()}`, {cache: "no-store"});
    if(!healthRes.ok){
      handleConnectionLost();
      return;
    }
  }catch(e){
    handleConnectionLost();
    return;
  }

  // fetch wrapper handles 401 from /health/auth and triggers session-expired modal.
  try{
    await fetch(`/health/auth?_=${Date.now()}`, {cache: "no-store"});
  }catch(e){
    // fetch wrapper already shows connection state.
  }
}

function startRealtimeSessionMonitor(){
  if(!isAuthenticatedPage()) return;
  connectSessionSocket();
  if(!authHealthTimer){
    authHealthTimer = setInterval(pollHealthEndpoints, 10000);
  }
  setTimeout(pollHealthEndpoints, 1800);
}

window.addEventListener("beforeunload", ()=>{
  pageUnloading = true;
  clearTimeout(wsReconnectTimer);
  if(authHealthTimer){
    clearInterval(authHealthTimer);
    authHealthTimer = null;
  }
  if(sessionWs){
    try{ sessionWs.close(1000, "page_unload"); }catch(e){}
  }
});

document.addEventListener("DOMContentLoaded", ()=>{
  startRealtimeSessionMonitor();
});

// Global loading overlay for HTMX requests
document.body.addEventListener("htmx:beforeRequest", ()=>{
  const el = document.getElementById("globalLoading");
  if(el) el.classList.add("show");
});
document.body.addEventListener("htmx:afterRequest", ()=>{
  const el = document.getElementById("globalLoading");
  if(el) el.classList.remove("show");
});
document.body.addEventListener("htmx:responseError", ()=>{
  const el = document.getElementById("globalLoading");
  if(el) el.classList.remove("show");
});


// ----------------------------
// Table Pagination (Client-side)
// Usage: add data-paginate="true" to a table (usually list pages).
// Default page size is 5 (can override with data-page-size).
// ----------------------------

function _num(x){
  const n = parseInt(x, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function _mkBtn(label, onClick, disabled=false){
  const b = document.createElement("button");
  b.type = "button";
  b.className = "btn btn-sm btn-outline-secondary";
  b.textContent = label;
  b.disabled = !!disabled;
  b.addEventListener("click", onClick);
  return b;
}

function paginateTable(table){
  if(!table) return;
  if(table.dataset.paginate !== "true") return;
  // Do not paginate if table has no tbody
  const tbody = table.tBodies && table.tBodies[0];
  if(!tbody) return;

  // Clean previous pager (if re-initializing)
  const prevPager = table._pagerEl;
  if(prevPager && prevPager.parentElement){
    prevPager.parentElement.removeChild(prevPager);
  }

  const allRows = Array.from(tbody.rows);
  const defaultSize = _num(table.dataset.pageSize) || 5;
  let pageSize = defaultSize;
  let page = _num(table.dataset.page) || 1;

  function totalPages(){
    return Math.max(1, Math.ceil(allRows.length / pageSize));
  }

  function render(){
    const tp = totalPages();
    if(page > tp) page = tp;
    if(page < 1) page = 1;
    table.dataset.page = String(page);
    table.dataset.pageSize = String(pageSize);

    const start = (page - 1) * pageSize;
    const end = start + pageSize;

    allRows.forEach((r, idx)=>{
      r.style.display = (idx >= start && idx < end) ? "" : "none";
    });

    // Update labels/buttons
    info.textContent = `صفحه ${page} از ${tp} — ${allRows.length} سطر`;
    prevBtn.disabled = (page <= 1);
    nextBtn.disabled = (page >= tp);
  }

  // Build pager UI
  const pager = document.createElement("div");
  pager.className = "table-pager d-flex flex-wrap align-items-center gap-2 mt-2";

  const info = document.createElement("div");
  info.className = "small text-muted";

  const prevBtn = _mkBtn("قبلی", ()=>{ page -= 1; render(); });
  const nextBtn = _mkBtn("بعدی", ()=>{ page += 1; render(); });

  const sizeWrap = document.createElement("div");
  sizeWrap.className = "d-flex align-items-center gap-2";
  const sizeLbl = document.createElement("span");
  sizeLbl.className = "small text-muted";
  sizeLbl.textContent = "سطر در صفحه:";
  const sizeSel = document.createElement("select");
  sizeSel.className = "form-select form-select-sm";
  sizeSel.style.width = "auto";
  [5,10,20,50].forEach(n=>{
    const o = document.createElement("option");
    o.value = String(n);
    o.textContent = String(n);
    if(n === pageSize) o.selected = true;
    sizeSel.appendChild(o);
  });
  sizeSel.addEventListener("change", ()=>{
    pageSize = _num(sizeSel.value) || 5;
    page = 1;
    render();
  });
  sizeWrap.appendChild(sizeLbl);
  sizeWrap.appendChild(sizeSel);

  pager.appendChild(info);
  pager.appendChild(prevBtn);
  pager.appendChild(nextBtn);
  pager.appendChild(sizeWrap);

  // Insert after table
  table.parentElement?.appendChild(pager);
  table._pagerEl = pager;

  render();
}

function initPaginatedTables(root=document){
  const tables = Array.from((root || document).querySelectorAll("table[data-paginate='true']"));
  tables.forEach(paginateTable);
}

document.addEventListener("DOMContentLoaded", ()=>{
  initPaginatedTables(document);
});

// Re-init after HTMX swaps
document.body.addEventListener("htmx:afterSwap", (e)=>{
  initPaginatedTables(e.target || document);
});
