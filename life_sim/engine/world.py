import math
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
    #
    #  z 0..14  : STONE bedrock
    #  z 15..18 : underground mix  (50% STONE, 44% SAND, 5% SOIL pockets, 1% WOOD veins)
    #  z 19..20 : thin topsoil     (2 layers — scarce surface calories)
    #  z 21+    : AIR              (organisms live here)
    BEDROCK_TOP    = 14
    UNDERGROUND_TOP = 18
    SOIL_TOP       = 20   # surface; organisms spawn at z=21

    WATER_POOL_COUNT = 40
    WATER_POOL_RADIUS = 3
    OUTCROP_COUNT = 20
    GROVE_COUNT = 4        # dense tree groves on the surface
    GROVE_RADIUS = 12      # cells radius per grove

    # Biome block size in chunks (4 chunks = 64 world cells per biome zone)
    BIOME_BLOCK = 4

    def generate_default(self, world: World):
        """Generate terrain for the entire world."""
        self._biome_map = self._generate_biome_map()
        self._fill_layers(world)
        self._add_water_pools(world)
        self._add_stone_outcroppings(world)
        self._add_lakes(world)
        self._add_rivers(world)
        self._add_groves(world)

    def _generate_biome_map(self) -> np.ndarray:
        """Generate a coarse biome grid (one type per BIOME_BLOCK x BIOME_BLOCK chunks).

        Biome types:
          0 = rocky     : exposed stone with sparse soil pockets
          1 = grassy    : soil-dominant, the "grass" biome (~25% of surface)
          2 = sand_dune : 90% sand with soil inclusions — rewards digger evolution
          3 = barren    : mixed stone/sand/soil wasteland
        """
        bw = (CHUNKS_W + self.BIOME_BLOCK - 1) // self.BIOME_BLOCK
        bh = (CHUNKS_H + self.BIOME_BLOCK - 1) // self.BIOME_BLOCK
        # Probabilities: rocky 30%, grassy 25%, sand_dune 25%, barren 20%
        return np.random.choice(4, size=(bw, bh), p=[0.30, 0.25, 0.25, 0.20])

    # ------------------------------------------------------------------
    # Layer filling
    # ------------------------------------------------------------------

    def _fill_layers(self, world: World):
        """Fill the world layer by layer, operating chunk-by-chunk for speed."""
        for cz in range(CHUNKS_D):
            z_base = cz * CHUNK_SIZE
            if z_base > self.SOIL_TOP:
                continue  # entirely AIR — skip chunk creation
            for cx in range(CHUNKS_W):
                for cy in range(CHUNKS_H):
                    chunk = world.get_chunk(cx, cy, cz)
                    self._fill_chunk_layers(chunk, z_base, cx, cy)

    def _fill_chunk_layers(self, chunk: Chunk, z_base: int, cx: int = 0, cy: int = 0):
        """Fill a single chunk according to layer rules.

        cx/cy are the chunk grid coordinates; used to look up the surface biome.
        """
        cells = chunk.cells  # shape (16,16,16), axis order: x, y, z
        _STONE = int(CellType.STONE)
        _SAND  = int(CellType.SAND)
        _SOIL  = int(CellType.SOIL)
        _WOOD  = int(CellType.WOOD)

        # Look up biome for this chunk's position
        bx = min(cx // self.BIOME_BLOCK, self._biome_map.shape[0] - 1)
        by = min(cy // self.BIOME_BLOCK, self._biome_map.shape[1] - 1)
        biome = int(self._biome_map[bx, by])

        for lz in range(CHUNK_SIZE):
            z = z_base + lz
            if z > self.SOIL_TOP:
                # AIR — leave as zeros
                continue
            elif z <= self.BEDROCK_TOP:
                # Solid bedrock
                cells[:, :, lz] = _STONE
            elif z <= self.UNDERGROUND_TOP:
                # Underground mix: 50% stone, 44% sand, 5% soil, 1% wood
                r = np.random.random((CHUNK_SIZE, CHUNK_SIZE))
                layer = np.full((CHUNK_SIZE, CHUNK_SIZE), _STONE, dtype=np.uint8)
                layer[r >= 0.50]              = _SAND
                layer[(r >= 0.94) & (r < 0.99)] = _SOIL
                layer[r >= 0.99]              = _WOOD
                cells[:, :, lz] = layer
            elif z == self.SOIL_TOP - 1:
                # z=19: sub-surface layer — mostly soil, biome influences composition
                r = np.random.random((CHUNK_SIZE, CHUNK_SIZE))
                layer = np.full((CHUNK_SIZE, CHUNK_SIZE), _SOIL, dtype=np.uint8)
                layer[r < 0.25] = _STONE
                if biome == 2:  # sand_dune biome has sandy subsurface too
                    layer[(r >= 0.50) & (r < 0.80)] = _SAND
                cells[:, :, lz] = layer
            else:
                # z=20: walking surface — biome-based variety
                # 0=rocky  1=grassy  2=sand_dune  3=barren
                r = np.random.random((CHUNK_SIZE, CHUNK_SIZE))
                if biome == 0:   # rocky: mostly exposed stone, sparse soil pockets
                    layer = np.full((CHUNK_SIZE, CHUNK_SIZE), _STONE, dtype=np.uint8)
                    layer[r < 0.12] = _SOIL
                elif biome == 1: # grassy: soil-dominant with some stone breaks
                    layer = np.full((CHUNK_SIZE, CHUNK_SIZE), _SOIL, dtype=np.uint8)
                    layer[r < 0.28] = _STONE
                elif biome == 2: # sand_dune: 90% sand, 10% soil (digger food)
                    layer = np.full((CHUNK_SIZE, CHUNK_SIZE), _SAND, dtype=np.uint8)
                    layer[r < 0.10] = _SOIL
                else:            # barren: stone/sand/soil wasteland
                    layer = np.full((CHUNK_SIZE, CHUNK_SIZE), _STONE, dtype=np.uint8)
                    layer[r < 0.35] = _SOIL
                    layer[(r >= 0.65) & (r < 0.80)] = _SAND
                cells[:, :, lz] = layer
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
    # Lakes (multiple large bodies of water)
    # ------------------------------------------------------------------

    def _add_lakes(self, world: World):
        """Place 3 large lakes spread across the world."""
        # Fixed approximate positions: one per third of the map
        positions = [
            (WORLD_W // 4 + random.randint(-30, 30),
             WORLD_H // 4 + random.randint(-30, 30)),
            (WORLD_W // 2 + random.randint(-30, 30),
             WORLD_H // 2 + random.randint(-30, 30)),
            (3 * WORLD_W // 4 + random.randint(-30, 30),
             3 * WORLD_H // 4 + random.randint(-30, 30)),
        ]
        self._lake_centers = []  # store for river generation
        surface_z = self.SOIL_TOP + 1  # z=21 — water sits on topsoil

        for cx, cy in positions:
            radius = random.randint(30, 50)
            self._lake_centers.append((cx, cy))
            r2 = radius * radius
            lake_cells = []
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if dx * dx + dy * dy <= r2:
                        x, y = cx + dx, cy + dy
                        if not world.in_bounds(x, y, surface_z):
                            continue
                        world.set_cell(x, y, surface_z, int(CellType.WATER))
                        # 2 cells deep — lower layer is water (kelp replaces some of these)
                        if world.in_bounds(x, y, surface_z - 1):
                            world.set_cell(x, y, surface_z - 1, int(CellType.WATER))
                        lake_cells.append((x, y))

            # Scatter aquatic vegetation (kelp) at z=surface_z-1 (lower water layer).
            # Kelp is WOOD placed inside the water column; organisms at z=surface_z
            # are adjacent (dz=-1) and can eat it — primary food source for gill organisms.
            # ~15% density, clustered in patches for realism.
            for x, y in lake_cells:
                if random.random() < 0.15:
                    world.set_cell(x, y, surface_z - 1, int(CellType.WOOD))

    # ------------------------------------------------------------------
    # Rivers
    # ------------------------------------------------------------------

    def _add_rivers(self, world: World):
        """Carve rivers connecting the lakes with winding paths."""
        if not hasattr(self, '_lake_centers') or len(self._lake_centers) < 2:
            return
        surface_z = self.SOIL_TOP + 1  # z=21

        # Connect lake[0]→lake[1] and lake[1]→lake[2]
        pairs = [(0, 1), (1, 2)]
        for i, j in pairs:
            x0, y0 = self._lake_centers[i]
            x1, y1 = self._lake_centers[j]
            self._carve_river(world, x0, y0, x1, y1, surface_z)

    def _carve_river(self, world: World, x0: int, y0: int, x1: int, y1: int, z: int):
        """Carve a winding river from (x0,y0) to (x1,y1) at altitude z.

        Uses a random walk biased toward the destination.
        River width: 2-4 cells.
        """
        x, y = x0, y0
        width = random.randint(2, 4)
        max_steps = int(math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2) * 2.5)

        for _ in range(max_steps):
            # Place water in a circle of `width` cells around (x, y)
            for dx in range(-width, width + 1):
                for dy in range(-width, width + 1):
                    if dx * dx + dy * dy <= width * width:
                        nx, ny = x + dx, y + dy
                        if world.in_bounds(nx, ny, z):
                            world.set_cell(nx, ny, z, int(CellType.WATER))
                        if world.in_bounds(nx, ny, z - 1):
                            world.set_cell(nx, ny, z - 1, int(CellType.WATER))

            # Step toward destination with some random wandering
            if abs(x1 - x) < 3 and abs(y1 - y) < 3:
                break  # close enough

            # 70% bias toward target, 30% random wander
            if random.random() < 0.7:
                dx = 1 if x1 > x else (-1 if x1 < x else 0)
                dy = 1 if y1 > y else (-1 if y1 < y else 0)
            else:
                dx = random.choice([-1, 0, 1])
                dy = random.choice([-1, 0, 1])

            x = max(0, min(WORLD_W - 1, x + dx))
            y = max(0, min(WORLD_H - 1, y + dy))

    # ------------------------------------------------------------------
    # Wood patches (surface food)
    # ------------------------------------------------------------------

    def _add_groves(self, world: World):
        """Place a small number of dense tree groves on the soil surface.

        Groves are the primary surface food source. With only GROVE_COUNT groves
        and thin topsoil (2 layers, calorie_value=1), food is scarce enough to
        keep populations in check while rewarding organisms that find the groves.
        """
        surface_z = self.SOIL_TOP  # z=20 is topsoil surface; trees go at z=21+
        tree_base = surface_z + 1  # z=21

        for _ in range(self.GROVE_COUNT):
            gx = random.randint(self.GROVE_RADIUS, WORLD_W - self.GROVE_RADIUS - 1)
            gy = random.randint(self.GROVE_RADIUS, WORLD_H - self.GROVE_RADIUS - 1)
            r = self.GROVE_RADIUS

            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    dist2 = dx * dx + dy * dy
                    if dist2 > r * r:
                        continue
                    x, y = gx + dx, gy + dy
                    # Tree density falls off from grove centre
                    edge_ratio = dist2 / (r * r)
                    if random.random() > (1.0 - edge_ratio * 0.7):
                        continue  # sparse at edges, dense at centre
                    # Tree height: 1–4 cells, taller near centre
                    max_h = max(1, int(4 * (1.0 - edge_ratio)))
                    height = random.randint(1, max_h)
                    for dz in range(height):
                        z = tree_base + dz
                        if z < WORLD_D and world.get_cell(x, y, z) == int(CellType.AIR):
                            world.set_cell(x, y, z, int(CellType.WOOD))

    # ------------------------------------------------------------------
    # Stone outcroppings
    # ------------------------------------------------------------------

    def _add_stone_outcroppings(self, world: World):
        """Scatter small stone blobs just above the soil surface."""
        base_z = self.SOIL_TOP + 1  # z=21

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
