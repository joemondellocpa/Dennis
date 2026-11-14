/* Shared config, constants and helpers. Everything hangs off window.RS. */
window.RS = window.RS || {};

RS.clamp = (v, a, b) => Math.max(a, Math.min(b, v));
RS.lerp = (a, b, t) => a + (b - a) * t;
RS.money = (v) => (v < 0 ? '-$' : '$') + Math.abs(Math.round(v)).toLocaleString('en-US');
RS.pct = (v) => (isFinite(v) ? (v * 100).toFixed(1) : '0.0') + '%';
RS.clock = (t) => {
  const m = Math.floor(17 * 60 + t);
  const h = Math.floor(m / 60) % 24, mm = m % 60;
  return ((h + 11) % 12 + 1) + ':' + String(mm).padStart(2, '0') + (h >= 12 ? ' pm' : ' am');
};
RS.DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
RS.DOW_DEMAND = [0.6, 0.66, 0.76, 0.92, 1.22, 1.32, 0.82];

/* Seeded RNG so a night can be replayed. */
RS.rng = (seed) => {
  let s = seed >>> 0;
  const r = () => {
    s |= 0; s = (s + 0x6D2B79F5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  r.range = (a, b) => a + r() * (b - a);
  r.pick = (arr) => arr[Math.floor(r() * arr.length)];
  r.weighted = (arr, wf) => {
    let tot = 0; const ws = arr.map((x) => { const w = Math.max(0, wf(x)); tot += w; return w; });
    if (tot <= 0) return arr[0];
    let x = r() * tot;
    for (let i = 0; i < arr.length; i++) { x -= ws[i]; if (x <= 0) return arr[i]; }
    return arr[arr.length - 1];
  };
  return r;
};

/* Who walks in. "likes" are tastes on the four atmosphere axes plus service touch, -1..1. */
RS.DEMOS = [
  { id: 'date', label: 'Date night', color: '#e57fa0', sizes: [2], ages: '28 to 45', spend: 1.1, alc: 1.2, patience: 1.0, linger: 1.25, base: 1.2,
    likes: { light: -0.8, noise: -0.6, formality: 0.3, spacing: 0.8, touch: -0.1 } },
  { id: 'business', label: 'Business dinner', color: '#6fa8dc', sizes: [2, 3, 4, 4, 6], ages: '35 to 60', spend: 1.4, alc: 1.1, patience: 0.8, linger: 0.9, base: 0.7,
    likes: { light: 0, noise: -0.9, formality: 0.9, spacing: 0.7, touch: 0.5 } },
  { id: 'family', label: 'Family', color: '#f2b84b', sizes: [3, 4, 4, 5, 6], ages: 'kids to grandparents', spend: 0.8, alc: 0.45, patience: 0.7, linger: 0.8, base: 0.8,
    likes: { light: 0.8, noise: 0.5, formality: -0.9, spacing: 0.1, touch: 0.2 } },
  { id: 'friends', label: 'Friends out', color: '#7fcf8a', sizes: [3, 4, 4, 4, 5, 6, 6, 8], ages: '24 to 40', spend: 1.0, alc: 1.5, patience: 1.0, linger: 1.3, base: 1.0,
    likes: { light: -0.2, noise: 0.9, formality: -0.5, spacing: -0.4, touch: -0.2 } },
  { id: 'solo', label: 'Solo regular', color: '#b89ae8', sizes: [1], ages: '30 to 65', spend: 0.9, alc: 0.9, patience: 1.1, linger: 0.7, base: 0.35,
    likes: { light: 0, noise: -0.2, formality: -0.2, spacing: 0, touch: 0.6 } },
  { id: 'celebration', label: 'Celebration', color: '#ff8c5a', sizes: [2, 4, 4, 6, 6, 8], ages: 'mixed', spend: 1.3, alc: 1.4, patience: 0.9, linger: 1.4, base: 0.5,
    likes: { light: -0.1, noise: 0.3, formality: 0.6, spacing: 0.3, touch: 0.9 } },
  { id: 'tourists', label: 'Visitors', color: '#5fd0c8', sizes: [2, 2, 4], ages: '30 to 70', spend: 1.0, alc: 0.8, patience: 0.9, linger: 1.0, base: 0.5,
    likes: { light: 0.5, noise: 0.1, formality: 0, spacing: 0.2, touch: 0.6 } },
  { id: 'foodie', label: 'Food lovers', color: '#d9d24a', sizes: [2, 2, 2, 4], ages: '27 to 55', spend: 1.25, alc: 1.15, patience: 1.2, linger: 1.1, base: 0.45,
    likes: { light: 0, noise: -0.1, formality: 0.1, spacing: 0.1, touch: 0.4 } }
];

/* What the concept itself pulls in, before the room has its say. */
RS.CUISINE_DRAW = {
  italian: { family: 1.5, date: 1.3, friends: 1.2, business: 0.7 },
  steakhouse: { business: 2.6, celebration: 1.7, date: 1.0, family: 0.55, friends: 0.7, foodie: 0.7 },
  american: { friends: 1.6, family: 1.2, solo: 1.3, business: 0.8 },
  japanese: { foodie: 2.0, date: 1.5, business: 1.3, family: 0.5, solo: 1.3 },
  french: { date: 1.8, celebration: 1.4, foodie: 1.5, family: 0.45, tourists: 1.3 }
};
RS.demoWeight = (d, cfg, hasBar) => {
  const a = cfg.atmosphere, A = { light: a.light / 100, noise: a.noise / 100, formality: a.formality / 100, spacing: a.spacing / 100 };
  let e = 0; Object.keys(A).forEach((k) => { e += d.likes[k] * (A[k] - 0.5); });
  let w = d.base * Math.exp(e * 1.6) * ((RS.CUISINE_DRAW[cfg.cuisine] || {})[d.id] || 1);
  const price = cfg.priceTier / 100 - 0.5, src = cfg.sourcing / 100 - 0.5, alc = cfg.menu.alcoholFocus / 100 - 0.5;
  // Price point: expense accounts and occasions follow it up, families and big casual groups drop away.
  w *= Math.exp(price * ({ business: 2.2, celebration: 1.6, foodie: 0.8, date: 0.5, family: -2.0, friends: -1.0, solo: -0.6 }[d.id] || 0));
  w *= Math.exp(src * ({ foodie: 2.4, date: 0.4, tourists: 0.3 }[d.id] || 0));
  w *= Math.exp(alc * ({ friends: 1.0, date: 0.5, family: -1.2 }[d.id] || 0));
  if (d.id === 'solo' && !hasBar) w *= 0.5;
  if (d.id === 'friends' && hasBar) w *= 1.15;
  return w;
};

/* Why this particular table came out tonight. */
RS.REASONS = {
  date: ['Date night', 'First date', 'Anniversary dinner', 'Sitter booked, finally out'],
  business: ['Client dinner', 'Team dinner on the company card', 'Closing a deal', 'Interviewing a hire over dinner'],
  family: ['Family night out', 'Grandparents are in town', 'Nobody wanted to cook', 'Kid picked the place'],
  friends: ['Catching up with friends', 'Dinner before a night out', 'Monthly dinner club', 'Old roommates reunion'],
  solo: ['Regular, here most weeks', 'Regular, always the same seat', 'In town for work, eating alone'],
  celebration: ['Birthday', 'Anniversary', 'Promotion', 'Graduation', 'Engagement'],
  tourists: ['Visiting, found you on a map', 'Hotel concierge sent them', 'Read a review before the trip'],
  foodie: ['Came for one specific dish', 'Following the chef', 'Heard about where you buy your ingredients', 'Working through the best-of list']
};
RS.visitReason = (demo, game, rnd) => {
  const cfg = game.cfg, x = rnd();
  if (game.day < 10 && x < 0.2 && demo.id !== 'solo') return 'Curious about the new place';
  if (game.day >= 5 && x < 0.2 + game.reputation * 0.22) return game.reputation > 0.55 && rnd() < 0.5 ? 'A friend recommended it' : 'Regulars, back again';
  if (cfg.plays.some((p) => p.type === 'discount' || p.type === 'bogo') && x > 0.85) return 'Came for the deal';
  if (cfg.room.bar.on && x > 0.93 && demo.id !== 'family') return 'Came for a drink, stayed for dinner';
  return rnd.pick(RS.REASONS[demo.id]);
};

/* Where the owner spends the night, and what they are good at. A skill counts in full only in a job that uses it. */
RS.OWNER_ROLES = [
  { id: 'floor', label: 'Working the room', uses: 'vibe', desc: 'You run the floor and stop at tables. No floor manager on payroll. Uses vibe-making.', bio: 'Moving through the dining room, stopping at tables.' },
  { id: 'greeter', label: 'At the door', uses: 'vibe', desc: 'You greet and seat. Guests wait more patiently and feel known. No floor manager on payroll. Uses vibe-making.', bio: 'At the host stand, greeting every party by name where possible.' },
  { id: 'chef', label: 'Head chef', uses: 'cooking', desc: 'Your food, your name on it. No head chef salary. The plates are as good as your cooking, for better or worse.', bio: 'Running the kitchen. Every plate goes past them.' },
  { id: 'kitchen', label: 'On the line', uses: 'cooking', desc: 'An extra pair of hands in the kitchen. Tickets move faster. You still pay a chef and a manager.', bio: 'On the line, jumping onto whichever station is buried.' },
  { id: 'office', label: 'In the office', uses: 'business', desc: 'Purchasing, scheduling, marketing. Lower costs and a fuller book. You pay a chef and a manager to run service.', bio: 'In the back office with the invoices.' },
  { id: 'handsoff', label: 'Completely hands off', uses: null, desc: 'You own it and someone else runs it. Add a general manager to the chef and floor manager. None of your skills reach the room.', bio: 'Not in the building.' }
];
RS.OWNER_POINTS = 180;
RS.ownerEff = (cfg) => {
  const o = cfg.owner, role = RS.OWNER_ROLES.find((x) => x.id === o.role) || RS.OWNER_ROLES[0];
  const f = (k) => (o[k] / 100) * (role.id === 'handsoff' ? 0 : (role.uses === k ? 1 : 0.2));
  return { role: role.id, cook: f('cooking'), biz: f('business'), vibe: f('vibe'), cooking: o.cooking / 100, vibeRaw: o.vibe / 100 };
};
RS.ownerLabor = (cfg) => {
  const r = cfg.owner.role, out = {};
  if (r !== 'floor' && r !== 'greeter') out['Floor manager'] = 220;
  if (r !== 'chef') out['Head chef'] = 280;
  if (r === 'handsoff') out['General manager'] = 200;
  return out;
};

/* The people on the schedule. Stable from night to night. */
const FIRST = ['Maya', 'Luis', 'Priya', 'Dante', 'Sofia', 'Marcus', 'Elena', 'Tomas', 'Aisha', 'Ben', 'Carmen', 'Jun', 'Nadia', 'Theo', 'Rosa', 'Kwame', 'Ines', 'Viktor', 'Lena', 'Omar', 'Grace', 'Hiro', 'Paloma', 'Dev'];
const LAST = 'ABCDGHJKLMNOPRSTVW';
const BIO = {
  server: ['Remembers every regular\'s drink.', 'Studying for a sommelier exam on days off.', 'Came over from a hotel dining room.', 'Fastest hands on the floor, working on the small talk.', 'Actor between auditions. Guests love the specials recital.', 'Sells more dessert than anyone on the team.'],
  busser: ['First restaurant job. Wants to be a server by summer.', 'Never lets a water glass run dry.', 'Works doubles to pay for culinary school.', 'Quiet, quick, and knows every table number cold.'],
  host: ['Knows half the neighborhood by name.', 'Can quote a wait time to the minute.', 'Runs the reservation book like air traffic control.'],
  bartender: ['Built the cocktail list.', 'Twelve regulars come in just to sit at this bar.', 'Pours fast and talks slow.', 'Competes in cocktail competitions.'],
  cook: ['Came up through hotel banquets.', 'Culinary school grad on a first line job.', 'Started as the dishwasher here.', 'Ten years on a grill and the forearms to prove it.', 'Staged in three countries before landing here.', 'Calm when the board is full.'],
  owner: ['You. Tonight you are working the room.']
};
RS.persona = (role, i, cfg, extra) => {
  const r = RS.rng((role.charCodeAt(0) * 131 + role.length * 17 + i * 977 + cfg.cuisine.length * 53) >>> 0);
  r(); r();
  const exp = cfg.staff.experience / 100, style = cfg.staff.style / 100;
  if (role === 'owner') { const o = RS.OWNER_ROLES.find((x) => x.id === cfg.owner.role) || RS.OWNER_ROLES[0]; return { name: 'The owner', title: 'Owner, ' + o.label.toLowerCase(), years: null, bio: o.bio }; }
  const years = Math.max(0.5, Math.round(RS.lerp(0.6, 13, exp) * r.range(0.5, 1.6) * 2) / 2);
  const name = FIRST[Math.floor(r() * FIRST.length + i * 5) % FIRST.length] + ' ' + LAST[Math.floor(r() * LAST.length)] + '.';
  const title = { server: 'Server', busser: 'Busser and food runner', host: 'Host', bartender: 'Bartender', cook: (extra && extra.lead ? 'Sous chef' : 'Line cook') + (extra && extra.station ? ', ' + RS.STATION_LABEL[extra.station].toLowerCase() : '') }[role];
  let bio = r.pick(BIO[role]);
  if (role === 'server' || role === 'host') bio += style > 0.6 ? ' Trained in formal service.' : (style < 0.4 ? ' On a first-name basis with guests by the second visit.' : '');
  return { name, title, years, bio };
};
RS.stationRect = (room, n, i) => { const sw = (room.w - 0.6) / Math.max(1, n); return { x: 0.3 + i * sw, y: -RS.KITCHEN_DEPTH + 0.35, w: sw - 0.3, h: 1.25 }; };

RS.DELIGHTERS = [
  { id: 'bread', name: 'House-baked bread', prepMin: 90, perCover: 0.45, sat: 4, desc: 'Baked before the shift. Costs a baker 90 minutes and about 45 cents a guest.' },
  { id: 'amuse', name: 'Amuse-bouche', prepMin: 60, perCover: 0.9, sat: 3, fancyBonus: 3, desc: 'One bite from the chef before the first course. Lands harder in a formal room.' },
  { id: 'water', name: 'Filtered still and sparkling on the house', prepMin: 0, perCover: 0.15, sat: 1.5, desc: 'Costs almost nothing. Gives up bottled water sales.' },
  { id: 'sweets', name: 'Something sweet with the check', prepMin: 45, perCover: 0.6, sat: 3, tip: 0.01, desc: 'A last impression. Nudges tips and return visits.' },
  { id: 'memory', name: 'Guest memory briefing', prepMin: 15, perCover: 0, sat: 2, regularBonus: 6, desc: 'Staff review tonight\'s regulars and occasions before doors open. Software does the remembering.' },
  { id: 'occasion', name: 'Celebration touch', prepMin: 0, perCover: 0, sat: 0, celebrationBonus: 10, celebrationCost: 4, desc: 'A candle and a comped dessert for birthday and anniversary tables.' }
];

RS.STATION_CAP = { grill: 6, saute: 6, fry: 4, oven: 6, cold: 8, pastry: 6, sushi: 5 };
RS.STATION_LABEL = { grill: 'Grill', saute: 'Saute', fry: 'Fry', oven: 'Oven', cold: 'Cold / garde manger', pastry: 'Pastry', sushi: 'Sushi counter', bar: 'Bar' };
RS.TABLE_DIM = { 2: [0.75, 0.75], 4: [1.2, 0.8], 6: [1.8, 0.9], 8: [2.4, 1.0] };
RS.KITCHEN_DEPTH = 3.4;

RS.defaultConfig = () => ({
  name: 'Your Restaurant',
  cuisine: 'italian',
  priceTier: 50,          // casual pricing <> destination pricing
  sourcing: 50,           // commodity <> premium / local
  atmosphere: { light: 35, noise: 55, formality: 45, spacing: 45, tableSize: 50 },
  locks: {},              // path -> true, the non-negotiables
  room: {
    w: 16, h: 11,
    entrance: { wall: 'S', pos: 0.5 },
    kitchenDoor: { pos: 0.7 },
    restroom: { wall: 'E', pos: 0.2 },
    line: 'standard',
    bar: { on: true, wall: 'W', pos: 0.5, seats: 8, vibe: 'cocktail' }
  },
  tables: { 2: 8, 4: 7, 6: 2, 8: 0 },
  manualLayout: null,     // {tableIndex: {x,y}} once the player drags
  diner: { touch: 55, pace: 50 },
  staff: { style: 45, experience: 55, servers: 4, bussers: 2, hosts: 1, cooks: 4, bartenders: 1 },
  owner: { role: 'floor', cooking: 50, business: 50, vibe: 50, detail: 70 },
  menu: { enabled: null, alcoholFocus: 55, priceAdj: 0 },
  plays: [],              // {type:'push'|'discount'|'bogo'|'special', itemId, pct}
  delighters: {},
  goal: { type: 'margin', target: 12, nights: 14, debt: 20000 }
});

RS.PRESETS = {
  italian: { name: 'Trattoria Lucia', room: { w: 18, h: 11 }, priceTier: 45, sourcing: 55,
    atmosphere: { light: 40, noise: 65, formality: 35, spacing: 35, tableSize: 45 }, tables: { 2: 8, 4: 8, 6: 2, 8: 1 },
    diner: { touch: 60, pace: 60 }, staff: { style: 30, experience: 55, servers: 4, bussers: 2, hosts: 1, cooks: 4, bartenders: 1 }, bar: { on: true, vibe: 'wine', seats: 8 } },
  steakhouse: { name: 'The Chop Room', room: { w: 21, h: 13 }, priceTier: 75, sourcing: 70,
    atmosphere: { light: 20, noise: 40, formality: 75, spacing: 65, tableSize: 70 }, tables: { 2: 6, 4: 8, 6: 2, 8: 1 },
    diner: { touch: 75, pace: 65 }, staff: { style: 75, experience: 75, servers: 5, bussers: 2, hosts: 1, cooks: 5, bartenders: 1 }, bar: { on: true, vibe: 'cocktail', seats: 10 } },
  american: { name: 'Common Table', room: { w: 18, h: 12 }, priceTier: 50, sourcing: 60,
    atmosphere: { light: 55, noise: 70, formality: 30, spacing: 40, tableSize: 50 }, tables: { 2: 8, 4: 7, 6: 3, 8: 1 },
    diner: { touch: 45, pace: 45 }, staff: { style: 25, experience: 50, servers: 4, bussers: 2, hosts: 1, cooks: 4, bartenders: 1 }, bar: { on: true, vibe: 'cocktail', seats: 10 } },
  japanese: { name: 'Kumo', room: { w: 16, h: 11 }, priceTier: 65, sourcing: 80,
    atmosphere: { light: 30, noise: 25, formality: 65, spacing: 55, tableSize: 40 }, tables: { 2: 8, 4: 6, 6: 2, 8: 0 },
    diner: { touch: 65, pace: 55 }, staff: { style: 70, experience: 70, servers: 3, bussers: 1, hosts: 1, cooks: 3, bartenders: 1 }, bar: { on: true, vibe: 'wine', seats: 8 } },
  french: { name: 'Chez Odette', room: { w: 16, h: 11 }, priceTier: 60, sourcing: 65,
    atmosphere: { light: 30, noise: 45, formality: 60, spacing: 30, tableSize: 40 }, tables: { 2: 10, 4: 6, 6: 2, 8: 0 },
    diner: { touch: 65, pace: 70 }, staff: { style: 65, experience: 65, servers: 3, bussers: 1, hosts: 1, cooks: 3, bartenders: 1 }, bar: { on: true, vibe: 'wine', seats: 6 } }
};

RS.applyPreset = (cfg, cuisineId) => {
  const p = RS.PRESETS[cuisineId]; if (!p) return cfg;
  cfg.cuisine = cuisineId; cfg.name = p.name; cfg.priceTier = p.priceTier; cfg.sourcing = p.sourcing;
  cfg.atmosphere = Object.assign({}, p.atmosphere); cfg.tables = Object.assign({}, p.tables);
  cfg.diner = Object.assign({}, p.diner); cfg.staff = Object.assign({}, p.staff);
  Object.assign(cfg.room.bar, p.bar); cfg.room.w = p.room.w; cfg.room.h = p.room.h; cfg.manualLayout = null; cfg.plays = []; cfg.menu.enabled = null;
  RS.ensureMenu(cfg);
  return cfg;
};

RS.cuisine = (cfg) => RS.CUISINES[cfg.cuisine];
RS.item = (cfg, id) => RS.cuisine(cfg).items.find((i) => i.id === id);

/* Make sure cfg.menu.enabled matches the chosen cuisine. */
RS.ensureMenu = (cfg) => {
  const c = RS.cuisine(cfg);
  const en = cfg.menu.enabled;
  if (!en || !c.items.some((i) => en[i.id] !== undefined)) {
    cfg.menu.enabled = {}; c.items.forEach((i) => { cfg.menu.enabled[i.id] = !!i.core; });
    cfg.plays = [];
  }
};

/* Items on tonight's menu, with a special added if one is being run. */
RS.activeItems = (cfg) => {
  RS.ensureMenu(cfg);
  const c = RS.cuisine(cfg);
  const specials = cfg.plays.filter((p) => p.type === 'special').map((p) => p.itemId);
  return c.items.filter((i) => cfg.menu.enabled[i.id] || specials.includes(i.id));
};

RS.priceMult = (cfg) => RS.lerp(0.8, 1.5, cfg.priceTier / 100) * (1 + cfg.menu.priceAdj / 100);
RS.costMult = (cfg) => RS.lerp(0.86, 1.34, cfg.sourcing / 100);
RS.playFor = (cfg, id, type) => cfg.plays.find((p) => p.itemId === id && (!type || p.type === type));

RS.itemPrice = (cfg, it) => {
  let p = it.price * RS.priceMult(cfg);
  if (RS.playFor(cfg, it.id, 'special')) p *= 1.1;
  const d = RS.playFor(cfg, it.id, 'discount'); if (d) p *= 1 - (d.pct || 20) / 100;
  return Math.round(p * 2) / 2;
};
RS.ingredientCount = (cfg) => { const s = new Set(); RS.activeItems(cfg).forEach((i) => i.ingredients.forEach((g) => s.add(g))); return s.size; };
/* More inventory lines means more spoilage, more ordering, smaller buys. Past ~45 lines it starts to bite. */
RS.complexityMult = (cfg) => 1 + Math.max(0, RS.ingredientCount(cfg) - 45) * 0.0035;
RS.itemCost = (cfg, it) => it.cost * RS.costMult(cfg) * RS.complexityMult(cfg);

RS.seatCount = (cfg) => [2, 4, 6, 8].reduce((s, n) => s + n * (cfg.tables[n] || 0), 0) + (cfg.room.bar.on ? cfg.room.bar.seats : 0);
RS.suggestStaff = (cfg) => {
  const seats = RS.seatCount(cfg), touch = cfg.diner.touch / 100;
  const active = RS.activeItems(cfg).filter((i) => i.course !== 'drink');
  const alacarte = active.filter((i) => i.prep === 'alacarte').length;
  return {
    servers: Math.max(2, Math.ceil(seats / RS.lerp(24, 12, touch))),
    bussers: Math.max(1, Math.round(seats / 35)),
    hosts: 1,
    cooks: Math.max(2, Math.round(2 + seats / 30 + alacarte / 8)),
    bartenders: cfg.room.bar.on ? 1 : 0
  };
};

/* Goal + money carried across nights. */
RS.newGame = () => ({ cfg: RS.defaultConfig(), day: 0, reputation: 0.5, cash: 0, debtLeft: 0, history: [], started: false });
