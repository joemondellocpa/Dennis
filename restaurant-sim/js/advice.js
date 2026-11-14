/* The advice layer. Reads one night's results and says what to change, in dollars, without
   touching anything the owner has locked as non-negotiable. Each note can carry a one-click fix. */
(function () {
  const RS = window.RS;

  RS.advise = (game, r) => {
    const cfg = game.cfg, out = [], good = [];
    const locked = (p) => !!cfg.locks[p];
    const touch = cfg.diner.touch / 100;
    const menu = RS.activeItems(cfg);
    const rows = menu.map((it) => {
      const s = r.items[it.id] || { qty: 0, rev: 0, cost: 0 }, price = RS.itemPrice(cfg, it), cost = RS.itemCost(cfg, it);
      return { it, qty: s.qty, rev: s.rev, price, cost, cm: price - cost, cmPct: price ? (price - cost) / price : 0 };
    });
    const food = rows.filter((x) => x.it.course !== 'drink');
    const add = (o) => out.push(o);
    const wm = RS.lerp(0.9, 1.35, cfg.staff.experience / 100);

    // 1. Guests drifting to the low-margin plates.
    ['main', 'starter'].forEach((course) => {
      const l = rows.filter((x) => x.it.course === course && x.qty >= 0); if (l.length < 3) return;
      const total = l.reduce((a, x) => a + x.qty, 0); if (total < 12) return;
      const top = l.slice().sort((a, b) => b.qty - a.qty)[0];
      const best = l.filter((x) => x !== top && !RS.playFor(cfg, x.it.id, 'push')).sort((a, b) => b.cm - a.cm)[0];
      if (!best || best.cm - top.cm < 3 || top.qty < best.qty * 1.3) return;
      const shift = Math.round(top.qty / 3), val = shift * (best.cm - top.cm);
      add({ tag: 'Menu mix', value: val, title: 'Guests went for ' + top.it.name + '. ' + best.it.name + ' earns more.',
        body: top.it.name + ' sold ' + top.qty + ' at ' + RS.money(top.cm) + ' contribution each. ' + best.it.name + ' sold ' + best.qty + ' and keeps ' + RS.money(best.cm) + '. Moving a third of those orders across is worth about ' + RS.money(val) + ' a night.' +
          (touch < 0.35 ? ' Your service is light touch, so a server recommendation will not carry far. Run it as the special instead.' : ' Have servers lead with it.'),
        action: { label: touch < 0.35 ? 'Make ' + best.it.name + ' the special' : 'Push ' + best.it.name, apply: (c) => { c.plays = c.plays.filter((p) => p.itemId !== best.it.id); c.plays.push({ type: touch < 0.35 ? 'special' : 'push', itemId: best.it.id }); } } });
    });

    // 2. Slow sellers that tie up inventory.
    if (r.covers > 30) {
      const dogs = food.filter((x) => x.qty <= Math.max(1, r.covers * 0.02) && cfg.menu.enabled[x.it.id]);
      const keep = (c) => food.filter((x) => x.it.course === c && !dogs.includes(x)).length;
      const cut = dogs.filter((x) => keep(x.it.course) >= 2).slice(0, 4);
      if (cut.length) {
        const used = {}; menu.forEach((m) => { if (!cut.some((d) => d.it === m)) m.ingredients.forEach((g) => { used[g] = 1; }); });
        const uniq = new Set(); cut.forEach((d) => d.it.ingredients.forEach((g) => { if (!used[g]) uniq.add(g); }));
        const prep = cut.reduce((a, d) => a + (d.it.prepMin || 0), 0), val = uniq.size * 2 * RS.costMult(cfg) + prep / 60 * 22;
        add({ tag: 'Inventory', value: val, title: 'Cut ' + cut.map((d) => d.it.name).join(', '),
          body: 'Together they sold ' + cut.reduce((a, d) => a + d.qty, 0) + ' plates, yet they keep ' + uniq.size + ' inventory lines on the shelf that nothing else uses and need ' + prep + ' minutes of prep before doors. Dropping them saves roughly ' + RS.money(val) + ' a night in spoilage and labor, and the walk-in gets simpler.',
          action: { label: 'Take them off the menu', apply: (c) => cut.forEach((d) => { c.menu.enabled[d.it.id] = false; c.plays = c.plays.filter((p) => p.itemId !== d.it.id); }) } });
      }
    }

    // 3. Kitchen bottleneck.
    const stWait = Object.entries(r.stationWait).sort((a, b) => b[1] - a[1])[0];
    if (r.lateTickets >= 5 && r.cookWait > 60 && (!stWait || r.cookWait > stWait[1])) {
      add({ tag: 'Kitchen', value: r.lateTickets * 5, title: 'The line ran out of hands', body: r.lateTickets + ' of ' + r.tickets + ' tickets ran late and mains averaged ' + r.mainTicket.toFixed(0) + ' minutes. Stations had room; cooks did not. One more cook costs about ' + RS.money(8 * 25 * wm) + ', or swap two cooked-to-order mains for batch dishes that only need plating.',
        action: { label: 'Add a line cook', apply: (c) => { c.staff.cooks++; } } });
    } else if (r.lateTickets >= 5 && stWait && stWait[1] > 45) {
      const name = stWait[0], onIt = food.filter((x) => x.it.station === name && x.it.prep !== 'batch').sort((a, b) => a.cm * a.qty - b.cm * b.qty);
      add({ tag: 'Kitchen', value: r.lateTickets * 5, title: RS.STATION_LABEL[name] + ' was the bottleneck',
        body: 'Orders queued ' + Math.round(stWait[1]) + ' plate-minutes waiting for space on ' + RS.STATION_LABEL[name].toLowerCase() + ' (' + r.stationCap[name] + ' at a time). ' + r.lateTickets + ' tickets ran late. ' + onIt.length + ' dishes compete for it.' +
          (onIt.length > 2 ? ' ' + onIt[0].it.name + ' earns the least for the space it takes.' : '') + ' A bigger line fixes it with rent; a menu that leans on other stations fixes it for free.',
        action: onIt.length > 2 ? { label: 'Drop ' + onIt[0].it.name, apply: (c) => { c.menu.enabled[onIt[0].it.id] = false; } } : { label: 'Build a larger line', apply: (c) => { c.room.line = 'large'; } } });
    }

    // 4. Guests lost at the door.
    if (r.walkouts > 0) {
      const val = r.walkouts * r.avgCheck * 0.6;
      let body = r.walkouts + ' guests gave up waiting, about ' + RS.money(r.walkouts * r.avgCheck) + ' in sales. ';
      let action = null;
      if (r.seatFill < 0.78) {
        body += 'Only ' + RS.pct(r.seatFill) + ' of the chairs at occupied tables had someone in them: couples were sitting at four-tops. Trading two 4-tops for four 2-tops seats the same room more fully.';
        if ((cfg.tables[4] || 0) >= 2) action = { label: 'Swap two 4-tops for four 2-tops', apply: (c) => { c.tables[4] -= 2; c.tables[2] = (c.tables[2] || 0) + 4; c.manualLayout = null; } };
      } else if (locked('atmosphere.spacing') || locked('diner.pace')) {
        body += 'The room was full. You have marked spacing or pacing as non-negotiable, so the room stays as it is. The money is in the wait itself: ' + (cfg.room.bar.on ? 'a host who walks waiting parties to the bar turns the queue into drink sales.' : 'a small bar would hold those guests and sell them a drink.');
      } else {
        body += 'The room was full, so this is about turns. Tables averaged ' + r.turns.toFixed(1) + ' seatings. A slightly quicker pace or a tighter floor plan adds covers on busy nights.';
        action = { label: 'Quicken the pace a notch', apply: (c) => { c.diner.pace = Math.max(0, c.diner.pace - 12); } };
      }
      add({ tag: 'Capacity', value: val, title: r.walkouts + ' guests walked out of the queue', body, action });
    }
    if (r.turnedAway > 0) add({ tag: 'Capacity', value: r.turnedAway * r.avgCheck * 0.6, title: 'No table for ' + r.turnedAway + ' guests in large parties', body: 'Big groups arrived and nothing could seat them. Large parties spend more per head on drinks. One 8-top, or two 4-tops kept adjacent, catches them.',
      action: { label: 'Add an 8-top', apply: (c) => { c.tables[8] = (c.tables[8] || 0) + 1; c.manualLayout = null; } } });

    // 5. Floor staffing.
    if (r.serverUtil < 0.3 && cfg.staff.servers > 2 && r.greetWait < 3) add({ tag: 'Labor', value: 7 * 11 * wm, title: 'One server too many for a ' + r.dayName, body: 'Servers were on a task ' + RS.pct(r.serverUtil) + ' of the shift and tables were greeted in ' + r.greetWait.toFixed(1) + ' minutes. Cutting one saves ' + RS.money(7 * 11 * wm) + ' in wages and gives the rest better tips.' + (locked('diner.touch') ? ' Your hands-on service standard still holds at this level.' : ''),
      action: { label: 'Schedule one fewer server', apply: (c) => { c.staff.servers--; } } });
    if (r.greetWait > 5 || r.serverUtil > 0.8) add({ tag: 'Service', value: r.covers * 1.2, title: 'Tables waited ' + r.greetWait.toFixed(1) + ' minutes for a first hello', body: 'Servers were busy ' + RS.pct(r.serverUtil) + ' of the night. Late greetings cost drink orders and set the mood for the whole meal.' + (touch > 0.65 ? ' Hands-on service takes longer per table, so it needs smaller sections.' : ''),
      action: { label: 'Add a server', apply: (c) => { c.staff.servers++; } } });
    if (r.busserUtil < 0.15 && cfg.staff.bussers > 1) add({ tag: 'Labor', value: 7 * 16 * wm, title: 'Bussers stood around', body: 'Busy only ' + RS.pct(r.busserUtil) + ' of the shift. One fewer saves ' + RS.money(7 * 16 * wm) + '.', action: { label: 'Schedule one fewer busser', apply: (c) => { c.staff.bussers--; } } });
    if (r.laborPct > 0.42) add({ tag: 'Labor', value: (r.laborPct - 0.34) * r.revenue, title: 'Labor ate ' + RS.pct(r.laborPct) + ' of sales', body: 'A healthy full-service room runs near 30 to 35 percent. ' + r.dayName + ' demand was ' + r.demand + ' guests. Staff the slow nights to the forecast instead of to the busiest night.' });

    // 6. Drinks.
    const bevShare = r.revenue ? r.bevRev / r.revenue : 0, bevTarget = 0.14 + 0.2 * cfg.menu.alcoholFocus / 100;
    if (bevShare < bevTarget - 0.04 && r.covers > 20) {
      const best = rows.filter((x) => x.it.course === 'drink' && x.it.drinkType !== 'na').sort((a, b) => b.cm - a.cm)[0];
      if (best) add({ tag: 'Beverage', value: (bevTarget - bevShare) * r.revenue * 0.75, title: 'Drinks were only ' + RS.pct(bevShare) + ' of sales', body: 'For the drinks program you described, the target is nearer ' + RS.pct(bevTarget) + '. Drinks carry about 75 to 80 percent margin and need no line time. ' + best.it.name + ' keeps ' + RS.money(best.cm) + ' a pour.',
        action: { label: 'Push ' + best.it.name, apply: (c) => { c.plays = c.plays.filter((p) => p.itemId !== best.it.id); c.plays.push({ type: 'push', itemId: best.it.id }); } } });
    }

    // 7. Plays that are not landing.
    if (cfg.plays.some((p) => p.type === 'push') && touch < 0.35) add({ tag: 'Plays', value: 20, title: 'Pushes need a voice', body: 'A push depends on servers recommending it at the table. With light-touch service, guests mostly never heard it. Specials and menu position do the work in a room like yours.' });
    if (r.discounts > r.revenue * 0.04) add({ tag: 'Plays', value: r.discounts * 0.5, title: 'Deals gave away ' + RS.money(r.discounts), body: 'That is ' + RS.pct(r.discounts / (r.revenue + r.discounts)) + ' of what the same plates would have rung at full price. Deals earn their keep on slow nights when chairs are empty. On a night with a queue they are a gift to guests who were coming anyway.' });

    // 8. Pricing against the experience.
    const quality = cfg.atmosphere.formality / 100 * 0.3 + cfg.sourcing / 100 * 0.35 + cfg.staff.experience / 100 * 0.35, priceT = cfg.priceTier / 100 + cfg.menu.priceAdj / 100;
    if (priceT > quality + 0.12) add({ tag: 'Pricing', value: r.revenue * 0.04, title: 'Prices are ahead of the experience', body: 'Guests judge the bill against the room, the ingredients and the staff. Right now the price sits above all three, which trims demand and satisfaction.' + (locked('priceTier') ? ' You have locked the price point, so the fix is to raise the experience to meet it: sourcing or more seasoned staff.' : ''),
      action: locked('priceTier') ? { label: 'Invest in sourcing', apply: (c) => { c.sourcing = Math.min(100, c.sourcing + 15); } } : { label: 'Ease prices 5%', apply: (c) => { c.menu.priceAdj -= 5; } } });
    else if (quality > priceT + 0.15 && (r.walkouts > 0 || r.turns > 1.8) && !locked('priceTier')) add({ tag: 'Pricing', value: r.revenue * 0.04, title: 'You are full and underpriced', body: 'The room, the product and the staff are worth more than the menu asks, and guests are queueing. A 5 percent increase is about ' + RS.money(r.revenue * 0.05) + ' a night with no extra plates cooked.',
      action: { label: 'Raise prices 5%', apply: (c) => { c.menu.priceAdj += 5; } } });

    // 9. Delighters.
    if (!cfg.delighters.bread && r.sat < 80) add({ tag: 'Loyalty', value: 25, title: 'Consider bread baked in house', body: 'About ' + RS.money(90 / 60 * 22 + 0.45 * r.covers) + ' a night in labor and flour. Guests remember it, satisfaction rises about four points, and reputation is what fills the slow nights a few weeks from now.',
      action: { label: 'Start baking', apply: (c) => { c.delighters.bread = true; } } });
    if (!cfg.delighters.memory && ((r.demos.solo || 0) + (r.demos.celebration || 0)) > r.demand * 0.18) add({ tag: 'Loyalty', value: 20, title: 'Brief the team on who is coming', body: 'Regulars and celebrations were ' + RS.pct(((r.demos.solo || 0) + (r.demos.celebration || 0)) / r.demand) + ' of tonight. Fifteen minutes before doors with the guest notes costs ' + RS.money(5.5) + ' and those tables notice.',
      action: { label: 'Add the pre-shift briefing', apply: (c) => { c.delighters.memory = true; } } });

    // What worked.
    const hero = food.filter((x) => x.qty >= 5).sort((a, b) => b.cm * b.qty - a.cm * a.qty)[0];
    if (hero) good.push(hero.it.name + ' carried the night: ' + hero.qty + ' sold, ' + RS.money(hero.cm * hero.qty) + ' in contribution.');
    const batch = food.filter((x) => x.it.prep === 'batch' && x.qty >= 4).sort((a, b) => b.cmPct - a.cmPct)[0];
    if (batch) good.push(batch.it.name + ' kept ' + RS.pct(batch.cmPct) + ' of its price and never touched the line during service.');
    if (r.sat >= 82) good.push('Guests left happy: satisfaction ' + r.sat.toFixed(0) + ' of 100.');
    if (r.primeCost && r.primeCost < 0.6) good.push('Prime cost (food plus labor) held at ' + RS.pct(r.primeCost) + '. Under 60 is where full-service rooms make money.');
    Object.keys(cfg.locks).filter((k) => cfg.locks[k]).length && good.push('Every recommendation here leaves your non-negotiables alone.');

    out.sort((a, b) => b.value - a.value);
    const n = cfg.owner.detail < 35 ? 3 : (cfg.owner.detail < 70 ? 6 : 99);
    return { notes: out.slice(0, n), hidden: Math.max(0, out.length - n), good, rows };
  };

  /* Menu engineering quadrant for a row within its course. */
  RS.quadrants = (rows) => {
    const by = {};
    rows.forEach((x) => { (by[x.it.course] = by[x.it.course] || []).push(x); });
    Object.values(by).forEach((l) => {
      const aq = l.reduce((a, x) => a + x.qty, 0) / l.length, ac = l.reduce((a, x) => a + x.cm, 0) / l.length;
      l.forEach((x) => { x.quad = x.qty >= aq * 0.9 ? (x.cm >= ac ? 'Star' : 'Workhorse') : (x.cm >= ac ? 'Puzzle' : 'Dog'); });
    });
    return rows;
  };
})();
