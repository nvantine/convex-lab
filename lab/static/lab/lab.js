/* Plain DOM operations: one declaration editor and small local chart helpers. */
"use strict";

for (const element of document.querySelectorAll(".math[data-math]")) {
  try {
    katex.render(element.textContent, element, {displayMode: true, trust: false, throwOnError: true});
    if (element.scrollWidth > element.clientWidth + 1) {
      const hint = document.createElement('small');
      hint.className = 'math-scroll-hint';
      hint.textContent = 'Scroll horizontally to read the whole equation.';
      element.after(hint);
    }
  } catch (error) {
    element.classList.add("math-error");
    element.textContent = `Math rendering failed: ${error.message}`;
  }
}

function equationEditor(input) {
  if (document.querySelector('#id_source_language')?.value !== 'latex' || input.dataset.enhanced) return;
  input.dataset.enhanced = 'true';
  const rendered = document.createElement('button');
  rendered.type = 'button';
  rendered.className = 'equation-render';
  rendered.setAttribute('aria-label', `Edit ${input.id === 'id_constraints' ? 'constraints' : 'equation'} LaTeX`);
  const hint = document.createElement('small');
  hint.textContent = 'Click the equation to edit LaTeX.';
  input.after(rendered, hint);
  const display = () => {
    rendered.replaceChildren();
    try {
      for (const source of input.value.split('\n').filter(s => s.trim())) {
        const line = document.createElement('div');
        katex.render(source, line, {displayMode: true, trust: false, throwOnError: true});
        rendered.append(line);
      }
      if (!rendered.childNodes.length) rendered.textContent = 'Click to enter an equation';
      input.hidden = true;
      rendered.hidden = false;
      hint.hidden = false;
    } catch (error) {
      input.hidden = false;
      rendered.hidden = true;
      hint.hidden = false;
      hint.textContent = `Typesetting preview: ${error.message}`;
    }
  };
  rendered.addEventListener('click', () => {
    rendered.hidden = true;
    input.hidden = false;
    hint.textContent = 'Edit the source, then click outside to render. Check math & DCP validates meaning.';
    input.focus();
  });
  input.addEventListener('blur', display);
  input.addEventListener('input', () => {
    // Keep focus while typing; show the live preview underneath the source.
    try {
      rendered.replaceChildren();
      for (const source of input.value.split('\n').filter(s => s.trim())) {
        const line = document.createElement('div');
        katex.render(source, line, {displayMode: true, trust: false, throwOnError: true});
        rendered.append(line);
      }
      rendered.hidden = false;
      hint.textContent = 'Live typesetting preview; Check math & DCP validates meaning.';
    } catch (error) { rendered.hidden = true; hint.textContent = `Typesetting preview: ${error.message}`; }
  });
  display();
}

