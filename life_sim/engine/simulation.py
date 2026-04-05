import random
import math
from .world import World, WorldGenerator, WORLD_W, WORLD_H, WORLD_D, CHUNK_SIZE
from .cells import CellType, CELL_PROPS
from .physics import PhysicsEngine
from .organism import Organism, OrganismPool
from .genetics import Genome, BodyPlan
from .behavior import BehaviorEvaluator, load_all_behaviors, mutate_behavior_file

class Simulation:
    def __init__(self, seed: int = 42):
        random.seed(seed)

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

        # Init
        load_all_behaviors()
        WorldGenerator().generate_default(self.world)
        self._seed_initial_organisms(count=50)

    def _seed_initial_organisms(self, count: int):
        """Place starter organisms on the soil surface."""
        # Find the surface z for random x,y positions and place organisms there
        for _ in range(count):
            x = random.randint(0, WORLD_W - 1)
            y = random.randint(0, WORLD_H - 1)
            # Find surface: highest z that is not AIR
            z = self._find_surface_z(x, y)
            if z is None:
                continue
            genome = Genome.random_genome()
            org = Organism(genome, x, y, z + 1, species_id=self.species_counter)
            self.species_counter += 1
            org.state.calories = org.body.calorie_capacity * 0.7
            self.pool.add(org)

    def _find_surface_z(self, x, y) -> int | None:
        """Return z of the highest non-AIR cell at (x,y), or None if all air."""
        for z in range(WORLD_D - 1, -1, -1):
            if self.world.get_cell(x, y, z) != CellType.AIR:
                return z
        return None

    def step(self):
        """Advance simulation by one tick."""
        self.tick_count += 1

        # 1. Update active chunks from organism positions
        active_chunks = set()
        for org in self.pool.living():
            cx = org.state.x // CHUNK_SIZE
            cy = org.state.y // CHUNK_SIZE
            cz = org.state.z // CHUNK_SIZE
            active_chunks.add((cx, cy, cz))
            self.world.mark_active(cx, cy, cz)

        # 2. Physics tick (fluid spreading, gravity)
        # Only every 3 ticks for performance
        if self.tick_count % 3 == 0:
            self.physics.tick(active_chunks)

        # 3. Process each organism
        dead_ids = []
        new_organisms = []

        for org in self.pool.living():
            result = self._process_organism(org)
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

    def _process_organism(self, org: Organism):
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

        # Update medium (in water?)
        cell_here = self.world.get_cell(state.x, state.y, state.z)
        state.in_water = (cell_here == CellType.WATER)

        # Drown if has lung and in water (gradual)
        if state.in_water and body.has_lung:
            state.calories -= body.calorie_cost_per_tick * 2  # drowning costs extra

        # Dry out if has gill and not in water
        if not state.in_water and body.has_gill:
            state.calories -= body.calorie_cost_per_tick * 1.5

        # Build world context for behavior evaluator
        ctx = self._build_world_context(org)

        # Evaluate behavior
        action = self.evaluator.evaluate(state, body, org.genome, ctx)
        if action:
            state.current_behavior = action['behavior_name']
            result = self._execute_action(org, action, ctx)
            if result == 'dead':
                return 'dead'
            if isinstance(result, Organism):
                return result

        return None

    def _build_world_context(self, org: Organism) -> dict:
        """
        Scan nearby cells/organisms to build context dict for behavior evaluator.
        Uses vision_range from genome to limit scan radius (capped at 50 for performance).
        """
        state = org.state
        body = org.body
        genome = org.genome

        vision = min(50, int(org.genome.phenotype('vision_range') * 50) + 5)

        # Defaults
        nearest_threat_dist = float('inf')
        nearest_food_dist = float('inf')
        nearest_food_pos = None
        nearest_mate_dist = float('inf')
        nearest_mate_id = None

        # Scan nearby organisms for threats/mates
        # Use pool.living() but limit to nearby (rough bounding box check)
        for other in self.pool.living():
            if other.id == org.id:
                continue
            dx = other.state.x - state.x
            dy = other.state.y - state.y
            dz = other.state.z - state.z
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            if dist > vision:
                continue

            # Threat: larger organism is a threat
            if other.body.total_cells > body.total_cells * 1.5:
                if dist < nearest_threat_dist:
                    nearest_threat_dist = dist
            # Mate: same species, different id, mature
            elif (other.genome.get_dominant_allele('reproduction_mode') >= 128 and
                  other.state.age >= other.body.__class__.__dict__.get('maturity_ticks', 100)):
                if dist < nearest_mate_dist:
                    nearest_mate_dist = dist
                    nearest_mate_id = other.id

        # Scan nearby cells for food
        # Food = SOIL (calorie_value > 0), WOOD
        scan_r = min(vision, 20)
        for dz in range(-2, 3):
            for dy in range(-scan_r, scan_r + 1, max(1, scan_r // 5)):
                for dx in range(-scan_r, scan_r + 1, max(1, scan_r // 5)):
                    nx, ny, nz = state.x + dx, state.y + dy, state.z + dz
                    if not self.world.in_bounds(nx, ny, nz):
                        continue
                    ct = self.world.get_cell(nx, ny, nz)
                    if CELL_PROPS.get(ct, {}).get('calorie_value', 0) > 0:
                        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                        if dist < nearest_food_dist:
                            nearest_food_dist = dist
                            nearest_food_pos = (nx, ny, nz)

        maturity = int(org.genome.phenotype('maturity_ticks') * 500) + 100

        return {
            'calories': state.calories,
            'calories_max': body.calorie_capacity,
            'nearest_threat_dist': nearest_threat_dist,
            'nearest_food_dist': nearest_food_dist,
            'nearest_food_pos': nearest_food_pos,
            'nearest_mate_dist': nearest_mate_dist,
            'nearest_mate_id': nearest_mate_id,
            'in_water': state.in_water,
            'has_lung': body.has_lung,
            'has_gill': body.has_gill,
            'age': state.age,
            'maturity_ticks': maturity,
        }

    def _execute_action(self, org: Organism, action: dict, ctx: dict):
        """
        Execute the chosen action. Returns 'dead', Organism (newborn), or None.
        """
        state = org.state
        body = org.body
        atype = action['action_type']
        speed_mul = action.get('speed_multiplier', 1.0)
        cal_mul = action.get('calorie_multiplier', 1.0)

        # Extra calorie burn for active behaviors
        state.calories -= body.calorie_cost_per_tick * (cal_mul - 1.0) * 0.5

        if atype == 'wander':
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
            # Reproduce if conditions met
            maturity = ctx['maturity_ticks']
            repro_cost = int(org.genome.phenotype('reproduction_cost') * body.calorie_capacity * 0.5) + 50
            mode = org.genome.get_dominant_allele('reproduction_mode')
            is_sexual = mode >= 128 and ctx['nearest_mate_id'] is not None

            if is_sexual:
                # Both parents must have enough calories; each pays half
                mate = self.pool.organisms.get(ctx['nearest_mate_id'])
                mate_cost = repro_cost // 2
                my_cost = repro_cost - mate_cost
                if (state.age >= maturity
                        and state.calories > my_cost
                        and mate and mate.is_alive
                        and mate.state.calories > mate_cost):
                    state.calories -= my_cost
                    mate.state.calories -= mate_cost
                    baby = self._reproduce(org, ctx, invested_calories=repro_cost)
                    if baby:
                        return baby
            else:
                # Asexual: only this organism pays
                if state.age >= maturity and state.calories > repro_cost:
                    state.calories -= repro_cost
                    baby = self._reproduce(org, ctx, invested_calories=repro_cost)
                    if baby:
                        return baby

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
                state.calories = min(org.body.calorie_capacity,
                                     state.calories + cal * efficiency * 10)
                self.world.set_cell(nx, ny, nz, CellType.AIR)  # consumed
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

    def _reproduce(self, org: Organism, ctx: dict, invested_calories: float = 50):
        """Create offspring. Genome determines sexual vs asexual.
        Baby starts with 80% of the calories invested by the parent(s),
        capped at its own calorie capacity.
        """
        mode = org.genome.get_dominant_allele('reproduction_mode')

        if mode >= 128 and ctx['nearest_mate_id']:
            mate = self.pool.organisms.get(ctx['nearest_mate_id'])
            if mate and mate.is_alive:
                child_genome = Genome.sexual_reproduction(org.genome, mate.genome)
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
                    return baby
        return None

    def get_stats(self) -> dict:
        """Return simulation statistics for UI."""
        return {
            'tick': self.tick_count,
            'organisms': self.pool.count(),
            'paused': self.paused,
        }
