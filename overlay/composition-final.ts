/** Reconcile engines that emit compositionend before the final input event. */
export interface CompositionSnapshot {
  active: boolean;
  isComposing: boolean;
  compositionAnchor: unknown | null;
  compositionLength: number;
  _lastCompositionText?: string;
  textarea: { value: string };
}

export function settleFinalComposition(state: CompositionSnapshot, flush: () => void): void {
  if (!state.active || !state.isComposing || !state.compositionAnchor) return;
  const pending = state.textarea.value;
  if (pending && (state.compositionLength === 0 || pending !== state._lastCompositionText)) {
    // Reuse the normal composition-input path before clearing the input or recording undo.
    flush();
  }
}
