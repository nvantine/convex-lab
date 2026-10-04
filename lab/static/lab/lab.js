/* Plain DOM operations: one declaration editor and small local chart helpers. */
"use strict";

for (const element of document.querySelectorAll(".math[data-math]")) {
  try {
    katex.render(element.textContent, element, {displayMode: true, trust: false, throwOnError: true});
  } catch (error) {
    element.classList.add("math-error");
    element.textContent = `Math rendering failed: ${error.message}`;
  }
}

const problemForm = document.querySelector("#problem-form");
if (problemForm) {
  const state = {variables: [], parameters: []};
  let sequence = 0;
  const rawErrors = new Set();
  const fields = {
    variables: ["name", "shape", "domain", "meaning", "units"],
    parameters: ["name", "value", "domain", "meaning", "units"]
  };
  const labels = {name: "Name", shape: "Shape (JSON)", domain: "Domain", meaning: "Meaning", units: "Units", value: "Value (JSON)"};
  const sources = {};
  const serialize = () => {
    for (const kind of Object.keys(state)) sources[kind].value = JSON.stringify(state[kind], null, 2);
  };
  const showError = (text) => {
    const note = document.querySelector("#declaration-error") || document.createElement("p");
    note.id = "declaration-error";
    note.className = "notice";
    note.setAttribute("role", "alert");
    note.textContent = text;
    problemForm.prepend(note);
  };
  const readRows = () => {
    const next = {variables: [], parameters: []};
    for (const kind of Object.keys(next)) {
      for (const row of document.querySelectorAll(`#${kind}-editor .declaration`)) {
        const value = {};
        for (const field of fields[kind]) {
          const input = row.querySelector(`[data-field="${field}"]`);
          value[field] = ["shape", "value"].includes(field) ? JSON.parse(input.value) : input.value;
        }
        next[kind].push(value);
      }
    }
    Object.assign(state, next);
    serialize();
    document.querySelector("#declaration-error")?.remove();
  };
  const render = () => {
    for (const kind of Object.keys(state)) {
      const container = document.querySelector(`#${kind}-editor`);
      container.replaceChildren();
      state[kind].forEach((declaration, index) => {
        const row = document.createElement("div");
        row.className = "declaration";
        const inputs = document.createElement("div");
        inputs.className = "declaration-fields";
        row.append(inputs);
        for (const field of fields[kind]) {
          const wrapper = document.createElement("div");
          const label = document.createElement("label");
          const id = `declaration-${++sequence}`;
          label.htmlFor = id;
          label.textContent = labels[field];
          let input;
          if (field === "domain") {
            input = document.createElement("select");
            for (const domain of ["free", "nonneg", "nonpos", "symmetric", "PSD"]) {
              const option = document.createElement("option");
              option.value = option.textContent = domain;
              input.append(option);
            }
          } else {
            input = document.createElement(field === "value" ? "textarea" : "input");
            if (field === "value") input.rows = 3;
          }
          input.id = id;
          input.dataset.field = field;
          input.value = ["shape", "value"].includes(field) ? JSON.stringify(declaration[field]) : (declaration[field] || (field === "domain" ? "free" : ""));
          wrapper.append(label, input);
          inputs.append(wrapper);
        }
        const actions = document.createElement("div");
        actions.className = "actions";
        for (const action of ["Remove", kind === "parameters" ? "Make variable" : "Make parameter"]) {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = action;
          button.addEventListener("click", () => {
            try {
              readRows();
              const item = state[kind].splice(index, 1)[0];
              if (action === "Make variable") {
                const shape = Array.isArray(item.value) ? [item.value.length] : [];
                if (shape.length && Array.isArray(item.value[0])) shape.push(item.value[0].length);
                delete item.value;
                item.shape = shape;
                state.variables.push(item);
              } else if (action === "Make parameter") {
                if (!Array.isArray(item.shape) || item.shape.length > 2 || item.shape.some(n => !Number.isInteger(n) || n < 1) || item.shape.reduce((a,b) => a*b, 1) > 100000) {
                  state[kind].splice(index, 0, item);
                  throw new Error("Use a valid, reasonably sized shape before converting to a parameter.");
                }
                item.value = item.shape.length === 0 ? 0 : Array.from({length: item.shape[0]}, () => item.shape.length === 1 ? 0 : Array(item.shape[1]).fill(0));
                delete item.shape;
                state.parameters.push(item);
              }
              serialize();
              render();
            } catch (error) { showError(`Check declaration JSON: ${error.message}`); }
          });
          actions.append(button);
        }
        row.append(actions);
        container.append(row);
      });
    }
  };
  let ready = true;
  for (const kind of Object.keys(state)) {
    sources[kind] = document.querySelector(`#id_${kind}`);
    try {
      state[kind] = JSON.parse(sources[kind].value || "[]");
      if (!Array.isArray(state[kind]) || state[kind].some(row => !row || typeof row !== "object" || Array.isArray(row))) throw new Error("Declarations must be a list of objects.");
    } catch (error) { ready = false; showError(`Fix the ${kind} JSON and resubmit: ${error.message}`); }
  }
  if (ready) {
    render();
    for (const source of Object.values(sources)) {
      source.closest("details").open = false;
      source.addEventListener("change", () => {
        try {
          const value = JSON.parse(source.value || "[]");
          if (!Array.isArray(value) || value.some(row => !row || typeof row !== "object" || Array.isArray(row))) throw new Error("Use a list of declaration objects.");
          state[source.id.slice(3)] = value;
          rawErrors.delete(source.id);
          document.querySelector("#declaration-error")?.remove();
          render();
        } catch (error) { rawErrors.add(source.id); showError(error.message); }
      });
    }
    for (const button of document.querySelectorAll(".add-declaration")) {
      button.hidden = false;
      button.addEventListener("click", () => {
        try {
          readRows();
          const kind = button.dataset.kind;
          state[kind].push({name: "", [kind === "variables" ? "shape" : "value"]: kind === "variables" ? [] : 0, domain: "free", meaning: "", units: ""});
          serialize();
          render();
        } catch (error) { showError(`Check declaration JSON: ${error.message}`); }
      });
    }
    problemForm.addEventListener("submit", event => {
      try {
        if (rawErrors.size) throw new Error("Fix the declaration JSON before submitting.");
        readRows();
      } catch (error) {
        event.preventDefault();
        showError(`Check declaration JSON: ${error.message}`);
      }
    });
  }
}

for (const chart of document.querySelectorAll("[data-chart]")) {
  const figure = JSON.parse(document.getElementById(chart.dataset.chart).textContent);
  Plotly.newPlot(chart, figure.data, figure.layout, {responsive: true, displaylogo: false});
}
const dialog = document.querySelector("#chart-dialog");
for (const button of document.querySelectorAll(".expand-chart")) {
  button.addEventListener("click", () => {
    const chart = document.getElementById(button.dataset.target);
    const figure = JSON.parse(document.getElementById(chart.dataset.chart).textContent);
    dialog.showModal();
    Plotly.newPlot("expanded-chart", figure.data, {...figure.layout, height: undefined, autosize: true}, {responsive: true, displaylogo: false});
  });
}
document.querySelector("#close-chart")?.addEventListener("click", () => {
  dialog.close();
  if (window.Plotly) Plotly.purge("expanded-chart");
});
