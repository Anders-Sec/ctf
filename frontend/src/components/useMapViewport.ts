import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Zoom and pan for the dungeon map.
 *
 * Drag to move, wheel to zoom toward the cursor, and a fullscreen mode that
 * fills the window. Kept apart from the map itself so the drawing code stays
 * about drawing.
 *
 * Panning is tracked as a drag *distance*, and a pointer that moved more than a
 * few pixels is treated as a pan rather than a click — otherwise every drag that
 * happens to start on a zone would also open it.
 */
export interface Viewport {
  scale: number;
  x: number;
  y: number;
}

const MIN_SCALE = 0.35;
const MAX_SCALE = 3;
const CLICK_SLOP = 5;

export function useMapViewport(content?: { width: number; height: number }) {
  const container = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState<Viewport>({ scale: 1, x: 0, y: 0 });
  const [fullscreen, setFullscreen] = useState(false);
  const [panning, setPanning] = useState(false);

  const drag = useRef<{ x: number; y: number; moved: number } | null>(null);
  //: How far the last gesture travelled. Kept past pointer-up because the click
  //: event fires *after* it, and that is where the pan-or-click call is made.
  const lastMoved = useRef(0);

  const zoomBy = useCallback((factor: number, originX?: number, originY?: number) => {
    setViewport((v) => {
      const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, v.scale * factor));
      if (scale === v.scale) return v;
      // Keep whatever is under the cursor under the cursor.
      const box = container.current?.getBoundingClientRect();
      const px = originX ?? (box ? box.width / 2 : 0);
      const py = originY ?? (box ? box.height / 2 : 0);
      const ratio = scale / v.scale;
      return {
        scale,
        x: px - (px - v.x) * ratio,
        y: py - (py - v.y) * ratio,
      };
    });
  }, []);

  /** The scale and offset that show the whole dungeon, centred. */
  const computeFit = useCallback((): Viewport => {
    const box = container.current?.getBoundingClientRect();
    // A container with no measured size yet (or none at all) cannot be fitted
    // against: doing the arithmetic anyway clamps to the minimum scale and
    // opens the map zoomed out to nothing.
    if (!box || !box.width || !box.height) return { scale: 1, x: 0, y: 0 };
    if (!content || !content.width || !content.height) {
      return { scale: 1, x: 0, y: 0 };
    }
    const scale = Math.min(
      MAX_SCALE,
      Math.max(
        MIN_SCALE,
        Math.min(box.width / content.width, box.height / content.height) * 0.96,
      ),
    );
    return {
      scale,
      x: (box.width - content.width * scale) / 2,
      y: (box.height - content.height * scale) / 2,
    };
  }, [content]);

  const reset = useCallback(() => setViewport(computeFit()), [computeFit]);

  // Open showing the whole map rather than at 1x in the top-left corner. Also
  // re-fits when leaving fullscreen, where the container is a different size.
  useEffect(() => {
    setViewport(computeFit());
  }, [computeFit, fullscreen]);

  const onPointerDown = useCallback((event: React.PointerEvent) => {
    // Left button only, so a right-click menu still works.
    if (event.button !== 0) return;
    drag.current = { x: event.clientX, y: event.clientY, moved: 0 };
    lastMoved.current = 0;
    setPanning(true);
  }, []);

  const onPointerMove = useCallback((event: React.PointerEvent) => {
    const state = drag.current;
    if (!state) return;
    const dx = event.clientX - state.x;
    const dy = event.clientY - state.y;
    state.moved += Math.abs(dx) + Math.abs(dy);
    state.x = event.clientX;
    state.y = event.clientY;
    setViewport((v) => ({ ...v, x: v.x + dx, y: v.y + dy }));
  }, []);

  const endDrag = useCallback(() => {
    if (drag.current) lastMoved.current = drag.current.moved;
    drag.current = null;
    setPanning(false);
  }, []);

  /** True when the pointer was dragged far enough that this was a pan. */
  const wasPan = useCallback(
    () => Math.max(lastMoved.current, drag.current?.moved ?? 0) > CLICK_SLOP,
    [],
  );

  const onWheel = useCallback(
    (event: React.WheelEvent) => {
      const box = container.current?.getBoundingClientRect();
      zoomBy(
        event.deltaY < 0 ? 1.12 : 1 / 1.12,
        box ? event.clientX - box.left : undefined,
        box ? event.clientY - box.top : undefined,
      );
    },
    [zoomBy],
  );

  // Escape leaves fullscreen — the same key that closes the zone panel, and the
  // one people try first.
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreen]);

  return {
    container,
    viewport,
    fullscreen,
    panning,
    setFullscreen,
    zoomBy,
    reset,
    wasPan,
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp: endDrag,
      onPointerLeave: endDrag,
      onWheel,
    },
  };
}
