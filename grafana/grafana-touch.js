// Touch gestures for Grafana's time series panels, loaded on every page (see
// Dockerfile).
//
// Based on grafana-touch-shim 0.3.5
// (https://github.com/dimitur2204/grafana-touch-shim), extended with sideways
// swipes that move the time range (see startPan()) and pinching to zoom it
// (see startPinch()). Its license:
//
//   MIT License
//
//   Copyright (c) 2026 Dimitar Nizamov
//
//   Permission is hereby granted, free of charge, to any person obtaining a
//   copy of this software and associated documentation files (the
//   "Software"), to deal in the Software without restriction, including
//   without limitation the rights to use, copy, modify, merge, publish,
//   distribute, sublicense, and/or sell copies of the Software, and to permit
//   persons to whom the Software is furnished to do so, subject to the
//   following conditions:
//
//   The above copyright notice and this permission notice shall be included
//   in all copies or substantial portions of the Software.
//
//   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
//   OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
//   MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
//   NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
//   DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
//   OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
//   USE OR OTHER DEALINGS IN THE SOFTWARE.

// Grafana's time series panels are drawn by uPlot, whose overlay element
// (.u-over) only understands mouse events. This shim turns touch gestures
// into those mouse events:
//
//   one-finger vertical swipe      -> untouched, the page scrolls as usual
//   one-finger sideways swipe      -> moves the time range: the chart follows
//                                     the finger, the dashboard switches to the
//                                     new range on lifting
//   two-finger pinch               -> zooms the time range around the fingers
//                                     (sliding both fingers also moves it); the
//                                     dashboard switches to it on lifting
//   long-press (300 ms), drag      -> mouseenter + mousemove: crosshair/tooltip
//                                     snaps onto the top line at the finger's
//                                     time; stays after lifting
//   while holding, tap a second    -> mousedown at the crosshair: marks the start
//     finger anywhere                 of a time range
//   keep dragging the first finger -> mousemove: uPlot draws the selection
//   lift the first finger          -> mouseup: zoom to the selection
//   tap the second finger again    -> cancel the selection, back to hover
//
// One finger does all the positioning; the second finger is only a button, so
// its position and jitter never matter. Because the crosshair snaps onto the
// line, only the finger's horizontal position matters and it can stay clear of
// the value it is reading.
(function () {
  'use strict';
  // Marked on the DOM, not window: someone running the original shim as a
  // userscript gets it in a different JS context but on the same document.
  if (document.documentElement.dataset.grafanaTouchShim) return;
  document.documentElement.dataset.grafanaTouchShim = '1';

  const LONG_PRESS_MS = 300;
  const MOVE_TOLERANCE = 10; // px a finger may drift before the press counts as a scroll
  // A swipe moves the time range only if it is at least this many times wider
  // than tall, so a slightly slanted scroll still scrolls.
  const PAN_RATIO = 2;
  // Fingers closer together than this (horizontally) count as this far apart,
  // so a mostly vertical pinch doesn't zoom wildly.
  const PINCH_MIN_PX = 40;
  // Maximum vertical spacing of the probes that look for the top line. Grafana
  // shows the cursor dot within 30 px of a line; see hover() for why the
  // spacing must not exceed that.
  const PROBE_STEP = 28;
  const TOUCH_EVENTS = ['touchstart', 'touchmove', 'touchend', 'touchcancel'];

  // Keep long-press from selecting text or opening the iOS callout on charts.
  // Leave only vertical scrolling to the browser, so sideways swipes and
  // pinches reach startPan() and startPinch() instead of moving or zooming the
  // page.
  // uPlot rounds the cursor dot's position up (Math.ceil) to whole pixels, so
  // it always sits 0-1 px right of and below the data point; shift it back by
  // half a pixel to centre the error. `translate` adds to uPlot's own
  // `transform` without touching it.
  const style = document.createElement('style');
  style.textContent = '.u-over{-webkit-touch-callout:none;-webkit-user-select:none;user-select:none;' +
    'touch-action:pan-y}' +
    '.u-cursor-pt{translate:-0.5px -0.5px}';
  document.head.appendChild(style);

  // The gesture in progress, or null when no finger is down on a chart.
  // mode: 'pending' (waiting for long-press) | 'hover' | 'select' | 'pan' | 'pinch' | 'browser' | 'done'
  let g = null;
  // Overlay whose tooltip is still showing after the finger lifted.
  let lingering = null;

  // Position of the last synthetic event, for movementX/Y. uPlot ignores
  // mousemove during a drag when both are 0 (its guard against Chrome's
  // spurious mousemoves), and synthetic events default to 0.
  let lastX = 0;
  let lastY = 0;

  function fire(over, type, x, y, buttons) {
    const movementX = x - lastX;
    const movementY = y - lastY;
    lastX = x;
    lastY = y;
    over.dispatchEvent(new MouseEvent(type, {
      movementX: movementX,
      movementY: movementY,
      bubbles: type !== 'mouseenter' && type !== 'mouseleave',
      cancelable: true,
      view: window,
      clientX: x,
      clientY: y,
      button: 0,
      buttons: buttons,
    }));
  }

  function findTouch(list, id) {
    return Array.prototype.find.call(list, (t) => t.identifier === id) || null;
  }

  function buzz() {
    if (navigator.vibrate) navigator.vibrate(15); // Android only; iOS ignores it
  }

  function hideLingering() {
    if (lingering) fire(lingering, 'mouseleave', 0, 0, 0);
    lingering = null;
  }

  // uPlot marks the hovered value with a dot (.u-cursor-pt); hidden dots get
  // .u-off. Returns the centre of the topmost visible dot, or null if none.
  function topDot(over) {
    let best = null;
    for (const el of over.querySelectorAll('.u-cursor-pt')) {
      if (el.classList.contains('u-off')) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      const dot = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      if (best === null || dot.y < best.y) best = dot;
    }
    return best;
  }

  // Snap the crosshair onto the top line at the finger's time. The time series
  // panel shows a single dot, on the line nearest the cursor and only within
  // 30 px of it, so probe down from the top of the chart until a dot appears.
  // With probes at most 30 px apart, the first dot is always on the top line:
  // the previous probe found nothing, so every line is more than 30 px below
  // it, i.e. below this probe too, and the line nearest a point above all of
  // them is the top one. (With wider spacing this probe could land just under
  // the top line and pick a closer line beneath it.) The probes run
  // synchronously, so only the final move is drawn.
  function hover() {
    const r = g.over.getBoundingClientRect();
    const n = Math.max(1, Math.ceil(r.height / PROBE_STEP)); // evenly spaced, both edges included
    let dot = null;
    for (let i = 0; !dot && i <= n; i++) {
      fire(g.over, 'mousemove', g.x, r.top + (r.height * i) / n, 0);
      dot = topDot(g.over);
    }
    // No dot means no value at this time (or not a line chart): follow the finger.
    if (!dot) {
      settle(g.x, g.y);
      return;
    }
    // First choice: the data point itself, so the crosshair lines up with the
    // dot on a steep line. But the dot is drawn on whole pixels, and when data
    // points are closer together than that, its x can hover the neighbouring
    // point instead; on a spike that one is far away and Grafana shows no dot
    // or tooltip. So check that uPlot still shows the same dot there.
    settle(dot.x, dot.y);
    const shown = topDot(g.over);
    if (shown && Math.abs(shown.x - dot.x) <= 0.5 && Math.abs(shown.y - dot.y) <= 0.5) return;
    // Fallback that cannot miss: at the probe's x uPlot hovers the same data
    // point, and at the dot's own height the cursor is 0 px from the line.
    settle(g.x, dot.y);
  }

  function settle(x, y) {
    g.snapX = x;
    g.snapY = y;
    fire(g.over, 'mousemove', x, y, 0);
  }

  function startHover() {
    g.mode = 'hover';
    fire(g.over, 'mouseenter', g.x, g.y, 0);
    hover();
  }

  // Mark the start of the range at the crosshair. The y of every drag event is
  // pinned to this point so uPlot sees a purely horizontal (time) selection.
  function startSelect() {
    g.mode = 'select';
    g.markX = g.snapX;
    g.markY = g.snapY;
    fire(g.over, 'mousedown', g.markX, g.markY, 1);
    buzz();
  }

  // Shrink the selection back to the mark, then release: uPlot only zooms on
  // a selection with a width, and it sizes the selection on mousemove.
  function cancelSelect() {
    if (g.x !== g.markX) fire(g.over, 'mousemove', g.markX, g.markY, 1);
    fire(g.over, 'mouseup', g.markX, g.markY, 0);
    g.mode = 'hover';
    hover();
    buzz();
  }

  // Whether the panel has its own time shift or relative time (Grafana marks
  // those with a clock in the header). Its range is not the dashboard's, so
  // moving or zooming it would change the dashboard by the wrong amount.
  function ownTimeRange(over) {
    const panel = over.closest('section');
    return !!(panel && panel.querySelector('[data-testid="icon-clock-nine"]'));
  }

  // Moving the time range is built into Grafana (12.4 has it on by default,
  // feature toggle timeRangePan): drag the x axis with the mouse. The chart
  // follows the pointer, like sliding paper, and on release Grafana applies the
  // new range to the whole dashboard. It listens for mousedown on the axis,
  // then for mousemove/mouseup on the document.
  function mouse(target, type, x) {
    target.dispatchEvent(new MouseEvent(type, {
      bubbles: target !== document,
      cancelable: true,
      view: window,
      clientX: x,
      clientY: g.y0,
      button: 0,
      buttons: type === 'mouseup' ? 0 : 1,
    }));
  }

  // Start moving the time range. Returns false where that is not possible.
  function startPan() {
    const axis = g.over.closest('.uplot').querySelector('.u-axis'); // the first axis is x
    if (!axis || ownTimeRange(g.over)) return false;
    if (lingering === g.over) hideLingering();
    g.mode = 'pan';
    mouse(axis, 'mousedown', g.x0);
    return true;
  }

  // Lift the finger: apply the new range, or, for a cancelled touch, slide the
  // chart back first (Grafana ignores drags under 5 px).
  function endPan(apply) {
    if (!apply) mouse(document, 'mousemove', g.x0);
    mouse(document, 'mouseup', apply ? g.x : g.x0);
  }

  // Grafana has no pinch, and no way to zoom out beyond the visible range by
  // mouse, so pinching works with uPlot directly. Grafana keeps the uPlot
  // instance on the React component that mounted it, a couple of levels above
  // the element uPlot was mounted into.
  function plotOf(over) {
    const host = over.closest('.uplot').parentElement;
    const key = host && Object.keys(host).find((k) => k.startsWith('__reactFiber$'));
    let fiber = key && host[key];
    for (let i = 0; fiber && i < 10; i++, fiber = fiber.return) {
      const u = fiber.stateNode && fiber.stateNode.plotInstance;
      if (u && typeof u.setScale === 'function') return u;
    }
    return null;
  }

  // Start zooming the time range with the first finger and another one.
  // Returns false where that is not possible.
  function startPinch(touches) {
    const a = findTouch(touches, g.id);
    const b = Array.prototype.find.call(touches, (t) => t.identifier !== g.id);
    const u = plotOf(g.over);
    if (!a || !b || !u || u.scales.x.min == null || ownTimeRange(g.over)) return false;
    if (lingering === g.over) hideLingering();
    const r = g.over.getBoundingClientRect();
    g.mode = 'pinch';
    g.id2 = b.identifier;
    g.u = u;
    g.left = r.left;
    g.width = r.width;
    g.min0 = u.scales.x.min;
    g.max0 = u.scales.x.max;
    g.mid0 = (a.clientX + b.clientX) / 2;
    g.dist0 = Math.max(Math.abs(a.clientX - b.clientX), PINCH_MIN_PX);
    // Grafana's range function pins the x scale to the dashboard's time range;
    // swap in one that shows the preview until the fingers lift.
    const view = { min: g.min0, max: g.max0 };
    g.view = view;
    g.range = u.scales.x.range;
    u.scales.x.range = () => [view.min, view.max];
    return true;
  }

  // Keep the time that was under the fingers' midpoint under it, and scale the
  // range by how far apart the fingers are horizontally (it's a time axis).
  function pinch(touches) {
    const a = findTouch(touches, g.id);
    const b = findTouch(touches, g.id2);
    if (!a || !b) return;
    const span0 = g.max0 - g.min0;
    const span = (span0 * g.dist0) / Math.max(Math.abs(a.clientX - b.clientX), PINCH_MIN_PX);
    const time = g.min0 + ((g.mid0 - g.left) / g.width) * span0;
    g.view.min = time - (((a.clientX + b.clientX) / 2 - g.left) / g.width) * span;
    g.view.max = g.view.min + span;
    g.u.setScale('x', { min: g.view.min, max: g.view.max });
  }

  // Apply the new range to the whole dashboard, or put the chart back.
  // Grafana has no API for this, but its router reads from/to from the URL on
  // popstate. pushState lets the back button undo the zoom.
  function endPinch(apply) {
    g.u.scales.x.range = g.range;
    if (!apply || (g.view.min === g.min0 && g.view.max === g.max0)) {
      g.u.setScale('x', { min: g.min0, max: g.max0 });
      return;
    }
    const url = new URL(location.href);
    url.searchParams.set('from', String(Math.round(g.view.min)));
    url.searchParams.set('to', String(Math.round(g.view.max)));
    history.pushState(history.state, '', url);
    window.dispatchEvent(new PopStateEvent('popstate', { state: history.state }));
  }

  // Entry point: a finger lands on a chart overlay.
  function onOverTouchStart(e) {
    if (g) return; // later fingers are handled by the document listeners
    const over = e.currentTarget;
    if (lingering !== over) hideLingering();
    const t = e.changedTouches[0];
    g = { over: over, id: t.identifier, x: t.clientX, y: t.clientY, x0: t.clientX, y0: t.clientY, mode: 'pending' };
    // Two fingers landing together are a pinch.
    if (e.touches.length > 1) {
      if (startPinch(e.touches)) e.preventDefault();
      else g.mode = 'browser';
    } else {
      g.timer = setTimeout(startHover, LONG_PRESS_MS);
    }
    // Follow the rest of the gesture on the document, since the second finger
    // may land outside the overlay.
    for (const type of TOUCH_EVENTS) {
      document.addEventListener(type, onDocTouch, { capture: true, passive: false });
    }
  }

  function onDocTouch(e) {
    if (e.type === 'touchstart') {
      if (g.mode === 'pending') {
        clearTimeout(g.timer);
        // Second finger before the long-press: a pinch.
        if (startPinch(e.touches)) e.preventDefault();
        else g.mode = 'browser';
      } else if (g.mode === 'hover') {
        e.preventDefault();
        startSelect();
      } else if (g.mode === 'select') {
        e.preventDefault();
        cancelSelect();
      }
      return;
    }

    if (e.type === 'touchmove') {
      const t = findTouch(e.touches, g.id);
      if (g.mode === 'pending') {
        if (!t) return;
        g.x = t.clientX;
        g.y = t.clientY;
        if (Math.hypot(g.x - g.x0, g.y - g.y0) > MOVE_TOLERANCE) {
          clearTimeout(g.timer);
          // Not cancelable means the browser is already scrolling.
          const sideways = Math.abs(g.x - g.x0) > PAN_RATIO * Math.abs(g.y - g.y0);
          if (e.cancelable && sideways && startPan()) {
            e.preventDefault();
            mouse(document, 'mousemove', g.x);
          } else {
            g.mode = 'browser'; // a normal swipe
          }
        }
      } else if (g.mode === 'pan') {
        e.preventDefault();
        if (!t) return; // only a second finger moved: ignore it
        g.x = t.clientX;
        mouse(document, 'mousemove', g.x);
      } else if (g.mode === 'pinch') {
        e.preventDefault();
        pinch(e.touches);
      } else if (g.mode === 'hover' || g.mode === 'select') {
        e.preventDefault();
        if (!t) return; // only the second finger moved: ignore it
        g.x = t.clientX;
        g.y = t.clientY;
        if (g.mode === 'hover') hover();
        else fire(g.over, 'mousemove', g.x, g.markY, 1);
      } else if (g.mode === 'done') {
        e.preventDefault();
      }
      return;
    }

    // touchend / touchcancel. Only the first finger lifting ends the gesture;
    // the second finger coming up is just the end of a tap. A pinch ends with
    // either of its fingers.
    const firstLifted = findTouch(e.changedTouches, g.id) !== null;
    if (g.mode === 'pinch' && (firstLifted || findTouch(e.changedTouches, g.id2))) {
      // A cancelled touch (e.g. an incoming call) must not zoom.
      endPinch(e.type === 'touchend');
      g.mode = 'done';
      g.suppressClick = true;
    } else if (firstLifted) {
      if (g.mode === 'select') {
        // A cancelled touch (e.g. an incoming call) must not zoom.
        if (e.type === 'touchcancel' && g.x !== g.markX) fire(g.over, 'mousemove', g.markX, g.markY, 1);
        fire(g.over, 'mouseup', e.type === 'touchcancel' ? g.markX : g.x, g.markY, 0);
        g.mode = 'done';
        g.suppressClick = true;
      } else if (g.mode === 'hover') {
        lingering = g.over;
        g.mode = 'done';
        g.suppressClick = true;
      } else if (g.mode === 'pan') {
        // A cancelled touch (e.g. an incoming call) must not move the range.
        endPan(e.type === 'touchend');
        g.mode = 'done';
        g.suppressClick = true;
      } else if (g.mode === 'pending') {
        clearTimeout(g.timer);
        g.mode = 'done'; // a plain tap: let the browser turn it into a click
      }
    }
    // Stop the browser's compatibility mouse events and click, which would
    // otherwise pin Grafana's tooltip or start another drag.
    if ((g.suppressClick || g.mode === 'hover' || g.mode === 'select') && e.cancelable) e.preventDefault();

    if (e.touches.length === 0) {
      clearTimeout(g.timer);
      for (const type of TOUCH_EVENTS) {
        document.removeEventListener(type, onDocTouch, { capture: true });
      }
      g = null;
    }
  }

  // Android opens a context menu on long-press; not wanted mid-gesture.
  function onContextMenu(e) {
    if (g) e.preventDefault();
  }

  // Touching anywhere outside the chart hides a lingering tooltip.
  document.addEventListener('touchstart', (e) => {
    if (lingering && !lingering.contains(e.target)) hideLingering();
  }, { capture: true, passive: true });

  // Panels mount and remount as you scroll and switch dashboards, so attach
  // to every new overlay. Scans are batched to at most one per frame.
  const attached = new WeakSet();
  function scan() {
    for (const over of document.querySelectorAll('.u-over')) {
      if (attached.has(over)) continue;
      attached.add(over);
      over.addEventListener('touchstart', onOverTouchStart, { passive: false });
      over.addEventListener('contextmenu', onContextMenu);
    }
  }
  let scanQueued = false;
  new MutationObserver(() => {
    if (scanQueued) return;
    scanQueued = true;
    requestAnimationFrame(() => {
      scanQueued = false;
      scan();
    });
  }).observe(document.body, { childList: true, subtree: true });
  scan();
})();
