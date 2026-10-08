// Small DOM helpers shared by every page.

export function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "style") Object.assign(node.style, value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function tile(label, value, unit = "", sub = "", color = "") {
  return el("div", { class: "tile", style: color ? { "--tile-color": `var(${color})` } : {} },
    el("div", { class: "label" }, label),
    el("div", {}, el("span", { class: "value" }, value), unit ? el("span", { class: "unit" }, unit) : null),
    sub ? el("div", { class: "sub" }, sub) : null);
}

export function fillTable(table, headers, rows) {
  table.replaceChildren(
    el("thead", {}, el("tr", {}, headers.map((h) => el("th", {}, h)))),
    el("tbody", {}, rows.map((cells) => el("tr", {}, cells.map((c) => (c instanceof Node && c.tagName === "TD" ? c : el("td", {}, c)))))),
  );
}

export function notify(message, kind = "ok") {
  const box = document.getElementById("notice");
  box.textContent = message;
  box.className = `notice ${kind}`;
  box.hidden = false;
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => { box.hidden = true; }, 8000);
}

export async function guarded(button, action) {
  button.disabled = true;
  try {
    await action();
  } catch (error) {
    notify(error.message, "error");
  } finally {
    button.disabled = false;
  }
}
