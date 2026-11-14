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
    const quality = A.formality * 0.3 + RS.clamp(sourcing + 0.3 * RS.buyQuality(cfg), 0, 1.1) * 0.35 + exp * 0.35;
    const overprice = Math.max(0, priceT - quality - 0.12);
    const dow = game.day % 7, OW = RS.ownerEff(cfg);
    const portion = cfg.menu.portion / 100, nowX = RS.expectNow(cfg), EX = game.expect || nowX;
    // Cuts below what regulars are used to. Fades as expectations drift down to the new normal.
    const drop = { quality: Math.max(0, EX.sourcing - nowX.sourcing) * 0.14, portion: Math.max(0, EX.portion - nowX.portion) * 0.14, price: Math.max(0, nowX.priceAdj - EX.priceAdj) * 0.45, delight: Math.max(0, EX.delight - nowX.delight) * 2.5 };
    const G_ = { wait: 0, kitchen: 0, price: 0, quality: 0, portion: 0, room: 0, extras: 0 }, P_ = { food: 0, service: 0, room: 0, extras: 0, portion: 0 };
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
    menu.forEach((i) => { st.items[i.id] = { qty: 0, rev: 0, cost: 0, free: 0, pos: 0, neg: 0, photos: 0 }; });
    Object.assign(st, { joins: 0, walkEmpty: 0, walkEmptyParties: 0, idleSmallMin: 0, reviews: 0, reviewStars: 0, dMention: {}, dMood: {}, hh: { parties: 0, covers: 0, rev: 0, cogs: 0, discount: 0, leak: 0, stayed: 0, overstay: 0 } });
    const HH = RS.HH_TYPES.find((x) => x.id === (cfg.happyHour || {}).type) || RS.HH_TYPES[0], itemQ = {};
    menu.forEach((i) => { itemQ[i.id] = RS.itemBuy(cfg, i).q; });
    Object.keys(RS.STATION_CAP).forEach((s) => {
      if (menu.some((i) => i.station === s && i.course !== 'drink' && i.prep !== 'batch')) { sim.stations[s] = { cap: Math.max(1, Math.round(RS.STATION_CAP[s] * lineMult)), active: 0, queued: 0 }; st.stationWait[s] = 0; st.stationBusy[s] = 0; }
    });
    // The line: one cook per station first, extras double up. The first one runs the pass.
    const stNames = Object.keys(sim.stations);
    sim.cookList = [];
    for (let i = 0; i < cfg.staff.cooks; i++) {
      const station = stNames.length ? stNames[i % stNames.length] : null, si = stNames.indexOf(station);
      const r = station ? RS.stationRect(cfg.room, stNames.length, si) : { x: 1, y: -2, w: 1, h: 1 };
      sim.cookList.push(Object.assign({ id: 'cook' + i, role: 'cook', station, plates: 0, x: r.x + 0.45 + Math.floor(i / Math.max(1, stNames.length)) * 0.6, y: r.y + r.h + 0.5 }, RS.persona('cook', i, cfg, { station, lead: i === 0 })));
    }
    let cookTurn = 0;
    const credit = (sname) => { const own = sim.cookList.filter((c) => c.station === sname); const c = own.length ? own[cookTurn++ % own.length] : sim.cookList[cookTurn++ % Math.max(1, sim.cookList.length)]; if (c) c.plates++; };
    const say = (msg, kind) => { sim.log.unshift({ t: sim.t, msg, kind: kind || 'info' }); if (sim.log.length > 60) sim.log.pop(); };

    /* ---------- staff ---------- */
    const mk = (role, i, home) => Object.assign({ id: role + i, role, x: home.x, y: home.y, home, queue: [], cur: null, busy: 0, done: 0, tables: 0, sales: 0, tips: 0 }, RS.persona(role, i, cfg));
    const inRoom = (p) => ({ x: RS.clamp(p.x, 0.5, cfg.room.w - 0.5), y: RS.clamp(p.y, 0.5, cfg.room.h - 0.5) });
    const servers = [], bussers = [], hosts = [], tenders = [];
    for (let i = 0; i < cfg.staff.servers; i++) servers.push(mk('server', i, inRoom({ x: G.pass.x + (i - (cfg.staff.servers - 1) / 2) * 0.7, y: 1.1 })));
    for (let i = 0; i < cfg.staff.bussers; i++) bussers.push(mk('busser', i, inRoom({ x: G.pass.x + (i - (cfg.staff.bussers - 1) / 2) * 0.7, y: 1.9 })));
    for (let i = 0; i < cfg.staff.hosts; i++) hosts.push(mk('host', i, { x: G.host.x + i * 0.6, y: G.host.y }));
    if (G.bar) for (let i = 0; i < cfg.staff.bartenders; i++) tenders.push(mk('bartender', i, { x: G.bar.tender.x + (G.bar.horiz ? i * 0.8 : 0), y: G.bar.tender.y + (G.bar.horiz ? 0 : i * 0.8) }));
    let owner = null;
    if (OW.role === 'floor') { owner = mk('owner', 0, inRoom({ x: G.host.x + 1.2, y: G.host.y })); owner.nextVisit = 12; }
    if (OW.role === 'greeter') hosts.push(mk('owner', 0, inRoom({ x: G.host.x - 0.8, y: G.host.y })));
    if (OW.role === 'chef' || OW.role === 'kitchen') sim.cookList.push(Object.assign({ id: 'owner', role: 'owner', plates: 0, x: RS.clamp(G.kitchenDoor.x - 1.2, 0.5, cfg.room.w - 0.5), y: -0.75 }, RS.persona('owner', 0, cfg)));
    if (OW.role === 'kitchen') sim.cooks += 0.5 + OW.cook;
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
      if (c.remain <= 0) { a.cur = null; a.done++; if (c.onDone) c.onDone(); }
    };

    /* ---------- demand ---------- */
    const seats = RS.seatCount(cfg);
    const deals = cfg.plays.filter((p) => p.type === 'discount' || p.type === 'bogo').length;
    const valueMult = 1 - 0.6 * overprice + 0.15 * Math.max(0, quality - priceT - 0.1);
    const target = (72 + 0.85 * seats) * RS.DOW_DEMAND[dow] * (0.55 + 0.9 * game.reputation) * valueMult * (1 + 0.03 * deals) * (1 + 0.08 * OW.biz) * RS.lerp(1.08, 0.76, cfg.priceTier / 100) * rnd.range(0.92, 1.08);
    st.demandCovers = Math.round(target);
    const maxTable = Math.max(Math.max.apply(null, sim.tables.map((t) => t.seats).concat([0])), sim.tables.filter((t) => !t.bar).map((t) => t.seats).sort((a, b) => b - a).slice(0, 3).reduce((a, b) => a + b, 0) - 1);
    const arrivals = []; let planned = 0, pid = 0;
    const demoW = (d) => RS.demoWeight(d, cfg, !!G.bar);
    while (planned < target) {
      const demo = rnd.weighted(RS.DEMOS, demoW), size = rnd.pick(demo.sizes);
      // Triangular: builds from 5, peaks around 7:30, tails off by last seating.
      const at = RS.clamp(145 + ((rnd() + rnd()) / 2 - 0.5) * 2 * 150, 0, LAST_SEATING);
      arrivals.push({ id: pid++, demo, size, at }); planned += size;
    }
    if (HH.pull) {   // the early crowd a happy hour brings in
      const hhTarget = seats * 0.22 * HH.pull * (1.25 - 0.75 * A.formality) * (G.bar ? 1 : 0.55) * (0.6 + 0.8 * game.reputation) * [1.1, 1.1, 1.15, 1.2, 1.3, 0.8, 0.6][dow];
      const pool = RS.DEMOS.filter((d) => ['friends', 'solo', 'date', 'business'].includes(d.id)), pw = { friends: 3, solo: 2, date: 1.5, business: 2 };
      let got = 0;
      while (got < hhTarget) { const demo = rnd.weighted(pool, (d) => pw[d.id]), size = Math.min(6, rnd.pick(demo.sizes)); arrivals.push({ id: pid++, demo, size, at: rnd.range(0, 78), hh: true }); got += size; }
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
      let price = free ? 0 : RS.itemPrice(cfg, it); const cost = RS.itemCost(cfg, it);
      if (HH.pull && sim.t < RS.HH_END && price > 0) {
        const m = it.course === 'starter' ? HH.starter : (it.course === 'drink' && it.drinkType !== 'na' ? HH.drink : 1);
        if (m < 1) { const off = price * (1 - m); price = Math.round((price - off) * 2) / 2; st.hh.discount += off; if (!party.hh) st.hh.leak += off; }
      }
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
      if (party.hh && !party.stays) {   // here for the deal: drinks, maybe a plate to share
        for (let i = 0; i < party.size; i++) {
          const it = pickDrink(party, rnd() < 0.9); if (it) { addLine(party, it, i); if (it.drinkType !== 'na') party.drinkers.push(i); }
          if (byCourse('starter').length && rnd() < (HH.starter < 1 ? 0.8 : 0.3)) addLine(party, rnd.weighted(byCourse('starter'), (x) => weight(x, party)), i);
        }
        return;
      }
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
            else if (batch || !sn) { x.state = 'cooking'; x.remain = Math.max(1, x.it.cookMin) + 0.8; x.sn = null; sim.cookActive++; credit(null); }
            else if (sn.active < sn.cap) { x.state = 'cooking'; x.remain = (x.it.cookMin * rnd.range(0.85, 1.25) + 1) * (1.15 - 0.3 * exp) * (OW.role === 'kitchen' ? 1 - 0.12 * OW.cook : 1); x.sn = sn; x.sname = sname; sn.active++; sim.cookActive++; credit(sname); }
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
    const secondRound = (p, extra) => p.drinkers.forEach((i) => { if (rnd() < RS.clamp(extra + 0.2 + 0.4 * touch + 0.25 * (p.demo.linger - 1) + 0.2 * (alcFocus - 0.5), 0, 0.9)) { const it = pickDrink(p, true); if (it) addLine(p, it, i); } });
    const delivered = (p, course) => {
      const lingerK = Math.sqrt(p.demo.linger);
      if (course === 'starter') {
        p.waits.starter = sim.t - p.orderedAt; p.state = 'eating';
        if (!p.lines.some((l) => !l.fired && (l.course === 'main' || l.course === 'side'))) { p.eatUntil = sim.t + 26 * lingerK; p.next = 'check'; secondRound(p, 0.3); return; }
        p.eatUntil = sim.t + (9 + 5 * pace) * lingerK; p.next = 'waitMain';
        p.fireMainAt = sim.t + 3 + 5 * pace;
      } else if (course === 'main') {
        p.waits.main = sim.t - Math.max(p.orderedAt, p.starterDone || 0); p.hadStarter = !!p.starterDone;
        p.state = 'eating'; p.eatUntil = sim.t + (17 + 12 * pace) * lingerK; p.next = 'clear';
        // A second round happens when someone is paying attention to the table.
        secondRound(p, 0);
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
      const d = p.demo; let s = 76, fit = 0;
      ['light', 'noise', 'formality', 'spacing'].forEach((k) => { fit += d.likes[k] * (A[k] - 0.5) * 9; });
      fit += d.likes.touch * (touch - 0.5) * 8 - Math.abs(style - A.formality) * 8;
      const wait = 0.9 * Math.max(0, p.waits.seat - 5) + 1.6 * Math.max(0, (p.waits.greet || 0) - 3) * (0.7 + 0.6 * priceT) + 0.8 * Math.max(0, (p.waits.check || 0) - 5);
      const kit = 1.0 * Math.max(0, (p.waits.starter || 0) - 14) + 1.0 * Math.max(0, (p.waits.main || 0) - (p.hadStarter ? 12 : 23));
      const cw = { main: 3, starter: 1.5, dessert: 1, side: 0.7, drink: 1 }; let qw = 0, qs = 0; p.lines.forEach((l) => { qw += cw[l.course]; qs += cw[l.course] * itemQ[l.item.id]; });
      const partyQ = qw ? qs / qw : 0;
      const food = (sourcing - 0.5) * 12 + partyQ * 26 - drop.quality + (OW.role === 'chef' ? (OW.cooking - 0.45) * 12 : 0);
      const port = (portion - 0.5) * 10 - drop.portion;
      const price = overprice * 28 + drop.price + Math.max(0, 0.5 - portion) * priceT * 8;   // small plates at big prices sting twice
      const svc = (exp - 0.5) * 8;
      s += fit - wait - kit + food + port - price + svc - drop.delight;
      G_.wait += wait; G_.kitchen += kit; G_.price += price; G_.quality += Math.max(0, -food); G_.portion += Math.max(0, -port); G_.room += Math.max(0, -fit); G_.extras += drop.delight;
      P_.food += Math.max(0, food); P_.service += Math.max(0, svc) + (p.ownerVisited ? 3 : 0); P_.room += Math.max(0, fit); P_.portion += Math.max(0, port);
      if (p.ownerVisited) s += 2 + 5 * OW.vibeRaw;
      if (OW.role === 'greeter') s += 1 + 4 * OW.vibeRaw;
      if (OW.role === 'kitchen') s += OW.cook * 2;
      if (OW.role === 'handsoff') s -= 2;
      if (HH.pull && !p.hh && p.seatedAt < RS.HH_END) s -= Math.max(0, A.formality - 0.4) * 9 + Math.max(0, 0.5 - A.noise) * 6;   // a happy-hour crowd in a quiet, formal room
      RS.DELIGHTERS.forEach((x) => {
        if (!D[x.id]) return;
        const pts = x.sat + (x.fancyBonus || 0) * A.formality + (x.regularBonus && d.id === 'solo' ? x.regularBonus : 0) + (x.celebrationBonus && d.id === 'celebration' ? x.celebrationBonus : 0);
        s += pts; P_.extras += pts; st.dMood[x.id] = (st.dMood[x.id] || 0) + pts; p.dPts = p.dPts || {}; p.dPts[x.id] = pts;
      });
      return RS.clamp(s + rnd.range(-5, 5), 0, 100);
    };
    const exit = (p) => { p.state = 'leaving'; p.target = { x: G.entrance.x, y: G.entrance.y }; p.onArrive = () => { sim.parties.splice(sim.parties.indexOf(p), 1); sim.gone.push(p); }; };
    const leave = (p) => {
      p.sat = satisfaction(p); st.sats.push(p.sat);
      st.tips += p.check * RS.clamp(0.18 + (p.sat - 76) * 0.003 + (D.sweets ? 0.01 : 0), 0.08, 0.28);
      const t = p.table;
      if (t.server) { t.server.tables++; t.server.sales += p.check; t.server.tips += p.check * RS.clamp(0.18 + (p.sat - 76) * 0.003, 0.08, 0.28); }
      [t].concat(t.joined || []).forEach((x) => {
        x.party = null; x.state = 'dirty'; x.lastParty = p; x.joinedTo = null;
        const bus = { type: 'bus', table: x, dest: { x: x.cx, y: x.cy + (x.h || 0) / 2 + 0.5 }, dwell: x.bar ? 1 : 3 + 2.5 * A.formality, onDone: () => { x.state = 'empty'; } };
        if (x.bar) addTask(x.server, bus); else addTask(null, bus);
      });
      t.joined = null;
      if (p.hh) { const h = st.hh; h.parties++; h.covers += p.size; h.rev += p.check; h.cogs += p.lines.reduce((x, l) => x + l.cost, 0); if (p.stays) h.stayed += p.size; }
      // Photos: some plates get their picture taken whatever the guest thought of the meal.
      const social = { friends: 1.4, date: 1.3, foodie: 1.6, celebration: 1.4, tourists: 1.3, business: 0.35, solo: 0.7, family: 0.8 }[p.demo.id] || 1, shot = {};
      p.lines.forEach((l) => { if (!shot[l.item.id] && rnd() < photoP(l.item) * social) { shot[l.item.id] = 1; st.items[l.item.id].photos++; } });
      // Reviews: a minority write one, the delighted and the furious most of all.
      if (rnd() < 0.13 + Math.abs(p.sat - 72) / 160) {
        st.reviews++; st.reviewStars += RS.clamp(Math.round(1 + (p.sat - 38) / 12), 1, 5);
        Object.keys(p.dPts || {}).forEach((id) => { if (rnd() < RS.clamp(p.dPts[id] / 13, 0, 0.7)) st.dMention[id] = (st.dMention[id] || 0) + 1; });
        const food = p.lines.filter((l) => !l.free);
        if (food.length) {
          const cheap = food.filter((l) => itemQ[l.item.id] < -0.2);
          if (cheap.length && rnd() < 0.65) st.items[rnd.pick(cheap).item.id].neg++;
          else if (p.sat < 58) st.items[rnd.weighted(food, (l) => (l.course === 'main' ? 3 : 1)).item.id].neg++;
          else if (p.sat >= 68) st.items[rnd.weighted(food, (l) => mentionW(l.item)).item.id].pos++;
        }
      }
      exit(p);
    };
    const photoP = (it) => { const tg = it.tags || []; let x = 0.03 + (it.course === 'dessert' ? 0.2 : 0) + (it.drinkType === 'cocktail' ? 0.15 : 0) + (tg.includes('signature') ? 0.2 : 0) + (tg.includes('premium') ? 0.12 : 0) + (tg.includes('shareable') ? 0.08 : 0) + (it.station === 'sushi' ? 0.1 : 0); return x * 0.45 * (1 + Math.min(0, itemQ[it.id])) * (0.75 + 0.5 * portion); };
    const mentionW = (it) => { const tg = it.tags || []; return it.appeal * (tg.includes('signature') ? 2.5 : 1) * (tg.includes('premium') ? 1.6 : 1) * ({ main: 1.3, dessert: 1.2, starter: 1, side: 0.5, drink: it.drinkType === 'cocktail' ? 0.9 : 0.4 }[it.course]) * (1 + itemQ[it.id]); };
    const walkOut = (p) => {
      st.walkouts += p.size; st.walkoutParties++; p.walked = true; p.sat = 35;
      const free = sim.tables.filter((t) => t.state === 'empty' && !t.bar);
      if (free.length) { st.walkEmpty += p.size; st.walkEmptyParties++; }
      say('Party of ' + p.size + ' (' + p.demo.label.toLowerCase() + ') gave up after ' + Math.round(sim.t - p.arrivedAt) + ' min waiting', 'bad');
      exit(p);
    };

    const arrive = (a) => {
      st.arrivals += a.size;
      if (a.size > maxTable + (maxTable >= 4 ? 1 : 0)) { st.turnedAway += a.size; say('Turned away a party of ' + a.size + ': no table that big', 'bad'); return; }
      const stays = a.hh && rnd() < 0.2;
      const p = { id: a.id, demo: a.demo, size: a.size, hh: !!a.hh, stays, reason: a.hh ? (stays ? 'Happy hour, then stayed for dinner' : 'Happy hour') : RS.visitReason(a.demo, game, rnd), x: G.entrance.x, y: G.entrance.y, state: 'walkin', arrivedAt: sim.t, lines: [], check: 0, drinkers: [], waits: {}, eatUntil: 0,
        patience: (18 + 18 * rnd()) * a.demo.patience * (G.bar ? 1.5 : 1) * (OW.role === 'greeter' ? 1 + 0.5 * OW.vibeRaw : 1), barOk: a.size <= 2 && (a.hh || a.demo.id === 'solo' || rnd() < 0.3) };
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
        let group = null;
        if (!best && p.size > 2 && sim.t - p.arrivedAt > 3) {   // nothing fits: push neighbouring tables together
          const free = sim.tables.filter((t) => t.state === 'empty' && !t.bar);
          for (const a of free) {
            const near = free.filter((t) => t !== a && Math.hypot(t.cx - a.cx, t.cy - a.cy) < 3.6).sort((x, y) => Math.hypot(x.cx - a.cx, x.cy - a.cy) - Math.hypot(y.cx - a.cx, y.cy - a.cy));
            const g = [a]; let n = a.seats;
            while (n < p.size && g.length < 3 && near.length) { const t = near.shift(); g.push(t); n += t.seats; }
            if (n >= p.size && (!group || n - p.size < group.n - p.size || (n === group.n && g.length < group.g.length))) group = { g, n };
          }
        }
        if (!best && !group) continue;
        const t = best ? best.t : group.g[0], all = best ? [t] : group.g, cap = all.reduce((x, y) => x + y.seats, 0);
        all.forEach((x) => { x.state = 'taken'; x.party = p; x.turns++; });
        if (group) { t.joined = all.slice(1); t.joined.forEach((x) => { x.joinedTo = t; }); st.joins++; say('Pushed tables ' + all.map((x) => x.id + 1).join(' and ') + ' together for a party of ' + p.size, 'info'); }
        p.table = t;
        p.waits.seat = sim.t - p.arrivedAt; st.seatWait.push(p.waits.seat);
        st.partiesSeated++; st.covers += p.size; st.seatsOffered += cap; st.seatsUsed += Math.min(p.size, cap);
        hostFreeAt[hi] = sim.t + seatTime + (group ? 1.5 : 0);
        if (hosts[hi]) hosts[hi].tables++;
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
              if (!fire(p, 'starter') && !fire(p, 'main')) { p.state = 'eating'; p.eatUntil = sim.t + 30 * Math.sqrt(p.demo.linger); p.next = 'check'; secondRound(p, 0.3); }
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
      if (sim.parties.some((p) => p.state === 'waiting' && p.size >= 3)) st.idleSmallMin += dt * sim.tables.filter((t) => t.state === 'empty' && !t.bar && t.seats === 2).length;
      for (const p of sim.parties.slice()) {
        if (p.hh && !p.stays && p.table && sim.t > RS.HH_END + 10) st.hh.overstay += p.size * dt;
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
      const prepMin = menu.reduce((x, i) => x + (i.prepMin || 0), 0);
      const labor = {
        'Servers': cfg.staff.servers * 7 * 11 * wm, 'Bussers and runners': cfg.staff.bussers * 7 * 16 * wm, 'Host': cfg.staff.hosts * 6.5 * 17 * wm,
        'Bartender': (G.bar ? cfg.staff.bartenders : 0) * 7.5 * 13 * wm, 'Line cooks': cfg.staff.cooks * 8 * 25 * wm,
        'Dishwasher': (seats > 90 ? 2 : 1) * 8 * 17, 'Pre-shift prep': prepMin / 60 * 22
      };
      Object.assign(labor, RS.ownerLabor(cfg));
      labor['Payroll tax and benefits'] = Object.values(labor).reduce((x, y) => x + y, 0) * 0.16;
      const laborTotal = Object.values(labor).reduce((x, y) => x + y, 0);
      const ingr = RS.ingredientCount(cfg);
      const batchCogs = menu.filter((i) => i.prep === 'batch').reduce((x, i) => x + s.items[i.id].cost, 0);
      const waste = (ingr * 2.0 * RS.costMult(cfg) + 0.12 * batchCogs) * (1 - 0.3 * OW.cook);
      const ownerSave = (s.cogs * 0.05 + laborTotal * 0.04) * OW.biz;
      const na = byCourse('drink').filter((i) => i.drinkType === 'na'), naPrice = na.length ? na.reduce((x, i) => x + RS.itemPrice(cfg, i), 0) / na.length : 0;
      const delighters = RS.DELIGHTERS.filter((d) => D[d.id]).map((d) => {
        const cost = d.prepMin / 60 * 22 * 1.16 + d.perCover * s.covers + (d.id === 'occasion' ? s.comps : 0);
        const givesUp = d.id === 'water' ? s.covers * 0.26 * naPrice * 0.85 : 0;
        return { id: d.id, name: d.name, cost, givesUp, mood: (s.dMood[d.id] || 0) / Math.max(1, s.sats.length), mentions: s.dMention[d.id] || 0 };
      });
      const delight = delighters.reduce((x, d) => x + d.cost, 0);
      const hh = Object.assign({ type: HH.id, label: HH.label }, s.hh); hh.net = hh.rev - hh.cogs - hh.rev * 0.063 - hh.leak;
      const occupancy = {
        'Rent': area * RS.lerp(1.0, 5.6, cfg.priceTier / 100) + { compact: 40, standard: 70, large: 120 }[cfg.room.line],
        'Utilities': 40 + 0.3 * area, 'Linen, glassware, supplies': s.covers * (0.5 + 1.2 * A.formality), 'Insurance, marketing, repairs, admin': 160 + s.revenue * 0.035
      };
      const occTotal = Object.values(occupancy).reduce((x, y) => x + y, 0);
      const card = s.revenue * 0.028;
      const profit = s.revenue - s.cogs - waste - delight - laborTotal - occTotal - card + ownerSave;
      const avgSat = avg(s.sats);
      const allSats = s.sats.concat(new Array(s.walkoutParties).fill(45));
      const shift = sim.shift || sim.t;
      const diningTables = sim.tables.filter((t) => !t.bar);
      return {
        day: game.day, dow, dayName: RS.DAYS[dow], revenue: s.revenue, foodRev: s.foodRev, bevRev: s.bevRev, discounts: s.discounts,
        cogs: s.cogs, waste, delight, delighters, hh, joins: s.joins, walkEmpty: s.walkEmpty, idleSmallMin: s.idleSmallMin, reviews: s.reviews, reviewStars: s.reviews ? s.reviewStars / s.reviews : 0, ownerSave, labor, laborTotal, occupancy, occTotal, card, profit, margin: s.revenue ? profit / s.revenue : 0,
        primeCost: s.revenue ? (s.cogs + waste + laborTotal) / s.revenue : 0, foodCostPct: s.revenue ? (s.cogs + waste) / s.revenue : 0, laborPct: s.revenue ? laborTotal / s.revenue : 0,
        covers: s.covers, parties: s.partiesSeated, demand: s.arrivals, walkouts: s.walkouts, turnedAway: s.turnedAway,
        avgCheck: s.covers ? s.revenue / s.covers : 0, tips: s.tips,
        seatWait: avg(s.seatWait), greetWait: avg(s.greetWait), mainTicket: avg(s.ticketTimes.filter((x) => x.course === 'main').map((x) => x.min)),
        lateTickets: s.lateTickets, tickets: s.ticketTimes.length, sat: avgSat, satAll: avg(allSats),
        items: s.items, ingredients: ingr, stationWait: s.stationWait, stationBusy: s.stationBusy, stationCap: Object.fromEntries(Object.entries(sim.stations).map(([k, v]) => [k, v.cap])), cookWait: s.cookWait,
        serverUtil: avg(servers.map((a) => a.busy / shift)), busserUtil: avg(bussers.map((a) => a.busy / shift)),
        seatFill: s.seatsOffered ? s.seatsUsed / s.seatsOffered : 0, turns: diningTables.length ? avg(diningTables.map((t) => t.turns)) : 0,
        demos: s.demos, seats, shift, drop, snap: nowX, stars: RS.stars(game.reputation),
        gripes: Object.fromEntries(Object.entries(G_).map(([k, v]) => [k, v / Math.max(1, s.sats.length)])), praise: Object.fromEntries(Object.entries(P_).map(([k, v]) => [k, v / Math.max(1, s.sats.length)])), barWaitDrinks: s.barWaitDrinks,
        get starsNext() { return RS.stars(this.reputationNext); },
        reputationNext: RS.clamp(game.reputation + RS.clamp(((avg(allSats) || 73) - 73) / 30 * 0.11, -0.035, 0.03) - (s.arrivals ? (s.walkouts + s.turnedAway) / s.arrivals : 0) * 0.04, 0.1, 1)
      };
    };
    return sim;
  };
})();
