"""
organism.py — Organism state and pool management for the life simulator.

OrganismState  : lightweight mutable runtime state (position, energy, age …)
Organism       : pairs a genome+body plan with a runtime state
OrganismPool   : container for all live organisms with culling support
"""

import uuid
from typing import Dict, List, Optional

from .genetics import Genome, BodyPlan


# ---------------------------------------------------------------------------
# Global limit
# ---------------------------------------------------------------------------

# Maximum organisms before the pool culls the weakest/oldest individuals.
MAX_ORGANISMS: int = 50_000


# ---------------------------------------------------------------------------
# OrganismState
# ---------------------------------------------------------------------------

class OrganismState:
    """Lightweight current state — separate from genome for cache locality."""

    __slots__ = [
        'x', 'y', 'z',
        'calories',
        'age',
        'alive',
        'heading',
        'in_water',
        'current_behavior',
        'threat_timer',
        'mate_timer',
        'last_ate_tick',
        # Cached food scan — refreshed every FOOD_SCAN_INTERVAL ticks
        '_cached_food_pos',
        '_cached_food_dist',
        '_food_scan_tick',
    ]

    def __init__(self, x: int, y: int, z: int, calories: float):
        self.x: int = x
        self.y: int = y
        self.z: int = z
        self.calories: float = calories
        self.age: int = 0
        self.alive: bool = True
        self.heading: tuple = (1, 0)   # (dx, dy), default facing east
        self.in_water: bool = False
        self.current_behavior: str = 'idle'
        self.threat_timer: int = 0
        self.mate_timer: int = 0
        self.last_ate_tick: int = 0
        self._cached_food_pos = None
        self._cached_food_dist: float = float('inf')
        self._food_scan_tick: int = -999  # force scan on first tick

    def __repr__(self) -> str:
        return (
            f"OrganismState(pos=({self.x},{self.y},{self.z}), "
            f"cal={self.calories:.1f}, age={self.age}, alive={self.alive})"
        )


# ---------------------------------------------------------------------------
# Organism
# ---------------------------------------------------------------------------

class Organism:
    """A single organism: genome + derived body plan + runtime state."""

    __slots__ = ['id', 'genome', 'body', 'state', 'species_id']

    def __init__(
        self,
        genome: Genome,
        x: int,
        y: int,
        z: int,
        species_id: int = 0,
    ):
        # Use a 32-bit ID for memory efficiency.
        self.id: int = uuid.uuid4().int & 0xFFFFFFFF
        self.genome: Genome = genome
        self.body: BodyPlan = BodyPlan(genome)
        self.state: OrganismState = OrganismState(
            x, y, z,
            self.body.calorie_capacity * 0.5,
        )
        self.species_id: int = species_id

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        return self.state.alive

    @property
    def display_char(self) -> str:
        """ASCII character for rendering, scaled by organism size."""
        size = self.body.total_cells
        if size <= 4:
            return ','
        if size <= 12:
            return 'o'
        if size <= 25:
            return 'O'
        return '@'

    @property
    def display_radius(self) -> int:
        """Rendering radius in screen cells. 0=1×1, 1=3×3.
        Organisms with ≥15 cells are large enough to display as a 3×3 block.
        """
        return 1 if self.body.total_cells >= 15 else 0

    @property
    def display_color_pair(self) -> int:
        """Return a curses color-pair index (1..8) based on genome color genes.

        Color pairs (standard curses setup assumed by the renderer):
          1=red, 2=green, 3=yellow, 4=blue, 5=magenta, 6=cyan, 7=white, 8=orange

        Aposematism: toxic organisms always display as orange (pair 8) regardless
        of their color genes, warning predators away.
        """
        # Aposematism override: toxicity > 127 = orange warning coloration
        if self.genome.get_dominant_allele('toxicity') > 127:
            return 8  # orange

        r = self.genome.get_dominant_allele('color_r')
        g = self.genome.get_dominant_allele('color_g')
        b = self.genome.get_dominant_allele('color_b')

        # Determine which channel dominates.
        max_val = max(r, g, b)

        if max_val == 0:
            return 7  # white (no color information)

        # Ties are broken by channel priority: r > g > b.
        if r == max_val and g == max_val:
            return 3  # yellow  (red + green)
        if r == max_val and b == max_val:
            return 5  # magenta (red + blue)
        if g == max_val and b == max_val:
            return 6  # cyan    (green + blue)
        if r == max_val:
            return 1  # red
        if g == max_val:
            return 2  # green
        if b == max_val:
            return 4  # blue
        return 7  # fallback white

    def stats_summary(self) -> dict:
        """Return a dict of key stats suitable for the UI info panel."""
        return {
            'id':        hex(self.id),
            'species':   self.species_id,
            'age':       self.state.age,
            'calories':  f"{self.state.calories:.1f}/{self.body.calorie_capacity}",
            'pos':       (self.state.x, self.state.y, self.state.z),
            'size':      self.body.total_cells,
            'can_dig':   self.genome.get_dominant_allele('can_dig')   > 127,
            'can_swim':  self.genome.get_dominant_allele('can_swim')  > 127,
            'can_climb': self.genome.get_dominant_allele('can_climb') > 127,
            'behavior':  self.state.current_behavior,
            'brain_cap': self.body.brain_capacity,
            'lung':      'lung' if self.body.has_lung else 'gill',
        }

    def __repr__(self) -> str:
        return (
            f"Organism(id={hex(self.id)}, species={self.species_id}, "
            f"pos=({self.state.x},{self.state.y},{self.state.z}), "
            f"alive={self.state.alive})"
        )


