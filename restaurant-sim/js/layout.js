/* Room geometry: doors, bar, and where the tables go. Units are meters, origin at the dining room's top-left.
   The kitchen is a band behind the north wall (negative y). */
(function () {
  const RS = window.RS;

  RS.wallPoint = (room, wall, pos) => {
    const m = 1.2;
    if (wall === 'N') return { x: RS.lerp(m, room.w - m, pos), y: 0 };
    if (wall === 'S') return { x: RS.lerp(m, room.w - m, pos), y: room.h };
    if (wall === 'W') return { x: 0, y: RS.lerp(m, room.h - m, pos) };
    return { x: room.w, y: RS.lerp(m, room.h - m, pos) };
  };
  const inward = (wall) => ({ N: [0, 1], S: [0, -1], W: [1, 0], E: [-1, 0] }[wall]);

  RS.geom = (cfg) => {
    const room = cfg.room, g = {};
    g.entrance = RS.wallPoint(room, room.entrance.wall, room.entrance.pos);
    const ei = inward(room.entrance.wall);
    g.host = { x: g.entrance.x + ei[0] * 1.5, y: g.entrance.y + ei[1] * 1.5 };
    g.waitSpot = (i) => ({ x: g.entrance.x + ei[0] * 0.7 + (ei[1] ? ((i % 5) - 2) * 0.55 : Math.floor(i / 5) * 0.5 * ei[0]),
      y: g.entrance.y + ei[1] * 0.7 + (ei[0] ? ((i % 5) - 2) * 0.55 : Math.floor(i / 5) * 0.5 * ei[1]) });
    g.kitchenDoor = RS.wallPoint(room, 'N', room.kitchenDoor.pos);
    g.pass = { x: g.kitchenDoor.x, y: 0.7 };
    g.restroom = RS.wallPoint(room, room.restroom.wall, room.restroom.pos);
    g.bar = null;
    if (room.bar.on) {
      const b = room.bar, len = Math.max(2, b.seats * 0.65), depth = 2.0;
      const horiz = b.wall === 'N' || b.wall === 'S';
      const span = horiz ? room.w : room.h;
      const start = RS.clamp(RS.lerp(0.4, span - len - 0.4, b.pos), 0.4, Math.max(0.4, span - len - 0.4));
      const r = horiz
        ? { x: start, y: b.wall === 'N' ? 0 : room.h - depth, w: len, h: depth }
        : { x: b.wall === 'W' ? 0 : room.w - depth, y: start, w: depth, h: len };
      const stools = [];
      for (let i = 0; i < b.seats; i++) {
        const t = (i + 0.5) / b.seats;
        stools.push(horiz ? { x: r.x + t * len, y: b.wall === 'N' ? 1.25 : room.h - 1.25 }
          : { x: b.wall === 'W' ? 1.25 : room.w - 1.25, y: r.y + t * len });
      }
      const counter = horiz ? { x: r.x, y: b.wall === 'N' ? 0.1 : room.h - 0.9, w: len, h: 0.8 }
        : { x: b.wall === 'W' ? 0.1 : room.w - 0.9, y: r.y, w: 0.8, h: len };
      const tender = horiz ? { x: r.x + len / 2, y: b.wall === 'N' ? 0.3 : room.h - 0.3 } : { x: b.wall === 'W' ? 0.3 : room.w - 0.3, y: r.y + len / 2 };
      const pickup = horiz ? { x: r.x + len / 2, y: b.wall === 'N' ? depth + 0.3 : room.h - depth - 0.3 } : { x: b.wall === 'W' ? depth + 0.3 : room.w - depth - 0.3, y: r.y + len / 2 };
      g.bar = { rect: r, stools, counter, tender, pickup, horiz };
    }
    return g;
  };

  const overlap = (a, b, pad) => a.x < b.x + b.w + pad && a.x + a.w + pad > b.x && a.y < b.y + b.h + pad && a.y + a.h + pad > b.y;

  /* Shelf-pack tables row by row. Spacing slider sets the aisle between them. Returns placed tables and how many did not fit. */
  RS.layoutTables = (cfg) => {
    const room = cfg.room, g = RS.geom(cfg), a = cfg.atmosphere;
    const scale = RS.lerp(0.88, 1.25, a.tableSize / 100);
    const gap = RS.lerp(1.0, 2.3, a.spacing / 100);   // includes chairs
    const margin = 0.9;
    const blocks = [];
    if (g.bar) blocks.push(g.bar.rect);
    [g.entrance, g.kitchenDoor, g.restroom].forEach((d) => blocks.push({ x: d.x - 1.3, y: d.y - 1.3, w: 2.6, h: 2.6 }));
    blocks.push({ x: g.host.x - 0.6, y: g.host.y - 0.6, w: 1.2, h: 1.2 });

    const want = [];
    [8, 6, 4, 2].forEach((n) => { for (let i = 0; i < (cfg.tables[n] || 0); i++) want.push(n); });
    // Interleave sizes a little so big tables are not all in one corner.
    const order = []; const big = want.filter((n) => n >= 6), small = want.filter((n) => n < 6);
    while (big.length || small.length) { if (big.length) order.push(big.shift()); for (let k = 0; k < 4 && small.length; k++) order.push(small.shift()); }

    const placed = []; let missing = 0;
    let y = margin + 0.4, x = margin, rowH = 0;
    for (const seats of order) {
      const d = RS.TABLE_DIM[seats]; const w = d[0] * scale, h = d[1] * scale;
      let ok = false, guard = 0;
      while (!ok && guard++ < 400) {
        if (x + w > room.w - margin) { x = margin; y += rowH + gap; rowH = 0; }
        if (y + h > room.h - margin) break;
        const r = { x, y, w, h };
        const hit = blocks.find((b) => overlap(r, b, gap * 0.35));
        if (hit) { x = Math.max(x + 0.3, hit.x + hit.w + gap * 0.35 + 0.01); continue; }
        ok = true;
      }
      if (!ok) { missing++; continue; }
      placed.push({ id: placed.length, seats, x, y, w, h });
      rowH = Math.max(rowH, h); x += w + gap;
    }
    // Center the block of tables vertically if there is slack.
    if (placed.length && !missing) {
      const maxY = Math.max.apply(null, placed.map((t) => t.y + t.h));
      const slack = (room.h - margin) - maxY;
      if (slack > 0.6) {
        const shift = slack / 2;
        const canShift = placed.every((t) => !blocks.some((b) => overlap({ x: t.x, y: t.y + shift, w: t.w, h: t.h }, b, gap * 0.3)));
        if (canShift) placed.forEach((t) => { t.y += shift; });
      }
    }
    if (cfg.manualLayout) placed.forEach((t) => { const m = cfg.manualLayout[t.id]; if (m) { t.x = RS.clamp(m.x, 0.2, room.w - t.w - 0.2); t.y = RS.clamp(m.y, 0.2, room.h - t.h - 0.2); } });
    placed.forEach((t) => { t.cx = t.x + t.w / 2; t.cy = t.y + t.h / 2; });
    // Bar stools become two-seat "tables" served by the bartender.
    if (g.bar) {
      for (let i = 0; i + 1 < g.bar.stools.length; i += 2) {
        const s1 = g.bar.stools[i], s2 = g.bar.stools[i + 1];
        placed.push({ id: placed.length, seats: 2, bar: true, stools: [s1, s2], cx: (s1.x + s2.x) / 2, cy: (s1.y + s2.y) / 2, x: s1.x, y: s1.y, w: 0, h: 0 });
      }
    }
    return { tables: placed, missing, geom: g };
  };

  /* Where a party sits, including any tables pushed together for them. */
  RS.partySpots = (p) => {
    const ts = [p.table].concat(p.table.joined || []); let left = p.size; const out = [];
    ts.forEach((t, i) => { const n = i === ts.length - 1 ? left : Math.min(left, t.seats); if (n > 0) RS.seatSpots(t, n).forEach((s) => out.push(s)); left -= n; });
    return out;
  };
  /* Seat positions around a table, used for drawing diners. */
  RS.seatSpots = (t, n) => {
    if (t.bar) return t.stools.slice(0, n);
    const out = [], per = Math.ceil(n / 2);
    for (let i = 0; i < n; i++) {
      const top = i % 2 === 0, k = Math.floor(i / 2);
      out.push({ x: t.x + (k + 0.5) * (t.w / per), y: top ? t.y - 0.32 : t.y + t.h + 0.32 });
    }
    return out;
  };
})();
