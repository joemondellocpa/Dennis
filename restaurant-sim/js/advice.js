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
      const name = stWait[0], lab = RS.STATION_LABEL[name], low = lab.toLowerCase();
      // Every dish that needs this station, with what it earns for each minute it holds a burner.
      const onIt = food.filter((x) => x.it.station === name && x.it.prep !== 'batch').map((x) => Object.assign({ min: x.qty * x.it.cookMin, per: x.cm / Math.max(1, x.it.cookMin) }, x)).sort((p, q) => q.per - p.per);
      const totalMin = onIt.reduce((p, x) => p + x.min, 0) || 1;
      const detail = '<table class="mini wide"><tr class="hd"><td>On the ' + low + '</td><td class="num">Sold</td><td class="num">Minutes each</td><td class="num">Share of station time</td><td class="num">Keeps</td><td class="num">Earns per station-minute</td></tr>' +
        onIt.map((x) => '<tr><td>' + x.it.name + (RS.playFor(cfg, x.it.id) ? ' <em>' + ({ push: 'pushed', slow: 'wait warned', special: 'special', discount: '20% off', bogo: '1+1' }[RS.playFor(cfg, x.it.id).type]) + '</em>' : '') + '</td><td class="num">' + x.qty + '</td><td class="num">' + x.it.cookMin + '</td><td class="num">' + Math.round(x.min / totalMin * 100) + '%</td><td class="num">' + RS.money(x.cm) + '</td><td class="num">$' + x.per.toFixed(2) + '</td></tr>').join('') + '</table>';
      const best = onIt.slice(0, Math.min(2, Math.max(1, onIt.length - 2))), worst = onIt.slice(-Math.min(2, Math.max(0, onIt.length - best.length)));
      const building = (game.projects || []).find((p) => p.station === name && !p.done), expanded = (game.projects || []).some((p) => p.station === name && p.done), cost = RS.STATION_COST[name];
      const actions = [];
      if (onIt.length >= 3) actions.push({ label: 'Tonight\'s fix: push ' + best.map((x) => x.it.name).join(' and ') + ', warn guests about the wait on ' + worst.map((x) => x.it.name).join(' and '),
        apply: (c) => { const ids = best.concat(worst).map((x) => x.it.id); c.plays = c.plays.filter((p) => !ids.includes(p.itemId)); best.forEach((x) => c.plays.push({ type: 'push', itemId: x.it.id })); worst.forEach((x) => c.plays.push({ type: 'slow', itemId: x.it.id })); } });
      if (!building && !expanded) actions.push({ label: 'Lasting fix: expand the ' + low + ' for ' + RS.money(cost) + ', ready in ' + RS.BUILD_NIGHTS + ' nights', apply: (c, g) => RS.startExpansion(g, name) });
      add({ tag: 'Kitchen', value: r.lateTickets * 5 + 40, title: lab + ' was the bottleneck', detail, actions,
        body: 'Orders queued ' + Math.round(stWait[1]) + ' plate-minutes waiting for space on the ' + low + ', which holds ' + r.stationCap[name] + ' at a time. ' + r.lateTickets + ' of ' + r.tickets + ' tickets ran late. The table shows what was using it. ' +
          (onIt.length >= 3 ? 'The quick fix costs nothing: have servers steer guests to the dishes that earn most for the time they take, and tell them honestly that the slow ones will be a while. Fewer people order those, and the ones who do mind the wait less. ' : '') +
          (building ? 'The expansion you ordered is ' + (building.ready - game.day - 1) + ' nights from done.' : expanded ? 'You have already expanded this station once and there is no room for more, so the answer now is the menu.' : 'The lasting fix is two more places on the station: ' + RS.money(cost) + ' of building work, and it takes ' + RS.BUILD_NIGHTS + ' nights before it helps. You can do either or both.') });
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

    // Tables that did not match the parties.
    {
      // Look at the last two weeks night by night: which nights needed tables joined, which nights needed every two-top.
      const twos = cfg.tables[2] || 0, pj = cfg.preJoin, dayStat = {};
      game.history.concat([r]).slice(-14).forEach((n) => { const d = dayStat[n.dow] = dayStat[n.dow] || { n: 0, joins: 0, small: 0, by: {} }; d.n++; d.joins += n.joins || 0; d.small += n.smallParties || 0; Object.entries(n.joinBy || {}).forEach(([k, v]) => { d.by[k] = (d.by[k] || 0) + v; }); });
      const joinDays = [], keepDays = [], who = {};
      Object.keys(dayStat).map(Number).sort().forEach((dw) => {
        const d = dayStat[dw], turn = twos ? d.small / d.n / twos : 9;
        if (turn >= 1.5) keepDays.push(dw);
        else if (d.joins / d.n >= 2 && !(pj.days[dw] && pj.pairs > 0)) { joinDays.push(dw); Object.entries(d.by).forEach(([k, v]) => { who[k] = (who[k] || 0) + v; }); }
      });
      const names = (l) => l.map((d) => RS.DAYS[d]).join(', ').replace(/, ([^,]*)$/, ' and $1');
      if (joinDays.length && twos >= 4) {
        const avgJ = joinDays.reduce((p, d) => p + dayStat[d].joins / dayStat[d].n, 0) / joinDays.length, k = RS.clamp(Math.round(avgJ / 2), 1, Math.floor(twos / 2) - 1);
        const top = Object.entries(who).sort((p, q) => q[1] - p[1])[0], crowd = top ? (RS.DEMOS.find((x) => x.id === top[0]) || {}).label.toLowerCase() : 'larger';
        const actions = [{ label: 'Set ' + k + (k === 1 ? ' pair' : ' pairs') + ' of two-tops as fours on ' + names(joinDays), apply: (c) => { c.preJoin.pairs = Math.max(c.preJoin.pairs, k); joinDays.forEach((d) => { c.preJoin.days[d] = true; }); } }];
        if (!keepDays.length && Object.keys(dayStat).length >= 5 && joinDays.length >= 5) actions.push({ label: 'Combine them every night', apply: (c) => { c.preJoin.pairs = Math.max(c.preJoin.pairs, k); c.preJoin.days = c.preJoin.days.map(() => true); } });
        add({ tag: 'Tables', value: avgJ * 8 + (r.walkEmpty || 0) * r.avgCheck * 0.3, title: 'Set the room differently by the night', actions,
          body: 'On ' + names(joinDays) + ' staff pushed tables together about ' + avgJ.toFixed(0) + ' times a night, mostly for ' + crowd + ' parties, while two-tops sat idle. ' +
            (keepDays.length ? 'On ' + names(keepDays) + ' it is the other way round: couples filled every two-top more than once, so those nights the small tables should stay apart. ' : 'I have not yet seen a night where couples needed every two-top. When one shows up I will tell you to keep those nights as they are. ') +
            'Setting the fours before doors open saves the scramble at the host stand. The change shows on the floor plan from the next night it applies, and you can edit it on the Room step.' });
      }
      // The plan is in place tonight but the couples came anyway.
      if (pj.pairs > 0 && pj.days[r.dow] && twos && (r.smallParties || 0) / twos >= 1.5 && r.walkouts > 0) add({ tag: 'Tables', value: r.walkouts * r.avgCheck * 0.3, title: RS.DAYS[r.dow] + ' needs its two-tops back', body: (r.smallParties || 0) + ' parties of one or two came for ' + twos + ' two-tops, ' + r.preJoined + ' pairs of which were set as fours, and ' + r.walkouts + ' guests gave up waiting. Keep the small tables apart on ' + RS.DAYS[r.dow] + 's.',
        actions: [{ label: 'Keep two-tops apart on ' + RS.DAYS[r.dow] + 's', apply: (c) => { c.preJoin.days[r.dow] = false; } }] });
    }
    if (r.walkEmpty > 0) add({ tag: 'Tables', value: r.walkEmpty * r.avgCheck * 0.6, title: r.walkEmpty + ' guests left while tables sat empty',
      body: 'They gave up waiting with free tables in the room, because the free ones were the wrong size for them, too far apart to join, or the host could not get to them in time. That is about ' + RS.money(r.walkEmpty * r.avgCheck) + ' walking out past empty chairs. Keeping small tables in pairs, close enough to push together, lets the floor absorb a group of four or five.' });

    // Happy hour.
    const hh = r.hh || {};
    if (hh.type && hh.type !== 'none') {
      if (hh.net < 40) add({ tag: 'Happy hour', value: Math.max(30, -hh.net), title: 'Happy hour is not paying for itself', body: 'It brought ' + hh.covers + ' guests and ' + RS.money(hh.rev) + ' in sales, but ' + RS.money(hh.leak) + ' of discount went to diners who were coming anyway. After the cost of what was poured and plated it nets ' + RS.money(hh.net) + '.' + (hh.type !== 'bites' ? ' Discounting food instead of drinks gives less away, since drinks are where your margin is.' : ' It may simply not suit this room.'),
        action: hh.type !== 'bites' ? { label: 'Switch to bar bites', apply: (c) => { c.happyHour.type = 'bites'; } } : { label: 'Drop happy hour', apply: (c) => { c.happyHour.type = 'none'; } } });
      else good.push('Happy hour brought ' + hh.covers + ' early guests and netted ' + RS.money(hh.net) + ' after discounts. ' + hh.stayed + ' of them stayed for dinner.');
    } else if (cfg.room.bar.on && r.dow < 5 && r.turns < 1.5 && r.walkouts === 0) add({ tag: 'Happy hour', value: 60, title: 'The first ninety minutes are empty', body: 'On a ' + r.dayName + ' the room does not fill until seven, and the staff are already on the clock. A happy hour puts people at the bar from five. Bar bites give away the least.',
      action: { label: 'Try bar bites until 6:30', apply: (c) => { c.happyHour.type = 'bites'; } } });

    // Delighters that are not earning their keep.
    (r.delighters || []).forEach((d) => {
      const worth = RS.delightWorth(game, r, d), cost = d.cost + d.givesUp;
      if (worth < cost * 0.6 && cost > 15) add({ tag: 'Delighters', value: cost - worth, title: d.name + ' is not moving the needle', body: 'It cost ' + RS.money(cost) + ' tonight' + (d.givesUp ? ' including the drink sales it replaces' : '') + ', added ' + d.mood.toFixed(1) + ' points of guest mood and was mentioned in ' + d.mentions + ' of ' + r.reviews + ' reviews. ' + (game.reputation > 0.9 ? 'Your rating is already near the top, so there is little left for it to lift.' : 'At that rate it returns about ' + RS.money(worth) + ' a night in future sales.'),
        action: { label: 'Stop offering it', apply: (c) => { c.delighters[d.id] = false; } } });
    });

    // What guests photograph and talk about.
    const shot = food.concat(rows.filter((x) => x.it.course === 'drink')).map((x) => ({ x, n: (r.items[x.it.id] || {}).photos || 0 })).sort((a, b) => b.n - a.n)[0];
    if (shot && shot.n >= 4 && shot.x.qty < r.covers * 0.12 && !RS.playFor(cfg, shot.x.it.id)) add({ tag: 'Word of mouth', value: shot.x.cm * 4, title: shot.x.it.name + ' is your most photographed plate', body: shot.n + ' of the ' + shot.x.qty + ' sold tonight ended up in somebody\'s photos. That is free advertising for a dish only ' + RS.pct(shot.x.qty / r.covers) + ' of guests order. Make it the special and let it travel.',
      action: { label: 'Feature it as the special', apply: (c) => { c.plays.push({ type: 'special', itemId: shot.x.it.id }); } } });
    const panned = food.map((x) => ({ x, n: (r.items[x.it.id] || {}).neg || 0 })).sort((a, b) => b.n - a.n)[0];
    if (panned && panned.n >= 2) add({ tag: 'Word of mouth', value: panned.n * 25, title: panned.x.it.name + ' is drawing complaints', body: panned.n + ' reviews tonight singled it out.' + (RS.itemBuy(cfg, panned.x.it).q < -0.2 ? ' It leans on ingredients you are buying at budget grade, and guests can tell on this dish.' : ' Check the plate before it leaves the pass.') });

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

    // Greed: cuts guests can taste. The saving is real tonight; the bill comes later through the rating.
    const snaps = game.history.map((h) => h.snap).filter(Boolean).concat([RS.expectNow(cfg)]), top = (k) => Math.max.apply(null, snaps.map((x) => x[k])), low = (k) => Math.min.apply(null, snaps.map((x) => x[k]));
    const d = r.drop || {}, exq = { sourcing: Math.max(50, top('sourcing')), portion: Math.max(50, top('portion')), priceAdj: low('priceAdj') }, fall = RS.stars(r.reputationNext) - RS.stars(game.reputation);
    const lost = (pts) => r.revenue * 0.9 * (pts / 30 * 0.11) * 7;   // a week of this mood, turned into lost sales per night
    if (d.quality > 1.5) add({ tag: 'Reputation', value: lost(d.quality) + 60, title: 'Guests can taste the cheaper ingredients', body: 'Buying down saved roughly ' + RS.money(r.cogs * (exq.sourcing - cfg.sourcing) / 100 * 0.45) + ' on tonight\'s plates and cost ' + d.quality.toFixed(0) + ' points of guest mood. Mood becomes reviews, reviews become the public rating, and the rating decides how many people come next week. Keep this up for a week and it costs about ' + RS.money(lost(d.quality)) + ' a night in sales that never walk in.',
      action: { label: 'Go back to the ingredients guests expect', apply: (c) => { c.sourcing = Math.min(100, Math.max(c.sourcing, Math.round(exq.sourcing))); Object.keys(c.buying).forEach((k) => { if (c.buying[k] < 0) c.buying[k] = 0; }); } } });
    if (d.portion > 1.5) add({ tag: 'Reputation', value: lost(d.portion) + 50, title: 'The plates got smaller and people noticed', body: 'Tighter portions trimmed plate cost and took ' + d.portion.toFixed(0) + ' points off guest mood. Regulars compare tonight with last month. The reviews that follow mention value, and that is the word that empties a room.',
      action: { label: 'Restore the portions', apply: (c) => { c.menu.portion = Math.round(exq.portion); } } });
    if (d.price > 1.5) add({ tag: 'Reputation', value: lost(d.price) + 40, title: 'The price rise landed badly', body: 'Prices went up faster than guests were ready for, costing ' + d.price.toFixed(0) + ' points of mood. Increases stick when they are small and the experience moves with them. Two or three percent at a time is invisible; fifteen is a review.',
      action: { label: 'Roll back to a smaller increase', apply: (c) => { c.menu.priceAdj = Math.round(exq.priceAdj + 3); } } });
    if (d.delight > 1.5) add({ tag: 'Reputation', value: lost(d.delight) + 30, title: 'Guests miss what you took away', body: 'Something they were used to getting is gone, and it cost ' + d.delight.toFixed(0) + ' points of mood. The small free things are the ones regulars mention first.' });
    const worst = Object.entries(r.gripes || {}).sort((a, b) => b[1] - a[1])[0];
    if ((fall < -0.02 || (worst && worst[1] > 3)) && worst && worst[1] > 1 && !out.some((n) => n.tag === 'Reputation')) {
      const fix = { quality: (cfg.sourcing < exq.sourcing || Object.values(cfg.buying).some((g) => g < 0)) ? { label: 'Buy better ingredients again', apply: (c) => { c.sourcing = Math.min(100, Math.max(c.sourcing, Math.round(exq.sourcing))); Object.keys(c.buying).forEach((k) => { if (c.buying[k] < 0) c.buying[k] = 0; }); } } : null, portion: cfg.menu.portion < exq.portion ? { label: 'Restore the portions', apply: (c) => { c.menu.portion = Math.round(exq.portion); } } : null, price: cfg.menu.priceAdj > exq.priceAdj ? { label: 'Take prices back to where they were', apply: (c) => { c.menu.priceAdj = Math.round(exq.priceAdj); } } : null }[worst[0]];
      const why = { wait: 'waiting: for a table, for a server, for the check', kitchen: 'slow food', price: 'prices that feel too high for what arrives', quality: 'the quality of the food', portion: 'small portions', room: 'a room that does not suit the people it attracts', extras: 'things that used to be included' }[worst[0]];
      add({ tag: 'Reputation', value: lost(Math.max(3, worst[1])) + 40, title: 'Your public rating is slipping', body: 'Tonight moves it from ' + RS.stars(game.reputation).toFixed(1) + ' to ' + RS.stars(r.reputationNext).toFixed(1) + ' stars. The biggest complaint was ' + why + '. Traffic follows the rating with a lag, so the cost of tonight shows up next week.', action: fix || undefined });
    }

    // The owner in the wrong job.
    const o = cfg.owner, role = RS.OWNER_ROLES.find((x) => x.id === o.role), best = ['cooking', 'business', 'vibe'].sort((a, b) => o[b] - o[a])[0];
    const fit = { cooking: 'chef', business: 'office', vibe: 'floor' }, word = { cooking: 'cooking', business: 'business sense', vibe: 'way with guests' };
    if (role && role.id !== 'handsoff' && role.uses !== best && o[best] - (role.uses ? o[role.uses] : 0) >= 20) {
      const to = RS.OWNER_ROLES.find((x) => x.id === fit[best]);
      add({ tag: 'Owner', value: 150, title: 'Your best skill is not in the room', body: 'Your strongest suit is your ' + word[best] + ', and tonight you were ' + role.label.toLowerCase() + ', which barely uses it. ' + to.label + ' puts it to work. The job you leave has to be paid for, so check the labor line after you switch.',
        action: { label: 'Move to: ' + to.label.toLowerCase(), apply: (c) => { c.owner.role = to.id; } } });
    }
    if (role && role.id === 'chef' && o.cooking < 45) add({ tag: 'Owner', value: 120, title: 'The food is not helping', body: 'You are head chef with modest cooking skill, and guests can taste it. A hired chef costs ' + RS.money(280 * 1.16) + ' a night and would cook better than you do.',
      action: { label: 'Hire a chef, work the room', apply: (c) => { c.owner.role = 'floor'; } } });

    // What worked.
    const hero = food.filter((x) => x.qty >= 5).sort((a, b) => b.cm * b.qty - a.cm * a.qty)[0];
    if (hero) good.push(hero.it.name + ' carried the night: ' + hero.qty + ' sold, ' + RS.money(hero.cm * hero.qty) + ' in contribution.');
    const batch = food.filter((x) => x.it.prep === 'batch' && x.qty >= 4).sort((a, b) => b.cmPct - a.cmPct)[0];
    if (batch) good.push(batch.it.name + ' kept ' + RS.pct(batch.cmPct) + ' of its price and never touched the line during service.');
    if (RS.stars(r.reputationNext) > RS.stars(game.reputation) + 0.02) good.push('Your public rating is climbing: ' + RS.stars(r.reputationNext).toFixed(1) + ' stars. More people will come looking for you.');
    if (r.sat >= 82) good.push('Guests left happy: satisfaction ' + r.sat.toFixed(0) + ' of 100.');
    if (r.primeCost && r.primeCost < 0.6) good.push('Prime cost (food plus labor) held at ' + RS.pct(r.primeCost) + '. Under 60 is where full-service rooms make money.');
    Object.keys(cfg.locks).filter((k) => cfg.locks[k]).length && good.push('Every recommendation here leaves your non-negotiables alone.');

    (game.projects || []).forEach((p) => { if (!p.done && p.ready === game.day + 1) good.push('The ' + RS.STATION_LABEL[p.station].toLowerCase() + ' expansion is finished. Two more places on that station from tomorrow.'); });
    out.forEach((n) => { n.actions = (n.actions || (n.action ? [n.action] : [])).filter(Boolean); });
    out.sort((a, b) => b.value - a.value);
    const n = cfg.owner.detail < 35 ? 3 : (cfg.owner.detail < 70 ? 6 : 99);
    return { notes: out.slice(0, n), hidden: Math.max(0, out.length - n), good, rows };
  };

  /* What a delighter is worth: mood lifts the rating, the rating lifts traffic. Nothing if the rating has no room left. */
  RS.delightWorth = (game, r, d) => r.revenue * 0.9 * (d.mood / 30 * 0.11) * 5 * 0.55 * (game.reputation > 0.97 ? 0.15 : 1);

  /* Menu engineering quadrant for a row within its course. */
  RS.quadrants = (rows) => {
    const by = {};
    rows.forEach((x) => { (by[x.it.course] = by[x.it.course] || []).push(x); });
    Object.values(by).forEach((l) => {
      const aq = l.reduce((a, x) => a + x.qty, 0) / l.length, ac = l.reduce((a, x) => a + x.cm, 0) / l.length;
      l.forEach((x) => { x.quadKey = x.qty >= aq * 0.9 ? (x.cm >= ac ? 'star' : 'workhorse') : (x.cm >= ac ? 'puzzle' : 'dog'); x.quad = { star: 'Star', workhorse: 'Crowd-pleaser', puzzle: 'Hidden gem', dog: 'Dead weight' }[x.quadKey]; });
    });
    return rows;
  };
})();
