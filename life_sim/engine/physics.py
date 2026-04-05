import numpy as np
import random

from .cells import CellType
from .world import World, Chunk, CHUNK_SIZE

_AIR   = int(CellType.AIR)
_WATER = int(CellType.WATER)
_SAND  = int(CellType.SAND)
_LAVA  = int(CellType.LAVA)
_ICE   = int(CellType.ICE)

# Fraction of cells sampled per tick for stochastic updates
_SAMPLE_FRACTION = 0.1


class PhysicsEngine:
    __slots__ = ['world']

    def __init__(self, world: World):
        self.world = world

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tick(self, active_chunks: set):
        """Process physics for all active chunks."""
        for chunk_key in active_chunks:
            self._process_chunk(chunk_key)

    # ------------------------------------------------------------------
    # Per-chunk processing
    # ------------------------------------------------------------------

    def _process_chunk(self, chunk_key: tuple):
        cx, cy, cz = chunk_key
        if chunk_key not in self.world.chunks:
            return
        chunk = self.world.chunks[chunk_key]

        # Base world coords of this chunk's origin
        ox = cx * CHUNK_SIZE
        oy = cy * CHUNK_SIZE
        oz = cz * CHUNK_SIZE

        cells = chunk.cells  # uint8 array (16,16,16)

        # Find all interesting cell positions (non-AIR, non-STONE, non-SOIL)
        # using numpy to avoid full Python loops
        interesting_mask = (
            (cells == _WATER) |
            (cells == _SAND) |
            (cells == _LAVA)
        )
        positions = np.argwhere(interesting_mask)  # shape (N, 3)

        if positions.shape[0] == 0:
            return

        # Sample a fraction for performance
        n_sample = max(1, int(len(positions) * _SAMPLE_FRACTION))
        if n_sample < len(positions):
            idx = np.random.choice(len(positions), size=n_sample, replace=False)
            positions = positions[idx]

        changed = False
        for lx, ly, lz in positions:
            ct = int(cells[lx, ly, lz])
            wx = ox + lx
            wy = oy + ly
            wz = oz + lz

            if ct == _WATER:
                changed |= self._spread_water(wx, wy, wz)
            elif ct == _SAND:
                changed |= self._fall_sand(wx, wy, wz)
            elif ct == _LAVA:
                changed |= self._spread_lava(wx, wy, wz)

        if changed:
            chunk.dirty = True

    # ------------------------------------------------------------------
    # Water spreading
    # ------------------------------------------------------------------

    def _spread_water(self, x: int, y: int, z: int) -> bool:
        world = self.world
        # Try to fall down first
        below = z - 1
        if below >= 0 and world.get_cell(x, y, below) == _AIR:
            world.set_cell(x, y, below, _WATER)
            world.set_cell(x, y, z, _AIR)
            return True

        # Spread laterally to an AIR neighbor
        lateral = [
            (x - 1, y, z), (x + 1, y, z),
            (x, y - 1, z), (x, y + 1, z),
        ]
        random.shuffle(lateral)
        for nx, ny, nz in lateral:
            if world.in_bounds(nx, ny, nz) and world.get_cell(nx, ny, nz) == _AIR:
                world.set_cell(nx, ny, nz, _WATER)
                world.set_cell(x, y, z, _AIR)
                return True

        return False

    # ------------------------------------------------------------------
    # Sand falling
    # ------------------------------------------------------------------

    def _fall_sand(self, x: int, y: int, z: int) -> bool:
        world = self.world
        below = z - 1
        if below < 0:
            return False
        cell_below = world.get_cell(x, y, below)
        if cell_below == _AIR or cell_below == _WATER:
            # Swap sand with the cell below
            world.set_cell(x, y, below, _SAND)
            world.set_cell(x, y, z, cell_below)
            return True
        return False

    # ------------------------------------------------------------------
    # Lava spreading + ice conversion
    # ------------------------------------------------------------------

    def _spread_lava(self, x: int, y: int, z: int) -> bool:
        world = self.world
        changed = False

        # Convert adjacent ICE to WATER
        neighbors_6 = [
            (x - 1, y, z), (x + 1, y, z),
            (x, y - 1, z), (x, y + 1, z),
            (x, y, z - 1), (x, y, z + 1),
        ]
        for nx, ny, nz in neighbors_6:
            if world.in_bounds(nx, ny, nz) and world.get_cell(nx, ny, nz) == _ICE:
                world.set_cell(nx, ny, nz, _WATER)
                changed = True

        # Try to fall down
        below = z - 1
        if below >= 0 and world.get_cell(x, y, below) == _AIR:
            world.set_cell(x, y, below, _LAVA)
            world.set_cell(x, y, z, _AIR)
            return True

        # Spread laterally into AIR
        lateral = [
            (x - 1, y, z), (x + 1, y, z),
            (x, y - 1, z), (x, y + 1, z),
        ]
        random.shuffle(lateral)
        for nx, ny, nz in lateral:
            if world.in_bounds(nx, ny, nz) and world.get_cell(nx, ny, nz) == _AIR:
                world.set_cell(nx, ny, nz, _LAVA)
                world.set_cell(x, y, z, _AIR)
                return True

        return changed
