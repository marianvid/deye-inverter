import { api } from "./api.js";
import { el, guarded, notify } from "./dom.js";

const form = document.getElementById("todo-form");
const input = document.getElementById("todo-text");

function editor(item, row) {
  const field = el("input", { type: "text", class: "todo-input", maxlength: 500, value: item.text });
  const save = () => change(item.id, { text: field.value });
  field.addEventListener("keydown", (event) => {
    if (event.key === "Enter") save();
    if (event.key === "Escape") render(lastItems);
  });
  row.replaceChildren(field, el("button", { type: "button", onclick: save }, "Save"));
  field.focus();
}

function itemRow(item) {
  const row = el("li", { class: item.done ? "todo-item done" : "todo-item" });
  const box = el("input", { type: "checkbox", checked: item.done, "aria-label": "Done",
    onchange: () => change(item.id, { done: box.checked }) });
  const dates = item.done ? `added ${item.added}, done ${item.done_on}` : `added ${item.added}`;
  row.append(
    box,
    el("span", { class: "todo-text" }, item.text),
    el("span", { class: "muted todo-dates" }, dates),
    el("button", { type: "button", class: "link-button", onclick: () => editor(item, row) }, "Edit"),
    el("button", { type: "button", class: "link-button", onclick: () => remove(item.id) }, "Delete"),
  );
  return row;
}

let lastItems = [];

function render(items) {
  lastItems = items;
  const open = items.filter((i) => !i.done);
  const done = items.filter((i) => i.done);
  document.getElementById("todo-open").replaceChildren(
    ...(open.length ? open.map(itemRow) : [el("li", { class: "muted" }, "Nothing left to do.")]));
  document.getElementById("todo-done").replaceChildren(...done.map(itemRow));
  document.getElementById("todo-done-box").hidden = !done.length;
  document.getElementById("todo-done-summary").textContent = `Done (${done.length})`;
}

async function change(id, body) {
  try {
    render(await api.post(`/api/todo/${id}`, body));
  } catch (error) {
    notify(error.message, "error");
  }
}

async function remove(id) {
  try {
    render(await api.delete(`/api/todo/${id}`));
  } catch (error) {
    notify(error.message, "error");
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  guarded(form.querySelector("button"), async () => {
    render(await api.post("/api/todo", { text: input.value }));
    input.value = "";
  });
});

api.get("/api/todo").then(render).catch((error) => notify(error.message, "error"));
