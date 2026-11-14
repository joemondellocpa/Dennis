/* Screens: the builder (six steps), the live dinner service, and the end-of-night review. */
(function () {
  const RS = window.RS;
  const $ = (q, el) => (el || document).querySelector(q);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const get = (o, path) => path.split('.').reduce((a, k) => (a == null ? a : a[k]), o);
  const set = (o, path, v) => { const ks = path.split('.'); const last = ks.pop(); ks.reduce((a, k) => a[k], o)[last] = v; };

  let game = RS.newGame();
  let screen = 'builder', step = 0, sim = null, layout = null, speed = 'normal', paused = false, selTable = null, selStaff = null, tab = 'tables', lastResults = null, lastAdvice = null;
  const cfg = () => game.cfg;
  RS._debug = () => ({ game, sim, lastResults });

  const STEPS = ['Concept', 'Atmosphere', 'Room', 'Experience', 'Menu', 'Open'];
  const STRUCTURAL = /^(cuisine|room\.|atmosphere\.formality|atmosphere\.tableSize)/;

  /* ---------- small components ---------- */
  const slider = (path, label, left, right, o) => {
    o = o || {}; const dis = game.started && STRUCTURAL.test(path);
    const lock = o.lock ? '<button class="lock ' + (cfg().locks[path] ? 'on' : '') + '" data-act="lock" data-path="' + path + '" title="Mark as non-negotiable">' + (cfg().locks[path] ? 'Non-negotiable' : 'Flexible') + '</button>' : '';
    return '<div class="sl' + (dis ? ' dis' : '') + '"><div class="sl-h"><label>' + label + '</label><span class="sl-v" data-val="' + path + '">' + (o.fmt ? o.fmt(get(cfg(), path)) : '') + '</span>' + lock + '</div>' +
      '<input type="range" min="' + (o.min || 0) + '" max="' + (o.max || 100) + '" step="' + (o.step || 1) + '" value="' + get(cfg(), path) + '" data-path="' + path + '"' + (dis ? ' disabled' : '') + '>' +
      '<div class="sl-ends"><span>' + left + '</span><span>' + right + '</span></div>' + (o.hint ? '<p class="hint">' + o.hint + '</p>' : '') + '</div>';
  };
  const stepper = (path, label, o) => {
    o = o || {}; const dis = game.started && STRUCTURAL.test(path);
    return '<div class="stp' + (dis ? ' dis' : '') + '"><label>' + label + '</label><div><button data-act="step" data-path="' + path + '" data-d="-1" data-min="' + (o.min || 0) + '">&minus;</button><b>' + get(cfg(), path) + '</b><button data-act="step" data-path="' + path + '" data-d="1" data-max="' + (o.max || 40) + '">+</button></div>' + (o.note ? '<small>' + o.note + '</small>' : '') + '</div>';
  };
  const select = (path, label, opts) => {
    const dis = game.started && STRUCTURAL.test(path), v = get(cfg(), path);
    return '<div class="sel' + (dis ? ' dis' : '') + '"><label>' + label + '</label><select data-path="' + path + '"' + (dis ? ' disabled' : '') + '>' + opts.map((o) => '<option value="' + o[0] + '"' + (String(o[0]) === String(v) ? ' selected' : '') + '>' + o[1] + '</option>').join('') + '</select></div>';
  };

  /* ---------- pro-forma used in the side panel ---------- */
  const proforma = () => {
    const c = cfg(), cui = RS.cuisine(c), menu = RS.activeItems(c);
    const avg = (course, f) => { const l = menu.filter((i) => i.course === course); return l.length ? l.reduce((s, i) => s + f(i), 0) / l.length : 0; };
    const P = (i) => RS.itemPrice(c, i), C = (i) => RS.itemCost(c, i);
    const touch = c.diner.touch / 100, drinks = (0.3 + 0.55 * c.menu.alcoholFocus / 100) * (1.3 + 0.4 * touch) + 0.2;
    const mix = [['starter', cui.starterRate * (0.75 + 0.3 * c.atmosphere.formality / 100)], ['main', 1], ['side', cui.sideRate], ['dessert', cui.dessertRate * (0.55 + 0.5 * touch)], ['drink', drinks]];
    const check = mix.reduce((s, m) => s + m[1] * avg(m[0], P), 0), cost = mix.reduce((s, m) => s + m[1] * avg(m[0], C), 0);
    const wm = RS.lerp(0.9, 1.35, c.staff.experience / 100), area = c.room.w * c.room.h, seats = RS.seatCount(c);
    const prep = menu.reduce((x, i) => x + (i.prepMin || 0), 0) + RS.DELIGHTERS.reduce((x, d) => x + (c.delighters[d.id] ? d.prepMin : 0), 0);
    const labor = (c.staff.servers * 77 * wm + c.staff.bussers * 112 * wm + c.staff.hosts * 110.5 * wm + (c.room.bar.on ? c.staff.bartenders : 0) * 97.5 * wm + c.staff.cooks * 200 * wm + (seats > 90 ? 272 : 136) + prep / 60 * 22 + Object.values(RS.ownerLabor(c)).reduce((x, y) => x + y, 0)) * 1.16;
    const occ = area * RS.lerp(1.0, 5.6, c.priceTier / 100) + { compact: 40, standard: 70, large: 120 }[c.room.line] + 40 + 0.3 * area + 160;
    const ingr = RS.ingredientCount(c), fixed = labor + occ + ingr * 2 * RS.costMult(c);
    const per = check - cost - check * 0.063 - (0.5 + 1.2 * c.atmosphere.formality / 100);
    return { check, foodPct: check ? cost / check : 0, labor, occ, fixed, breakeven: per > 0 ? Math.ceil(fixed / per) : 0, ingr, seats, items: menu.length };
  };
  const aside = () => {
    const p = proforma(), c = cfg(), L = RS.layoutTables(c);
    const locks = Object.keys(c.locks).filter((k) => c.locks[k]).length;
    return '<h3>' + esc(c.name) + '</h3><p class="muted">' + RS.cuisine(c).name + '</p>' +
      '<dl class="kv"><dt>Seats</dt><dd>' + p.seats + (L.missing ? ' <em class="bad">(' + L.missing + ' tables do not fit)</em>' : '') + '</dd>' +
      '<dt>Menu</dt><dd>' + p.items + ' items, ' + p.ingr + ' inventory lines</dd>' +
      '<dt>Expected check</dt><dd>' + RS.money(p.check) + ' a guest</dd>' +
      '<dt>Plate cost</dt><dd>' + RS.pct(p.foodPct) + '</dd>' +
      '<dt>Nightly labor</dt><dd>' + RS.money(p.labor) + '</dd>' +
      '<dt>Rent and overhead</dt><dd>' + RS.money(p.occ) + '</dd>' +
      '<dt>Break-even</dt><dd><b>' + p.breakeven + ' guests</b> a night' + (p.seats ? ' (' + (p.breakeven / p.seats).toFixed(1) + ' turns)' : '') + '</dd>' +
      '<dt>Non-negotiables</dt><dd>' + (locks ? locks + ' locked' : 'none yet') + '</dd></dl>' +
      (game.started ? '<p class="muted">Night ' + (game.day + 1) + ', ' + RS.DAYS[game.day % 7] + '. Greyed-out settings are construction decisions and stay as built.</p>' : '<p class="muted">Lock anything the owner will not trade away. The advice after each service works around those.</p>');
  };

  /* ---------- the rating, always on screen ---------- */
  const topBar = () => {
    const el = $('#rep'); if (!el) return;
    const h = game.history, now = RS.stars(game.reputation), full = Math.round(now);
    const stars = '<span class="stars">' + '&#9733;'.repeat(full) + '<i>' + '&#9733;'.repeat(5 - full) + '</i></span>';
    const delta = (from, label) => { const d = now - from; return Math.abs(d) < 0.05 ? '<span class="muted">steady ' + label + '</span>' : '<span class="' + (d > 0 ? 'good' : 'bad') + '">' + (d > 0 ? '&#9650; +' : '&#9660; ') + d.toFixed(1) + ' ' + label + '</span>'; };
    let trend = '<span class="muted">no reviews yet</span>';
    if (h.length) trend = delta(RS.stars(game.reputationPrev), 'last night') + (h.length >= 7 ? ' &middot; ' + delta(h.length > 7 ? h[h.length - 8].starsNext : RS.stars(0.5), 'this week') : '');
    el.innerHTML = '<b>' + now.toFixed(1) + '</b>' + stars + '<small>public rating<br>' + trend + '</small>';
  };

  /* Share of the menu's ingredient spend that sits in one family, weighted by how popular each dish is. */
  const buyShare = (cat) => {
    let tot = 0, part = 0;
    RS.activeItems(cfg()).forEach((it) => { let w = 0, wc = 0; it.ingredients.forEach((g) => { const k = RS.INGR_CATS.find((x) => x.id === RS.ingrCat(g)); w += k.w; if (k.id === cat) wc += k.w; }); if (w) { tot += it.cost * it.appeal; part += it.cost * it.appeal * wc / w; } });
    return tot ? part / tot : 0;
  };

  /* ---------- builder steps ---------- */
  const crowd = () => {
    const a = cfg().atmosphere, A = { light: a.light / 100, noise: a.noise / 100, formality: a.formality / 100, spacing: a.spacing / 100 };
    const ws = RS.DEMOS.map((d) => ({ d, w: RS.demoWeight(d, cfg(), cfg().room.bar.on) }));
    const tot = ws.reduce((s, x) => s + x.w, 0);
    return ws.sort((x, y) => y.w - x.w).map((x) => '<div class="bar"><span>' + x.d.label + '</span><i><b style="width:' + (x.w / tot * 100 / 0.4).toFixed(0) + '%;background:' + x.d.color + '"></b></i><em>' + Math.round(x.w / tot * 100) + '%</em></div>').join('');
  };
  const stepHTML = [
    () => {
      const c = cfg();
      return '<h2>What are you building?</h2><p class="lede">Start with the idea. Everything after this is about making that idea pay for itself.</p>' +
        '<div class="field"><label>Name</label><input type="text" data-path="name" value="' + esc(c.name) + '" maxlength="40"></div>' +
        '<div class="cards">' + Object.values(RS.CUISINES).map((x) => '<button class="card' + (c.cuisine === x.id ? ' on' : '') + (game.started ? ' dis' : '') + '" data-act="cuisine" data-id="' + x.id + '"><b>' + x.name + '</b><span>' + x.blurb + '</span></button>').join('') + '</div>' +
        (game.started ? '' : '<p><button class="ghost" data-act="preset">Load a ready-made ' + RS.cuisine(c).name.toLowerCase() + ' to start from</button></p>') +
        '<div class="grid2">' + slider('priceTier', 'Price point', 'Neighborhood prices', 'Destination prices', { lock: true, hint: 'Sets menu prices and the kind of address you pay rent on.' }) +
        slider('sourcing', 'Ingredients', 'Broadline supplier', 'Small farms, prime cuts', { lock: true, hint: 'Better product costs more per plate. Guests taste it, and it has to be priced for.' }) + '</div>' +
        '<h3>What does winning look like?</h3><div class="grid3">' + select('goal.type', 'Goal', [['margin', 'Hit a profit margin'], ['debt', 'Pay off the build-out loan'], ['sandbox', 'No goal, just run it']]) +
        (c.goal.type === 'margin' ? select('goal.target', 'Target margin', [[8, '8%'], [10, '10%'], [12, '12%'], [15, '15%'], [18, '18%']]) : '') +
        (c.goal.type === 'debt' ? select('goal.debt', 'Loan', [[10000, '$10,000'], [20000, '$20,000'], [35000, '$35,000'], [50000, '$50,000']]) : '') +
        (c.goal.type !== 'sandbox' ? select('goal.nights', 'Deadline', [[7, '1 week'], [14, '2 weeks'], [28, '4 weeks'], [56, '8 weeks']]) : '') + '</div>';
    },
    () => '<h2>How should the room feel?</h2><p class="lede">The room decides who walks in and how long they stay. Mark the ones you would never compromise on.</p><div class="grid2"><div>' +
      slider('atmosphere.light', 'Light', 'Candlelit', 'Bright and open', { lock: true }) +
      slider('atmosphere.noise', 'Sound', 'Quiet, intimate', 'Loud, convivial', { lock: true }) +
      slider('atmosphere.formality', 'Dress', 'Come as you are', 'White tablecloth', { lock: true }) +
      slider('atmosphere.spacing', 'Space between tables', 'Elbow to elbow', 'Room to breathe', { lock: true, hint: 'Space is the most expensive thing in the room. Every extra foot is a chair you are not selling.' }) +
      slider('atmosphere.tableSize', 'Table size', 'Compact', 'Generous', { lock: true }) +
      '</div><div class="panel"><h3>Who this restaurant draws</h3><div id="crowd">' + crowd() + '</div><p class="hint">Cuisine, price point, ingredients and the room all pull on this. Each group spends, drinks and lingers differently, and you can click their tables during service.</p></div></div>',
    () => {
      const c = cfg(), walls = [['S', 'Front wall'], ['W', 'Left wall'], ['E', 'Right wall']];
      return '<h2>Lay out the room</h2><p class="lede">A rectangle, a kitchen behind the back wall, and as many tables as your spacing allows. Drag tables to move them.</p><div class="grid-room"><div>' +
        '<div class="grid2">' + slider('room.w', 'Width', '10 m', '28 m', { min: 10, max: 28, fmt: (v) => v + ' m' }) + slider('room.h', 'Depth', '7 m', '18 m', { min: 7, max: 18, fmt: (v) => v + ' m' }) + '</div>' +
        '<div class="grid2">' + select('room.entrance.wall', 'Entrance and host stand', walls) + slider('room.entrance.pos', 'Position along wall', '', '', { max: 1, step: 0.05 }) +
        select('room.restroom.wall', 'Restrooms', walls.concat([['N', 'Back wall']])) + slider('room.restroom.pos', 'Position along wall', '', '', { max: 1, step: 0.05 }) +
        select('room.line', 'Kitchen line', [['compact', 'Compact (cheaper, less capacity)'], ['standard', 'Standard'], ['large', 'Large (more burners, more rent)']]) + slider('room.kitchenDoor.pos', 'Kitchen door', 'Left', 'Right', { max: 1, step: 0.05 }) + '</div>' +
        '<h3>Bar</h3><div class="grid2">' + select('room.bar.on', 'Bar', [[true, 'Yes'], [false, 'No bar']]) + (c.room.bar.on ? select('room.bar.vibe', 'What kind', [['cocktail', 'Cocktail bar'], ['wine', 'Wine bar'], ['beer', 'Neighborhood taps']]) +
          select('room.bar.wall', 'Along', walls) + slider('room.bar.pos', 'Position', '', '', { max: 1, step: 0.05 }) + stepper('room.bar.seats', 'Stools', { min: 4, max: 16 }) : '') + '</div>' +
        '<h3>Tables</h3><div class="grid4">' + [2, 4, 6, 8].map((n) => stepper('tables.' + n, n + '-tops', { max: 30 })).join('') + '</div>' +
        '</div><div><div class="canvas-wrap edit"><canvas id="plan"></canvas></div><p class="hint" id="fit"></p><button class="ghost" data-act="auto">Arrange automatically</button></div></div>';
    },
    () => {
      const sg = RS.suggestStaff(cfg());
      return '<h2>What is it like to be here?</h2><p class="lede">Three experiences: the guest\'s, the staff\'s, and yours.</p><div class="grid3col"><div class="panel"><h3>The guest</h3>' +
        slider('diner.touch', 'Service', 'Light touch, left alone', 'Hands-on, guided', { lock: true, hint: 'Hands-on service sells more starters, drinks and dessert. It also needs more servers per table.' }) +
        slider('diner.pace', 'Pace', 'In and out', 'Stay all night', { lock: true, hint: 'Lingering guests are happy guests who are sitting in a chair you could have sold twice.' }) +
        '</div><div class="panel"><h3>The staff</h3>' +
        slider('staff.style', 'Manner with guests', 'First names, banter', 'Formal, choreographed', { lock: true, hint: 'It should match the room. Formal service in a loud casual room feels off, and so does the reverse.' }) +
        slider('staff.experience', 'Seasoning', 'New, trained on the job', 'Career professionals', { lock: true, hint: 'Veterans cost about 35 percent more an hour, move faster, and sell better.' }) +
        '<div class="grid2">' + stepper('staff.servers', 'Servers', { min: 1, note: 'suggested ' + sg.servers }) + stepper('staff.bussers', 'Bussers', { note: 'suggested ' + sg.bussers }) + stepper('staff.hosts', 'Hosts', { max: 3, note: 'suggested 1' }) +
        stepper('staff.cooks', 'Line cooks', { min: 1, note: 'suggested ' + sg.cooks }) + (cfg().room.bar.on ? stepper('staff.bartenders', 'Bartenders', { max: 4, note: 'suggested 1' }) : '') + '</div>' +
        '</div><div class="panel"><h3>The owner</h3>' +
        select('owner.role', 'Where you are at 8 pm', RS.OWNER_ROLES.map((o) => [o.id, o.label])) + '<p class="hint" style="margin:-4px 0 14px">' + (RS.OWNER_ROLES.find((o) => o.id === cfg().owner.role) || {}).desc + '</p>' +
        '<p class="hint" style="margin-bottom:10px">What you are good at. ' + RS.OWNER_POINTS + ' points to spread across three skills. A skill counts in full only in a job that uses it. <b id="pts"></b></p>' +
        slider('owner.cooking', 'Cooking', 'Can follow a recipe', 'Could run any kitchen') +
        slider('owner.business', 'Business', 'Shoebox of receipts', 'Knows every number') +
        slider('owner.vibe', 'Vibe-making', 'Awkward at tables', 'The reason people come back') +
        slider('owner.detail', 'How much you want to see', 'Three things to fix', 'Every number', { hint: 'Sets how much the end-of-night review shows you.' }) + '</div></div>';
    },
    () => {
      const c = cfg(), cui = RS.cuisine(c); RS.ensureMenu(c);
      const course = (id, label) => {
        const items = cui.items.filter((i) => i.course === id);
        return '<tbody><tr class="grp"><td colspan="8">' + label + '</td></tr>' + items.map((i) => {
          const on = c.menu.enabled[i.id], pl = RS.playFor(c, i.id), price = RS.itemPrice(c, i), cost = RS.itemCost(c, i), m = (price - cost) / price;
          return '<tr class="' + (on || (pl && pl.type === 'special') ? '' : 'off') + '" title="' + esc(i.note || '') + '"><td><input type="checkbox" data-item="' + i.id + '"' + (on ? ' checked' : '') + '></td><td><b>' + esc(i.name) + '</b><small>' + esc(i.note || '') + '</small></td>' +
            '<td class="num">' + RS.money(price) + '</td><td class="num">' + RS.money(cost) + '</td><td class="num ' + (m > 0.72 ? 'good' : (m < 0.62 ? 'bad' : '')) + '">' + Math.round(m * 100) + '%</td>' +
            '<td><span class="chip ' + i.prep + '">' + { batch: 'made ahead', assembly: 'quick finish', alacarte: 'cooked to order' }[i.prep] + '</span></td><td class="muted">' + (i.course === 'drink' ? 'bar' : RS.STATION_LABEL[i.station].split(' ')[0].toLowerCase()) + '</td>' +
            '<td><select data-play="' + i.id + '"><option value="">no play</option>' + [['push', 'Push it'], ['discount', '20% off'], ['bogo', '1 + 1'], ['special', 'Tonight\'s special']].map((o) => '<option value="' + o[0] + '"' + (pl && pl.type === o[0] ? ' selected' : '') + '>' + o[1] + '</option>').join('') + '</select></td></tr>';
        }).join('') + '</tbody>';
      };
      return '<h2>The menu</h2><p class="lede">In a real engagement the chef writes this. Here, pick from a list. Watch the inventory count: every new ingredient is something to order, store and throw away.</p>' +
        '<div class="grid3">' + slider('menu.alcoholFocus', 'How much is this place about drinking?', 'Food first', 'Wine and cocktails lead', { lock: true }) +
        slider('menu.priceAdj', 'Price adjustment', '-15%', '+25%', { min: -15, max: 25, fmt: (v) => (v > 0 ? '+' : '') + v + '%', hint: 'Guests notice sudden jumps. Small steps stick.' }) +
        slider('menu.portion', 'Portions', 'Tight, every gram counted', 'Generous', { lock: true, hint: 'Smaller plates cost less tonight. Guests compare them with what they got last time.' }) +
        '<div class="sel"><label>Menu size</label><div class="btnrow"><button class="ghost" data-act="msize" data-k="tight">Tight</button><button class="ghost" data-act="msize" data-k="core">Core</button><button class="ghost" data-act="msize" data-k="all">Everything</button></div></div></div>' +
        '<div class="tablewrap"><table class="menu"><thead><tr><th></th><th>Item</th><th class="num">Price</th><th class="num">Cost</th><th class="num">Margin</th><th>Kitchen</th><th>Station</th><th>Play</th></tr></thead>' +
        course('starter', 'Starters') + course('main', 'Mains') + course('side', 'Sides') + course('dessert', 'Desserts') + course('drink', 'Drinks') + '</table></div>' +
        '<h3>Where to spend on ingredients</h3><p class="hint">Your overall standard is set on the Concept step. Here you can trade up or down one family at a time. Some swaps guests never notice. Others they taste on the first bite.</p><div class="tablewrap"><table class="menu buy"><tbody>' +
        RS.INGR_CATS.map((k) => { const g = c.buying[k.id] || 0, sh = buyShare(k.id); return '<tr><td><b>' + k.label + '</b><small>' + k.tell + '</small></td><td class="num muted">' + Math.round(sh * 100) + '% of plate cost</td><td><div class="btnrow">' + [-1, 0, 1].map((x) => '<button class="ghost' + (g === x ? ' on' : '') + '" data-act="grade" data-cat="' + k.id + '" data-g="' + x + '">' + RS.GRADE[x].label + '</button>').join('') + '</div></td><td class="num ' + (g < 0 ? 'good' : (g > 0 ? 'bad' : 'muted')) + '">' + (g ? (g < 0 ? '&minus;' : '+') + Math.round(Math.abs(RS.GRADE[g].cost - 1) * sh * 100) + '% food cost' : '') + '</td><td><span class="chip ' + (k.notice > 0.8 ? 'alacarte' : (k.notice > 0.3 ? 'assembly' : 'batch')) + '">' + (k.notice > 0.8 ? 'guests notice at once' : (k.notice > 0.3 ? 'some notice' : 'nobody notices')) + '</span></td></tr>'; }).join('') + '</tbody></table></div>' +
        '<h3>Happy hour</h3><div class="grid2">' + select('happyHour.type', 'Before the dinner rush', RS.HH_TYPES.map((h) => [h.id, h.label])) + '<p class="hint" style="align-self:center">' + (RS.HH_TYPES.find((h) => h.id === c.happyHour.type) || RS.HH_TYPES[0]).desc + ' The review after service shows what it brought in against what it gave away.</p></div>' +
        '<h3>Delighters</h3><p class="hint">Small things that cost a little and bring people back.</p><div class="cards small">' + RS.DELIGHTERS.map((d) => '<label class="card check' + (c.delighters[d.id] ? ' on' : '') + '"><input type="checkbox" data-delight="' + d.id + '"' + (c.delighters[d.id] ? ' checked' : '') + '><b>' + d.name + '</b><span>' + d.desc + '</span></label>').join('') + '</div>';
    },
    () => {
      const c = cfg(), p = proforma(), L = RS.layoutTables(c);
      const locks = Object.keys(c.locks).filter((k) => c.locks[k]);
      const names = { priceTier: 'price point', sourcing: 'ingredients', 'atmosphere.light': 'lighting', 'atmosphere.noise': 'sound', 'atmosphere.formality': 'dress', 'atmosphere.spacing': 'table spacing', 'atmosphere.tableSize': 'table size', 'diner.touch': 'service style', 'diner.pace': 'pace', 'staff.style': 'staff manner', 'staff.experience': 'staff seasoning', 'menu.alcoholFocus': 'drinks focus', 'menu.portion': 'portions' };
      return '<h2>' + (game.started ? 'Ready for ' + RS.DAYS[game.day % 7] + '?' : 'Open the doors') + '</h2><p class="lede">' + esc(c.name) + ': ' + p.seats + ' seats, ' + p.items + ' menu items, ' + (c.staff.servers + c.staff.bussers + c.staff.hosts + c.staff.cooks + (c.room.bar.on ? c.staff.bartenders : 0)) + ' on the schedule. You need about <b>' + p.breakeven + ' guests</b> at ' + RS.money(p.check) + ' each to break even on a night.</p>' +
        (locks.length ? '<p class="lede">Non-negotiable: ' + locks.map((k) => names[k] || k).join(', ') + '.</p>' : '') +
        (L.missing ? '<p class="warn">' + L.missing + ' tables do not fit in the room at this spacing. They will be left out.</p>' : '') +
        '<p class="hint">Once service starts you watch. Nobody on the floor takes instructions from you tonight.</p>' +
        '<p><button class="primary big" data-act="open">Start ' + RS.DAYS[game.day % 7] + ' dinner service</button></p>';
    }
  ];

  const renderBuilder = () => {
    RS.ensureMenu(cfg());
    $('#app').innerHTML = '<div class="builder"><nav class="steps">' + STEPS.map((s, i) => '<button class="' + (i === step ? 'on' : '') + '" data-act="goto" data-i="' + i + '"><i>' + (i + 1) + '</i>' + s + '</button>').join('') + '</nav>' +
      '<section class="main">' + stepHTML[step]() + '<div class="navrow">' + (step > 0 ? '<button class="ghost" data-act="goto" data-i="' + (step - 1) + '">Back</button>' : '<span></span>') + (step < STEPS.length - 1 ? '<button class="primary" data-act="goto" data-i="' + (step + 1) + '">Next: ' + STEPS[step + 1] + '</button>' : '') + '</div></section>' +
      '<aside class="aside" id="aside">' + aside() + '</aside></div>';
    if (step === 2) drawPlan();
    ownerPts(); topBar();
  };
  const ownerPts = () => { const el = $('#pts'), o = cfg().owner; if (el) el.textContent = (RS.OWNER_POINTS - o.cooking - o.business - o.vibe) + ' left.'; };
  const drawPlan = () => {
    const cv = $('#plan'); if (!cv) return;
    layout = RS.layoutTables(cfg());
    RS.draw(cv, cfg(), layout, null, null);
    const seats = layout.tables.reduce((s, t) => s + t.seats, 0);
    $('#fit').innerHTML = layout.missing ? '<span class="bad">' + layout.missing + ' tables do not fit. Widen the room, tighten the spacing, or cut tables.</span>' : seats + ' seats in ' + (cfg().room.w * cfg().room.h) + ' m², ' + (cfg().room.w * cfg().room.h / Math.max(1, seats)).toFixed(1) + ' m² a seat.';
  };

  /* ---------- service ---------- */
  const SPEEDS = { normal: 400 / 300, fast: 400 / 180, turbo: 400 / 12, week: 400 * 7 / 60 };
  const startNight = () => {
    if (!game.started) { game.started = true; game.debtLeft = cfg().goal.type === 'debt' ? Number(cfg().goal.debt) : 0; }
    sim = RS.createSim(game); layout = { tables: sim.tables, geom: sim.geom, missing: 0 };
    selTable = null; selStaff = null; screen = 'service'; paused = false; renderService();
  };
  const renderService = () => {
    $('#app').innerHTML = '<div class="svc"><div class="stage"><div class="canvas-wrap"><canvas id="floor"></canvas></div><div class="legend">' +
      [['server', 'Server'], ['busser', 'Busser'], ['host', 'Host'], ['bartender', 'Bartender'], ['cook', 'Cook'], ['owner', 'Owner']].map((r) => '<span><i class="sq" style="background:' + RS.ROLE_COLOR[r[0]] + '"></i>' + r[1] + '</span>').join('') +
      RS.DEMOS.map((d) => '<span><i class="dot" style="background:' + d.color + '"></i>' + d.label + '</span>').join('') +
      '<span><i class="sq" style="background:#d98b3a"></i>waiting</span><span><i class="sq" style="background:#5fae6e"></i>eating</span><span><i class="sq" style="background:#7b9bd1"></i>finishing</span><span><i class="sq" style="background:#6b5b4d"></i>needs bussing</span></div></div>' +
      '<aside class="side"><div id="hud"></div><div class="tabs">' + [['tables', 'Who is this?'], ['menu', 'Menu tally'], ['log', 'Floor notes']].map((t) => '<button data-act="tab" data-t="' + t[0] + '" class="' + (tab === t[0] ? 'on' : '') + '">' + t[1] + '</button>').join('') + '</div><div id="tabbody"></div></aside></div>';
    updateSide(); topBar();
  };
  const tableHTML = () => {
    if (selStaff) return staffHTML(selStaff);
    const t = selTable; if (!t) return '<p class="muted">Click a table to see who is sitting there, why they came and what they ordered. Click anyone on staff, in the dining room or the kitchen, to meet them. Pausing makes them easier to catch.</p>';
    const p = t.party || t.lastParty;
    let h = '<h4>' + (t.bar ? 'Bar seats' : 'Table ' + (t.id + 1)) + ' <small>' + t.seats + ' seats, ' + (t.server ? t.server.role + ' ' + (Number(t.server.id.replace(/\D/g, '')) + 1) : '') + '</small></h4>';
    if (!p) return h + '<p class="muted">Empty so far tonight.</p>';
    const stateTxt = { toTable: 'being seated', seated: 'waiting to order', waitFood: 'waiting on food', eating: 'eating', waitClear: 'finished, plates still down', waitCheck: 'asked for the check', paying: 'paying and lingering', leaving: 'left' };
    h += '<p><i class="dot" style="background:' + p.demo.color + '"></i> <b>' + p.demo.label + '</b>, party of ' + p.size + ', ages ' + p.demo.ages + '<br><span class="muted">' + (t.party ? stateTxt[p.state] || p.state : 'left; table ' + (t.state === 'dirty' ? 'needs bussing' : 'reset')) + '</span></p>';
    if (t.joined && t.joined.length) h += '<p class="muted">Pushed together with table ' + t.joined.map((x) => x.id + 1).join(' and ') + ' for this party.</p>';
    if (t.joinedTo) h += '<p class="muted">Joined onto table ' + (t.joinedTo.id + 1) + '.</p>';
    h += '<dl class="kv"><dt>Why they came</dt><dd>' + esc(p.reason) + '</dd><dt>Arrived</dt><dd>' + RS.clock(p.arrivedAt) + '</dd><dt>Waited for table</dt><dd>' + (p.waits.seat || 0).toFixed(0) + ' min</dd>' +
      (p.waits.greet != null ? '<dt>Waited for server</dt><dd>' + p.waits.greet.toFixed(1) + ' min</dd>' : '') + (p.waits.main != null ? '<dt>Waited for mains</dt><dd>' + p.waits.main.toFixed(0) + ' min</dd>' : '') +
      (p.sat != null ? '<dt>Left feeling</dt><dd>' + p.sat.toFixed(0) + ' / 100</dd>' : '') + '</dl>';
    if (p.lines.length) {
      const agg = {}; p.lines.forEach((l) => { const k = l.item.id + (l.free ? 'f' : ''); (agg[k] = agg[k] || { l, n: 0, sum: 0 }).n++; agg[k].sum += l.price; });
      h += '<table class="mini">' + Object.values(agg).map((a) => '<tr><td>' + a.n + ' &times;</td><td>' + esc(a.l.item.name) + (a.l.free ? ' <em>(free)</em>' : '') + '</td><td class="num">' + RS.money(a.sum) + '</td></tr>').join('') + '<tr class="tot"><td></td><td>Check</td><td class="num">' + RS.money(p.check) + '</td></tr></table>';
    } else h += '<p class="muted">Has not ordered yet.</p>';
    return h;
  };
  const staffHTML = (a) => {
    const doing = { order: 'taking an order', food: 'running food', drinks: 'carrying drinks', check: 'dropping a check', clear: 'clearing plates', bus: 'resetting a table', visit: a.role === 'host' ? 'seating a party' : 'checking on a table' };
    let now = a.id === 'owner' && a.plates !== undefined ? 'at the pass, checking every plate' : a.role === 'cook' ? (a.station && sim.stations[a.station].active ? 'cooking, ' + sim.stations[a.station].active + ' on the ' + RS.STATION_LABEL[a.station].split(' ')[0].toLowerCase() : 'waiting for tickets') : (a.cur ? doing[a.cur.type] + (a.cur.table ? (a.cur.table.bar ? ' at the bar' : ', table ' + (a.cur.table.id + 1)) : '') : (a.role === 'bartender' ? 'behind the bar' : 'standing by'));
    let h = '<h4><i class="sq" style="background:' + RS.ROLE_COLOR[a.role] + '"></i>' + esc(a.name) + ' <small>' + esc(a.title) + '</small></h4><p>' + esc(a.bio) + '<br><span class="muted">Right now: ' + now + '</span></p><dl class="kv">';
    if (a.years != null) h += '<dt>In the business</dt><dd>' + a.years + (a.years === 1 ? ' year' : ' years') + '</dd>';
    if (a.plates !== undefined) h += '<dt>Plates out tonight</dt><dd>' + a.plates + '</dd>';
    else if (a.busy !== undefined) {
      h += '<dt>Busy</dt><dd>' + RS.pct(sim.t ? a.busy / sim.t : 0) + ' of the night</dd><dt>Trips made</dt><dd>' + a.done + '</dd>';
      if (a.role === 'server' || a.role === 'bartender') h += '<dt>Tables finished</dt><dd>' + a.tables + '</dd><dt>Sales rung</dt><dd>' + RS.money(a.sales) + '</dd><dt>Tips so far</dt><dd>' + RS.money(a.tips) + '</dd>';
      if (a.role === 'host') h += '<dt>Parties seated</dt><dd>' + a.tables + '</dd>';
      if (a.role === 'server') { const sec = sim.tables.filter((t) => t.server === a && !t.bar).map((t) => t.id + 1); h += '<dt>Section</dt><dd>tables ' + sec.join(', ') + '</dd>'; }
    }
    return h + '</dl>';
  };
  const tallyHTML = () => {
    const c = cfg(), rows = RS.activeItems(c).map((i) => ({ i, s: sim.stats.items[i.id] }));
    const sec = (course, label) => '<tr class="grp"><td colspan="3">' + label + '</td></tr>' + rows.filter((r) => r.i.course === course).sort((a, b) => b.s.qty - a.s.qty).map((r) => '<tr><td class="num"><b>' + r.s.qty + '</b></td><td>' + esc(r.i.name) + (RS.playFor(c, r.i.id) ? ' <em>' + { push: 'push', discount: '20% off', bogo: '1+1', special: 'special' }[RS.playFor(c, r.i.id).type] + '</em>' : '') + '</td><td class="num">' + RS.money(r.s.rev) + '</td></tr>').join('');
    return '<table class="mini tally">' + sec('starter', 'Starters') + sec('main', 'Mains') + sec('side', 'Sides') + sec('dessert', 'Desserts') + sec('drink', 'Drinks') + '</table>';
  };
  const updateSide = () => {
    if (!sim || screen !== 'service') return;
    const s = sim.stats, waiting = sim.parties.filter((p) => p.state === 'waiting').reduce((a, p) => a + p.size, 0), seated = sim.parties.filter((p) => p.table && p.state !== 'leaving').reduce((a, p) => a + p.size, 0);
    const sat = s.sats.length ? s.sats.reduce((a, b) => a + b, 0) / s.sats.length : 0;
    $('#hud').innerHTML = '<div class="clock"><span>' + RS.DAYS[game.day % 7] + ', night ' + (game.day + 1) + '</span><b>' + RS.clock(sim.t) + '</b></div>' +
      '<div class="speed">' + [['pause', '&#10074;&#10074;', 'Pause'], ['normal', '&gt;', 'One dinner in about 5 minutes'], ['fast', '&gt;&gt;', 'One dinner in about 3 minutes'], ['turbo', '&gt;&gt;&gt;', 'Tonight in about 12 seconds'], ['week', '&gt;&gt;&gt;&gt;', 'The rest of the week without stopping, about a minute']].map((x) => '<button title="' + x[2] + '" data-act="speed" data-s="' + x[0] + '" class="' + ((x[0] === 'pause' ? paused : (!paused && speed === x[0])) ? 'on' : '') + '">' + x[1] + '</button>').join('') + '</div>' +
      '<div class="kpis"><div><small>Sales</small><b>' + RS.money(s.revenue) + '</b></div><div><small>Guests served</small><b>' + s.covers + '</b></div><div><small>In the room</small><b>' + seated + ' / ' + RS.seatCount(cfg()) + '</b></div>' +
      '<div><small>Waiting at door</small><b class="' + (waiting > 6 ? 'bad' : '') + '">' + waiting + '</b></div><div><small>Walked out</small><b class="' + (s.walkouts ? 'bad' : '') + '">' + (s.walkouts + s.turnedAway) + '</b></div><div><small>Mood so far</small><b>' + (sat ? sat.toFixed(0) : '&ndash;') + '</b></div></div>';
    $('#tabbody').innerHTML = tab === 'tables' ? tableHTML() : (tab === 'menu' ? tallyHTML() : '<ul class="log">' + (sim.log.length ? sim.log.map((l) => '<li class="' + l.kind + '"><time>' + RS.clock(l.t) + '</time>' + esc(l.msg) + '</li>').join('') : '<li class="muted">Quiet so far.</li>') + '</ul>');
  };

  const endNight = () => {
    const r = sim.results(); lastResults = r;
    lastAdvice = RS.advise(game, r);
    const weekEnd = game.day % 7 === 6;
    RS.closeNight(game, r); topBar();
    if (speed === 'week' && !weekEnd) { sim = RS.createSim(game); layout = { tables: sim.tables, geom: sim.geom, missing: 0 }; selTable = null; selStaff = null; return; }
    if (speed === 'week') speed = 'normal';
    sim = null; screen = 'review'; renderReview();
  };

  /* ---------- review ---------- */
  const goalHTML = () => {
    const g = cfg().goal, h = game.history; if (g.type === 'sandbox') return '';
    const left = g.nights - h.length;
    if (g.type === 'margin') {
      const last = h.slice(-7), rev = last.reduce((a, r) => a + r.revenue, 0), pr = last.reduce((a, r) => a + r.profit, 0), m = rev ? pr / rev : 0, hit = m * 100 >= g.target;
      return '<div class="goal ' + (hit ? 'hit' : '') + '"><b>Goal: ' + g.target + '% margin by night ' + g.nights + '</b><span>Trailing ' + last.length + '-night margin is ' + RS.pct(m) + '. ' + (hit ? 'You are there. Hold it.' : (left > 0 ? left + ' nights left.' : 'Deadline passed. Keep going or start over.')) + '</span><i><u style="width:' + RS.clamp(m * 100 / g.target * 100, 0, 100) + '%"></u></i></div>';
    }
    const paid = g.debt - game.debtLeft, done = game.debtLeft <= 0;
    return '<div class="goal ' + (done ? 'hit' : '') + '"><b>Goal: repay ' + RS.money(g.debt) + ' in ' + g.nights + ' nights</b><span>' + RS.money(paid) + ' repaid, ' + RS.money(game.debtLeft) + ' to go. ' + (done ? 'Loan cleared.' : (left > 0 ? left + ' nights left; you need ' + RS.money(game.debtLeft / left) + ' a night.' : 'Deadline passed.')) + '</span><i><u style="width:' + RS.clamp(paid / g.debt * 100, 0, 100) + '%"></u></i></div>';
  };
  const chartHTML = () => {
    const h = game.history.slice(-14); if (h.length < 2) return '';
    const max = Math.max.apply(null, h.map((r) => Math.abs(r.profit)).concat([1])), bw = 100 / h.length;
    return '<div class="panel"><h3>Profit by night</h3><svg class="chart" viewBox="0 0 100 44" preserveAspectRatio="none">' + h.map((r, i) => { const hh = Math.abs(r.profit) / max * 18; return '<rect x="' + (i * bw + bw * 0.15) + '" y="' + (r.profit >= 0 ? 20 - hh : 20) + '" width="' + bw * 0.7 + '" height="' + Math.max(0.4, hh) + '" fill="' + (r.profit >= 0 ? '#5fae6e' : '#d9614f') + '"><title>' + r.dayName + ': ' + RS.money(r.profit) + '</title></rect>'; }).join('') +
      '<line x1="0" x2="100" y1="20" y2="20" stroke="#8a8172" stroke-width="0.2"/></svg><div class="chartlbl">' + h.map((r) => '<span>' + r.dayName.slice(0, 2) + '<br>' + RS.money(r.profit) + '</span>').join('') + '</div></div>';
  };
  const reviewsHTML = (r) => {
    const bad = { wait: 'Stood at the door forever, then waited again for the check.', kitchen: 'Forty minutes for a main. We nearly left.', price: 'Not worth what they charge now.', quality: 'Used to be better. The food tastes like corners are being cut.', portion: 'Portions have shrunk. Left hungry.', room: 'Wrong room for us. Could not hear each other, or could hear everything.', extras: 'They stopped doing the little things we came for.' };
    const nice = { food: 'You can taste the ingredients. Worth every dollar.', service: 'Staff who know what they are doing and seem glad you came.', room: 'The room is exactly right. We stayed for hours.', extras: 'The small touches made the night.', portion: 'Generous plates. Nobody leaves hungry.' };
    const g = Object.entries(r.gripes).filter((e) => e[1] > 1.2).sort((a, b) => b[1] - a[1]).slice(0, 2), p = Object.entries(r.praise).filter((e) => e[1] > 1.5).sort((a, b) => b[1] - a[1]).slice(0, 2);
    const hist = game.history.slice(-8).map((x) => x.starsNext.toFixed(1));
    return '<div class="panel"><h3>What guests are saying online</h3><p><b style="font-size:20px">' + RS.stars(game.reputation).toFixed(1) + ' &#9733;</b> <span class="muted">' + (hist.length > 1 ? 'recent nights: ' + hist.join(' &rarr; ') : 'your first night of reviews') + '</span></p>' +
      g.map((e) => '<p class="quote bad">&ldquo;' + bad[e[0]] + '&rdquo;</p>').join('') + p.map((e) => '<p class="quote good">&ldquo;' + nice[e[0]] + '&rdquo;</p>').join('') +
      (!g.length && !p.length ? '<p class="muted">Nothing strong either way tonight.</p>' : '') + '<p class="hint">The rating follows how guests felt when they left. Next week\'s traffic follows the rating.</p></div>';
  };
  const week = () => game.history.slice(-7);
  const buzzHTML = (r) => {
    const wk = week(), by = {};
    wk.forEach((n) => Object.keys(n.items).forEach((id) => { const s = n.items[id], b = by[id] = by[id] || { id, qty: 0, pos: 0, neg: 0, photos: 0 }; b.qty += s.qty; b.pos += s.pos || 0; b.neg += s.neg || 0; b.photos += s.photos || 0; }));
    const rows = Object.values(by).map((b) => Object.assign(b, { it: RS.item(cfg(), b.id) })).filter((b) => b.it && (b.pos + b.neg + b.photos) > 0).sort((x, y) => (y.pos + y.photos + y.neg) - (x.pos + x.photos + x.neg)).slice(0, 8);
    const reviews = wk.reduce((x, n) => x + n.reviews, 0);
    if (!rows.length) return '';
    return '<div class="panel"><h3>What people post about</h3><p class="hint">' + reviews + ' reviews written over the last ' + wk.length + (wk.length === 1 ? ' night' : ' nights') + ', averaging ' + (wk.reduce((x, n) => x + n.reviewStars * n.reviews, 0) / Math.max(1, reviews)).toFixed(1) + ' stars. Photos are plates that ended up on someone\'s feed.</p><table class="mini wide"><tr class="hd"><td>Dish</td><td class="num">Sold</td><td class="num">Praised</td><td class="num">Complained</td><td class="num">Photos</td></tr>' +
      rows.map((b) => '<tr><td>' + esc(b.it.name) + '</td><td class="num">' + b.qty + '</td><td class="num good">' + (b.pos || '') + '</td><td class="num bad">' + (b.neg || '') + '</td><td class="num">' + (b.photos || '') + '</td></tr>').join('') + '</table></div>';
  };
  const delightHTML = (r) => {
    if (!r.delighters.length) return '';
    const wk = week();
    return '<div class="panel"><h3>Are the delighters working?</h3><table class="mini wide"><tr class="hd"><td></td><td class="num">Cost tonight</td><td class="num">Mood added</td><td class="num">Review mentions, ' + wk.length + (wk.length === 1 ? ' night' : ' nights') + '</td><td></td></tr>' +
      r.delighters.map((d) => { const worth = RS.delightWorth(game, r, d), cost = d.cost + d.givesUp, m = wk.reduce((x, n) => x + ((n.delighters.find((y) => y.id === d.id) || {}).mentions || 0), 0);
        const v = worth >= cost * 1.3 ? ['q-star', 'Earning its keep'] : (worth < cost * 0.6 ? ['q-dog', 'Not moving the needle'] : ['q-workhorse', 'About break-even']);
        return '<tr><td>' + d.name + (d.givesUp ? '<br><small class="muted">includes ' + RS.money(d.givesUp) + ' of drink sales it replaces</small>' : '') + '</td><td class="num">' + RS.money(cost) + '</td><td class="num">+' + d.mood.toFixed(1) + '</td><td class="num">' + m + '</td><td><span class="chip ' + v[0] + '">' + v[1] + '</span></td></tr>'; }).join('') +
      '</table><p class="hint">Mood lifts the public rating and the rating brings guests, so each delighter is judged on the future sales its mood points are worth against what it costs. ' + (game.reputation > 0.97 ? 'Your rating is at the ceiling, so none of them can lift it further right now.' : '') + '</p></div>';
  };
  const happyHTML = (r) => {
    const h = r.hh; if (!h || h.type === 'none') return '';
    const wk = week().filter((n) => n.hh && n.hh.type !== 'none'), wnet = wk.reduce((x, n) => x + n.hh.net, 0);
    return '<div class="panel"><h3>Happy hour</h3><p class="muted">' + h.label + '</p><dl class="kv"><dt>Guests it brought in</dt><dd>' + h.covers + '</dd><dt>Their sales</dt><dd>' + RS.money(h.rev) + '</dd><dt>Cost of what they were served</dt><dd>' + RS.money(-h.cogs) + '</dd><dt>Discount given to diners coming anyway</dt><dd class="bad">' + RS.money(-h.leak) + '</dd><dt>Stayed on for dinner</dt><dd>' + h.stayed + ' guests</dd><dt>Still at a table after 6:45</dt><dd>' + Math.round(h.overstay / 60 * 10) / 10 + ' seat-hours</dd><dt><b>Net effect on profit tonight</b></dt><dd><b class="' + (h.net >= 0 ? 'good' : 'bad') + '">' + RS.money(h.net) + '</b></dd>' +
      (wk.length > 1 ? '<dt>Net over ' + wk.length + ' nights</dt><dd class="' + (wnet >= 0 ? 'good' : 'bad') + '">' + RS.money(wnet) + '</dd>' : '') + '</dl><p class="hint">Staff are already on the clock at five, so no extra wages are counted. The real costs are what gets poured and the discount handed to people who would have paid full price.</p></div>';
  };
  const renderReview = () => {
    const r = lastResults, a = lastAdvice, full = cfg().owner.detail >= 35;
    const line = (label, v, cls, pctOf) => '<tr class="' + (cls || '') + '"><td>' + label + '</td><td class="num">' + RS.money(v) + '</td><td class="num muted">' + (pctOf ? RS.pct((/tot/.test(cls || '') ? v : Math.abs(v)) / pctOf) : '') + '</td></tr>';
    const sub = (obj) => (cfg().owner.detail >= 60 ? Object.entries(obj).filter((e) => e[1] > 0).map((e) => line('&nbsp;&nbsp;&nbsp;' + e[0], -e[1], 'subl', r.revenue)).join('') : '');
    const week = game.history.slice(-7), isWeek = game.day % 7 === 0 && week.length === 7;
    const wk = isWeek ? { rev: week.reduce((x, y) => x + y.revenue, 0), pr: week.reduce((x, y) => x + y.profit, 0), cov: week.reduce((x, y) => x + y.covers, 0) } : null;
    const rows = RS.quadrants(a.rows.filter((x) => x.it.course !== 'drink')).sort((x, y) => y.cm * y.qty - x.cm * x.qty);
    $('#app').innerHTML = '<div class="review"><header><div><h2>' + r.dayName + ' night, in the books</h2><p class="lede">Night ' + (r.day + 1) + ' at ' + esc(cfg().name) + '. ' + r.demand + ' guests came to the door, ' + r.covers + ' were fed' + (r.walkouts + r.turnedAway ? ', ' + (r.walkouts + r.turnedAway) + ' left hungry' : '') + '.</p></div>' +
      '<div class="navrow"><button class="ghost" data-act="tweak">Adjust before next service</button><button class="primary" data-act="next">Run ' + RS.DAYS[game.day % 7] + '</button><button class="ghost" data-act="week">Run the week fast</button></div></header>' + goalHTML() +
      (wk ? '<div class="goal"><b>The week</b><span>' + RS.money(wk.rev) + ' in sales, ' + RS.money(wk.pr) + ' profit (' + RS.pct(wk.rev ? wk.pr / wk.rev : 0) + '), ' + wk.cov + ' guests.</span></div>' : '') +
      '<div class="kpis big"><div><small>Sales</small><b>' + RS.money(r.revenue) + '</b></div><div><small>Profit</small><b class="' + (r.profit >= 0 ? 'good' : 'bad') + '">' + RS.money(r.profit) + '</b></div><div><small>Margin</small><b class="' + (r.profit >= 0 ? 'good' : 'bad') + '">' + RS.pct(r.margin) + '</b></div>' +
      '<div><small>Guests</small><b>' + r.covers + '</b></div><div><small>Check per guest</small><b>' + RS.money(r.avgCheck) + '</b></div><div><small>Guest mood</small><b>' + r.sat.toFixed(0) + '</b></div><div><small>Table turns</small><b>' + r.turns.toFixed(1) + '</b></div><div><small>Public rating</small><b class="' + (game.reputation >= game.reputationPrev ? 'good' : 'bad') + '">' + (game.reputation >= game.reputationPrev ? '&#9650; ' : '&#9660; ') + RS.stars(game.reputation).toFixed(1) + ' &#9733;</b></div></div>' +
      '<div class="cols"><div><div class="panel"><h3>What to change</h3>' + (a.notes.length ? a.notes.map((n, i) => '<div class="note"><span class="tag">' + n.tag + '</span><b>' + esc(n.title) + '</b>' + (n.value > 15 ? '<em class="val">about ' + RS.money(n.value) + ' a night</em>' : '') + '<p>' + esc(n.body) + '</p>' + (n.action ? '<button class="ghost apply" data-act="apply" data-i="' + i + '">' + esc(n.action.label) + '</button>' : '') + '</div>').join('') : '<p class="muted">Nothing urgent. A clean night.</p>') +
      (a.hidden ? '<p class="muted">' + a.hidden + ' smaller notes held back. Raise "how much you want to see" under Experience to get them.</p>' : '') + '</div>' +
      reviewsHTML(r) + buzzHTML(r) + delightHTML(r) + happyHTML(r) + (a.good.length ? '<div class="panel"><h3>What worked</h3><ul class="good-list">' + a.good.map((g) => '<li>' + esc(g) + '</li>').join('') + '</ul></div>' : '') + chartHTML() + '</div>' +
      '<div><div class="panel"><h3>Tonight\'s books</h3><table class="pl">' + line('Food', r.foodRev) + line('Drinks', r.bevRev) + line('Sales', r.revenue, 'tot') +
      line('Ingredients on the plate', -r.cogs, '', r.revenue) + line('Spoilage and overproduction', -r.waste, '', r.revenue) + (r.delight ? line('Delighters', -r.delight, '', r.revenue) + (cfg().owner.detail >= 60 ? r.delighters.map((d) => line('&nbsp;&nbsp;&nbsp;' + d.name, -d.cost, 'subl', r.revenue)).join('') : '') : '') +
      line('Labor', -r.laborTotal, '', r.revenue) + sub(r.labor) + line('Rent and overhead', -r.occTotal, '', r.revenue) + sub(r.occupancy) + line('Card fees', -r.card, '', r.revenue) + (r.ownerSave > 1 ? line('Saved by the owner\'s desk work', r.ownerSave, '', r.revenue) : '') + line('Profit', r.profit, 'tot ' + (r.profit >= 0 ? 'good' : 'bad'), r.revenue) + '</table>' +
      '<p class="hint">Prime cost (food plus labor) ' + RS.pct(r.primeCost) + '. Staff took home ' + RS.money(r.tips) + ' in tips.' + (r.discounts > 1 ? ' Deals and comps gave away ' + RS.money(r.discounts) + '.' : '') + '</p></div>' +
      (full ? '<div class="panel"><h3>Service</h3><dl class="kv"><dt>Wait for a table</dt><dd>' + r.seatWait.toFixed(1) + ' min</dd><dt>Wait for a server</dt><dd>' + r.greetWait.toFixed(1) + ' min</dd><dt>Mains ticket time</dt><dd>' + r.mainTicket.toFixed(1) + ' min</dd><dt>Late tickets</dt><dd>' + r.lateTickets + ' of ' + r.tickets + '</dd><dt>Servers on task</dt><dd>' + RS.pct(r.serverUtil) + '</dd><dt>Chairs filled at seated tables</dt><dd>' + RS.pct(r.seatFill) + '</dd><dt>Inventory lines</dt><dd>' + r.ingredients + '</dd><dt>Tables pushed together</dt><dd>' + r.joins + ' times</dd><dt>Left while tables sat empty</dt><dd class="' + (r.walkEmpty ? 'bad' : '') + '">' + r.walkEmpty + ' guests</dd><dt>Two-tops idle while groups waited</dt><dd>' + Math.round(r.idleSmallMin) + ' table-min</dd></dl>' +
        '<h4>Who came</h4>' + RS.DEMOS.filter((d) => r.demos[d.id]).sort((x, y) => r.demos[y.id] - r.demos[x.id]).map((d) => '<div class="bar"><span>' + d.label + '</span><i><b style="width:' + (r.demos[d.id] / r.demand * 100 / 0.5).toFixed(0) + '%;background:' + d.color + '"></b></i><em>' + r.demos[d.id] + '</em></div>').join('') + '</div>' : '') + '</div></div>' +
      (full ? '<div class="panel"><h3>The menu, plate by plate</h3><p class="hint"><b>Keeps</b> is what is left of the price after the ingredients are paid for. <b>Contribution</b> is that times the number sold: what the dish put toward rent and wages tonight. Each dish is then compared with the others in its course. <b>Star</b>: sells well and keeps a lot. <b>Crowd-pleaser</b>: sells well but keeps little, so it fills the room without filling the till. <b>Hidden gem</b>: keeps a lot but few people order it, so it is worth pushing. <b>Dead weight</b>: neither, and a candidate to cut.</p><div class="tablewrap"><table class="menu"><thead><tr><th>Item</th><th class="num">Sold</th><th class="num">Price</th><th class="num">Keeps</th><th class="num">Contribution</th><th></th></tr></thead><tbody>' +
        rows.map((x) => '<tr><td><b>' + esc(x.it.name) + '</b> <span class="muted">' + x.it.course + '</span></td><td class="num">' + x.qty + '</td><td class="num">' + RS.money(x.price) + '</td><td class="num">' + RS.money(x.cm) + '</td><td class="num">' + RS.money(x.cm * x.qty) + '</td><td><span class="chip q-' + x.quadKey + '">' + x.quad + '</span></td></tr>').join('') + '</tbody></table></div></div>' : '') + '</div>';
    window.scrollTo(0, 0); topBar();
  };

  /* ---------- events ---------- */
  const refreshLive = () => { const a = $('#aside'); if (a) a.innerHTML = aside(); const cr = $('#crowd'); if (cr) cr.innerHTML = crowd(); if (step === 2) drawPlan(); };
  document.addEventListener('input', (e) => {
    const el = e.target, path = el.dataset.path; if (!path || screen !== 'builder') return;
    if (el.type === 'range') { set(cfg(), path, Number(el.value));
      if (/^owner\.(cooking|business|vibe)$/.test(path)) { const o = cfg().owner, over = o.cooking + o.business + o.vibe - RS.OWNER_POINTS; if (over > 0) { set(cfg(), path, Number(el.value) - over); el.value = get(cfg(), path); } ownerPts(); } const v = $('[data-val="' + path + '"]'); if (v && path.startsWith('room.')) v.textContent = path.endsWith('pos') ? '' : el.value + ' m'; if (v && path === 'menu.priceAdj') v.textContent = (el.value > 0 ? '+' : '') + el.value + '%'; if (path.startsWith('room.') || path.startsWith('atmosphere.')) cfg().manualLayout = null; }
    else if (el.type === 'text') set(cfg(), path, el.value);
    else return;
    refreshLive();
  });
  document.addEventListener('change', (e) => {
    const el = e.target; if (screen !== 'builder') return;
    if (el.dataset.item) { cfg().menu.enabled[el.dataset.item] = el.checked; }
    else if (el.dataset.play !== undefined) { const id = el.dataset.play; cfg().plays = cfg().plays.filter((p) => p.itemId !== id); if (el.value) cfg().plays.push({ type: el.value, itemId: id, pct: 20 }); }
    else if (el.dataset.delight) { cfg().delighters[el.dataset.delight] = el.checked; }
    else if (el.tagName === 'SELECT' && el.dataset.path) { let v = el.value; if (v === 'true') v = true; else if (v === 'false') v = false; else if (v !== '' && !isNaN(v)) v = Number(v); set(cfg(), el.dataset.path, v); cfg().manualLayout = null; }
    else if (el.type === 'range' && step !== 2 && step !== 1) { /* fall through to re-render so dependent text updates */ }
    else return;
    const y = window.scrollY; renderBuilder(); window.scrollTo(0, y);
  });
  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-act]'); if (!el) return;
    const act = el.dataset.act, c = cfg(), y = window.scrollY;
    if (act === 'goto') { step = Number(el.dataset.i); renderBuilder(); window.scrollTo(0, 0); }
    else if (act === 'lock') { c.locks[el.dataset.path] = !c.locks[el.dataset.path]; renderBuilder(); window.scrollTo(0, y); }
    else if (act === 'step') { const p = el.dataset.path, d = Number(el.dataset.d), v = get(c, p) + d; if ((el.dataset.min !== undefined && v < Number(el.dataset.min)) || (el.dataset.max !== undefined && v > Number(el.dataset.max))) return; if (game.started && STRUCTURAL.test(p)) return; set(c, p, v); if (p.startsWith('tables.') || p.startsWith('room.')) c.manualLayout = null; renderBuilder(); window.scrollTo(0, y); }
    else if (act === 'cuisine') { if (game.started) return; c.cuisine = el.dataset.id; c.menu.enabled = null; RS.ensureMenu(c); renderBuilder(); }
    else if (act === 'preset') { RS.applyPreset(c, c.cuisine); renderBuilder(); }
    else if (act === 'grade') { c.buying[el.dataset.cat] = Number(el.dataset.g); renderBuilder(); window.scrollTo(0, y); }
    else if (act === 'auto') { c.manualLayout = null; drawPlan(); }
    else if (act === 'msize') { const k = el.dataset.k, cui = RS.cuisine(c); const seen = {}; cui.items.forEach((i) => { let on = k === 'all' ? true : !!i.core; if (k === 'tight' && on) { seen[i.course] = (seen[i.course] || 0) + 1; on = seen[i.course] <= { starter: 3, main: 4, side: 1, dessert: 2, drink: 5 }[i.course]; } c.menu.enabled[i.id] = on; }); renderBuilder(); window.scrollTo(0, y); }
    else if (act === 'open') startNight();
    else if (act === 'tab') { tab = el.dataset.t; renderService(); }
    else if (act === 'speed') { if (el.dataset.s === 'pause') paused = !paused; else { speed = el.dataset.s; paused = false; } updateSide(); }
    else if (act === 'next') startNight();
    else if (act === 'week') { speed = 'week'; startNight(); }
    else if (act === 'tweak') { screen = 'builder'; step = 4; renderBuilder(); window.scrollTo(0, 0); }
    else if (act === 'apply') { const n = lastAdvice.notes[Number(el.dataset.i)]; if (n && n.action && !n.applied) { n.action.apply(c); n.applied = true; el.textContent = 'Done for tomorrow'; el.disabled = true; el.classList.add('applied'); } }
    else if (act === 'restart') { if (el.dataset.armed) { delete el.dataset.armed; el.textContent = 'Start over'; game = RS.newGame(); RS.applyPreset(game.cfg, 'italian'); game.cfg.name = 'Your Restaurant'; screen = 'builder'; step = 0; sim = null; renderBuilder(); } else { el.dataset.armed = '1'; el.textContent = 'Click again to wipe this restaurant'; setTimeout(() => { if (el.dataset.armed) { delete el.dataset.armed; el.textContent = 'Start over'; } }, 4000); } }
  });

  // Canvas: pick a table during service, drag tables in the layout editor.
  let drag = null;
  const hitTable = (cv, ev) => {
    const rect = cv.getBoundingClientRect(), v = RS.view(cv, cfg(), screen === 'service'), p = v.inv(ev.clientX - rect.left, ev.clientY - rect.top);
    const t = layout.tables.find((t) => t.bar ? Math.hypot(p.x - t.cx, p.y - t.cy) < 0.8 : (p.x >= t.x - 0.35 && p.x <= t.x + t.w + 0.35 && p.y >= t.y - 0.45 && p.y <= t.y + t.h + 0.45));
    return { t, p };
  };
  document.addEventListener('pointerdown', (e) => {
    if (e.target.id === 'floor') { const h = hitTable(e.target, e); selStaff = sim ? sim.agents.concat(sim.cookList).filter((a) => Math.hypot(a.x - h.p.x, a.y - h.p.y) < 0.55).sort((a, b) => Math.hypot(a.x - h.p.x, a.y - h.p.y) - Math.hypot(b.x - h.p.x, b.y - h.p.y))[0] || null : null; selTable = selStaff ? null : (h.t || null); tab = 'tables'; renderService(); }
    else if (e.target.id === 'plan') { const h = hitTable(e.target, e); if (h.t && !h.t.bar) { drag = { t: h.t, dx: h.p.x - h.t.x, dy: h.p.y - h.t.y }; e.target.setPointerCapture(e.pointerId); } }
  });
  document.addEventListener('pointermove', (e) => {
    if (!drag || e.target.id !== 'plan') return;
    const h = hitTable(e.target, e), c = cfg();
    c.manualLayout = c.manualLayout || {};
    layout.tables.forEach((t) => { if (!t.bar && !c.manualLayout[t.id]) c.manualLayout[t.id] = { x: t.x, y: t.y }; });
    c.manualLayout[drag.t.id] = { x: h.p.x - drag.dx, y: h.p.y - drag.dy };
    drawPlan();
  });
  document.addEventListener('pointerup', () => { drag = null; });
  window.addEventListener('resize', () => { if (screen === 'builder' && step === 2) drawPlan(); });

  /* ---------- loop ---------- */
  let last = performance.now(), sideAt = 0;
  const frame = (now) => {
    const dtReal = Math.min(0.1, (now - last) / 1000); last = now;
    if (screen === 'service' && sim) {
      if (!paused) {
        let m = dtReal * SPEEDS[speed];
        while (m > 0 && sim && !sim.done) { const d = Math.min(0.08, m); sim.step(d); m -= d; }
        if (sim && sim.done) endNight();
      }
      const cv = $('#floor');
      if (cv && sim) { RS.draw(cv, cfg(), layout, sim, selTable, selStaff); if (now - sideAt > 300) { sideAt = now; updateSide(); } }
    }
    requestAnimationFrame(frame);
  };

  RS.boot = () => { RS.applyPreset(game.cfg, 'italian'); game.cfg.name = 'Your Restaurant'; renderBuilder(); requestAnimationFrame(frame); };
})();
