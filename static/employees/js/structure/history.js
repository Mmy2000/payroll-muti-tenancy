// Undo and redo. The server keeps the moves: they are real records, so it decides whether each can
// still go back. Arranging cards only lives in this browser, so it stays here, each step noting the
// move it came after. Together they run in the order they were done, so Ctrl+Z after dragging a card
// puts the card back rather than reversing an older move.
import { api } from "../../../core/js/api.js";
import { toast } from "../../../core/js/ui.js";
import { refresh, routes, state, words } from "./store.js";

const undoButton = document.querySelector("[data-undo]");
const redoButton = document.querySelector("[data-redo]");
const panel = document.querySelector("[data-panel]");

const arranged = []; // {undo, redo, after: the id of the last move at the time}
const unarranged = [];
let busy = false;

const moves = () => state.tree?.history ?? { undo: [], redo: [] };
const lastMove = () => moves().undo[0]?.id ?? 0;

function nextUndo() {
  const step = arranged.at(-1);
  if (step && step.after >= lastMove()) return { step };
  return moves().undo[0] ? { change: moves().undo[0] } : null;
}

function nextRedo() {
  const step = unarranged.at(-1);
  const change = moves().redo[0];
  if (step && (step.after <= lastMove() || !change)) return { step };
  return change ? { change } : null;
}

function drawButton(button, word, nothing, next) {
  const name = next ? `${word}: ${next.change?.label ?? words.arranged}` : nothing;
  button.disabled = busy || !next;
  button.title = name;
  button.setAttribute("aria-label", name);
}

export function drawHistory() {
  drawButton(undoButton, words.undo, words.nothing_to_undo, nextUndo());
  drawButton(redoButton, words.redo, words.nothing_to_redo, nextRedo());
}

// `undo` and `redo` put the cards back and redraw.
export function recordArrangement({ undo, redo }) {
  arranged.push({ undo, redo, after: lastMove() });
  unarranged.length = 0;
  drawHistory();
}

export function forgetRedo() {
  unarranged.length = 0;
}

async function sendMove(route, change, word) {
  busy = true;
  drawHistory();
  try {
    const result = await api(route, { method: "POST", body: { change_id: change.id } });
    if (result.done) toast(`${word}: ${result.label}`);
    else toast(`${result.label}: ${result.message}`, { kind: "error" });
    await refresh();
  } catch (error) {
    toast(error.message, { kind: "error" });
  } finally {
    busy = false;
    drawHistory();
  }
}

function undo() {
  const next = nextUndo();
  if (busy || !next) return;
  if (next.step) {
    arranged.pop();
    unarranged.push(next.step);
    next.step.undo();
    drawHistory();
  } else {
    sendMove(routes.undo, next.change, words.undone);
  }
}

function redo() {
  const next = nextRedo();
  if (busy || !next) return;
  if (next.step) {
    unarranged.pop();
    arranged.push(next.step);
    next.step.redo();
    drawHistory();
  } else {
    sendMove(routes.redo, next.change, words.redone);
  }
}

undoButton.addEventListener("click", undo);
redoButton.addEventListener("click", redo);

// The usual keys, except while typing, where they belong to the field, or in the move panel.
document.addEventListener("keydown", (event) => {
  if (!(event.ctrlKey || event.metaKey) || event.altKey || !panel.hidden) return;
  if (event.target.closest("input, textarea, select, [contenteditable], [data-modal]")) return;
  const key = event.key.toLowerCase();
  if (key !== "z" && key !== "y") return;
  event.preventDefault();
  if (key === "y" || event.shiftKey) redo();
  else undo();
});