# ---------------------------------------------------------------------------
# OrganismPool
# ---------------------------------------------------------------------------

class OrganismPool:
    """Manages all organisms; handles culling when the population exceeds the
    global limit.
    """

    def __init__(self):
        self.organisms: Dict[int, Organism] = {}   # id -> Organism
        self.dead_ids:  List[int] = []

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def add(self, organism: Organism) -> None:
        """Register a new organism in the pool."""
        self.organisms[organism.id] = organism

    def remove(self, organism_id: int) -> None:
        """Mark an organism as dead and stage its ID for cleanup.

        The organism is killed in-place so that any live references see the
        updated state, and its id is queued so the dict entry can be purged
        on the next cleanup pass.
        """
        org = self.organisms.get(organism_id)
        if org is not None:
            org.state.alive = False
            self.dead_ids.append(organism_id)

    def _flush_dead(self) -> None:
        """Remove all staged dead IDs from the dict."""
        for oid in self.dead_ids:
            self.organisms.pop(oid, None)
        self.dead_ids.clear()

    def cull_to_limit(self) -> int:
        """If the population exceeds MAX_ORGANISMS, kill the weakest.

        Weakness proxy: lowest calories first; ties broken by oldest age
        (larger age = weaker, because old organisms have already reproduced).

        Removes the bottom 10 % of the overage to avoid thrashing on every
        tick when hovering near the limit.

        Returns the number of organisms culled.
        """
        self._flush_dead()

        count = len(self.organisms)
        if count <= MAX_ORGANISMS:
            return 0

        overage   = count - MAX_ORGANISMS
        cull_count = max(1, int(overage + MAX_ORGANISMS * 0.10))

        # Sort ascending by calories, then descending by age (oldest weakest).
        ranked = sorted(
            self.organisms.values(),
            key=lambda o: (o.state.calories, -o.state.age),
        )

        culled = 0
        for org in ranked[:cull_count]:
            org.state.alive = False
            self.dead_ids.append(org.id)
            culled += 1

        self._flush_dead()
        return culled

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def living(self) -> List[Organism]:
        """Return all currently-alive organisms."""
        return [o for o in self.organisms.values() if o.state.alive]

    def count(self) -> int:
        """Total organisms currently tracked (alive + freshly dead staged)."""
        return len(self.organisms)

    def at_chunk(self, cx: int, cy: int, cz: int, chunk_size: int = 16) -> List[Organism]:
        """Return alive organisms whose position falls within the given chunk.

        Chunks are axis-aligned cubes of *chunk_size* cells on each side.
        """
        x0 = cx * chunk_size
        y0 = cy * chunk_size
        z0 = cz * chunk_size
        x1 = x0 + chunk_size
        y1 = y0 + chunk_size
        z1 = z0 + chunk_size

        result: List[Organism] = []
        for org in self.organisms.values():
            if not org.state.alive:
                continue
            s = org.state
            if x0 <= s.x < x1 and y0 <= s.y < y1 and z0 <= s.z < z1:
                result.append(org)
        return result

    def __repr__(self) -> str:
        alive = sum(1 for o in self.organisms.values() if o.state.alive)
        return f"OrganismPool(total={len(self.organisms)}, alive={alive})"
