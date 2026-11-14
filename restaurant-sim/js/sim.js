/* One dinner service, 5:00 pm onward. Nobody is player-controlled: guests, floor staff and the kitchen
   all run on the rules below. step(dt) advances dt sim-minutes; results() produces the night's P&L. */
(function () {
  const RS = window.RS;
  const LAST_SEATING = 285, HARD_CLOSE = 425;
  const PRIO = { food: 0, drinks: 1, order: 2, check: 3, clear: 3, bus: 5, visit: 6 };

  RS.createSim = (game, seed) => {
    const cfg = game.cfg, rnd = RS.rng(seed || (game.day + 1) * 7919);
    const L = RS.layoutTables(cfg), G = L.geom, cui = RS.cuisine(cfg);
    const A = { light: cfg.atmosphere.light / 100, noise: cfg.atmosphere.noise / 100, formality: cfg.atmosphere.formality / 100, spacing: cfg.atmosphere.spacing / 100 };
    const touch = cfg.diner.touch / 100, pace = cfg.diner.pace / 100, exp = cfg.staff.experience / 100, style = cfg.staff.style / 100;
    const alcFocus = cfg.menu.alcoholFocus / 100, priceT = cfg.priceTier / 100 + cfg.menu.priceAdj / 100, sourcing = cfg.sourcing / 100;
    const quality = A.formality * 0.3 + sourcing * 0.35 + exp * 0.35;
    const overprice = Math.max(0, priceT - quality - 0.12);
    const dow = game.day % 7;
    const D = cfg.delighters || {};
    const menu = RS.activeItems(cfg);
    const byCourse = (c) => menu.filter((i) => i.course === c);
    const avgPrice = {}; ['starter', 'main', 'side', 'dessert', 'drink'].forEach((c) => { const l = byCourse(c); avgPrice[c] = l.length ? l.reduce((s, i) => s + i.price, 0) / l.length : 1; });
    const lineMult = { compact: 0.7, standard: 1, large: 1.4 }[cfg.room.line] || 1;

    const sim = { t: 0, done: false, cfg, geom: G, tables: L.tables, parties: [], gone: [], agents: [], tickets: [], log: [], dow,
      stations: {}, cooks: cfg.staff.cooks, cookActive: 0 };
    const st = sim.stats = { revenue: 0, foodRev: 0, bevRev: 0, discounts: 0, cogs: 0, covers: 0, partiesSeated: 0, walkouts: 0, walkoutParties: 0, turnedAway: 0,
      items: {}, seatWait: [], greetWait: [], ticketTimes: [], lateTickets: 0, sats: [], tips: 0, cookWait: 0, stationWait: {}, stationBusy: {},
      seatsOffered: 0, seatsUsed: 0, demos: {}, comps: 0, perCoverCost: 0, checkWait: [], arrivals: 0, demandCovers: 0, barWaitDrinks: 0 };
    menu.forEach((i) => { st.items[i.id] = { qty: 0, rev: 0, cost: 0, free: 0 }; });
    Object.keys(RS.STATION_CAP).forEach((s) => {
      if (menu.some((i) => i.station === s && i.course !== 'drink' && i.prep !== 'batch')) { sim.stations[s] = { cap: Math.max(1, Math.round(RS.STATION_CAP[s] * lineMult)), active: 0, queued: 0 }; st.stationWait[s] = 0; st.stationBusy[s] = 0; }
    });
    const say = (msg, kind) => { sim.log.unshift({ t: sim.t, msg, kind: kind || 'info' }); if (sim.log.length > 60) sim.log.pop(); };

    /* ---------- staff ---------- */
    const mk = (role, i, home) => ({ id: role + i, role, x: home.x, y: home.y, home, queue: [], cur: null, busy: 0 });
    const inRoom = (p) => ({ x: RS.clamp(p.x, 0.5, cfg.room.w - 0.5), y: RS.clamp(p.y, 0.5, cfg.room.h - 0.5) });
    const servers = [], bussers = [], hosts = [], tenders = [];
    for (let i = 0; i < cfg.staff.servers; i++) servers.push(mk('server', i, inRoom({ x: G.pass.x + (i - (cfg.staff.servers - 1) / 2) * 0.7, y: 1.1 })));
    for (let i = 0; i < cfg.staff.bussers; i++) bussers.push(mk('busser', i, inRoom({ x: G.pass.x + (i - (cfg.staff.bussers - 1) / 2) * 0.7, y: 1.9 })));
    for (let i = 0; i < cfg.staff.hosts; i++) hosts.push(mk('host', i, { x: G.host.x + i * 0.6, y: G.host.y }));
    if (G.bar) for (let i = 0; i < cfg.staff.bartenders; i++) tenders.push(mk('bartender', i, { x: G.bar.tender.x + (G.bar.horiz ? i * 0.8 : 0), y: G.bar.tender.y + (G.bar.horiz ? 0 : i * 0.8) }));
    let owner = null;
    if (cfg.owner.presence > 60) { owner = mk('owner', 0, inRoom({ x: G.host.x + 1.2, y: G.host.y })); owner.nextVisit = 20; }
    sim.agents = [].concat(servers, bussers, hosts, tenders, owner ? [owner] : []);
    const hostFreeAt = hosts.length ? hosts.map(() => 0) : [0];
    const seatTime = hosts.length ? 1.2 : 3.5;

    // Sections: split the dining tables into contiguous strips, one per server. The bartender owns the stools.
    const dining = sim.tables.filter((t) => !t.bar).slice().sort((a, b) => a.cx - b.cx || a.cy - b.cy);
    dining.forEach((t, i) => { t.server = servers[Math.min(servers.length - 1, Math.floor(i * servers.length / Math.max(1, dining.length)))]; });
    sim.tables.filter((t) => t.bar).forEach((t, i) => { t.server = tenders.length ? tenders[i % tenders.length] : servers[i % servers.length]; });
    sim.tables.forEach((t) => { t.state = 'empty'; t.party = null; t.turns = 0; });
    const busQueue = [];

    const addTask = (agent, task) => { task.created = sim.t; task.prio = PRIO[task.type]; (agent ? agent.queue : busQueue).push(task); };
    const tableTask = (table, task) => { task.dest = { x: table.cx, y: table.cy + (table.bar ? 0 : table.h / 2 + 0.55) }; task.table = table; addTask(table.server, task); };
    const move = (o, target, speed, dt) => {
      const dx = target.x - o.x, dy = target.y - o.y, d = Math.hypot(dx, dy), s = speed * dt;
      if (d <= s) { o.x = target.x; o.y = target.y; return true; }
      o.x += dx / d * s; o.y += dy / d * s; return false;
    };
    const pickTask = (q) => { let bi = -1; for (let i = 0; i < q.length; i++) if (bi < 0 || q[i].prio < q[bi].prio || (q[i].prio === q[bi].prio && q[i].created < q[bi].created)) bi = i; return bi < 0 ? null : q.splice(bi, 1)[0]; };

    const stepAgent = (a, dt) => {
      if (!a.cur) {
        let task = pickTask(a.queue);
        if (!task && a.role === 'busser') {
          task = pickTask(busQueue);
          if (!task) { // run food that has been dying on the pass
            for (const s of servers) { const i = s.queue.findIndex((q) => q.type === 'food' && sim.t - q.created > 1.5); if (i >= 0) { task = s.queue.splice(i, 1)[0]; break; } }
          }
        }
        if (!task && a.role === 'server' && !bussers.length) task = pickTask(busQueue);
        if (!task && a.role === 'owner' && sim.t >= a.nextVisit) {
          const occ = sim.tables.filter((t) => t.party && !t.party.ownerVisited && t.party.state !== 'toTable');
          a.nextVisit = sim.t + 5 + rnd() * 5;
          if (occ.length) { const t = rnd.pick(occ); task = { type: 'visit', dest: { x: t.cx + 0.6, y: t.cy + (t.h || 0) / 2 + 0.6 }, dwell: 1.5, onDone: () => { if (t.party) t.party.ownerVisited = true; } }; }
        }
        if (!task) { move(a, a.home, 22, dt); return; }
        a.cur = task; task.phase = task.pickup ? 'pickup' : 'dest'; task.remain = task.dwell || 0.5;
      }
      a.busy += dt;
      const c = a.cur;
      if (c.phase === 'pickup') { if (move(a, c.pickup, 20, dt)) c.phase = 'dest'; return; }
      if (c.phase === 'dest') { if (move(a, c.dest, 20, dt)) { c.phase = 'dwell'; if (c.onStart) c.onStart(); } return; }
      c.remain -= dt;
      if (c.remain <= 0) { a.cur = null; if (c.onDone) c.onDone(); }
    };

    /* ---------- demand ---------- */
    const seats = RS.seatCount(cfg);
    const deals = cfg.plays.filter((p) => p.type === 'discount' || p.type === 'bogo').length;
    const valueMult = 1 - 0.6 * overprice + 0.15 * Math.max(0, quality - priceT - 0.1);
    const target = (72 + 0.85 * seats) * RS.DOW_DEMAND[dow] * (0.55 + 0.9 * game.reputation) * valueMult * (1 + 0.03 * deals) * rnd.range(0.92, 1.08);
    st.demandCovers = Math.round(target);
    const maxTable = Math.max.apply(null, sim.tables.map((t) => t.seats).concat([0]));
    const arrivals = []; let planned = 0, pid = 0;
    const demoW = (d) => { let e = 0; ['light', 'noise', 'formality', 'spacing'].forEach((k) => { e += d.likes[k] * (A[k] - 0.5); }); return d.base * Math.exp(e * 1.6) * (d.id === 'solo' && !G.bar ? 0.5 : 1); };
    while (planned < target) {
      const demo = rnd.weighted(RS.DEMOS, demoW), size = rnd.pick(demo.sizes);
      // Triangular: builds from 5, peaks around 7:30, tails off by last seating.
      const at = RS.clamp(145 + ((rnd() + rnd()) / 2 - 0.5) * 2 * 150, 0, LAST_SEATING);
      arrivals.push({ id: pid++, demo, size, at }); planned += size;
    }
    arrivals.sort((a, b) => a.at - b.at);
    let nextArrival = 0;

    /* ---------- ordering ---------- */
    const vibe = G.bar ? cfg.room.bar.vibe : null;
    const weight = (it, party) => {
      const d = party.demo; let w = it.appeal;
      w *= Math.exp(-(1.2 / d.spend) * (it.price / avgPrice[it.course] - 1));
      const tg = it.tags || [];
      if (tg.includes('premium')) w *= d.spend * d.spend;
      if (tg.includes('kid')) w *= d.id === 'family' ? 1.6 : 0.7;
      if (tg.includes('light') && d.id === 'date') w *= 1.2;
      if (tg.includes('comfort') && (d.id === 'family' || d.id === 'friends')) w *= 1.2;
      if (tg.includes('signature')) w *= 1.25;
      if (it.course === 'drink' && vibe) {
        if (vibe === 'wine' && (it.drinkType === 'wine' || it.drinkType === 'sake')) w *= 1.5;
        if (vibe === 'cocktail' && it.drinkType === 'cocktail') w *= 1.5;
        if (vibe === 'beer' && it.drinkType === 'beer') w *= 1.7;
      }
      if (it.drinkType === 'wine' || it.drinkType === 'sake') w *= 0.6 + cui.wineAffinity;
      // A pushed item only moves if somebody at the table is actually talking to the guests.
      if (RS.playFor(cfg, it.id, 'push')) w *= 1 + 1.6 * touch * (0.6 + 0.6 * exp);
      const dc = RS.playFor(cfg, it.id, 'discount'); if (dc) w *= 1 + (dc.pct || 20) / 100 * 3.5;
      if (RS.playFor(cfg, it.id, 'bogo') && party.size >= 2) w *= 1.7;
      if (RS.playFor(cfg, it.id, 'special')) w *= 1.5 + 0.6 * touch;
      return w;
    };
    const addLine = (party, it, diner, free) => {
      const price = free ? 0 : RS.itemPrice(cfg, it), cost = RS.itemCost(cfg, it);
      const line = { item: it, price, cost, course: it.course, diner, free: !!free };
      party.lines.push(line); party.check += price;
      const s = st.items[it.id]; s.qty++; s.rev += price; s.cost += cost; if (free) s.free++;
      st.revenue += price; st.cogs += cost; if (it.course === 'drink') st.bevRev += price; else st.foodRev += price;
      const full = it.price * RS.priceMult(cfg) * (RS.playFor(cfg, it.id, 'special') ? 1.1 : 1);
      if (price < full - 0.01) st.discounts += full - price;
      return line;
    };
    const pickDrink = (party, alc) => { const l = byCourse('drink').filter((i) => alc ? i.drinkType !== 'na' : i.drinkType === 'na'); return l.length ? rnd.weighted(l, (i) => weight(i, party)) : null; };
    const pAlc = (party) => RS.clamp((0.3 + 0.55 * alcFocus) * party.demo.alc * (vibe === 'cocktail' || vibe === 'wine' ? 1.08 : 1), 0, 0.95);

    const takeOrder = (party) => {
      const d = party.demo, upsell = touch * (0.6 + 0.6 * exp);
      const kids = d.id === 'family' ? Math.max(0, party.size - 2) : 0;
      const picks = [];
      for (let i = 0; i < party.size; i++) {
        const kid = i >= party.size - kids;
        if (!kid && rnd() < pAlc(party)) { const it = pickDrink(party, true); if (it) { picks.push([it, i]); party.drinkers.push(i); } }
        else if (rnd() < (D.water ? 0.12 : 0.38)) { const it = pickDrink(party, false); if (it) picks.push([it, i]); }
        if (byCourse('starter').length && rnd() < RS.clamp(cui.starterRate * (0.55 + 0.5 * A.formality + 0.35 * upsell) * d.spend * (kid ? 0.4 : 1), 0, 0.95)) picks.push([rnd.weighted(byCourse('starter'), (x) => weight(x, party)), i]);
        if (byCourse('main').length) picks.push([rnd.weighted(byCourse('main'), (x) => weight(x, party)), i]);
        if (byCourse('side').length && rnd() < RS.clamp(cui.sideRate * (0.7 + 0.5 * upsell), 0, 0.9)) picks.push([rnd.weighted(byCourse('side'), (x) => weight(x, party)), i]);
      }
      // 1+1: someone else at the table usually takes the free one.
      cfg.plays.filter((p) => p.type === 'bogo').forEach((p) => {
        const it = menu.find((m) => m.id === p.itemId); if (!it) return;
        const n = picks.filter((x) => x[0] === it).length;
        if (n % 2 === 1 && rnd() < 0.6) { const other = picks.find((x) => x[0] !== it && x[0].course === it.course); if (other) other[0] = it; }
      });
      const seen = {};
      picks.forEach(([it, diner]) => {
        let free = false;
        if (RS.playFor(cfg, it.id, 'bogo')) { seen[it.id] = (seen[it.id] || 0) + 1; free = seen[it.id] % 2 === 0; }
        addLine(party, it, diner, free);
      });
    };

    /* ---------- kitchen ---------- */
    const fire = (party, course) => {
      const lines = party.lines.filter((l) => !l.fired && l.course !== 'drink' && (course === 'main' ? (l.course === 'main' || l.course === 'side') : l.course === course));
      if (!lines.length) return false;
      lines.forEach((l) => { l.fired = true; });
      sim.tickets.push({ party, course, fired: sim.t, ready: false,
        items: lines.map((l) => ({ it: l.item, state: 'queued', remain: 0 })) });
      return true;
    };
    const stationOf = (it) => (sim.stations[it.station] ? it.station : (it.station === 'bar' ? 'cold' : it.station));
    const stepKitchen = (dt) => {
      const cookCap = sim.cooks * 3;
      Object.values(sim.stations).forEach((s) => { s.queued = 0; });
      for (const tk of sim.tickets) {
        if (tk.ready) continue;
        let allDone = true;
        for (const x of tk.items) {
          if (x.state === 'queued') {
            const batch = x.it.prep === 'batch', sname = stationOf(x.it), sn = sim.stations[sname];
            if (sim.cookActive >= cookCap) { st.cookWait += dt; if (sn && !batch) sn.queued++; }
            else if (batch || !sn) { x.state = 'cooking'; x.remain = Math.max(1, x.it.cookMin) + 0.8; x.sn = null; sim.cookActive++; }
            else if (sn.active < sn.cap) { x.state = 'cooking'; x.remain = (x.it.cookMin * rnd.range(0.85, 1.25) + 1) * (1.15 - 0.3 * exp); x.sn = sn; x.sname = sname; sn.active++; sim.cookActive++; }
            else { st.stationWait[sname] += dt; sn.queued++; }
          }
          if (x.state === 'cooking') {
            x.remain -= dt; if (x.sn) st.stationBusy[x.sname] += dt;
            if (x.remain <= 0) { x.state = 'done'; sim.cookActive--; if (x.sn) x.sn.active--; }
          }
          if (x.state !== 'done') allDone = false;
        }
        if (allDone) {
          tk.ready = true; tk.readyAt = sim.t;
          const tt = sim.t - tk.fired; st.ticketTimes.push({ course: tk.course, min: tt });
          if (tt > (tk.course === 'main' ? 20 : 13)) { st.lateTickets++; if (tt > 28) say('Table ' + (tk.party.table.id + 1) + ' waited ' + Math.round(tt) + ' min on ' + tk.course + 's', 'bad'); }
          runFood(tk);
        }
      }
      sim.tickets = sim.tickets.filter((tk) => !tk.delivered);
    };
    const runFood = (tk) => {
      const p = tk.party;
      if (tk.course === 'main' && p.eatUntil > sim.t) { p.heldTicket = tk; return; } // hold on the pass until starters are cleared
      tableTask(p.table, { type: 'food', pickup: p.table.bar ? null : G.pass, dwell: 1 + 0.15 * p.size, onDone: () => { tk.delivered = true; delivered(p, tk.course); p.checkBackAt = sim.t + 3; } });
    };

    /* ---------- the guest journey ---------- */
    const delivered = (p, course) => {
      const lingerK = Math.sqrt(p.demo.linger);
      if (course === 'starter') {
        p.waits.starter = sim.t - p.orderedAt; p.state = 'eating'; p.eatUntil = sim.t + (9 + 5 * pace) * lingerK; p.next = 'waitMain';
        p.fireMainAt = sim.t + 3 + 5 * pace;
      } else if (course === 'main') {
        p.waits.main = sim.t - Math.max(p.orderedAt, p.starterDone || 0); p.hadStarter = !!p.starterDone;
        p.state = 'eating'; p.eatUntil = sim.t + (17 + 12 * pace) * lingerK; p.next = 'clear';
        // A second round happens when someone is paying attention to the table.
        p.drinkers.forEach((i) => { if (rnd() < RS.clamp(0.2 + 0.4 * touch + 0.25 * (p.demo.linger - 1) + 0.2 * (alcFocus - 0.5), 0, 0.9)) { const it = pickDrink(p, true); if (it) addLine(p, it, i); } });
      } else { p.state = 'eating'; p.eatUntil = sim.t + (9 + 5 * pace) * lingerK; p.next = 'check'; }
    };
    const askCheck = (p) => { p.state = 'waitCheck'; p.checkAsked = sim.t; tableTask(p.table, { type: 'check', dwell: 2.5, onDone: () => dropCheck(p) }); };
    const dropCheck = (p) => { p.waits.check = sim.t - (p.checkAsked || sim.t); p.state = 'paying'; p.leaveAt = sim.t + 3 + 7 * pace * p.demo.linger; };
    const stepParty = (p, dt) => {
      if (p.target) { if (move(p, p.target, 18, dt)) { p.target = null; if (p.onArrive) { const f = p.onArrive; p.onArrive = null; f(); } } return; }
      if (p.state === 'waiting') {
        if (G.bar && !p.barDrinks && sim.t - p.arrivedAt > 2) {
          p.barDrinks = true;
          for (let i = 0; i < p.size; i++) if (rnd() < pAlc(p) * 0.55) { const it = pickDrink(p, true); if (it) { addLine(p, it, i); st.barWaitDrinks++; } }
        }
        if (sim.t - p.arrivedAt > p.patience) walkOut(p);
      } else if (p.state === 'eating' && sim.t >= p.eatUntil) {
        if (p.next === 'waitMain') { p.starterDone = sim.t; p.state = 'waitFood'; if (p.heldTicket) { const tk = p.heldTicket; p.heldTicket = null; runFood(tk); } }
        else if (p.next === 'clear') {
          p.state = 'waitClear';
          tableTask(p.table, { type: 'clear', dwell: 1 + touch, onDone: () => {
            const pd = RS.clamp(cui.dessertRate * (0.55 + 0.7 * touch * (0.6 + 0.6 * exp)) * p.demo.spend * (0.7 + 0.6 * pace) * ((p.waits.main || 0) > 30 ? 0.5 : 1), 0, 0.9);
            let any = false;
            if (byCourse('dessert').length) for (let i = 0; i < p.size; i++) if (rnd() < pd) { addLine(p, rnd.weighted(byCourse('dessert'), (x) => weight(x, p)), i); any = true; }
            if (D.occasion && p.demo.id === 'celebration' && byCourse('dessert').length) { st.comps += 4; any = true; const it = byCourse('dessert')[0]; addLine(p, it, 0, true); }
            if (any && fire(p, 'dessert')) p.state = 'waitFood'; else dropCheck(p);
          } });
        } else askCheck(p);
      } else if (p.fireMainAt && sim.t >= p.fireMainAt) { p.fireMainAt = 0; fire(p, 'main'); }
      else if (p.state === 'paying' && sim.t >= p.leaveAt) leave(p);
    };
    const satisfaction = (p) => {
      const d = p.demo; let s = 76;
      ['light', 'noise', 'formality', 'spacing'].forEach((k) => { s += d.likes[k] * (A[k] - 0.5) * 9; });
      s += d.likes.touch * (touch - 0.5) * 8;
      s -= 0.9 * Math.max(0, p.waits.seat - 5);
      s -= 1.6 * Math.max(0, (p.waits.greet || 0) - 3) * (0.7 + 0.6 * priceT);
      s -= 1.0 * Math.max(0, (p.waits.starter || 0) - 14);
      s -= 1.0 * Math.max(0, (p.waits.main || 0) - (p.hadStarter ? 12 : 23));
      s -= 0.8 * Math.max(0, (p.waits.check || 0) - 5);
      s += (exp - 0.5) * 8 + (sourcing - 0.5) * 5;
      s -= overprice * 28;
      s -= Math.abs(style - A.formality) * 8;
      if (p.ownerVisited) s += 3;
      RS.DELIGHTERS.forEach((x) => {
        if (!D[x.id]) return;
        s += x.sat + (x.fancyBonus || 0) * A.formality;
        if (x.regularBonus && d.id === 'solo') s += x.regularBonus;
        if (x.celebrationBonus && d.id === 'celebration') s += x.celebrationBonus;
      });
      return RS.clamp(s + rnd.range(-5, 5), 0, 100);
    };
    const exit = (p) => { p.state = 'leaving'; p.target = { x: G.entrance.x, y: G.entrance.y }; p.onArrive = () => { sim.parties.splice(sim.parties.indexOf(p), 1); sim.gone.push(p); }; };
    const leave = (p) => {
      p.sat = satisfaction(p); st.sats.push(p.sat);
      st.tips += p.check * RS.clamp(0.18 + (p.sat - 76) * 0.003 + (D.sweets ? 0.01 : 0), 0.08, 0.28);
      const t = p.table; t.party = null; t.state = 'dirty'; t.lastParty = p;
      const bus = { type: 'bus', table: t, dest: { x: t.cx, y: t.cy + (t.h || 0) / 2 + 0.5 }, dwell: t.bar ? 1 : 3 + 2.5 * A.formality, onDone: () => { t.state = 'empty'; } };
      if (t.bar) addTask(t.server, bus); else addTask(null, bus);
      exit(p);
    };
    const walkOut = (p) => {
      st.walkouts += p.size; st.walkoutParties++; p.walked = true; p.sat = 35;
      say('Party of ' + p.size + ' (' + p.demo.label.toLowerCase() + ') gave up after ' + Math.round(sim.t - p.arrivedAt) + ' min waiting', 'bad');
      exit(p);
    };

    const arrive = (a) => {
      st.arrivals += a.size;
      if (a.size > maxTable + (maxTable >= 4 ? 1 : 0)) { st.turnedAway += a.size; say('Turned away a party of ' + a.size + ': no table that big', 'bad'); return; }
      const p = { id: a.id, demo: a.demo, size: a.size, x: G.entrance.x, y: G.entrance.y, state: 'walkin', arrivedAt: sim.t, lines: [], check: 0, drinkers: [], waits: {}, eatUntil: 0,
        patience: (18 + 18 * rnd()) * a.demo.patience * (G.bar ? 1.5 : 1), barOk: a.size <= 2 && (a.demo.id === 'solo' || rnd() < 0.3) };
      sim.parties.push(p);
      st.demos[a.demo.id] = (st.demos[a.demo.id] || 0) + a.size;
      const q = sim.parties.filter((x) => x.state === 'waiting' || x.state === 'walkin').length - 1;
      p.target = G.waitSpot(q); p.onArrive = () => { p.state = 'waiting'; };
    };
    const seatParties = () => {
      const hi = hostFreeAt.findIndex((f) => f <= sim.t); if (hi < 0) return;
      for (const p of sim.parties) {
        if (p.state !== 'waiting') continue;
        let best = null;
        for (const t of sim.tables) {
          if (t.state !== 'empty' || t.seats + (t.seats >= 4 && !t.bar ? 1 : 0) < p.size) continue;
          if (t.bar && !p.barOk) continue;
          const score = (t.seats - p.size) * 10 + (t.bar ? (p.demo.id === 'solo' ? -5 : 5) : 0) + rnd();
          if (!best || score < best.score) best = { t, score };
        }
        if (!best) continue;
        const t = best.t; t.state = 'taken'; t.party = p; t.turns++; p.table = t;
        p.waits.seat = sim.t - p.arrivedAt; st.seatWait.push(p.waits.seat);
        st.partiesSeated++; st.covers += p.size; st.seatsOffered += t.seats; st.seatsUsed += Math.min(p.size, t.seats);
        hostFreeAt[hi] = sim.t + seatTime;
        if (hosts[hi]) addTask(hosts[hi], { type: 'visit', dest: { x: t.cx, y: t.cy + (t.h || 0) / 2 + 0.6 }, dwell: 0.3 });
        p.state = 'toTable'; p.target = { x: t.cx, y: t.cy };
        p.onArrive = () => {
          p.state = 'seated'; p.seatedAt = sim.t;
          if (!t.bar) addTask(null, { type: 'bus', table: t, dest: { x: t.cx, y: t.cy - 0.6 }, dwell: 0.8 + (D.bread ? 0.5 : 0) });
          tableTask(t, { type: 'order', dwell: 2.2 + 3.5 * touch + 0.2 * p.size, onStart: () => { p.waits.greet = sim.t - p.seatedAt; st.greetWait.push(p.waits.greet); },
            onDone: () => {
              takeOrder(p); p.orderedAt = sim.t; p.state = 'waitFood';
              const drinks = p.lines.filter((l) => l.course === 'drink' && !l.served);
              if (drinks.length) {
                drinks.forEach((l) => { l.served = true; });
                const pend = sim.pendingDrinks = (sim.pendingDrinks || 0) + 1;
                const ready = sim.t + 1.5 + 0.6 * pend / Math.max(0.6, tenders.length || 0.6);
                p.drinksAt = ready;
              }
              if (!fire(p, 'starter')) fire(p, 'main');
            } });
        };
        return; // one seating per host per tick
      }
    };

    /* ---------- main loop ---------- */
    sim.step = (dt) => {
      if (sim.done) return;
      sim.t += dt;
      while (nextArrival < arrivals.length && arrivals[nextArrival].at <= sim.t) arrive(arrivals[nextArrival++]);
      seatParties();
      for (const p of sim.parties.slice()) {
        stepParty(p, dt);
        if (p.checkBackAt && sim.t >= p.checkBackAt && p.table && p.state === 'eating') { p.checkBackAt = 0; tableTask(p.table, { type: 'visit', dwell: 0.5 + 1.6 * touch }); }
        if (p.drinksAt && sim.t >= p.drinksAt && p.table) { p.drinksAt = 0; sim.pendingDrinks--; tableTask(p.table, { type: 'drinks', pickup: p.table.bar ? null : (G.bar ? G.bar.pickup : G.pass), dwell: 0.4 }); }
      }
      stepKitchen(dt);
      sim.agents.forEach((a) => stepAgent(a, dt));
      if (sim.t >= HARD_CLOSE) sim.parties.slice().forEach((p) => { if (p.table && p.state !== 'leaving') leave(p); else if (p.state !== 'leaving') exit(p); });
      const quiet = nextArrival >= arrivals.length && !sim.parties.length && sim.tables.every((t) => t.state === 'empty');
      if ((sim.t > LAST_SEATING && quiet) || sim.t >= HARD_CLOSE + 10) { sim.done = true; sim.shift = sim.t; }
    };
    sim.staffLists = { servers, bussers, hosts, tenders };

    /* ---------- the night's books ---------- */
    sim.results = () => {
      const s = st, avg = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
      const wm = RS.lerp(0.9, 1.35, exp), area = cfg.room.w * cfg.room.h;
      const prepMin = menu.reduce((x, i) => x + (i.prepMin || 0), 0) + RS.DELIGHTERS.reduce((x, d) => x + (D[d.id] ? d.prepMin : 0), 0);
      const labor = {
        'Servers': cfg.staff.servers * 7 * 11 * wm, 'Bussers and runners': cfg.staff.bussers * 7 * 16 * wm, 'Host': cfg.staff.hosts * 6.5 * 17 * wm,
        'Bartender': (G.bar ? cfg.staff.bartenders : 0) * 7.5 * 13 * wm, 'Line cooks': cfg.staff.cooks * 8 * 25 * wm,
        'Dishwasher': (seats > 90 ? 2 : 1) * 8 * 17, 'Pre-shift prep': prepMin / 60 * 22, 'Floor manager': cfg.owner.presence > 60 ? 0 : 260
      };
      labor['Payroll tax and benefits'] = Object.values(labor).reduce((x, y) => x + y, 0) * 0.16;
      const laborTotal = Object.values(labor).reduce((x, y) => x + y, 0);
      const ingr = RS.ingredientCount(cfg);
      const batchCogs = menu.filter((i) => i.prep === 'batch').reduce((x, i) => x + s.items[i.id].cost, 0);
      const waste = ingr * 2.0 * RS.costMult(cfg) + 0.12 * batchCogs;
      const delight = RS.DELIGHTERS.reduce((x, d) => x + (D[d.id] ? d.perCover * s.covers : 0), 0) + s.comps;
      const occupancy = {
        'Rent': area * RS.lerp(1.0, 3.8, cfg.priceTier / 100) + { compact: 40, standard: 70, large: 120 }[cfg.room.line],
        'Utilities': 40 + 0.3 * area, 'Linen, glassware, supplies': s.covers * (0.5 + 1.2 * A.formality), 'Insurance, marketing, repairs, admin': 160 + s.revenue * 0.035
      };
      const occTotal = Object.values(occupancy).reduce((x, y) => x + y, 0);
      const card = s.revenue * 0.028;
      const profit = s.revenue - s.cogs - waste - delight - laborTotal - occTotal - card;
      const avgSat = avg(s.sats);
      const allSats = s.sats.concat(new Array(s.walkoutParties).fill(45));
      const shift = sim.shift || sim.t;
      const diningTables = sim.tables.filter((t) => !t.bar);
      return {
        day: game.day, dow, dayName: RS.DAYS[dow], revenue: s.revenue, foodRev: s.foodRev, bevRev: s.bevRev, discounts: s.discounts,
        cogs: s.cogs, waste, delight, labor, laborTotal, occupancy, occTotal, card, profit, margin: s.revenue ? profit / s.revenue : 0,
        primeCost: s.revenue ? (s.cogs + waste + laborTotal) / s.revenue : 0, foodCostPct: s.revenue ? (s.cogs + waste) / s.revenue : 0, laborPct: s.revenue ? laborTotal / s.revenue : 0,
        covers: s.covers, parties: s.partiesSeated, demand: s.arrivals, walkouts: s.walkouts, turnedAway: s.turnedAway,
        avgCheck: s.covers ? s.revenue / s.covers : 0, tips: s.tips,
        seatWait: avg(s.seatWait), greetWait: avg(s.greetWait), mainTicket: avg(s.ticketTimes.filter((x) => x.course === 'main').map((x) => x.min)),
        lateTickets: s.lateTickets, tickets: s.ticketTimes.length, sat: avgSat, satAll: avg(allSats),
        items: s.items, ingredients: ingr, stationWait: s.stationWait, stationBusy: s.stationBusy, stationCap: Object.fromEntries(Object.entries(sim.stations).map(([k, v]) => [k, v.cap])), cookWait: s.cookWait,
        serverUtil: avg(servers.map((a) => a.busy / shift)), busserUtil: avg(bussers.map((a) => a.busy / shift)),
        seatFill: s.seatsOffered ? s.seatsUsed / s.seatsOffered : 0, turns: diningTables.length ? avg(diningTables.map((t) => t.turns)) : 0,
        demos: s.demos, seats, shift, barWaitDrinks: s.barWaitDrinks,
        reputationNext: RS.clamp(game.reputation + ((avg(allSats) || 70) - 70) / 30 * 0.08 - (s.arrivals ? (s.walkouts + s.turnedAway) / s.arrivals : 0) * 0.04, 0.1, 1)
      };
    };
    return sim;
  };
})();
