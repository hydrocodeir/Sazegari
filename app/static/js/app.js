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
  const jsonText = JSON.stringify(schema, null, 2);

  const hidden = document.getElementById("schema_text");
  if(hidden) hidden.value = jsonText;

  const preview = document.getElementById("schema_text_preview");
  if(preview && document.activeElement !== preview){
    preview.value = jsonText;
  }
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

// show HTMX errors as toast
document.body.addEventListener("htmx:responseError", (e)=>{
  showToast("خطا در ارتباط با سرور", "danger");
});
document.body.addEventListener("htmx:sendError", (e)=>{
  showToast("ارسال درخواست ناموفق بود", "danger");
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
