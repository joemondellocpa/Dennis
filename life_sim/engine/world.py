import numpy as np
import random

from .cells import CellType

WORLD_W, WORLD_H, WORLD_D = 1000, 1000, 100
CHUNK_SIZE = 16

# Number of chunks along each axis (ceiling division)
CHUNKS_W = (WORLD_W + CHUNK_SIZE - 1) // CHUNK_SIZE
CHUNKS_H = (WORLD_H + CHUNK_SIZE - 1) // CHUNK_SIZE
CHUNKS_D = (WORLD_D + CHUNK_SIZE - 1) // CHUNK_SIZE


class Chunk:
    __slots__ = ['cells', 'dirty']

    def __init__(self):
        self.cells = np.zeros((CHUNK_SIZE, CHUNK_SIZE, CHUNK_SIZE), dtype=np.uint8)
        self.dirty = True


class World:
    __slots__ = ['chunks', 'active_chunks']

    def __init__(self):
        self.chunks: dict[tuple, Chunk] = {}
        self.active_chunks: set[tuple] = set()

    # ------------------------------------------------------------------
    # Chunk access
    # ------------------------------------------------------------------

    def get_chunk_key(self, x: int, y: int, z: int) -> tuple:
        """Convert world coordinates to chunk key."""
        return (x // CHUNK_SIZE, y // CHUNK_SIZE, z // CHUNK_SIZE)

    def get_chunk(self, cx: int, cy: int, cz: int) -> Chunk:
        """Return chunk at chunk coords, creating it if it does not exist."""
        key = (cx, cy, cz)
        if key not in self.chunks:
            self.chunks[key] = Chunk()
        return self.chunks[key]

    def mark_active(self, cx: int, cy: int, cz: int):
        """Mark a chunk as active (kept in memory)."""
        self.active_chunks.add((cx, cy, cz))

    # ------------------------------------------------------------------
    # Cell access (world coordinates)
    # ------------------------------------------------------------------

    def in_bounds(self, x: int, y: int, z: int) -> bool:
        return 0 <= x < WORLD_W and 0 <= y < WORLD_H and 0 <= z < WORLD_D

    def get_cell(self, x: int, y: int, z: int) -> int:
        """Return cell type at world coords. Returns AIR for out-of-bounds."""
        if not self.in_bounds(x, y, z):
            return int(CellType.AIR)
        key = (x // CHUNK_SIZE, y // CHUNK_SIZE, z // CHUNK_SIZE)
        if key not in self.chunks:
            return int(CellType.AIR)
        chunk = self.chunks[key]
        lx = x % CHUNK_SIZE
        ly = y % CHUNK_SIZE
        lz = z % CHUNK_SIZE
        return int(chunk.cells[lx, ly, lz])

    def set_cell(self, x: int, y: int, z: int, cell_type: int):
        """Set cell type at world coords."""
        if not self.in_bounds(x, y, z):
            return
        chunk = self.get_chunk(x // CHUNK_SIZE, y // CHUNK_SIZE, z // CHUNK_SIZE)
        lx = x % CHUNK_SIZE
        ly = y % CHUNK_SIZE
        lz = z % CHUNK_SIZE
        chunk.cells[lx, ly, lz] = cell_type
        chunk.dirty = True

    # ------------------------------------------------------------------
    # Neighbors
    # ------------------------------------------------------------------

    def get_neighbors(self, x: int, y: int, z: int) -> list:
        """Return 6 face-adjacent neighbors as list of (nx, ny, nz, cell_type)."""
        offsets = [
            (-1, 0, 0), (1, 0, 0),
            (0, -1, 0), (0, 1, 0),
            (0, 0, -1), (0, 0, 1),
        ]
        result = []
        for dx, dy, dz in offsets:
            nx, ny, nz = x + dx, y + dy, z + dz
            result.append((nx, ny, nz, self.get_cell(nx, ny, nz)))
        return result

    # ------------------------------------------------------------------
    # Serialization stub
    # ------------------------------------------------------------------

    def serialize_chunk(self, cx: int, cy: int, cz: int):
        """Serialize a chunk to disk (stub for MVP)."""
        pass

    def deserialize_chunk(self, cx: int, cy: int, cz: int):
        """Deserialize a chunk from disk (stub for MVP)."""
        pass


# ---------------------------------------------------------------------------
# World generation
# ---------------------------------------------------------------------------

class WorldGenerator:
    """Generates a default world layout using numpy bulk operations."""

    # Layer boundaries (z indices, inclusive)
    STONE_TOP = 10          # z 0..10  -> STONE
    SOIL_TOP = 20           # z 11..20 -> SOIL
    SOIL_POCKET_TOP = 25    # z 21..25 -> SOIL with air pockets
    # z 26+                 -> AIR

    AIR_POCKET_PROB = 0.08  # probability a cell in the pocket zone becomes AIR
    WATER_POOL_COUNT = 40   # number of water pools to scatter
    WATER_POOL_RADIUS = 3   # radius of each water pool (in cells)
    OUTCROP_COUNT = 30      # number of stone outcroppings

    def generate_default(self, world: World):
        """Generate terrain for the entire world."""
        self._fill_layers(world)
        self._add_water_pools(world)
        self._add_stone_outcroppings(world)

    # ------------------------------------------------------------------
    # Layer filling
    # ------------------------------------------------------------------

    def _fill_layers(self, world: World):
        """Fill the world layer by layer, operating chunk-by-chunk for speed."""
        for cz in range(CHUNKS_D):
            z_base = cz * CHUNK_SIZE

            # Entirely AIR slab — don't create chunks
            if z_base > self.SOIL_POCKET_TOP:
                continue

            for cx in range(CHUNKS_W):
                for cy in range(CHUNKS_H):
                    chunk = world.get_chunk(cx, cy, cz)
                    self._fill_chunk_layers(chunk, z_base)

    def _fill_chunk_layers(self, chunk: Chunk, z_base: int):
        """Fill a single chunk according to layer rules."""
        cells = chunk.cells  # shape (16,16,16), axis order: x, y, z
        for lz in range(CHUNK_SIZE):
            z = z_base + lz
            if z > self.SOIL_POCKET_TOP:
                # AIR (already zeros)
                continue
            elif z <= self.STONE_TOP:
                cells[:, :, lz] = int(CellType.STONE)
            elif z <= self.SOIL_TOP:
                cells[:, :, lz] = int(CellType.SOIL)
            else:
                # z in [SOIL_TOP+1 .. SOIL_POCKET_TOP]: soil with air pockets
                cells[:, :, lz] = int(CellType.SOIL)
                mask = np.random.random((CHUNK_SIZE, CHUNK_SIZE)) < self.AIR_POCKET_PROB
                cells[:, :, lz][mask] = int(CellType.AIR)
        chunk.dirty = True

    # ------------------------------------------------------------------
    # Water pools
    # ------------------------------------------------------------------

    def _add_water_pools(self, world: World):
        """Scatter small water pools on the soil surface (z = SOIL_TOP + 1)."""
        surface_z = self.SOIL_TOP + 1
        r = self.WATER_POOL_RADIUS

        for _ in range(self.WATER_POOL_COUNT):
            cx_center = random.randint(r, WORLD_W - r - 1)
            cy_center = random.randint(r, WORLD_H - r - 1)

            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if dx * dx + dy * dy <= r * r:
                        x = cx_center + dx
                        y = cy_center + dy
                        if world.get_cell(x, y, surface_z) == int(CellType.AIR):
                            world.set_cell(x, y, surface_z, int(CellType.WATER))

    # ------------------------------------------------------------------
    # Stone outcroppings
    # ------------------------------------------------------------------

    def _add_stone_outcroppings(self, world: World):
        """Scatter small stone blobs just above the soil layer."""
        base_z = self.SOIL_TOP + 1

        for _ in range(self.OUTCROP_COUNT):
            ox = random.randint(1, WORLD_W - 2)
            oy = random.randint(1, WORLD_H - 2)
            height = random.randint(1, 4)
            radius = random.randint(1, 3)

            for dz in range(height):
                z = base_z + dz
                if z >= WORLD_D:
                    break
                for dx in range(-radius, radius + 1):
                    for dy in range(-radius, radius + 1):
                        if dx * dx + dy * dy <= radius * radius:
                            x = ox + dx
                            y = oy + dy
                            if world.in_bounds(x, y, z):
                                world.set_cell(x, y, z, int(CellType.STONE))
