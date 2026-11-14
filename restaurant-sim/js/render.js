/* Top-down drawing of the room. Used live during service (with a sim) and as the layout editor (without one). */
(function () {
  const RS = window.RS;
  RS.ROLE_COLOR = { server: '#f4f1e8', busser: '#9aa7b8', host: '#e0c06a', bartender: '#c58cf0', owner: '#ff5d5d', cook: '#ffffff' };
  const TABLE_COLOR = { empty: null, taken: '#c9a24a', seated: '#d98b3a', waitFood: '#d98b3a', eating: '#5fae6e', waitClear: '#7b9bd1', waitCheck: '#7b9bd1', paying: '#7b9bd1', dirty: '#6b5b4d' };

  RS.view = (canvas, cfg, withKitchen) => {
    const K = withKitchen ? RS.KITCHEN_DEPTH : 0, pad = 0.6;
    const cw = canvas.clientWidth, ch = canvas.clientHeight, dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(cw * dpr) || canvas.height !== Math.round(ch * dpr)) { canvas.width = Math.round(cw * dpr); canvas.height = Math.round(ch * dpr); }
    const s = Math.min(cw / (cfg.room.w + pad * 2), ch / (cfg.room.h + K + pad * 2));
    const ox = (cw - cfg.room.w * s) / 2, oy = (ch - (cfg.room.h + K) * s) / 2 + K * s;
    return { s, ox, oy, dpr, K, X: (x) => ox + x * s, Y: (y) => oy + y * s, inv: (px, py) => ({ x: (px - ox) / s, y: (py - oy) / s }) };
  };

  const rr = (c, x, y, w, h, r) => { c.beginPath(); if (c.roundRect) c.roundRect(x, y, w, h, r); else c.rect(x, y, w, h); };
  const dot = (c, x, y, r, fill, stroke) => { c.beginPath(); c.arc(x, y, r, 0, 6.2832); c.fillStyle = fill; c.fill(); if (stroke) { c.strokeStyle = stroke; c.lineWidth = 1; c.stroke(); } };

  RS.draw = (canvas, cfg, layout, sim, sel) => {
    const v = RS.view(canvas, cfg, !!sim), c = canvas.getContext('2d'), room = cfg.room, g = layout.geom, s = v.s;
    c.setTransform(v.dpr, 0, 0, v.dpr, 0, 0);
    c.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
    c.font = Math.max(9, Math.min(12, s * 0.42)) + 'px system-ui, sans-serif'; c.textBaseline = 'middle'; c.textAlign = 'center';

    // Floor. The light slider sets how bright the room reads.
    const li = cfg.atmosphere.light / 100, f = Math.round(RS.lerp(30, 92, li));
    c.fillStyle = 'rgb(' + f + ',' + Math.round(f * 0.9) + ',' + Math.round(f * 0.78) + ')';
    rr(c, v.X(0), v.Y(0), room.w * s, room.h * s, 4); c.fill();
    c.strokeStyle = '#b79a62'; c.lineWidth = 2; c.stroke();
    const ink = li > 0.6 ? '#2b241a' : '#e8dfcc';

    // Kitchen band with stations.
    if (sim) {
      c.fillStyle = '#2a3138'; rr(c, v.X(0), v.Y(-v.K), room.w * s, v.K * s - 2, 4); c.fill();
      c.strokeStyle = '#55616d'; c.lineWidth = 1.5; c.stroke();
      const names = Object.keys(sim.stations), n = names.length, sw = (room.w - 0.6) / Math.max(1, n);
      names.forEach((name, i) => {
        const stn = sim.stations[name], x = 0.3 + i * sw, y = -v.K + 0.35, w = sw - 0.3, h = 1.25;
        const load = stn.active / stn.cap;
        c.fillStyle = stn.queued > 0 ? '#7a2e2e' : (load > 0.7 ? '#7a5a2a' : '#3b4650'); rr(c, v.X(x), v.Y(y), w * s, h * s, 3); c.fill();
        c.fillStyle = '#ffb84d'; c.fillRect(v.X(x), v.Y(y + h) - 4, w * s * Math.min(1, load), 4);
        c.fillStyle = '#e6edf3'; c.fillText(RS.STATION_LABEL[name].split(' ')[0] + ' ' + stn.active + '/' + stn.cap + (stn.queued ? ' +' + stn.queued : ''), v.X(x + w / 2), v.Y(y + h / 2));
        for (let k = 0; k < stn.active; k++) dot(c, v.X(x + 0.35 + k * 0.45), v.Y(y + h + 0.45), s * 0.17, RS.ROLE_COLOR.cook, '#333');
      });
      // Cooks who are not on a station right now stand at the pass.
      const idle = Math.max(0, sim.cooks - Math.ceil(sim.cookActive / 3));
      for (let k = 0; k < idle; k++) dot(c, v.X(g.kitchenDoor.x - 0.6 - k * 0.45), v.Y(-0.5), s * 0.17, RS.ROLE_COLOR.cook, '#333');
      const waiting = sim.tickets.filter((t) => t.ready && !t.delivered).length;
      c.fillStyle = waiting > 3 ? '#ff8c5a' : '#9aa7b8'; c.textAlign = 'left';
      c.fillText('KITCHEN   plates on the pass: ' + waiting, v.X(0.3), v.Y(-0.35)); c.textAlign = 'center';
    }

    // Doors.
    const door = (p, label, col) => {
      c.fillStyle = col;
      if (p.x === 0 || p.x === room.w) c.fillRect(v.X(p.x) - 4, v.Y(p.y) - s * 0.6, 8, s * 1.2);
      else c.fillRect(v.X(p.x) - s * 0.6, v.Y(p.y) - 4, s * 1.2, 8);
      c.fillStyle = ink; const ly = p.y === 0 ? 0.42 : (p.y === room.h ? -0.42 : 0), lx = p.x === 0 ? 1.05 : (p.x === room.w ? -1.05 : 0);
      c.fillText(label, v.X(p.x + lx), v.Y(p.y + ly));
    };
    door(g.entrance, 'Entrance', '#7fcf8a'); door(g.kitchenDoor, 'Kitchen', '#ffb84d'); door(g.restroom, 'WC', '#6fa8dc');
    c.fillStyle = '#8a6a3a'; rr(c, v.X(g.host.x - 0.4), v.Y(g.host.y - 0.25), 0.8 * s, 0.5 * s, 2); c.fill();

    // Bar.
    if (g.bar) {
      c.fillStyle = 'rgba(120,80,160,0.16)'; c.fillRect(v.X(g.bar.rect.x), v.Y(g.bar.rect.y), g.bar.rect.w * s, g.bar.rect.h * s);
      c.fillStyle = '#5a3d2a'; rr(c, v.X(g.bar.counter.x), v.Y(g.bar.counter.y), g.bar.counter.w * s, g.bar.counter.h * s, 3); c.fill();
      c.fillStyle = '#e8dfcc'; c.save(); c.translate(v.X(g.bar.counter.x + g.bar.counter.w / 2), v.Y(g.bar.counter.y + g.bar.counter.h / 2));
      if (!g.bar.horiz) c.rotate(-Math.PI / 2); c.fillText('BAR', 0, 0); c.restore();
      g.bar.stools.forEach((p) => dot(c, v.X(p.x), v.Y(p.y), s * 0.2, 'rgba(0,0,0,0)', ink));
    }

    // Tables.
    layout.tables.forEach((t) => {
      const st = sim ? (t.party && t.state === 'taken' ? (t.party.state === 'toTable' ? 'taken' : t.party.state) : t.state) : 'empty';
      const col = TABLE_COLOR[st] || null;
      if (t.bar) { if (sel === t) { c.strokeStyle = '#fff'; c.lineWidth = 2; c.strokeRect(v.X(t.cx) - s * 0.7, v.Y(t.cy) - s * 0.45, s * 1.4, s * 0.9); } return; }
      RS.seatSpots(t, t.seats).forEach((p) => { c.fillStyle = li > 0.6 ? 'rgba(0,0,0,0.18)' : 'rgba(255,255,255,0.13)'; c.fillRect(v.X(p.x) - s * 0.16, v.Y(p.y) - s * 0.16, s * 0.32, s * 0.32); });
      c.fillStyle = col || (li > 0.6 ? '#fbf7ee' : '#4a4034'); rr(c, v.X(t.x), v.Y(t.y), t.w * s, t.h * s, 3); c.fill();
      c.strokeStyle = sel === t ? '#ffffff' : 'rgba(0,0,0,0.35)'; c.lineWidth = sel === t ? 2.5 : 1; c.stroke();
      c.fillStyle = col ? '#1b1610' : ink; c.fillText(sim ? String(t.id + 1) : t.seats, v.X(t.cx), v.Y(t.cy));
    });

    if (!sim) return v;

    // Guests.
    const R = s * 0.2;
    sim.parties.forEach((p) => {
      const seated = p.table && !p.target && p.state !== 'leaving' && p.state !== 'toTable';
      if (seated) RS.seatSpots(p.table, p.size).forEach((q) => dot(c, v.X(q.x), v.Y(q.y), R, p.demo.color, '#1b1610'));
      else for (let i = 0; i < p.size; i++) dot(c, v.X(p.x + (i % 3) * 0.32 - 0.3), v.Y(p.y + Math.floor(i / 3) * 0.32), R, p.demo.color, p.walked ? '#ff3b3b' : '#1b1610');
    });
    // Staff, drawn as squares so they never read as guests.
    sim.agents.forEach((a) => {
      const z = s * 0.38; c.fillStyle = RS.ROLE_COLOR[a.role]; c.strokeStyle = '#111'; c.lineWidth = 1.2;
      c.beginPath(); c.rect(v.X(a.x) - z / 2, v.Y(a.y) - z / 2, z, z); c.fill(); c.stroke();
      if (a.cur && (a.cur.type === 'food' || a.cur.type === 'drinks') && a.cur.phase === 'dest') dot(c, v.X(a.x) + z * 0.5, v.Y(a.y) - z * 0.5, z * 0.28, a.cur.type === 'food' ? '#ffb84d' : '#8fd3ff');
    });
    return v;
  };
})();
