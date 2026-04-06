import random
import math
import heapq as _heapq
from collections import deque
from .world import World, WorldGenerator, WORLD_W, WORLD_H, WORLD_D, CHUNK_SIZE
from .cells import CellType, CELL_PROPS
from .physics import PhysicsEngine
from .organism import Organism, OrganismPool
from .genetics import Genome, BodyPlan
from .behavior import BehaviorEvaluator, load_all_behaviors, mutate_behavior_file

class Simulation:
    def __init__(self, seed: int = 42, initial_count: int = 100, spawning_density: int = 3):
        random.seed(seed)
        self.spawning_density = max(1, min(5, spawning_density))

        # Core systems
        self.world = World()
        self.pool = OrganismPool()
        self.physics = PhysicsEngine(self.world)
        self.evaluator = BehaviorEvaluator()

        # State
        self.tick_count = 0
        self.running = True
        self.paused = False
        self.species_counter = 0

        # Species registry: species_id -> {'genome_snapshot': Genome, 'first_tick': int, 'extinct_tick': int|None}
        self.species_registry: dict = {}

        # Rolling gene history snapshots (200 ticks max)
        self._gene_history: deque = deque(maxlen=200)
        self._regen_heap: list = []   # (respawn_tick, x, y, z, cell_type_int)
        self._heapq = _heapq

        # Init
        load_all_behaviors()
        WorldGenerator().generate_default(self.world)
        self._seed_initial_organisms(count=initial_count)

    def _seed_initial_organisms(self, count: int):
        """Place starter organisms on the soil surface.

        Size distribution is intentionally skewed toward small organisms so the
        ecosystem starts with abundant prey and a few large predators:
          50% tiny  (size 1–5):  cheap, fast, eat soil — the base of the food chain
          30% small (size 5–15): generalist survivors
          15% medium(size 15–30): emerging predators / large herbivores
           5% large (size 30–50): apex predators, seed the predation niche early
        """
        # Cluster-based spawning: density 1 = spread, density 5 = tight clusters
        # Choose a set of cluster centers, then spawn each organism near one
        import math as _math
        n_clusters = max(2, count // 8)
        cluster_centers = [
            (random.randint(50, WORLD_W - 50), random.randint(50, WORLD_H - 50))
            for _ in range(n_clusters)
        ]
        # Cluster radius: density 1 → whole map, density 5 → 60 cells
        cluster_radius = int(500 / (self.spawning_density ** 0.8))

        for i in range(count):
            cx, cy = random.choice(cluster_centers)
            x = max(0, min(WORLD_W - 1, cx + random.randint(-cluster_radius, cluster_radius)))
            y = max(0, min(WORLD_H - 1, cy + random.randint(-cluster_radius, cluster_radius)))
            z = self._find_surface_z(x, y)
            if z is None:
                continue
            genome = Genome.random_genome()

            # Biased size distribution — size gene dominant allele controls size tier
            size_roll = random.random()
            if size_roll < 0.50:               # tiny  (1-5 cells)
                sv = random.randint(1, 26)
            elif size_roll < 0.80:             # small (5-15 cells)
                sv = random.randint(27, 77)
            elif size_roll < 0.95:             # medium (15-30 cells)
                sv = random.randint(78, 153)
            else:                              # large (30-50 cells)
                sv = random.randint(154, 255)
            genome._alleles['size'] = (sv, random.randint(0, sv))

            # Large organisms seed predation; small organisms seed flocking / prey traits
            if size_roll >= 0.80:
                genome._alleles['can_attack'] = (random.randint(160, 255), random.randint(128, 200))
            else:
                genome._alleles['flock_behavior'] = (random.randint(128, 220), random.randint(100, 200))

            # Bias lung/gill to match spawn terrain
            spawn_cell = self.world.get_cell(x, y, z - 1)
            if spawn_cell == CellType.WATER:
                genome._alleles['lung_ratio'] = (random.randint(0, 80), random.randint(0, 80))
            else:
                genome._alleles['lung_ratio'] = (random.randint(150, 255), random.randint(150, 255))

            org = Organism(genome, x, y, z + 1, species_id=self.species_counter)
            self.species_counter += 1
            org.state.calories = org.body.calorie_capacity * 0.9
            self.pool.add(org)
            self.species_registry[org.species_id] = {
                'genome_snapshot': org.genome,
                'first_tick': 0,
                'extinct_tick': None,
            }

    def _find_surface_z(self, x, y) -> int | None:
        """Return z of the highest non-AIR cell at (x,y), or None if all air."""
        for z in range(WORLD_D - 1, -1, -1):
            if self.world.get_cell(x, y, z) != CellType.AIR:
                return z
        return None

    def step(self):
        """Advance simulation by one tick."""
        self.tick_count += 1

        # Snapshot living list ONCE — reused by all per-organism calls this tick
        living_now = self.pool.living()

        # 1. Update active chunks from organism positions
        active_chunks = set()
        for org in living_now:
            cx = org.state.x // CHUNK_SIZE
            cy = org.state.y // CHUNK_SIZE
            cz = org.state.z // CHUNK_SIZE
            active_chunks.add((cx, cy, cz))
            self.world.mark_active(cx, cy, cz)

        # 2. Physics tick (fluid spreading, gravity)
        # Only every 3 ticks for performance
        if self.tick_count % 3 == 0:
            self.physics.tick(active_chunks)

        # Vegetation growth (every 3 ticks to keep groves alive and expanding)
        if self.tick_count % 3 == 0:
            self._grow_vegetation()

        # 3. Process each organism
        dead_ids = []
        new_organisms = []

        for org in living_now:
            result = self._process_organism(org, living_now)
            if result == 'dead':
                dead_ids.append(org.id)
            elif result is not None and isinstance(result, Organism):
                new_organisms.append(result)

        # 4. Remove dead, add newborns
        for oid in dead_ids:
            self.pool.remove(oid)
        for baby in new_organisms:
            self.pool.add(baby)

        # 5. Cull if over limit
        self.pool.cull_to_limit()

        # Regenerate consumed food cells — prevents permanent depletion
        _now = self.tick_count
        while self._regen_heap and self._regen_heap[0][0] <= _now:
            _, rx, ry, rz, rct = self._heapq.heappop(self._regen_heap)
            if self.world.get_cell(rx, ry, rz) == int(CellType.AIR):
                self.world.set_cell(rx, ry, rz, rct)

        # Sample gene averages every 5 ticks for the gene screen
        if self.tick_count % 5 == 0:
            living_snapshot = self.pool.living()
            if living_snapshot:
                from .genetics import Genome
                snapshot = {}
                for gene in Genome.GENES:
                    vals = [o.genome.get_dominant_allele(gene) for o in living_snapshot]
                    snapshot[gene] = sum(vals) / len(vals)
                self._gene_history.append((self.tick_count, snapshot))

    def get_gene_history(self):
        """Return list of (tick, {gene: avg_dominant}) snapshots."""
        return list(self._gene_history)

    def _process_organism(self, org: Organism, living_now: list):
        """
        Process one organism for one tick.
        Returns: 'dead' | Organism (newborn) | None
        """
        state = org.state
        body = org.body

        # Age
        state.age += 1

        # Passive calorie burn
        state.calories -= body.calorie_cost_per_tick

        # Die of starvation
        if state.calories <= 0:
            state.alive = False
            return 'dead'

        # Die of old age (rough: size-dependent max age)
        max_age = 5000 + body.total_cells * 500
        if state.age > max_age:
            state.alive = False
            return 'dead'

        # Ensure organism rests on the correct surface every tick.
        # Without this, an organism that eats the cell below it floats in mid-air
        # until it happens to move, starving next to food it cannot reach.
        self._apply_gravity(org)

        # Update medium (in water?)
        cell_here = self.world.get_cell(state.x, state.y, state.z)
        state.in_water = (cell_here == CellType.WATER)

        # Drown if has lung and in water (gradual)
        if state.in_water and body.has_lung:
            state.calories -= body.calorie_cost_per_tick * 2  # drowning costs extra

        # Dry out if has gill and not in water
        if not state.in_water and body.has_gill:
            state.calories -= body.calorie_cost_per_tick * 1.5

        # tree_affinity: gain calories when adjacent to WOOD cells
        if org.genome.get_dominant_allele('tree_affinity') > 127:
            for _, _, _, neighbor_ct in self.world.get_neighbors(state.x, state.y, state.z):
                if neighbor_ct == CellType.WOOD:
                    # Bonus = 30% of tick cost, min 1.5 cal — makes staying near trees worthwhile
                    bonus = max(1.5, body.calorie_cost_per_tick * 0.30)
                    state.calories = min(body.calorie_capacity, state.calories + bonus)
                    break

        # cold_blood: 50% metabolism reduction (applied by reducing cost here)
        if org.genome.get_dominant_allele('cold_blood') > 127:
            state.calories += body.calorie_cost_per_tick * 0.5  # refund half the tick cost

        # Unconditional eat attempt every 3 ticks — baseline survival independent
        # of which behavior slots the organism rolled in its genome.
        if self.tick_count % 3 == 0:
            self._try_eat(org)

        # Large organisms are slower — skip movement on some ticks
        # size 1=99%, size 25=75%, size 50=50% movement probability
        _size_move_prob = max(0.5, 1.0 - body.total_cells * 0.01)
        _size_move_skip = random.random() > _size_move_prob

        # Unconditional reproduce attempt — every 5 ticks for mature, well-fed orgs.
        # This ensures reproduction happens regardless of behavior slot lottery.
        if self.tick_count % 5 == org.id % 5:  # stagger across organisms
            maturity_ticks = int(org.genome.phenotype('maturity_ticks') * 500) + 100
            if state.age >= maturity_ticks:
                cal_ratio = state.calories / max(1, body.calorie_capacity)
                repro_cost = int(org.genome.phenotype('reproduction_cost') * body.calorie_capacity * 0.25) + max(1, int(body.calorie_capacity * 0.05))
                if cal_ratio >= 0.75 and state.calories > repro_cost:
                    mode = org.genome.get_dominant_allele('reproduction_mode')
                    # Build minimal context for _reproduce (needs nearest_mate_id)
                    living_near = [o for o in living_now
                                   if o is not org and o.is_alive
                                   and abs(o.state.x - state.x) + abs(o.state.y - state.y) <= 200]
                    nearest_mate_id = living_near[0].id if living_near else None
                    is_sexual = mode >= 128 and nearest_mate_id is not None
                    mini_ctx = {'nearest_mate_id': nearest_mate_id}
                    if is_sexual:
                        mate = self.pool.organisms.get(nearest_mate_id)
                        mate_cost = repro_cost // 2
                        my_cost = repro_cost - mate_cost
                        if (mate and mate.is_alive and
                                state.calories > my_cost and
                                mate.state.calories > mate_cost):
                            state.calories -= my_cost
                            mate.state.calories -= mate_cost
                            baby = self._reproduce(org, mini_ctx, invested_calories=repro_cost)
                            if baby:
                                return baby
                    else:
                        state.calories -= repro_cost
                        baby = self._reproduce(org, mini_ctx, invested_calories=repro_cost)
                        if baby:
                            return baby

        # Large hungry predators hunt unconditionally — they can't survive on plants alone.
        # hunt_range is size-scaled vision so predators actively track distant prey.
        if (org.genome.get_dominant_allele('can_attack') > 127 and
                body.total_cells >= 15 and
                state.calories / body.calorie_capacity < 0.7):
            attack_range_u = 1.5 + body.total_cells * 0.1
            hunt_range = min(150, 20 + body.total_cells * 2)  # size15=50, size50=120 cells
            nearest_prey_u, nearest_dist_u = None, float('inf')
            for other in living_now:
                if other.id == org.id or not other.is_alive:
                    continue
                if other.body.total_cells >= body.total_cells * 0.7:
                    continue  # too big to eat
                # toxin_detection: skip visibly toxic (orange) prey
                if (other.genome.get_dominant_allele('toxicity') > 127 and
                        org.genome.get_dominant_allele('toxin_detection') > 127):
                    continue
                odx = other.state.x - state.x
                ody = other.state.y - state.y
                odist = math.sqrt(odx*odx + ody*ody)
                if odist <= hunt_range and odist < nearest_dist_u:
                    nearest_prey_u, nearest_dist_u = other, odist
            if nearest_prey_u is not None:
                if nearest_dist_u <= attack_range_u:
                    armor_factor = 1.0 - nearest_prey_u.genome.phenotype('armor') * 0.6
                    cal_gain = nearest_prey_u.body.calorie_capacity * org.genome.phenotype('calorie_efficiency') * armor_factor
                    state.calories = min(body.calorie_capacity, state.calories + cal_gain)
                    if nearest_prey_u.genome.get_dominant_allele('toxicity') > 127:
                        state.calories = max(0, state.calories - 20)
                    nearest_prey_u.state.alive = False
                else:
                    self._move_toward(org, nearest_prey_u.state.x, nearest_prey_u.state.y, nearest_prey_u.state.z, 1.0)

        # Build world context for behavior evaluator
        ctx = self._build_world_context(org, living_now)

        # Evaluate behavior
        action = self.evaluator.evaluate(state, body, org.genome, ctx)
        if action:
            state.current_behavior = action['behavior_name']
            result = self._execute_action(org, action, ctx, living_now, skip_move=_size_move_skip)
            if result == 'dead':
                return 'dead'
            if isinstance(result, Organism):
                return result

        return None

    def _build_world_context(self, org: Organism, living_now: list) -> dict:
        """
        Scan nearby cells/organisms to build context dict for behavior evaluator.
        Uses vision_range from genome to limit scan radius (capped at 50 for performance).
        living_now is the pre-computed snapshot for this tick — do NOT call pool.living() here.
        """
        state = org.state
        body = org.body
        genome = org.genome

        vision = min(50, int(org.genome.phenotype('vision_range') * 50) + 5)

        # sound_range adds threat detection bonus
        sound_bonus = int(org.genome.phenotype('sound_range') * 20)
        threat_scan_r = min(70, vision + sound_bonus)

        # Defaults
        nearest_threat_dist = float('inf')
        nearest_food_dist = float('inf')
        nearest_food_pos = None
        nearest_mate_dist = float('inf')
        nearest_mate_id = None
        nearest_prey_dist = float('inf')
        nearest_prey_id = None

        # Scan a capped sample of organisms — avoid O(n²) with large populations.
        # Sample up to 100 random organisms; with 1000 orgs this cuts work by 10x
        # while still reliably finding nearby threats/prey/mates.
        import random as _rnd
        scan_pool = living_now if len(living_now) <= 100 else _rnd.sample(living_now, 100)
        MATE_RANGE = 200
        for other in scan_pool:
            if other.id == org.id:
                continue
            dx = other.state.x - state.x
            dy = other.state.y - state.y
            dz = other.state.z - state.z
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)

            if dist > max(threat_scan_r, vision, MATE_RANGE):
                continue

            if dist <= threat_scan_r:
                # Threat detection (within threat scan range)
                can_attack_me = other.genome.get_dominant_allele('can_attack') > 127
                if can_attack_me and other.body.total_cells > body.total_cells * 0.7:
                    if dist < nearest_threat_dist:
                        # camouflage: predator sees this organism as if it were farther away
                        camo = org.genome.phenotype('camouflage')
                        effective_dist = dist * (1.0 + camo * 1.5)
                        nearest_threat_dist = effective_dist

            if dist <= vision:
                # Prey detection (within vision)
                can_attack = org.genome.get_dominant_allele('can_attack') > 127
                if can_attack and other.body.total_cells < body.total_cells * 0.7:
                    # toxin_detection: predator recognizes orange=toxic and avoids toxic prey
                    prey_is_toxic = other.genome.get_dominant_allele('toxicity') > 127
                    has_toxin_detection = org.genome.get_dominant_allele('toxin_detection') > 127
                    if prey_is_toxic and has_toxin_detection:
                        pass  # skip this prey — it's orange/toxic and predator knows it
                    elif dist < nearest_prey_dist:
                        nearest_prey_dist = dist
                        nearest_prey_id = other.id

            # Mate detection uses wider range
            if dist <= MATE_RANGE:
                if (other.genome.get_dominant_allele('reproduction_mode') >= 128 and
                        other.state.age >= 100):
                    if dist < nearest_mate_dist:
                        nearest_mate_dist = dist
                        nearest_mate_id = other.id

        # Food scan — expensive, so cache the result for FOOD_SCAN_INTERVAL ticks.
        # If the organism has moved far from its cached food, invalidate.
        FOOD_SCAN_INTERVAL = 10
        if (self.tick_count - state._food_scan_tick >= FOOD_SCAN_INTERVAL or
                state._cached_food_pos is None):
            scan_r = min(vision, 15)
            stride = max(1, scan_r // 8)
            # Small organisms scan deeper — can find soil 2 layers below stone
            _dz_min = -2 if body.total_cells < 10 else -1
            for dz in range(_dz_min, 2):
                for dy in range(-scan_r, scan_r + 1, stride):
                    for dx in range(-scan_r, scan_r + 1, stride):
                        nx = state.x + dx
                        ny = state.y + dy
                        nz = state.z + dz
                        if nx < 0 or ny < 0 or nx >= 1000 or ny >= 1000 or nz < 0 or nz >= 100:
                            continue
                        ct = self.world.get_cell(nx, ny, nz)
                        if CELL_PROPS.get(ct, {}).get('calorie_value', 0) > 0:
                            d = math.sqrt(dx*dx + dy*dy + dz*dz)
                            if d < nearest_food_dist:
                                nearest_food_dist = d
                                nearest_food_pos = (nx, ny, nz)
            state._cached_food_pos = nearest_food_pos
            state._cached_food_dist = nearest_food_dist
            state._food_scan_tick = self.tick_count
        else:
            nearest_food_pos = state._cached_food_pos
            nearest_food_dist = state._cached_food_dist

        maturity = int(org.genome.phenotype('maturity_ticks') * 500) + 100

        return {
            'calories': state.calories,
            'calories_max': body.calorie_capacity,
            'nearest_threat_dist': nearest_threat_dist,
            'nearest_food_dist': nearest_food_dist,
            'nearest_food_pos': nearest_food_pos,
            'nearest_mate_dist': nearest_mate_dist,
            'nearest_mate_id': nearest_mate_id,
            'nearest_prey_dist': nearest_prey_dist,
            'nearest_prey_id': nearest_prey_id,
            'in_water': state.in_water,
            'has_lung': body.has_lung,
            'has_gill': body.has_gill,
            'age': state.age,
            'maturity_ticks': maturity,
        }

    def _execute_action(self, org: Organism, action: dict, ctx: dict, living_now: list = None, skip_move: bool = False):
        """
        Execute the chosen action. Returns 'dead', Organism (newborn), or None.
        """
        state = org.state
        body = org.body
        atype = action['action_type']
        speed_mul = action.get('speed_multiplier', 1.0)
        cal_mul = action.get('calorie_multiplier', 1.0)

        # Honour size-based speed gating set in _process_organism
        if skip_move:
            if action.get('action_type') in ('wander', 'flee', 'approach', 'hunt', 'dive', 'surface'):
                return None

        # Extra calorie burn for active behaviors
        state.calories -= body.calorie_cost_per_tick * (cal_mul - 1.0) * 0.5

        if atype == 'wander':
            # Sexual organisms without a nearby mate wander purposefully toward
            # other organisms rather than randomly — speeds up mate-finding.
            is_sexual = org.genome.get_dominant_allele('reproduction_mode') >= 128
            if is_sexual and ctx.get('nearest_mate_id') is None and len(living_now) > 1:
                # Find the nearest organism of opposite gender
                my_gender = org.genome.get_dominant_allele('gender') >= 128
                best, best_d = None, float('inf')
                for other in living_now:
                    if other.id == org.id or not other.is_alive:
                        continue
                    other_gender = other.genome.get_dominant_allele('gender') >= 128
                    if other_gender == my_gender:
                        continue  # same gender, skip
                    d = abs(other.state.x - state.x) + abs(other.state.y - state.y)
                    if d < best_d:
                        best, best_d = other, d
                if best and best_d > 5:  # don't chase when very close
                    self._move_toward(org, best.state.x, best.state.y, best.state.z, speed_mul)
                else:
                    self._move_random(org, speed_mul)
            else:
                self._move_random(org, speed_mul)

        elif atype == 'flee':
            # Move away from nearest threat direction (roughly)
            self._move_random(org, speed_mul)  # simplified: random flee

        elif atype == 'approach':
            target = action.get('target')
            if target:
                self._move_toward(org, target[0], target[1], target[2], speed_mul)

        elif atype == 'eat':
            # Try to eat an adjacent food cell
            result = self._try_eat(org)
            if result:
                state.last_ate_tick = self.tick_count

        elif atype == 'dig':
            # Dig adjacent SOIL/SAND toward food
            target = action.get('target')
            if target:
                self._try_dig(org, target[0], target[1], target[2])

        elif atype == 'reproduce':
            maturity = ctx['maturity_ticks']
            cal_threshold = action.get('action_param', action.get('param', 75)) / 100.0
            repro_cost = int(org.genome.phenotype('reproduction_cost') * body.calorie_capacity * 0.25) + max(1, int(body.calorie_capacity * 0.05))
            mode = org.genome.get_dominant_allele('reproduction_mode')
            cal_ratio = state.calories / max(1, body.calorie_capacity)
            is_sexual = mode >= 128 and ctx.get('nearest_mate_id') is not None

            if state.age >= maturity and cal_ratio >= cal_threshold:
                if is_sexual:
                    mate = self.pool.organisms.get(ctx['nearest_mate_id'])
                    mate_cost = repro_cost // 2
                    my_cost = repro_cost - mate_cost
                    if (state.calories > my_cost and mate and mate.is_alive
                            and mate.state.calories > mate_cost):
                        state.calories -= my_cost
                        mate.state.calories -= mate_cost
                        baby = self._reproduce(org, ctx, invested_calories=repro_cost)
                        if baby:
                            return baby
                else:
                    # Asexual — no mate required
                    if state.calories > repro_cost:
                        state.calories -= repro_cost
                        baby = self._reproduce(org, ctx, invested_calories=repro_cost)
                        if baby:
                            return baby

        elif atype == 'hunt':
            prey_id = ctx.get('nearest_prey_id')
            if prey_id:
                prey = self.pool.organisms.get(prey_id)
                if prey and prey.is_alive:
                    tx, ty, tz = prey.state.x, prey.state.y, prey.state.z
                    self._move_toward(org, tx, ty, tz, speed_mul)
                    # If now adjacent (dist <= 1.5), attack
                    dx = org.state.x - prey.state.x
                    dy = org.state.y - prey.state.y
                    dz = org.state.z - prey.state.z
                    dist = (dx*dx + dy*dy + dz*dz) ** 0.5
                    attack_range = 1.5 + body.total_cells * 0.1
                    if dist <= attack_range:
                        # armor gene reduces calorie gain (prey absorbs up to 60% damage)
                        armor_factor = 1.0 - prey.genome.phenotype('armor') * 0.6
                        cal_gain = prey.body.calorie_capacity * org.genome.phenotype('calorie_efficiency') * armor_factor
                        # pack_instinct: +50% bonus if a pack-mate recently attacked this prey
                        if org.genome.get_dominant_allele('pack_instinct') > 127:
                            # check if another living predator is within 5 cells of prey
                            px, py = prey.state.x, prey.state.y
                            for other in living_now:
                                if other is not org and other.is_alive and other.genome.get_dominant_allele('can_attack') > 127:
                                    od = abs(other.state.x - px) + abs(other.state.y - py)
                                    if od <= 5:
                                        cal_gain *= 1.5
                                        break
                        state.calories = min(body.calorie_capacity, state.calories + cal_gain)
                        # toxicity: if prey is toxic, attacker loses 20 cal
                        if prey.genome.get_dominant_allele('toxicity') > 127:
                            state.calories = max(0, state.calories - 20)
                        prey.state.alive = False

        elif atype == 'surface':
            # Move toward higher z (out of water)
            new_z = min(WORLD_D - 1, state.z + 1)
            if self.world.get_cell(state.x, state.y, new_z) in (CellType.AIR, CellType.WATER):
                state.z = new_z

        elif atype == 'dive':
            # Move toward lower z (into water)
            new_z = max(0, state.z - 1)
            ct = self.world.get_cell(state.x, state.y, new_z)
            if ct == CellType.WATER:
                state.z = new_z

        return None

    def _move_random(self, org: Organism, speed_mul: float):
        """Move one step in a random cardinal direction. Speed >1 means multiple steps."""
        steps = max(1, int(speed_mul))
        state = org.state
        body = org.body

        for _ in range(steps):
            dirs = [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0)]
            # Add vertical movement if organism can climb
            can_climb = org.genome.get_dominant_allele('can_climb') > 127
            can_swim = org.genome.get_dominant_allele('can_swim') > 127

            random.shuffle(dirs)
            for dx, dy, dz_unused in dirs:
                nx, ny = state.x + dx, state.y + dy
                nz = state.z
                if not self.world.in_bounds(nx, ny, nz):
                    continue
                ct = self.world.get_cell(nx, ny, nz)
                # Can move into air or water (if can_swim)
                if ct == CellType.AIR:
                    state.x, state.y = nx, ny
                    # Apply gravity: fall if cell below is passable
                    self._apply_gravity(org)
                    break
                elif ct == CellType.WATER and can_swim:
                    state.x, state.y = nx, ny
                    break

    def _move_toward(self, org: Organism, tx: int, ty: int, tz: int, speed_mul: float):
        """Move one step toward target."""
        state = org.state
        dx = tx - state.x
        dy = ty - state.y
        dz = tz - state.z

        steps = max(1, int(speed_mul))
        can_swim = org.genome.get_dominant_allele('can_swim') > 127

        for _ in range(steps):
            # Pick dominant axis
            moves = []
            if abs(dx) > 0: moves.append((int(math.copysign(1, dx)), 0))
            if abs(dy) > 0: moves.append((0, int(math.copysign(1, dy))))

            moved = False
            for mdx, mdy in moves:
                nx, ny = state.x + mdx, state.y + mdy
                if not self.world.in_bounds(nx, ny, state.z):
                    continue
                ct = self.world.get_cell(nx, ny, state.z)
                if ct == CellType.AIR or (ct == CellType.WATER and can_swim):
                    state.x, state.y = nx, ny
                    dx -= mdx
                    dy -= mdy
                    self._apply_gravity(org)
                    moved = True
                    break
            if not moved:
                break

    def _apply_gravity(self, org: Organism):
        """Drop organism down if cell below is passable (air/water)."""
        state = org.state
        can_swim = org.genome.get_dominant_allele('can_swim') > 127
        can_float = org.genome.get_dominant_allele('can_float') > 127

        if can_float:
            return

        below_z = state.z - 1
        if below_z < 0:
            return
        ct_below = self.world.get_cell(state.x, state.y, below_z)
        if ct_below == CellType.AIR:
            state.z = below_z
        elif ct_below == CellType.WATER and not can_swim:
            state.z = below_z  # sink

    def _try_eat(self, org: Organism) -> bool:
        """Try to eat an adjacent cell with calorie value > 0. Returns True if ate."""
        state = org.state
        neighbors = self.world.get_neighbors(state.x, state.y, state.z)

        for nx, ny, nz, ct in neighbors:
            cal = CELL_PROPS.get(ct, {}).get('calorie_value', 0)
            if cal > 0:
                efficiency = org.genome.phenotype('calorie_efficiency')
                # Larger organisms take bigger bites; still can't sustain on SOIL alone at size 15+
                body = org.body
                bite_size = max(10, body.total_cells * 0.5 + 5)
                state.calories = min(body.calorie_capacity,
                                     state.calories + cal * efficiency * bite_size)
                self.world.set_cell(nx, ny, nz, CellType.AIR)  # consumed
                # Schedule regeneration: SOIL=60 ticks, WOOD=250 ticks
                delay = 250 if ct == int(CellType.WOOD) else 60
                self._heapq.heappush(self._regen_heap,
                    (self.tick_count + delay, nx, ny, nz, ct))
                return True
        return False

    def _try_dig(self, org: Organism, tx: int, ty: int, tz: int):
        """Dig one step toward target if diggable and organism has can_dig."""
        if not (org.genome.get_dominant_allele('can_dig') > 127):
            return

        state = org.state
        dx = int(math.copysign(1, tx - state.x)) if tx != state.x else 0
        dy = int(math.copysign(1, ty - state.y)) if ty != state.y else 0

        for mdx, mdy in [(dx, 0), (0, dy), (dx, dy)]:
            if mdx == 0 and mdy == 0:
                continue
            nx, ny = state.x + mdx, state.y + mdy
            if not self.world.in_bounds(nx, ny, state.z):
                continue
            ct = self.world.get_cell(nx, ny, state.z)
            if CELL_PROPS.get(ct, {}).get('diggable', False):
                self.world.set_cell(nx, ny, state.z, CellType.AIR)
                state.calories -= org.body.calorie_cost_per_tick * 3  # digging costs energy
                break

    def _attack(self, attacker: Organism, prey: Organism):
        """Attacker kills prey and gains calories from it."""
        can_attack = attacker.genome.get_dominant_allele('can_attack') > 127
        if not can_attack:
            return
        if attacker.body.total_cells <= prey.body.total_cells * 0.7:
            return  # prey too big
        # Kill prey, attacker gains prey's calories
        calorie_gain = prey.state.calories * attacker.genome.phenotype('calorie_efficiency')
        attacker.state.calories = min(
            attacker.body.calorie_capacity,
            attacker.state.calories + calorie_gain
        )
        prey.state.alive = False
        self.pool.remove(prey.id)

    def _reproduce(self, org: Organism, ctx: dict, invested_calories: float = 50):
        """Create offspring. Genome determines sexual vs asexual.
        Baby starts with 80% of the calories invested by the parent(s),
        capped at its own calorie capacity.
        Returns None immediately if the population cap (400) is reached.
        """
        if self.pool.count() >= 400:
            return None
        mode = org.genome.get_dominant_allele('reproduction_mode')

        if mode >= 128 and ctx.get('nearest_mate_id'):
            mate = self.pool.organisms.get(ctx['nearest_mate_id'])
            if mate and mate.is_alive:
                my_gender = org.genome.get_dominant_allele('gender') >= 128
                mate_gender = mate.genome.get_dominant_allele('gender') >= 128
                if my_gender != mate_gender:  # require opposite genders
                    child_genome = Genome.sexual_reproduction(org.genome, mate.genome)
                else:
                    child_genome = Genome.asexual_reproduction(org.genome)
            else:
                child_genome = Genome.asexual_reproduction(org.genome)
        else:
            child_genome = Genome.asexual_reproduction(org.genome)

        # Place offspring adjacent to parent
        ox, oy, oz = org.state.x, org.state.y, org.state.z
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            nx, ny = ox + dx, oy + dy
            if self.world.in_bounds(nx, ny, oz):
                ct = self.world.get_cell(nx, ny, oz)
                if ct == CellType.AIR:
                    baby = Organism(child_genome, nx, ny, oz, species_id=org.species_id)
                    # Baby starts with 80% of invested calories, capped at capacity
                    baby.state.calories = min(
                        baby.body.calorie_capacity,
                        invested_calories * 0.8
                    )
                    # Register new species if not already known
                    if baby.species_id not in self.species_registry:
                        self.species_registry[baby.species_id] = {
                            'genome_snapshot': baby.genome,
                            'first_tick': self.tick_count,
                            'extinct_tick': None,
                        }
                    return baby
        return None

    def _grow_vegetation(self):
        """Expand WOOD cells near existing WOOD — simulates tree and kelp regrowth.

        Each active chunk has a small chance per tick to grow one new WOOD cell
        adjacent to an existing one, allowing groves to slowly expand and fill gaps.
        """
        _WOOD = int(CellType.WOOD)
        _AIR  = int(CellType.AIR)
        _WATER = int(CellType.WATER)
        import numpy as _np

        for chunk_key in list(self.world.active_chunks):
            if random.random() > 0.08:   # only 8% of active chunks grow per tick
                continue
            if chunk_key not in self.world.chunks:
                continue
            chunk = self.world.chunks[chunk_key]
            wood_positions = _np.argwhere(chunk.cells == _WOOD)
            if len(wood_positions) == 0:
                continue
            cx, cy, cz = chunk_key
            ox, oy, oz = cx * 16, cy * 16, cz * 16
            # Pick one random wood cell to try to grow from
            lx, ly, lz = wood_positions[random.randrange(len(wood_positions))]
            wx, wy, wz = int(ox + lx), int(oy + ly), int(oz + lz)
            # Growth directions: prefer upward for trees, sideways for kelp
            candidates = [(wx, wy, wz + 1), (wx + 1, wy, wz), (wx - 1, wy, wz),
                          (wx, wy + 1, wz), (wx, wy - 1, wz)]
            random.shuffle(candidates)
            for nx, ny, nz in candidates:
                if not self.world.in_bounds(nx, ny, nz):
                    continue
                ct = self.world.get_cell(nx, ny, nz)
                if ct == _AIR or ct == _WATER:
                    self.world.set_cell(nx, ny, nz, _WOOD)
                    break

    def get_stats(self) -> dict:
        """Return simulation statistics for UI."""
        return {
            'tick': self.tick_count,
            'organisms': self.pool.count(),
            'paused': self.paused,
        }

    def get_species_stats(self) -> list:
        """Return per-species stats sorted by population desc, then extinct ones after."""
        living = self.pool.living()
        pop_counts = {}
        for org in living:
            pop_counts[org.species_id] = pop_counts.get(org.species_id, 0) + 1

        result = []
        for sid, info in self.species_registry.items():
            pop = pop_counts.get(sid, 0)
            if pop == 0 and info['extinct_tick'] is None:
                info['extinct_tick'] = self.tick_count
            result.append({
                'species_id': sid,
                'population': pop,
                'extinct': pop == 0,
                'extinct_tick': info['extinct_tick'],
                'first_tick': info['first_tick'],
                'genome': info['genome_snapshot'],
            })
        result.sort(key=lambda x: (-x['population'], x['species_id']))
        return result
