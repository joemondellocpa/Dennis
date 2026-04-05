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

        # 1. Direct fall if cell below is air or water
        if below >= 0:
            cell_below = world.get_cell(x, y, below)
            if cell_below == _AIR or cell_below == _WATER:
                world.set_cell(x, y, below, _SAND)
                world.set_cell(x, y, z, cell_below)
                return True

        # 2. Angle-of-repose slide: find the lowest reachable adjacent position.
        # Sand slides into a lateral neighbour and falls as far as possible,
        # but will not build a sand stack taller than 2.
        best_nx, best_ny, best_nz = None, None, z  # must be strictly lower than z

        laterals = [(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)]
        random.shuffle(laterals)

        for nx, ny in laterals:
            if not world.in_bounds(nx, ny, z):
                continue
            # Entry cell at same level must be passable to slide into
            if world.get_cell(nx, ny, z) not in (_AIR, _WATER):
                continue

            # Descend the adjacent column to find the lowest air/water cell
            land_z = z
            for cz in range(z - 1, -1, -1):
                ct = world.get_cell(nx, ny, cz)
                if ct == _AIR or ct == _WATER:
                    land_z = cz
                else:
                    break

            if land_z >= z:
                continue  # no lower position found

            # Enforce max stack height of 2 at destination
            dest_stack = 0
            cz = land_z - 1
            while cz >= 0 and world.get_cell(nx, ny, cz) == _SAND:
                dest_stack += 1
                cz -= 1
            if dest_stack >= 2:
                continue  # would create a stack of 3+

            if land_z < best_nz:
                best_nz = land_z
                best_nx, best_ny = nx, ny

        if best_nx is not None:
            world.set_cell(best_nx, best_ny, best_nz, _SAND)
            world.set_cell(x, y, z, _AIR)
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