const problemForm = document.querySelector("#problem-form");
if (problemForm) {
  const state = {variables: [], parameters: [], criteria: []};
  let sequence = 0;
  const rawErrors = new Set();
  const fields = {
    variables: ["name", "shape", "domain", "meaning", "units"],
    parameters: ["name", "value", "domain", "meaning", "units"],
    criteria: ["name", "sense", "expression", "meaning", "units"]
  };
  const labels = {name: "Name", shape: "Shape (JSON)", domain: "Domain", meaning: "Meaning", units: "Units", value: "Value (JSON)", sense: "Direction", expression: "Criterion expression"};
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
    const next = {variables: [], parameters: [], criteria: []};
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
          if (["domain", "sense"].includes(field)) {
            input = document.createElement("select");
            for (const domain of (field === "sense" ? ["minimize", "maximize"] : ["free", "nonneg", "nonpos", "symmetric", "PSD"])) {
              const option = document.createElement("option");
              option.value = option.textContent = domain;
              input.append(option);
            }
          } else {
            input = document.createElement(["value", "expression"].includes(field) ? "textarea" : "input");
            if (["value", "expression"].includes(field)) input.rows = 3;
          }
          input.id = id;
          input.dataset.field = field;
          input.value = ["shape", "value"].includes(field) ? JSON.stringify(declaration[field]) : (declaration[field] || (field === "domain" ? "free" : field === "sense" ? "minimize" : ""));
          wrapper.append(label, input);
          inputs.append(wrapper);
          if (field === "expression") equationEditor(input);
        }
        const actions = document.createElement("div");
        actions.className = "actions";
        for (const action of (kind === "criteria" ? ["Remove"] : ["Remove", kind === "parameters" ? "Make variable" : "Make parameter"])) {
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
  const mode = document.querySelector('#id_mode');
  const toggleMode = () => {
    document.querySelector('#single-editor').hidden = mode.value === 'multi';
    document.querySelector('#multi-editor').hidden = mode.value !== 'multi';
  };
  if (!mode.value) mode.value = 'single';
  mode.addEventListener('change', toggleMode);
  toggleMode();
  for (const input of document.querySelectorAll('.equation-input')) equationEditor(input);
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
          state[kind].push(kind === "criteria" ? {name: "", sense: "minimize", expression: "", meaning: "", units: ""} : {name: "", [kind === "variables" ? "shape" : "value"]: kind === "variables" ? [] : 0, domain: "free", meaning: "", units: ""});
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

function inspectPoint(chart, event) {
  const index = event.points?.[0]?.customdata;
  if (!chart.dataset.pointBase || !Number.isInteger(index)) return;
  const url = `${chart.dataset.pointBase}${index}/`;
  const note = document.querySelector('#point-selection');
  if (note) note.textContent = `Opening point ${index}: decision values and exact sampling settings.`;
  window.location.assign(url);
}
for (const chart of document.querySelectorAll("[data-chart]")) {
  const figure = JSON.parse(document.getElementById(chart.dataset.chart).textContent);
  Plotly.newPlot(chart, figure.data, figure.layout, {responsive: true, displaylogo: false}).then(() => {
    chart.on("plotly_click", event => inspectPoint(chart, event));
    let previousWidth = chart.clientWidth;
    const observer = new ResizeObserver(() => {
      if (chart.clientWidth > 0 && chart.clientWidth !== previousWidth) {
        previousWidth = chart.clientWidth;
        Plotly.relayout(chart, {width: previousWidth});
      }
    });
    observer.observe(chart);
  });
}
const dialog = document.querySelector("#chart-dialog");
for (const button of document.querySelectorAll(".expand-chart")) {
  button.addEventListener("click", () => {
    const chart = document.getElementById(button.dataset.target);
    // Preserve the current zoom and visible traces when opening the dialog.
    const figure = chart.data && chart.layout
      ? JSON.parse(JSON.stringify({data: chart.data, layout: chart.layout}))
      : JSON.parse(document.getElementById(chart.dataset.chart).textContent);
    dialog.showModal();
    Plotly.newPlot("expanded-chart", figure.data, {...figure.layout, width: undefined, height: undefined, autosize: true}, {responsive: true, displaylogo: false}).then(() => {
      document.querySelector("#expanded-chart").on("plotly_click", event => inspectPoint(chart, event));
    });
  });
}
document.querySelector("#close-chart")?.addEventListener("click", () => {
  dialog.close();
  if (window.Plotly) Plotly.purge("expanded-chart");
});

const datasetForm = document.querySelector('#dataset-form');
if (datasetForm) datasetForm.addEventListener('submit', () => {
  const button = datasetForm.querySelector('button');
  button.disabled = true;
  button.textContent = 'Fetching daily prices…';
});

// Browser-driven asynchronous batches: persisted progress, no worker process.
const fetchControls = document.querySelector('#fetch-controls');
if (fetchControls) {
  let running = false, paused = false;
  const resume = document.querySelector('#fetch-resume');
  const status = document.querySelector('#fetch-status');
  const run = async () => {
    if (running) return;
    running = true; paused = false; resume.disabled = true;
    try {
      while (!paused) {
        status.textContent = `${document.querySelector('#fetch-meter').value} symbols saved. Fetching next batch…`;
        const response = await fetch(fetchControls.dataset.batchUrl, {method: 'POST',
          headers: {'X-CSRFToken': fetchControls.querySelector('[name=csrfmiddlewaretoken]').value}, credentials: 'same-origin'});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Fetch failed. Resume to retry.');
        status.textContent = `${result.completed} / ${result.total} symbols stored. ${result.message}`;
        document.querySelector('#fetch-meter').value = result.completed;
        document.querySelector('#available-symbols').textContent = result.available.join(', ');
        document.querySelector('#fetch-errors').replaceChildren();
        for (const [symbol, error] of Object.entries(result.errors)) {
          const li = document.createElement('li'); li.textContent = `${symbol}: ${error}`; document.querySelector('#fetch-errors').append(li);
        }
        if (result.dataset_url) { window.location.assign(result.dataset_url); break; }
        if (!result.pending) break;
      }
    } catch (error) { status.textContent = `${error.message} Successful batches remain saved.`; }
    finally { running = false; resume.disabled = false; }
  };
  resume.addEventListener('click', run);
  document.querySelector('#fetch-pause').addEventListener('click', () => { paused = true; status.textContent += ' Pausing after the current batch.'; });
  if (fetchControls.dataset.autoRun === 'true') run();
}

const runProgress = document.querySelector('[data-run-status]');
if (runProgress) {
  const poll = async () => {
    try {
      const response = await fetch(runProgress.dataset.runStatus, {credentials: 'same-origin'});
      if (!response.ok) { runProgress.textContent = 'Status unavailable. Refresh to retry.'; return; }
      const result = await response.json();
      if (result.status !== 'running') { window.location.reload(); return; }
      setTimeout(poll, 5000);
    } catch (error) { runProgress.textContent = 'Connection interrupted. Refresh to retry.'; }
  };
  setTimeout(poll, 5000);
}
